import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentpulse.db import init_db, db_session

init_db()
with db_session() as conn:
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print("Tables created:", [t["name"] for t in tables])
    for t in tables:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {t['name']}").fetchone()[0]
        print(f"  {t['name']}: {cnt} rows")

print("DB init OK")

from agentpulse.distribution.site import create_app
app = create_app()
print("FastAPI app created:", app.title, app.version)

from fastapi.testclient import TestClient
client = TestClient(app)
resp = client.get("/health")
print("GET /health:", resp.status_code, resp.json())

resp = client.get("/")
print("GET /:", resp.status_code)
assert resp.status_code == 200

resp = client.get("/rss.xml")
print("GET /rss.xml:", resp.status_code, resp.headers.get("content-type"))
assert resp.status_code == 200

resp = client.get("/api/events/price")
print("GET /api/events/price:", resp.status_code, len(resp.json()), "items")

print("All integration checks passed!")