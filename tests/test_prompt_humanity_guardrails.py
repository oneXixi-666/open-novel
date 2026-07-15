from __future__ import annotations

import json
from pathlib import Path

from open_novel.core.editorial_profile import EDITORIAL_PROMPT_PRESETS

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_SKILLS = ROOT / "open_novel" / "builtin_skills"
SOURCE_SKILLS = ROOT / "skills"


def _prompt(skill_id: str) -> str:
    return (BUILTIN_SKILLS / skill_id / "prompt.md").read_text(encoding="utf-8")


def test_humanity_guardrails_cover_contract_drafting_editing_and_review() -> None:
    contract = _prompt("generation-scene-contract-builder")
    writer = _prompt("chapter-writer")
    editor = _prompt("line-editor")
    continuity = _prompt("continuity-checker")

    assert "initial defense or desire" in contract
    assert "not-yet-digested emotional consequence" in contract
    assert "artificial incompetence or an author-level contradiction" in contract
    assert "do not prescribe a five-senses checklist" in contract

    assert "Emotion may be suppressed, displaced, or left unresolved" in writer
    assert "Such incompleteness must arise from" in writer
    assert "Do not imitate humanity by deliberately adding typos" in writer
    assert "Use hesitation only when" in writer
    assert "do not inventory all five senses" in writer
    assert "Do not repeat stock body reactions" in writer

    assert "Preserve meaningful asymmetry" in editor
    assert "Distinguish character-level incompleteness from author-level error" in editor
    assert "do not expand the passage into a five-senses checklist" in editor

    assert "Distinguish a character's evidence-based misreading" in continuity
    assert "Suppressed emotion still counts" in continuity
    assert "Do not recommend deliberate typos" in continuity


def test_editorial_and_style_rules_preserve_causal_human_imperfection() -> None:
    humanity = EDITORIAL_PROMPT_PRESETS["generic-humanity"].rubric
    emotion = EDITORIAL_PROMPT_PRESETS["emotion-line-editor"].rubric
    catalog = json.loads(
        (ROOT / "open_novel" / "builtin_style_profiles" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )
    generic = next(
        profile for profile in catalog["profiles"] if profile["id"] == "generic-web-serial"
    )

    assert any("有因果依据的误解" in item for item in humanity)
    assert any("故意错字" in item for item in humanity)
    assert any("不要求每种情绪都配身体反应" in item for item in emotion)
    assert any("五感清单" in item for item in emotion)
    assert any("不完整表达" in item for item in generic["emotionGuidance"])
    assert any(
        "视角人物此刻会注意到" in item for item in generic["descriptionGuidance"]
    )
    assert any("伪造人味" in item for item in generic["taboo"])


def test_source_and_packaged_shared_skills_do_not_drift() -> None:
    shared_skills = [
        "canon-patch-proposer",
        "chapter-writer",
        "continuity-checker",
        "line-editor",
        "scene-contract-builder",
    ]

    for skill_id in shared_skills:
        for filename in ("prompt.md", "skill.json"):
            source = (SOURCE_SKILLS / skill_id / filename).read_text(encoding="utf-8")
            packaged = (BUILTIN_SKILLS / skill_id / filename).read_text(encoding="utf-8")
            assert source == packaged, f"shared skill drift: {skill_id}/{filename}"
