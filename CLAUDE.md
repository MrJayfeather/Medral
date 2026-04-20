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

## НЕРЕШЁННАЯ ПРОБЛЕМА (на чём остановились) ⚠️

**Бот отключается от голосового канала ровно через ~25 секунд после входа**, затем срабатывает auto-reconnect, снова отваливается, и так по кругу.

### Что известно

- Таймаут ровно 25 сек = 5 UDP-keepalive интервалов py-cord × 5 сек. Классический признак, что UDP к голосовым серверам Discord не доходит.
- Я предположил, что виновата сеть пользователя (eduroam — академическая сеть с жёсткой фильтрацией UDP).
- **НО** — пользователь раздал интернет с мобильного телефона (hotspot), и **проблема сохранилась**. Значит дело НЕ в сети eduroam.

### Что НЕ попробовали (для следующей сессии — в порядке приоритета)

1. **Версия Opus / PyNaCl** — py-cord для голоса требует PyNaCl, для кодирования — libopus. Возможно, в venv нет или битая libopus. Проверить: `import nacl` и `discord.opus.is_loaded()`.
2. **Windows Firewall блокирует python.exe** для исходящего UDP — проверить правила для `venv\Scripts\python.exe`.
3. **Логи py-cord на уровне DEBUG** — включить `logging.basicConfig(level=logging.DEBUG)` и посмотреть, что именно говорит voice-client перед разрывом.
4. **Discord voice region для сервера** — может, конкретный регион голосового сервера отдаёт 403/connection reset. Попробовать сменить регион канала в Discord.
5. **Антивирус / Windows Defender / сторонние firewall** на машине пользователя.
6. **Проверить, что бот НЕ deafened в Discord** (серверные права) — иногда сервер имеет роль, которая запрещает боту аудио.

### Гипотезы для следующей сессии

- Самая правдоподобная: **локальный фаервол (Windows Defender) блокирует UDP от python.exe**. Проявляется одинаково и на eduroam, и на мобильном, т.к. блок происходит до выхода наружу.
- Второе место: **отсутствует/битый Opus в venv**. При этом бот может "подключаться" к голосовому каналу, но не может слать аудио-фреймы, Discord считает соединение мёртвым после keepalive-тайм-аутов.

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
