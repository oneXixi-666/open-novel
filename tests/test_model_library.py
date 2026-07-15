from __future__ import annotations

import io
import sqlite3
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi.testclient import TestClient

from open_novel.core.model_library import ModelLibraryService
from open_novel.core.project import ProjectService
from open_novel.core.workspace_registry import WorkspaceRegistryService
from open_novel.core.writing_model import WritingModelService
from open_novel.server import app


def _docx_bytes(text: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body><w:p><w:r><w:t>"
        + text
        + "</w:t></w:r></w:p></w:body></w:document>"
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", document)
    return output.getvalue()


def _setup_workspace(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "workspace.sqlite3"
    monkeypatch.setenv("OPEN_NOVEL_DB_PATH", str(db_path))
    monkeypatch.setenv("OPEN_NOVEL_INCLUDE_TEMP_PROJECTS", "1")
    first = ProjectService().create_project(tmp_path / "first", title="第一本书")
    second = ProjectService().create_project(tmp_path / "second", title="第二本书")
    registry = WorkspaceRegistryService(db_path)
    registry.register_project(first.root)
    registry.register_project(second.root)
    return db_path, first, second


def test_model_library_supports_categories_sources_and_cross_book_selection(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    service = ModelLibraryService(db_path)

    assert {item["label"] for item in service.list_categories()} >= {"玄幻", "都市", "其他"}
    templates = service.list_templates()
    assert len(templates) == 14
    assert len({item["id"] for item in templates}) == len(templates)
    assert {item["categoryId"] for item in templates} == {
        "fantasy",
        "urban",
        "romance",
        "mystery",
        "history",
        "science-fiction",
        "other",
    }
    assert {item["name"] for item in templates} >= {
        "东方玄幻升级流",
        "现代甜宠言情",
        "本格悬疑推理",
        "硬科幻探索",
    }
    category = service.create_category("第一人称")
    model = service.create_model(
        name="冷峻第一人称",
        category_id=category["id"],
        purpose="模仿叙事风格",
    )

    txt = service.add_uploaded_source(
        model["id"],
        filename="样本一.txt",
        content=("这是第一篇合格训练文章。" * 80).encode("utf-8"),
    )
    docx = service.add_uploaded_source(
        model["id"],
        filename="样本二.docx",
        content=_docx_bytes("这是第二篇合格训练文章。" * 80),
    )
    duplicate = service.add_uploaded_source(
        model["id"],
        filename="重复.txt",
        content=("这是第一篇合格训练文章。" * 80).encode("utf-8"),
    )

    assert txt["status"] == "eligible"
    assert docx["status"] == "eligible"
    assert duplicate["status"] == "skipped"
    assert duplicate["reasonCode"] == "duplicate"
    assert service.readiness(model["id"])["eligibleCount"] == 2

    first_selection = service.set_book_selection(
        book_id="/books/first",
        model_id=model["id"],
    )
    second_selection = service.set_book_selection(
        book_id="/books/second",
        model_id=model["id"],
    )
    assert first_selection["modelId"] == model["id"]
    assert second_selection["modelId"] == model["id"]
    assert service.get_model(model["id"])["usedByBooks"] == [
        "/books/second",
        "/books/first",
    ]


def test_builtin_model_templates_are_seeded_in_sqlite_without_overwriting_edits(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    ModelLibraryService(db_path)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM model_templates").fetchone()[0] == 14
        conn.execute(
            """
            UPDATE model_templates
            SET name = ?, updated_at = ?
            WHERE id = ?
            """,
            ("作者自定义玄幻模板", "2026-07-15T00:00:00+00:00", "fantasy-progression"),
        )

    reloaded = ModelLibraryService(db_path)
    customized = next(
        item
        for item in reloaded.list_templates()
        if item["id"] == "fantasy-progression"
    )
    assert customized["name"] == "作者自定义玄幻模板"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM model_templates").fetchone()[0] == 14


def test_model_library_api_accepts_multiple_txt_docx_and_book_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _, first, second = _setup_workspace(tmp_path, monkeypatch)
    long_chapter = "# 第一章\n\n" + "林澈沿着声音追进废弃楼道。" * 100
    ProjectService().write_text(first.root, "chapters/001.md", long_chapter)
    client = TestClient(app)

    created = client.post(
        "/api/model-library",
        json={
            "name": "跨书悬疑模型",
            "categoryId": "mystery",
            "purpose": "综合模仿",
            "description": "供所有作品选择",
        },
    )
    assert created.status_code == 200
    model_id = created.json()["model"]["id"]

    uploaded = client.post(
        f"/api/model-library/{model_id}/sources/upload",
        files=[
            ("files", ("悬疑一.txt", ("门后传来脚步声。" * 100).encode(), "text/plain")),
            (
                "files",
                (
                    "悬疑二.docx",
                    _docx_bytes("走廊尽头的灯忽然熄灭。" * 100),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            ),
        ],
    )
    assert uploaded.status_code == 200
    assert [item["status"] for item in uploaded.json()["items"]] == [
        "eligible",
        "eligible",
    ]

    from_book = client.post(
        f"/api/model-library/{model_id}/sources/from-books",
        json={"items": [{"bookId": str(first.root), "chapterId": "001"}]},
    )
    assert from_book.status_code == 200
    assert from_book.json()["items"][0]["sourceBookId"] == str(first.root)
    assert from_book.json()["items"][0]["status"] == "eligible"

    listing = client.get("/api/model-library")
    assert listing.status_code == 200
    assert len(listing.json()["templates"]) == 14
    listed = next(item for item in listing.json()["models"] if item["id"] == model_id)
    assert listed["eligibleCount"] == 3
    assert listed["visibility"] == "workspace"
    backend_listing = client.get("/api/model-library-training-backends")
    assert backend_listing.status_code == 200
    assert {item["id"] for item in backend_listing.json()["backends"]} == {
        "auto",
        "system",
        "mlx-lm",
        "llama-factory",
    }

    detail = client.get(f"/api/model-library/{model_id}")
    assert detail.status_code == 200
    assert {item["format"] for item in detail.json()["sources"]} == {
        "txt",
        "docx",
        "chapter",
    }
    assert second.root.as_posix() in {
        item["root"] for item in WorkspaceRegistryService().list_projects()
    }


def test_trained_public_model_can_be_selected_by_multiple_books(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path, first, second = _setup_workspace(tmp_path, monkeypatch)
    service = ModelLibraryService(db_path)
    model = service.create_model(
        name="公共训练模型",
        category_id="fantasy",
        purpose="模仿写法",
    )
    for index in range(20):
        source = service.add_uploaded_source(
            model["id"],
            filename=f"样本-{index:02d}.txt",
            content=(f"第{index}篇训练文章。" * 100).encode(),
        )
        assert source["status"] == "eligible"

    monkeypatch.setenv(
        "OPEN_NOVEL_MLX_TRAIN_COMMAND",
        "/usr/bin/touch {output_dir}/mlx.txt",
    )
    monkeypatch.setenv(
        "OPEN_NOVEL_LLAMA_FACTORY_TRAIN_COMMAND",
        "/usr/bin/touch {output_dir}/done.txt",
    )
    monkeypatch.setenv(
        "OPEN_NOVEL_INFER_COMMAND",
        "/usr/bin/printf trained-output",
    )
    backends = service.list_training_backends()
    assert {item["id"] for item in backends if item["available"]} == {
        "auto",
        "mlx-lm",
        "llama-factory",
    }
    result = service.run_training(model["id"], backend_id="llama-factory")
    assert result["status"] == "usable"
    trained_model = service.get_model(model["id"])
    assert trained_model["activeVersionId"] == result["versionId"]
    assert trained_model["versions"][0]["backendId"] == "llama-factory"

    client = TestClient(app)
    first_selected = client.put(
        f"/api/books/{quote(first.root.as_posix(), safe='')}/model",
        json={"bookId": first.root.as_posix(), "modelId": model["id"]},
    )
    second_selected = client.put(
        f"/api/books/{quote(second.root.as_posix(), safe='')}/model",
        json={"bookId": second.root.as_posix(), "modelId": model["id"]},
    )
    assert first_selected.status_code == 200
    assert second_selected.status_code == 200
    assert service.get_book_selection(first.root.as_posix())["modelId"] == model["id"]
    assert service.get_book_selection(second.root.as_posix())["modelId"] == model["id"]
    assert WritingModelService().get_profile(first.root, model["id"]).label == "公共训练模型"
    assert WritingModelService().get_profile(second.root, model["id"]).label == "公共训练模型"
