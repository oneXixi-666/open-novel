from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from open_novel.core.jobs import JobController


class WorkbenchModelLibraryService:
    def __init__(self, presenter: Any) -> None:
        self.presenter = presenter

    def list_models(self) -> dict[str, Any]:
        return {
            "categories": self.presenter.model_library_service.list_categories(),
            "templates": self.presenter.model_library_service.list_templates(),
            "models": self.presenter.model_library_service.list_models(),
        }

    def list_training_backends(self) -> dict[str, Any]:
        return {
            "backends": self.presenter.model_library_service.list_training_backends(),
        }

    def create_model(self, request: Any) -> dict[str, Any]:
        try:
            model = self.presenter.model_library_service.create_model(
                name=request.name,
                category_id=request.categoryId,
                purpose=request.purpose,
                description=request.description,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"model": model, "summary": f"已创建模型：{model['name']}"}

    def create_category(self, request: Any) -> dict[str, Any]:
        try:
            category = self.presenter.model_library_service.create_category(request.label)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"category": category, "summary": f"已创建分类：{category['label']}"}

    def model_detail(self, model_id: str) -> dict[str, Any]:
        try:
            return self.presenter.model_library_service.get_model(model_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def upload_sources(
        self,
        model_id: str,
        files: list[tuple[str, bytes]],
    ) -> dict[str, Any]:
        if not files:
            raise HTTPException(status_code=400, detail="请至少选择一个 TXT 或 DOCX 文件。")
        total_bytes = sum(len(content) for _, content in files)
        if total_bytes > self.presenter.model_library_service.max_batch_bytes:
            raise HTTPException(status_code=400, detail="单次上传总大小不能超过 20 MB。")
        items: list[dict[str, Any]] = []
        for filename, content in files:
            try:
                item = self.presenter.model_library_service.add_uploaded_source(
                    model_id,
                    filename=filename,
                    content=content,
                )
            except FileNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except ValueError as exc:
                items.append(
                    {
                        "originalName": filename,
                        "status": "failed",
                        "reasonCode": "upload_failed",
                        "reasonLabel": str(exc),
                    }
                )
                continue
            items.append(item)
        return {
            "model": self.presenter.model_library_service.get_model(model_id),
            "items": items,
            "summary": (
                f"已处理 {len(items)} 个文件，"
                f"可用 {sum(item.get('status') == 'eligible' for item in items)} 个。"
            ),
        }

    def add_book_sources(self, model_id: str, request: Any) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for source in request.items:
            try:
                root = self.presenter._root_from_book_id(source.bookId)
            except HTTPException:
                items.append(
                    {
                        "sourceBookId": source.bookId,
                        "sourceChapterId": source.chapterId,
                        "status": "failed",
                        "reasonLabel": "来源作品不存在。",
                    }
                )
                continue
            chapter = next(
                (
                    item
                    for item in self.presenter._chapters_for_root(root)  # noqa: SLF001
                    if str(item.get("id") or "") == source.chapterId
                ),
                None,
            )
            if chapter is None:
                items.append(
                    {
                        "sourceBookId": source.bookId,
                        "sourceChapterId": source.chapterId,
                        "status": "failed",
                        "reasonLabel": "来源章节不存在。",
                    }
                )
                continue
            item = self.presenter.model_library_service.add_book_chapter_source(
                model_id,
                book_id=source.bookId,
                chapter_id=source.chapterId,
                label=(
                    f"{self.presenter.book_for_root(root)['title']} · "
                    f"{chapter.get('title') or source.chapterId}"
                ),
                text=str(chapter.get("content") or ""),
            )
            items.append(item)
        return {
            "model": self.presenter.model_library_service.get_model(model_id),
            "items": items,
            "summary": f"已处理 {len(items)} 个作品章节。",
        }

    def readiness(self, model_id: str) -> dict[str, Any]:
        try:
            return self.presenter.model_library_service.readiness(model_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def start_training(self, model_id: str, request: Any) -> dict[str, Any]:
        if not request.confirm:
            raise HTTPException(status_code=400, detail="开始训练前需要确认训练素材。")
        root = self.presenter._target_root(request.bookId)
        if root is None:
            raise HTTPException(status_code=400, detail="当前工作区还没有可记录训练任务的作品。")
        try:
            readiness = self.presenter.model_library_service.readiness(model_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if readiness["status"] != "ready":
            raise HTTPException(
                status_code=400,
                detail=readiness["recommendedNextAction"],
            )
        backend = next(
            (
                item
                for item in self.presenter.model_library_service.list_training_backends()
                if item["id"] == request.backendId
            ),
            None,
        )
        if backend is None or not backend["available"]:
            raise HTTPException(status_code=400, detail="选择的训练方式当前不可用。")
        selected_ids = request.sourceIds or [
            item["id"]
            for item in readiness["items"]
            if item["status"] == "eligible"
        ]
        controller = JobController()
        job = controller.submit_background(
            root,
            kind="model-library-training",
            title=f"训练模型：{self.presenter.model_library_service.get_model(model_id)['name']}",
            detail=f"使用 {len(selected_ids)} 篇合格文章训练公共模型。",
            params={
                "modelId": model_id,
                "sourceIds": selected_ids,
                "backendId": request.backendId,
            },
            work=lambda current_job: self.presenter.model_library_service.run_training(
                model_id,
                source_ids=selected_ids,
                backend_id=request.backendId,
                cancel_check=lambda: controller.is_cancel_requested(root, current_job.jobId),
            ),
        )
        return {
            "modelId": model_id,
            "job": self.presenter._job_summary(root, job),
            "summary": "训练任务已提交，系统将使用默认训练能力执行。",
        }

    def delete_source(self, model_id: str, source_id: str) -> dict[str, Any]:
        try:
            model = self.presenter.model_library_service.delete_source(model_id, source_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"model": model, "summary": "训练素材已删除。"}
