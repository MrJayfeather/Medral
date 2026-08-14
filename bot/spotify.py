"""Spotify support without API keys.

Spotify streams can't be played directly, but the public embed page
(https://open.spotify.com/embed/{kind}/{id}) carries full track metadata in
its Next.js ``__NEXT_DATA__`` JSON blob. We parse titles/artists/durations
out of it and resolve the actual audio lazily through a YouTube/SoundCloud
search (see audio.get_stream_url).

The embed page structure (observed 2026-08):

    props.pageProps.state.data.entity = {
        "type": "track" | "playlist" | "album",
        "title": ..., "name": ...,
        "artists": [{"name": ...}, ...],          # track only
        "subtitle": "Artist1, Artist2",           # collections / list items
        "duration": <ms>,
        "trackList": [{...}, ...],                # collections only
        "visualIdentity": {"image": [{"url": ..., "maxWidth": ...}, ...]},
        "coverArt": {"sources": [{"url": ...}, ...]},
    }

Spotify reshuffles this periodically, so parsing is defensive: direct paths
first, recursive key search as a fallback.
"""

import asyncio
import json
import re
import urllib.request
from typing import List, Optional, Tuple

_SPOTIFY_URL_RE = re.compile(
    r"(?:https?://)?open\.spotify\.com/(?:intl-[\w-]+/)?"
    r"(track|playlist|album)/([A-Za-z0-9]+)"
)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

MAX_COLLECTION_TRACKS = 100


def is_spotify_url(url: str) -> bool:
    """True for open.spotify.com track/playlist/album URLs (intl-* included)."""
    return bool(_SPOTIFY_URL_RE.search(url.strip()))


# ------------------------------------------------------------------ fetching

def _fetch_embed_html(kind: str, item_id: str) -> str:
    """Blocking GET of the embed page (call via run_in_executor)."""
    url = f"https://open.spotify.com/embed/{kind}/{item_id}"
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept-Language": "en",
    })
    # urllib follows redirects by default
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")


# ------------------------------------------------------------------ parsing

def _extract_next_data(html: str) -> dict:
    m = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S
    )
    if not m:
        raise ValueError(
            "Spotify embed page has no __NEXT_DATA__ script — "
            "page layout changed or the item is unavailable"
        )
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Spotify embed __NEXT_DATA__ is not valid JSON: {exc}")


def _find_entity(node) -> Optional[dict]:
    """Recursive fallback: locate a dict that looks like the embed entity."""
    if isinstance(node, dict):
        if node.get("type") in ("track", "playlist", "album") and (
            "title" in node or "name" in node
        ):
            return node
        for value in node.values():
            found = _find_entity(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_entity(value)
            if found is not None:
                return found
    return None


def _clean(text) -> str:
    """Normalize non-breaking spaces Spotify puts between artist names."""
    return str(text or "").replace("\xa0", " ").strip()


def _best_image(entity: dict) -> str:
    """Largest available cover image URL, or ""."""
    images = (entity.get("visualIdentity") or {}).get("image") or []
    best_url, best_w = "", -1
    for img in images:
        if not isinstance(img, dict) or not img.get("url"):
            continue
        width = img.get("maxWidth") or 0
        if width > best_w:
            best_url, best_w = img["url"], width
    if best_url:
        return best_url
    for src in (entity.get("coverArt") or {}).get("sources") or []:
        if isinstance(src, dict) and src.get("url"):
            return src["url"]
    return ""


def _track_entity_to_meta(entity: dict) -> dict:
    """Meta dict from a single-track embed entity."""
    title = _clean(entity.get("title") or entity.get("name"))
    if not title:
        raise ValueError("Spotify track entity has no title — layout changed?")
    artists = entity.get("artists")
    names: List[str] = []
    if isinstance(artists, list):
        names = [
            _clean(a.get("name"))
            for a in artists
            if isinstance(a, dict) and a.get("name")
        ]
    artists_str = ", ".join(names) or _clean(entity.get("subtitle"))
    return {
        "title": title,
        "artists": artists_str,
        "duration_ms": int(entity.get("duration") or 0),
        "thumbnail": _best_image(entity),
    }


def _list_item_to_meta(item: dict, fallback_thumbnail: str) -> Optional[dict]:
    """Meta dict from one trackList item of a playlist/album embed."""
    if not isinstance(item, dict):
        return None
    title = _clean(item.get("title") or item.get("name"))
    if not title:
        return None
    return {
        "title": title,
        "artists": _clean(item.get("subtitle")),
        "duration_ms": int(item.get("duration") or 0),
        "thumbnail": _best_image(item) or fallback_thumbnail,
    }


# ------------------------------------------------------------------ public API

async def fetch_spotify(url: str) -> Tuple[str, List[dict]]:
    """Fetch metadata for a Spotify URL without any API credentials.

    Returns ("track", [meta]) or ("collection", [meta, ...]) where meta is
    {"title", "artists", "duration_ms", "thumbnail"}. Raises ValueError with
    a readable message when the URL or page structure is not recognized.
    """
    m = _SPOTIFY_URL_RE.search(url.strip())
    if not m:
        raise ValueError(f"not a Spotify track/playlist/album URL: {url!r}")
    kind, item_id = m.group(1), m.group(2)

    loop = asyncio.get_running_loop()
    html = await loop.run_in_executor(
        None, lambda: _fetch_embed_html(kind, item_id)
    )
    data = _extract_next_data(html)

    # Direct path first; recursive scan survives layout reshuffles
    entity = None
    try:
        entity = data["props"]["pageProps"]["state"]["data"]["entity"]
    except (KeyError, TypeError):
        entity = None
    if not isinstance(entity, dict):
        entity = _find_entity(data)
    if not isinstance(entity, dict):
        raise ValueError(
            f"could not locate {kind} metadata in Spotify embed page — "
            "layout changed?"
        )

    if kind == "track":
        return "track", [_track_entity_to_meta(entity)]

    track_list = entity.get("trackList")
    if not isinstance(track_list, list) or not track_list:
        raise ValueError(
            f"Spotify {kind} has no track list — private, empty, or "
            "layout changed?"
        )
    cover = _best_image(entity)
    metas: List[dict] = []
    for item in track_list[:MAX_COLLECTION_TRACKS]:
        meta = _list_item_to_meta(item, cover)
        if meta is not None:
            metas.append(meta)
    if not metas:
        raise ValueError(f"no parsable tracks in Spotify {kind}")
    return "collection", metas
