import re
import time
import json
import logging
import random
import argparse
import os
import sys
import shutil
from contextlib import contextmanager
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Importar la configuración
import config

# Configuración del logging para mostrar información en la consola
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def ensure_directory_exists(path):
    """Asegura que un directorio exista, si no, lo crea."""
    if not os.path.exists(path):
        os.makedirs(path)
        logger.info(f"Directorio creado: {path}")

def get_base_league_name_from_url(league_url):
    """Extrae un nombre base de la URL para nombrar archivos."""
    clean_url = league_url.rstrip('/').split('?')[0]
    parts = clean_url.split('/')
    if len(parts) >= 3:
        return f"{parts[-2]}_{parts[-1]}".replace('-', '_')
    elif len(parts) >= 1 and parts[-1]:
        return parts[-1].replace('-', '_')
    return "flashscore_data"

def create_data_backup(filepath_to_backup, league_name):
    """Crea una copia de seguridad de un archivo de datos existente."""
    if not os.path.exists(filepath_to_backup):
        return
    try:
        ensure_directory_exists(config.BACKUP_PATH)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        original_filename = os.path.basename(filepath_to_backup)
        backup_file = os.path.join(config.BACKUP_PATH, f"{league_name}_{timestamp}_{original_filename}")
        shutil.copy2(filepath_to_backup, backup_file)
        logger.info(f"Backup creado: {backup_file}")
    except Exception as e:
        logger.error(f"Error creando backup de {filepath_to_backup}: {e}")

def print_progress_bar(iteration, total, prefix='', suffix='', length=50, fill='█'):
    """Muestra una barra de progreso en la terminal."""
    percent = ("{0:.1f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    sys.stdout.write(f'\r{prefix} |{bar}| {percent}% {suffix}')
    sys.stdout.flush()
    if iteration == total:
        sys.stdout.write('\n')
        sys.stdout.flush()

@contextmanager
def get_chrome_driver(headless=True):
    """Inicializa y gestiona el driver de Selenium."""
    driver = None
    try:
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument(f"user-agent={random.choice(config.USER_AGENTS)}")
        
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        yield driver
    except Exception as e:
        logger.error(f"Error al crear el driver de Chrome: {e}")
        raise
    finally:
        if driver:
            driver.quit()

def add_human_delay(min_delay=1, max_delay=3):
    """Añade una pausa aleatoria para simular comportamiento humano."""
    time.sleep(random.uniform(min_delay, max_delay))

def open_page_and_navigate(driver, url, timeout=30):
    """Navega a una URL específica."""
    logger.debug(f"Navegando a: {url}")
    driver.set_page_load_timeout(timeout)
    driver.get(url)
    add_human_delay(0.5, 1.5)

def wait_for_selector_safe(driver, selector, timeout=config.TIMEOUT_FAST):
    """Espera de forma segura a que un elemento aparezca en la página."""
    try:
        WebDriverWait(driver, timeout / 1000).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        return True
    except TimeoutException:
        return False

class FlashscoreMatchScraper:
    """Clase principal que contiene toda la lógica de scraping."""

    def _safe_get_text(self, driver, selector):
        """Obtiene el texto de un elemento de forma segura."""
        try:
            return driver.find_element(By.CSS_SELECTOR, selector).text.strip()
        except NoSuchElementException:
            return 'N/A'
            
    def _safe_get_text_from_element(self, parent_element, selector):
        """Obtiene el texto de un elemento hijo de forma segura."""
        try:
            return parent_element.find_element(By.CSS_SELECTOR, selector).text.strip()
        except NoSuchElementException:
            return 'N/A'

    def get_match_id_list(self, driver, league_season_url):
        """Obtiene la lista de todos los partidos y sus etapas desde la página de resultados."""
        logger.info(f"Obteniendo lista de partidos de: {league_season_url}")
        results_url = league_season_url.rstrip('/') + '/results'
        open_page_and_navigate(driver, results_url)

        show_more_selectors = ['a.event__more.event__more--static', 'a.wclButtonLink']
        for _ in range(config.MAX_SHOW_MORE_CLICKS):
            clicked = False
            for selector in show_more_selectors:
                try:
                    show_more_button = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    driver.execute_script("arguments[0].click();", show_more_button)
                    logger.debug(f"Click en 'Mostrar más partidos' con selector: {selector}")
                    add_human_delay(2, 4)
                    clicked = True
                    break
                except (TimeoutException, NoSuchElementException):
                    continue
            if not clicked:
                logger.info("No se encontró más botón 'Mostrar más partidos'.")
                break
        
        try:
            logger.info("Esperando a que la lista de partidos cargue...")
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.sportName.basketball')))
            logger.info("Contenedor de partidos de baloncesto está presente.")
        except TimeoutException:
            logger.error("La página no parece contener partidos de baloncesto o no cargó a tiempo.")
            return []

        matches_with_stage = []
        all_rows = driver.find_elements(By.CSS_SELECTOR, '.event__match, .event__title')
        current_stage = "N/A"
        for row in all_rows:
            if "event__title" in row.get_attribute("class"):
                try:
                    stage_element = row.find_element(By.CSS_SELECTOR, 'div.event__titleBox strong')
                    current_stage = stage_element.text.strip()
                    logger.info(f"Etapa encontrada: {current_stage}")
                except NoSuchElementException:
                    logger.debug("Fila de título encontrada, pero sin el selector de etapa esperado.")
            elif "event__match" in row.get_attribute("class"):
                match_id_attr = row.get_attribute('id')
                if match_id_attr:
                    clean_id = match_id_attr.split('_')[-1]
                    matches_with_stage.append({'id': clean_id, 'stage': current_stage})

        logger.info(f"Encontrados {len(matches_with_stage)} partidos con sus etapas.")
        return matches_with_stage

    def _extract_quarter_scores(self, driver):
        """Extrae los puntos de cada cuarto desde la página de resumen."""
        quarters = {}
        try:
            score_container = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".smh__template.basketball"))
            )
            for i in range(1, 6):  # 4 cuartos + posibles tiempos extras
                q_key = f"Q{i}" if i <= 4 else "OT"
                try:
                    home_element = score_container.find_element(
                        By.CSS_SELECTOR, f'.smh__home.smh__part--{i}'
                    )
                    away_element = score_container.find_element(
                        By.CSS_SELECTOR, f'.smh__away.smh__part--{i}'
                    )
                    home_score = home_element.text.strip()
                    away_score = away_element.text.strip()
                    
                    if home_score.isdigit() and away_score.isdigit():
                        quarters[q_key] = {
                            'home_score': home_score,
                            'away_score': away_score
                        }
                except NoSuchElementException:
                    break  # No hay más cuartos
        except Exception as e:
            logger.debug(f"No se pudo extraer el resultado por cuartos: {e}")
        return quarters

    def extract_match_data(self, driver):
        """Extrae los datos principales de la página de resumen del partido."""
        quarter_scores = self._extract_quarter_scores(driver)
        
        # Obtener los puntajes directamente de la página
        home_score = self._safe_get_text(driver, '.detailScore__wrapper .detailScore__home')
        away_score = self._safe_get_text(driver, '.detailScore__wrapper .detailScore__away')
        
        # Si no se encontraron puntajes directos, calcularlos sumando los cuartos
        if home_score == 'N/A' or away_score == 'N/A':
            home_total = 0
            away_total = 0
            for q in quarter_scores.values():
                try:
                    home_total += int(q['home_score'])
                    away_total += int(q['away_score'])
                except (ValueError, TypeError):
                    continue
            
            home_score = str(home_total) if home_total > 0 else 'N/A'
            away_score = str(away_total) if away_total > 0 else 'N/A'
        
        return {
            'date': self._safe_get_text(driver, '.duelParticipant__startTime'),
            'home_team': self._safe_get_text(driver, '.duelParticipant__home .participant__participantName'),
            'away_team': self._safe_get_text(driver, '.duelParticipant__away .participant__participantName'),
            'home_score': home_score,
            'away_score': away_score,
            'quarter_scores': quarter_scores
        }

    def extract_all_quarters_statistics(self, driver, match_id, home_team_name, away_team_name):
        """Recorre las pestañas de cada cuarto y extrae sus estadísticas."""
        all_stats = {}
        period_map = {'1st Quarter': 'Q1', '2nd Quarter': 'Q2', '3rd Quarter': 'Q3', '4th Quarter': 'Q4', 'Overtime': 'OT'}
        
        for i in range(1, 10): # Intenta hasta 9 períodos (4Q + 5OT)
            stats_url = f"{config.BASE_URL}/match/{match_id}/#/match-summary/match-statistics/{i}"
            open_page_and_navigate(driver, stats_url)
            
            if not wait_for_selector_safe(driver, "div[data-testid='wcl-statistics']", timeout=5):
                logger.info(f"No se encontraron estadísticas para el período {i}. Fin de la extracción.")
                break
            
            add_human_delay(1, 2)
            try:
                period_name_raw = driver.find_element(By.CSS_SELECTOR, "button.wcl-tabSelected_T--kd").text.strip()
                period_key = period_map.get(period_name_raw, period_name_raw)
                logger.info(f"Extrayendo estadísticas para: {period_name_raw} ({period_key})")
                
                home_stats, away_stats = {}, {}
                stat_elements = driver.find_elements(By.CSS_SELECTOR, "div[data-testid='wcl-statistics']")
                for element in stat_elements:
                    category = self._safe_get_text_from_element(element, "[data-testid='wcl-statistics-category']")
                    if category in config.PREDEFINED_STAT_CATEGORIES_ORDER:
                        stat_key = re.sub(r'[^a-z0-9_]', '', category.lower().replace(' ', '_'))
                        values = element.find_elements(By.CSS_SELECTOR, "[data-testid='wcl-statistics-value'] > strong")
                        home_stats[stat_key] = values[0].text.strip() if len(values) > 0 else 'N/A'
                        away_stats[stat_key] = values[1].text.strip() if len(values) > 1 else 'N/A'
                
                if home_stats and away_stats:
                    all_stats[period_key] = {home_team_name: home_stats, away_team_name: away_stats}
            except Exception as e:
                logger.error(f"Error extrayendo estadísticas para el período {i}: {e}")
                break
        return all_stats

    def get_match_data(self, driver, match_id, stage_name):
        """Orquesta la extracción de todos los datos para un solo partido."""
        logger.info(f"Procesando partido: {match_id} ({stage_name})")
        
        summary_url = f"{config.BASE_URL}/match/{match_id}/#/match-summary/match-summary"
        open_page_and_navigate(driver, summary_url)
        if not wait_for_selector_safe(driver, '.duelParticipant__startTime'):
            logger.warning(f"No se pudo cargar la página de resumen para {match_id}")
            return None
        
        match_info = self.extract_match_data(driver)
        statistics_by_quarter = self.extract_all_quarters_statistics(driver, match_id, match_info['home_team'], match_info['away_team'])
        
        return {
            "match_id": match_id,
            "stage": stage_name,
            **match_info,
            "quarter_stats": statistics_by_quarter,
            "scraped_at": datetime.now().isoformat()
        }

def export_to_json(data_list, filename):
    """Exporta la lista de datos a un archivo JSON."""
    filepath = os.path.join(config.OUTPUT_PATH, f"{filename}.json")
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, indent=4, ensure_ascii=False)
        logger.info(f"Datos exportados a: {filepath}")
        return True
    except IOError as e:
        logger.error(f"Error exportando a JSON: {e}")
        return False

def main():
    """Función principal que maneja los argumentos y el flujo del script."""
    parser = argparse.ArgumentParser(description='Scraper de Flashscore para Baloncesto (Versión Estable).')
    parser.add_argument('--url', required=True, help='URL de la liga de baloncesto de Flashscore (página de resultados).')
    parser.add_argument('--output', help='Nombre del archivo de salida (sin extensión). Si se omite, se genera uno.')
    parser.add_argument('--last', type=int, help='Número de los partidos más recientes a raspar.')
    parser.add_argument('--no-headless', action='store_true', help='Ejecutar el navegador en modo visible.')
    args = parser.parse_args()

    ensure_directory_exists(config.OUTPUT_PATH)
    base_league_name = get_base_league_name_from_url(args.url)
    output_filename = args.output or f"{base_league_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    final_filepath_json = os.path.join(config.OUTPUT_PATH, f"{output_filename}.json")

    try:
        with get_chrome_driver(headless=not args.no_headless) as driver:
            scraper = FlashscoreMatchScraper()
            all_matches_info = scraper.get_match_id_list(driver, args.url)
            
            matches_to_scrape_info = all_matches_info
            if args.last:
                matches_to_scrape_info = matches_to_scrape_info[:args.last]

            logger.info(f"Se rasparán {len(matches_to_scrape_info)} partidos.")
            
            scraped_data = []
            total_to_scrape = len(matches_to_scrape_info)
            start_time = time.time()
            
            for i, match_info in enumerate(matches_to_scrape_info):
                match_id, stage_name = match_info['id'], match_info['stage']
                eta_str = ""
                if i > 0:
                    elapsed = time.time() - start_time
                    avg_time_per_match = elapsed / i
                    remaining_matches = total_to_scrape - i
                    eta_seconds = int(remaining_matches * avg_time_per_match)
                    mins, secs = divmod(eta_seconds, 60)
                    eta_str = f" | ETA: {mins:02d}m {secs:02d}s"

                print_progress_bar(i + 1, total_to_scrape, prefix='Progreso:', suffix=f'Partido {match_id}{eta_str}')
                
                match_data = scraper.get_match_data(driver, match_id, stage_name)
                if match_data:
                    scraped_data.append(match_data)
            
            if total_to_scrape > 0:
                print_progress_bar(total_to_scrape, total_to_scrape, prefix='Progreso:', suffix='Completado')

            if scraped_data:
                if os.path.exists(final_filepath_json):
                    create_data_backup(final_filepath_json, base_league_name)
                export_to_json(scraped_data, output_filename)
            else:
                logger.info("No se rasparon nuevos datos.")

        logger.info("=== Proceso completado exitosamente ===")

    except Exception as e:
        logger.error(f"Ocurrió un error inesperado: {e}", exc_info=True)

if __name__ == "__main__":
    main()