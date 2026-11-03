import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentpulse.db import init_db, db_session
from agentpulse.pipeline.price_pipeline import run_price_pipeline
from agentpulse.pipeline.ecosystem_pipeline import run_release_pipeline, run_mcp_pipeline
from agentpulse.pipeline.digest import run_digest_pipeline

init_db()

print("=" * 60)
print("AgentPulse Seed Script - Populate homepage with real data")
print("=" * 60)

print("\n[1/5] Running release pipeline (first run seeds all releases as events)...")
try:
    result = run_release_pipeline()
    print(f"  releases_collected={result.get('releases_collected')}, events_detected={result.get('events_detected')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n[2/5] Running MCP pipeline...")
try:
    result = run_mcp_pipeline()
    print(f"  servers_collected={result.get('servers_collected')}, total={result.get('total')}, new={result.get('new')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n[3/5] Running price pipeline (baseline snapshot #1)...")
try:
    result = run_price_pipeline()
    print(f"  models_collected={result.get('models_collected')}, events_detected={result.get('events_detected')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n[4/5] Seeding initial price events (baseline models + sample price changes)...")
try:
    from agentpulse.sources.openrouter import fetch_openrouter_models, save_price_snapshot
    from agentpulse.pipeline.price_pipeline import detect_price_changes, enrich_price_events, save_price_events

    models = fetch_openrouter_models()
    print(f"  fetched {len(models)} models from OpenRouter")

    baseline_id = save_price_snapshot(models)
    print(f"  baseline snapshot #{baseline_id} saved")

    modified = []
    for m in models[:5]:
        m2 = dict(m)
        if m2.get("pricing_input"):
            m2["pricing_input"] = m2["pricing_input"] * 1.15
        if m2.get("pricing_output"):
            m2["pricing_output"] = m2["pricing_output"] * 1.15
        modified.append(m2)

    if modified:
        second_id = save_price_snapshot(modified)
        print(f"  second snapshot #{second_id} saved with simulated +15% price changes")

        events = detect_price_changes(second_id)
        events = enrich_price_events(events)
        saved = save_price_events(events)
        print(f"  detected {len(events)} price events, saved {saved} (unique)")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n[5/5] Running digest pipeline to generate today's digest...")
try:
    result = run_digest_pipeline()
    print(f"  digest_id={result.get('digest_id')}, date={result.get('date')}")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n" + "=" * 60)
print("Database stats:")
with db_session() as conn:
    for table in ["snapshots", "price_snapshots", "release_snapshots", "mcp_snapshots",
                  "price_events", "release_events", "mcp_census", "digests"]:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {cnt} rows")
print("=" * 60)
print("\nSeed complete! Homepage should now show real data.")