import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentpulse.pipeline.ecosystem_pipeline import (
    detect_breaking_grade,
    extract_deadline,
    extract_migration_steps,
    semver_jump,
)


class TestEcosystemPipeline:
    def test_breaking_keyword_direct_confirm(self):
        content = "BREAKING: This is a breaking change that requires migration."
        grade = detect_breaking_grade(content, "patch")
        assert grade == "breaking"

    def test_must_migrate_keyword(self):
        content = "You must migrate your code to the new API."
        grade = detect_breaking_grade(content, "minor")
        assert grade == "breaking"

    def test_deprecation_plus_minor_jump_is_breaking(self):
        content = "This feature is deprecated and will be removed."
        grade = detect_breaking_grade(content, "minor")
        assert grade == "breaking"

    def test_only_major_jump_is_likely(self):
        grade = detect_breaking_grade("Some improvements and bug fixes.", "major")
        assert grade == "likely"

    def test_only_deprecation_is_watch(self):
        content = "This method is deprecated."
        grade = detect_breaking_grade(content, "patch")
        assert grade == "watch"

    def test_docs_chore_is_noise(self):
        grade = detect_breaking_grade("docs: update README", "patch")
        assert grade == "noise"

    def test_safe_release(self):
        grade = detect_breaking_grade("Bug fixes and performance improvements.", "patch")
        assert grade == "safe"

    def test_semver_jump_major(self):
        assert semver_jump("1.2.3", "2.0.0") == "major"

    def test_semver_jump_minor(self):
        assert semver_jump("1.2.3", "1.3.0") == "minor"

    def test_semver_jump_patch(self):
        assert semver_jump("1.2.3", "1.2.4") == "patch"

    def test_semver_jump_with_v_prefix(self):
        assert semver_jump("v1.2.3", "v2.0.0") == "major"

    def test_semver_jump_invalid(self):
        assert semver_jump("unknown", "2.0.0") == "none"

    def test_migration_steps_split_by_sentence(self):
        content = (
            "Update your imports from old to new. "
            "Change the constructor call signature. "
            "Run the migration script to upgrade data. "
            "Restart your application."
        )
        steps = extract_migration_steps(content)
        assert len(steps) >= 2
        assert len(steps) <= 3
        assert any("imports" in s.lower() for s in steps)

    def test_migration_steps_no_content(self):
        assert extract_migration_steps("") == []

    def test_migration_steps_limits_to_3(self):
        content = ". ".join([f"Step {i} do something" for i in range(10)]) + "."
        steps = extract_migration_steps(content, max_steps=3)
        assert len(steps) <= 3

    def test_extract_deadline(self):
        content = "This will be removed on 2027-07-28."
        date_str, days = extract_deadline(content)
        assert date_str == "2027-07-28"
        assert days is not None
        assert days > 0

    def test_extract_deadline_none(self):
        content = "No specific date mentioned."
        assert extract_deadline(content) == (None, None)