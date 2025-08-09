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
