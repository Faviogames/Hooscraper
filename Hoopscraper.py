import re
import time
import json
import logging
import random
import argparse
import os
import sys
import shutil
import platform
import subprocess
from contextlib import contextmanager
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

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
    if not os.path.exists(path):
        os.makedirs(path)
        logger.info(f"Directorio creado: {path}")

def get_base_league_name_from_url(league_url):
    # Normalizar URL eliminando /results/ si existe
    clean_url = league_url.rstrip('/').split('?')[0]
    if clean_url.endswith('/results'):
        clean_url = clean_url[:-8]  # Remover '/results'
    
    parts = clean_url.split('/')
    if len(parts) >= 3:
        return f"{parts[-2]}_{parts[-1]}".replace('-', '_')
    elif len(parts) >= 1 and parts[-1]:
        return parts[-1].replace('-', '_')
    return "flashscore_data"

def normalize_league_url(league_url):
    """Normaliza la URL para asegurar que termine en /results/"""
    clean_url = league_url.rstrip('/')
    if not clean_url.endswith('/results'):
        clean_url += '/results'
    return clean_url

def calculate_total_score_from_quarters(quarter_scores):
    """Calcula el puntaje total sumando los cuartos."""
    home_total = 0
    away_total = 0
    
    for quarter, scores in quarter_scores.items():
        if isinstance(scores, dict):
            home_score = scores.get('home_score', '0')
            away_score = scores.get('away_score', '0')
            
            # Convertir a entero, manejar casos de 'N/A' o strings vacíos
            try:
                home_total += int(home_score) if home_score and home_score != 'N/A' else 0
                away_total += int(away_score) if away_score and away_score != 'N/A' else 0
            except (ValueError, TypeError):
                continue
    
    return str(home_total), str(away_total)

def create_data_backup(filepath_to_backup, league_name):
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
    percent = ("{0:.1f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = fill * filled_length + '-' * (length - filled_length)
    sys.stdout.write(f'\r{prefix} |{bar}| {percent}% {suffix}')
    sys.stdout.flush()
    if iteration == total:
        sys.stdout.write('\n')
        sys.stdout.flush()

def load_existing_match_ids(filepath):
    """Carga los IDs de partidos ya procesados para evitar duplicados."""
    existing_ids = set()
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    for match in data:
                        if isinstance(match, dict) and 'match_id' in match:
                            existing_ids.add(match['match_id'])
                logger.info(f"Cargados {len(existing_ids)} partidos existentes desde {filepath}")
        except Exception as e:
            logger.error(f"Error cargando partidos existentes: {e}")
    return existing_ids

def _parse_match_datetime(match):
    """
    Intenta parsear 'date' con formato 'dd.mm.yyyy HH:MM'.
    Fallback: 'scraped_at' (yyyy-mm-dd).
    Si no se puede, retorna datetime.min para que quede al final en orden desc.
    """
    dt = None
    date_str = (match or {}).get('date') or ''
    if isinstance(date_str, str):
        for fmt in ["%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d"]:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                break
            except Exception:
                pass
    if dt is None:
        sa = (match or {}).get('scraped_at') or ''
        if isinstance(sa, str):
            for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M"]:
                try:
                    dt = datetime.strptime(sa.strip(), fmt)
                    break
                except Exception:
                    pass
    return dt or datetime.min

def _sort_matches(data, order='desc'):
    rev = (order == 'desc')
    return sorted(data, key=_parse_match_datetime, reverse=rev)

def reorder_json_file(filepath, order='desc'):
    """
    Reordena el JSON de partidos por fecha (más recientes primero si 'desc').
    No lanza excepción si el archivo no existe o está vacío.
    """
    try:
        if not os.path.exists(filepath):
            return False
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, list):
            return False
        data_sorted = _sort_matches(data, order=order)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_sorted, f, ensure_ascii=False, indent=2)
        logger.info(f"Archivo reordenado: {filepath} ({'desc' if order=='desc' else 'asc'})")
        return True
    except Exception as e:
        logger.error(f"Error reordenando {filepath}: {e}")
        return False

def save_match_incremental(match_data, filepath, insert_at_beginning=False, ensure_desc_order=False):
    """Guarda un partido individual de forma incremental, con opciones de orden."""
    try:
        # Cargar datos existentes
        existing_data = []
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                try:
                    existing_data = json.load(f)
                except json.JSONDecodeError:
                    existing_data = []

        # Añadir nuevo partido
        if not isinstance(existing_data, list):
            existing_data = []
        if insert_at_beginning:
            existing_data.insert(0, match_data)
        else:
            existing_data.append(match_data)

        # Aplicar orden si se solicita
        if ensure_desc_order:
            existing_data = _sort_matches(existing_data, order='desc')

        # Guardar datos actualizados
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(existing_data, f, ensure_ascii=False, indent=2)

        logger.debug(f"Partido {match_data.get('match_id', 'N/A')} guardado incrementalmente")
        return True
    except Exception as e:
        logger.error(f"Error guardando partido incrementalmente: {e}")
        return False

def interactive_batch_pause(processed_count, remaining_count, batch_size=250):
    """Pausa interactiva cada cierto número de partidos para evitar bloqueos."""
    print(f"\n{'='*60}")
    print(f"⏸️  PAUSA AUTOMÁTICA PARA EVITAR BLOQUEOS")
    print(f"{'='*60}")
    print(f"📊 Partidos procesados en este lote: {processed_count}")
    print(f"🔄 Partidos restantes: {remaining_count}")
    print(f"⚠️  Flashscore puede bloquear después de muchos partidos")
    print(f"💡 Recomendación: Cambiar IP/VPN si hay problemas")
    print(f"{'='*60}")
    print()
    print("OPCIONES:")
    print("1. Continuar inmediatamente")
    print("2. Continuar (recomendado si cambias IP/VPN)")
    print("3. Salir (usar modo --update después)")
    print()
    
    while True:
        choice = input("Selecciona opción (1, 2 o 3): ").strip()
        
        if choice == "1":
            logger.info("Continuando inmediatamente...")
            return True
        elif choice == "2":
            print("\n⏳ Esperando 60 segundos para espaciar las solicitudes...")
            time.sleep(60)
            logger.info("Continuando después de pausa...")
            return True
        elif choice == "3":
            print("\n🛑 Scraping pausado por el usuario.")
            print("💡 Para continuar después, usa: python Hoopscraper.py URL --update")
            return False
        else:
            print("❌ Por favor selecciona 1, 2 o 3")

def shutdown_computer():
    """Apaga la computadora según el sistema operativo."""
    try:
        system = platform.system()
        logger.info("Iniciando apagado del sistema...")
        
        if system == "Windows":
            subprocess.run(["shutdown", "/s", "/t", "60", "/c", "Scraping completado. Apagando en 60 segundos..."], check=True)
            logger.info("Comando de apagado enviado (Windows). El sistema se apagará en 60 segundos.")
        elif system == "Linux" or system == "Darwin":  # Darwin es macOS
            subprocess.run(["sudo", "shutdown", "-h", "+1", "Scraping completado"], check=True)
            logger.info("Comando de apagado enviado (Linux/Mac). El sistema se apagará en 1 minuto.")
        else:
            logger.warning(f"Sistema operativo {system} no soportado para apagado automático.")
            
    except subprocess.CalledProcessError as e:
        logger.error(f"Error ejecutando comando de apagado: {e}")
    except Exception as e:
        logger.error(f"Error inesperado durante apagado: {e}")

@contextmanager
def get_chrome_driver_with_retry(headless=True, max_attempts=3):
    """Context manager que reinicia el driver automáticamente en caso de fallo."""
    driver = None
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        try:
            logger.info(f"Iniciando driver de Chrome (intento {attempt}/{max_attempts})")

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

            # Configuración de imágenes basada en config
            prefs = {}
            if hasattr(config, 'DISABLE_IMAGES') and config.DISABLE_IMAGES:
                prefs["profile.managed_default_content_settings.images"] = 2
                logger.debug("Carga de imágenes desactivada para acelerar navegación")

            if prefs:
                options.add_experimental_option("prefs", prefs)

            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            logger.info("Driver de Chrome iniciado exitosamente")
            break

        except Exception as e:
            logger.error(f"Error al crear el driver de Chrome (intento {attempt}): {e}")
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                driver = None

            if attempt >= max_attempts:
                logger.error("Se agotaron los intentos para crear el driver de Chrome")
                raise
            else:
                logger.info(f"Esperando {config.RECONNECTION_DELAY if hasattr(config, 'RECONNECTION_DELAY') else 30} segundos antes del siguiente intento...")
                time.sleep(config.RECONNECTION_DELAY if hasattr(config, 'RECONNECTION_DELAY') else 30)

    try:
        yield driver
    finally:
        if driver:
            try:
                driver.quit()
                logger.debug("Driver cerrado correctamente")
            except:
                pass

def add_human_delay(min_delay=1, max_delay=3):
    time.sleep(random.uniform(min_delay, max_delay))

def open_page_and_navigate(driver, url, timeout=30):
    logger.debug(f"Navegando a: {url}")
    driver.set_page_load_timeout(timeout)
    driver.get(url)
    add_human_delay(0.5, 1.5)

def wait_for_selector_safe(driver, selector, timeout=config.TIMEOUT_FAST):
    try:
        WebDriverWait(driver, timeout / 1000).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        return True
    except TimeoutException:
        return False

class FlashscoreMatchScraper:
    def _safe_get_text(self, driver, selector):
        try:
            return driver.find_element(By.CSS_SELECTOR, selector).text.strip()
        except NoSuchElementException:
            return 'N/A'
            
    def _safe_get_text_from_element(self, parent_element, selector):
        try:
            return parent_element.find_element(By.CSS_SELECTOR, selector).text.strip()
        except NoSuchElementException:
            return 'N/A'

    def get_match_id_list(self, driver, league_season_url):
        # Normalizar URL para asegurar que termine en /results/
        normalized_url = normalize_league_url(league_season_url)
        logger.info(f"Obteniendo lista de partidos de: {normalized_url}")
        open_page_and_navigate(driver, normalized_url)

        # 1) Detectar base de liga y posible contexto de playoff en Results
        league_base = None
        playoffs_context_text = None  # p.ej. "EuroBasket - Play Offs" / "NBA - Playoffs" / "NCAA - March Madness"
        try:
            nodes = driver.find_elements(By.CSS_SELECTOR, "strong[data-testid='wcl-scores-simple-text-01']")
            header_txt = nodes[0].text.strip() if nodes else ""
            if header_txt:
                # Si viene con prefijo regional: "EUROPE: EuroBasket - Play Offs"
                if ":" in header_txt:
                    header_txt = header_txt.split(":", 1)[1].strip()
                if " - " in header_txt:
                    base, suffix = header_txt.split(" - ", 1)
                    league_base = base.strip()
                    suf_low = suffix.lower().strip()
                    if any(k in suf_low for k in ["play off", "play-off", "playoffs", "march madness", "postseason", "post season"]):
                        playoffs_context_text = f"{league_base} - {suffix.strip()}"
                else:
                    league_base = header_txt
            if not league_base:
                try:
                    league_base = driver.find_element(By.CSS_SELECTOR, "div.heading__name").text.strip()
                except NoSuchElementException:
                    league_base = None
        except Exception as e:
            logger.debug(f"No se pudo leer encabezado de liga: {e}")

        if not league_base:
            try:
                parts = normalized_url.rstrip("/").split("/")
                league_base = parts[-2].replace("-", " ").title() if len(parts) >= 2 else "Basketball"
            except Exception:
                league_base = "Basketball"

        # Botón "mostrar más partidos"
        show_more_selectors = ['a.event__more.event__more--static', 'a.wclButtonLink']
        for _ in range(config.MAX_SHOW_MORE_CLICKS):
            clicked = False
            for selector in show_more_selectors:
                try:
                    btn = WebDriverWait(driver, 2).until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    driver.execute_script("arguments[0].click();", btn)
                    add_human_delay(2, 4)
                    clicked = True
                    break
                except (TimeoutException, NoSuchElementException):
                    continue
            if not clicked:
                break

        try:
            WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, '.sportName.basketball')))
        except TimeoutException:
            logger.error("La página no cargó a tiempo o no contiene partidos de baloncesto.")
            return []

        # Utilidad local para formar stage final siguiendo tus prioridades
        def _compose_stage(league_base_name, row_stage_text, playoffs_text):
            def _is_specific(text):
                if not text:
                    return False
                t = text.lower()
                # Normalizaciones típicas
                t = t.replace('semi finals', 'semi-finals').replace('quarter finals', 'quarter-finals')
                keys = ['final', 'semi', 'quarter', 'round', 'group', 'phase', 'stage', 'place']
                return any(k in t for k in keys) and len(text) < 80
            if _is_specific(row_stage_text):
                return f"{league_base_name} - {row_stage_text.strip()}"
            if playoffs_text:
                return playoffs_text
            return league_base_name

        matches_with_stage = []

        # CRÍTICO: incluir .event__round como "título de bloque" además de .event__title
        all_rows = driver.find_elements(By.CSS_SELECTOR, '.event__match, .event__title, .event__round.event__round--static, .event__round')

        current_block_stage = "N/A"
        for row in all_rows:
            classes = (row.get_attribute("class") or "")

            # 1) Ronda específica por bloque (nuevo diseño)
            if "event__round" in classes:
                try:
                    current_block_stage = row.text.strip()
                except Exception:
                    current_block_stage = "N/A"
                continue

            # 2) Compatibilidad con títulos antiguos por bloque
            if "event__title" in classes:
                try:
                    current_block_stage = row.find_element(By.CSS_SELECTOR, 'div.event__titleBox strong').text.strip()
                except NoSuchElementException:
                    current_block_stage = "N/A"
                continue

            # 3) Fila de partido
            if "event__match" in classes:
                match_id_attr = row.get_attribute('id')
                if not match_id_attr:
                    continue
                clean_id = match_id_attr.split('_')[-1]

                # Stage por fila (si lo hubiera dentro de la fila)
                row_stage_text = None
                try:
                    try:
                        row_stage_text = row.find_element(By.CSS_SELECTOR, "div.event__round.event__round--static").text.strip()
                    except NoSuchElementException:
                        pass
                    if not row_stage_text:
                        cand = row.find_elements(By.CSS_SELECTOR, "div[class*='event__round']")
                        if cand:
                            txt = cand[0].text.strip()
                            row_stage_text = txt if txt else None
                except Exception:
                    pass

                # Fallback: usar el stage del bloque actual
                if not row_stage_text and current_block_stage != "N/A":
                    row_stage_text = current_block_stage

                final_stage = _compose_stage(league_base, row_stage_text, playoffs_context_text)
                matches_with_stage.append({'id': clean_id, 'stage': final_stage})

        logger.info(f"Encontrados {len(matches_with_stage)} partidos con sus etapas compuestas.")
        return matches_with_stage

    def extract_match_data(self, driver):
        quarter_scores = self._extract_quarter_scores(driver)

        # Calculate total scores from quarters
        home_score, away_score = calculate_total_score_from_quarters(quarter_scores)

        # Extract stage/league information from the header
        stage = self._extract_stage_from_header(driver)

        return {
            'match_id': '', # Will be assigned later
            'stage': stage, # Now extracted from header
            'date': self._safe_get_text(driver, '.duelParticipant__startTime'),
            'scraped_at': datetime.now().strftime('%Y-%m-%d'),
            'home_team': self._safe_get_text(driver, '.duelParticipant__home .participant__participantName'),
            'away_team': self._safe_get_text(driver, '.duelParticipant__away .participant__participantName'),
            'home_score': home_score,
            'away_score': away_score,
            'quarter_scores': quarter_scores,
            'match_stats': {} # Will be assigned later
        }

    def _extract_stage_from_header(self, driver):
        """
        Prioridades:
        1) Liga + Stage específico (event__round en match o bloque)
        2) Liga con contexto playoff desde strong[data-testid='wcl-scores-simple-text-01']
        3) Liga limpia
        Fallback final: heading__name o URL.
        """
        try:
            league_base = None
            playoffs_context_text = None

            try:
                nodes = driver.find_elements(By.CSS_SELECTOR, "strong[data-testid='wcl-scores-simple-text-01']")
                header_txt = nodes[0].text.strip() if nodes else ""
                if header_txt:
                    if ":" in header_txt:
                        header_txt = header_txt.split(":", 1)[1].strip()
                    if " - " in header_txt:
                        base, suffix = header_txt.split(" - ", 1)
                        league_base = base.strip()
                        suf_low = suffix.lower().strip()
                        if any(k in suf_low for k in ["play off", "play-off", "playoffs", "march madness", "postseason", "post season"]):
                            playoffs_context_text = f"{league_base} - {suffix.strip()}"
                    else:
                        league_base = header_txt
            except Exception:
                pass

            if not league_base:
                try:
                    league_base = driver.find_element(By.CSS_SELECTOR, "div.heading__name").text.strip()
                except NoSuchElementException:
                    league_base = None
            if not league_base:
                try:
                    current_url = driver.current_url
                    parts = current_url.rstrip("/").split("/")
                    league_base = parts[-2].replace("-", " ").title() if len(parts) >= 2 else "Basketball"
                except Exception:
                    league_base = "Basketball"

            # Stage específico
            row_stage_text = None
            try:
                # En la vista de match o si quedó visible el bloque
                try:
                    row_stage_text = driver.find_element(By.CSS_SELECTOR, "div.event__round.event__round--static").text.strip()
                except NoSuchElementException:
                    pass
                if not row_stage_text:
                    cands = driver.find_elements(By.CSS_SELECTOR, "div[class*='event__round'], .stage-info, .round-info, [class*='stage'], [class*='phase']")
                    for el in cands:
                        txt = el.text.strip()
                        if txt:
                            row_stage_text = txt
                            break
                if not row_stage_text:
                    try:
                        row_stage_text = driver.find_element(By.CSS_SELECTOR, "div.event__titleBox strong").text.strip()
                    except NoSuchElementException:
                        pass
            except Exception:
                pass

            def _is_specific(text):
                if not text:
                    return False
                t = text.lower()
                t = t.replace('semi finals', 'semi-finals').replace('quarter finals', 'quarter-finals')
                keys = ['final', 'semi', 'quarter', 'round', 'group', 'phase', 'stage', 'place']
                return any(k in t for k in keys) and len(text) < 80

            if _is_specific(row_stage_text):
                return f"{league_base} - {row_stage_text}"
            if playoffs_context_text:
                return playoffs_context_text
            return league_base

        except Exception as e:
            logger.error(f"Error en extracción de stage: {e}")
            return "Unknown Competition"
    def _extract_quarter_scores(self, driver):
        quarters = {}
        try:
            score_container = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".smh__template.basketball")))
            for i in range(1, 6):
                q_key = f"Q{i}" if i <= 4 else "OT"
                try:
                    home_score = score_container.find_element(By.CSS_SELECTOR, f'.smh__home.smh__part--{i}').text.strip()
                    away_score = score_container.find_element(By.CSS_SELECTOR, f'.smh__away.smh__part--{i}').text.strip()
                    if home_score and away_score:
                        quarters[q_key] = {'home_score': home_score, 'away_score': away_score}
                except NoSuchElementException:
                    break
        except Exception as e:
            logger.debug(f"No se pudo extraer el resultado por cuartos: {e}")
        return quarters

    def extract_all_quarters_statistics(self, driver, match_id, home_team_name, away_team_name):
        """Extrae estadísticas generales del partido (no por cuartos específicos)."""
        try:
            # Navigate to the match page first
            match_url = f"{config.BASE_URL}/match/{match_id}/"
            open_page_and_navigate(driver, match_url)

            # Look for the STATS tab (NOT PLAYER STATS)
            stats_tab_clicked = False
            try:
                # Wait for the page to load completely
                time.sleep(3)

                # Method 1: Try to find STATS tab by text content
                logger.debug("Looking for STATS tab...")
                all_elements = driver.find_elements(By.XPATH, "//*[text()='STATS' or text()='Stats']")

                for element in all_elements:
                    element_text = element.text.strip()
                    tag_name = element.tag_name.lower()

                    # Make sure it's EXACTLY "STATS" and not "PLAYER STATS"
                    if element_text == "STATS" or element_text == "Stats":
                        logger.debug(f"Found STATS tab: {element_text} ({tag_name})")
                        try:
                            # Scroll into view and click
                            driver.execute_script("arguments[0].scrollIntoView(true);", element)
                            time.sleep(1)
                            driver.execute_script("arguments[0].click();", element)
                            logger.debug("Clicked on STATS tab")
                            time.sleep(3)  # Wait for content to load
                            stats_tab_clicked = True
                            break
                        except Exception as e:
                            logger.debug(f"Error clicking STATS tab: {e}")
                            continue

                # Method 2: If Method 1 fails, try wcl-tab approach
                if not stats_tab_clicked:
                    logger.debug("Method 1 failed, trying wcl-tab approach...")
                    wcl_tabs = driver.find_elements(By.CSS_SELECTOR, 'button[data-testid="wcl-tab"]')
                    for tab in wcl_tabs:
                        tab_text = tab.text.strip()
                        if tab_text == "STATS" or tab_text == "Stats":
                            logger.debug(f"Found wcl-tab STATS: {tab_text}")
                            driver.execute_script("arguments[0].click();", tab)
                            time.sleep(3)
                            stats_tab_clicked = True
                            break

                if not stats_tab_clicked:
                    logger.warning(f"Could not find or click STATS tab for match {match_id}")
                    return {}

            except Exception as e:
                logger.error(f"Error finding/clicking STATS tab for match {match_id}: {e}")
                return {}

            # Wait for statistics content to load
            logger.debug("Waiting for statistics content to load...")
            time.sleep(2)

            # Now look for statistics using multiple methods
            home_stats = {}
            away_stats = {}

            # Method 1: Try wcl-statistics (your original approach)
            stat_elements = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="wcl-statistics"]')
            logger.debug(f"Found {len(stat_elements)} wcl-statistics elements")

            if len(stat_elements) > 0:
                logger.debug("Using wcl-statistics approach...")
                for element in stat_elements:
                    try:
                        # Get the category name
                        category_element = element.find_element(By.CSS_SELECTOR, 'div[data-testid="wcl-statistics-category"] strong')
                        category = category_element.text.strip()

                        if category in config.PREDEFINED_STAT_CATEGORIES_ORDER:
                            # Convert category name to key format
                            stat_key = re.sub(r'[^a-z0-9_]', '', category.lower().replace(' ', '_').replace('.', '').replace('-', '_'))

                            # Get values from both teams
                            value_elements = element.find_elements(By.CSS_SELECTOR, 'div[data-testid="wcl-statistics-value"] strong')
                            if len(value_elements) >= 2:
                                home_value = value_elements[0].text.strip()
                                away_value = value_elements[1].text.strip()

                                home_stats[stat_key] = home_value
                                away_stats[stat_key] = away_value

                                logger.debug(f"Extracted stat: {category} - Home: {home_value}, Away: {away_value}")
                    except Exception as e:
                        logger.debug(f"Error extracting wcl-statistics element: {e}")
                        continue

            # Return results
            match_stats = {}
            if home_team_name != 'N/A':
                match_stats[home_team_name] = home_stats
            if away_team_name != 'N/A':
                match_stats[away_team_name] = away_stats

            logger.info(f"Successfully extracted {len(home_stats)} stats categories for match {match_id}")

            if len(home_stats) == 0:
                logger.warning(f"No statistics extracted for match {match_id}. This might indicate the stats are not available.")

            return match_stats
            
        except Exception as e:
            logger.error(f"Error extracting statistics for match {match_id}: {e}")
            return {}

    def extract_team_stats_by_quarter(self, driver, match_id, home_team_name, away_team_name, quarter_scores):
        """
        Extrae estadísticas detalladas por cuarto para cada equipo.
        Navega por cada pestaña de cuarto (Q1-Q4) y extrae las estadísticas.
        """
        try:
            # Navigate to the match page first
            match_url = f"{config.BASE_URL}/match/{match_id}/"
            open_page_and_navigate(driver, match_url)
            time.sleep(2)

            # Look for the STATS tab first
            stats_tab_clicked = False
            try:
                # Method 1: Try to find STATS tab by text content
                logger.debug("Looking for STATS tab for quarter stats...")
                all_elements = driver.find_elements(By.XPATH, "//*[text()='STATS' or text()='Stats']")

                for element in all_elements:
                    element_text = element.text.strip()
                    tag_name = element.tag_name.lower()

                    # Make sure it's EXACTLY "STATS" and not "PLAYER STATS"
                    if element_text == "STATS" or element_text == "Stats":
                        logger.debug(f"Found STATS tab: {element_text} ({tag_name})")
                        try:
                            # Scroll into view and click
                            driver.execute_script("arguments[0].scrollIntoView(true);", element)
                            time.sleep(1)
                            driver.execute_script("arguments[0].click();", element)
                            logger.debug("Clicked on STATS tab")
                            time.sleep(3)  # Wait for content to load
                            stats_tab_clicked = True
                            break
                        except Exception as e:
                            logger.debug(f"Error clicking STATS tab: {e}")
                            continue

                # Method 2: If Method 1 fails, try wcl-tab approach
                if not stats_tab_clicked:
                    logger.debug("Method 1 failed, trying wcl-tab approach for quarter stats...")
                    wcl_tabs = driver.find_elements(By.CSS_SELECTOR, 'button[data-testid="wcl-tab"]')
                    for tab in wcl_tabs:
                        tab_text = tab.text.strip()
                        if tab_text == "STATS" or tab_text == "Stats":
                            logger.debug(f"Found wcl-tab STATS: {tab_text}")
                            driver.execute_script("arguments[0].click();", tab)
                            time.sleep(3)
                            stats_tab_clicked = True
                            break

                if not stats_tab_clicked:
                    logger.warning(f"Could not find or click STATS tab for match {match_id}")
                    return {}

            except Exception as e:
                logger.error(f"Error finding/clicking STATS tab for match {match_id}: {e}")
                return {}

            # Wait for statistics content to load
            logger.debug("Waiting for statistics content to load for quarter stats...")
            time.sleep(2)

            # Initialize quarter stats structure
            quarter_stats = {}
            
            # Define the quarters to process (using the correct names from diagnostic)
            quarters = ["1ST QUARTER", "2ND QUARTER", "3RD QUARTER", "4TH QUARTER"]
            quarter_short_names = ["Q1", "Q2", "Q3", "Q4"]
            
            # Get all tab buttons once to avoid repeated queries
            tab_buttons = driver.find_elements(By.CSS_SELECTOR, "button[data-testid='wcl-tab']")
            logger.debug(f"Found {len(tab_buttons)} tab buttons")
            
            # Process each quarter
            for i, quarter in enumerate(quarters):
                logger.debug(f"Processing {quarter} statistics...")
                
                try:
                    # Click on the quarter tab using the working approach from debug_quarter_tabs.py
                    quarter_tab_clicked = False
                    
                    # Find the button that corresponds to this quarter
                    for button in tab_buttons:
                        try:
                            button_text = button.text.strip()
                            if button_text == quarter:
                                logger.debug(f"Found {quarter} button")
                                
                                # Check if already selected
                                class_name = button.get_attribute("class") or ""
                                if "wcl-tabSelected" in class_name:
                                    logger.debug(f"{quarter} tab already selected")
                                    quarter_tab_clicked = True
                                else:
                                    # Click on button
                                    driver.execute_script("arguments[0].scrollIntoView(true);", button)
                                    time.sleep(1)
                                    driver.execute_script("arguments[0].click();", button)
                                    logger.debug(f"Successfully clicked on {quarter} tab")
                                    time.sleep(2)  # Wait for content to load
                                    quarter_tab_clicked = True
                                
                                break
                        except Exception as e:
                            logger.debug(f"Error processing {quarter} button: {e}")
                            continue
                    
                    if not quarter_tab_clicked:
                        logger.warning(f"Could not find or click {quarter} tab for match {match_id}")
                        continue
                    
                    # Wait for quarter content to load
                    time.sleep(2)
                    
                    # Extract statistics for this quarter
                    quarter_data = {}
                    
                    # Try to find statistics elements for this quarter
                    stat_elements = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="wcl-statistics"]')
                    logger.debug(f"Found {len(stat_elements)} wcl-statistics elements for {quarter}")
                    
                    if len(stat_elements) > 0:
                        home_stats = {}
                        away_stats = {}
                        
                        for element in stat_elements:
                            try:
                                # Get the category name
                                category_element = element.find_element(By.CSS_SELECTOR, 'div[data-testid="wcl-statistics-category"] strong')
                                category = category_element.text.strip()
                                
                                # Check if this category is in our predefined list
                                if category in config.PREDEFINED_STAT_CATEGORIES_ORDER:
                                    # Convert category name to key format
                                    stat_key = re.sub(r'[^a-z0-9_]', '', category.lower().replace(' ', '_').replace('.', '').replace('-', '_'))
                                    
                                    # Get values from both teams
                                    value_elements = element.find_elements(By.CSS_SELECTOR, 'div[data-testid="wcl-statistics-value"] strong')
                                    if len(value_elements) >= 2:
                                        home_value = value_elements[0].text.strip()
                                        away_value = value_elements[1].text.strip()
                                        
                                        home_stats[stat_key] = home_value
                                        away_stats[stat_key] = away_value
                                        
                                        logger.debug(f"Extracted {quarter} stat: {category} - Home: {home_value}, Away: {away_value}")
                            except Exception as e:
                                logger.debug(f"Error extracting wcl-statistics element for {quarter}: {e}")
                                continue
                        
                        # Add team names to quarter data
                        if home_team_name != 'N/A' and home_stats:
                            quarter_data[home_team_name] = home_stats
                        if away_team_name != 'N/A' and away_stats:
                            quarter_data[away_team_name] = away_stats
                    
                    # Add quarter data to main structure using short name
                    if quarter_data:
                        quarter_stats[quarter_short_names[i]] = quarter_data
                        logger.info(f"Successfully extracted {len(home_stats)} stat categories for {quarter}")
                    else:
                        logger.warning(f"No statistics extracted for {quarter} in match {match_id}")
                        
                except Exception as e:
                    logger.error(f"Error processing {quarter} for match {match_id}: {e}")
                    continue
            
            return quarter_stats
            
        except Exception as e:
            logger.error(f"Error extracting team stats by quarter for match {match_id}: {e}")
            return {}
    
    def _handle_popups_and_banners(self, driver):
        """Handle common popups, cookie banners, and overlays that might interfere with scraping."""
        try:
            # List of common popup/banner selectors to dismiss
            popup_selectors = [
                # Cookie consent buttons
                "button[id*='cookie']",
                "button[class*='cookie']",
                "button[aria-label*='cookie']",
                "button[aria-label*='Cookie']",
                "div[id*='cookie'] button",
                "div[class*='cookie'] button",
                "div[id*='consent'] button",
                "div[class*='consent'] button",
                
                # General popup close buttons
                "button[aria-label*='close']",
                "button[aria-label*='Close']",
                "button[aria-label*='Accept']",
                "button[aria-label*='accept']",
                "button[class*='close']",
                "button[class*='Close']",
                "button[id*='close']",
                "div[class*='modal'] button",
                "div[class*='popup'] button",
                "div[class*='overlay'] button",
                ".close-button",
                ".modal-close",
                ".popup-close",
                
                # Specific Flashscore elements
                "button[data-testid='cookie-button-accept']",
                "button[data-testid='cookie-button-reject']",
                "div[id*='gdpr'] button",
                "div[class*='gdpr'] button"
            ]
            
            # Try to find and click each type of popup/button
            for selector in popup_selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        try:
                            # Check if element is visible
                            if element.is_displayed() and element.is_enabled():
                                element_text = element.text.strip().lower()
                                # Only click if it's a consent/accept/close button
                                if any(keyword in element_text for keyword in ['accept', 'agree', 'close', 'continue', 'ok', 'yes']):
                                    logger.debug(f"Clicking popup button: {element_text}")
                                    driver.execute_script("arguments[0].click();", element)
                                    time.sleep(1)
                        except Exception:
                            # Try JavaScript click if normal click fails
                            try:
                                driver.execute_script("arguments[0].click();", element)
                                time.sleep(1)
                            except Exception:
                                continue
                except Exception:
                    continue
                    
            # Additional check for overlays that might need to be dismissed
            try:
                # Look for overlay elements and try to remove them
                overlay_selectors = [
                    "div[class*='overlay']",
                    "div[class*='modal']",
                    "div[class*='popup']",
                    "div[id*='overlay']",
                    "div[id*='modal']",
                    "div[id*='popup']"
                ]
                
                for selector in overlay_selectors:
                    try:
                        overlays = driver.find_elements(By.CSS_SELECTOR, selector)
                        for overlay in overlays:
                            try:
                                # Only remove if it's covering the page
                                if overlay.is_displayed():
                                    style = overlay.value_of_css_property("position")
                                    z_index = overlay.value_of_css_property("z-index")
                                    if style in ["fixed", "absolute"] and (z_index and int(z_index) > 100):
                                        logger.debug(f"Removing overlay with z-index: {z_index}")
                                        driver.execute_script("arguments[0].remove();", overlay)
                                        time.sleep(0.5)
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception:
                pass
                
        except Exception as e:
            logger.debug(f"Error handling popups and banners: {e}")

    def scrape_match_with_error_handling(self, driver, match_info, output_filepath, attempt=1):
        """Scrape un partido individual con manejo de errores y reconexión."""
        match_id = match_info['id']
        stage = match_info['stage']
        max_attempts = config.MAX_RECONNECTION_ATTEMPTS if hasattr(config, 'MAX_RECONNECTION_ATTEMPTS') else 3
        
        try:
            logger.info(f"Procesando partido ID: {match_id} (Etapa: {stage}) - Intento {attempt}")
            
            # Navegar a la página del partido
            match_url = f"{config.BASE_URL}/match/{match_id}/"
            open_page_and_navigate(driver, match_url)
            
            # Extraer datos básicos del partido
            match_data = self.extract_match_data(driver)
            
            # Asignar match_id y stage en el orden correcto
            match_data['match_id'] = match_id
            match_data['stage'] = stage
            
            # Extraer estadísticas detalladas
            match_stats = {}
            quarter_stats = {}
            
            # Extraer estadísticas por cuarto si está habilitado en la configuración
            if hasattr(config, 'ENABLE_QUARTER_STATS') and config.ENABLE_QUARTER_STATS:
                try:
                    logger.info(f"Extrayendo estadísticas por cuarto para partido {match_id}...")
                    quarter_stats = self.extract_team_stats_by_quarter(
                        driver, match_id,
                        match_data['home_team'],
                        match_data['away_team'],
                        match_data['quarter_scores']
                    )
                    match_data['quarter_stats'] = quarter_stats
                    if quarter_stats:
                        logger.info(f"✓ Estadísticas por cuarto extraídas para partido {match_id}")
                    else:
                        logger.warning(f"No se pudieron extraer estadísticas por cuarto para partido {match_id}")
                except Exception as e:
                    logger.warning(f"Error extrayendo estadísticas por cuarto para partido {match_id}: {e}")
                    match_data['quarter_stats'] = {}
            
            # Extraer estadísticas generales del partido (solo si no está habilitado REMOVE_TOTAL_MATCH_STATS)
            if not (hasattr(config, 'REMOVE_TOTAL_MATCH_STATS') and config.REMOVE_TOTAL_MATCH_STATS):
                try:
                    match_stats = self.extract_all_quarters_statistics(
                        driver, match_id,
                        match_data['home_team'],
                        match_data['away_team']
                    )
                    match_data['match_stats'] = match_stats
                except Exception as e:
                    logger.warning(f"Error extrayendo estadísticas para partido {match_id}: {e}")
                    match_data['match_stats'] = {}
            else:
                # Si REMOVE_TOTAL_MATCH_STATS está habilitado, no guardamos match_stats
                match_data['match_stats'] = {}
            
            # Guardar partido incrementalmente
            if save_match_incremental(match_data, output_filepath):
                logger.info(f"✓ Partido {match_id} procesado y guardado exitosamente")
                return True
            else:
                logger.error(f"✗ Error guardando partido {match_id}")
                return False
                
        except WebDriverException as e:
            logger.error(f"Error de WebDriver en partido {match_id} (intento {attempt}): {e}")
            if attempt < max_attempts:
                logger.info(f"Reintentando partido {match_id} en {config.RECONNECTION_DELAY if hasattr(config, 'RECONNECTION_DELAY') else 30} segundos...")
                time.sleep(config.RECONNECTION_DELAY if hasattr(config, 'RECONNECTION_DELAY') else 30)
                # El driver será recreado por el context manager en el nivel superior
                raise  # Re-lanza la excepción para que sea manejada en el nivel superior
            else:
                logger.error(f"✗ Se agotaron los intentos para partido {match_id}")
                return False
        except Exception as e:
            logger.error(f"✗ Error procesando partido {match_id}: {e}")
            return False

    def scrape_league_with_incremental_save(self, league_season_url, output_filename=None, update_mode=False, limit_old=None, limit_new=None, order_after_update=None, pre_fix_order=False):
        """Función principal mejorada con guardado incremental, manejo de errores y reconexión automática."""
        league_name = get_base_league_name_from_url(league_season_url)
        ensure_directory_exists(config.OUTPUT_PATH)
        
        if not output_filename:
            output_filename = f"{league_name}.json"
        output_filepath = os.path.join(config.OUTPUT_PATH, output_filename)
        
        # En modo update, solo crear backup si es la primera vez
        if not update_mode:
            create_data_backup(output_filepath, league_name)

        # Nuevo: corrección opcional antes de actualizar
        if update_mode:
            desired_desc = (order_after_update is None and getattr(config, 'DEFAULT_UPDATE_ORDER_DESC', True)) or (order_after_update == 'desc')
            is_interactive_env = (len(sys.argv) == 1)
            if pre_fix_order or (is_interactive_env and getattr(config, 'ASK_FIX_ORDER_BEFORE_UPDATE', True) and os.path.exists(output_filepath)):
                try:
                    print()
                    if is_interactive_env:
                        print("🛠️ El archivo existente puede estar desordenado.")
                        ans = input("¿Deseas corregir el orden a 'más recientes primero' ANTES de actualizar? (s/n): ").strip().lower()
                        if ans == 's':
                            reorder_json_file(output_filepath, order='desc')
                    elif pre_fix_order:
                        reorder_json_file(output_filepath, order='desc')
                except Exception as e:
                    logger.warning(f"No se pudo aplicar la corrección previa de orden: {e}")
        
        # Variables para control de reconexión
        global_driver_restarts = 0
        max_global_restarts = config.MAX_RECONNECTION_ATTEMPTS if hasattr(config, 'MAX_RECONNECTION_ATTEMPTS') else 5
        
        while global_driver_restarts < max_global_restarts:
            try:
                with get_chrome_driver_with_retry(headless=True) as driver:
                    # Obtener lista de partidos (solo la primera vez)
                    if global_driver_restarts == 0:
                        matches_with_stage = self.get_match_id_list(driver, league_season_url)
                        if not matches_with_stage:
                            logger.error("No se encontraron partidos para procesar.")
                            return
                        
                        # Aplicar filtros de prueba si se especifican
                        original_count = len(matches_with_stage)
                        if limit_old:
                            # --old toma los ÚLTIMOS de la lista (más antiguos)
                            matches_with_stage = matches_with_stage[-limit_old:]
                            logger.info(f"🔍 MODO PRUEBA: Tomando los {limit_old} partidos MÁS ANTIGUOS de {original_count}")
                        elif limit_new:
                            # --new toma los PRIMEROS de la lista (más recientes)
                            matches_with_stage = matches_with_stage[:limit_new]
                            logger.info(f"🔍 MODO PRUEBA: Tomando los {limit_new} partidos MÁS RECIENTES de {original_count}")
                        
                        # Verificar si es una liga grande (solo en modo normal)
                        total_matches = len(matches_with_stage)
                        is_large_league = original_count >= (config.AUTO_SHUTDOWN_THRESHOLD if hasattr(config, 'AUTO_SHUTDOWN_THRESHOLD') else 500)
                        
                        if is_large_league and not update_mode and not limit_old and not limit_new:
                            logger.info(f"🔥 LIGA GRANDE DETECTADA: {original_count} partidos")
                            logger.info("🔄 Apagado automático activado al completar")
                    
                    # Cargar partidos ya procesados
                    existing_match_ids = load_existing_match_ids(output_filepath)
                    
                    # Filtrar partidos ya procesados
                    matches_to_process = [
                        match for match in matches_with_stage 
                        if match['id'] not in existing_match_ids
                    ]
                    
                    if global_driver_restarts == 0:  # Solo mostrar info la primera vez
                        already_processed = len(existing_match_ids)
                        to_process = len(matches_to_process)
                        
                        # Mensajes específicos para modo update
                        if update_mode:
                            logger.info(f"📥 MODO UPDATE ACTIVADO")
                            logger.info(f"🔍 Buscando partidos faltantes en: {output_filename}")
                        
                        logger.info(f"Partidos encontrados: {total_matches}")
                        logger.info(f"Ya procesados: {already_processed}")
                        logger.info(f"Por procesar: {to_process}")
                        
                        if to_process == 0:
                            if update_mode:
                                logger.info("✅ Archivo actualizado. No hay partidos faltantes.")
                            else:
                                logger.info("Todos los partidos ya han sido procesados.")
                            
                            if is_large_league and not update_mode and not limit_old and not limit_new:
                                logger.info("🔥 Liga grande completada. Iniciando apagado automático...")
                                shutdown_computer()
                            return
                        
                        if update_mode:
                            logger.info(f"🔄 Actualizando {to_process} partidos faltantes...")
                    
                    # Procesar partidos restantes con sistema de lotes
                    successful_count = 0
                    failed_count = 0
                    batch_size = config.MATCHES_PER_BATCH if hasattr(config, 'MATCHES_PER_BATCH') else 250
                    is_interactive = len(sys.argv) == 1  # Detectar si es modo interactivo
                    
                    # Desactivar pausas automáticas en modo de prueba
                    use_batch_pause = (is_interactive and 
                                     not limit_old and 
                                     not limit_new and
                                     hasattr(config, 'BATCH_PAUSE_MESSAGE') and 
                                     config.BATCH_PAUSE_MESSAGE)
                    
                    for i, match_info in enumerate(matches_to_process):
                        # Verificar si necesitamos pausa por lotes (solo en modo interactivo y no en pruebas)
                        if (use_batch_pause and 
                            i > 0 and 
                            i % batch_size == 0):
                            
                            remaining = len(matches_to_process) - i
                            if not interactive_batch_pause(i, remaining, batch_size):
                                logger.info("Scraping pausado por el usuario. Progreso guardado.")
                                break
                        
                        print_progress_bar(
                            i, len(matches_to_process), 
                            prefix='Progreso:', 
                            suffix=f'Partido {match_info["id"]}'
                        )
                        
                        try:
                            success = self.scrape_match_with_error_handling(
                                driver, match_info, output_filepath
                            )
                            
                            if success:
                                successful_count += 1
                            else:
                                failed_count += 1
                            
                            # Delay entre partidos para evitar rate limiting
                            add_human_delay(2, 4)
                            
                        except WebDriverException as e:
                            logger.error(f"Error crítico de WebDriver: {e}")
                            logger.info("Reiniciando driver...")
                            raise  # Esto forzará la recreación del driver
                    
                    # Si llegamos aquí, el scraping se completó exitosamente
                    print_progress_bar(len(matches_to_process), len(matches_to_process), prefix='Progreso:', suffix='Completado')
                    
                    # Resumen final
                    logger.info("=" * 50)
                    if limit_old or limit_new:
                        logger.info("RESUMEN DE PRUEBA:")
                    elif update_mode:
                        logger.info("RESUMEN DE ACTUALIZACIÓN:")
                    else:
                        logger.info("RESUMEN DEL SCRAPING:")
                    
                    total_processed = successful_count + failed_count
                    logger.info(f"Total de partidos procesados: {total_processed}")
                    logger.info(f"Exitosos: {successful_count}")
                    logger.info(f"Fallidos: {failed_count}")
                    
                    if total_processed < len(matches_to_process):
                        paused_count = len(matches_to_process) - total_processed
                    if total_processed < len(matches_to_process):
                        paused_count = len(matches_to_process) - total_processed
                        logger.info(f"Pausados por el usuario: {paused_count}")
                        logger.info(f"💡 Para continuar usa: python Hoopscraper.py [URL] --update")
                    
                    logger.info(f"Archivo de salida: {output_filepath}")
                    
                    # Verificar apagado automático para ligas grandes (solo en modo normal y si se completó todo, NO en pruebas)
                    if (is_large_league and 
                        failed_count == 0 and 
                        not update_mode and 
                        not limit_old and 
                        not limit_new and
                        total_processed == len(matches_to_process)):
                        logger.info("🔥 LIGA GRANDE COMPLETADA EXITOSAMENTE")
                        logger.info("🔄 Iniciando apagado automático del sistema...")
                        shutdown_computer()
                    elif is_large_league and not update_mode and not limit_old and not limit_new:
                        logger.warning("Liga grande completada con algunos fallos o pausas. No se ejecutará apagado automático.")
                    
                    # Nuevo: reordenar tras completar update para garantizar "más recientes primero"
                    if update_mode:
                        try:
                            final_order = 'desc' if ((order_after_update is None and getattr(config, 'DEFAULT_UPDATE_ORDER_DESC', True)) or order_after_update == 'desc') else 'asc'
                            reorder_json_file(output_filepath, order=final_order)
                            logger.info(f"✅ Orden aplicado tras update ({final_order}). Archivo: {output_filepath}")
                        except Exception as e:
                            logger.warning(f"No se pudo reordenar tras update: {e}")

                    if update_mode and successful_count > 0:
                        logger.info(f"✅ Archivo actualizado exitosamente con {successful_count} nuevos partidos")

                    if limit_old or limit_new:
                        logger.info("🔍 Modo de prueba completado.")

                    logger.info("=" * 50)
                    break  # Salir del bucle de reintentos globales
                    
            except WebDriverException as e:
                global_driver_restarts += 1
                logger.error(f"Error crítico de conexión (intento {global_driver_restarts}/{max_global_restarts}): {e}")
                
                if global_driver_restarts < max_global_restarts:
                    delay = config.RECONNECTION_DELAY if hasattr(config, 'RECONNECTION_DELAY') else 30
                    logger.info(f"Reiniciando completamente en {delay} segundos...")
                    time.sleep(delay)
                else:
                    logger.error("Se agotaron todos los intentos de reconexión. Terminando.")
                    break
            except Exception as e:
                logger.error(f"Error inesperado: {e}")
                break

    def update_league_data(self, league_season_url, output_filename=None):
        """Modo específico para actualizar datos de liga existente."""
        logger.info("🔄 INICIANDO MODO UPDATE")
        return self.scrape_league_with_incremental_save(league_season_url, output_filename, update_mode=True, order_after_update=None, pre_fix_order=False)

# Función principal para mantener compatibilidad
def main():
    # Verificar si se pasaron argumentos de línea de comandos
    if len(sys.argv) > 1:
        # Modo línea de comandos
        parser = argparse.ArgumentParser(description='Scraper de partidos de baloncesto de Flashscore')
        parser.add_argument('url', help='URL de la liga/temporada de Flashscore')
        parser.add_argument('--output', '-o', help='Nombre del archivo de salida')
        parser.add_argument('--headless', action='store_true', default=True, help='Ejecutar en modo headless')
        parser.add_argument('--update', '-u', action='store_true', help='Modo update: solo raspar partidos faltantes')
        parser.add_argument('--old', type=int, metavar='N', help='Modo prueba: raspar solo los N partidos más antiguos')
        parser.add_argument('--new', type=int, metavar='N', help='Modo prueba: raspar solo los N partidos más recientes')
        parser.add_argument('--fix-order', action='store_true', help='Reordenar el archivo existente a "más recientes primero" antes de actualizar')
        parser.add_argument('--order', choices=['desc', 'asc'], help='Orden a aplicar tras la actualización (por defecto: desc si config.DEFAULT_UPDATE_ORDER_DESC=True)')
        
        args = parser.parse_args()
        
        # Validar que no se usen --old y --new al mismo tiempo
        if args.old and args.new:
            print("❌ Error: No puedes usar --old y --new al mismo tiempo")
            return
        
        scraper = FlashscoreMatchScraper()

        if args.update:
            # Derivar el filepath como hace la función
            league_name = get_base_league_name_from_url(args.url)
            out_name = args.output if args.output else f"{league_name}.json"
            out_path = os.path.join(config.OUTPUT_PATH, out_name)

            # Si se pidió, repara orden antes (útil incluso sin modo interactivo)
            if args.fix_order and os.path.exists(out_path):
                reorder_json_file(out_path, order='desc')

            # Pasar preferencias a la función
            scraper.scrape_league_with_incremental_save(
                args.url,
                out_name,
                update_mode=True,
                order_after_update=args.order,            # None respeta config.DEFAULT_UPDATE_ORDER_DESC
                pre_fix_order=args.fix_order
            )
        else:
            scraper.scrape_league_with_incremental_save(
                args.url,
                args.output,
                update_mode=False,
                limit_old=args.old,
                limit_new=args.new
            )
    else:
        # Modo interactivo (doble clic)
        print("=" * 60)
        print("🏀 HOOPSCRAPER - Scraper de Baloncesto de Flashscore")
        print("=" * 60)
        print()
        
        try:
            # Preguntar modo de operación
            print("🔧 SELECCIONAR MODO:")
            print("1. Scraping completo (nueva liga o reiniciar)")
            print("2. Modo update (solo partidos faltantes)")
            print()
            
            while True:
                mode_choice = input("Selecciona modo (1 o 2): ").strip()
                if mode_choice in ['1', '2']:
                    break
                print("❌ Por favor selecciona 1 o 2")
            
            update_mode = (mode_choice == '2')
            
            print()
            if update_mode:
                print("📥 MODO UPDATE SELECCIONADO")
                print("Solo se procesarán partidos faltantes del archivo existente")
            else:
                print("🆕 MODO COMPLETO SELECCIONADO")
                print("Se procesarán todos los partidos (se creará backup del archivo existente)")
            
            print()
            
            # Solicitar URL de la liga
            print("📝 INTRODUCIR URL DE LA LIGA:")
            print("Ejemplo: https://www.flashscore.com/basketball/asia/asia-cup/results/")
            print()
            
            league_url = input("URL: ").strip()
            
            if not league_url:
                print("❌ Error: URL vacía. Cerrando programa.")
                input("Presiona Enter para salir...")
                return
            
            if not league_url.startswith('http'):
                print("❌ Error: URL inválida. Debe comenzar con http:// o https://")
                input("Presiona Enter para salir...")
                return
            
            print()
            print(f"🎯 Liga seleccionada: {league_url}")
            print()
            
            # Preguntar por archivo de salida personalizado (opcional)
            if update_mode:
                print("📁 Archivo existente a actualizar (opcional, presiona Enter para auto-detectar):")
            else:
                print("📁 Archivo de salida (opcional, presiona Enter para auto-generar):")
            
            output_filename = input("Nombre: ").strip()
            
            if not output_filename:
                output_filename = None
                if update_mode:
                    print("✅ Se detectará automáticamente el archivo existente")
                else:
                    print("✅ Se generará nombre automáticamente")
            else:
                if not output_filename.endswith('.json'):
                    output_filename += '.json'
                print(f"✅ Archivo: {output_filename}")
            
            print()
            if update_mode:
                print("🔄 Iniciando modo update...")
            else:
                print("🚀 Iniciando scraping completo...")
            print("=" * 60)
            
            # Ejecutar scraper
            scraper = FlashscoreMatchScraper()
            
            if update_mode:
                scraper.scrape_league_with_incremental_save(
                    league_url,
                    output_filename,
                    update_mode=True
                )
            else:
                scraper.scrape_league_with_incremental_save(league_url, output_filename)
            
        except KeyboardInterrupt:
            print("\n❌ Scraping interrumpido por el usuario.")
        except Exception as e:
            print(f"\n❌ Error inesperado: {e}")
        finally:
            print("\n" + "=" * 60)
            print("Presiona Enter para salir...")
            input()

if __name__ == "__main__":
    main()