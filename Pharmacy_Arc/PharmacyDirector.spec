# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('logo.png', '.'), ('carthage.png', '.'), ('templates', 'templates')],
    hiddenimports=['flask', 'flask.templating', 'jinja2', 'werkzeug', 'werkzeug.serving', 'werkzeug.routing', 'waitress', 'supabase', 'supabase._sync', 'supabase._sync.client', 'supabase.lib', 'supabase.lib.client_options', 'gotrue', 'gotrue._sync', 'gotrue._sync.client', 'gotrue._sync.gotrue_base_api', 'gotrue.http_clients', 'postgrest', 'postgrest._sync', 'realtime', 'storage3', 'supafunc', 'supabase_auth', 'supabase_functions', 'httpx', 'httpx._transports', 'h2', 'hpack', 'hyperframe', 'bcrypt', 'dotenv', 'threading', 'yarl'],
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
