import asyncio
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import aiohttp
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, field_validator

import bot as music_bot

load_dotenv()

# Session tokens travel in the WS query string; uvicorn's access log would
# otherwise persist them into journalctl for their whole 30-day lifetime.
import logging as _logging
import re as _re


class _RedactTokenFilter(_logging.Filter):
    def filter(self, record: _logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "token=" in msg:
            record.msg = _re.sub(r"token=[^\s&\"']+", "token=***", msg)
            record.args = ()
        return True


for _name in ("uvicorn.access", "uvicorn.error"):
    _logging.getLogger(_name).addFilter(_RedactTokenFilter())

TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))

# Discord OAuth2 (desktop client login). Missing values disable /auth/login
# with 503 instead of crashing the server.
DISCORD_CLIENT_ID: Optional[str] = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET: Optional[str] = os.getenv("DISCORD_CLIENT_SECRET")
PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

DISCORD_API = "https://discord.com/api"

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_EXE = REPO_ROOT / "dist" / "MedralPlayer.exe"
SESSIONS_FILE = REPO_ROOT / "sessions.json"

STATE_TTL = 600                 # seconds an OAuth state stays valid
SESSION_TTL = 30 * 24 * 3600    # session lifetime — 30 days


# ------------------------------------------------------------------ WebSocket manager

class ConnectionManager:
    def __init__(self) -> None:
        # ws -> guild ids (str) whose state updates this connection may receive
        self._connections: dict[WebSocket, set[str]] = {}

    async def connect(self, ws: WebSocket, allowed_guild_ids: set[str]) -> None:
        await ws.accept()
        self._connections[ws] = allowed_guild_ids

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.pop(ws, None)

    async def broadcast(self, data: dict) -> None:
        if not self._connections:
            return
        # state_update carries guild_id (str) — deliver only to members
        guild_id = data.get("guild_id") if data.get("type") == "state_update" else None
        payload = json.dumps(data, ensure_ascii=False)
        dead: list[WebSocket] = []
        # Iterate over a copy — connect/disconnect may mutate the dict while
        # we await inside the loop.
        for ws, allowed in list(self._connections.items()):
            if guild_id is not None and guild_id not in allowed:
                continue
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.pop(ws, None)

    async def send_guilds_update(self, guilds: list[dict]) -> None:
        """Push {"type": "guilds_update"} to every connection, each payload
        filtered down to the guilds that connection is allowed to see."""
        if not self._connections:
            return
        dead: list[WebSocket] = []
        # Iterate over a copy — connect/disconnect may mutate the dict while
        # we await inside the loop.
        for ws, allowed in list(self._connections.items()):
            filtered = [g for g in guilds if g["id"] in allowed]
            payload = json.dumps(
                {"type": "guilds_update", "guilds": filtered}, ensure_ascii=False
            )
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.pop(ws, None)

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


async def _broadcast_state(guild_id: int, state: dict) -> None:
    await manager.broadcast({"type": "state_update", **state})


# ------------------------------------------------------------------ guilds_update debounce

GUILDS_UPDATE_DEBOUNCE = 1.0  # seconds

# pending debounced guilds_update broadcast (cancelled by each new event)
_guilds_update_task: Optional[asyncio.Task] = None


async def _debounced_guilds_update() -> None:
    try:
        await asyncio.sleep(GUILDS_UPDATE_DEBOUNCE)
    except asyncio.CancelledError:
        return
    await manager.send_guilds_update(music_bot.get_guilds())


def _on_voice_topology_changed() -> None:
    """Sync callback from bot.on_voice_state_update — restarts the debounce."""
    global _guilds_update_task
    old = _guilds_update_task
    if old is not None and not old.done():
        old.cancel()
    _guilds_update_task = asyncio.get_running_loop().create_task(
        _debounced_guilds_update()
    )


# ------------------------------------------------------------------ auth: sessions & OAuth state

# state -> {"created_at": float, "result": Optional[dict]} — result appears
# after the OAuth callback succeeds and is handed to the client exactly once.
_pending_states: dict[str, dict] = {}
# session_token -> {"user_id": str, "username": str, "created_at": float}
_sessions: dict[str, dict] = {}


def _load_sessions() -> None:
    if not SESSIONS_FILE.exists():
        return
    try:
        data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[auth] failed to load {SESSIONS_FILE.name}: {exc}")
        return
    now = time.time()
    for token, sess in data.items():
        if isinstance(sess, dict) and now - sess.get("created_at", 0) < SESSION_TTL:
            _sessions[token] = sess
    print(f"[auth] loaded {len(_sessions)} session(s)")


def _save_sessions() -> None:
    # Atomic write: tmp file + replace, so a crash never corrupts the store
    tmp = SESSIONS_FILE.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(_sessions, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, SESSIONS_FILE)
    except OSError as exc:
        print(f"[auth] failed to save {SESSIONS_FILE.name}: {exc}")


def _prune_expired() -> None:
    now = time.time()
    expired = [t for t, s in _sessions.items() if now - s.get("created_at", 0) >= SESSION_TTL]
    for token in expired:
        del _sessions[token]
    if expired:
        _save_sessions()
    stale = [s for s, e in _pending_states.items() if now - e["created_at"] >= STATE_TTL]
    for state in stale:
        del _pending_states[state]


def _session_for_token(token: str) -> Optional[dict]:
    sess = _sessions.get(token)
    if sess is None:
        return None
    if time.time() - sess.get("created_at", 0) >= SESSION_TTL:
        del _sessions[token]
        _save_sessions()
        return None
    return sess


async def get_session(request: Request) -> dict:
    """FastAPI dependency: resolve Authorization: Bearer <token> to a session."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        sess = _session_for_token(token)
        if sess is not None:
            return {"token": token, **sess}
    raise HTTPException(status_code=401, detail="unauthorized")


async def _require_member(session: dict, guild_id: int) -> None:
    if not await music_bot.api_is_member(guild_id, int(session["user_id"])):
        raise HTTPException(status_code=403, detail="not a member of this guild")


async def _require_same_channel(session: dict, guild_id: int) -> None:
    """403 unless the user sits in the bot's current voice channel.

    When the bot is not connected at all, control falls through to the
    endpoint's own handling (e.g. 400 "bot not in a voice channel").
    """
    bot_channel = music_bot.api_bot_voice_channel_id(guild_id)
    if bot_channel is None:
        return
    user_channel = music_bot.api_user_voice_channel_id(guild_id, int(session["user_id"]))
    if user_channel != bot_channel:
        raise HTTPException(status_code=403, detail="you must be in the bot's voice channel")


def _auth_page(title: str, message: str, status_code: int = 200) -> HTMLResponse:
    html = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Medral</title>
<style>
  body {{ margin: 0; min-height: 100vh; display: flex; align-items: center;
         justify-content: center; background: #14101d; color: #e6e0f0;
         font-family: "Segoe UI", Arial, sans-serif; }}
  .card {{ text-align: center; padding: 40px 48px; background: #241a35;
           border-radius: 16px; box-shadow: 0 8px 32px rgba(0,0,0,.45); }}
  h1 {{ font-size: 22px; margin: 0 0 10px; color: #b48cff; }}
  p  {{ margin: 0; font-size: 15px; opacity: .85; }}
</style></head>
<body><div class="card"><h1>{title}</h1><p>{message}</p></div></body></html>"""
    return HTMLResponse(html, status_code=status_code)


# ------------------------------------------------------------------ lifespan

async def _keepalive_loop() -> None:
    """Sends a JSON ping every 25 s and a position update every 10 s."""
    tick = 0
    while True:
        await asyncio.sleep(5)
        tick += 1
        if not manager.count:
            continue
        if tick % 5 == 0:          # every 25 s — application-level keepalive
            await manager.broadcast({"type": "ping"})
        if tick % 2 == 0:          # every 10 s — position sync while playing
            for player in music_bot.get_all_players().values():
                if player.is_playing:
                    await manager.broadcast(
                        {"type": "state_update", **player.get_state()}
                    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set. Check your .env file.")

    # py-cord captures the event loop at Bot.__init__ time (module import).
    # Rebind all loop references to uvicorn's actual running loop so that
    # voice connect tasks don't land on a different loop.
    loop = asyncio.get_running_loop()
    music_bot.bot.loop = loop
    music_bot.bot.http.loop = loop
    music_bot.bot._connection.loop = loop

    _load_sessions()
    music_bot.set_broadcast_callback(_broadcast_state)
    music_bot.set_voice_topology_callback(_on_voice_topology_changed)
    bot_task        = asyncio.create_task(music_bot.bot.start(TOKEN))
    keepalive_task  = asyncio.create_task(_keepalive_loop())
    print(f"[api] HTTP server running on {API_HOST}:{API_PORT}")
    print("[api] Discord bot connecting...")

    try:
        yield
    finally:
        keepalive_task.cancel()
        if _guilds_update_task is not None and not _guilds_update_task.done():
            _guilds_update_task.cancel()
        bot_task.cancel()
        if not music_bot.bot.is_closed():
            await music_bot.bot.close()
        try:
            await bot_task
        except (asyncio.CancelledError, Exception):
            pass
        print("[api] shutdown complete")


# ------------------------------------------------------------------ app

app = FastAPI(title="Medral API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------ helpers

def _ok_or_raise(result: dict) -> dict:
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "operation failed"))
    return result


def _empty_state(guild_id: int) -> dict:
    return {
        "guild_id": str(guild_id),
        "current": None,
        "position": 0.0,
        "queue": [],
        "is_playing": False,
        "is_paused": False,
        "volume": 0.5,
        "loop_mode": "none",
        "voice_channel_id": None,
    }


# ------------------------------------------------------------------ request bodies

class JoinBody(BaseModel):
    guild_id: int
    channel_id: int


class PlayBody(BaseModel):
    guild_id: int
    query: str


class GuildBody(BaseModel):
    guild_id: int


class SeekBody(BaseModel):
    guild_id: int
    position: float  # seconds


class VolumeBody(BaseModel):
    guild_id: int
    volume: float   # 0.0 – 1.0

    @field_validator("volume")
    @classmethod
    def _check_volume(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("volume must be between 0.0 and 1.0")
        return v


class QueueMoveBody(BaseModel):
    guild_id: int
    from_index: int
    to_index: int


class QueueRemoveBody(BaseModel):
    guild_id: int
    index: int


class LoopBody(BaseModel):
    guild_id: int
    mode: str   # "none" | "one" | "all"

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in ("none", "one", "all"):
            raise ValueError("mode must be 'none', 'one' or 'all'")
        return v


class PlaylistBody(BaseModel):
    guild_id: int
    url: str


# ------------------------------------------------------------------ auth endpoints

@app.get("/auth/login")
async def auth_login(state: str):
    """Entry point of the OAuth2 flow — redirects the browser to Discord."""
    if not (DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET and PUBLIC_BASE_URL):
        raise HTTPException(status_code=503, detail="oauth not configured")
    if not state.strip():
        raise HTTPException(status_code=422, detail="state must not be empty")
    _prune_expired()
    _pending_states[state] = {"created_at": time.time(), "result": None}
    params = urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "response_type": "code",
        "scope": "identify",
        "redirect_uri": f"{PUBLIC_BASE_URL}/auth/callback",
        "state": state,
    })
    return RedirectResponse(f"https://discord.com/oauth2/authorize?{params}", status_code=302)


@app.get("/auth/callback")
async def auth_callback(code: str = "", state: str = "", error: str = ""):
    """Discord redirects here; exchanges the code and stores the session."""
    _prune_expired()
    entry = _pending_states.get(state)
    if entry is None:
        return _auth_page("Ошибка входа",
                          "Неизвестный или истёкший запрос авторизации. "
                          "Попробуй войти из приложения ещё раз.", status_code=400)
    if error or not code:
        return _auth_page("Ошибка входа",
                          "Discord отклонил авторизацию. Попробуй ещё раз.",
                          status_code=400)

    try:
        async with aiohttp.ClientSession() as http:
            # 1. code -> access_token
            async with http.post(
                f"{DISCORD_API}/oauth2/token",
                data={
                    "client_id": DISCORD_CLIENT_ID,
                    "client_secret": DISCORD_CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": f"{PUBLIC_BASE_URL}/auth/callback",
                },
            ) as resp:
                if resp.status != 200:
                    print(f"[auth] token exchange failed: HTTP {resp.status}")
                    return _auth_page("Ошибка входа",
                                      "Discord не подтвердил авторизацию. Попробуй ещё раз.",
                                      status_code=400)
                token_data = await resp.json()

            access_token = token_data.get("access_token")
            if not access_token:
                return _auth_page("Ошибка входа",
                                  "Discord не выдал токен доступа. Попробуй ещё раз.",
                                  status_code=400)

            # 2. who is this?
            async with http.get(
                f"{DISCORD_API}/users/@me",
                headers={"Authorization": f"Bearer {access_token}"},
            ) as resp:
                if resp.status != 200:
                    print(f"[auth] users/@me failed: HTTP {resp.status}")
                    return _auth_page("Ошибка входа",
                                      "Не удалось получить профиль Discord. Попробуй ещё раз.",
                                      status_code=400)
                user = await resp.json()
    except aiohttp.ClientError as exc:
        print(f"[auth] Discord API request failed: {exc}")
        return _auth_page("Ошибка входа",
                          "Не удалось связаться с Discord. Попробуй ещё раз.",
                          status_code=502)

    session_token = secrets.token_urlsafe(32)
    sess = {
        "user_id": str(user["id"]),
        "username": user.get("username", ""),
        "created_at": time.time(),
    }
    _sessions[session_token] = sess
    _save_sessions()
    entry["result"] = {
        "token": session_token,
        "user_id": sess["user_id"],
        "username": sess["username"],
    }
    print(f"[auth] user {sess['username']} ({sess['user_id']}) logged in")
    return _auth_page("Готово!", "Вернись в приложение Medral.")


@app.get("/auth/poll")
async def auth_poll(state: str):
    """Client polls this until the browser part of the flow completes."""
    _prune_expired()
    entry = _pending_states.get(state)
    if entry is None:
        raise HTTPException(status_code=404, detail="unknown or expired state")
    if entry["result"] is None:
        return {"status": "pending"}
    # Hand the token out exactly once
    del _pending_states[state]
    return {"status": "ok", **entry["result"]}


@app.get("/auth/me")
async def auth_me(session: dict = Depends(get_session)):
    return {"user_id": session["user_id"], "username": session["username"]}


@app.post("/auth/logout")
async def auth_logout(session: dict = Depends(get_session)):
    _sessions.pop(session["token"], None)
    _save_sessions()
    return {"ok": True}


# ------------------------------------------------------------------ info endpoints

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "bot_ready": not music_bot.bot.is_closed(),
        "ws_clients": manager.count,
        "guilds": len(music_bot.bot.guilds),
    }


@app.get("/guilds")
async def get_guilds(session: dict = Depends(get_session)):
    """Guilds the bot is in AND the user is a member of, with voice channels."""
    user_id = int(session["user_id"])
    return [
        g for g in music_bot.get_guilds()
        if await music_bot.api_is_member(int(g["id"]), user_id)
    ]


@app.get("/state/{guild_id}")
async def get_state(guild_id: int, session: dict = Depends(get_session)):
    """Full player state for a guild."""
    await _require_member(session, guild_id)
    state = await music_bot.api_get_state(guild_id)
    return state if state is not None else _empty_state(guild_id)


# ------------------------------------------------------------------ voice channel control

@app.post("/join")
async def join(body: JoinBody, session: dict = Depends(get_session)):
    # The user must already sit in the target voice channel
    user_channel = music_bot.api_user_voice_channel_id(body.guild_id, int(session["user_id"]))
    if user_channel != body.channel_id:
        raise HTTPException(status_code=403, detail="join the voice channel first")
    return _ok_or_raise(await music_bot.api_join(body.guild_id, body.channel_id))


@app.post("/leave")
async def leave(body: GuildBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_leave(body.guild_id)


# ------------------------------------------------------------------ playback control

@app.post("/play")
async def play(body: PlayBody, session: dict = Depends(get_session)):
    """Play a track. Playlist URLs are detected and enqueued as a whole."""
    await _require_same_channel(session, body.guild_id)
    return _ok_or_raise(await music_bot.api_play(body.guild_id, body.query))


@app.post("/playlist")
async def play_playlist(body: PlaylistBody, session: dict = Depends(get_session)):
    """Load a whole playlist by URL and enqueue all its tracks."""
    await _require_same_channel(session, body.guild_id)
    return _ok_or_raise(await music_bot.api_play_playlist(body.guild_id, body.url))


@app.post("/skip")
async def skip(body: GuildBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_skip(body.guild_id)


@app.post("/previous")
async def previous(body: GuildBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_previous(body.guild_id)


@app.post("/pause")
async def pause(body: GuildBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_pause(body.guild_id)


@app.post("/resume")
async def resume(body: GuildBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_resume(body.guild_id)


@app.post("/stop")
async def stop(body: GuildBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_stop(body.guild_id)


@app.post("/volume")
async def set_volume(body: VolumeBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_set_volume(body.guild_id, body.volume)


@app.post("/seek")
async def seek(body: SeekBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_seek(body.guild_id, body.position)


@app.post("/shuffle")
async def shuffle(body: GuildBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return _ok_or_raise(await music_bot.api_shuffle(body.guild_id))


@app.post("/loop")
async def set_loop(body: LoopBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return _ok_or_raise(await music_bot.api_set_loop(body.guild_id, body.mode))


# ------------------------------------------------------------------ search

@app.get("/search")
async def search(q: str, max_results: int = 5, session: dict = Depends(get_session)):
    """Search YouTube for tracks. Returns list of track objects."""
    if not q.strip():
        raise HTTPException(status_code=422, detail="query 'q' must not be empty")
    max_results = max(1, min(max_results, 10))
    results = await music_bot.api_search(q, max_results=max_results)
    return results


# ------------------------------------------------------------------ queue

@app.get("/queue/{guild_id}")
async def get_queue(guild_id: int, session: dict = Depends(get_session)):
    await _require_member(session, guild_id)
    state = await music_bot.api_get_state(guild_id)
    if state is None:
        return {"current": None, "queue": []}
    return {"current": state.get("current"), "queue": state.get("queue", [])}


@app.post("/queue/move")
async def move_in_queue(body: QueueMoveBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_move_in_queue(body.guild_id, body.from_index, body.to_index)


@app.post("/queue/remove")
async def remove_from_queue(body: QueueRemoveBody, session: dict = Depends(get_session)):
    await _require_same_channel(session, body.guild_id)
    return await music_bot.api_remove_from_queue(body.guild_id, body.index)


# ------------------------------------------------------------------ client auto-update

@app.get("/version")
async def get_version():
    """Latest client version and whether a client build is available."""
    version_file = REPO_ROOT / "version.txt"
    version = version_file.read_text(encoding="utf-8").strip() if version_file.exists() else ""
    return {"client": version, "client_available": CLIENT_EXE.exists()}


@app.get("/update/client")
async def download_client():
    """Download the latest client executable."""
    if not CLIENT_EXE.exists():
        raise HTTPException(status_code=404, detail="client build not available")
    return FileResponse(CLIENT_EXE, filename="MedralPlayer.exe")


# ------------------------------------------------------------------ WebSocket

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, token: str = ""):
    sess = _session_for_token(token) if token else None
    if sess is None:
        # Accept the handshake so the client actually sees close code 4401
        await ws.accept()
        await ws.close(code=4401)
        return

    # Guilds whose updates this connection may receive (member-only)
    user_id = int(sess["user_id"])
    allowed = {
        str(g.id) for g in music_bot.bot.guilds
        if await music_bot.api_is_member(g.id, user_id)
    }

    await manager.connect(ws, allowed)
    print(f"[ws] client connected ({manager.count} total)")

    try:
        # Send current state for every allowed guild immediately on connect
        for player in music_bot.get_all_players().values():
            state = player.get_state()
            if state.get("guild_id") not in allowed:
                continue
            await ws.send_text(
                json.dumps({"type": "state_update", **state}, ensure_ascii=False)
            )

        # Keep connection alive; incoming messages are ignored (REST handles commands).
        # receive_text() raises WebSocketDisconnect when client closes.
        while True:
            await ws.receive_text()

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        print(f"[ws] unexpected error: {exc}")
    finally:
        manager.disconnect(ws)
        print(f"[ws] client disconnected ({manager.count} total)")


# ------------------------------------------------------------------ entry point

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host=API_HOST, port=API_PORT, reload=False)
