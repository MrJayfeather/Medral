# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for MedralServer.exe
# Build from project root:  pyinstaller bot\server.spec
#
import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / 'bot' / 'api.py')],
    pathex=[str(ROOT), str(ROOT / 'bot')],
    binaries=[],
    datas=[
        # version file
        (str(ROOT / 'version.txt'), '.'),
        # yt-dlp extractor plugins
        ('venv/Lib/site-packages/yt_dlp', 'yt_dlp'),
    ],
    hiddenimports=[
        # discord / py-cord
        'discord',
        'discord.ext.commands',
        'discord.voice',
        'discord.voice.client',
        'discord.voice.gateway',
        'discord.voice.state',
        'discord.ext.pages',
        'discord.opus',
        'nacl',
        'nacl.secret',
        'nacl.utils',
        'nacl.bindings',
        # davey (DAVE E2EE)
        'davey',
        # fastapi / uvicorn
        'fastapi',
        'fastapi.middleware.cors',
        'fastapi.responses',
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'websockets',
        'websockets.legacy',
        'websockets.legacy.server',
        # yt-dlp
        'yt_dlp',
        'yt_dlp.extractor',
        'yt_dlp.postprocessor',
        # pydantic
        'pydantic',
        'pydantic.v1',
        'pydantic_core',
        # other
        'aiohttp',
        'dotenv',
        'multipart',
        'email',
        'email.mime',
        'email.mime.text',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'test', 'pydoc',
        'matplotlib', 'numpy', 'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
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
    name='MedralServer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,     # server needs console for logs
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
