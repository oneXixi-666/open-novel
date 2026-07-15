from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_WHEEL_ENTRIES = [
    "open_novel/__init__.py",
    "open_novel/server.py",
    "open_novel/web/app.py",
    "open_novel/web/__init__.py",
    "open_novel/web/routes_basic.py",
    "open_novel/web/routes_workbench.py",
    "frontend/package.json",
    "frontend/index.html",
    "frontend/src/main.tsx",
    "frontend/src/pages/ShelfPage.tsx",
    "frontend/src/pages/ModelPage.tsx",
    "frontend/src/api/workbenchClient.ts",
    "open_novel/core/beginner_guidance.py",
    "open_novel/builtin_style_profiles/__init__.py",
    "open_novel/builtin_style_profiles/catalog.json",
    "open_novel/builtin_style_profiles/planned_slots/workplace-business-growth.json",
    "open_novel/builtin_style_profiles/packs/broad-genre-reserve.json",
    "open_novel/builtin_regression_scenarios/__init__.py",
    "open_novel/builtin_regression_scenarios/fanqie-xuanhuan-upgrade.json",
    "open_novel/builtin_skills/chapter-writer/skill.json",
    "open_novel/builtin_skills/chapter-writer/prompt.md",
    "open_novel/builtin_skills/writing-formula-extractor/skill.json",
    "open_novel/builtin_skills/writing-formula-extractor/prompt.md",
    "skills/chapter-writer/skill.json",
    "skills/chapter-writer/prompt.md",
]


DEPENDENCY_RESOLUTION_MARKERS = (
    "Failed to resolve requirements",
    "Failed to fetch",
    "failed to lookup address information",
    "nodename nor servname provided",
    "Temporary failure in name resolution",
    "Name or service not known",
    "No matching distribution found",
    "Could not find a version that satisfies the requirement",
)


def dependency_resolution_failed(output: str) -> bool:
    return any(marker in output for marker in DEPENDENCY_RESOLUTION_MARKERS)


def print_dependency_resolution_blocked(action: str, hint: str, output: str) -> None:
    print(
        f"PACKAGE_CHECK: BLOCKED dependency resolution failed while {action}.",
        file=sys.stderr,
    )
    print(
        "PACKAGE_CHECK: run this check again where " + hint + ".",
        file=sys.stderr,
    )
    if output:
        print(output, file=sys.stderr, end="" if output.endswith("\n") else "\n")


def wheel_install_command(python: Path, wheel: Path) -> list[str]:
    if shutil.which("uv") is not None:
        return ["uv", "pip", "install", "--python", str(python), "--quiet", str(wheel)]
    return [str(python), "-m", "pip", "install", "--quiet", str(wheel)]


def extracted_wheel_command(target: Path) -> str:
    return (
        "from pathlib import Path\n"
        "from open_novel.core.skills import SkillLoader\n"
        "from open_novel.core.style_profile import StyleProfileService\n"
        "from open_novel.web.app import app\n"
        "import open_novel.web.routes_workbench\n"
        f"package_root = Path({str(target)!r})\n"
        "assert package_root.joinpath("
        "'open_novel/builtin_skills/chapter-writer/skill.json'"
        ").exists()\n"
        "assert package_root.joinpath('skills/chapter-writer/skill.json').exists()\n"
        "assert package_root.joinpath('frontend/src/main.tsx').exists()\n"
        "assert package_root.joinpath('frontend/src/pages/ShelfPage.tsx').exists()\n"
        "paths = {route.path for route in app.routes}\n"
        "assert '/health' in paths\n"
        "assert '/api/workspace' in paths\n"
        "allowed = {'/health', '/skills', '/agents/detect', '/openapi.json', "
        "'/docs', '/docs/oauth2-redirect', '/redoc'}\n"
        "assert all(path in allowed or path.startswith('/api/') or "
        "path.startswith('/projects/') for path in paths)\n"
        "skills = SkillLoader(package_root / 'open_novel' / 'builtin_skills').list_skills()\n"
        "assert any(skill.id == 'chapter-writer' for skill in skills)\n"
        "assert StyleProfileService().validate_catalog()['profileCount'] >= 4\n"
        "print('PACKAGE_INSTALL: PASS')\n"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and inspect the Open Novel package.")
    parser.add_argument(
        "--keep-dist",
        action="store_true",
        help="Leave generated dist artifacts in place.",
    )
    parser.add_argument(
        "--fallback-current-env",
        action="store_true",
        help=(
            "If isolated dependency installation is blocked, verify the extracted wheel "
            "with the current Python environment instead. This is not a replacement for "
            "a full isolated package check."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dist = ROOT / "dist"
    if dist.exists() and not args.fallback_current_env:
        shutil.rmtree(dist)

    build_command = ["uv", "build", "--wheel"]
    if shutil.which("uv") is None:
        build_command = [sys.executable, "-m", "build", "--wheel"]
    build = subprocess.run(build_command, cwd=ROOT, capture_output=True, text=True)
    if build.returncode != 0:
        output = "\n".join(part for part in [build.stdout, build.stderr] if part)
        if dependency_resolution_failed(output):
            print_dependency_resolution_blocked(
                "building wheel",
                "build-system dependencies such as hatchling can be resolved from "
                "PyPI or an internal cache",
                output,
            )
            wheels = sorted(dist.glob("*.whl")) if args.fallback_current_env else []
            if len(wheels) == 1:
                wheel = wheels[0]
                print(
                    "PACKAGE_CHECK: FALLBACK reusing existing wheel because isolated "
                    "build dependency resolution was blocked.",
                    file=sys.stderr,
                )
            else:
                raise SystemExit(build.returncode)
        elif output:
            print(output, file=sys.stderr, end="" if output.endswith("\n") else "\n")
            raise SystemExit(build.returncode)
    else:
        wheels = sorted(dist.glob("*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"expected exactly one wheel, found {len(wheels)}")
        wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    missing = [entry for entry in REQUIRED_WHEEL_ENTRIES if entry not in names]
    if missing:
        raise SystemExit("missing wheel entries: " + ", ".join(missing))

    with tempfile.TemporaryDirectory(prefix="open-novel-package-check-") as tmpdir:
        target = Path(tmpdir)
        with zipfile.ZipFile(wheel) as archive:
            archive.extractall(target)
        subprocess.run(
            [sys.executable, "-c", extracted_wheel_command(target)],
            cwd=target,
            check=True,
            env={"PYTHONPATH": str(target)},
        )
        installed_command = extracted_wheel_command(target)
        venv_dir = target / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], cwd=target, check=True)
        python = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        open_novel = venv_dir / (
            "Scripts/open-novel.exe" if sys.platform == "win32" else "bin/open-novel"
        )
        install = subprocess.run(
            wheel_install_command(python, wheel),
            cwd=target,
            capture_output=True,
            text=True,
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        )
        if install.returncode != 0:
            output = "\n".join(part for part in [install.stdout, install.stderr] if part)
            if dependency_resolution_failed(output):
                print_dependency_resolution_blocked(
                    "installing wheel dependencies",
                    "runtime dependencies such as fastapi can be resolved from "
                    "PyPI or an internal cache",
                    output,
                )
                if args.fallback_current_env:
                    subprocess.run(
                        [sys.executable, "-c", installed_command],
                        cwd=target,
                        check=True,
                        env={"PYTHONPATH": str(target)},
                    )
                    print(
                        "PACKAGE_CHECK: FALLBACK current environment verified extracted wheel "
                        "after isolated dependency resolution was blocked.",
                        file=sys.stderr,
                    )
                    return 0
            elif output:
                print(output, file=sys.stderr, end="" if output.endswith("\n") else "\n")
            raise SystemExit(install.returncode)
        installed_cwd = target / "installed-cwd"
        installed_cwd.mkdir()
        skill_list = subprocess.run(
            [open_novel, "skill", "list"],
            cwd=installed_cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        if "chapter-writer" not in skill_list.stdout:
            raise SystemExit("installed console script could not list built-in skills")
        style_validate = subprocess.run(
            [open_novel, "style", "validate-catalog"],
            cwd=installed_cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        if "STYLE_CATALOG: PASS" not in style_validate.stdout:
            raise SystemExit("installed console script could not validate style catalog")
        style_draft = subprocess.run(
            [open_novel, "style", "draft-profile", "workplace-business-growth"],
            cwd=installed_cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        if '"templateStatus": "candidate"' not in style_draft.stdout:
            raise SystemExit("installed console script could not draft style profile")
        subprocess.run(
            [open_novel, "style", "evaluate-promotion", "--help"],
            cwd=installed_cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [open_novel, "style", "export-promoted-profile", "--help"],
            cwd=installed_cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [open_novel, "style", "validate-exported-profile", "--help"],
            cwd=installed_cwd,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run([open_novel, "--help"], cwd=installed_cwd, check=True, capture_output=True)
        subprocess.run([python, "-c", installed_command], cwd=installed_cwd, check=True)

    if not args.keep_dist:
        shutil.rmtree(dist, ignore_errors=True)

    print(f"PACKAGE_CHECK: PASS {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
