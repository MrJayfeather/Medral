import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator

import bot as music_bot

load_dotenv()

TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")
API_HOST: str = os.getenv("API_HOST", "0.0.0.0")
API_PORT: int = int(os.getenv("API_PORT", "8000"))


# ------------------------------------------------------------------ WebSocket manager

class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, data: dict) -> None:
        if not self._connections:
            return
        payload = json.dumps(data, ensure_ascii=False)
        dead: set[WebSocket] = set()
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


async def _broadcast_state(guild_id: int, state: dict) -> None:
    await manager.broadcast({"type": "state_update", **state})


# ------------------------------------------------------------------ lifespan

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN is not set. Check your .env file.")

    music_bot.set_broadcast_callback(_broadcast_state)
    bot_task = asyncio.create_task(music_bot.bot.start(TOKEN))
    print(f"[api] HTTP server running on {API_HOST}:{API_PORT}")
    print("[api] Discord bot connecting...")

    try:
        yield
    finally:
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
async def get_guilds():
    """List all guilds the bot is in, with their voice channels."""
    return music_bot.get_guilds()


@app.get("/state/{guild_id}")
async def get_state(guild_id: int):
    """Full player state for a guild."""
    state = await music_bot.api_get_state(guild_id)
    return state if state is not None else _empty_state(guild_id)


# ------------------------------------------------------------------ voice channel control

@app.post("/join")
async def join(body: JoinBody):
    return _ok_or_raise(await music_bot.api_join(body.guild_id, body.channel_id))


@app.post("/leave")
async def leave(body: GuildBody):
    return await music_bot.api_leave(body.guild_id)


# ------------------------------------------------------------------ playback control

@app.post("/play")
async def play(body: PlayBody):
    return _ok_or_raise(await music_bot.api_play(body.guild_id, body.query))


@app.post("/skip")
async def skip(body: GuildBody):
    return await music_bot.api_skip(body.guild_id)


@app.post("/previous")
async def previous(body: GuildBody):
    return await music_bot.api_previous(body.guild_id)


@app.post("/pause")
async def pause(body: GuildBody):
    return await music_bot.api_pause(body.guild_id)


@app.post("/resume")
async def resume(body: GuildBody):
    return await music_bot.api_resume(body.guild_id)


@app.post("/stop")
async def stop(body: GuildBody):
    return await music_bot.api_stop(body.guild_id)


@app.post("/volume")
async def set_volume(body: VolumeBody):
    return await music_bot.api_set_volume(body.guild_id, body.volume)


# ------------------------------------------------------------------ search

@app.get("/search")
async def search(q: str, max_results: int = 5):
    """Search YouTube for tracks. Returns list of track objects."""
    if not q.strip():
        raise HTTPException(status_code=422, detail="query 'q' must not be empty")
    results = await music_bot.api_search(q, max_results=min(max_results, 10))
    return results


# ------------------------------------------------------------------ queue

@app.get("/queue/{guild_id}")
async def get_queue(guild_id: int):
    state = await music_bot.api_get_state(guild_id)
    if state is None:
        return {"current": None, "queue": []}
    return {"current": state.get("current"), "queue": state.get("queue", [])}


@app.post("/queue/move")
async def move_in_queue(body: QueueMoveBody):
    return await music_bot.api_move_in_queue(body.guild_id, body.from_index, body.to_index)


@app.post("/queue/remove")
async def remove_from_queue(body: QueueRemoveBody):
    return await music_bot.api_remove_from_queue(body.guild_id, body.index)


# ------------------------------------------------------------------ WebSocket

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    print(f"[ws] client connected ({manager.count} total)")

    try:
        # Send current state for every known guild immediately on connect
        for player in music_bot.get_all_players().values():
            await ws.send_text(
                json.dumps({"type": "state_update", **player.get_state()}, ensure_ascii=False)
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
