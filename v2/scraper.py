import threading
import logging
import requests
import random
import time
import re
from bs4 import BeautifulSoup
from PyQt5.QtCore import QObject, pyqtSignal

from listing import Listing 

BASE_URL   = "https://www.monthly-mansion.com"
WARD_CODES = ["13119","13113","13104","13115","13102",
              "13101","13116","13105","13103","13110"]
LAYOUT_PARAM_MAP = {
    "1R":"m1r","1K":"m1k","1DK":"m1dk","1LDK":"m1ldk",
    "2K":"m2k","2DK":"m2dk","2LDK":"m2ldk","3LDK":"m3ldk"
}
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
]
INITIAL_BACKOFF_TIME = 5
MAX_BACKOFF_TIME     = 60
MAX_SCRAPER_RETRIES  = 5

class Scraper(QObject):
    """Handles the web scraping process in a separate thread."""
    new_listing = pyqtSignal(Listing) 
    finished    = pyqtSignal()
    error       = pyqtSignal(str)
    progress    = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._stop_event   = threading.Event()
        self.layout_params = []
        self.known_listing_links = set() # delta scraping check

    def _get_headers(self):
        return {'User-Agent': random.choice(USER_AGENTS)}

    def start(self, layout_params, known_links, skip_cached):
        logging.debug(f"Scraper.start() with layouts={layout_params}, skip_cached={skip_cached}")
        self.layout_params = layout_params
        self.known_listing_links = known_links
        self.skip_cached = skip_cached
        self._stop_event.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        logging.info("Stop requested for Scraper.")
        self._stop_event.set()

    def _build_url(self, page):
        url = BASE_URL + "/tokyo/search/list.html?search_mode=area"
        for c in WARD_CODES:
            url += f"&jc%5B%5D={c}"
        url += "&cmd=select_page&rno=300&cnt=30&srt=1"
        for t in self.layout_params:
            p = LAYOUT_PARAM_MAP.get(t)
            if p:
                url += f"&{p}=1"
        url += "&j01=1"
        url += f"&pno={page}"
        return url

    def _run(self):
        try:
            page = 1
            empty_in_a_row = 0
            current_backoff_time = INITIAL_BACKOFF_TIME
            retries = 0

            logging.debug("Scraper thread started")
            while not self._stop_event.is_set():
                url = self._build_url(page)
                logging.info(f"Fetching page {page}: {url}")
                self.progress.emit(f"Fetching page {page}...")
                try:
                    resp = requests.get(url, headers=self._get_headers(), timeout=20)
                    resp.raise_for_status()
                    retries = 0
                    current_backoff_time = INITIAL_BACKOFF_TIME
                except requests.exceptions.HTTPError as http_err:
                    logging.warning(f"HTTP error: {http_err.response.status_code} for {url}")
                    if http_err.response.status_code in [403, 429] or http_err.response.status_code >= 500:
                        retries += 1
                        if retries > MAX_SCRAPER_RETRIES:
                            self.error.emit(f"Max retries exceeded for {url}. Error: {http_err}")
                            break
                        logging.warning(f"Retrying ({retries}/{MAX_SCRAPER_RETRIES}) in {current_backoff_time}s...")
                        self.progress.emit(f"Rate limited. Retrying page {page} in {current_backoff_time}s...")
                        self._stop_event.wait(current_backoff_time)
                        if self._stop_event.is_set(): break
                        current_backoff_time = min(current_backoff_time * 2, MAX_BACKOFF_TIME)
                        continue
                    else:
                        self.error.emit(f"HTTP error: {http_err}")
                        break
                except requests.exceptions.RequestException as req_err:
                    logging.error(f"Request exception: {req_err} for {url}")
                    retries += 1
                    if retries > MAX_SCRAPER_RETRIES:
                        self.error.emit(f"Max retries exceeded for {url}. Error: {type(req_err).__name__}: {req_err}")
                        break
                    logging.warning(f"Retrying ({retries}/{MAX_SCRAPER_RETRIES}) in {current_backoff_time}s...")
                    self.progress.emit(f"Network issue. Retrying page {page} in {current_backoff_time}s...")
                    self._stop_event.wait(current_backoff_time)
                    if self._stop_event.is_set(): break
                    current_backoff_time = min(current_backoff_time * 2, MAX_BACKOFF_TIME)
                    continue

                # Use resp.content and let BeautifulSoup handle decoding
                soup = BeautifulSoup(resp.content, 'html.parser', from_encoding='EUC-JP')
                boxes = soup.select('.listArea .box')

                if not boxes:
                    empty_in_a_row += 1
                    if empty_in_a_row >= 2:
                        logging.info(f"No more listings after page {page-1}.")
                        break
                    page += 1
                    self._stop_event.wait(1)
                    if self._stop_event.is_set(): break
                    continue
                empty_in_a_row = 0

                for idx, box in enumerate(boxes):
                    if self._stop_event.is_set():
                        logging.debug("Stop event detected in Scraper, breaking box loop")
                        break
                    try:
                        title_tag = box.select_one('.th02 a')
                        if not title_tag or not title_tag.has_attr('href'):
                            logging.warning(f"[p{page}][#{idx}] Title tag or href not found. Skipping.")
                            continue
                        link  = BASE_URL + title_tag['href']
                        title = title_tag.get_text(strip=True)

                        # Delta Scraping Check
                        if self.skip_cached and link in self.known_listing_links:
                            logging.debug(f"Skipping known listing (delta mode): {link}")
                            continue # skip processing further

                        detail_table_el = box.select_one('.detail table')
                        if not detail_table_el:
                            logging.warning(f"[p{page}][#{idx}] Detail table not found for '{title}'. Skipping.")
                            continue

                        # Initialize with defaults for critical fields
                        data = {} # Still populate for less critical or unexpected fields
                        addr_val = ''
                        stations_val = ''
                        area_str_val = '0' # Keep as string initially
                        layout_val = 'N/A'
                        build_val = ''
                        pay_method_val = ''

                        for tr_detail in detail_table_el.find_all('tr'):
                            th_tag = tr_detail.find('th')
                            td_tag = tr_detail.find('td')
                            if th_tag and td_tag:
                                k = th_tag.get_text(strip=True)
                                v = td_tag.get_text(" / ", strip=True)
                                data[k] = v # Populate data dict for general access

                                # Direct assignment for critical known fields
                                if k == '住所':
                                    addr_val = v
                                elif k == '最寄り駅':
                                    stations_val = v
                                elif k == '面積':
                                    area_str_val = v
                                elif k in ['間取', '間取り', 'タイプ']:
                                    layout_val = v
                                elif k == '築年月':
                                    build_val = v
                                elif 'お支払い方法' in k:
                                    pay_method_val = v
                        
                        # Process directly extracted critical values
                        area_s = area_str_val.replace('m²','').strip().rstrip('〜')
                        try:
                            area = float(area_s) if area_s else 0.0
                        except ValueError:
                            logging.warning(f"[p{page}][#{idx}] Bad area value '{area_s}' for '{title}'. Skipping.")
                            continue
                        if area == 0.0 and area_str_val != '0': # Only skip if truly zero and not default
                            logging.warning(f"[p{page}][#{idx}] Area is 0 for '{title}' (original: '{area_str_val}'). Skipping.")
                            continue
                        
                        # Use directly assigned values
                        addr = addr_val
                        stations = stations_val
                        layout = layout_val
                        build = build_val
                        pay_method = pay_method_val

                        rent_tbl = box.select_one('.rent table')
                        if not rent_tbl:
                            logging.warning(f"[p{page}][#{idx}] Rent table not found for '{title}'. Skipping.")
                            continue

                        row_m = rent_tbl.select_one('tr.m')
                        row_s = rent_tbl.select_one('tr.s')
                        row_generic = None
                        if not (row_m or row_s):
                             candidate_rows = rent_tbl.select('tr')
                             # Check if the first row looks like a header-value pair for rent
                             if candidate_rows and candidate_rows[0].find('th'):
                                row_generic = candidate_rows[0]

                        target_row = row_m or row_s or row_generic
                        if not target_row:
                            logging.warning(f"[p{page}][#{idx}] No m, s, or generic rent row for '{title}'. Skipping.")
                            continue

                        cols = target_row.find_all('td')
                        if len(cols) < 1:
                            logging.warning(f"[p{page}][#{idx}] Not enough columns in rent row for '{title}'. Skipping.")
                            continue

                        rent_txt = cols[0].get_text(" ", strip=True).replace('〜','')
                        m = re.search(r'([\d,]+)円/月', rent_txt)
                        rent_val = None
                        if not m:
                            m_fallback = re.search(r'([\d,]+)円', rent_txt)
                            if m_fallback:
                                rent_val_str = m_fallback.group(1).replace(',','')
                                try:
                                     potential_rent = int(rent_val_str)
                                     if potential_rent > 20000: # heuristic check
                                          rent_val = potential_rent
                                          logging.debug(f"Used fallback rent parsing (no /月) for {title}: {rent_txt}")
                                     else:
                                          logging.warning(f"[p{page}][#{idx}] Rent parse (円/月 not found, fallback value {rent_val_str} too low): '{rent_txt}' for '{title}'. Skipping.")
                                          continue
                                except ValueError:
                                      logging.warning(f"[p{page}][#{idx}] Rent parse failed converting fallback '{rent_val_str}': '{rent_txt}' for '{title}'. Skipping.")
                                      continue
                            else:
                                logging.warning(f"[p{page}][#{idx}] Monthly rent parse fail (no 円/月 or 円): '{rent_txt}' for '{title}'. Skipping.")
                                continue
                        else:
                             try:
                                rent_val = int(m.group(1).replace(',',''))
                             except ValueError:
                                logging.warning(f"[p{page}][#{idx}] Rent parse failed converting '{m.group(1)}': '{rent_txt}' for '{title}'. Skipping.")
                                continue

                        if rent_val is None: # backup
                            logging.warning(f"[p{page}][#{idx}] Rent value ended up None after parsing: '{rent_txt}' for '{title}'. Skipping.")
                            continue

                        utils = cols[1].get_text(strip=True) if len(cols) > 1 else "N/A"
                        clean = cols[2].get_text(strip=True) if len(cols) > 2 else "N/A"

                        listing = Listing(
                            title, link, addr, stations, area,
                            layout, build, pay_method,
                            rent_val, utils, clean
                        )
                        self.new_listing.emit(listing)
                        self._stop_event.wait(0.05)
                        if self._stop_event.is_set(): break

                    except Exception as e:
                        logging.error(f"[p{page}][#{idx}] Exception processing box for '{title if 'title' in locals() else 'Unknown'}': {e!r}", exc_info=True)

                if self._stop_event.is_set():
                    logging.debug("Stop event detected after page processing.")
                    break
                page += 1
                self._stop_event.wait(0.25)
                if self._stop_event.is_set(): break

            logging.debug("Scraper thread exiting normally or due to stop.")
            self.finished.emit()

        except Exception as e:
            logging.error("Unhandled Scraper error in _run:", exc_info=True)
            self.error.emit(f"Critical scraper error: {str(e)}")
        finally:
            logging.debug("Scraper thread _run finished.")