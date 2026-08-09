import asyncio
import random
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

# Faster opts for search — flat extraction skips visiting each video page
YTDL_SEARCH_OPTS = {
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
    "extract_flat": True,
}

# Playlist opts — flat like search, but playlist expansion is allowed
YTDL_PLAYLIST_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "source_address": "0.0.0.0",
    "extract_flat": "in_playlist",   # metadata only, no per-video stream URLs
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
    loop = asyncio.get_running_loop()
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


def is_playlist_url(query: str) -> bool:
    """True for URLs that reference a whole playlist rather than a single track."""
    return (
        query.startswith("http")
        and ("list=" in query or "/playlist" in query or "/album" in query)
    )


async def search_tracks(query: str, max_results: int = 5) -> List[Track]:
    if query.startswith("http://") or query.startswith("https://"):
        search_query = query
        opts = YTDL_OPTS          # URL — нужна полная инфа
    else:
        search_query = f"ytsearch{max_results}:{query}"
        opts = YTDL_SEARCH_OPTS   # текстовый запрос — плоский, быстрый

    try:
        data = await _yt_extract(opts, search_query)
    except Exception as exc:
        print(f"[search] yt-dlp error for {search_query!r}: {exc}")
        return []

    if not data:
        return []

    entries = data.get("entries", [data]) if "entries" in data else [data]
    tracks = []
    for e in entries:
        if not e:
            continue
        try:
            tracks.append(_entry_to_track(e))
        except Exception as exc:
            print(f"[search] entry parse error: {exc}")
    return tracks[:max_results]


async def load_playlist(url: str, max_tracks: int = 100) -> List[Track]:
    """Extract all tracks from a playlist URL (flat — no stream URLs yet)."""
    try:
        data = await _yt_extract(YTDL_PLAYLIST_OPTS, url)
    except Exception as exc:
        print(f"[playlist] yt-dlp error for {url!r}: {exc}")
        return []

    if not data:
        return []

    entries = data.get("entries") or []
    tracks: List[Track] = []
    for e in entries:
        if not e:
            continue
        try:
            t = _entry_to_track(e)
        except Exception as exc:
            print(f"[playlist] entry parse error: {exc}")
            continue
        if not t.webpage_url:
            continue
        if not t.thumbnail:
            # Flat entries carry a "thumbnails" list instead of "thumbnail"
            thumbs = e.get("thumbnails") or []
            if thumbs:
                t.thumbnail = thumbs[-1].get("url", "")
        tracks.append(t)
        if len(tracks) >= max_tracks:
            break
    return tracks


async def get_stream_url(track: Track) -> str:
    data = await _yt_extract(YTDL_OPTS, track.webpage_url)
    return data.get("url", "")


# Loop modes
LOOP_NONE = "none"
LOOP_ONE = "one"
LOOP_ALL = "all"
LOOP_MODES = (LOOP_NONE, LOOP_ONE, LOOP_ALL)


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
        self.loop_mode: str = LOOP_NONE

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

    async def enqueue_many(self, tracks: List[Track]) -> None:
        self.queue.extend(tracks)
        await self._on_state_change(self.guild_id)

    async def play_next(self) -> None:
        if not self.voice_client or not self.voice_client.is_connected():
            if self.current:
                self.history.append(self.current)
                self.current = None
            await self._on_state_change(self.guild_id)
            return

        # Route the finished track according to loop mode. current may already
        # be None here (previous() clears it before stopping the source).
        if self.current:
            if self.loop_mode == LOOP_ONE:
                # Replay the same track — back to the front, not into history
                self.queue.appendleft(self.current)
            elif self.loop_mode == LOOP_ALL:
                # Cycle the finished track to the end of the queue
                self.queue.append(self.current)
            else:
                self.history.append(self.current)
            self.current = None

        if not self.queue:
            await self._on_state_change(self.guild_id)
            return

        self.current = self.queue.popleft()
        self._paused = False
        self._total_paused = 0.0

        try:
            stream_url = await get_stream_url(self.current)
            self._current_stream_url = stream_url

            raw_source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
            source = discord.PCMVolumeTransformer(raw_source, volume=self._volume)
        except Exception as exc:
            # Track unavailable (deleted, age-restricted, ...) — drop it into
            # history and skip to the next one. Dropping (instead of letting
            # the loop logic re-queue it) keeps a dead track from cycling
            # forever under loop one/all. Recursion is safe: the queue is
            # finite and shrinks each call.
            print(f"[audio] cannot play {self.current.title}: {exc}")
            self.history.append(self.current)
            self.current = None
            await self.play_next()
            return

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
            self._paused = False
            self._total_paused += time.time() - self._pause_started_at

    async def seek(self, position: float) -> None:
        if not self.current or not self.voice_client or not self.voice_client.is_connected():
            return
        if not self._current_stream_url:
            return
        position = max(0.0, position)
        if self.current.duration > 0:
            position = min(position, self.current.duration - 1)

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

        loop = asyncio.get_running_loop()

        def _after(error: Optional[Exception]) -> None:
            if error:
                print(f"[audio] playback error: {error}")
            if not self._seeking:
                loop.create_task(self.play_next())

        self.voice_client.play(source, after=_after)
        # Reset only after play() — a slow-dying old FFmpeg fires its _after
        # late, and with the flag still set it won't spawn a stray play_next.
        self._seeking = False
        await self._on_state_change(self.guild_id)

    def skip(self) -> None:
        if self.voice_client and (
            self.voice_client.is_playing() or self.voice_client.is_paused()
        ):
            if self.loop_mode == LOOP_ONE and self.current:
                # Manual skip should advance even in repeat-one mode
                self.history.append(self.current)
                self.current = None
            self.voice_client.stop()  # triggers _after -> play_next

    async def previous(self) -> None:
        if not self.history:
            return
        prev = self.history.pop()
        if self.current:
            self.queue.appendleft(self.current)
            # Already back in the queue — clear it so play_next doesn't
            # append it to history a second time.
            self.current = None
        self.queue.appendleft(prev)
        if self.voice_client and (
            self.voice_client.is_playing() or self.voice_client.is_paused()
        ):
            self.voice_client.stop()
        else:
            await self.play_next()

    async def shuffle(self) -> None:
        q = list(self.queue)
        random.shuffle(q)
        self.queue = deque(q)
        await self._on_state_change(self.guild_id)

    def set_loop(self, mode: str) -> None:
        if mode not in LOOP_MODES:
            raise ValueError(f"unknown loop mode: {mode!r}")
        self.loop_mode = mode

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
        self.queue.clear()
        if self.voice_client:
            # Set the flag only when a real disconnect will follow — the flag
            # is consumed by on_voice_state_update, and without a disconnect
            # it would linger and mask the next unexpected drop as intentional.
            if self.voice_client.is_connected():
                self._intentional_stop = True
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
            "loop_mode": self.loop_mode,
            "voice_channel_id": (
                str(self.voice_client.channel.id)
                if self.voice_client and self.voice_client.channel
                else None
            ),
        }
