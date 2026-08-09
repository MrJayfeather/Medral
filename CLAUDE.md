# Medral — заметки для Claude

## Архитектура

- **`bot/`** — FastAPI-сервер + Discord-бот (py-cord 2.7.2) в одном процессе uvicorn
  - `api.py` — REST endpoints + WebSocket `/ws` для push-уведомлений
  - `bot.py` — Discord bot, slash-команды, API-функции `api_*`, логика переподключения к голосу
  - `audio.py` — `MusicPlayer` (очередь, позиция, громкость), yt-dlp + FFmpeg
- **`client/`** — PyQt6 desktop client
  - `network.py` — `ApiClient` на фоновом asyncio-потоке, сигналы в UI-поток
  - `ui/main_window.py` — главное окно, топбар с выбором сервера
  - `ui/channel_panel.py` — левая панель: голосовые каналы, кнопка connect/disconnect
  - `ui/player_panel.py`, `queue_panel.py`, `search_panel.py`

Запуск: сервер `python bot/api.py` (создаёт venv через `bot/run_server.bat`), клиент `python client/main.py` или сборка `.exe` через `client/build.bat`.

## Что уже работает

- Slash-команды: `/join /play /search /skip /previous /pause /resume /stop /leave /queue /volume`
- REST API для всех команд плюс `/guilds`, `/state/{guild_id}`, `/search`, `/health`
- WebSocket broadcast `state_update` на любое изменение состояния
- **Server-side keepalive**: каждые 25 сек JSON `{"type":"ping"}`, каждые 10 сек — позиция при воспроизведении (`_keepalive_loop` в `api.py`)
- **Восстановление выбора сервера** при реконнекте WS (раньше сбрасывался на "No Server"), фикс в `main_window.py:_on_guilds`
- **Race condition при `api_join`** — использует `guild.voice_client` как источник правды, ловит `discord.ClientException` "Already connected"
- **Auto-reconnect к голосу** при неожиданном отключении:
  - флаг `_intentional_stop` в `MusicPlayer` отличает `/leave` от аварийного разрыва
  - debounce 3 сек (`_reconnect_voice` в `bot.py`) + per-guild lock → серии призрачных событий не плодят параллельные коннекты
  - circuit breaker `MAX_RECONNECT_ATTEMPTS=3` — после лимита бот сдаётся
  - при `api_join` счётчик попыток сбрасывается
  - защитная проверка: если `after.channel is None`, но `bot.voice_clients` содержит живой клиент — считаем событие призрачным
- Сохранение очереди при аварийном дисконнекте, возобновление прерванного трека после reconnect

## РЕШЕНО: «отвал голоса через 25 секунд» (историческое)

Проблема была только при **локальном** запуске сервера на Windows-машине пользователя.
Анализ `voice_debug.log` (2026-08) опроверг старые гипотезы: firewall и UDP ни при чём —
voice-handshake и heartbeat-ack проходили успешно. Реальная причина: **блокировка asyncio
event loop на 10–100 секунд** («Shard ID None heartbeat blocked for more than N seconds»),
из-за чего Discord рвал сессию. На VPS проблема не воспроизводится — бот работает стабильно.
Вывод на будущее: не запускать продакшн-сервер локально; следить, чтобы синхронные вызовы
(yt-dlp и т.п.) не блокировали loop.

## Продакшн

- **VPS**: root@144.124.243.108 (vdsina, Ubuntu 24.04, 1c/1GB + 2GB swap), SSH по ключу
- Код: `/opt/medral`, сервис `systemctl restart medral`, логи `journalctl -u medral -f`
- Деплой серверного кода: `git push` → на VPS `git pull && chown -R medral:medral /opt/medral && systemctl restart medral` (release.bat делает автоматически)
- ⚠️ Универская сеть пользователя не маршрутизирует 144.124.x.x (2026-08-09) — работа через хотспот; перепроверить позже

## Важные технические детали

- **Большие ID (Discord snowflakes)** — 64-битные, в PyQt `pyqtSignal(int)` их режет до 32-бит. Используется `pyqtSignal(object, object)` в `channel_panel.py`, и в `setData` канала храним как **строку** (`str(ch["id"])`), а в `_on_*` парсим обратно `int()`.
- **Uvicorn WS keepalive**: по умолчанию `ws_ping_interval=20, ws_ping_timeout=20`. Клиентский `websockets` имеет `ping_interval=None` (не шлёт ping'и сам), но отвечает PONG'ом на серверные ping'и — этого достаточно.
- **`_keepalive_loop`** в `api.py` — отдельная задача, запускается в `lifespan`, её надо отменить при shutdown (это сделано).
- **`asyncio.get_running_loop()`** вместо устаревшего `get_event_loop()` в `audio.MusicPlayer.play_next`.
- **Путь Windows/bash**: проект на `D:\Medral`, в bash — `/d/Medral/`. В коде все пути через `os.path` или относительные.

## Память о пользователе

- Работать автономно, разрешения не спрашивать
- Писать в чате **только на русском**
- Любит краткость
