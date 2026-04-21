"""
Диагностика голосового подключения Discord.
Запуск: venv\Scripts\python diag_voice.py
"""
import asyncio
import ctypes
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))


def check_opus() -> None:
    print("=== Opus ===")
    try:
        import discord.opus as op
        loaded = op._load_default()
        if loaded:
            ver = op._lib.opus_get_version_string().decode()
            print(f"  [OK] libopus loaded: {ver}")
        else:
            print("  [FAIL] libopus NOT loaded — голос работать не будет")
            _basedir = os.path.dirname(os.path.abspath(op.__file__))
            _bitness = struct.calcsize("P") * 8
            _target = "x64" if _bitness > 32 else "x86"
            dll = os.path.join(_basedir, "bin", f"libopus-0.{_target}.dll")
            print(f"  Expected DLL: {dll}")
            print(f"  File exists:  {os.path.exists(dll)}")
    except Exception as e:
        print(f"  [ERROR] {e}")


def check_nacl() -> None:
    print("=== PyNaCl ===")
    try:
        import nacl.secret  # noqa: F401
        import nacl.utils   # noqa: F401
        print("  [OK] PyNaCl available")
    except ImportError:
        print("  [FAIL] PyNaCl not installed — голос работать не будет")
        print("         Исправление: pip install PyNaCl")


def check_udp_discord() -> None:
    """
    Проверяет, что мы можем отправить UDP-пакет и получить ответ от
    публичного DNS 8.8.8.8:53 (простейший UDP echo-тест).
    Это не гарантирует доступ к Discord voice, но покажет, блокирует
    ли Firewall UDP вообще.
    """
    print("=== UDP connectivity (DNS probe to 8.8.8.8:53) ===")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        # Minimal DNS query for 'a.root-servers.net'
        query = bytes.fromhex(
            "aabb0100000100000000000001610c726f6f742d73657276657273036e657400000100010"
        )
        sock.sendto(query, ("8.8.8.8", 53))
        data, _ = sock.recvfrom(512)
        sock.close()
        print("  [OK] UDP works (got DNS response)")
    except socket.timeout:
        print("  [WARN] UDP timeout — может блокировать Firewall или NAT")
    except Exception as e:
        print(f"  [FAIL] UDP error: {e}")


def check_discord_voice_ports() -> None:
    """
    Discord голосовые серверы используют порты 50000-50009 UDP.
    Проверяем TCP к ближайшему голосовому gateway через WebSocket-порт 443.
    """
    print("=== TCP к Discord gateway (api.discord.com:443) ===")
    try:
        sock = socket.create_connection(("discord.com", 443), timeout=5)
        sock.close()
        print("  [OK] TCP/443 к discord.com доступен")
    except Exception as e:
        print(f"  [FAIL] {e}")

    # Discord voice UDP: попробуем connect (не sendto) чтобы проверить routing
    print("=== UDP routing к Discord voice endpoint (50000) ===")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2)
        # connect() на UDP просто устанавливает default destination, не шлёт пакеты
        sock.connect(("45.33.93.102", 50000))  # один из IP голосовых серверов Discord
        local_addr = sock.getsockname()
        print(f"  [OK] UDP routing работает, локальный адрес: {local_addr}")
        sock.close()
    except Exception as e:
        print(f"  [FAIL] UDP routing: {e}")


async def check_voice_connect() -> None:
    """Пробует реально подключить бота к Discord и немедленно отключиться."""
    print("=== Реальное подключение бота (требует DISCORD_TOKEN в .env) ===")
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("  [SKIP] DISCORD_TOKEN не найден в .env")
        return

    import discord

    intents = discord.Intents.default()
    intents.guilds = True
    intents.voice_states = True
    client = discord.Client(intents=intents)
    connected = asyncio.Event()

    @client.event
    async def on_ready():
        print(f"  [OK] Бот подключён к Discord: {client.user}")
        guilds = client.guilds
        if not guilds:
            print("  [SKIP] Нет серверов")
            await client.close()
            return

        g = guilds[0]
        vcs = g.voice_channels
        if not vcs:
            print(f"  [SKIP] Нет голосовых каналов в {g.name}")
            await client.close()
            return

        vc_chan = vcs[0]
        print(f"  Попытка join #{vc_chan.name} в {g.name}...")
        try:
            vc = await vc_chan.connect(timeout=10.0)
            print(f"  [OK] Подключились к голосовому каналу!")
            await asyncio.sleep(5)
            if vc.is_connected():
                print("  [OK] Через 5 сек всё ещё подключены!")
            else:
                print("  [FAIL] Через 5 сек уже отключились!")
            await vc.disconnect(force=True)
        except Exception as e:
            print(f"  [FAIL] Не удалось подключиться: {e}")
        finally:
            await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=30)
    except asyncio.TimeoutError:
        print("  [FAIL] Timeout при подключении к Discord")
    except Exception as e:
        print(f"  [FAIL] {e}")


if __name__ == "__main__":
    print("Medral Voice Diagnostics\n")
    check_nacl()
    check_opus()
    check_udp_discord()
    check_discord_voice_ports()
    asyncio.run(check_voice_connect())
    print("\nГотово. Если есть [FAIL] — исправьте соответствующий пункт.")
    print("Если всё [OK] но бот всё равно отваливается — запустите сервер")
    print("и смотрите voice_debug.log в папке bot/")
