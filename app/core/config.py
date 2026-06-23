# ── Conexión a SQL Server ───────────────────────────────────────────────
DB_DRIVER = "ODBC Driver 17 for SQL Server"   # Ver README si no está instalado
DB_SERVER = "GEN01\\SQL"                       # o "NOMBRE_SERVIDOR\\INSTANCIA"
DB_DATABASE = "RFID_FPT"

# Autenticación: Windows (Trusted) o SQL Server (usuario/clave)
DB_TRUSTED_CONNECTION = True
DB_USERNAME = "sa"          # usado solo si DB_TRUSTED_CONNECTION = False
DB_PASSWORD = "lediscet"          # usado solo si DB_TRUSTED_CONNECTION = False

DB_ENCRYPT = False                       # True si SQL Server exige conexión cifrada
DB_TRUST_SERVER_CERTIFICATE = True       # True para certificados autofirmados (entornos locales)

# ── Buffer de inserts en batch ──────────────────────────────────────────
# Cada cuántos segundos se vuelca el buffer de lecturas a SQL Server.
# Valores más bajos = más "tiempo real" en la BD, pero más carga de escritura.
INTERVALO_FLUSH_SEGUNDOS = 2.0
TAMANO_MAXIMO_BUFFER = 50_000   # límite de lecturas en memoria si la BD se cae

# ── Recarga de configuración de readers ─────────────────────────────────
# Cada cuántos segundos la app vuelve a leer dbo.Readers/dbo.Antenas desde
# la BD, para detectar readers nuevos agregados desde el panel sin reiniciar
# la aplicación completa.
INTERVALO_RECARGA_CONFIG_SEGUNDOS = 30

# ── Parámetros LLRP por defecto (usados si un reader no los especifica) ──
SESSION_DEFAULT = 2
TAG_POPULATION_DEFAULT = 4
REPORT_EVERY_N_TAGS = 1   # CRÍTICO: necesario para que el reader reporte en
                          # tiempo real. Ver notas en README sobre este punto.

# ── Servidor web ───────────────────────────────────────────────────────
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
