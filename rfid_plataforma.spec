# -*- mode: python ; coding: utf-8 -*-
#
# rfid_plataforma.spec — Especificación de PyInstaller
#
# Uso:
#   pyinstaller rfid_plataforma.spec
#   (o usar build.bat que automatiza todo el proceso)
#
# Notas:
#   - Modo onedir: genera dist/rfid_plataforma/ con el .exe y _internal/
#   - config.py se copia FUERA de _internal/ (ver build.bat) para que sea
#     editable por el usuario y por la app en tiempo de ejecución.
#   - console=True es intencional: cuando se corre como servicio Windows
#     (via NSSM), stdout/stderr se redirigen a archivos de log.

a = Analysis(
    ['app/app.py'],
    pathex=['app/core'],
    binaries=[],
    datas=[
        # Assets web: templates y archivos estáticos
        ('app/templates', 'templates'),
        ('app/static',    'static'),
    ],
    hiddenimports=[
        # flask-socketio con async_mode="threading" (sin eventlet/gevent)
        'engineio.async_drivers.threading',
        'socketio.async_drivers.threading',
        # Módulos que PyInstaller no detecta automáticamente
        'flask_socketio',
        'flask_login',
        'pyodbc',
        'werkzeug.security',
        'werkzeug.middleware.proxy_fix',
        'pkg_resources.py2_warn',
    ],
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
    [],
    exclude_binaries=True,
    name='rfid_plataforma',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX puede causar falsos positivos en antivirus
    console=True,       # logs van a stdout/stderr → NSSM los captura a archivos
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='rfid_plataforma',
)
