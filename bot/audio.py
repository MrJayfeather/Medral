import asyncio
import hashlib
import os
import random
import tempfile
import time
import urllib.request
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
    "options": "-vn",  # FFmpegPCMAudio appends -f s16le -ar 48000 -ac 2 itself
}


@dataclass
class Track:
    webpage_url: str
    title: str
    artist: str
    duration: int       # seconds
    thumbnail: str
    # Lazily-resolved tracks (e.g. from Spotify metadata) have an empty
    # webpage_url and a text query to search on YouTube/SoundCloud instead.
    search_query: str = ""
    source: str = "youtube"

    def to_dict(self) -> dict:
        return {
            "webpage_url": self.webpage_url,
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "source": self.source,
        }


async def _yt_extract(opts: dict, query: str) -> dict:
    loop = asyncio.get_running_loop()
    with yt_dlp.YoutubeDL(opts) as ydl:
        return await loop.run_in_executor(
            None, lambda: ydl.extract_info(query, download=False)
        )


def _entry_to_track(entry: dict) -> Track:
    # NB: .get(key, default) does NOT protect against explicit None values —
    # deleted/private playlist entries come with "title": None
    return Track(
        webpage_url=entry.get("webpage_url") or entry.get("url") or "",
        title=str(entry.get("title") or "Unknown Title"),
        artist=str(
            entry.get("uploader")
            or entry.get("channel")
            or "Unknown Artist"
        ),
        duration=int(entry.get("duration") or 0),
        thumbnail=entry.get("thumbnail") or "",
    )


def is_playlist_url(query: str) -> bool:
    """True for URLs that reference a whole playlist rather than a single track."""
    if "open.spotify.com" in query:
        # Spotify URLs are routed through the spotify module before this
        # check — never let /playlist|/album Spotify links reach yt-dlp.
        return False
    return (
        query.startswith("http")
        and ("list=" in query or "/playlist" in query or "/album" in query)
    )


async def _run_search(opts: dict, search_query: str, max_results: int) -> List[Track]:
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
            t = _entry_to_track(e)
        except Exception as exc:
            print(f"[search] entry parse error: {exc}")
            continue
        if not t.thumbnail:
            # Flat entries carry a "thumbnails" list instead of "thumbnail"
            thumbs = e.get("thumbnails") or []
            if thumbs:
                t.thumbnail = thumbs[-1].get("url", "")
        tracks.append(t)
    return tracks[:max_results]


async def search_tracks(query: str, max_results: int = 5) -> List[Track]:
    is_url = query.startswith("http://") or query.startswith("https://")
    if is_url:
        search_query = query
        opts = YTDL_OPTS          # URL — нужна полная инфа
    else:
        search_query = f"ytsearch{max_results}:{query}"
        opts = YTDL_SEARCH_OPTS   # текстовый запрос — плоский, быстрый

    tracks = await _run_search(opts, search_query, max_results)

    if is_url and "soundcloud.com" in query:
        # Correct the source label for directly pasted SoundCloud links
        for t in tracks:
            t.source = "soundcloud"

    if not tracks and not is_url:
        # Zero YouTube hits for a text query — retry the search on SoundCloud
        tracks = await _run_search(
            YTDL_SEARCH_OPTS, f"scsearch{max_results}:{query}", max_results
        )
        for t in tracks:
            t.source = "soundcloud"
    return tracks


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
        # Deleted/private videos: title is None or a placeholder, no duration
        raw_title = e.get("title")
        if raw_title in ("[Deleted video]", "[Private video]") or (
            raw_title is None and not e.get("duration")
        ):
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


async def _resolve_lazy_track(track: Track) -> str:
    """Resolve a lazily-defined track (Spotify metadata) to a stream URL.

    Full extraction of "ytsearch1:{query}" first, SoundCloud as fallback.
    On success the track is mutated in place (webpage_url, thumbnail if it
    was empty, source set to the service that actually matched) and the
    direct stream URL is returned. Raises if neither service has a match —
    play_next() then skips the track like any other dead entry.
    """
    for prefix, source in (("ytsearch1:", "youtube"), ("scsearch1:", "soundcloud")):
        try:
            data = await _yt_extract(YTDL_OPTS, f"{prefix}{track.search_query}")
        except Exception as exc:
            print(f"[audio] lazy resolve via {source} failed "
                  f"for {track.search_query!r}: {exc}")
            continue

        entry = None
        if data:
            if "entries" in data:
                entries = data.get("entries") or []
                entry = entries[0] if entries else None
            else:
                entry = data
        if not entry:
            continue

        stream_url = entry.get("url", "")
        if not stream_url:
            continue

        # webpage_url keys the local audio cache — an empty one would make
        # every lazy track collide on md5("") in the cache dir
        resolved_url = entry.get("webpage_url") or entry.get("original_url") or ""
        if not resolved_url:
            continue
        track.webpage_url = resolved_url
        if not track.thumbnail:
            track.thumbnail = entry.get("thumbnail") or ""
        if not track.duration:
            track.duration = int(entry.get("duration") or 0)
        track.source = source
        return stream_url

    raise RuntimeError(
        f"no playable source found for {track.search_query!r} "
        "(YouTube and SoundCloud searches came up empty)"
    )


async def get_stream_url(track: Track) -> str:
    if not track.webpage_url and track.search_query:
        return await _resolve_lazy_track(track)
    data = await _yt_extract(YTDL_OPTS, track.webpage_url)
    return data.get("url", "")


# ------------------------------------------------------------------ local cache
# YouTube paces long streams down to ~realtime after an initial burst, which
# starves FFmpeg a few minutes into long tracks (audible stutter). The VPS
# pulls from googlevideo at tens of MB/s, so a full pre-download is ~1 s and
# makes playback (and seeking) completely independent of YouTube's pacing.

AUDIO_CACHE_DIR = os.path.join(tempfile.gettempdir(), "medral_audio")
MAX_CACHE_FILE_BYTES = 250 * 1024 * 1024   # bigger than this → stream directly
DOWNLOAD_TIMEOUT = 30          # s; beyond this fall back to direct streaming
DOWNLOAD_CHUNK = 10 * 1024 * 1024  # googlevideo bursts per-request: ranged
                                   # chunks dodge its ~realtime pacing
PREBUFFER_MIN_DURATION = 8 * 60    # only long tracks suffer from pacing —
                                   # short ones start instantly via streaming


def _purge_cache(max_age: float = 6 * 3600) -> None:
    try:
        now = time.time()
        for name in os.listdir(AUDIO_CACHE_DIR):
            path = os.path.join(AUDIO_CACHE_DIR, name)
            if now - os.path.getmtime(path) > max_age:
                os.remove(path)
    except OSError:
        pass


def _download_to_cache(url: str, key: str) -> str:
    """Blocking download of the full audio stream into the cache dir.

    Downloads in separate ranged requests: googlevideo serves each request
    with an initial fast burst, then throttles to ~realtime — one sequential
    read of a 25-minute track takes minutes, ranged 10MB chunks take seconds.
    """
    os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)
    _purge_cache()
    path = os.path.join(AUDIO_CACHE_DIR, key)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    tmp_path = path + ".part"
    pos = 0
    total = None   # unknown until the first response tells us
    stall_retries = 0
    with open(tmp_path, "wb") as f:
        while total is None or pos < total:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0",
                "Range": f"bytes={pos}-{pos + DOWNLOAD_CHUNK - 1}",
            })
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
                if total is None:
                    # "Content-Range: bytes 0-999/23814570" → full size;
                    # a plain 200 means ranges are unsupported — trust
                    # Content-Length instead.
                    crange = resp.headers.get("Content-Range", "")
                    if "/" in crange:
                        total = int(crange.rsplit("/", 1)[1])
                    elif resp.status == 200:
                        total = int(resp.headers.get("Content-Length") or len(data))
                    if total > MAX_CACHE_FILE_BYTES:
                        raise ValueError("stream too large to cache")
            if not data:
                # Server can close a response early — retry the same offset a
                # few times before giving up
                stall_retries += 1
                if stall_retries > 5:
                    raise IOError(f"download stalled at {pos}/{total}")
                continue
            stall_retries = 0
            f.write(data)
            pos += len(data)
    if total is not None and pos < total:
        raise IOError(f"incomplete download: {pos}/{total}")
    os.replace(tmp_path, path)
    return path


async def download_track(stream_url: str, track: Track) -> Optional[str]:
    """Pre-download audio to disk; None on any failure (caller streams)."""
    key = hashlib.md5(track.webpage_url.encode()).hexdigest()[:16] + ".audio"
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: _download_to_cache(stream_url, key)),
            timeout=DOWNLOAD_TIMEOUT,
        )
    except Exception as exc:
        print(f"[audio] cache download failed ({exc}); falling back to streaming")
        return None


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
        # Serializes play_next/seek — a seek arriving while the next track is
        # still downloading must not spawn a second concurrent audio source.
        self._play_lock = asyncio.Lock()

        # progress tracking
        self._play_started_at: float = 0.0
        self._pause_started_at: float = 0.0
        self._total_paused: float = 0.0
        self._current_stream_url: str = ""
        self._current_file: Optional[str] = None   # local cache copy, if any

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
        async with self._play_lock:
            await self._play_next_locked()

    async def _play_next_locked(self) -> None:
        if not self.voice_client or not self.voice_client.is_connected():
            if self.current:
                self.history.append(self.current)
                self.current = None
            await self._on_state_change(self.guild_id)
            return

        # A stacked/late play_next (queued while another one was downloading
        # or seeking) must not restart or steal an already-active source.
        if self.voice_client.is_playing() or self.voice_client.is_paused():
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

        # Loop (not recursion): unavailable tracks are dropped into history
        # and the next queued one is tried, so one dead track can't wedge
        # the queue or cycle forever under loop one/all.
        while True:
            if not self.queue:
                await self._on_state_change(self.guild_id)
                return

            self.current = self.queue.popleft()
            self._paused = False
            self._total_paused = 0.0

            try:
                stream_url = await get_stream_url(self.current)
                self._current_stream_url = stream_url

                # Only long tracks are pre-downloaded — they are the ones
                # YouTube's stream pacing starves mid-play. duration 0 means
                # unknown (possibly live) — stream those directly too.
                local = None
                if 0 < self.current.duration and self.current.duration >= PREBUFFER_MIN_DURATION:
                    local = await download_track(stream_url, self.current)

                old_file = self._current_file
                self._current_file = local
                if old_file and old_file != local:
                    try:
                        os.remove(old_file)
                    except OSError:
                        pass

                if local:
                    raw_source = discord.FFmpegPCMAudio(local, options="-vn")
                else:
                    raw_source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS)
                source = discord.PCMVolumeTransformer(raw_source, volume=self._volume)
                break
            except Exception as exc:
                print(f"[audio] cannot play {self.current.title}: {exc}")
                self.history.append(self.current)
                self.current = None

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
        async with self._play_lock:
            await self._seek_locked(position)

    async def _seek_locked(self, position: float) -> None:
        if not self.current or not self.voice_client or not self.voice_client.is_connected():
            return
        if not self._current_file and not self._current_stream_url:
            return
        position = max(0.0, position)
        if self.current.duration > 0:
            position = min(position, self.current.duration - 1)

        self._seeking = True
        if self.voice_client.is_playing() or self.voice_client.is_paused():
            self.voice_client.stop()
            await asyncio.sleep(0.15)  # let _after fire before we start new source

        if self._current_file:
            # Local cache copy — instant seek, no risk of a stale stream URL
            seek_opts = {
                "before_options": f"-ss {position:.2f}",
                "options": "-vn",
            }
            seek_target = self._current_file
        else:
            seek_opts = {
                "before_options": (
                    f"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {position:.2f}"
                ),
                "options": "-vn",
            }
            seek_target = self._current_stream_url
        raw_source = discord.FFmpegPCMAudio(seek_target, **seek_opts)
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
        if self._current_file:
            try:
                os.remove(self._current_file)
            except OSError:
                pass
            self._current_file = None
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
