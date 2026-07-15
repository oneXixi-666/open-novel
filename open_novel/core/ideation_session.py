from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from open_novel.core.models import utc_now
from open_novel.core.project import ProjectService

IDEATION_SESSION_DIR = "story/ideation-sessions"


class IdeationTurn(BaseModel):
    role: str
    content: str
    createdAt: str


class IdeationSession(BaseModel):
    schemaVersion: int = 1
    sessionId: str
    title: str
    status: str = "active"
    focus: str = ""
    source: str = "story"
    turns: list[IdeationTurn] = Field(default_factory=list)
    path: str = ""
    createdAt: str
    updatedAt: str


class IdeationSessionService:
    """Store lightweight Creative Hub sessions as project-local JSON artifacts."""

    def __init__(self, project_service: ProjectService | None = None) -> None:
        self.project_service = project_service or ProjectService()

    def create_session(self, root: Path, title: str, focus: str, seed: str = "") -> IdeationSession:
        project = self.project_service.open_project(root)
        now = utc_now().isoformat()
        cleaned_title = title.strip() or "创意探索"
        session_id = self._session_id(cleaned_title)
        path = f"{IDEATION_SESSION_DIR}/{session_id}.json"
        turns = [
            IdeationTurn(role="user", content=seed.strip(), createdAt=now)
        ] if seed.strip() else []
        session = IdeationSession(
            sessionId=session_id,
            title=cleaned_title,
            focus=focus.strip(),
            turns=turns,
            path=path,
            createdAt=now,
            updatedAt=now,
        )
        self.project_service.write_text(
            project.root,
            path,
            json.dumps(session.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )
        return session

    def read_session(self, root: Path, session_id: str) -> IdeationSession:
        project = self.project_service.open_project(root)
        relative_path = self._session_path(session_id)
        return IdeationSession.model_validate_json(
            self.project_service.read_text(project.root, relative_path)
        )

    def append_turn(
        self,
        root: Path,
        session_id: str,
        *,
        role: str,
        content: str,
    ) -> IdeationSession:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("ideation turn content is required")
        session = self.read_session(root, session_id)
        now = utc_now().isoformat()
        session.turns.append(
            IdeationTurn(role=role.strip() or "user", content=cleaned, createdAt=now)
        )
        session.updatedAt = now
        self._write_session(root, session)
        return session

    def append_session_to_section(
        self,
        root: Path,
        session_id: str,
        *,
        section_path: str,
        heading: str = "创意会话沉淀",
    ) -> str:
        session = self.read_session(root, session_id)
        if not session.turns:
            raise ValueError("ideation session has no turns to materialize")
        project = self.project_service.open_project(root)
        current = self.project_service.read_text(project.root, section_path)
        addition = self._section_markdown(session, heading=heading)
        updated = f"{current.rstrip()}\n\n{addition}\n" if current.strip() else f"{addition}\n"
        self.project_service.write_text(project.root, section_path, updated)
        return updated

    def list_sessions(self, root: Path, limit: int = 5) -> list[IdeationSession]:
        project = self.project_service.open_project(root)
        sessions: list[IdeationSession] = []
        paths = sorted(
            (
                relative_path
                for relative_path in self.project_service.list_paths(
                    project.root, IDEATION_SESSION_DIR
                )
                if relative_path.endswith(".json")
            ),
            key=lambda relative_path: self.project_service.modified_at(
                project.root, relative_path
            ),
            reverse=True,
        )
        for relative_path in paths:
            try:
                sessions.append(
                    IdeationSession.model_validate_json(
                        self.project_service.read_text(project.root, relative_path)
                    )
                )
            except ValueError:
                continue
            if len(sessions) >= limit:
                break
        return sessions

    def _write_session(self, root: Path, session: IdeationSession) -> None:
        project = self.project_service.open_project(root)
        self.project_service.write_text(
            project.root,
            session.path,
            json.dumps(session.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
        )

    def _session_path(self, session_id: str) -> str:
        if not re.fullmatch(r"[\w\-\u4e00-\u9fff]+", session_id):
            raise ValueError("invalid ideation session id")
        return f"{IDEATION_SESSION_DIR}/{session_id}.json"

    def _session_id(self, title: str) -> str:
        stamp = utc_now().strftime("%Y%m%d%H%M%S%f")
        slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", title).strip("-").lower()
        return f"ideation-{slug[:32] or 'session'}-{stamp}"

    def _section_markdown(self, session: IdeationSession, *, heading: str) -> str:
        lines = [
            f"## {heading}",
            "",
            f"- 会话：{session.title}",
            f"- 焦点：{session.focus or '未设置'}",
            f"- 来源：{session.path}",
            "",
            "### 回合记录",
        ]
        for index, turn in enumerate(session.turns, start=1):
            lines.append(f"{index}. **{turn.role}**：{turn.content}")
        return "\n".join(lines)
