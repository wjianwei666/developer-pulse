import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentpulse.pipeline.scoring import (
    grade_from_score,
    score_price_event,
    score_release_event,
)


class TestScoring:
    def test_grade_thresholds(self):
        assert grade_from_score(70) == "alert"
        assert grade_from_score(69) == "digest"
        assert grade_from_score(40) == "digest"
        assert grade_from_score(39) == "archive"

    def test_price_event_deprecation_not_penalized(self):
        score = score_price_event(
            event_type="deprecation",
            field_name="deprecation_date",
            change_pct=0.0,
            blended_cost_old=None,
            blended_cost_new=None,
            percentile_shift=0.0,
            adoption=100.0,
            days_remaining=30,
        )
        assert score >= 40, f"Deprecation event should not be systemically under-scored, got {score}"

    def test_price_event_high_adoption_high_change(self):
        score = score_price_event(
            event_type="price",
            field_name="pricing_input",
            change_pct=50.0,
            blended_cost_old=1.0,
            blended_cost_new=1.5,
            percentile_shift=10.0,
            adoption=100.0,
        )
        assert score >= 40

    def test_release_breaking_score(self):
        score = score_release_event(
            breaking_grade="breaking",
            adoption=90.0,
            days_remaining=30,
            has_migration_steps=True,
        )
        assert score >= 70

    def test_release_noise_low_score(self):
        score = score_release_event(
            breaking_grade="noise",
            adoption=50.0,
            days_remaining=None,
            has_migration_steps=False,
            is_noise=True,
        )
        assert score < 40

    def test_score_clamped_0_100(self):
        score = score_price_event(
            event_type="price",
            field_name="pricing_reasoning",
            change_pct=1000.0,
            blended_cost_old=0.01,
            blended_cost_new=0.11,
            percentile_shift=100.0,
            adoption=100.0,
        )
        assert 0 <= score <= 100