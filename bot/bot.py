import os
import asyncio
import time
import discord
from dotenv import load_dotenv
from typing import Optional, Dict, Callable, Awaitable, Tuple

from audio import MusicPlayer, search_tracks, load_playlist, is_playlist_url

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True

bot = discord.Bot(intents=intents)

# guild_id -> MusicPlayer
_players: Dict[int, MusicPlayer] = {}

# pending voice-reconnect tasks (one per guild)
_reconnect_tasks: Dict[int, asyncio.Task] = {}
# per-guild lock to serialize reconnect attempts
_reconnect_locks: Dict[int, asyncio.Lock] = {}
# per-guild reconnect attempt counter
_reconnect_attempts: Dict[int, int] = {}
MAX_RECONNECT_ATTEMPTS = 3

# per-guild auto-leave timers: disconnect after AUTO_LEAVE_DELAY seconds when
# idle (empty queue, nothing playing) or alone (no humans in the channel)
_auto_leave_tasks: Dict[int, asyncio.Task] = {}
AUTO_LEAVE_DELAY = 300  # seconds

# membership cache: (guild_id, user_id) -> (is_member, expires_at monotonic)
_member_cache: Dict[Tuple[int, int], Tuple[bool, float]] = {}
MEMBER_CACHE_TTL = 300  # seconds

# set by api.py so state updates are broadcast to WebSocket clients
_broadcast: Optional[Callable[[int, dict], Awaitable[None]]] = None


def set_broadcast_callback(cb: Callable[[int, dict], Awaitable[None]]) -> None:
    global _broadcast
    _broadcast = cb


def get_all_players() -> Dict[int, MusicPlayer]:
    return _players


def get_guilds() -> list[dict]:
    return [
        {
            "id": str(g.id),
            "name": g.name,
            "icon": str(g.icon) if g.icon else None,
            "voice_channels": [
                {"id": str(vc.id), "name": vc.name}
                for vc in g.voice_channels
            ],
        }
        for g in bot.guilds
    ]


async def _notify(guild_id: int) -> None:
    # Every state change re-evaluates the auto-leave timer
    _check_auto_leave(guild_id)
    if _broadcast and guild_id in _players:
        await _broadcast(guild_id, _players[guild_id].get_state())


def _player(guild_id: int) -> MusicPlayer:
    if guild_id not in _players:
        _players[guild_id] = MusicPlayer(guild_id, _notify)
    return _players[guild_id]


# ------------------------------------------------------------------ auto-leave

def _is_idle(p: MusicPlayer) -> bool:
    """Nothing queued, nothing playing, nothing paused."""
    return not p.queue and not p.is_playing and not p.is_paused


def _is_alone(p: MusicPlayer) -> bool:
    """No human members left in the bot's voice channel."""
    channel = p.voice_client.channel if p.voice_client else None
    if channel is None:
        return False
    members = channel.members
    # After a bot restart the member cache may be empty/stale. Trust it only
    # when it can at least see the bot itself sitting in the channel —
    # otherwise we'd kick ourselves out mid-playback with listeners present.
    if not any(m.id == bot.user.id for m in members):
        return False
    return not any(not m.bot for m in members)


async def _auto_leave(guild_id: int) -> None:
    """Disconnect after AUTO_LEAVE_DELAY seconds if still idle or alone."""
    try:
        await asyncio.sleep(AUTO_LEAVE_DELAY)
    except asyncio.CancelledError:
        return

    _auto_leave_tasks.pop(guild_id, None)
    p = _players.get(guild_id)
    guild = bot.get_guild(guild_id)
    if not p or not guild or not p.voice_client or not p.voice_client.is_connected():
        return

    # Re-check right before leaving — activity may have resumed meanwhile
    idle, alone = _is_idle(p), _is_alone(p)
    if not idle and not alone:
        return

    reason = "idle" if idle else "empty channel"
    print(f"[voice] auto-leave ({reason}) after {AUTO_LEAVE_DELAY}s in {guild.name}")
    # stop_and_disconnect sets _intentional_stop, so on_voice_state_update
    # won't treat this as an unexpected drop and trigger auto-reconnect.
    await p.stop_and_disconnect()


def _cancel_auto_leave(guild_id: int) -> None:
    task = _auto_leave_tasks.pop(guild_id, None)
    if task and not task.done():
        task.cancel()


def _check_auto_leave(guild_id: int) -> None:
    """Arm or cancel the auto-leave timer based on current activity.

    Keeps an already-armed timer running (no countdown restarts) while the
    idle/alone condition holds; cancels it as soon as activity resumes.
    """
    p = _players.get(guild_id)
    if not p or not p.voice_client or not p.voice_client.is_connected():
        _cancel_auto_leave(guild_id)
        return
    if _is_idle(p) or _is_alone(p):
        existing = _auto_leave_tasks.get(guild_id)
        if existing is None or existing.done():
            _auto_leave_tasks[guild_id] = asyncio.create_task(_auto_leave(guild_id))
    else:
        _cancel_auto_leave(guild_id)


# ------------------------------------------------------------------ events

@bot.event
async def on_ready() -> None:
    print(f"[bot] ready — {bot.user} (id: {bot.user.id})")
    print(f"[bot] serving {len(bot.guilds)} guild(s)")


async def _reconnect_voice(guild_id: int, channel_id: int) -> None:
    """
    Debounced voice-reconnect. Serialized per-guild so only one attempt runs
    at a time. Gives up after MAX_RECONNECT_ATTEMPTS to avoid hammering
    Discord when the network simply can't maintain voice.
    """
    try:
        await asyncio.sleep(3)
    except asyncio.CancelledError:
        return

    _reconnect_tasks.pop(guild_id, None)

    lock = _reconnect_locks.setdefault(guild_id, asyncio.Lock())
    async with lock:
        guild = bot.get_guild(guild_id)
        p     = _players.get(guild_id)
        if not guild or not p:
            return

        # Authoritative check — is voice actually down?
        existing = discord.utils.get(bot.voice_clients, guild=guild)
        if existing and existing.is_connected():
            if p.voice_client is not existing:
                p.voice_client = existing
                print(f"[voice] voice client restored by py-cord in {guild.name}")
                await _notify(guild_id)
            _reconnect_attempts[guild_id] = 0
            return

        attempt = _reconnect_attempts.get(guild_id, 0) + 1
        _reconnect_attempts[guild_id] = attempt

        if attempt > MAX_RECONNECT_ATTEMPTS:
            print(f"[voice] giving up after {MAX_RECONNECT_ATTEMPTS} failed "
                  f"attempts in {guild.name} — check network/firewall "
                  f"(Discord voice needs stable outbound UDP)")
            p.current = None
            p.queue.clear()
            await _notify(guild_id)
            return

        channel = guild.get_channel(channel_id)
        if not channel or not isinstance(channel, discord.VoiceChannel):
            return

        print(f"[voice] reconnect attempt {attempt}/{MAX_RECONNECT_ATTEMPTS} "
              f"to #{channel.name} in {guild.name}")
        try:
            vc = await channel.connect(timeout=15.0, reconnect=True)
            p.voice_client = vc
            print(f"[voice] reconnected to #{channel.name}")
            _reconnect_attempts[guild_id] = 0
            await _maybe_resume(p, guild_id)
        except discord.ClientException as exc:
            if "Already connected" in str(exc):
                vc = discord.utils.get(bot.voice_clients, guild=guild)
                if vc:
                    p.voice_client = vc
                    _reconnect_attempts[guild_id] = 0
                    await _notify(guild_id)
                    return
            print(f"[voice] reconnect failed: {exc}")
            await _notify(guild_id)
        except Exception as exc:
            print(f"[voice] reconnect failed: {exc}")
            await _notify(guild_id)


async def _maybe_resume(p, guild_id: int) -> None:
    """Put the interrupted track back and resume if there's a queue."""
    if p.current:
        p.queue.appendleft(p.current)
        p.current = None
    if p.queue and not p.is_playing:
        await p.play_next()
    else:
        await _notify(guild_id)


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    if member != bot.user:
        # Humans joining/leaving affect the alone-in-channel condition
        if member.guild.id in _players:
            _check_auto_leave(member.guild.id)
        return
    p = _players.get(member.guild.id)
    if not p:
        return

    if after.channel is None:
        # py-cord sometimes fires spurious after=None events during a
        # gateway session RESUME even though the voice connection is alive.
        # Verify against the authoritative bot.voice_clients list first.
        live_vc = discord.utils.get(bot.voice_clients, guild=member.guild)
        if live_vc is not None and live_vc.is_connected():
            p.voice_client = live_vc
            return

        intentional = p._intentional_stop
        p._intentional_stop = False
        p.voice_client = None
        _cancel_auto_leave(member.guild.id)

        if intentional:
            # /leave or stop command — clear everything
            p.current = None
            p.queue.clear()
            await _notify(member.guild.id)
        else:
            # Unexpected disconnect — keep queue, schedule ONE reconnect task
            prev_channel_id = before.channel.id if before.channel else None
            print(f"[voice] unexpected disconnect in {member.guild.name} "
                  f"(was in channel {before.channel})")
            await _notify(member.guild.id)
            if prev_channel_id:
                # Cancel any previous pending reconnect for this guild
                old = _reconnect_tasks.get(member.guild.id)
                if old and not old.done():
                    old.cancel()
                _reconnect_tasks[member.guild.id] = asyncio.create_task(
                    _reconnect_voice(member.guild.id, prev_channel_id)
                )
    else:
        # Bot moved to another channel or gateway reconnected —
        # refresh the VoiceClient reference so it stays valid.
        vc = discord.utils.get(bot.voice_clients, guild=member.guild)
        if vc is not None:
            p.voice_client = vc
        await _notify(member.guild.id)


# ------------------------------------------------------------------ slash commands

@bot.slash_command(name="join", description="Подключить бота к голосовому каналу")
async def cmd_join(
    ctx: discord.ApplicationContext,
    channel: Optional[discord.VoiceChannel] = None,
) -> None:
    if channel is None:
        if ctx.author.voice:
            channel = ctx.author.voice.channel
        else:
            await ctx.respond("Вы не в голосовом канале!", ephemeral=True)
            return

    p = _player(ctx.guild_id)
    if ctx.voice_client:
        await ctx.voice_client.move_to(channel)
        p.voice_client = ctx.voice_client
    else:
        p.voice_client = await channel.connect()

    await ctx.respond(f"Подключён к **{channel.name}**")
    await _notify(ctx.guild_id)


@bot.slash_command(name="play", description="Воспроизвести трек или добавить в очередь")
async def cmd_play(ctx: discord.ApplicationContext, query: str) -> None:
    await ctx.defer()
    p = _player(ctx.guild_id)

    if not ctx.voice_client:
        if ctx.author.voice:
            p.voice_client = await ctx.author.voice.channel.connect()
        else:
            await ctx.followup.send("Вы не в голосовом канале!")
            return
    elif p.voice_client is None:
        p.voice_client = ctx.voice_client

    results = await search_tracks(query, max_results=1)
    if not results:
        await ctx.followup.send("Трек не найден.")
        return

    track = results[0]
    await p.enqueue(track)
    await ctx.followup.send(f"Добавлен: **{track.title}** — {track.artist}")

    if not p.is_playing and not p.is_paused:
        await p.play_next()


@bot.slash_command(name="search", description="Найти треки (топ-5)")
async def cmd_search(ctx: discord.ApplicationContext, query: str) -> None:
    await ctx.defer()
    results = await search_tracks(query, max_results=5)
    if not results:
        await ctx.followup.send("Ничего не найдено.")
        return
    lines = [f"{i + 1}. **{t.title}** — {t.artist} [{t.duration // 60}:{t.duration % 60:02d}]"
             for i, t in enumerate(results)]
    await ctx.followup.send("\n".join(lines))


@bot.slash_command(name="playlist", description="Загрузить плейлист по ссылке")
async def cmd_playlist(ctx: discord.ApplicationContext, url: str) -> None:
    await ctx.defer()
    p = _player(ctx.guild_id)

    if not ctx.voice_client:
        if ctx.author.voice:
            p.voice_client = await ctx.author.voice.channel.connect()
        else:
            await ctx.followup.send("Вы не в голосовом канале!")
            return
    elif p.voice_client is None:
        p.voice_client = ctx.voice_client

    tracks = await load_playlist(url)
    if not tracks:
        await ctx.followup.send("Плейлист пуст или недоступен.")
        return

    await p.enqueue_many(tracks)
    await ctx.followup.send(f"Добавлено треков из плейлиста: {len(tracks)}")

    if not p.is_playing and not p.is_paused:
        await p.play_next()


@bot.slash_command(name="shuffle", description="Перемешать очередь")
async def cmd_shuffle(ctx: discord.ApplicationContext) -> None:
    p = _player(ctx.guild_id)
    if not p.queue:
        await ctx.respond("Очередь пуста.", ephemeral=True)
        return
    await p.shuffle()
    await ctx.respond("🔀 Очередь перемешана")


@bot.slash_command(name="loop", description="Режим повтора: none / one / all")
async def cmd_loop(
    ctx: discord.ApplicationContext,
    mode: discord.Option(str, "Режим повтора", choices=["none", "one", "all"]),  # type: ignore[valid-type]
) -> None:
    p = _player(ctx.guild_id)
    p.set_loop(mode)
    await _notify(ctx.guild_id)
    labels = {"none": "Повтор выключен", "one": "🔂 Повтор трека", "all": "🔁 Повтор очереди"}
    await ctx.respond(labels[mode])


@bot.slash_command(name="skip", description="Пропустить текущий трек")
async def cmd_skip(ctx: discord.ApplicationContext) -> None:
    p = _player(ctx.guild_id)
    if not p.is_playing and not p.is_paused:
        await ctx.respond("Ничего не играет!", ephemeral=True)
        return
    p.skip()
    await ctx.respond("Пропущен ▶")


@bot.slash_command(name="previous", description="Предыдущий трек")
async def cmd_previous(ctx: discord.ApplicationContext) -> None:
    p = _player(ctx.guild_id)
    await p.previous()
    await ctx.respond("⏮ Предыдущий трек")


@bot.slash_command(name="pause", description="Пауза")
async def cmd_pause(ctx: discord.ApplicationContext) -> None:
    p = _player(ctx.guild_id)
    if not p.is_playing:
        await ctx.respond("Ничего не играет!", ephemeral=True)
        return
    p.pause()
    await ctx.respond("⏸ Пауза")
    await _notify(ctx.guild_id)


@bot.slash_command(name="resume", description="Продолжить воспроизведение")
async def cmd_resume(ctx: discord.ApplicationContext) -> None:
    p = _player(ctx.guild_id)
    if not p.is_paused:
        await ctx.respond("Не на паузе!", ephemeral=True)
        return
    p.resume()
    await ctx.respond("▶ Продолжено")
    await _notify(ctx.guild_id)


@bot.slash_command(name="stop", description="Остановить воспроизведение и очистить очередь")
async def cmd_stop(ctx: discord.ApplicationContext) -> None:
    p = _player(ctx.guild_id)
    p.queue.clear()
    if p.is_playing or p.is_paused:
        # Park the track in history before stopping — otherwise loop one/all
        # would re-queue it inside play_next and playback would restart.
        if p.current:
            p.history.append(p.current)
            p.current = None
        p.skip()
    await ctx.respond("⏹ Остановлено, очередь очищена")
    await _notify(ctx.guild_id)


@bot.slash_command(name="leave", description="Отключить бота")
async def cmd_leave(ctx: discord.ApplicationContext) -> None:
    p = _player(ctx.guild_id)
    await p.stop_and_disconnect()
    await ctx.respond("Отключён.")


@bot.slash_command(name="queue", description="Показать очередь")
async def cmd_queue(ctx: discord.ApplicationContext) -> None:
    p = _player(ctx.guild_id)
    if not p.current and not p.queue:
        await ctx.respond("Очередь пуста.", ephemeral=True)
        return

    lines: list[str] = []
    if p.current:
        dur = p.current.duration
        lines.append(
            f"▶ **{p.current.title}** — {p.current.artist} "
            f"[{dur // 60}:{dur % 60:02d}]"
        )
    for i, t in enumerate(list(p.queue)[:20]):
        lines.append(f"{i + 1}. {t.title} — {t.artist}")
    if len(p.queue) > 20:
        lines.append(f"...и ещё {len(p.queue) - 20} треков")

    await ctx.respond("\n".join(lines))


@bot.slash_command(name="volume", description="Установить громкость (0–100)")
async def cmd_volume(ctx: discord.ApplicationContext, level: int) -> None:
    if not 0 <= level <= 100:
        await ctx.respond("Громкость от 0 до 100.", ephemeral=True)
        return
    p = _player(ctx.guild_id)
    p.set_volume(level / 100.0)
    await ctx.respond(f"🔊 Громкость: {level}%")
    await _notify(ctx.guild_id)


# ------------------------------------------------------------------ public API used by api.py

async def api_join(guild_id: int, channel_id: int) -> dict:
    guild = bot.get_guild(guild_id)
    if not guild:
        return {"ok": False, "error": "guild not found"}
    channel = guild.get_channel(channel_id)
    if not channel or not isinstance(channel, discord.VoiceChannel):
        return {"ok": False, "error": "channel not found"}
    p = _player(guild_id)

    # User-initiated connect — reset circuit breaker
    _reconnect_attempts[guild_id] = 0
    old = _reconnect_tasks.pop(guild_id, None)
    if old and not old.done():
        old.cancel()

    vc = guild.voice_client  # authoritative Discord cache
    try:
        if vc is not None:
            if not vc.is_connected():
                await vc.disconnect(force=True)
                vc = await channel.connect()
            elif vc.channel.id != channel.id:
                await vc.move_to(channel)
        else:
            vc = await channel.connect()
    except discord.ClientException:
        # Race condition: another request is already connecting.
        # Find the connection via bot.voice_clients (lower-level list).
        vc = discord.utils.get(bot.voice_clients, guild=guild)
        if vc is None:
            return {"ok": False, "error": "voice connection busy, try again"}

    p.voice_client = vc
    await _notify(guild_id)
    return {"ok": True}


async def api_leave(guild_id: int) -> dict:
    p = _player(guild_id)
    await p.stop_and_disconnect()
    return {"ok": True}


async def api_play(guild_id: int, query: str) -> dict:
    # Whole-playlist URLs go through the playlist loader
    if is_playlist_url(query):
        return await api_play_playlist(guild_id, query)
    p = _player(guild_id)
    if not p.voice_client or not p.voice_client.is_connected():
        return {"ok": False, "error": "bot not in a voice channel"}
    results = await search_tracks(query, max_results=1)
    if not results:
        return {"ok": False, "error": "track not found"}
    track = results[0]
    await p.enqueue(track)
    if not p.is_playing and not p.is_paused:
        await p.play_next()
    return {"ok": True, "track": track.to_dict()}


async def api_play_playlist(guild_id: int, url: str) -> dict:
    p = _player(guild_id)
    if not p.voice_client or not p.voice_client.is_connected():
        return {"ok": False, "error": "bot not in a voice channel"}
    tracks = await load_playlist(url)
    if not tracks:
        return {"ok": False, "error": "playlist empty or unavailable"}
    await p.enqueue_many(tracks)
    if not p.is_playing and not p.is_paused:
        await p.play_next()
    return {"ok": True, "count": len(tracks)}


async def api_search(query: str, max_results: int = 5) -> list[dict]:
    results = await search_tracks(query, max_results)
    return [t.to_dict() for t in results]


async def api_skip(guild_id: int) -> dict:
    p = _player(guild_id)
    p.skip()
    return {"ok": True}


async def api_previous(guild_id: int) -> dict:
    p = _player(guild_id)
    await p.previous()
    return {"ok": True}


async def api_pause(guild_id: int) -> dict:
    p = _player(guild_id)
    p.pause()
    await _notify(guild_id)
    return {"ok": True}


async def api_resume(guild_id: int) -> dict:
    p = _player(guild_id)
    p.resume()
    await _notify(guild_id)
    return {"ok": True}


async def api_stop(guild_id: int) -> dict:
    p = _player(guild_id)
    p.queue.clear()
    if p.is_playing or p.is_paused:
        # Park the track in history before stopping — otherwise loop one/all
        # would re-queue it inside play_next and playback would restart.
        if p.current:
            p.history.append(p.current)
            p.current = None
        p.skip()
    # skip() notifies via play_next only when something was playing —
    # notify here so the cleared queue is broadcast in every branch.
    await _notify(guild_id)
    return {"ok": True}


async def api_shuffle(guild_id: int) -> dict:
    p = _player(guild_id)
    if not p.queue:
        return {"ok": False, "error": "queue is empty"}
    await p.shuffle()
    return {"ok": True}


async def api_set_loop(guild_id: int, mode: str) -> dict:
    p = _player(guild_id)
    try:
        p.set_loop(mode)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    await _notify(guild_id)
    return {"ok": True, "loop_mode": mode}


async def api_set_volume(guild_id: int, volume: float) -> dict:
    p = _player(guild_id)
    p.set_volume(volume)
    await _notify(guild_id)
    return {"ok": True}


async def api_seek(guild_id: int, position: float) -> dict:
    p = _player(guild_id)
    await p.seek(position)
    return {"ok": True}


async def api_remove_from_queue(guild_id: int, index: int) -> dict:
    p = _player(guild_id)
    ok = p.remove_from_queue(index)
    if ok:
        await _notify(guild_id)
    return {"ok": ok}


async def api_move_in_queue(guild_id: int, from_index: int, to_index: int) -> dict:
    p = _player(guild_id)
    ok = p.move_in_queue(from_index, to_index)
    if ok:
        await _notify(guild_id)
    return {"ok": ok}


async def api_get_state(guild_id: int) -> Optional[dict]:
    p = _players.get(guild_id)
    return p.get_state() if p else None


# ------------------------------------------------------------------ auth helpers used by api.py

async def api_is_member(guild_id: int, user_id: int) -> bool:
    """Whether the user is a member of the guild. Cached for MEMBER_CACHE_TTL."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return False

    key = (guild_id, user_id)
    now = time.monotonic()
    cached = _member_cache.get(key)
    if cached is not None and cached[1] > now:
        return cached[0]

    if guild.get_member(user_id) is not None:
        _member_cache[key] = (True, now + MEMBER_CACHE_TTL)
        return True

    try:
        await guild.fetch_member(user_id)
        result = True
    except discord.NotFound:
        result = False
    except discord.HTTPException as exc:
        # Transient Discord error — deny access but don't poison the cache
        print(f"[auth] fetch_member({user_id}) failed in {guild.name}: {exc}")
        return False

    _member_cache[key] = (result, now + MEMBER_CACHE_TTL)
    return result


def api_user_voice_channel_id(guild_id: int, user_id: int) -> Optional[int]:
    """Voice channel the user is currently in, or None."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return None
    member = guild.get_member(user_id)
    if member is not None and member.voice and member.voice.channel:
        return member.voice.channel.id
    # Voice states are tracked per-guild even for members missing from the
    # member cache. _voice_states is private but stable across py-cord releases.
    voice_state = getattr(guild, "_voice_states", {}).get(user_id)
    if voice_state is not None and voice_state.channel:
        return voice_state.channel.id
    return None


def api_bot_voice_channel_id(guild_id: int) -> Optional[int]:
    """Voice channel the bot is currently connected to, or None."""
    guild = bot.get_guild(guild_id)
    if not guild:
        return None
    vc = guild.voice_client  # authoritative Discord cache
    if vc is not None and vc.is_connected() and vc.channel is not None:
        return vc.channel.id
    return None
