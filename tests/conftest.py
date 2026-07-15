from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolate_default_workspace_database(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(tmp_path / "workspace.sqlite3"))
