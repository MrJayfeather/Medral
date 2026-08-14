"""Spawning children from a frozen (PyInstaller) process.

A onefile exe unpacks itself into a temp dir and points PyInstaller/Qt
env vars at it.  A child spawned with the inherited environment reuses
that dir and dies with "no Qt platform plugin could be initialized" as
soon as the parent exits and deletes it — every relaunch of the exe must
pass env=child_env() to Popen.
"""

import os

# PyInstaller >= 6 and legacy onefile markers, plus Qt plugin paths
# pinned to the parent's extraction dir
_STALE_ENV_VARS = (
    "_PYI_APPLICATION_HOME_DIR",
    "_PYI_ARCHIVE_FILE",
    "_PYI_PARENT_PROCESS_LEVEL",
    "_MEIPASS2",
    "QT_PLUGIN_PATH",
    "QT_QPA_PLATFORM_PLUGIN_PATH",
)


def child_env() -> dict:
    env = os.environ.copy()
    for var in _STALE_ENV_VARS:
        env.pop(var, None)
    return env
