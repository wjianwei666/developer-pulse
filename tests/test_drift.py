import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agentpulse.db as db_mod
from agentpulse.config import settings
from agentpulse.pipeline.ecosystem_pipeline import run_mcp_census


class TestDriftDetection:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "test.db"
        settings.db_path = db_path
        db_mod.settings = settings
        db_mod.init_db()

    def teardown_method(self):
        self.tmp.cleanup()

    def test_drift_detected_when_registry_version_stale(self):
        with db_mod.db_session() as conn:
            cur = conn.execute(
                "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
                ("mcp_registry", "mcp", "2026-01-01T00:00:00+00:00"),
            )
            prev_id = cur.lastrowid
            conn.execute(
                """INSERT INTO mcp_snapshots
                   (snapshot_id, server_id, name, version, pkg_version, remote_url, is_remote)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (prev_id, "server-1", "server-1", "1.0.0", "1.0.0", None, 0),
            )

            cur = conn.execute(
                "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
                ("mcp_registry", "mcp", "2026-01-02T00:00:00+00:00"),
            )
            new_id = cur.lastrowid
            conn.execute(
                """INSERT INTO mcp_snapshots
                   (snapshot_id, server_id, name, version, pkg_version, remote_url, is_remote)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (new_id, "server-1", "server-1", "1.0.0", "1.1.0", None, 0),
            )

        census = run_mcp_census(new_id)
        assert census["drift_count"] == 1, (
            "Drift must be detected when registry version stays the same "
            "but pkg_version advances (appendix A.3)"
        )

    def test_no_drift_when_versions_advance_together(self):
        with db_mod.db_session() as conn:
            cur = conn.execute(
                "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
                ("mcp_registry", "mcp", "2026-01-01T00:00:00+00:00"),
            )
            prev_id = cur.lastrowid
            conn.execute(
                """INSERT INTO mcp_snapshots
                   (snapshot_id, server_id, name, version, pkg_version, remote_url, is_remote)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (prev_id, "server-1", "server-1", "1.0.0", "1.0.0", None, 0),
            )

            cur = conn.execute(
                "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
                ("mcp_registry", "mcp", "2026-01-02T00:00:00+00:00"),
            )
            new_id = cur.lastrowid
            conn.execute(
                """INSERT INTO mcp_snapshots
                   (snapshot_id, server_id, name, version, pkg_version, remote_url, is_remote)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (new_id, "server-1", "server-1", "1.1.0", "1.1.0", None, 0),
            )

        census = run_mcp_census(new_id)
        assert census["drift_count"] == 0

    def test_census_counts(self):
        with db_mod.db_session() as conn:
            cur = conn.execute(
                "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
                ("mcp_registry", "mcp", "2026-01-01T00:00:00+00:00"),
            )
            prev_id = cur.lastrowid
            conn.execute(
                """INSERT INTO mcp_snapshots
                   (snapshot_id, server_id, name, version, pkg_version, remote_url, is_remote)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (prev_id, "old-server", "old-server", "1.0.0", "1.0.0", None, 0),
            )

            cur = conn.execute(
                "INSERT INTO snapshots (source, snapshot_type, created_at) VALUES (?, ?, ?)",
                ("mcp_registry", "mcp", "2026-01-02T00:00:00+00:00"),
            )
            new_id = cur.lastrowid
            conn.execute(
                """INSERT INTO mcp_snapshots
                   (snapshot_id, server_id, name, version, pkg_version, remote_url, is_remote)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (new_id, "new-server", "new-server", "1.0.0", "1.0.0", "https://example.com", 1),
            )

        census = run_mcp_census(new_id)
        assert census["total"] == 1
        assert census["new"] == 1
        assert census["deleted"] == 1
        assert census["remote_ratio"] == 1.0