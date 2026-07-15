from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK_PYTHON_ROOTS = [
    ROOT / "open_novel" / "agents",
    ROOT / "open_novel" / "core",
    ROOT / "open_novel" / "exporters",
    ROOT / "open_novel" / "security",
]

SCENARIO_SPECIFIC_MARKERS = [
    "林澈",
    "周衡",
    "青岚宗",
    "测试石",
    "裂纹玉牌",
    "禁忌传承",
    "残缺灵根",
    "山门测试",
]


def test_framework_python_does_not_embed_specific_regression_plot() -> None:
    offenders: list[str] = []
    for root in FRAMEWORK_PYTHON_ROOTS:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            found = [marker for marker in SCENARIO_SPECIFIC_MARKERS if marker in text]
            if found:
                offenders.append(f"{path.relative_to(ROOT)}: {', '.join(found)}")

    assert offenders == []
