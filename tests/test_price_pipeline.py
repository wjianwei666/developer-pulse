import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentpulse.config import settings
from agentpulse.pipeline.price_pipeline import blended_cost, compute_percentile


class TestPricePipeline:
    def test_blended_cost_7_2_1_ratio(self):
        row = {
            "pricing_cache_read": 1.0,
            "pricing_input": 2.0,
            "pricing_output": 4.0,
        }
        expected = (
            1.0 * settings.blended_cache_ratio
            + 2.0 * settings.blended_input_ratio
            + 4.0 * settings.blended_output_ratio
        )
        assert blended_cost(row) == expected
        assert expected == 1.0 * 0.7 + 2.0 * 0.2 + 4.0 * 0.1
        assert expected == 0.7 + 0.4 + 0.4
        assert expected == 1.5

    def test_blended_cost_cache_missing_falls_back_to_input(self):
        row = {
            "pricing_cache_read": None,
            "pricing_input": 3.0,
            "pricing_output": 6.0,
        }
        result = blended_cost(row)
        assert result is not None
        expected = 3.0 * 0.7 + 3.0 * 0.2 + 6.0 * 0.1
        assert result == expected

    def test_blended_cost_all_missing_returns_none(self):
        row = {
            "pricing_cache_read": None,
            "pricing_input": None,
            "pricing_output": None,
        }
        assert blended_cost(row) is None

    def test_percentile_calculation(self):
        all_blended = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert compute_percentile(1.0, all_blended) == 0.0
        assert compute_percentile(5.0, all_blended) == 80.0
        assert compute_percentile(3.0, all_blended) == 40.0

    def test_percentile_empty_list(self):
        assert compute_percentile(1.0, []) == 0.0