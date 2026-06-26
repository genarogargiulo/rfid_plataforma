@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

echo.
echo ═══════════════════════════════════════════════════════════════
echo   RFID Plataforma — Build con PyInstaller
echo ═══════════════════════════════════════════════════════════════
echo.

:: ── Prerequisito: PyInstaller ────────────────────────────────────────────────
where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller no encontrado.
    echo         Instalar con: pip install pyinstaller
    echo.
    pause
    exit /b 1
)

:: ── Limpiar builds anteriores ─────────────────────────────────────────────────
echo [1/4] Limpiando builds anteriores...
if exist "dist\rfid_plataforma" (
    rmdir /s /q "dist\rfid_plataforma"
    echo       dist\rfid_plataforma eliminado.
)
if exist "build\rfid_plataforma" (
    rmdir /s /q "build\rfid_plataforma"
    echo       build\rfid_plataforma eliminado.
)

:: ── Compilar con PyInstaller ──────────────────────────────────────────────────
echo.
echo [2/4] Compilando con PyInstaller...
pyinstaller rfid_plataforma.spec
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo el build de PyInstaller.
    echo         Revisar el output de arriba para detalles.
    pause
    exit /b 1
)

:: ── Copiar archivos editables fuera de _internal/ ────────────────────────────
echo.
echo [3/4] Copiando archivos editables junto al ejecutable...

:: config.py va junto al .exe (no dentro de _internal/) para ser editable
copy /Y "app\core\config.py" "dist\rfid_plataforma\config.py" >nul
echo       config.py → dist\rfid_plataforma\config.py

:: Scripts SQL para que el cliente pueda configurar la BD
if not exist "dist\rfid_plataforma\sql" mkdir "dist\rfid_plataforma\sql"
copy /Y "sql\schema.sql"          "dist\rfid_plataforma\sql\" >nul
copy /Y "sql\usuarios_y_logs.sql" "dist\rfid_plataforma\sql\" >nul
echo       sql\ → dist\rfid_plataforma\sql\

:: Directorio de logs (NSSM lo usará)
if not exist "dist\rfid_plataforma\logs" mkdir "dist\rfid_plataforma\logs"
echo       logs\ creado.

:: ── Verificar resultado ───────────────────────────────────────────────────────
echo.
echo [4/4] Verificando resultado...
if not exist "dist\rfid_plataforma\rfid_plataforma.exe" (
    echo [ERROR] No se encontro dist\rfid_plataforma\rfid_plataforma.exe
    pause
    exit /b 1
)

echo.
echo ═══════════════════════════════════════════════════════════════
echo   Build exitoso. Estructura generada:
echo.
echo   dist\rfid_plataforma\
echo     rfid_plataforma.exe   ← ejecutable principal
echo     config.py             ← configuracion editable (DB, puertos, etc.)
echo     sql\                  ← scripts SQL para el cliente
echo     logs\                 ← directorio para logs del servicio
echo     _internal\            ← runtime de Python y dependencias (no editar)
echo.
echo   Siguiente paso:
echo     1. Descargar WinSW x64: https://github.com/winsw/winsw/releases
echo     2. Renombrar el .exe descargado a WinSW-x64.exe
echo     3. Copiarlo a installer\winsw\WinSW-x64.exe
echo     4. Abrir installer\setup.iss con Inno Setup 6.x y compilar
echo ═══════════════════════════════════════════════════════════════
echo.
pause
