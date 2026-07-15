from __future__ import annotations

from open_novel.agents.detection import AgentDetectionService
from open_novel.core.skills import SkillLoader
from open_novel.web.app import app


@app.get("/skills")
def list_skills() -> list[dict[str, object]]:
    return [skill.model_dump() for skill in SkillLoader().list_skills()]


@app.get("/agents/detect")
def detect_agents() -> list[dict[str, object]]:
    return [agent.model_dump() for agent in AgentDetectionService().detect_all()]
