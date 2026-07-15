from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx

from open_novel import __version__
from open_novel.core.workspace_storage import default_workspace_db_path

DEFAULT_UPDATE_REPOSITORY = "oneXixi-666/open-novel"


class UpdateCheckError(RuntimeError):
    """Raised when the latest release cannot be checked reliably."""


class UpdatePreparationError(RuntimeError):
    """Raised when an update package cannot be prepared safely."""


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str


class UpdateService:
    def __init__(
        self,
        *,
        current_version: str = __version__,
        repository: str | None = None,
        api_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.current_version = self._normalize_version(current_version)
        self.repository = (
            repository
            or os.environ.get("OPEN_NOVEL_UPDATE_REPOSITORY", "").strip()
            or DEFAULT_UPDATE_REPOSITORY
        )
        self.api_url = (
            api_url
            or os.environ.get("OPEN_NOVEL_UPDATE_API_URL", "").strip()
            or f"https://api.github.com/repos/{self.repository}/releases/latest"
        )
        self.client = client

    def check(self) -> dict[str, Any]:
        try:
            payload = self._fetch_release()
            return self._release_payload(payload)
        except UpdateCheckError as exc:
            return {
                "checkSucceeded": False,
                "currentVersion": self.current_version,
                "latestVersion": "",
                "updateAvailable": False,
                "downloadReady": False,
                "status": "检查失败",
                "message": str(exc),
                "releaseName": "",
                "releaseNotes": "",
                "publishedAt": "",
                "releaseUrl": "",
                "packageUrl": "",
                "checksumUrl": "",
            }

    def prepare_latest(
        self,
        *,
        update_root: Path | None = None,
        database_path: Path | None = None,
        install_root: Path | None = None,
    ) -> dict[str, Any]:
        release = self.check()
        if not release["checkSucceeded"]:
            raise UpdatePreparationError(str(release["message"]))
        if not release["updateAvailable"]:
            raise UpdatePreparationError("当前版本已是最新版本，无需准备更新。")
        if not release["downloadReady"]:
            raise UpdatePreparationError("新版本缺少发布包或 SHA-256 校验文件。")

        target_version = str(release["latestVersion"])
        configured_update_root = os.environ.get("OPEN_NOVEL_UPDATE_DIR", "").strip()
        root = (
            update_root
            or (Path(configured_update_root) if configured_update_root else None)
            or Path.cwd() / ".open-novel" / "updates"
        ).expanduser().resolve()
        target_dir = root / target_version
        target_dir.mkdir(parents=True, exist_ok=True)
        package_path = target_dir / f"open-novel-{target_version}.zip"
        checksum_path = target_dir / f"{package_path.name}.sha256"
        plan_path = target_dir / "update-plan.json"

        package_bytes = self._download(str(release["packageUrl"]))
        checksum_bytes = self._download(str(release["checksumUrl"]))
        expected_checksum = self._parse_checksum(checksum_bytes, package_path.name)
        actual_checksum = sha256(package_bytes).hexdigest()
        if actual_checksum != expected_checksum:
            package_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)
            raise UpdatePreparationError("更新包校验失败，已停止更新准备。")

        package_path.write_bytes(package_bytes)
        checksum_path.write_text(f"{actual_checksum}  {package_path.name}\n", encoding="ascii")
        db_path = (database_path or default_workspace_db_path()).expanduser().resolve()
        database_backup_path = self._backup_database(db_path, target_dir)
        plan = {
            "schemaVersion": 1,
            "status": "prepared",
            "createdAt": datetime.now(UTC).isoformat(),
            "currentVersion": self.current_version,
            "targetVersion": target_version,
            "installRoot": str((install_root or Path.cwd()).expanduser().resolve()),
            "packagePath": str(package_path),
            "packageSha256": actual_checksum,
            "databasePath": str(db_path),
            "databaseBackupPath": str(database_backup_path) if database_backup_path else "",
        }
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {
            "status": "更新包已准备",
            "message": "更新包已下载并通过校验，数据库备份和外部更新计划已生成。",
            "currentVersion": self.current_version,
            "targetVersion": target_version,
            "planPath": str(plan_path),
            "packagePath": str(package_path),
            "databaseBackupPath": str(database_backup_path) if database_backup_path else "",
            "restartRequired": True,
        }

    def _fetch_release(self) -> dict[str, Any]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"open-novel/{self.current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            if self.client is not None:
                response = self.client.get(self.api_url, headers=headers)
            else:
                with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                    response = client.get(self.api_url, headers=headers)
        except httpx.HTTPError as exc:
            raise UpdateCheckError("暂时无法连接版本服务器，请稍后重试。") from exc
        if response.status_code in {403, 429} and self.api_url.startswith(
            "https://api.github.com/repos/"
        ):
            return self._fetch_release_from_github_redirect(headers)
        if response.status_code == 404:
            raise UpdateCheckError("当前尚未发布可供更新的正式版本。")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpdateCheckError(
                f"版本服务器返回异常状态（{response.status_code}）。"
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpdateCheckError("版本服务器返回了无法识别的数据。") from exc
        if not isinstance(payload, dict):
            raise UpdateCheckError("版本服务器返回了无法识别的数据。")
        return payload

    def _fetch_release_from_github_redirect(
        self,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        latest_url = f"https://github.com/{self.repository}/releases/latest"
        try:
            if self.client is not None:
                response = self.client.get(latest_url, headers=headers, follow_redirects=True)
            else:
                with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                    response = client.get(latest_url, headers=headers)
        except httpx.HTTPError as exc:
            raise UpdateCheckError("暂时无法连接版本服务器，请稍后重试。") from exc
        if response.status_code == 404:
            raise UpdateCheckError("当前尚未发布可供更新的正式版本。")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpdateCheckError(
                f"版本服务器返回异常状态（{response.status_code}）。"
            ) from exc
        marker = "/releases/tag/"
        final_url = str(response.url)
        if marker not in final_url:
            raise UpdateCheckError("版本服务器未返回可识别的正式版本。")
        tag_name = final_url.split(marker, 1)[1].split("?", 1)[0].strip("/")
        try:
            version = self._normalize_version(tag_name)
        except ValueError as exc:
            raise UpdateCheckError("最新发布版本号格式不正确。") from exc
        asset_root = f"https://github.com/{self.repository}/releases/download/{tag_name}"
        package_name = f"open-novel-{version}.zip"
        return {
            "tag_name": tag_name,
            "name": f"Open Novel {version}",
            "body": "",
            "published_at": "",
            "html_url": final_url,
            "assets": [
                {
                    "name": package_name,
                    "browser_download_url": f"{asset_root}/{package_name}",
                },
                {
                    "name": f"{package_name}.sha256",
                    "browser_download_url": f"{asset_root}/{package_name}.sha256",
                },
            ],
        }

    def _download(self, url: str) -> bytes:
        try:
            if self.client is not None:
                response = self.client.get(url, follow_redirects=True)
            else:
                with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                    response = client.get(url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpdatePreparationError("更新包下载失败，请稍后重试。") from exc
        return response.content

    def _parse_checksum(self, content: bytes, package_name: str) -> str:
        try:
            lines = content.decode("utf-8").splitlines()
        except UnicodeDecodeError as exc:
            raise UpdatePreparationError("更新包校验文件无法识别。") from exc
        candidates: list[tuple[str, str]] = []
        for line in lines:
            value = line.strip()
            if not value:
                continue
            parts = value.replace("*", " ").split()
            checksum = parts[0].lower()
            filename = parts[-1] if len(parts) > 1 else ""
            if re.fullmatch(r"[0-9a-f]{64}", checksum):
                candidates.append((checksum, filename))
        if not candidates:
            raise UpdatePreparationError("更新包校验文件不包含有效的 SHA-256。")
        matched = next(
            (checksum for checksum, filename in candidates if filename == package_name),
            candidates[0][0] if len(candidates) == 1 else "",
        )
        if not matched:
            raise UpdatePreparationError("更新包校验文件中缺少当前发布包。")
        return matched

    def _backup_database(self, db_path: Path, target_dir: Path) -> Path | None:
        if not db_path.is_file():
            return None
        backup_path = target_dir / "workspace-before-update.sqlite3"
        with sqlite3.connect(db_path) as source:
            with sqlite3.connect(backup_path) as target:
                source.backup(target)
        return backup_path

    def _release_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_version = str(payload.get("tag_name") or payload.get("name") or "").strip()
        try:
            latest_version = self._normalize_version(raw_version)
            update_available = self._version_key(latest_version) > self._version_key(
                self.current_version
            )
        except ValueError as exc:
            raise UpdateCheckError("最新发布版本号格式不正确。") from exc

        assets = self._assets(payload.get("assets"))
        package = self._find_package_asset(assets, latest_version)
        checksum = self._find_checksum_asset(assets, package)
        download_ready = bool(package and checksum)
        if update_available and download_ready:
            status = "发现新版本"
            message = f"版本 {latest_version} 已发布，可以下载安装。"
        elif update_available:
            status = "发现新版本"
            message = "已发现新版本，但发布包或校验文件尚未准备完成。"
        else:
            status = "已是最新版本"
            message = f"当前版本 {self.current_version} 已是最新版本。"
        return {
            "checkSucceeded": True,
            "currentVersion": self.current_version,
            "latestVersion": latest_version,
            "updateAvailable": update_available,
            "downloadReady": download_ready,
            "status": status,
            "message": message,
            "releaseName": str(payload.get("name") or raw_version),
            "releaseNotes": str(payload.get("body") or ""),
            "publishedAt": str(payload.get("published_at") or ""),
            "releaseUrl": str(payload.get("html_url") or ""),
            "packageUrl": package.download_url if package else "",
            "checksumUrl": checksum.download_url if checksum else "",
        }

    def _assets(self, raw_assets: Any) -> list[ReleaseAsset]:
        if not isinstance(raw_assets, list):
            return []
        return [
            ReleaseAsset(
                name=str(item.get("name") or ""),
                download_url=str(item.get("browser_download_url") or ""),
            )
            for item in raw_assets
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and str(item.get("browser_download_url") or "").strip()
        ]

    def _find_package_asset(
        self,
        assets: list[ReleaseAsset],
        version: str,
    ) -> ReleaseAsset | None:
        expected_names = {
            f"open-novel-{version}.zip",
            f"open-novel-v{version}.zip",
        }
        return next(
            (asset for asset in assets if asset.name.lower() in expected_names),
            next(
                (
                    asset
                    for asset in assets
                    if asset.name.lower().startswith("open-novel-")
                    and asset.name.lower().endswith(".zip")
                ),
                None,
            ),
        )

    def _find_checksum_asset(
        self,
        assets: list[ReleaseAsset],
        package: ReleaseAsset | None,
    ) -> ReleaseAsset | None:
        if package is None:
            return None
        expected_names = {
            f"{package.name}.sha256",
            f"{package.name.removesuffix('.zip')}.sha256",
            "sha256sums.txt",
        }
        return next(
            (asset for asset in assets if asset.name.lower() in expected_names),
            None,
        )

    def _normalize_version(self, version: str) -> str:
        normalized = version.strip()
        if normalized.lower().startswith("v"):
            normalized = normalized[1:]
        if not normalized or not re.fullmatch(
            r"\d+(?:\.\d+){0,3}(?:-[0-9A-Za-z.-]+)?",
            normalized,
        ):
            raise ValueError(f"invalid version: {version}")
        return normalized

    def _version_key(self, version: str) -> tuple[tuple[int, ...], int, tuple[str, ...]]:
        base, separator, prerelease = version.partition("-")
        numbers = tuple(int(part) for part in base.split("."))
        padded = numbers + (0,) * (4 - len(numbers))
        prerelease_parts = tuple(prerelease.split(".")) if separator else ()
        return padded, 0 if prerelease_parts else 1, prerelease_parts
