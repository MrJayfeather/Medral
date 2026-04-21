import asyncio
import time
import yt_dlp
import discord
from dataclasses import dataclass
from typing import Optional, List, Callable, Awaitable
from collections import deque


YTDL_OPTS = {
    "format": "bestaudio[ext=webm]/bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
    "extract_flat": False,
}

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
    ),
    "options": "-vn -ar 48000 -ac 2",
}


@dataclass
class Track:
    webpage_url: str
    title: str
    artist: str
    duration: int       # seconds
    thumbnail: str

    def to_dict(self) -> dict:
        return {
            "webpage_url": self.webpage_url,
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
        }


async def _yt_extract(opts: dict, query: str) -> dict:
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(opts) as ydl:
        return await loop.run_in_executor(
            None, lambda: ydl.extract_info(query, download=False)
        )


def _entry_to_track(entry: dict) -> Track:
    return Track(
        webpage_url=entry.get("webpage_url") or entry.get("url", ""),
        title=entry.get("title", "Unknown Title"),
        artist=(
            entry.get("uploader")
            or entry.get("channel")
            or "Unknown Artist"
        ),
        duration=int(entry.get("duration") or 0),
        thumbnail=entry.get("thumbnail") or "",
    )


async def search_tracks(query: str, max_results: int = 5) -> List[Track]:
    if query.startswith("http://") or query.startswith("https://"):
        search_query = query
    else:
        search_query = f"ytsearch{max_results}:{query}"

    data = await _yt_extract(YTDL_OPTS, search_query)
    entries = data.get("entries", [data]) if "entries" in data else [data]
    return [_entry_to_track(e) for e in entries if e][:max_results]


async def get_stream_url(track: Track) -> str:
    data = await _yt_extract(YTDL_OPTS, track.webpage_url)
    return data.get("url", "")


class MusicPlayer:
    def __init__(
        self,
        guild_id: int,
        on_state_change: Callable[[int], Awaitable[None]],
    ):
        self.guild_id = guild_id
        self._on_state_change = on_state_change

        self.voice_client: Optional[discord.VoiceClient] = None
        self.queue: deque[Track] = deque()
        self.history: List[Track] = []
        self.current: Optional[Track] = None

        self._volume: float = 0.5
        self._paused: bool = False
        self._intentional_stop: bool = False
        self._seeking: bool = False

        # progress tracking
        self._play_started_at: float = 0.0
        self._pause_started_at: float = 0.0
        self._total_paused: float = 0.0
        self._current_stream_url: str = ""

    # ------------------------------------------------------------------ props

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def is_playing(self) -> bool:
        return self.voice_client is not None and self.voice_client.is_playing()

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def position(self) -> float:
        """Elapsed playback seconds (excludes pause time)."""
        if not self.current:
            return 0.0
        if self._paused:
            return self._pause_started_at - self._play_started_at - self._total_paused
        if self.is_playing:
            return time.time() - self._play_started_at - self._total_paused
        return 0.0

    # ------------------------------------------------------------------ queue

    async def enqueue(self, track: Track) -> None:
        self.queue.append(track)
        await self._on_state_change(self.guild_id)

    async def play_next(self) -> None:
        if not self.queue or not self.voice_client or not self.voice_client.is_connected():
            if self.current:
                self.history.append(self.current)
                self.current = None
            await self._on_state_change(self.guild_id)
            return

        if self.current:
            self.history.append(self.current)

        self.current = self.queue.popleft()
        self._paused = False
        self._total_paused = 0.0

        stream_url = await get_stream_url(self.current)
        self._current_stream_url = stream_url

        raw_source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(raw_source, volume=self._volume)

        self._play_started_at = time.time()
        loop = asyncio.get_running_loop()

        def _after(error: Optional[Exception]) -> None:
            if error:
                print(f"[audio] playback error: {error}")
            if not self._seeking:
                loop.create_task(self.play_next())

        self.voice_client.play(source, after=_after)
        await self._on_state_change(self.guild_id)

    # ------------------------------------------------------------------ controls

    def pause(self) -> None:
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.pause()
            self._paused = True
            self._pause_started_at = time.time()

    def resume(self) -> None:
        if self.voice_client and self.voice_client.is_paused():
            self.voice_client.resume()
            self._total_paused += time.time() - self._pause_started_at

    async def seek(self, position: float) -> None:
        if not self.current or not self.voice_client or not self.voice_client.is_connected():
            return
        if not self._current_stream_url:
            return
        position = max(0.0, position)

        self._seeking = True
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()
            await asyncio.sleep(0.15)  # let _after fire before we start new source

        seek_opts = {
            "before_options": (
                f"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {position:.2f}"
            ),
            "options": "-vn -ar 48000 -ac 2",
        }
        raw_source = discord.FFmpegPCMAudio(self._current_stream_url, **seek_opts)
        source = discord.PCMVolumeTransformer(raw_source, volume=self._volume)

        self._play_started_at = time.time() - position
        self._total_paused = 0.0
        self._paused = False
        self._seeking = False

        loop = asyncio.get_running_loop()

        def _after(error: Optional[Exception]) -> None:
            if error:
                print(f"[audio] playback error: {error}")
            if not self._seeking:
                loop.create_task(self.play_next())

        self.voice_client.play(source, after=_after)
        await self._on_state_change(self.guild_id)

    def skip(self) -> None:
        if self.voice_client and (
            self.voice_client.is_playing() or self.voice_client.is_paused()
        ):
            self.voice_client.stop()  # triggers _after -> play_next

    async def previous(self) -> None:
        if not self.history:
            return
        prev = self.history.pop()
        if self.current:
            self.queue.appendleft(self.current)
        self.queue.appendleft(prev)
        if self.voice_client and (
            self.voice_client.is_playing() or self.voice_client.is_paused()
        ):
            self.voice_client.stop()
        else:
            await self.play_next()

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        if (
            self.voice_client
            and self.voice_client.source
            and isinstance(self.voice_client.source, discord.PCMVolumeTransformer)
        ):
            self.voice_client.source.volume = self._volume

    # ------------------------------------------------------------------ queue ops

    def remove_from_queue(self, index: int) -> bool:
        q = list(self.queue)
        if 0 <= index < len(q):
            q.pop(index)
            self.queue = deque(q)
            return True
        return False

    def move_in_queue(self, from_index: int, to_index: int) -> bool:
        q = list(self.queue)
        n = len(q)
        if 0 <= from_index < n and 0 <= to_index < n:
            item = q.pop(from_index)
            q.insert(to_index, item)
            self.queue = deque(q)
            return True
        return False

    # ------------------------------------------------------------------ lifecycle

    async def stop_and_disconnect(self) -> None:
        self._intentional_stop = True
        self.queue.clear()
        if self.voice_client:
            if self.voice_client.is_playing() or self.voice_client.is_paused():
                self.voice_client.stop()
            await self.voice_client.disconnect()
            self.voice_client = None
        self.current = None
        self._paused = False
        await self._on_state_change(self.guild_id)

    # ------------------------------------------------------------------ state

    def get_state(self) -> dict:
        return {
            "guild_id": str(self.guild_id),
            "current": self.current.to_dict() if self.current else None,
            "position": round(self.position, 1),
            "queue": [t.to_dict() for t in self.queue],
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "volume": self._volume,
            "voice_channel_id": (
                str(self.voice_client.channel.id)
                if self.voice_client and self.voice_client.channel
                else None
            ),
        }
