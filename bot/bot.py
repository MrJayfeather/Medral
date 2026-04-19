import os
import asyncio
import discord
from dotenv import load_dotenv
from typing import Optional, Dict, Callable, Awaitable

from audio import MusicPlayer, search_tracks

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.guilds = True
intents.voice_states = True

bot = discord.Bot(intents=intents)

# guild_id -> MusicPlayer
_players: Dict[int, MusicPlayer] = {}

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
    if _broadcast and guild_id in _players:
        await _broadcast(guild_id, _players[guild_id].get_state())


def _player(guild_id: int) -> MusicPlayer:
    if guild_id not in _players:
        _players[guild_id] = MusicPlayer(guild_id, _notify)
    return _players[guild_id]


# ------------------------------------------------------------------ events

@bot.event
async def on_ready() -> None:
    print(f"[bot] ready — {bot.user} (id: {bot.user.id})")
    print(f"[bot] serving {len(bot.guilds)} guild(s)")


@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    # notify clients when the bot is moved / disconnected externally
    if member == bot.user:
        p = _players.get(member.guild.id)
        if p:
            if after.channel is None:
                p.voice_client = None
                p.current = None
                p.queue.clear()
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
        p.skip()
    await ctx.respond("⏹ Остановлено, очередь очищена")


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
    if p.voice_client and p.voice_client.is_connected():
        await p.voice_client.move_to(channel)
    else:
        p.voice_client = await channel.connect()
    await _notify(guild_id)
    return {"ok": True}


async def api_leave(guild_id: int) -> dict:
    p = _player(guild_id)
    await p.stop_and_disconnect()
    return {"ok": True}


async def api_play(guild_id: int, query: str) -> dict:
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
        p.skip()
    return {"ok": True}


async def api_set_volume(guild_id: int, volume: float) -> dict:
    p = _player(guild_id)
    p.set_volume(volume)
    await _notify(guild_id)
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
