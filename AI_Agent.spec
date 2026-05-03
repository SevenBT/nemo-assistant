# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

openai_datas, openai_binaries, openai_hiddenimports = collect_all('openai')
httpx_datas, httpx_binaries, httpx_hiddenimports = collect_all('httpx')
httpcore_datas, httpcore_binaries, httpcore_hiddenimports = collect_all('httpcore')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=openai_binaries + httpx_binaries + httpcore_binaries,
    datas=[
        *openai_datas,
        *httpx_datas,
        *httpcore_datas,
        # Ship the tools directory next to the exe so users can add/edit scripts
        # without repackaging.  At runtime TOOLS_DIR resolves to
        # Path(sys.executable).parent / "tools".
        ('tools', 'tools'),
    ],
    hiddenimports=[
        *openai_hiddenimports,
        *httpx_hiddenimports,
        *httpcore_hiddenimports,
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AI Agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AI Agent',
)
