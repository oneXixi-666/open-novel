from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class QualityThresholdConfig:
    min_chars_blocker: int = 360
    min_chars_medium: int = 600
    max_chars_medium: int = 9000
    similarity_blocker: float = 0.86
    similarity_high: float = 0.72
    choice_marker_min: int = 2
    conflict_marker_min: int = 2
    emotion_marker_min: int = 1
    exposition_marker_max: int = 4
    min_recommended_examples: int = 20
    regression_gate_tolerance: float = 2.0

    @classmethod
    def from_dict(cls, data: object) -> QualityThresholdConfig:
        if not isinstance(data, dict):
            return cls()
        defaults = cls()
        values: dict[str, object] = {}
        for field, default in asdict(defaults).items():
            raw = data.get(field)
            if raw is None:
                raw = data.get(_camel_case(field))
            if raw is None:
                continue
            try:
                if isinstance(default, int):
                    values[field] = max(0, int(raw))
                elif field.startswith("similarity_"):
                    values[field] = max(0.0, min(1.0, float(raw)))
                else:
                    values[field] = max(0.0, float(raw))
            except (TypeError, ValueError):
                continue
        return cls(**values)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def suggested_min_recommended_examples(chapter_count: int) -> int:
    if chapter_count <= 0:
        return QualityThresholdConfig().min_recommended_examples
    return max(10, min(50, round(chapter_count * 0.6)))


def build_calibration_analysis(
    rows: list[dict[str, Any]],
    current: QualityThresholdConfig,
) -> dict[str, Any]:
    positive_labels = {"acceptable"}
    labeled_rows = [
        row
        for row in rows
        if str(row.get("label") or "") in {*positive_labels, "repair", "block"}
    ]
    positive_count = sum(1 for row in labeled_rows if row.get("label") in positive_labels)
    suggested = current.to_dict()
    if positive_count and len(labeled_rows) >= 2:
        suggested.update(
            {
                "min_chars_blocker": _best_min_threshold(
                    labeled_rows,
                    "characters",
                    positive_labels,
                    current.min_chars_blocker,
                ),
                "min_chars_medium": _best_min_threshold(
                    labeled_rows,
                    "characters",
                    positive_labels,
                    current.min_chars_medium,
                ),
                "similarity_blocker": _best_max_threshold(
                    labeled_rows,
                    "previousSimilarity",
                    positive_labels,
                    current.similarity_blocker,
                ),
                "similarity_high": _best_max_threshold(
                    labeled_rows,
                    "previousSimilarity",
                    positive_labels,
                    current.similarity_high,
                ),
                "choice_marker_min": _best_min_threshold(
                    labeled_rows,
                    "choiceMarkers",
                    positive_labels,
                    current.choice_marker_min,
                ),
                "conflict_marker_min": _best_min_threshold(
                    labeled_rows,
                    "conflictMarkers",
                    positive_labels,
                    current.conflict_marker_min,
                ),
                "emotion_marker_min": _best_min_threshold(
                    labeled_rows,
                    "emotionMarkers",
                    positive_labels,
                    current.emotion_marker_min,
                ),
                "exposition_marker_max": _best_max_count_threshold(
                    labeled_rows,
                    "expositionMarkers",
                    positive_labels,
                    current.exposition_marker_max,
                ),
            }
        )
    precision_recall = _precision_recall(labeled_rows, positive_labels)
    labels = {str(row.get("label") or "") for row in labeled_rows}
    acceptable_point = next(
        (
            item for item in precision_recall
            if float(item["precision"]) >= 0.8 and float(item["recall"]) >= 0.8
        ),
        None,
    )
    threshold_blockers = []
    if len(labeled_rows) < 10:
        threshold_blockers.append("每个题材至少需要 10 个完整人工标注章节。")
    if not {"acceptable", "repair", "block"}.issubset(labels):
        threshold_blockers.append("校准集必须同时覆盖可用、需修复和阻断三档。")
    if acceptable_point is None:
        threshold_blockers.append("当前误报和漏报还不能同时控制在 20% 以内。")
    return {
        "scoreDistribution": _score_distribution(labeled_rows),
        "currentThresholds": current.to_dict(),
        "suggestedThresholds": QualityThresholdConfig.from_dict(suggested).to_dict(),
        "precisionRecall": precision_recall,
        "confidence": (
            "样本不足，建议仅参考" if len(labeled_rows) < 10 else "样本量可用于初步校准"
        ),
        "sampleCount": len(labeled_rows),
        "thresholdEligible": not threshold_blockers,
        "thresholdBlockers": threshold_blockers,
    }


def _best_min_threshold(
    rows: list[dict[str, Any]],
    metric: str,
    positive_labels: set[str],
    fallback: int,
) -> int:
    values = sorted({_metric(row, metric) for row in rows})
    if not values:
        return fallback
    best = (0.0, fallback)
    for value in values:
        score = _f1(rows, positive_labels, lambda row, cutoff=value: _metric(row, metric) >= cutoff)
        if score > best[0]:
            best = (score, int(value))
    return int(best[1])


def _best_max_threshold(
    rows: list[dict[str, Any]],
    metric: str,
    positive_labels: set[str],
    fallback: float,
) -> float:
    values = sorted({_metric(row, metric) for row in rows})
    if not values:
        return fallback
    best = (0.0, fallback)
    for value in values:
        score = _f1(rows, positive_labels, lambda row, cutoff=value: _metric(row, metric) <= cutoff)
        if score > best[0]:
            best = (score, float(value))
    return round(float(best[1]), 3)


def _best_max_count_threshold(
    rows: list[dict[str, Any]],
    metric: str,
    positive_labels: set[str],
    fallback: int,
) -> int:
    values = sorted({_metric(row, metric) for row in rows})
    if not values:
        return fallback
    best = (0.0, fallback)
    for value in values:
        score = _f1(rows, positive_labels, lambda row, cutoff=value: _metric(row, metric) < cutoff)
        if score > best[0]:
            best = (score, int(value))
    return int(best[1])


def _precision_recall(
    rows: list[dict[str, Any]],
    positive_labels: set[str],
) -> list[dict[str, float | int]]:
    if not rows:
        return []
    result: list[dict[str, float | int]] = []
    for threshold in range(0, 101, 5):
        true_positive = sum(
            1
            for row in rows
            if int(row.get("score") or 0) >= threshold and row.get("label") in positive_labels
        )
        false_positive = sum(
            1
            for row in rows
            if int(row.get("score") or 0) >= threshold and row.get("label") not in positive_labels
        )
        false_negative = sum(
            1
            for row in rows
            if int(row.get("score") or 0) < threshold and row.get("label") in positive_labels
        )
        precision = true_positive / (true_positive + false_positive or 1)
        recall = true_positive / (true_positive + false_negative or 1)
        result.append(
            {
                "threshold": threshold,
                "precision": round(precision, 3),
                "recall": round(recall, 3),
            }
        )
    return result


def _score_distribution(rows: list[dict[str, Any]]) -> list[dict[str, object]]:
    buckets: dict[tuple[int, str], int] = {}
    for row in rows:
        score = max(0, min(100, int(row.get("score") or 0)))
        bucket = score - score % 5
        label = str(row.get("label") or "")
        key = (bucket, label)
        buckets[key] = buckets.get(key, 0) + 1
    return [
        {"score": score, "label": label, "count": count}
        for (score, label), count in sorted(buckets.items())
    ]


def _f1(rows: list[dict[str, Any]], positive_labels: set[str], predicate: Any) -> float:
    true_positive = sum(1 for row in rows if predicate(row) and row.get("label") in positive_labels)
    false_positive = sum(
        1 for row in rows if predicate(row) and row.get("label") not in positive_labels
    )
    false_negative = sum(
        1 for row in rows if not predicate(row) and row.get("label") in positive_labels
    )
    precision = true_positive / (true_positive + false_positive or 1)
    recall = true_positive / (true_positive + false_negative or 1)
    return 2 * precision * recall / (precision + recall or 1)


def _metric(row: dict[str, Any], key: str) -> float:
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    value = metrics.get(key, row.get(key, 0))
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _camel_case(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)
