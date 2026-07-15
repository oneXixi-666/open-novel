from __future__ import annotations

import json
import os
import shutil
import time
import zipfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any


class UpdateInstallError(RuntimeError):
    """Raised when a prepared update cannot be installed or rolled back safely."""


class UpdateInstaller:
    max_files = 20_000
    max_uncompressed_bytes = 500 * 1024 * 1024
    protected_roots = {".git", ".open-novel"}

    def apply(self, plan_path: Path) -> dict[str, Any]:
        resolved_plan = plan_path.expanduser().resolve()
        plan = self._load_plan(resolved_plan)
        if plan.get("status") != "prepared":
            raise UpdateInstallError("更新计划当前不是可执行状态。")
        install_root = Path(str(plan.get("installRoot") or "")).expanduser().resolve()
        package_path = Path(str(plan.get("packagePath") or "")).expanduser().resolve()
        if not install_root.is_dir():
            raise UpdateInstallError("更新计划中的程序目录不存在。")
        if not package_path.is_file():
            raise UpdateInstallError("更新计划中的发布包不存在。")
        expected_checksum = str(plan.get("packageSha256") or "").strip().lower()
        actual_checksum = sha256(package_path.read_bytes()).hexdigest()
        if actual_checksum != expected_checksum:
            raise UpdateInstallError("更新包摘要与更新计划不一致。")

        backup_root = resolved_plan.parent / "application-before-update"
        if backup_root.exists():
            raise UpdateInstallError("更新目录中已存在程序备份，请先处理上一次更新。")
        backup_root.mkdir(parents=True)
        created_files: list[str] = []
        replaced_files: list[str] = []
        try:
            with zipfile.ZipFile(package_path) as archive:
                manifest, prefix = self._read_manifest(archive)
                files = self._validated_files(archive, manifest, prefix)
                for relative_path in files:
                    source_name = f"{prefix}/{relative_path}"
                    destination = self._safe_destination(install_root, relative_path)
                    backup_path = backup_root / relative_path
                    if destination.is_file():
                        backup_path.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(destination, backup_path)
                        replaced_files.append(relative_path)
                    else:
                        created_files.append(relative_path)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_name(f".{destination.name}.open-novel-update")
                    try:
                        temporary.write_bytes(archive.read(source_name))
                        os.replace(temporary, destination)
                    finally:
                        temporary.unlink(missing_ok=True)
        except Exception as exc:
            self._restore_files(
                install_root=install_root,
                backup_root=backup_root,
                replaced_files=replaced_files,
                created_files=created_files,
            )
            shutil.rmtree(backup_root, ignore_errors=True)
            if isinstance(exc, UpdateInstallError):
                raise
            raise UpdateInstallError("应用更新失败，已恢复更新前程序文件。") from exc

        plan.update(
            {
                "status": "applied",
                "applicationBackupPath": str(backup_root),
                "replacedFiles": replaced_files,
                "createdFiles": created_files,
            }
        )
        self._write_plan(resolved_plan, plan)
        return {
            "status": "更新文件已应用",
            "message": "程序文件已替换，数据库未修改。请由外部进程重启服务并执行健康检查。",
            "targetVersion": str(plan.get("targetVersion") or ""),
            "replacedFileCount": len(replaced_files),
            "createdFileCount": len(created_files),
            "applicationBackupPath": str(backup_root),
            "restartRequired": True,
        }

    def rollback(self, plan_path: Path) -> dict[str, Any]:
        resolved_plan = plan_path.expanduser().resolve()
        plan = self._load_plan(resolved_plan)
        if plan.get("status") != "applied":
            raise UpdateInstallError("只有已应用的更新计划可以回滚。")
        install_root = Path(str(plan.get("installRoot") or "")).expanduser().resolve()
        backup_root = Path(str(plan.get("applicationBackupPath") or "")).expanduser().resolve()
        if not install_root.is_dir() or not backup_root.is_dir():
            raise UpdateInstallError("更新回滚所需的程序目录或备份不存在。")
        replaced_files = self._string_list(plan.get("replacedFiles"))
        created_files = self._string_list(plan.get("createdFiles"))
        self._restore_files(
            install_root=install_root,
            backup_root=backup_root,
            replaced_files=replaced_files,
            created_files=created_files,
        )
        plan["status"] = "rolled_back"
        self._write_plan(resolved_plan, plan)
        return {
            "status": "更新已回滚",
            "message": "程序文件已恢复到更新前状态，数据库备份保持不变。",
            "restoredFileCount": len(replaced_files),
            "removedFileCount": len(created_files),
        }

    def wait_for_process_exit(self, pid: int, timeout_seconds: int = 120) -> None:
        if pid <= 0:
            return
        deadline = time.monotonic() + max(1, timeout_seconds)
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            except PermissionError as exc:
                raise UpdateInstallError("无法确认当前服务进程是否已经退出。") from exc
            time.sleep(0.25)
        raise UpdateInstallError("等待当前服务退出超时，未执行程序替换。")

    def _read_manifest(
        self,
        archive: zipfile.ZipFile,
    ) -> tuple[dict[str, Any], str]:
        manifest_names = [
            name
            for name in archive.namelist()
            if PurePosixPath(name).name == "update-manifest.json"
        ]
        if len(manifest_names) != 1:
            raise UpdateInstallError("更新包缺少唯一的版本清单。")
        manifest_name = manifest_names[0]
        path = PurePosixPath(manifest_name)
        if len(path.parts) != 2:
            raise UpdateInstallError("更新包版本清单目录结构不正确。")
        try:
            manifest = json.loads(archive.read(manifest_name))
        except (ValueError, UnicodeDecodeError) as exc:
            raise UpdateInstallError("更新包版本清单无法识别。") from exc
        if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
            raise UpdateInstallError("更新包版本清单格式不受支持。")
        return manifest, path.parts[0]

    def _validated_files(
        self,
        archive: zipfile.ZipFile,
        manifest: dict[str, Any],
        prefix: str,
    ) -> list[str]:
        files = self._string_list(manifest.get("files"))
        if not files or len(files) > self.max_files:
            raise UpdateInstallError("更新包文件数量不正确。")
        archive_entries = {item.filename: item for item in archive.infolist()}
        total_size = 0
        validated: list[str] = []
        for relative_path in files:
            normalized = self._validate_relative_path(relative_path)
            archive_name = f"{prefix}/{normalized}"
            entry = archive_entries.get(archive_name)
            if entry is None or entry.is_dir():
                raise UpdateInstallError(f"更新包缺少清单文件：{normalized}")
            total_size += entry.file_size
            if total_size > self.max_uncompressed_bytes:
                raise UpdateInstallError("更新包解压体积超过安全限制。")
            validated.append(normalized)
        return validated

    def _validate_relative_path(self, relative_path: str) -> str:
        path = PurePosixPath(relative_path)
        if (
            not relative_path
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[0] in self.protected_roots
        ):
            raise UpdateInstallError("更新包包含不允许写入的路径。")
        return path.as_posix()

    def _safe_destination(self, install_root: Path, relative_path: str) -> Path:
        destination = (install_root / relative_path).resolve()
        try:
            destination.relative_to(install_root)
        except ValueError as exc:
            raise UpdateInstallError("更新目标路径超出程序目录。") from exc
        return destination

    def _restore_files(
        self,
        *,
        install_root: Path,
        backup_root: Path,
        replaced_files: list[str],
        created_files: list[str],
    ) -> None:
        for relative_path in created_files:
            self._safe_destination(install_root, relative_path).unlink(missing_ok=True)
        for relative_path in replaced_files:
            backup_path = backup_root / relative_path
            destination = self._safe_destination(install_root, relative_path)
            if backup_path.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, destination)

    def _load_plan(self, plan_path: Path) -> dict[str, Any]:
        if not plan_path.is_file():
            raise UpdateInstallError("更新计划不存在。")
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UpdateInstallError("更新计划无法识别。") from exc
        if not isinstance(plan, dict) or plan.get("schemaVersion") != 1:
            raise UpdateInstallError("更新计划格式不受支持。")
        return plan

    def _write_plan(self, plan_path: Path, plan: dict[str, Any]) -> None:
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]
