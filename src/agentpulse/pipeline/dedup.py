from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid", "gclid"}


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    query_parts = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0]
        if key.lower() in _TRACKING_PARAMS:
            continue
        query_parts.append(part)
    cleaned = parsed._replace(query="&".join(sorted(query_parts)), fragment="")
    return urlunparse(cleaned).rstrip("/")


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def _normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_tokens(title: str) -> set[str]:
    return set(_normalize_title(title).split())


def title_similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def cluster_by_title(items: list[dict], title_key: str = "title", threshold: float = 0.6) -> list[list[dict]]:
    clusters: list[list[dict]] = []
    for item in items:
        placed = False
        for cluster in clusters:
            rep = cluster[0].get(title_key, "")
            if title_similarity(rep, item.get(title_key, "")) >= threshold:
                cluster.append(item)
                placed = True
                break
        if not placed:
            clusters.append([item])
    return clusters


def dedup_items(items: list[dict], url_key: str = "url", title_key: str = "title") -> list[dict]:
    seen_hashes: set[str] = set()
    unique: list[dict] = []
    for item in items:
        h = url_hash(item.get(url_key, ""))
        if h and h in seen_hashes:
            continue
        if h:
            seen_hashes.add(h)
        unique.append(item)
    return unique