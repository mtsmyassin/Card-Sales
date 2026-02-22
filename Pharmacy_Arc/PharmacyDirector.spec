# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('logo.png', '.'), ('carthage.png', '.'), ('.env', '.')],
    hiddenimports=['flask', 'flask.templating', 'jinja2', 'werkzeug', 'werkzeug.serving', 'werkzeug.routing', 'supabase', 'gotrue', 'postgrest', 'realtime', 'storage3', 'supafunc', 'httpx', 'bcrypt', 'dotenv', 'threading'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='PharmacyDirector',
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
)
