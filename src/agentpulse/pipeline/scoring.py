from __future__ import annotations

from ..config import settings


def adoption_weight(model_id: str | None) -> float:
    if not model_id:
        return 50
    mid = model_id.lower()
    for vendor, weight in settings.default_adoption_weights.items():
        if vendor in mid:
            return float(weight)
    return 40.0


def _clamp(score: float) -> float:
    return max(0.0, min(100.0, score))


def grade_from_score(score: float) -> str:
    if score >= settings.score_alert_threshold:
        return "alert"
    if score >= settings.score_digest_threshold:
        return "digest"
    return "archive"


def score_price_event(
    event_type: str,
    field_name: str | None,
    change_pct: float,
    blended_cost_old: float | None,
    blended_cost_new: float | None,
    percentile_shift: float,
    adoption: float,
    days_remaining: int | None = None,
) -> float:
    field = (field_name or "").lower()

    is_metric_field = "cache" in field or "reasoning" in field
    is_io_field = field in ("pricing_input", "pricing_output")

    bill_impact = 0.0
    decision_relevance = 0.0
    caliber_value = 0.0
    scope = 0.0
    urgency = 0.0

    if event_type == "price":
        bill_impact = min(35.0, abs(change_pct) * adoption / 100.0 * 3.5)
        decision_relevance = min(25.0, abs(percentile_shift) * 2.5)
        if is_metric_field:
            caliber_value = 20.0
        elif is_io_field:
            caliber_value = 10.0
        if "image" in field or "search" in field:
            scope = 6.0
        else:
            scope = 12.0
        if days_remaining is not None:
            urgency = 8.0 if days_remaining <= 30 else (5.0 if days_remaining <= 90 else 2.0)

    elif event_type == "context":
        bill_impact = min(35.0, abs(change_pct) * adoption / 100.0 * 3.5)
        decision_relevance = min(25.0, abs(change_pct) * 0.5)
        caliber_value = 5.0
        scope = 12.0

    elif event_type == "deprecation":
        bill_impact = 0.0
        decision_relevance = 25.0 * adoption / 100.0
        caliber_value = 5.0
        scope = 12.0
        if days_remaining is not None:
            urgency = 8.0 if days_remaining <= 30 else (5.0 if days_remaining <= 90 else 2.0)
        else:
            urgency = 8.0

    elif event_type in ("new", "removed"):
        decision_relevance = adoption / 100.0 * 25.0
        caliber_value = 5.0
        scope = 12.0 if event_type == "new" else 6.0
        urgency = 3.0

    total = bill_impact + decision_relevance + caliber_value + scope + urgency
    return _clamp(total)


def score_release_event(
    breaking_grade: str,
    adoption: float,
    days_remaining: int | None,
    has_migration_steps: bool,
    is_noise: bool = False,
) -> float:
    grade_scores = {"breaking": 30.0, "likely": 20.0, "watch": 10.0, "safe": 0.0, "noise": 0.0}
    destructive = grade_scores.get(breaking_grade, 0.0)

    impact = min(25.0, adoption / 100.0 * 25.0)

    if days_remaining is not None:
        if days_remaining <= 30:
            deadline = 20.0
        elif days_remaining <= 90:
            deadline = 14.0
        else:
            deadline = 8.0
    elif breaking_grade in ("breaking", "likely"):
        deadline = 8.0
    else:
        deadline = 0.0

    migration = 15.0 if has_migration_steps else 5.0
    noise_filter = 0.0 if is_noise else 10.0

    total = destructive + impact + deadline + migration + noise_filter
    return _clamp(total)