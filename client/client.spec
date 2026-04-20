# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for MedralPlayer.exe
# Build from project root:  pyinstaller client\client.spec
#
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).parent   # SPECPATH = client/, ROOT = project root

a = Analysis(
    [str(ROOT / 'client' / 'main.py')],
    pathex=[str(ROOT / 'client')],
    binaries=[],
    datas=[
        # version file — placed next to the exe in dist/
        (str(ROOT / 'version.txt'), '.'),
        # UI modules loaded at runtime via sys.path
        (str(ROOT / 'client' / 'ui'), 'ui'),
        (str(ROOT / 'client' / 'styles.py'), '.'),
        (str(ROOT / 'client' / 'network.py'), '.'),
    ],
    hiddenimports=[
        'PyQt6',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtNetwork',
        'PyQt6.sip',
        'aiohttp',
        'aiohttp.connector',
        'aiohttp.client',
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'test', 'pydoc',
        'matplotlib', 'numpy',
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
    name='MedralPlayer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,    # GUI app — no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
