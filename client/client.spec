# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for MedralPlayer.exe
# Single exe: GUI client + embedded server (--server flag)
# Build from project root:  pyinstaller client\client.spec
#
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).parent   # SPECPATH = client/, ROOT = project root

a = Analysis(
    [str(ROOT / 'client' / 'main.py')],
    pathex=[
        str(ROOT / 'client'),
        str(ROOT / 'bot'),      # 'import api', 'import bot', 'import audio'
    ],
    binaries=[],
    datas=[
        (str(ROOT / 'version.txt'),          '.'),
        (str(ROOT / 'client' / 'ui'),        'ui'),
        (str(ROOT / 'client' / 'styles.py'), '.'),
        (str(ROOT / 'client' / 'network.py'),'.'),
        # yt-dlp extractors
        (str(ROOT / 'venv' / 'Lib' / 'site-packages' / 'yt_dlp'), 'yt_dlp'),
    ],
    hiddenimports=[
        # ---- client ----
        'PyQt6', 'PyQt6.QtWidgets', 'PyQt6.QtCore',
        'PyQt6.QtGui', 'PyQt6.QtNetwork', 'PyQt6.sip',
        'aiohttp', 'aiohttp.connector', 'aiohttp.client',
        'websockets', 'websockets.legacy', 'websockets.legacy.client',
        # ---- server (bot modules) ----
        'api', 'bot', 'audio',
        # discord / py-cord
        'discord', 'discord.ext.commands',
        'discord.voice', 'discord.voice.client',
        'discord.voice.gateway', 'discord.voice.state',
        'discord.opus',
        'nacl', 'nacl.secret', 'nacl.utils', 'nacl.bindings',
        'davey',
        # fastapi / uvicorn
        'fastapi', 'fastapi.middleware.cors', 'fastapi.responses',
        'uvicorn', 'uvicorn.logging',
        'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
        'uvicorn.protocols', 'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan', 'uvicorn.lifespan.on',
        'websockets.legacy.server',
        # yt-dlp
        'yt_dlp', 'yt_dlp.extractor', 'yt_dlp.postprocessor',
        # pydantic
        'pydantic', 'pydantic.v1', 'pydantic_core',
        # other server deps
        'dotenv', 'multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'test', 'pydoc', 'matplotlib', 'numpy'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MedralPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
