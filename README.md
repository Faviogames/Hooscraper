# Hooscraper
A scraper for basketball that extract points and stats of a match and export it in a very well structured json
# 🏀 Flashscore Basketball Scraper

Este proyecto es un **scraper automatizado** que obtiene resultados, estadísticas y puntajes por cuartos de partidos de baloncesto desde [Flashscore](https://www.flashscore.com).  
Está diseñado para funcionar con **Selenium** y **Chrome WebDriver** de forma estable, pudiendo ejecutarse en modo **headless** o con interfaz gráfica.

---

## ✨ Características

- Extrae:
  - Nombre de equipos.
  - Puntajes totales y por cuartos (incluyendo tiempos extra).
  - Estadísticas por período (Q1, Q2, Q3, Q4, OT).
  - Fecha y etapa del partido.
- Genera archivo **JSON** con toda la información.
- Permite limitar la cantidad de partidos a extraer.
- Simula comportamiento humano para evitar bloqueos.

## 📦 Requisitos

- **Python 3.8+**
- Google Chrome instalado.
- Paquetes de Python (instalar con `pip install -r requirements.txt`)
  
selenium
webdriver-manager
⚙️ Configuración (config.py)
OUTPUT_PATH → Carpeta donde se guardarán los JSON.

BACKUP_PATH → Carpeta donde se guardarán las copias de seguridad.

BASE_URL → URL base de Flashscore.

USER_AGENTS → Lista de agentes de usuario para simular navegadores.

PREDEFINED_STAT_CATEGORIES_ORDER → Lista de estadísticas que se extraerán por cuarto.

🚀 Uso
Ejecutar el script desde la terminal:
python scraper.py --url "<URL_LIGA>" [opciones]
Parámetros disponibles
Parámetro	Requerido	Descripción
--url	✅ Sí	URL de la liga de baloncesto en Flashscore (página de resultados).
--output	❌ No	Nombre del archivo de salida (sin extensión). Si se omite, se genera automáticamente.
--last	❌ No	Número de partidos más recientes a extraer. Ej: --last 5 para los últimos 5 partidos.
--no-headless	❌ No	Ejecuta el navegador en modo visible (útil para depuración).

📄 Ejemplos de uso
Extraer todos los partidos de una temporada
`python scraper.py --url "https://www.flashscore.com/basketball/usa/nba/`
Extraer solo los últimos 10 partidos y guardar con nombre personalizado
`python scraper.py --url "https://www.flashscore.com/basketball/spain/acb/" --last 10 --output acb_ultimos10`
Ejecutar con navegador visible
`python scraper.py --url "https://www.flashscore.com/basketball/usa/nba-2024-2025/" --no-headless`

📂 Estructura del proyecto
`
├── scraper.py          # Script principal
├── config.py           # Configuración
├── output/             # Carpeta de resultados en JSON
├── backups/            # Carpeta de copias de seguridad
├── requirements.txt    # Dependencias
└── README.md           # Documentación`

📤 Salida (Ejemplo JSON)
`json
[
    {
        "match_id": "123abc",
        "stage": "Regular Season - Round 5",
        "date": "12.01.2025 20:00",
        "home_team": "Los Angeles Lakers",
        "away_team": "Boston Celtics",
        "home_score": "102",
        "away_score": "98",
        "quarter_scores": {
            "Q1": {"home_score": "25", "away_score": "22"},
            "Q2": {"home_score": "28", "away_score": "25"},
            "Q3": {"home_score": "20", "away_score": "26"},
            "Q4": {"home_score": "29", "away_score": "25"}
        },
        "quarter_stats": {
            "Q1": {
                "Los Angeles Lakers": {"field_goals_attempted": "20", "field_goals_made": "10"},
                "Boston Celtics": {"field_goals_attempted": "19", "field_goals_made": "9"}
            }
        },
        "scraped_at": "2025-01-13T15:45:00"
    }
]`
