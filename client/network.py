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
    auth_required        = pyqtSignal()        # HTTP 401 или WS close 4401
    auth_ok              = pyqtSignal(dict)    # ответ /auth/me: {"user_id","username"}

    def __init__(self, host: str, port: int) -> None:
        super().__init__()
        self._base    = f"http://{host}:{port}"
        self._ws_url  = f"ws://{host}:{port}/ws"
        self._loop:    Optional[asyncio.AbstractEventLoop] = None
        self._session: Optional[aiohttp.ClientSession]     = None
        self._running  = False
        self._thread:  Optional[threading.Thread]          = None
        # bumped on every stop(): a listener that outlived join(timeout=3)
        # sees the mismatch and exits instead of racing the new thread
        self._generation = 0
        self._token: Optional[str] = None
        # set on WS close 4401: the listener stops reconnecting until
        # set_token() is called (otherwise — infinite 4401 loop)
        self._auth_blocked = False

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._generation += 1
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def set_server(self, host: str, port: int) -> None:
        """Switch to a different server without restarting the app."""
        self.stop()
        if self._thread:
            self._thread.join(timeout=3)
        self._base   = f"http://{host}:{port}"
        self._ws_url = f"ws://{host}:{port}/ws"
        self._auth_blocked = False   # новый сервер — новая попытка
        self.start()

    def set_token(self, token: Optional[str]) -> None:
        """Set (or clear with None) the session token for HTTP and WS."""
        self._token = token
        self._auth_blocked = False   # снимаем блок реконнекта WS

    # ── background event loop ─────────────────────────────────────────────

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)

        async def _make_session() -> aiohttp.ClientSession:
            return aiohttp.ClientSession()

        session = loop.run_until_complete(_make_session())
        self._session = session
        try:
            loop.run_until_complete(self._ws_listener())
        except RuntimeError:
            pass   # loop.stop() interrupts run_until_complete
        finally:
            # loop.stop() skips any finally inside the coroutine, so close
            # this run's session here ("Unclosed client session" otherwise)
            if self._session is session:
                self._session = None
            try:
                loop.run_until_complete(session.close())
            except Exception:
                pass

    async def _ws_listener(self) -> None:
        generation = self._generation
        retry = 2.0
        while self._running and generation == self._generation:
            if self._auth_blocked:
                # 4401: не реконнектимся, пока не появится новый токен
                await asyncio.sleep(1.0)
                continue
            tok = self._token
            url = self._ws_url + (f"?token={tok}" if tok else "")
            try:
                async with websockets.connect(
                    url,
                    ping_interval=None,   # server sends JSON {"type":"ping"} every 25 s
                    open_timeout=10,
                ) as ws:
                    if generation != self._generation:
                        return
                    self.ws_connected.emit()
                    retry = 2.0
                    async for raw in ws:
                        if generation != self._generation:
                            return
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        msg_type = data.get("type")
                        if msg_type == "state_update":
                            self.state_updated.emit(data)
                        elif msg_type == "guilds_update":
                            # voice members changed — reuse the existing
                            # guilds_updated path to refresh the UI
                            guilds = data.get("guilds")
                            if isinstance(guilds, list):
                                self.guilds_updated.emit(guilds)
                        # "ping" messages from server are ignored (keepalive only)
            except websockets.exceptions.ConnectionClosed as e:
                rcvd = getattr(e, "rcvd", None)
                if rcvd is not None and getattr(rcvd, "code", None) == 4401:
                    # блокируем, только если токен не сменился, пока соединение
                    # жило (иначе 4401 по старому токену заблокирует новый)
                    if tok == self._token:
                        self._auth_blocked = True
                        self.auth_required.emit()
            except Exception:
                pass
            if self._running and generation == self._generation:
                self.ws_disconnected.emit()
                if self._auth_blocked:
                    continue          # наверх — ждать новый токен
                await asyncio.sleep(retry)
                retry = min(retry * 1.5, 30.0)

    # ── internal HTTP helpers ─────────────────────────────────────────────

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def _post(
        self, path: str, body: dict, timeout: float = 10,
        headers: Optional[dict] = None,
    ) -> Optional[dict]:
        if self._session is None:
            return None
        try:
            async with self._session.post(
                f"{self._base}{path}", json=body,
                headers=self._headers() if headers is None else headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as r:
                if r.status == 401:
                    self.auth_required.emit()
                    return None
                if r.status >= 400:
                    self.request_error.emit(f"Server error {r.status} on {path}")
                    return None
                return await r.json(content_type=None)
        except Exception as exc:
            self.request_error.emit(str(exc))
            return None

    async def _get(self, path: str, params: Optional[dict] = None) -> Optional[object]:
        if self._session is None:
            return None
        try:
            async with self._session.get(
                f"{self._base}{path}", params=params, headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 401:
                    self.auth_required.emit()
                    return None
                if r.status >= 400:
                    self.request_error.emit(f"Server error {r.status} on {path}")
                    return None
                return await r.json(content_type=None)
        except Exception as exc:
            self.request_error.emit(str(exc))
            return None

    def _submit(self, coro) -> None:
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ── public API (called from UI thread) ────────────────────────────────

    # auth
    def auth_me(self) -> None:
        """Validate the stored token; emits auth_ok(dict) or auth_required on 401."""
        async def _do() -> None:
            data = await self._get("/auth/me")
            if isinstance(data, dict):
                self.auth_ok.emit(data)
        self._submit(_do())

    def logout(self) -> None:
        # снапшот заголовка на момент вызова: set_token(None) сразу после
        # logout() не должен превратить запрос в неавторизованный
        headers = self._headers()
        self._submit(self._post("/auth/logout", {}, headers=headers))

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

    def play_playlist(self, guild_id: int, url: str) -> None:
        # Flat-extracting a 100-track playlist can exceed the default timeout
        self._submit(self._post("/playlist", {"guild_id": guild_id, "url": url}, timeout=30))

    def set_loop(self, guild_id: int, mode: str) -> None:
        """mode: "none" | "one" | "all"."""
        self._submit(self._post("/loop", {"guild_id": guild_id, "mode": mode}))

    # queue
    def shuffle(self, guild_id: int) -> None:
        self._submit(self._post("/shuffle", {"guild_id": guild_id}))

    def remove_from_queue(self, guild_id: int, index: int) -> None:
        self._submit(self._post("/queue/remove", {"guild_id": guild_id, "index": index}))

    def move_in_queue(self, guild_id: int, from_index: int, to_index: int) -> None:
        self._submit(self._post("/queue/move", {
            "guild_id": guild_id,
            "from_index": from_index,
            "to_index": to_index,
        }))
