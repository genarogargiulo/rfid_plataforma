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
;  Resultado: ..\dist_installer\FPT_RFID_Plataforma_v1.1.0_Setup.exe
; ═══════════════════════════════════════════════════════════════════════════

#define MyAppName      "FPT RFID Plataforma"
#define MyAppDirName   "PLATAFORMA_RFID"
#define MyAppVersion   "1.1.0"
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

DefaultDirName={autopf}\{#MyAppDirName}
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
Name: "instalarservicio"; Description: "Instalar como servicio de Windows (inicio automático con el sistema)"
Name: "accesodirecto"; Description: "Crear acceso directo en el Escritorio (abre el panel en el navegador)"; Flags: unchecked

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

; ── Scripts de gestión del servicio y utilidades de soporte ───────────────
Source: "service_install.bat";   DestDir: "{app}"; Flags: ignoreversion
Source: "service_uninstall.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "resetear_password.bat"; DestDir: "{app}"; Flags: ignoreversion

[Dirs]
Name: "{app}\logs"

[Icons]
Name: "{group}\Abrir panel RFID"; \
      Filename: "http://localhost:{#MyWebPort}"; \
      IconFilename: "{app}\rfid_plataforma.exe"
Name: "{group}\Resetear contraseña de administrador"; \
      Filename: "{app}\resetear_password.bat"
Name: "{group}\Carpeta de instalación"; \
      Filename: "{app}"
Name: "{group}\Desinstalar {#MyAppName}"; \
      Filename: "{uninstallexe}"
Name: "{userdesktop}\Panel RFID FPT"; \
      Filename: "http://localhost:{#MyWebPort}"; \
      Tasks: accesodirecto

[Run]
; Abrir el panel al finalizar (el setup de BD y del servicio se maneja en
; CurStepChanged, más abajo, para poder mostrar errores en vez de fallar en silencio)
Filename: "http://localhost:{#MyWebPort}"; \
    Flags: nowait postinstall shellexec skipifsilent; \
    Description: "Abrir el panel RFID en el navegador"

[UninstallRun]
Filename: "{app}\service_uninstall.bat"; \
    Flags: runhidden waituntilterminated; \
    RunOnceId: "EliminarServicio"

[Code]
var
  PageAuth: TInputOptionWizardPage;
  PageDB: TInputQueryWizardPage;

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
      'No se detectó el driver ODBC de SQL Server en este equipo.' + #13#10 + #13#10 +
      'La plataforma RFID lo requiere para conectarse a la base de datos.' + #13#10 +
      'Descargarlo de: https://aka.ms/downloadmsodbcsql' + #13#10 + #13#10 +
      '¿Querés continuar la instalación de todas formas?',
      mbConfirmation, MB_YESNO
    );
    if Res = IDNO then
      Result := False;
  end;
end;

procedure InitializeWizard;
begin
  PageAuth := CreateInputOptionPage(wpSelectTasks,
    'Autenticación de Base de Datos',
    'Elegí cómo se va a conectar la aplicación a SQL Server',
    'Se recomienda autenticación de SQL Server: el servicio de Windows normalmente ' +
    'no corre con una cuenta que tenga acceso a la base de datos.',
    True, False);
  PageAuth.Add('Autenticación de SQL Server (usuario y contraseña)');
  PageAuth.Add('Autenticación de Windows (cuenta del servicio)');
  PageAuth.SelectedValueIndex := 0;

  PageDB := CreateInputQueryPage(PageAuth.ID,
    'Configuración de Base de Datos',
    'Datos de conexión a SQL Server',
    'Estos datos se usan para crear la base de datos (si no existe) y cargar las tablas ' +
    'automáticamente. Dejá "Servidor" y "Base de datos" en blanco si preferís omitir este ' +
    'paso y configurarlo después desde el panel web (Configuración).');
  PageDB.Add('Servidor SQL (ej: SERVIDOR\INSTANCIA):', False);
  PageDB.Add('Base de datos:', False);
  PageDB.Add('Usuario SQL (si no usás autenticación de Windows):', False);
  PageDB.Add('Contraseña SQL:', True);

  PageDB.Values[1] := 'RFID_FPT';
  PageDB.Values[2] := 'sa';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Servidor, BaseDatos: String;
begin
  Result := True;
  if CurPageID = PageDB.ID then
  begin
    Servidor := Trim(PageDB.Values[0]);
    BaseDatos := Trim(PageDB.Values[1]);
    if (Servidor = '') <> (BaseDatos = '') then
    begin
      MsgBox('Completá "Servidor" y "Base de datos" juntos, o dejá ambos en blanco para omitir este paso.',
        mbError, MB_OK);
      Result := False;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  Servidor, BaseDatos, Usuario, Password, Params: String;
  UsaWindowsAuth: Boolean;
begin
  if CurStep <> ssPostInstall then
    exit;

  { ── 1. Setup de base de datos (opcional, según lo cargado en el wizard) ── }
  Servidor := Trim(PageDB.Values[0]);
  BaseDatos := Trim(PageDB.Values[1]);
  Usuario := PageDB.Values[2];
  Password := PageDB.Values[3];
  UsaWindowsAuth := (PageAuth.SelectedValueIndex = 1);

  if (Servidor <> '') and (BaseDatos <> '') then
  begin
    Params := 'initdb --server "' + Servidor + '" --database "' + BaseDatos + '"';
    if UsaWindowsAuth then
      Params := Params + ' --trusted'
    else
      Params := Params + ' --user "' + Usuario + '" --password "' + Password + '"';

    if Exec(ExpandConstant('{app}\rfid_plataforma.exe'), Params, ExpandConstant('{app}'),
            SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    begin
      if ResultCode = 0 then
        MsgBox('Base de datos configurada correctamente.', mbInformation, MB_OK)
      else
        MsgBox(
          'No se pudo configurar la base de datos automáticamente (código ' + IntToStr(ResultCode) + ').' + #13#10 + #13#10 +
          'Revisá el detalle en: ' + ExpandConstant('{app}') + '\logs\db_init.log' + #13#10 + #13#10 +
          'Podés configurar la conexión manualmente después desde el panel web (Configuración), ' +
          'o volver a ejecutar este instalador.',
          mbError, MB_OK
        );
    end else
      MsgBox('No se pudo ejecutar rfid_plataforma.exe para configurar la base de datos.', mbError, MB_OK);
  end;

  { ── 2. Servicio de Windows ──────────────────────────────────────────────── }
  if WizardIsTaskSelected('instalarservicio') then
  begin
    if Exec(ExpandConstant('{app}\service_install.bat'), '"' + ExpandConstant('{app}') + '"',
            ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    begin
      if ResultCode <> 0 then
        MsgBox(
          'El servicio de Windows no pudo instalarse (código ' + IntToStr(ResultCode) + ').' + #13#10 + #13#10 +
          'Revisá el detalle en: ' + ExpandConstant('{app}') + '\logs\service_install.log' + #13#10 + #13#10 +
          'Causa habitual: el antivirus bloqueó rfid_plataforma_svc.exe. Agregá una exclusión ' +
          'para la carpeta de instalación y volvé a ejecutar service_install.bat como administrador.',
          mbError, MB_OK
        );
    end else
      MsgBox('No se pudo ejecutar service_install.bat.', mbError, MB_OK);
  end;
end;

[Messages]
WelcomeLabel2=Este asistente instalará [name] en tu equipo.%n%nAntes de continuar, verificá que:%n  • El servidor SQL Server esté accesible en la red%n  • El driver ODBC 17 o 18 para SQL Server esté instalado%n%nMás adelante vas a poder configurar la conexión a SQL Server y crear la base de datos automáticamente desde este mismo instalador.%n%nSe recomienda cerrar todas las aplicaciones antes de continuar.
