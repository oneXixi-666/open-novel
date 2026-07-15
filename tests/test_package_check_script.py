from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import package_check
from scripts.package_check import DEPENDENCY_RESOLUTION_MARKERS, REQUIRED_WHEEL_ENTRIES


def test_package_check_script_exposes_cli_help() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/package_check.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--keep-dist" in completed.stdout
    assert "--fallback-current-env" in completed.stdout
    assert "Open Novel package" in completed.stdout


def test_package_check_requires_runtime_assets() -> None:
    required = set(REQUIRED_WHEEL_ENTRIES)

    assert "open_novel/web/app.py" in required
    assert "open_novel/web/routes_basic.py" in required
    assert "open_novel/web/routes_workbench.py" in required
    assert "frontend/package.json" in required
    assert "frontend/src/main.tsx" in required
    assert "frontend/src/pages/ShelfPage.tsx" in required
    assert "frontend/src/pages/ModelPage.tsx" in required
    assert "frontend/src/api/workbenchClient.ts" in required
    assert "open_novel/builtin_style_profiles/catalog.json" in required
    assert (
        "open_novel/builtin_style_profiles/planned_slots/workplace-business-growth.json"
        in required
    )
    assert "open_novel/builtin_style_profiles/packs/broad-genre-reserve.json" in required
    assert "open_novel/builtin_skills/chapter-writer/skill.json" in required
    assert "skills/chapter-writer/skill.json" in required
    assert not any(path.startswith("examples/novels/demo/") for path in required)


def test_docker_image_no_longer_copies_file_demo_assets() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "examples/novels/demo" not in dockerfile


def test_package_check_prefers_uv_for_wheel_install(monkeypatch, tmp_path) -> None:
    python = tmp_path / "venv" / "bin" / "python"
    wheel = tmp_path / "dist" / "open_novel-0.1.0-py3-none-any.whl"

    monkeypatch.setattr(package_check.shutil, "which", lambda name: "/usr/bin/uv")

    assert package_check.wheel_install_command(python, wheel) == [
        "uv",
        "pip",
        "install",
        "--python",
        str(python),
        "--quiet",
        str(wheel),
    ]


def test_package_check_falls_back_to_pip_for_wheel_install(monkeypatch, tmp_path) -> None:
    python = tmp_path / "venv" / "bin" / "python"
    wheel = tmp_path / "dist" / "open_novel-0.1.0-py3-none-any.whl"

    monkeypatch.setattr(package_check.shutil, "which", lambda name: None)

    assert package_check.wheel_install_command(python, wheel) == [
        str(python),
        "-m",
        "pip",
        "install",
        "--quiet",
        str(wheel),
    ]


def test_package_check_reports_dependency_resolution_failures(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    assert "Failed to fetch" in DEPENDENCY_RESOLUTION_MARKERS
    assert "failed to lookup address information" in DEPENDENCY_RESOLUTION_MARKERS

    def fake_run(*args, **kwargs):  # noqa: ANN002, ANN003
        return subprocess.CompletedProcess(
            args[0],
            2,
            "",
            "Failed to fetch: https://pypi.org/simple/hatchling/\n"
            "failed to lookup address information\n",
        )

    monkeypatch.setattr(package_check, "ROOT", tmp_path)
    monkeypatch.setattr(package_check.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(package_check.subprocess, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["package_check.py"])

    with pytest.raises(SystemExit) as exc:
        package_check.main()

    assert exc.value.code == 2
    stderr = capsys.readouterr().err
    assert "PACKAGE_CHECK: BLOCKED dependency resolution failed while building wheel." in stderr
    assert "such as hatchling can be resolved from PyPI or an internal cache" in stderr
    assert "Failed to fetch" in stderr


def test_package_check_reports_install_dependency_resolution_failures(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "open_novel-0.1.0-py3-none-any.whl"
    with package_check.zipfile.ZipFile(wheel, "w") as archive:
        for entry in REQUIRED_WHEEL_ENTRIES:
            archive.writestr(entry, "")

    def fake_run(args, **kwargs):  # noqa: ANN001, ANN003
        command = [str(part) for part in args]
        if command[:2] == ["uv", "build"]:
            dist.mkdir(exist_ok=True)
            with package_check.zipfile.ZipFile(wheel, "w") as archive:
                for entry in REQUIRED_WHEEL_ENTRIES:
                    archive.writestr(entry, "")
            return subprocess.CompletedProcess(args, 0, "", "")
        if command[1:3] == ["-m", "venv"]:
            python = tmp_path / "open-novel-package-check-test" / "venv" / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")
        if command[:3] == ["uv", "pip", "install"]:
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "ERROR: Could not find a version that satisfies the requirement fastapi>=0.115.0\n"
                "ERROR: No matching distribution found for fastapi>=0.115.0\n",
            )
        return subprocess.CompletedProcess(args, 0, "PACKAGE_IMPORT: PASS\n", "")

    class FakeTemporaryDirectory:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.path = tmp_path / "open-novel-package-check-test"

        def __enter__(self) -> str:
            self.path.mkdir(exist_ok=True)
            return str(self.path)

        def __exit__(self, *args) -> None:  # noqa: ANN002
            return None

    monkeypatch.setattr(package_check, "ROOT", tmp_path)
    monkeypatch.setattr(package_check.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(package_check.subprocess, "run", fake_run)
    monkeypatch.setattr(package_check.tempfile, "TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr(sys, "argv", ["package_check.py"])

    with pytest.raises(SystemExit) as exc:
        package_check.main()

    assert exc.value.code == 1
    stderr = capsys.readouterr().err
    assert (
        "PACKAGE_CHECK: BLOCKED dependency resolution failed while installing wheel dependencies."
        in stderr
    )
    assert (
        "runtime dependencies such as fastapi can be resolved from PyPI or an internal cache"
        in stderr
    )
    assert "No matching distribution found for fastapi" in stderr


def test_package_check_fallback_current_env_is_explicit(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "open_novel-0.1.0-py3-none-any.whl"
    with package_check.zipfile.ZipFile(wheel, "w") as archive:
        for entry in REQUIRED_WHEEL_ENTRIES:
            archive.writestr(entry, "")

    run_calls: list[list[str]] = []

    def fake_run(args, **kwargs):  # noqa: ANN001, ANN003
        command = [str(part) for part in args]
        run_calls.append(command)
        if command[:2] == ["uv", "build"]:
            dist.mkdir(exist_ok=True)
            with package_check.zipfile.ZipFile(wheel, "w") as archive:
                for entry in REQUIRED_WHEEL_ENTRIES:
                    archive.writestr(entry, "")
            return subprocess.CompletedProcess(args, 0, "", "")
        if command[1:3] == ["-m", "venv"]:
            python = tmp_path / "open-novel-package-check-test" / "venv" / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")
        if command[:3] == ["uv", "pip", "install"]:
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "Failed to fetch: https://pypi.org/simple/pydantic/\n"
                "failed to lookup address information\n",
            )
        return subprocess.CompletedProcess(args, 0, "PACKAGE_INSTALL: PASS\n", "")

    class FakeTemporaryDirectory:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.path = tmp_path / "open-novel-package-check-test"

        def __enter__(self) -> str:
            self.path.mkdir(exist_ok=True)
            return str(self.path)

        def __exit__(self, *args) -> None:  # noqa: ANN002
            return None

    monkeypatch.setattr(package_check, "ROOT", tmp_path)
    monkeypatch.setattr(package_check.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(package_check.subprocess, "run", fake_run)
    monkeypatch.setattr(package_check.tempfile, "TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr(sys, "argv", ["package_check.py", "--fallback-current-env"])

    assert package_check.main() == 0
    stderr = capsys.readouterr().err
    assert "PACKAGE_CHECK: BLOCKED dependency resolution failed" in stderr
    assert "PACKAGE_CHECK: FALLBACK current environment verified extracted wheel" in stderr
    assert any(command[0] == sys.executable and command[1] == "-c" for command in run_calls)


def test_package_check_fallback_can_reuse_existing_wheel_when_build_is_blocked(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "open_novel-0.1.0-py3-none-any.whl"
    with package_check.zipfile.ZipFile(wheel, "w") as archive:
        for entry in REQUIRED_WHEEL_ENTRIES:
            archive.writestr(entry, "")

    def fake_run(args, **kwargs):  # noqa: ANN001, ANN003
        command = [str(part) for part in args]
        if command[:2] == ["uv", "build"]:
            return subprocess.CompletedProcess(
                args,
                2,
                "",
                "Failed to fetch: https://pypi.org/simple/hatchling/\n",
            )
        if command[1:3] == ["-m", "venv"]:
            python = tmp_path / "open-novel-package-check-test" / "venv" / "bin" / "python"
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
            return subprocess.CompletedProcess(args, 0, "", "")
        if command[:3] == ["uv", "pip", "install"]:
            return subprocess.CompletedProcess(
                args,
                1,
                "",
                "Failed to fetch: https://pypi.org/simple/fastapi/\n",
            )
        return subprocess.CompletedProcess(args, 0, "PACKAGE_INSTALL: PASS\n", "")

    class FakeTemporaryDirectory:
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            self.path = tmp_path / "open-novel-package-check-test"

        def __enter__(self) -> str:
            self.path.mkdir(exist_ok=True)
            return str(self.path)

        def __exit__(self, *args) -> None:  # noqa: ANN002
            return None

    monkeypatch.setattr(package_check, "ROOT", tmp_path)
    monkeypatch.setattr(package_check.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(package_check.subprocess, "run", fake_run)
    monkeypatch.setattr(package_check.tempfile, "TemporaryDirectory", FakeTemporaryDirectory)
    monkeypatch.setattr(sys, "argv", ["package_check.py", "--fallback-current-env"])

    assert package_check.main() == 0
    stderr = capsys.readouterr().err
    assert "PACKAGE_CHECK: FALLBACK reusing existing wheel" in stderr
    assert "PACKAGE_CHECK: FALLBACK current environment verified extracted wheel" in stderr
