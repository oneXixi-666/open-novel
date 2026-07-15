from __future__ import annotations

import argparse
import json
import re
import subprocess
import zipfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath

from open_novel import __version__

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_RELEASE_ROOTS = {
    ".agents",
    ".claude",
    ".codex",
    ".git",
    ".github",
    ".open-novel",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "dist",
    "docs",
    "output",
    "tests",
}
EXCLUDED_RELEASE_PREFIXES = {
    "frontend/.e2e-runtime",
    "frontend/node_modules",
    "frontend/test-results",
    "frontend/tests",
    "scripts/p0_real_agent_acceptance.py",
    "scripts/p2_quality_calibration_acceptance.py",
    "scripts/p3_service_restart_acceptance.py",
    "scripts/real_project_regression.py",
    "scripts/stage_d_fanqie_benchmark_review.py",
    "scripts/stage_d_fanqie_benchmarks.py",
    "scripts/stage_d_long_form_acceptance.py",
    "scripts/stage_d_quality_calibration_candidates.py",
    "scripts/stage_d_quality_calibration_report.py",
    "scripts/stage_d_real_thirty_chapter_generation.py",
    "scripts/stage_d_release_risk_check.py",
}
EXCLUDED_DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
EXCLUDED_SECRET_FILENAMES = {"open-novel-ai-secrets.json"}
SENSITIVE_CONTENT_PATTERNS = {
    "macOS 本机路径": re.compile(rb"/" rb"Users/[^/\s]+/"),
    "Linux 本机路径": re.compile(rb"/" rb"home/[^/\s]+/"),
    "Windows 本机路径": re.compile(rb"[A-Za-z]:\\" rb"Users\\[^\\\s]+\\"),
    "OpenAI 风格密钥": re.compile(rb"sk" rb"-[A-Za-z0-9_-]{20,}"),
    "GitHub 令牌": re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    "私钥": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a versioned Open Novel update bundle and SHA-256 file."
    )
    parser.add_argument(
        "--version",
        default=__version__,
        help="Release version without the v prefix.",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    return parser.parse_args()


def tracked_files(root: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [
        root / item.decode("utf-8")
        for item in completed.stdout.split(b"\0")
        if item
    ]


def validate_runtime_modules_are_tracked(root: Path, files: list[Path]) -> None:
    tracked = {
        path.resolve().relative_to(root.resolve()).as_posix()
        for path in files
        if path.exists()
    }
    missing = [
        path.relative_to(root).as_posix()
        for path in sorted((root / "open_novel").rglob("*.py"))
        if path.relative_to(root).as_posix() not in tracked
    ]
    if missing:
        raise ValueError(
            "release runtime modules are not tracked by Git: " + ", ".join(missing)
        )


def is_release_source(relative: str) -> bool:
    normalized = PurePosixPath(relative)
    if not normalized.parts:
        return False
    if normalized.parts[0] in EXCLUDED_RELEASE_ROOTS:
        return False
    if any(
        relative == prefix or relative.startswith(f"{prefix}/")
        for prefix in EXCLUDED_RELEASE_PREFIXES
    ):
        return False
    name = normalized.name.lower()
    if name == ".env" or name.startswith(".env."):
        return False
    if name in EXCLUDED_SECRET_FILENAMES:
        return False
    return normalized.suffix.lower() not in EXCLUDED_DATABASE_SUFFIXES


def validate_release_bundle(bundle_path: Path) -> None:
    with zipfile.ZipFile(bundle_path) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            relative = PurePosixPath(item.filename)
            if len(relative.parts) < 2 or not is_release_source(
                PurePosixPath(*relative.parts[1:]).as_posix()
            ):
                raise ValueError(f"release bundle contains excluded path: {item.filename}")
            content = archive.read(item)
            for label, pattern in SENSITIVE_CONTENT_PATTERNS.items():
                if pattern.search(content):
                    raise ValueError(
                        f"release bundle contains {label}: {item.filename}"
                    )


def build_bundle(
    *,
    root: Path,
    output_dir: Path,
    version: str,
    source_files: list[Path] | None = None,
) -> tuple[Path, Path]:
    normalized_version = version.removeprefix("v").strip()
    if normalized_version != __version__:
        raise ValueError(
            f"release version {normalized_version} does not match package version {__version__}"
        )
    frontend_dist = root / "frontend" / "dist"
    if not (frontend_dist / "index.html").is_file():
        raise FileNotFoundError(
            "frontend/dist/index.html is required; run the frontend build first"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / f"open-novel-{normalized_version}.zip"
    checksum_path = output_dir / f"{bundle_path.name}.sha256"
    prefix = f"open-novel-{normalized_version}"
    files = source_files if source_files is not None else tracked_files(root)
    if source_files is None:
        validate_runtime_modules_are_tracked(root, files)
    included: list[str] = []

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if not path.is_file():
                continue
            relative = path.resolve().relative_to(root.resolve()).as_posix()
            if not is_release_source(relative):
                continue
            archive.write(path, f"{prefix}/{relative}")
            included.append(relative)
        for path in sorted(frontend_dist.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            archive.write(path, f"{prefix}/{relative}")
            included.append(relative)
        manifest = {
            "schemaVersion": 1,
            "version": normalized_version,
            "createdAt": datetime.now(UTC).isoformat(),
            "files": sorted(set(included)),
        }
        archive.writestr(
            f"{prefix}/update-manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    try:
        validate_release_bundle(bundle_path)
    except Exception:
        bundle_path.unlink(missing_ok=True)
        raise
    digest = sha256(bundle_path.read_bytes()).hexdigest()
    checksum_path.write_text(f"{digest}  {bundle_path.name}\n", encoding="ascii")
    return bundle_path, checksum_path


def main() -> int:
    args = parse_args()
    bundle_path, checksum_path = build_bundle(
        root=ROOT,
        output_dir=args.output_dir.expanduser().resolve(),
        version=args.version,
    )
    print(bundle_path)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
