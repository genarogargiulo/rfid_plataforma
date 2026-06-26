; ═══════════════════════════════════════════════════════════════════════════
;  FPT RFID Plataforma — Script de instalación Inno Setup 6.x
;
;  Prerequisitos para compilar este script:
;    - Inno Setup 6.x  (https://jrsoftware.org/isinfo.php)
;    - Build de PyInstaller en ..\dist\rfid_plataforma\
;    - WinSW x64 descargado de:
;        https://github.com/winsw/winsw/releases
;      Renombrar el .exe descargado a WinSW-x64.exe y colocarlo en:
;        installer\winsw\WinSW-x64.exe
;
;  Resultado: ..\dist_installer\FPT_RFID_Plataforma_v1.0.0_Setup.exe
; ═══════════════════════════════════════════════════════════════════════════

#define MyAppName      "FPT RFID Plataforma"
#define MyAppVersion   "1.0.0"
#define MyAppPublisher "FPT Córdoba"
#define MyWebPort      "5000"

[Setup]
; GUID único — no cambiar entre versiones (permite actualizaciones in-place)
AppId={{8C3D4E5F-6A7B-4890-BCDE-F01234567890}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=http://localhost:{#MyWebPort}
AppSupportURL=http://localhost:{#MyWebPort}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes

OutputDir=..\dist_installer
OutputBaseFilename=FPT_RFID_Plataforma_v{#MyAppVersion}_Setup

Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
MinVersion=10.0
UninstallDisplayIcon={app}\rfid_plataforma.exe
UninstallDisplayName={#MyAppName}

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "instalarservicio"; \
      Description: "Instalar como servicio de Windows (inicio automático con el sistema)"; \
      Flags: checked
Name: "accesodirecto"; \
      Description: "Crear acceso directo en el Escritorio (abre el panel en el navegador)"; \
      Flags: unchecked

[Files]
; ── Aplicación compilada (PyInstaller onedir) ──────────────────────────────
Source: "..\dist\rfid_plataforma\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; ── WinSW: se instala con el nombre que espera el XML de configuración ─────
; Descargar de https://github.com/winsw/winsw/releases
; Guardar como: installer\winsw\WinSW-x64.exe
Source: "winsw\WinSW-x64.exe"; \
    DestDir: "{app}"; \
    DestName: "rfid_plataforma_svc.exe"; \
    Flags: ignoreversion

; ── XML de configuración del servicio WinSW ───────────────────────────────
Source: "rfid_plataforma_svc.xml"; \
    DestDir: "{app}"; \
    Flags: ignoreversion

; ── Scripts de gestión del servicio ───────────────────────────────────────
Source: "service_install.bat";   DestDir: "{app}"; Flags: ignoreversion
Source: "service_uninstall.bat"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\logs"

[Icons]
Name: "{group}\Abrir panel RFID"; \
      Filename: "http://localhost:{#MyWebPort}"; \
      IconFilename: "{app}\rfid_plataforma.exe"
Name: "{group}\Carpeta de instalación"; \
      Filename: "{app}"
Name: "{group}\Desinstalar {#MyAppName}"; \
      Filename: "{uninstallexe}"
Name: "{userdesktop}\Panel RFID FPT"; \
      Filename: "http://localhost:{#MyWebPort}"; \
      Tasks: accesodirecto

[Run]
; Registrar e iniciar el servicio
Filename: "{app}\service_install.bat"; \
    Parameters: """{app}"""; \
    Flags: runhidden waituntilterminated; \
    Tasks: instalarservicio; \
    StatusMsg: "Registrando servicio de Windows..."

; Abrir el panel al finalizar
Filename: "http://localhost:{#MyWebPort}"; \
    Flags: nowait postinstall shellexec skipifsilent; \
    Description: "Abrir el panel RFID en el navegador"

[UninstallRun]
Filename: "{app}\service_uninstall.bat"; \
    Flags: runhidden waituntilterminated; \
    RunOnceId: "EliminarServicio"

[Code]
function OdbcDriverInstalado: Boolean;
begin
  Result :=
    RegKeyExists(HKLM, 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 17 for SQL Server') or
    RegKeyExists(HKLM, 'SOFTWARE\ODBC\ODBCINST.INI\ODBC Driver 18 for SQL Server');
end;

function InitializeSetup: Boolean;
var
  Res: Integer;
begin
  Result := True;
  if not OdbcDriverInstalado then
  begin
    Res := MsgBox(
      'No se detectó el driver ODBC de SQL Server en este equipo.' + #13#10 +
      #13#10 +
      'La plataforma RFID lo requiere para conectarse a la base de datos.' + #13#10 +
      'Descargarlo de: https://aka.ms/downloadmsodbcsql' + #13#10 +
      #13#10 +
      '¿Querés continuar la instalación de todas formas?',
      mbConfirmation, MB_YESNO
    );
    if Res = IDNO then
      Result := False;
  end;
end;

[Messages]
WelcomeLabel2=Este asistente instalará [name] en tu equipo.%n%n%
Antes de continuar, verificá que:%n%
  • El servidor SQL Server esté accesible en la red%n%
  • El driver ODBC 17 o 18 para SQL Server esté instalado%n%
  • Los scripts SQL (sql\schema.sql y sql\usuarios_y_logs.sql) ya%n%
    hayan sido ejecutados contra la base de datos de destino%n%n%
Se recomienda cerrar todas las aplicaciones antes de continuar.
