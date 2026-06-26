"""
config.py — Configuración general de la plataforma RFID.
Editado desde el panel web. Requiere reinicio de la aplicación para tomar efecto.
"""

# ── Conexión a SQL Server ───────────────────────────────────────────────
DB_DRIVER = "ODBC Driver 17 for SQL Server"
DB_SERVER = "GEN01\SQL"
DB_DATABASE = "RFID_FPT"

DB_TRUSTED_CONNECTION = True
DB_USERNAME = "sa"
DB_PASSWORD = "lediscet"

DB_ENCRYPT = False
DB_TRUST_SERVER_CERTIFICATE = True

# ── Buffer de inserts en batch ──────────────────────────────────────────
INTERVALO_FLUSH_SEGUNDOS = 2.0
TAMANO_MAXIMO_BUFFER = 50000

# ── Recarga de configuración de readers ─────────────────────────────────
INTERVALO_RECARGA_CONFIG_SEGUNDOS = 30

# ── Parámetros LLRP por defecto ──────────────────────────────────────────
SESSION_DEFAULT = 2
TAG_POPULATION_DEFAULT = 4
REPORT_EVERY_N_TAGS = 1

# ── Servidor web ───────────────────────────────────────────────────────
WEB_HOST = "0.0.0.0"
WEB_PORT = 5000
