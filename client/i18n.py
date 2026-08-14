"""Client i18n foundation (RU/EN).

Usage:
    from i18n import tr, tr_n, init_lang, get_lang, set_lang

    init_lang(cfg.get("lang"))      # once, BEFORE any widget is created
    label.setText(tr("login_button"))
    count.setText(f"{n} {tr_n('track', n)}")

The catalog holds every user-visible string of the client, including the
ones not yet wired through tr() (channel/search/player/queue panels) so
later phases only have to swap the literals.  Keys are snake_case by
meaning; placeholders use str.format syntax: {} / {n} / {version} / ...

tr() never raises: an unknown key comes back as the key itself, a failed
.format() returns the raw template.
"""

from __future__ import annotations

SUPPORTED_LANGS = ("ru", "en")

_lang = "en"


# ── catalog ───────────────────────────────────────────────────────────────

_CATALOG: dict[str, dict[str, str]] = {
    # ── login dialog (main.py) ────────────────────────────────────────────
    "login_window_title": {
        "ru": "Medral — вход",
        "en": "Medral — Sign in",
    },
    "login_subtitle": {
        "ru": "Войди через Discord, чтобы управлять ботом",
        "en": "Sign in with Discord to control the bot",
    },
    "login_button": {
        "ru": "Войти через Discord",
        "en": "Sign in with Discord",
    },
    "login_copy_link": {
        "ru": "Скопировать ссылку для другого браузера",
        "en": "Copy the link for another browser",
    },
    "login_browser_opened": {
        "ru": "Открыл браузер — подтверди вход и вернись сюда…",
        "en": "Opened your browser — confirm the sign-in and come back…",
    },
    "login_link_copied": {
        "ru": "Ссылка скопирована — вставь её в браузер с нужным "
              "аккаунтом Discord и подтверди вход",
        "en": "Link copied — paste it into the browser with the right "
              "Discord account and confirm the sign-in",
    },
    "login_timeout": {
        "ru": "Не дождался входа, попробуй ещё раз",
        "en": "Sign-in timed out, try again",
    },
    "login_expired": {
        "ru": "Сессия входа устарела — нажми кнопку ещё раз",
        "en": "Sign-in session expired — press the button again",
    },
    "cancel": {
        "ru": "Отмена",
        "en": "Cancel",
    },

    # ── connect dialog (main.py) ──────────────────────────────────────────
    "connect_dialog_title": {
        "ru": "Подключение к серверу",
        "en": "Connect to server",
    },
    "connect_dialog_sub": {
        "ru": "Клиент v{version} — введи адрес своего сервера Medral.",
        "en": "Client v{version} — Enter the address of your Medral server.",
    },
    "host_label": {
        "ru": "Host",
        "en": "Host",
    },
    "port_label": {
        "ru": "Port",
        "en": "Port",
    },
    "host_placeholder": {
        "ru": "127.0.0.1  или  IP сервера",
        "en": "127.0.0.1  or  server IP",
    },
    "run_locally": {
        "ru": "Запустить локально",
        "en": "Run locally",
    },
    "run_locally_tip": {
        "ru": "Запустить встроенный сервер на этом ПК",
        "en": "Run the built-in server on this PC",
    },
    "connect_button": {
        "ru": "Подключиться",
        "en": "Connect",
    },
    "server_starting": {
        "ru": "Запускаю сервер…",
        "en": "Starting the server…",
    },
    "server_start_failed": {
        "ru": "Не удалось запустить сервер.",
        "en": "Failed to start the server.",
    },
    "server_no_response": {
        "ru": "Сервер не ответил за 10 сек.",
        "en": "Server did not respond within 10 s.",
    },
    "server_started": {
        "ru": "Сервер запущен!",
        "en": "Server is up!",
    },

    # ── main window / top bar (main_window.py) ────────────────────────────
    "server_combo_label": {
        "ru": "Сервер:",
        "en": "Server:",
    },
    "no_server": {
        "ru": "Нет сервера",
        "en": "No server",
    },
    "update_button": {
        "ru": "↓ Обновить",
        "en": "↓ Update",
    },
    "update_ready_tip": {
        "ru": "Версия {version} загружена — нажми для перезапуска",
        "en": "Version {version} downloaded — click to restart",
    },
    "settings_tooltip": {
        "ru": "Настройки",
        "en": "Settings",
    },
    "ws_disconnected_tip": {
        "ru": "WebSocket отключён",
        "en": "WebSocket disconnected",
    },
    "ws_retrying_tip": {
        "ru": "Отключено — повторяю…",
        "en": "Disconnected — retrying…",
    },
    "status_connecting": {
        "ru": "Подключение…",
        "en": "Connecting…",
    },
    "status_connected": {
        "ru": "Подключено",
        "en": "Connected",
    },
    "status_disconnected": {
        "ru": "Отключено — переподключаюсь…",
        "en": "Disconnected — reconnecting…",
    },
    "status_error": {
        "ru": "Ошибка: {msg}",
        "en": "Error: {msg}",
    },
    "status_loading_playlist": {
        "ru": "Загружаю плейлист…",
        "en": "Loading the playlist…",
    },
    "status_connecting_to": {
        "ru": "Подключение к {host}:{port}…",
        "en": "Connecting to {host}:{port}…",
    },

    # ── settings page (settings_view.py) ──────────────────────────────────
    "back_button": {
        "ru": "←  Назад",
        "en": "←  Back",
    },
    "settings_title": {
        "ru": "Настройки",
        "en": "Settings",
    },
    "section_server": {
        "ru": "СЕРВЕР",
        "en": "SERVER",
    },
    "section_playback": {
        "ru": "ВОСПРОИЗВЕДЕНИЕ",
        "en": "PLAYBACK",
    },
    "normalize_title": {
        "ru": "Нормализация громкости",
        "en": "Volume normalization",
    },
    "normalize_sub": {
        "ru": "Выравнивает громкость треков",
        "en": "Evens out track loudness",
    },
    "radio_title": {
        "ru": "Радио-режим",
        "en": "Radio mode",
    },
    "radio_sub": {
        "ru": "Когда очередь кончается, бот продолжает похожими треками",
        "en": "When the queue ends, the bot continues with similar tracks",
    },
    "crossfade_title": {
        "ru": "Кроссфейд",
        "en": "Crossfade",
    },
    "crossfade_sub": {
        "ru": "Плавный переход между треками (6 секунд)",
        "en": "Smooth 6-second transition between tracks",
    },
    "section_app": {
        "ru": "ПРИЛОЖЕНИЕ",
        "en": "APPLICATION",
    },
    # Deliberately bilingual in BOTH languages so any user can find the
    # switch no matter which language is currently active.
    "lang_label": {
        "ru": "Язык / Language",
        "en": "Язык / Language",
    },
    # Language names are always shown in their own language (native names).
    "lang_russian": {
        "ru": "Русский",
        "en": "Русский",
    },
    "lang_english": {
        "ru": "English",
        "en": "English",
    },
    "lang_restart_hint": {
        "ru": "Применится после перезапуска",
        "en": "Applies after restart",
    },
    "restart_now": {
        "ru": "Перезапустить",
        "en": "Restart now",
    },
    "section_account": {
        "ru": "АККАУНТ",
        "en": "ACCOUNT",
    },
    "logout_button": {
        "ru": "Выйти из аккаунта",
        "en": "Log out",
    },
    "client_version": {
        "ru": "Medral Client v{version}",
        "en": "Medral Client v{version}",
    },

    # ── channel panel (channel_panel.py, not wired yet) ───────────────────
    "no_server_header": {
        "ru": "НЕТ СЕРВЕРА",
        "en": "NO SERVER",
    },
    "voice_channels_header": {
        "ru": "ГОЛОСОВЫЕ КАНАЛЫ",
        "en": "VOICE CHANNELS",
    },
    "connect_bot": {
        "ru": "Подключить бота",
        "en": "Connect Bot",
    },
    "disconnect_bot": {
        "ru": "Отключить бота",
        "en": "Disconnect Bot",
    },

    # ── search panel (search_panel.py, not wired yet) ─────────────────────
    "search_placeholder": {
        "ru": "Поиск на YouTube — трек, исполнитель или ссылка YouTube/Spotify…",
        "en": "Search YouTube — song, artist, or paste a YouTube/Spotify URL…",
    },
    "search_button": {
        "ru": "Поиск",
        "en": "Search",
    },
    "add_to_queue_tip": {
        "ru": "Добавить в очередь",
        "en": "Add to queue",
    },
    "unknown_title": {
        "ru": "Без названия",
        "en": "Unknown Title",
    },
    "unknown_artist": {
        "ru": "Неизвестный исполнитель",
        "en": "Unknown Artist",
    },

    # ── player panel (player_panel.py, not wired yet) ─────────────────────
    "nothing_playing": {
        "ru": "Ничего не играет",
        "en": "Nothing playing",
    },
    "unknown": {
        "ru": "Неизвестно",
        "en": "Unknown",
    },
    "loop_off": {
        "ru": "Повтор: выкл",
        "en": "Loop: off",
    },
    "loop_queue": {
        "ru": "Повтор: очередь",
        "en": "Loop: queue",
    },
    "loop_track": {
        "ru": "Повтор: трек",
        "en": "Loop: track",
    },
    "shuffle_tip": {
        "ru": "Перемешать очередь",
        "en": "Shuffle queue",
    },
    "previous_tip": {
        "ru": "Предыдущий",
        "en": "Previous",
    },
    "skip_tip": {
        "ru": "Следующий",
        "en": "Skip",
    },
    "volume_tip": {
        "ru": "Громкость",
        "en": "Volume",
    },
    "play_pause_tip": {
        "ru": "Играть / Пауза",
        "en": "Play / Pause",
    },

    # ── queue panel (queue_panel.py, not wired yet) ───────────────────────
    "queue_header": {
        "ru": "ОЧЕРЕДЬ",
        "en": "QUEUE",
    },
    "remove_from_queue": {
        "ru": "Убрать из очереди",
        "en": "Remove from queue",
    },
    "move_up": {
        "ru": "Выше",
        "en": "Move up",
    },
    "move_down": {
        "ru": "Ниже",
        "en": "Move down",
    },

    # ── plural forms (tr_n) ───────────────────────────────────────────────
    # ru: 1 трек / 2 трека / 5 треков; en: 1 track / 2 tracks
    "track_one": {
        "ru": "трек",
        "en": "track",
    },
    "track_few": {
        "ru": "трека",
        "en": "tracks",
    },
    "track_many": {
        "ru": "треков",
        "en": "tracks",
    },
}


# ── language state ────────────────────────────────────────────────────────

def get_lang() -> str:
    return _lang


def set_lang(lang: str) -> None:
    """Switch the active language; unsupported values are ignored."""
    global _lang
    if isinstance(lang, str) and lang.lower() in SUPPORTED_LANGS:
        _lang = lang.lower()


def init_lang(saved: str | None = None) -> str:
    """Pick the startup language: saved config value or the system locale.

    Must run BEFORE any widget is created — tr() is called at build time.
    Without a saved value: ru-* system locale → "ru", anything else → "en".
    """
    global _lang
    if isinstance(saved, str) and saved.lower() in SUPPORTED_LANGS:
        _lang = saved.lower()
        return _lang
    name = ""
    try:
        from PyQt6.QtCore import QLocale
        name = QLocale.system().name()          # e.g. "ru_RU", "en_US"
    except Exception:
        pass
    _lang = "ru" if name.startswith("ru") else "en"
    return _lang


# ── lookup ────────────────────────────────────────────────────────────────

def tr(key: str, *args, **kwargs) -> str:
    """Translate `key` for the active language; never raises.

    Unknown key → the key itself.  *args/**kwargs are substituted with
    str.format ({} / {n} / {version} …); a broken template comes back raw.
    """
    entry = _CATALOG.get(key)
    if entry is None:
        return key
    text = entry.get(_lang) or entry.get("en") or key
    if args or kwargs:
        try:
            return text.format(*args, **kwargs)
        except Exception:
            return text
    return text


def _plural_form(lang: str, n: int) -> str:
    """CLDR-style plural category: ru → one/few/many, en → one/many."""
    n = abs(int(n))
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"                        # 1, 21, 31 … but not 11
        if 2 <= n % 10 <= 4 and not (12 <= n % 100 <= 14):
            return "few"                        # 2-4, 22-24 … but not 12-14
        return "many"                           # 0, 5-20, 25-30 …
    return "one" if n == 1 else "many"


def tr_n(key: str, n: int, **kwargs) -> str:
    """Plural-aware tr: looks up "{key}_{form}" for the count `n`.

    Returns the correct form (e.g. tr_n("track", 2) → "трека"); an {n}
    placeholder inside the value is substituted too.  Never raises.
    """
    try:
        form = _plural_form(_lang, n)
    except Exception:
        return key
    full_key = f"{key}_{form}"
    entry = _CATALOG.get(full_key)
    if entry is None:
        return full_key
    text = entry.get(_lang) or entry.get("en") or full_key
    try:
        return text.format(n=n, **kwargs)
    except Exception:
        return text
