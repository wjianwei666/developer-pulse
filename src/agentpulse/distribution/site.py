from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr

from ..config import PROJECT_ROOT, settings
from ..db import db_session
from ..governance.cost_control import rate_limiter
from ..pipeline.digest import get_digest, list_digests

TEMPLATES_DIR = PROJECT_ROOT / "src" / "agentpulse" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app = FastAPI(title="AgentPulse", version="0.1.0")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/api/"):
        key = f"{_client_key(request)}:{request.url.path}"
        if not rate_limiter.is_allowed(key):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again later."},
            )
    return await call_next(request)


class SubscribeRequest(BaseModel):
    email: EmailStr


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    digests = list_digests(limit=10)
    with db_session() as conn:
        recent_price = conn.execute(
            "SELECT * FROM price_events ORDER BY detected_at DESC LIMIT 10"
        ).fetchall()
        recent_release = conn.execute(
            "SELECT * FROM release_events ORDER BY detected_at DESC LIMIT 10"
        ).fetchall()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "digests": digests,
            "recent_price": [dict(r) for r in recent_price],
            "recent_release": [dict(r) for r in recent_release],
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )


@app.get("/digest/{digest_date}", response_class=HTMLResponse)
def digest_detail(request: Request, digest_date: str):
    data = get_digest(digest_date)
    if not data:
        raise HTTPException(status_code=404, detail="Digest not found")
    return templates.TemplateResponse(
        "digest.html",
        {"request": request, "digest": data, "digest_date": digest_date},
    )


@app.get("/price", response_class=HTMLResponse)
def price_page(request: Request, model: str | None = None, limit: int = Query(100, le=500)):
    with db_session() as conn:
        if model:
            rows = conn.execute(
                "SELECT * FROM price_events WHERE model_id LIKE ? ORDER BY detected_at DESC LIMIT ?",
                (f"%{model}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM price_events ORDER BY detected_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return templates.TemplateResponse(
        "price.html",
        {"request": request, "events": [dict(r) for r in rows], "model_filter": model},
    )


@app.get("/ecosystem", response_class=HTMLResponse)
def ecosystem_page(request: Request, repo: str | None = None, limit: int = Query(100, le=500)):
    with db_session() as conn:
        if repo:
            rows = conn.execute(
                "SELECT * FROM release_events WHERE repo LIKE ? ORDER BY detected_at DESC LIMIT ?",
                (f"%{repo}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM release_events ORDER BY detected_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return templates.TemplateResponse(
        "ecosystem.html",
        {"request": request, "events": [dict(r) for r in rows], "repo_filter": repo},
    )


@app.get("/api/digest/{digest_date}")
def api_digest(digest_date: str):
    data = get_digest(digest_date)
    if not data:
        raise HTTPException(status_code=404, detail="Digest not found")
    return JSONResponse(data)


@app.get("/api/events/price")
def api_price_events(limit: int = Query(50, le=200)):
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM price_events ORDER BY detected_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/events/release")
def api_release_events(limit: int = Query(50, le=200)):
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM release_events ORDER BY detected_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/events/search")
def api_search(q: str = Query(..., min_length=2), limit: int = Query(30, le=100)):
    pattern = f"%{q}%"
    with db_session() as conn:
        price_rows = conn.execute(
            """SELECT 'price' AS kind, model_id AS title, event_type, field_name,
                      CAST(change_pct AS TEXT) AS detail, impact_score, detected_at
               FROM price_events
               WHERE model_id LIKE ? OR field_name LIKE ?
               ORDER BY detected_at DESC LIMIT ?""",
            (pattern, pattern, limit),
        ).fetchall()
        release_rows = conn.execute(
            """SELECT 'release' AS kind, repo AS title, breaking_grade AS event_type,
                      tag AS field_name, deadline AS detail, impact_score, detected_at
               FROM release_events
               WHERE repo LIKE ? OR tag LIKE ? OR migration_steps LIKE ?
               ORDER BY detected_at DESC LIMIT ?""",
            (pattern, pattern, pattern, limit),
        ).fetchall()
    return {
        "query": q,
        "results": [dict(r) for r in price_rows] + [dict(r) for r in release_rows],
        "count": len(price_rows) + len(release_rows),
    }


@app.get("/api/trends/{model_id}")
def api_trends(model_id: str):
    with db_session() as conn:
        rows = conn.execute(
            """SELECT ps.snapshot_id, ps.pricing_input, ps.pricing_output,
                      ps.pricing_cache_read, s.created_at
               FROM price_snapshots ps
               JOIN snapshots s ON ps.snapshot_id = s.id
               WHERE ps.model_id = ?
               ORDER BY s.id ASC""",
            (model_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="Model not found in snapshots")
    trends = []
    for r in rows:
        point = {"snapshot_id": r["snapshot_id"], "created_at": r["created_at"]}
        for field in ("pricing_input", "pricing_output", "pricing_cache_read"):
            point[field] = r[field]
        trends.append(point)
    return {"model_id": model_id, "trends": trends, "points": len(trends)}


@app.get("/trends", response_class=HTMLResponse)
def trends_page(request: Request, model: str = Query(...)):
    return templates.TemplateResponse(
        "trends.html",
        {"request": request, "model_id": model},
    )


@app.get("/api/mcp/census")
def api_mcp_census(limit: int = Query(10, le=50)):
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM mcp_census ORDER BY recorded_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/rss.xml", response_class=Response)
def rss_feed():
    from .rss import build_rss

    xml = build_rss()
    return Response(content=xml, media_type="application/rss+xml")


@app.get("/search.html", response_class=HTMLResponse)
def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})


@app.post("/api/subscribe")
def subscribe(payload: SubscribeRequest):
    import secrets

    email = payload.email
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with db_session() as conn:
            conn.execute(
                """INSERT INTO subscribers (email, tier, status, confirm_token, created_at)
                   VALUES (?, 'free', 'pending', ?, ?)""",
                (email, token, now),
            )
    except Exception:
        return {"status": "already_subscribed", "email": email}
    confirm_url = f"/api/confirm?token={token}"
    return {"status": "confirmation_sent", "email": email, "confirm_url": confirm_url}


@app.get("/api/confirm")
def confirm_subscription(token: str = Query(...)):
    now = datetime.now(timezone.utc).isoformat()
    with db_session() as conn:
        cur = conn.execute(
            "UPDATE subscribers SET status='confirmed', confirmed_at=? WHERE confirm_token=? AND status='pending'",
            (now, token),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=400, detail="Invalid or already used token")
    return {"status": "confirmed"}


@app.post("/api/unsubscribe")
def unsubscribe(email: str = Query(...)):
    with db_session() as conn:
        cur = conn.execute(
            "DELETE FROM subscribers WHERE email = ?",
            (email,),
        )
        if cur.rowcount == 0:
            return {"status": "not_found", "email": email}
    return {"status": "unsubscribed", "email": email}


@app.get("/auth/github/login")
def github_login(request: Request):
    if not settings.github_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
    from urllib.parse import urlencode
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": settings.github_oauth_redirect_uri,
        "scope": "read:user user:email",
        "state": "agentpulse",
    }
    url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return {"login_url": url}


@app.get("/auth/github/callback")
def github_callback(code: str = Query(...)):
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
    import secrets
    import httpx

    token_resp = httpx.post(
        "https://github.com/login/oauth/access_token",
        json={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": settings.github_oauth_redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=15,
    )
    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="OAuth token exchange failed")

    user_resp = httpx.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        timeout=15,
    )
    user_data = user_resp.json()
    github_login = user_data.get("login", "")
    user_email = user_data.get("email") or f"{github_login}@users.noreply.github.com"

    now = datetime.now(timezone.utc).isoformat()
    token = secrets.token_urlsafe(32)
    try:
        with db_session() as conn:
            existing = conn.execute(
                "SELECT id, github_login FROM subscribers WHERE email = ?", (user_email,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE subscribers SET github_login=?, status='confirmed', confirmed_at=? WHERE id=?",
                    (github_login, now, existing["id"]),
                )
                session_token = existing["id"]
            else:
                cur = conn.execute(
                    "INSERT INTO subscribers (email, tier, status, confirm_token, github_login, created_at, confirmed_at)"
                    " VALUES (?, 'free', 'confirmed', ?, ?, ?, ?)",
                    (user_email, token, github_login, now, now),
                )
                session_token = cur.lastrowid
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save user")

    return {
        "status": "authenticated",
        "github_login": github_login,
        "email": user_email,
    }


@app.post("/api/keys/generate")
def generate_api_key(email: str = Query(...)):
    import secrets
    with db_session() as conn:
        sub = conn.execute(
            "SELECT id, status FROM subscribers WHERE email = ?", (email,)
        ).fetchone()
        if not sub:
            raise HTTPException(status_code=404, detail="Subscriber not found")
        if sub["status"] != "confirmed":
            raise HTTPException(status_code=403, detail="Email not confirmed")
        api_key = f"ap_{secrets.token_urlsafe(32)}"
        conn.execute(
            "UPDATE subscribers SET api_key = ? WHERE id = ?", (api_key, sub["id"])
        )
    return {"api_key": api_key}


@app.get("/health")
def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


def create_app() -> FastAPI:
    return app