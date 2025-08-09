import os

# Rutas de directorios
OUTPUT_PATH = "output"
BACKUP_PATH = "backups"

# Nombre del archivo de log
LOG_FILE_NAME = "log.txt"

# URL base para Flashscore
BASE_URL = "https://www.flashscore.com"

# Tiempos de espera para Selenium (en milisegundos)
TIMEOUT_FAST = 10000 # 10 segundos
TIMEOUT_SLOW = 30000 # 30 segundos

# Número máximo de clics en el botón "Mostrar más partidos" en la página de resultados de la liga.
MAX_SHOW_MORE_CLICKS = 30

# User-Agents para simular diferentes navegadores
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ==============================================================================
# --- CONFIGURACIÓN DE ESTADÍSTICAS PARA BALONCESTO ---
# ==============================================================================

# Ya no necesitamos una lista de "no deseadas", ya que definiremos exactamente
# las que SÍ queremos en el orden correcto. Dejarla vacía es más seguro.
UNWANTED_STAT_CATEGORIES = {}

# Orden y lista completa de las categorías de estadísticas que SÍ queremos mantener.
# Estas son las que se extraerán de cada cuarto.
PREDEFINED_STAT_CATEGORIES_ORDER = [
    # Scoring
    "Field Goals Attempted",
    "Field Goals Made",
    "Field Goals %",
    "2-Point Field G. Attempted",
    "2-Point Field Goals Made",
    "2-Point Field Goals %",
    "3-Point Field G. Attempted",
    "3-Point Field Goals Made",
    "3-Point Field Goals %",
    "Free Throws Attempted",
    "Free Throws Made",
    "Free Throws %",
    # Rebounds
    "Offensive Rebounds",
    "Defensive Rebounds",
    "Total Rebounds",
    # Other
    "Assists",
    "Blocks",
    "Turnovers",
    "Steals",
    "Personal Fouls",
]
