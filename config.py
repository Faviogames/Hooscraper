import os

# Rutas de directorios
OUTPUT_PATH = "output"
BACKUP_PATH = "backups"

# Nombre del archivo de log
LOG_FILE_NAME = "log.txt"

# URL base para Flashscore
BASE_URL = "https://www.flashscore.com"

# Tiempos de espera para Selenium (en milisegundos)
TIMEOUT_FAST = 10000  # 10 segundos
TIMEOUT_SLOW = 30000  # 30 segundos

# Número máximo de clics en el botón "Mostrar más partidos" en la página de resultados de la liga.
MAX_SHOW_MORE_CLICKS = 30

# Configuración de optimización de Selenium
DISABLE_IMAGES = True  # True para desactivar carga de imágenes y acelerar navegación

# Configuración para ligas grandes
AUTO_SHUTDOWN_THRESHOLD = 500  # Número de partidos para activar apagado automático
MAX_RECONNECTION_ATTEMPTS = 5  # Máximo intentos de reconexión antes de fallar
RECONNECTION_DELAY = 30  # Segundos de espera entre intentos de reconexión

# Configuración para evitar bloqueos de Flashscore
MATCHES_PER_BATCH = 250  # Número de partidos antes de pausa automática
BATCH_PAUSE_MESSAGE = True  # Mostrar mensaje de pausa en modo interactivo

# User-Agents para simular diferentes navegadores
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ====================================================================
# --- CONFIGURACIÓN DE ORDENAMIENTO DE DATOS ---
# ====================================================================

# Orden por defecto al actualizar (desc: más recientes primero)
DEFAULT_UPDATE_ORDER_DESC = True

# Preguntar en modo interactivo si se quiere corregir el orden antes de actualizar
ASK_FIX_ORDER_BEFORE_UPDATE = True

# Preguntar en modo interactivo si se quiere migrar a quarter_stats y backfill antes de actualizar
ASK_MIGRATE_QUARTER_STATS_BEFORE_UPDATE = True
# Habilitar extracción por cuartos y eliminación de totales
# Si True: el scraper extrae quarter_stats (Q1–Q4) y NO escribe match_stats totales
ENABLE_QUARTER_STATS = True
REMOVE_TOTAL_MATCH_STATS = True
# ====================================================================
# --- CONFIGURACIÓN DE ESTADÍSTICAS PARA BALONCESTO ---
# ====================================================================

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