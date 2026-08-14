import os
import sys
import json
import socket
import secrets
import subprocess
import tempfile
import threading
import time
import webbrowser
from pathlib import Path


# ── server mode ───────────────────────────────────────────────────────────────
# When the exe is launched with --server it runs the FastAPI/Discord server
# instead of the GUI.  The GUI client starts it this way for local mode.

def _run_server() -> None:
    frozen = getattr(sys, "frozen", False)

    if frozen:
        root = Path(sys.executable).parent
    else:
        root = Path(__file__).parent.parent          # client/ → project root
        bot_dir = root / "bot"
        if str(bot_dir) not in sys.path:
            sys.path.insert(0, str(bot_dir))

    os.chdir(str(root))                              # load_dotenv() in api.py finds .env here

    import uvicorn
    import api as _api                               # bot/api.py (on sys.path)
    uvicorn.run(_api.app, host=_api.API_HOST, port=_api.API_PORT, reload=False)


if "--server" in sys.argv:
    _run_server()
    sys.exit(0)


# ── normal GUI mode ───────────────────────────────────────────────────────────

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QWidget,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QFont

sys.path.insert(0, str(Path(__file__).parent))

from styles          import STYLESHEET
from defaults        import DEFAULT_HOST, DEFAULT_PORT, SENTRY_DSN, SPLASH_VERSION
from network         import ApiClient
from ui.main_window   import MainWindow
from ui.splash_screen import SplashScreen
from ui.splash_screen_v2 import SplashScreenV2


# ── version ───────────────────────────────────────────────────────────────────

def _read_version() -> str:
    for candidate in (
        Path(__file__).parent / "version.txt",
        Path(__file__).parent.parent / "version.txt",
        Path(sys.executable).parent / "version.txt",
    ):
        if candidate.exists():
            return candidate.read_text().strip()
    return "0.0.0"


CLIENT_VERSION = _read_version()
CONFIG_FILE = Path.home() / ".medral" / "config.json"


def _load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {"host": DEFAULT_HOST, "port": DEFAULT_PORT}


def _save_config(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


# ── server auto-start ─────────────────────────────────────────────────────────

def _is_server_running(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def _start_local_server() -> bool:
    """Launch this same exe with --server in a hidden window."""
    exe = Path(sys.executable)
    subprocess.Popen(
        [str(exe), "--server"],
        creationflags=subprocess.CREATE_NO_WINDOW,
        cwd=str(exe.parent),
    )
    return True


# ── auto-update ───────────────────────────────────────────────────────────────

def _ver_tuple(v: str):
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


class _AutoUpdater(QObject):
    """Silent client self-update — no dialogs, ever.

    Periodically checks GET /version in a daemon thread; when the server has
    a newer build, streams it into a temp file, verifies its md5 against the
    server-provided client_md5 and only then emits update_ready(version).
    A corrupted or truncated download is deleted immediately and retried on
    the next cycle.  The actual swap is done by a .bat script: apply_now()
    replaces the exe and restarts the app, apply_on_exit() (wired to
    app.aboutToQuit) replaces it silently on the way out.
    """

    update_ready = pyqtSignal(str)          # version of the verified download

    FIRST_CHECK_MS    = 3500
    CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000  # every 4 hours
    _TMP_PREFIX = "MedralUpdate-"

    def __init__(self, host: str, port: int, current_version: str) -> None:
        super().__init__()
        self._host    = host
        self._port    = port
        self._current = current_version
        self._pending: str | None = None    # path of the verified new exe
        self._pending_version = ""
        self._applied  = False              # guard against a double swap
        self._checking = False              # one check at a time

        self._timer = QTimer(self)
        self._timer.setInterval(self.CHECK_INTERVAL_MS)
        self._timer.timeout.connect(self._check_in_background)

    # ── public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        """First check shortly after launch, then every CHECK_INTERVAL_MS."""
        self._cleanup_stale_downloads()
        QTimer.singleShot(self.FIRST_CHECK_MS, self._check_in_background)
        self._timer.start()

    def _cleanup_stale_downloads(self) -> None:
        # Downloads left behind by a crash never get applied (each cycle
        # uses a fresh random name) — sweep them so %TEMP% stays clean
        try:
            for p in Path(tempfile.gettempdir()).glob(self._TMP_PREFIX + "*"):
                if self._pending and str(p) == self._pending:
                    continue
                try:
                    p.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def apply_now(self) -> None:
        """Swap the exe and restart the app (update banner clicked)."""
        if self._spawn_swap_script(restart=True):
            QApplication.quit()

    def apply_on_exit(self) -> None:
        """Swap the exe silently while quitting (wired to app.aboutToQuit)."""
        self._spawn_swap_script(restart=False)

    # ── check & download (daemon thread) ──────────────────────────────────

    def _check_in_background(self) -> None:
        # Skip when an update is already downloaded/applied or a check runs
        if self._pending is not None or self._applied or self._checking:
            return
        self._checking = True
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self) -> None:
        try:
            self._do_check()
        except Exception as e:
            # Silent by design: log to stdout, retry on the next cycle
            print(f"[updater] check failed: {e}")
        finally:
            self._checking = False

    def _do_check(self) -> None:
        import hashlib
        import urllib.request

        base = f"http://{self._host}:{self._port}"
        with urllib.request.urlopen(f"{base}/version", timeout=10) as r:
            data = json.loads(r.read())
        latest = data.get("client", "0.0.0")
        if not data.get("client_available"):
            return
        if _ver_tuple(latest) <= _ver_tuple(self._current):
            return
        # Servers older than this feature send no client_md5 — the hash
        # verification is then skipped (size check below still applies).
        expected_md5 = data.get("client_md5") or None

        md5 = hashlib.md5()
        tmp_file = tempfile.NamedTemporaryFile(
            suffix=".exe", prefix=self._TMP_PREFIX, delete=False
        )
        tmp_path = tmp_file.name
        try:
            with tmp_file, urllib.request.urlopen(
                f"{base}/update/client", timeout=60
            ) as resp:
                total = int(resp.headers.get("content-length", 0) or 0)
                done  = 0
                while chunk := resp.read(65536):
                    tmp_file.write(chunk)
                    md5.update(chunk)
                    done += len(chunk)
            if total and done != total:
                raise ValueError(f"truncated download: {done} of {total} bytes")
            if expected_md5 and md5.hexdigest().lower() != expected_md5.lower():
                raise ValueError("md5 mismatch — corrupted download")
        except Exception:
            # Never keep a partial or corrupted file around
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        self._pending = tmp_path
        self._pending_version = latest
        print(f"[updater] version {latest} downloaded and verified: {tmp_path}")
        self.update_ready.emit(latest)

    # ── apply (bat swap script) ───────────────────────────────────────────

    def _spawn_swap_script(self, restart: bool) -> bool:
        """Write and launch the swap .bat. Returns True when the app should quit."""
        if self._pending is None or self._applied:
            return False
        self._applied = True

        if not getattr(sys, "frozen", False):
            # Dev run: sys.executable is python.exe — never overwrite it
            print(f"[updater] not frozen — swap skipped, update left at {self._pending}")
            return False

        exe = Path(sys.executable)
        # goto-based retry: the running exe stays locked until this process
        # actually exits, so the move may need a few attempts. If it never
        # succeeds, the downloaded file is removed and the old exe keeps
        # working — a half-swapped install is impossible with move /y.
        lines = [
            "@echo off",
            "chcp 65001 >nul",
            "set tries=0",
            ":retry",
            "ping 127.0.0.1 -n 3 >nul",
            f'move /y "{self._pending}" "{exe}" >nul',
            "if not errorlevel 1 goto done",
            "set /a tries+=1",
            "if %tries% lss 10 goto retry",
            f'del "{self._pending}" >nul',
            "goto cleanup",
            ":done",
        ]
        if restart:
            lines.append(f'start "" "{exe}"')
        lines += [":cleanup", 'del "%~f0"']

        bat = tempfile.mktemp(suffix=".bat")
        Path(bat).write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
        subprocess.Popen(["cmd", "/c", bat], creationflags=subprocess.CREATE_NO_WINDOW)
        return True


# ── Discord login ─────────────────────────────────────────────────────────────

class LoginDialog(QDialog):
    """OAuth-вход через Discord: открывает браузер и поллит /auth/poll.

    Поллинг — QTimer каждые 2 с + urllib в daemon-потоке (в daemon-потоке),
    UI не блокируется. Таймаут 180 с. «Отмена» = reject → выход из приложения.
    """

    _poll_done = pyqtSignal(dict)   # daemon thread → UI thread (queued)

    def __init__(self, host: str, port: int, parent=None) -> None:
        super().__init__(parent)
        self._host     = host
        self._port     = port
        self._state    = ""
        self._deadline = 0.0
        self._polling  = False

        self.result_token    = ""
        self.result_user_id  = ""
        self.result_username = ""

        self.setWindowTitle("Medral — вход")
        self.setFixedSize(420, 300)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._poll_tick)
        self._poll_done.connect(self._on_poll_done)

        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 32, 36, 28)
        root.setSpacing(0)

        logo = QLabel("♪  MEDRAL")
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(logo)
        root.addSpacing(16)

        sub = QLabel("Войди через Discord, чтобы управлять ботом")
        sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        sub.setWordWrap(True)
        sub.setStyleSheet("color:#7d8590; font-size:12px;")
        root.addWidget(sub)
        root.addSpacing(22)

        self._login_btn = QPushButton("Войти через Discord")
        self._login_btn.setObjectName("primaryBtn")
        self._login_btn.setDefault(True)
        self._login_btn.clicked.connect(self._start_login)
        root.addWidget(self._login_btn)
        root.addSpacing(8)

        # Для тех, у кого нужный Discord-аккаунт в другом браузере:
        # копирует ссылку входа вместо открытия браузера по умолчанию.
        self._copy_btn = QPushButton("Скопировать ссылку для другого браузера")
        self._copy_btn.setStyleSheet(
            "QPushButton { background:transparent; border:none; color:#6b6b8a;"
            " font-size:11px; text-decoration:underline; }"
            "QPushButton:hover { color:#A78BFA; }"
        )
        self._copy_btn.clicked.connect(self._copy_login_link)
        root.addWidget(self._copy_btn)
        root.addSpacing(10)

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#6b6b8a; font-size:11px;")
        root.addWidget(self._status)
        root.addStretch()

        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        root.addWidget(cancel)

    # ── login flow ────────────────────────────────────────────────────────

    def _begin(self, open_browser: bool) -> None:
        self._state    = secrets.token_urlsafe(24)
        self._deadline = time.monotonic() + 180
        self._login_btn.setEnabled(False)
        url = f"http://{self._host}:{self._port}/auth/login?state={self._state}"
        if open_browser:
            self._status.setText("Открыл браузер — подтверди вход и вернись сюда…")
            webbrowser.open(url)
        else:
            QApplication.clipboard().setText(url)
            self._status.setText(
                "Ссылка скопирована — вставь её в браузер с нужным "
                "аккаунтом Discord и подтверди вход"
            )
        self._timer.start()

    def _start_login(self) -> None:
        self._begin(open_browser=True)

    def _copy_login_link(self) -> None:
        self._begin(open_browser=False)

    def _fail(self, message: str) -> None:
        self._status.setText(message)
        self._login_btn.setEnabled(True)

    def _poll_tick(self) -> None:
        if time.monotonic() >= self._deadline:
            self._timer.stop()
            self._fail("Не дождался входа, попробуй ещё раз")
            return
        if self._polling:
            return
        self._polling = True
        threading.Thread(
            target=self._poll_once, args=(self._state,), daemon=True
        ).start()

    def _poll_once(self, state: str) -> None:
        import urllib.request, urllib.error, json as _json
        try:
            with urllib.request.urlopen(
                f"http://{self._host}:{self._port}/auth/poll?state={state}", timeout=5
            ) as r:
                data = _json.loads(r.read())
        except urllib.error.HTTPError as e:
            # 404 = state неизвестен/протух (например, сервер перезапустился)
            # — ждать дальше бессмысленно
            data = {"status": "expired"} if e.code == 404 else {}
        except Exception:
            data = {}   # сеть — просто ждём следующий тик
        self._poll_done.emit(data if isinstance(data, dict) else {})

    def _on_poll_done(self, data: dict) -> None:
        self._polling = False
        if not self._timer.isActive():
            return   # уже таймаут или отмена
        if data.get("status") == "expired":
            self._timer.stop()
            self._fail("Сессия входа устарела — нажми кнопку ещё раз")
            return
        if data.get("status") == "ok" and data.get("token"):
            self._timer.stop()
            self.result_token    = data["token"]
            self.result_user_id  = str(data.get("user_id", ""))
            self.result_username = data.get("username", "")
            self.accept()

    def reject(self) -> None:
        self._timer.stop()
        super().reject()

    # frameless drag (как у ConnectDialog)
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if ev.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(ev.globalPosition().toPoint() - self._drag_pos)


# ── connection dialog ─────────────────────────────────────────────────────────

class ConnectDialog(QDialog):
    def __init__(self, cfg: dict) -> None:
        super().__init__()
        self.result_host = ""
        self.result_port = 8000
        self.setWindowTitle("Medral")
        self.setFixedSize(420, 280)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self._build(cfg)

    def _build(self, cfg: dict) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(36, 36, 36, 36)
        root.setSpacing(0)

        title = QLabel("Connect to server")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        root.addSpacing(6)

        sub = QLabel(f"Client v{CLIENT_VERSION} — Enter the address of your Medral server.")
        sub.setStyleSheet("color:#7d8590; font-size:12px;")
        root.addWidget(sub)
        root.addSpacing(20)

        h_row = QHBoxLayout()
        h_lbl = QLabel("Host")
        h_lbl.setFixedWidth(40)
        h_lbl.setStyleSheet("color:#7d8590;")
        self._host = QLineEdit(cfg.get("host", "127.0.0.1"))
        self._host.setPlaceholderText("127.0.0.1  или  IP сервера")
        h_row.addWidget(h_lbl)
        h_row.addWidget(self._host)
        root.addLayout(h_row)
        root.addSpacing(10)

        p_row = QHBoxLayout()
        p_lbl = QLabel("Port")
        p_lbl.setFixedWidth(40)
        p_lbl.setStyleSheet("color:#7d8590;")
        self._port = QLineEdit(str(cfg.get("port", 8000)))
        self._port.setPlaceholderText("8000")
        p_row.addWidget(p_lbl)
        p_row.addWidget(self._port)
        root.addLayout(p_row)
        root.addSpacing(8)

        self._hint = QLabel("")
        self._hint.setStyleSheet("color:#3fb950; font-size:11px;")
        root.addWidget(self._hint)
        root.addSpacing(16)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        local_btn = QPushButton("Запустить локально")
        local_btn.setToolTip("Запустить встроенный сервер на этом ПК")
        local_btn.clicked.connect(self._on_local)
        btn_row.addWidget(local_btn)

        connect = QPushButton("Подключиться")
        connect.setObjectName("primaryBtn")
        connect.setDefault(True)
        connect.clicked.connect(self._on_connect)
        btn_row.addWidget(connect)
        root.addLayout(btn_row)

    def _on_local(self) -> None:
        host, port = "127.0.0.1", 8000
        if not _is_server_running(host, port):
            self._hint.setText("Запускаю сервер…")
            QApplication.processEvents()
            if not _start_local_server():
                self._hint.setText("Не удалось запустить сервер.")
                return
            for _ in range(20):
                QApplication.processEvents()
                import time
                time.sleep(0.5)
                if _is_server_running(host, port):
                    break
            else:
                self._hint.setText("Сервер не ответил за 10 сек.")
                return
        self._hint.setText("Сервер запущен!")
        self.result_host = host
        self.result_port = port
        self.accept()

    def _on_connect(self) -> None:
        h = self._host.text().strip()
        if not h:
            self._host.setFocus()
            return
        try:
            p = int(self._port.text().strip())
        except ValueError:
            p = 8000
        self.result_host = h
        self.result_port = p
        self.accept()

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, ev) -> None:
        if ev.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(ev.globalPosition().toPoint() - self._drag_pos)


# ── entry point ───────────────────────────────────────────────────────────────

def _load_fonts() -> None:
    """Load Syne + DM Sans.

    Primary source: fonts/ shipped next to the code (client/fonts in dev,
    _MEIPASS/fonts inside the PyInstaller exe).  Fallback: ~/.medral/fonts.
    """
    from PyQt6.QtGui import QFontDatabase
    bundled  = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "fonts"
    fallback = Path.home() / ".medral" / "fonts"
    loaded = 0
    for fonts_dir in (bundled, fallback):
        if not fonts_dir.is_dir():
            continue
        for f in sorted(fonts_dir.glob("*.ttf")):
            if QFontDatabase.addApplicationFont(str(f)) >= 0:
                loaded += 1
        if loaded:
            break


def _play_startup_sound() -> None:
    """Play the short startup chime (async, best-effort).

    Same _MEIPASS pattern as _load_fonts: sounds/ ships next to the code in
    dev and inside the PyInstaller exe.  Missing file or non-Windows platform
    is silently ignored.
    """
    try:
        import winsound
        # A startup.wav dropped next to the exe overrides the bundled one,
        # so the sound can be swapped without rebuilding
        override = Path(sys.executable).parent / "startup.wav"
        bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "sounds" / "startup.wav"
        path = override if override.is_file() else bundled
        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
    except Exception:
        pass


def _init_sentry() -> None:
    """Crash reporting for the client (no-op with an empty SENTRY_DSN)."""
    if not SENTRY_DSN:
        return
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            environment="client",
            release=CLIENT_VERSION,
            traces_sample_rate=0,
            send_default_pii=False,
        )
    except Exception:
        pass


def _install_excepthook() -> None:
    """Log unhandled slot exceptions instead of letting PyQt6 abort the app.

    Without a custom excepthook PyQt6 calls qFatal() on any Python exception
    that escapes a slot — the process dies with 0xc0000409 and no trace.
    Errors are also forwarded to Sentry when it is configured.
    """
    import traceback
    from datetime import datetime
    log_file = Path.home() / ".medral" / "client.log"

    def hook(exc_type, exc_value, exc_tb):
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] Unhandled exception:\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass
        if SENTRY_DSN:
            try:
                import sentry_sdk
                sentry_sdk.capture_exception(exc_value)
            except Exception:
                pass
        traceback.print_exception(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def main() -> None:
    _init_sentry()
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName("Medral")
    app.setStyleSheet(STYLESHEET)

    _load_fonts()
    app.setFont(QFont("DM Sans", 10))

    cfg   = _load_config()
    host  = cfg.get("host", DEFAULT_HOST)
    port  = cfg.get("port", DEFAULT_PORT)
    token = cfg.get("token") or None

    client = ApiClient(host, port)
    client.set_token(token)
    client.start()

    window = MainWindow(client)

    def _show_login() -> bool:
        """Модальный вход через Discord. Отмена = выход из приложения."""
        c   = _load_config()   # host/port могли смениться через «Change server»
        dlg = LoginDialog(
            c.get("host", DEFAULT_HOST), c.get("port", DEFAULT_PORT),
            parent=window if window.isVisible() else None,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            c["token"]    = dlg.result_token
            c["username"] = dlg.result_username
            _save_config(c)
            client.set_token(dlg.result_token)
            window.set_username(dlg.result_username)
            client.fetch_guilds()
            return True
        QApplication.quit()
        return False

    window.set_login_handler(_show_login)

    if token is None:
        # входим ДО показа главного окна (request_login → guard от повторов)
        if not window.request_login():
            client.stop()
            sys.exit(0)
    else:
        window.set_username(cfg.get("username", ""))

    splash_cls = SplashScreen if SPLASH_VERSION == "v1" else SplashScreenV2
    splash = splash_cls()
    splash.show()

    def _on_splash_done() -> None:
        # The chime marks the moment loading ends and the window appears
        _play_startup_sound()
        window.show()
        QTimer.singleShot(800, client.fetch_guilds)
        if token is not None:
            # валидация сохранённого токена в фоне; при 401 → auth_required
            QTimer.singleShot(1200, client.auth_me)

    splash.closed.connect(_on_splash_done)

    updater = _AutoUpdater(host, port, CLIENT_VERSION)     # keep a reference alive
    window.set_updater(updater)                            # topbar update banner
    app.aboutToQuit.connect(updater.apply_on_exit)         # silent swap on close
    updater.start()

    ret = app.exec()
    client.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()
