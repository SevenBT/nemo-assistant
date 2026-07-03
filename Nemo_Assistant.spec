# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

openai_datas, openai_binaries, openai_hiddenimports = collect_all('openai')
httpx_datas, httpx_binaries, httpx_hiddenimports = collect_all('httpx')
httpcore_datas, httpcore_binaries, httpcore_hiddenimports = collect_all('httpcore')
# litellm ships data files (model_prices_and_context_window_backup.json) that it
# reads at import time even with LITELLM_LOCAL_MODEL_COST_MAP=True. collect_all
# pulls in those data files + submodules; missing them => import fails at runtime.
litellm_datas, litellm_binaries, litellm_hiddenimports = collect_all('litellm')
# tiktoken registers its encodings (cl100k_base, etc.) via the tiktoken_ext
# namespace plugin package, discovered dynamically at runtime — PyInstaller's
# static analysis misses it, causing "Unknown encoding cl100k_base / Plugins
# found: []". collect_all grabs the plugin submodules + tiktoken's data files.
tiktoken_datas, tiktoken_binaries, tiktoken_hiddenimports = collect_all('tiktoken')
tiktoken_ext_hiddenimports = collect_submodules('tiktoken_ext')

# Built-in tools are discovered dynamically at runtime (pkgutil), so PyInstaller's
# static analysis won't see them. Force-collect every app.tools.* submodule.
tool_hiddenimports = collect_submodules('app.tools')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=openai_binaries + httpx_binaries + httpcore_binaries + litellm_binaries + tiktoken_binaries,
    datas=[
        *openai_datas,
        *httpx_datas,
        *httpcore_datas,
        *litellm_datas,
        *tiktoken_datas,
        # Bundle app assets. In onefile mode the bootloader unpacks these into
        # sys._MEIPASS at runtime; config.py resolves ASSETS_DIR against that
        # dir. Built-in tools live in the app.tools package (collected
        # automatically); user-added tools live in data/user_tools next to the
        # exe and are unaffected.
        ('assets', 'assets'),
    ],
    hiddenimports=[
        *openai_hiddenimports,
        *httpx_hiddenimports,
        *httpcore_hiddenimports,
        *litellm_hiddenimports,
        *tiktoken_hiddenimports,
        *tiktoken_ext_hiddenimports,
        *tool_hiddenimports,
        'apscheduler',
        'apscheduler.schedulers.background',
        'apscheduler.executors.pool',
        'apscheduler.jobstores.memory',
        'apscheduler.triggers.cron',
        'apscheduler.triggers.date',
        'apscheduler.triggers.interval',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        # Common packages that user scripts may import.
        # Add more here when bundling tools that need extra dependencies.
        'psutil',
        'requests',
        'runpy',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter', 'tk', 'tcl', 'gevent'],
    noarchive=False,
)

pyz = PYZ(a.pure)

# Onefile build: pack binaries + datas into a single self-extracting exe.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Nemo Assistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
)
