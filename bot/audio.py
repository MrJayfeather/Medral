import asyncio
import audioop
import hashlib
import math
import os
import random
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
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

# Single-pass (dynamic) loudness normalization applied on the fly. One-pass
# loudnorm can't hit the exact integrated target a two-pass run would, but it
# evens out quiet/loud tracks well enough for live playback.
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"

# ------------------------------------------------------------------ crossfade
# Overlapped track transitions: near the end of the current track the next
# source is pre-spawned and mixed in with equal-power gain curves.

CROSSFADE_SEC = 6
SKIP_FADE_SEC = 0.5
FRAME_BYTES = 3840              # 20 ms of 48 kHz s16le stereo
FRAMES_PER_SEC = 50
CROSSFADE_FRAMES = CROSSFADE_SEC * FRAMES_PER_SEC        # 300
SKIP_FADE_FRAMES = int(SKIP_FADE_SEC * FRAMES_PER_SEC)   # 25
CROSSFADE_PREPARE_LEAD = 5      # s before the overlap point to start preparing

DEFAULT_SETTINGS = {"normalize": True, "radio": False, "crossfade": False}


def _ffmpeg_output_opts(player: "MusicPlayer") -> str:
    """FFmpeg output options for every audio source this player spawns.

    Always strips video (-vn); adds the loudnorm filter when the per-guild
    "normalize" setting is enabled. Used by play_next (local file + stream)
    and seek (both variants) so the filter string lives in one place.
    """
    if player.settings.get("normalize"):
        return f"-vn -af {LOUDNORM_FILTER}"
    return "-vn"


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
            # Needed to persist lazily-resolved (Spotify) tracks across
            # restarts; the desktop client simply ignores unknown fields.
            "search_query": self.search_query,
            "source": self.source,
        }


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def track_from_dict(d: dict) -> Track:
    """Inverse of Track.to_dict(): rebuild a Track from a plain dict.

    Every field falls back to a sensible default so partially-written or
    older state files never crash the restore path.
    """
    return Track(
        webpage_url=str(d.get("webpage_url") or ""),
        title=str(d.get("title") or "Unknown Title"),
        artist=str(d.get("artist") or "Unknown Artist"),
        duration=_safe_int(d.get("duration")),
        thumbnail=str(d.get("thumbnail") or ""),
        search_query=str(d.get("search_query") or ""),
        source=str(d.get("source") or "youtube"),
    )


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
    # Unique tmp name: a background prefetch and a foreground play_next may
    # download the same key concurrently — each writes its own tmp file and
    # the atomic replace below makes the last complete copy win. Leftover
    # .part files are swept by _purge_cache.
    tmp_path = f"{path}.{uuid.uuid4().hex[:8]}.part"
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


# ------------------------------------------------------------------ radio mode

RADIO_ENQUEUE_COUNT = 5          # related tracks appended per radio refill
RADIO_MIX_FETCH_LIMIT = 25       # RD mixes serve ~25 entries; fetch them all
                                 # so filtering out repeats still leaves picks


def _youtube_video_id(url: str) -> str:
    """Video id from a YouTube watch URL ('' for non-YouTube/unparseable)."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return ""
    host = parsed.netloc.lower()
    if host.endswith("youtu.be"):
        return parsed.path.lstrip("/").split("/")[0]
    if "youtube.com" not in host:
        return ""
    values = urllib.parse.parse_qs(parsed.query).get("v") or []
    return values[0] if values else ""


# Loop modes
LOOP_NONE = "none"
LOOP_ONE = "one"
LOOP_ALL = "all"
LOOP_MODES = (LOOP_NONE, LOOP_ONE, LOOP_ALL)


@dataclass
class PreparedNext:
    """Next-track source spawned ahead of time for a crossfade."""
    track: Track
    raw: discord.AudioSource      # FFmpegPCMAudio, process already spawned
    stream_url: str
    file: Optional[str]           # local cache copy, if any


class CrossfadeSource(discord.AudioSource):
    """Pass-through mixer wrapped around every raw FFmpeg source.

    Outside a fade it forwards frames from the current source untouched
    (zero overhead). During a crossfade it mixes the outgoing and incoming
    sources with equal-power gain curves; during a skip/stop fade it only
    attenuates the current source down to silence.

    read() runs on the voice send thread with a 20 ms budget and must never
    raise. The mutating entry points run on the event loop; the lock guards
    only pointer/counter swaps and is held for microseconds.
    """

    def __init__(self, current: discord.AudioSource):
        self._lock = threading.Lock()
        self._current: Optional[discord.AudioSource] = current
        self._next: Optional[discord.AudioSource] = None
        self._gains: List[tuple] = []       # (gain_out, gain_in) per frame
        self._fade_pos: int = 0
        self._fade_out_only: bool = False
        self._current_eof: bool = False
        self._next_eof: bool = False
        self._on_done: Optional[Callable[[discord.AudioSource], None]] = None

    @staticmethod
    def _gain_table(frames: int) -> List[tuple]:
        # Equal-power curves sampled at frame centers: summed power
        # gain_out^2 + gain_in^2 == 1 across the whole fade.
        return [
            (
                math.cos((i + 0.5) / frames * math.pi / 2),
                math.sin((i + 0.5) / frames * math.pi / 2),
            )
            for i in range(frames)
        ]

    def start_fade(
        self,
        nxt: discord.AudioSource,
        frames: int,
        on_done: Callable[[discord.AudioSource], None],
    ) -> None:
        """Begin mixing `nxt` in over `frames` frames (event-loop side).

        on_done receives the displaced current source once the fade completes;
        it is invoked from the send thread and must only hand off elsewhere.
        """
        table = self._gain_table(frames)
        with self._lock:
            self._next = nxt
            self._gains = table
            self._fade_pos = 0
            self._fade_out_only = False
            self._current_eof = False
            self._next_eof = False
            self._on_done = on_done

    def start_fade_out(self, frames: int) -> None:
        """Fade the current source to silence, then report EOF."""
        table = self._gain_table(frames)
        with self._lock:
            self._next = None
            self._gains = table
            self._fade_pos = 0
            self._fade_out_only = True
            self._current_eof = False
            self._next_eof = False
            self._on_done = None

    def is_fading(self) -> bool:
        with self._lock:
            return bool(self._gains)

    @staticmethod
    def _pad(buf: bytes) -> bytes:
        # audioop.add() requires equal-length fragments — zero-fill the last
        # short frame a dying source hands out.
        if 0 < len(buf) < FRAME_BYTES:
            return buf + b"\x00" * (FRAME_BYTES - len(buf))
        return buf

    @staticmethod
    def _safe_read(src: Optional[discord.AudioSource]) -> bytes:
        if src is None:
            return b""
        try:
            return src.read()
        except Exception as exc:
            print(f"[crossfade] source read error: {exc}")
            return b""

    def read(self) -> bytes:
        with self._lock:
            gains = self._gains
            pos = self._fade_pos
            fade_out_only = self._fade_out_only
            cur = self._current
            nxt = self._next

        if not gains:
            # No fade in progress — plain pass-through.
            return self._safe_read(cur)

        if fade_out_only:
            if pos >= len(gains):
                return b""
            a = self._safe_read(cur)
            if not a:
                return b""
            with self._lock:
                self._fade_pos = pos + 1
            return audioop.mul(self._pad(a), 2, gains[pos][0])

        # Full crossfade: mix the outgoing (A) and incoming (B) sources.
        # The eof flags are only touched by this (send) thread during a fade.
        a = b""
        if not self._current_eof:
            a = self._safe_read(cur)
            if not a:
                self._current_eof = True
            elif len(a) < FRAME_BYTES:
                self._current_eof = True   # short frame — EOF from next read on

        b = b""
        if not self._next_eof:
            b = self._safe_read(nxt)
            if not b:
                self._next_eof = True
            elif len(b) < FRAME_BYTES:
                self._next_eof = True

        if not b:
            # The incoming source died right after the fade started — cancel
            # the fade and let the outgoing one play out normally; play_next
            # then advances past the dead track (accepted degradation).
            with self._lock:
                self._next = None
                self._gains = []
                self._fade_pos = 0
                self._on_done = None
            if nxt is not None:
                try:
                    nxt.cleanup()
                except Exception:
                    pass
            print("[crossfade] next source died mid-fade; "
                  "falling back to a plain transition")
            return a

        g_out, g_in = gains[pos]
        if not a:
            # Outgoing track ended early (overstated duration) — keep the
            # incoming one on its fade-in curve so there is no volume jump.
            out = audioop.mul(self._pad(b), 2, g_in)
        else:
            out = audioop.add(
                audioop.mul(self._pad(a), 2, g_out),
                audioop.mul(self._pad(b), 2, g_in),
                2,
            )

        pos += 1
        if pos >= len(gains):
            # Fade complete — promote the incoming source to current.
            with self._lock:
                old = self._current
                self._current = self._next
                self._next = None
                self._gains = []
                self._fade_pos = 0
                self._current_eof = False
                self._next_eof = False
                on_done = self._on_done
                self._on_done = None
            if on_done is not None:
                try:
                    on_done(old)
                except Exception as exc:
                    print(f"[crossfade] on_done callback error: {exc}")
        else:
            with self._lock:
                self._fade_pos = pos
        return out

    def cleanup(self) -> None:
        # Called by the AudioPlayer thread on vc.stop() — killing the ffmpeg
        # processes from that thread is what py-cord does today anyway.
        with self._lock:
            cur = self._current
            nxt = self._next
            self._current = None
            self._next = None
            self._gains = []
            self._fade_pos = 0
            self._on_done = None
        for src in (cur, nxt):
            if src is not None:
                try:
                    src.cleanup()
                except Exception:
                    pass


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
        # Per-guild playback settings, persisted across restarts by bot.py
        self.settings: dict = dict(DEFAULT_SETTINGS)
        # Serializes play_next/seek — a seek arriving while the next track is
        # still downloading must not spawn a second concurrent audio source.
        self._play_lock = asyncio.Lock()
        # Background prefetch of the upcoming track (one task per player)
        self._prefetch_task: Optional[asyncio.Task] = None
        # Crossfade machinery: the per-track pass-through mixer, the
        # pre-spawned next source and the monitor task arming the overlap
        self._mixer: Optional[CrossfadeSource] = None
        self._next_prepared: Optional[PreparedNext] = None
        self._crossfade_task: Optional[asyncio.Task] = None

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

        # The monitor watching the finished track is stale now, and a
        # prepared source that no longer matches the queue head must not
        # leak its ffmpeg process (stop / queue mutations).
        if self._crossfade_task is not None and not self._crossfade_task.done():
            self._crossfade_task.cancel()
        if self._next_prepared is not None and (
            not self.queue or self.queue[0] is not self._next_prepared.track
        ):
            self._discard_prepared()

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

            prepared = self._next_prepared
            if prepared is not None and prepared.track is self.current:
                # A source prepared for a crossfade that never started —
                # reuse it for an instant plain transition.
                self._next_prepared = None
                self._current_stream_url = prepared.stream_url
                old_file = self._current_file
                self._current_file = prepared.file
                if old_file and old_file != prepared.file:
                    try:
                        os.remove(old_file)
                    except OSError:
                        pass
                raw_source = prepared.raw
                break

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
                    raw_source = discord.FFmpegPCMAudio(
                        local, options=_ffmpeg_output_opts(self)
                    )
                else:
                    raw_source = discord.FFmpegPCMAudio(
                        stream_url,
                        before_options=FFMPEG_OPTIONS["before_options"],
                        options=_ffmpeg_output_opts(self),
                    )
                break
            except Exception as exc:
                print(f"[audio] cannot play {self.current.title}: {exc}")
                self.history.append(self.current)
                self.current = None

        # Every raw source goes through the pass-through mixer, so enabling
        # crossfade mid-track works immediately; the master volume stays on
        # top of (i.e. after) the mix.
        mixer = CrossfadeSource(raw_source)
        self._mixer = mixer
        source = discord.PCMVolumeTransformer(mixer, volume=self._volume)

        self._play_started_at = time.time()
        loop = asyncio.get_running_loop()

        def _after(error: Optional[Exception]) -> None:
            if error:
                print(f"[audio] playback error: {error}")
            if not self._seeking:
                loop.create_task(self.play_next())

        self.voice_client.play(source, after=_after)
        if self.settings.get("crossfade"):
            self._start_crossfade_watch()
        # Warm up what comes next (lazy resolve / pre-download / radio refill)
        # in the background — never blocks or affects the track just started.
        self._start_prefetch()
        await self._on_state_change(self.guild_id)

    # ------------------------------------------------------------------ prefetch

    def _start_prefetch(self) -> None:
        """Fire-and-forget prefetch of upcoming playback (one per player)."""
        old = self._prefetch_task
        if old is not None and not old.done():
            old.cancel()
        self._prefetch_task = asyncio.get_running_loop().create_task(
            self._prefetch_next()
        )

    async def _prefetch_next(self) -> None:
        """Prepare the next track while the current one is playing.

        - Radio mode: if the queue is empty (current track is the last one)
          and settings["radio"] is on, pull YouTube's RD mix for the current
          track and append a few related tracks.
        - Lazy tracks (Spotify): resolve queue[0] to a real URL up front.
        - Long tracks: pre-download into the local cache so the follow-up
          play_next() picks the file up instantly (gapless transition).

        All failures are logged and swallowed — prefetch must never affect
        the track that is already playing.
        """
        try:
            if self.settings.get("radio") and not self.queue and self.current:
                await self._radio_extend()
            if not self.queue:
                return
            nxt = self.queue[0]
            stream_url = ""
            if not nxt.webpage_url and nxt.search_query:
                # Mutates the track in place (webpage_url/thumbnail/duration)
                stream_url = await _resolve_lazy_track(nxt)
                # Clients show the resolved metadata right away
                await self._on_state_change(self.guild_id)
            if 0 < nxt.duration and nxt.duration >= PREBUFFER_MIN_DURATION:
                if not stream_url:
                    stream_url = await get_stream_url(nxt)
                if stream_url:
                    # Cache hit in the later play_next() is instant
                    await download_track(stream_url, nxt)
        except Exception as exc:
            print(f"[prefetch] error (guild {self.guild_id}): {exc}")

    async def _radio_extend(self) -> None:
        """Append a few RD-mix ("radio") tracks related to the current one."""
        current = self.current
        if current is None or current.source == "soundcloud":
            # SoundCloud pages have no YouTube mix — skip radio for them
            return
        video_id = _youtube_video_id(current.webpage_url)
        if not video_id:
            return
        mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
        candidates = await load_playlist(mix_url, max_tracks=RADIO_MIX_FETCH_LIMIT)

        # Skip the seed track itself and anything already played or queued
        seen = {
            (t.title.casefold(), t.artist.casefold())
            for t in [*self.history, *self.queue, current]
        }
        picked: List[Track] = []
        for t in candidates:
            if video_id in t.webpage_url:
                continue
            key = (t.title.casefold(), t.artist.casefold())
            if key in seen:
                continue
            seen.add(key)
            picked.append(t)
            if len(picked) >= RADIO_ENQUEUE_COUNT:
                break
        if picked:
            await self.enqueue_many(picked)   # single state_update broadcast
            print(f"[radio] queued {len(picked)} related track(s) "
                  f"after {current.title!r}")

    # ------------------------------------------------------------------ crossfade

    def _start_crossfade_watch(self) -> None:
        """(Re)start the monitor that arms the overlap for the current track."""
        old = self._crossfade_task
        if old is not None and not old.done():
            old.cancel()
        self._crossfade_task = asyncio.get_running_loop().create_task(
            self._crossfade_watch()
        )

    async def _crossfade_watch(self) -> None:
        """Watch the current track and fire the overlap near its end.

        Prepares the next source CROSSFADE_PREPARE_LEAD seconds before the
        overlap point and promotes it once the remaining time drops to
        CROSSFADE_SEC. Exits (discarding anything prepared) as soon as any
        precondition breaks; every failure degrades to the regular
        play_next() transition.
        """
        track = self.current
        if track is None:
            return
        try:
            while True:
                if (
                    self.current is not track
                    or not self.settings.get("crossfade")
                    or self.loop_mode == LOOP_ONE
                    or track.duration <= 0
                    or not self.voice_client
                    or not self.voice_client.is_connected()
                    or self._mixer is None
                ):
                    self._discard_prepared()
                    return
                # position is wall-clock and freezes on pause, so the monitor
                # simply keeps waiting while playback is paused.
                remaining = track.duration - self.position
                if (
                    remaining <= CROSSFADE_SEC + CROSSFADE_PREPARE_LEAD
                    and self._next_prepared is None
                    and self.queue
                ):
                    await self._prepare_next()
                if remaining <= CROSSFADE_SEC:
                    if self._next_prepared is not None:
                        # On failure the track plays out and play_next reuses
                        # the prepared source (plain transition).
                        await self._promote_next(CROSSFADE_FRAMES)
                    return
                if remaining > CROSSFADE_SEC + CROSSFADE_PREPARE_LEAD + 3:
                    await asyncio.sleep(2.0)
                else:
                    await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[crossfade] watch error (guild {self.guild_id}): {exc}")

    async def _prepare_next(self) -> None:
        """Spawn the FFmpeg source for queue[0] ahead of the overlap.

        Mirrors what play_next does for a fresh track (lazy resolve, cache
        download for long tracks) but never touches the playing source. All
        failures are logged and leave _next_prepared unset.
        """
        try:
            if not self.queue:
                return
            nxt = self.queue[0]
            was_lazy = not nxt.webpage_url and bool(nxt.search_query)
            # Resolves lazy (Spotify) tracks in place — identity is preserved
            stream_url = await get_stream_url(nxt)
            if not stream_url:
                return
            if was_lazy:
                # Clients show the resolved metadata right away
                await self._on_state_change(self.guild_id)
            file = None
            if 0 < nxt.duration and nxt.duration >= PREBUFFER_MIN_DURATION:
                file = await download_track(stream_url, nxt)
            # Re-check after the awaits: the queue may have mutated or the
            # setting may have been flipped while we were resolving.
            if not (
                self.queue
                and self.queue[0] is nxt
                and self.settings.get("crossfade")
            ):
                return
            if file:
                raw = discord.FFmpegPCMAudio(
                    file, options=_ffmpeg_output_opts(self)
                )
            else:
                raw = discord.FFmpegPCMAudio(
                    stream_url,
                    before_options=FFMPEG_OPTIONS["before_options"],
                    options=_ffmpeg_output_opts(self),
                )
            self._next_prepared = PreparedNext(nxt, raw, stream_url, file)
        except Exception as exc:
            print(f"[crossfade] prepare failed (guild {self.guild_id}): {exc}")

    async def _promote_next(self, fade_frames: int) -> bool:
        async with self._play_lock:
            return await self._promote_next_locked(fade_frames)

    async def _promote_next_locked(self, fade_frames: int) -> bool:
        """Start the overlap: fade the prepared source in as the new current.

        Returns False (leaving the prepared source for play_next to reuse)
        when any precondition fails. The identity check on queue[0] covers
        shuffle/move/remove/previous happening between prepare and promote.
        """
        prepared = self._next_prepared
        if (
            prepared is None
            or not self.voice_client
            or not self.voice_client.is_connected()
            or not self.voice_client.is_playing()
            or self._paused
            or self._mixer is None
            or self._mixer.is_fading()
            or not self.queue
            or self.queue[0] is not prepared.track
            or not self.settings.get("crossfade")
        ):
            return False

        self._next_prepared = None
        nxt = self.queue.popleft()
        old = self.current
        if old is not None:
            # Mirror play_next's routing (LOOP_ONE never reaches promotion)
            if self.loop_mode == LOOP_ALL:
                self.queue.append(old)
            else:
                self.history.append(old)

        # UI contract: the incoming track becomes current the moment its
        # audio starts, with its position counting up from zero.
        self.current = nxt
        self._paused = False
        self._total_paused = 0.0
        self._play_started_at = time.time()
        old_file = self._current_file
        self._current_file = prepared.file
        self._current_stream_url = prepared.stream_url

        loop = asyncio.get_running_loop()
        self._mixer.start_fade(
            prepared.raw,
            fade_frames,
            # Fired from the send thread when the fade completes — hop back
            # to the loop for the actual cleanup of the outgoing source.
            on_done=lambda old_raw: loop.call_soon_threadsafe(
                self._fade_done, old_raw, old_file
            ),
        )
        self._start_prefetch()
        self._start_crossfade_watch()
        await self._on_state_change(self.guild_id)
        return True

    def _fade_done(
        self, old_raw: discord.AudioSource, old_file: Optional[str]
    ) -> None:
        """Dispose of the faded-out source (and its cache file) off-loop."""
        current_file = self._current_file

        def _cleanup() -> None:
            try:
                old_raw.cleanup()
            except Exception:
                pass
            # Windows can't delete a file its ffmpeg still reads — remove
            # strictly after cleanup, in the same executor job.
            if old_file and old_file != current_file:
                try:
                    os.remove(old_file)
                except OSError:
                    pass

        asyncio.get_running_loop().run_in_executor(None, _cleanup)

    async def _crossfade_skip(self, expected: Optional[Track]) -> None:
        """Manual skip with crossfade on: quick fade into the next track."""
        async with self._play_lock:
            if self.current is not expected:
                # The track ended on its own while this task waited for the
                # lock and play_next already started the following one — the
                # skip is satisfied, leave the new track alone.
                return
            mixer = self._mixer
            if mixer is None or mixer.is_fading():
                # A second skip during a fade (or a vanished source) —
                # plain hard stop wins.
                if self.voice_client and (
                    self.voice_client.is_playing()
                    or self.voice_client.is_paused()
                ):
                    self.voice_client.stop()
                return
            if (
                self._next_prepared is not None
                and self.queue
                and self.queue[0] is self._next_prepared.track
                and await self._promote_next_locked(SKIP_FADE_FRAMES)
            ):
                return
            # Nothing usable prepared — short fade-out, then the regular
            # after -> play_next transition (no hard-cut click).
            mixer.start_fade_out(SKIP_FADE_FRAMES)

    def _discard_prepared(self) -> None:
        """Drop the prepared next source, killing its ffmpeg off-loop."""
        prepared = self._next_prepared
        if prepared is None:
            return
        self._next_prepared = None

        def _cleanup() -> None:
            try:
                prepared.raw.cleanup()
            except Exception:
                pass

        asyncio.get_running_loop().run_in_executor(None, _cleanup)

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
                "options": _ffmpeg_output_opts(self),
            }
            seek_target = self._current_file
        else:
            seek_opts = {
                "before_options": (
                    f"-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss {position:.2f}"
                ),
                "options": _ffmpeg_output_opts(self),
            }
            seek_target = self._current_stream_url
        raw_source = discord.FFmpegPCMAudio(seek_target, **seek_opts)
        # vc.stop() above disposed the previous mixer (both of its sources);
        # wrap the new one the same way so crossfade keeps working after seek.
        mixer = CrossfadeSource(raw_source)
        self._mixer = mixer
        source = discord.PCMVolumeTransformer(mixer, volume=self._volume)

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
            if (
                self.settings.get("crossfade")
                and self._mixer is not None
                and not self._paused
                and not self._mixer.is_fading()
            ):
                # Quick fade into the next track instead of a hard cut.
                # A second skip during that fade takes the else branch.
                asyncio.get_running_loop().create_task(
                    self._crossfade_skip(self.current)
                )
            else:
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
        # A prefetch working for the queue we just cleared is pointless
        if self._prefetch_task is not None and not self._prefetch_task.done():
            self._prefetch_task.cancel()
        # Same goes for the crossfade monitor and its prepared source
        if self._crossfade_task is not None and not self._crossfade_task.done():
            self._crossfade_task.cancel()
        self._discard_prepared()
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
        # vc.stop() above disposed both mixer sources via CrossfadeSource.cleanup
        self._mixer = None
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
            "settings": dict(self.settings),
            "voice_channel_id": (
                str(self.voice_client.channel.id)
                if self.voice_client and self.voice_client.channel
                else None
            ),
        }
