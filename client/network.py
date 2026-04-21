import asyncio
import json
import threading
from typing import Optional

import aiohttp
import websockets
from PyQt6.QtCore import QObject, pyqtSignal


class ApiClient(QObject):
    # ── inbound signals (background thread → UI thread) ──────────────────
    state_updated        = pyqtSignal(dict)
    guilds_updated       = pyqtSignal(list)
    search_results_ready = pyqtSignal(list)
    ws_connected         = pyqtSignal()
    ws_disconnected      = pyqtSignal()
    request_error        = pyqtSignal(str)

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self._base    = f"http://{host}:{port}"
        self._ws_url  = f"ws://{host}:{port}/ws"
        self._loop:    Optional[asyncio.AbstractEventLoop] = None
        self._session: Optional[aiohttp.ClientSession]     = None
        self._running  = False
        self._thread:  Optional[threading.Thread]          = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def set_server(self, host: str, port: int) -> None:
        """Switch to a different server without restarting the app."""
        self.stop()
        if self._thread:
            self._thread.join(timeout=3)
        self._base   = f"http://{host}:{port}"
        self._ws_url = f"ws://{host}:{port}/ws"
        self.start()

    # ── background event loop ─────────────────────────────────────────────

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_main())

    async def _async_main(self) -> None:
        self._session = aiohttp.ClientSession()
        try:
            await self._ws_listener()
        finally:
            await self._session.close()
            self._session = None

    async def _ws_listener(self) -> None:
        retry = 2.0
        while self._running:
            try:
                async with websockets.connect(
                    self._ws_url,
                    ping_interval=None,   # server sends JSON {"type":"ping"} every 25 s
                    open_timeout=10,
                ) as ws:
                    self.ws_connected.emit()
                    retry = 2.0
                    async for raw in ws:
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        msg_type = data.get("type")
                        if msg_type == "state_update":
                            self.state_updated.emit(data)
                        # "ping" messages from server are ignored (keepalive only)
            except Exception:
                pass
            if self._running:
                self.ws_disconnected.emit()
                await asyncio.sleep(retry)
                retry = min(retry * 1.5, 30.0)

    # ── internal HTTP helpers ─────────────────────────────────────────────

    async def _post(self, path: str, body: dict) -> Optional[dict]:
        if self._session is None:
            return None
        try:
            async with self._session.post(
                f"{self._base}{path}", json=body, timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                return await r.json()
        except Exception as exc:
            self.request_error.emit(str(exc))
            return None

    async def _get(self, path: str, params: Optional[dict] = None) -> Optional[object]:
        if self._session is None:
            return None
        try:
            async with self._session.get(
                f"{self._base}{path}", params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                return await r.json()
        except Exception as exc:
            self.request_error.emit(str(exc))
            return None

    def _submit(self, coro) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ── public API (called from UI thread) ────────────────────────────────

    def fetch_guilds(self) -> None:
        async def _do() -> None:
            data = await self._get("/guilds")
            if isinstance(data, list):
                self.guilds_updated.emit(data)
        self._submit(_do())

    def fetch_state(self, guild_id: int) -> None:
        async def _do() -> None:
            data = await self._get(f"/state/{guild_id}")
            if isinstance(data, dict):
                data["type"] = "state_update"
                self.state_updated.emit(data)
        self._submit(_do())

    def search(self, query: str, max_results: int = 5) -> None:
        async def _do() -> None:
            data = await self._get("/search", {"q": query, "max_results": max_results})
            if isinstance(data, list):
                self.search_results_ready.emit(data)
        self._submit(_do())

    # voice
    def join(self, guild_id: int, channel_id: int) -> None:
        self._submit(self._post("/join", {"guild_id": guild_id, "channel_id": channel_id}))

    def leave(self, guild_id: int) -> None:
        self._submit(self._post("/leave", {"guild_id": guild_id}))

    # playback
    def play(self, guild_id: int, query: str) -> None:
        self._submit(self._post("/play", {"guild_id": guild_id, "query": query}))

    def skip(self, guild_id: int) -> None:
        self._submit(self._post("/skip", {"guild_id": guild_id}))

    def previous(self, guild_id: int) -> None:
        self._submit(self._post("/previous", {"guild_id": guild_id}))

    def pause(self, guild_id: int) -> None:
        self._submit(self._post("/pause", {"guild_id": guild_id}))

    def resume(self, guild_id: int) -> None:
        self._submit(self._post("/resume", {"guild_id": guild_id}))

    def stop_playback(self, guild_id: int) -> None:
        self._submit(self._post("/stop", {"guild_id": guild_id}))

    def set_volume(self, guild_id: int, volume: float) -> None:
        self._submit(self._post("/volume", {"guild_id": guild_id, "volume": volume}))

    def seek(self, guild_id: int, position: float) -> None:
        self._submit(self._post("/seek", {"guild_id": guild_id, "position": position}))

    # queue
    def remove_from_queue(self, guild_id: int, index: int) -> None:
        self._submit(self._post("/queue/remove", {"guild_id": guild_id, "index": index}))

    def move_in_queue(self, guild_id: int, from_index: int, to_index: int) -> None:
        self._submit(self._post("/queue/move", {
            "guild_id": guild_id,
            "from_index": from_index,
            "to_index": to_index,
        }))
