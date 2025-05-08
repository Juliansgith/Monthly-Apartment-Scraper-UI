import threading
import logging
import json
import os
import requests
import random
import re
import hashlib
import time 
from datetime import datetime
from bs4 import BeautifulSoup
from PyQt5.QtCore import QObject, pyqtSignal

from listing import Listing

BASE_URL   = "https://www.monthly-mansion.com"
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
]
MAX_DETAIL_THREADS = 5 
LISTINGS_CACHE_FILE = "listings_cache.json"
IMAGE_CACHE_DIR = "image_cache"


class DataManager(QObject):
    listing_details_fetched = pyqtSignal(Listing)
    listings_updated = pyqtSignal()
    fetch_status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.all_listings_map = {}
        self.detail_fetch_sem = threading.BoundedSemaphore(MAX_DETAIL_THREADS)
        self.detail_fetch_stop_event = threading.Event()
        self._ensure_image_cache_dir()
        self.load_listings_cache() 

    def _ensure_image_cache_dir(self):
        if not os.path.exists(IMAGE_CACHE_DIR):
            try:
                os.makedirs(IMAGE_CACHE_DIR)
                logging.info(f"Created image cache directory: {IMAGE_CACHE_DIR}")
            except OSError as e:
                logging.error(f"Failed to create image cache directory '{IMAGE_CACHE_DIR}': {e}")

    def _get_image_cache_path(self, url):
        url_hash = hashlib.sha256(url.encode('utf-8')).hexdigest()
        _, ext = os.path.splitext(url)
        if ext.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']: ext = '.jpg'
        return os.path.join(IMAGE_CACHE_DIR, f"{url_hash}{ext}")

    def _get_headers(self):
        return {'User-Agent': random.choice(USER_AGENTS)}

    def add_or_update_listing(self, basic_listing: Listing, recheck_details: bool):
        existing_listing = self.all_listings_map.get(basic_listing.link)
        needs_detail_fetch = False
        is_new = False 

        if existing_listing:
            original_date_added = existing_listing.date_added
            original_is_viewed = existing_listing.is_viewed

            existing_listing.title = basic_listing.title; existing_listing.address = basic_listing.address
            existing_listing.stations = basic_listing.stations; existing_listing.area = basic_listing.area
            existing_listing.layout = basic_listing.layout; existing_listing.build = basic_listing.build
            existing_listing.build_year = existing_listing._parse_build_year(basic_listing.build)
            existing_listing.pay_methods = basic_listing.pay_methods; existing_listing.middle_rent = basic_listing.middle_rent
            existing_listing.utilities = basic_listing.utilities; existing_listing.cleaning = basic_listing.cleaning
            existing_listing.ppm2 = basic_listing.ppm2

            existing_listing.date_added = original_date_added; existing_listing.is_viewed = original_is_viewed

            if not existing_listing.details_fetched or recheck_details: needs_detail_fetch = True
            listing_to_process = existing_listing
            logging.debug(f"Updating existing listing: {basic_listing.link}")
        else:
            self.all_listings_map[basic_listing.link] = basic_listing
            basic_listing.fetch_status = "Pending Details"
            needs_detail_fetch = True
            is_new = True
            listing_to_process = basic_listing
            logging.debug(f"Adding new listing: {basic_listing.link}")

        if needs_detail_fetch:
            if is_new or not listing_to_process.details_fetched or recheck_details:
                 listing_to_process.fetch_status = "Pending Details"
                 threading.Thread(target=self._fetch_listing_details_task, args=(listing_to_process,), daemon=True).start()
        self.listings_updated.emit()


    def _fetch_listing_details_task(self, listing: Listing):
        if self.detail_fetch_stop_event.is_set():
            logging.debug(f"Skipping detail fetch for {listing.link} as stop event is set.")
            if listing.fetch_status != "Details OK":
                 listing.fetch_status = "Detail Fetch Error"; listing.detail_fetch_error_message = "Operation stopped"
                 self.listing_details_fetched.emit(listing)
            return

        with self.detail_fetch_sem:
            if self.detail_fetch_stop_event.is_set():
                 logging.debug(f"Skipping detail fetch for {listing.link} post-semaphore as stop event is set.")
                 if listing.fetch_status != "Details OK":
                      listing.fetch_status = "Detail Fetch Error"; listing.detail_fetch_error_message = "Operation stopped (post-sem)"
                      self.listing_details_fetched.emit(listing)
                 return

            try:
                logging.info(f"Fetching full details for: {listing.link}")
                self.fetch_status_update.emit(f"Fetching details: {listing.title[:30]}...")
                headers = self._get_headers()
                resp = requests.get(listing.link, headers=headers, timeout=25)
                resp.raise_for_status()
                resp.encoding = 'EUC-JP'
                soup = BeautifulSoup(resp.text, 'html.parser')

                photo_urls = []
                fetched_photo_data = []
                for a_tag in soup.select('div.photo ul.thumbnail li a'):
                    img_href = a_tag.get('href')
                    if img_href:
                        full_photo_url = BASE_URL + img_href if not img_href.startswith('http') else img_href
                        photo_urls.append(full_photo_url)
                        cache_path = self._get_image_cache_path(full_photo_url)
                        image_bytes = None
                        if os.path.exists(cache_path):
                             try:
                                  with open(cache_path, 'rb') as f_img: image_bytes = f_img.read()
                                  logging.debug(f"Loaded image from cache: {cache_path}")
                             except Exception as e_read: logging.warning(f"Failed to read image cache '{cache_path}': {e_read}")
                        if image_bytes is None:
                             try:
                                  if self.detail_fetch_stop_event.is_set(): raise InterruptedError("Stop event set during photo fetch")
                                  img_resp = requests.get(full_photo_url, headers=headers, timeout=15); img_resp.raise_for_status()
                                  image_bytes = img_resp.content
                                  try:
                                       with open(cache_path, 'wb') as f_img: f_img.write(image_bytes)
                                       logging.debug(f"Saved image to cache: {cache_path}")
                                  except Exception as e_write: logging.warning(f"Failed to write image cache '{cache_path}': {e_write}")
                             except requests.exceptions.RequestException as img_e: logging.warning(f"Image download failed for {full_photo_url}: {img_e!r}")
                             except InterruptedError: logging.info(f"Photo fetch interrupted for {listing.link}"); raise
                listing.photo_urls = photo_urls

                appliances, remarks_str = [], ""
                setsubi_th = soup.find('th', string='設備'); bikou_th = soup.find('th', string='備考')
                if setsubi_th and setsubi_th.find_next_sibling('td'):
                    setsubi_td = setsubi_th.find_next_sibling('td')
                    if setsubi_td.find_all('li'): appliances = [li.get_text(strip=True) for li in setsubi_td.find_all('li')]
                    else: appliances = [item.strip() for item in re.split(r'[、､,]', setsubi_td.get_text(strip=True)) if item.strip()]
                if bikou_th and bikou_th.find_next_sibling('td'): remarks_str = bikou_th.find_next_sibling('td').get_text("\n", strip=True)
                listing.appliances = appliances; listing.remarks = remarks_str

                listing.latitude = None; listing.longitude = None
                gmaps_iframe = soup.select_one('iframe[src*="google.com/maps/embed"]')
                if gmaps_iframe and gmaps_iframe.get('src'):
                    gmaps_src = gmaps_iframe['src']
                    coord_match = re.search(r'[?&]q=([\d.-]+),([\d.-]+)', gmaps_src)
                    if coord_match:
                        try: listing.latitude = float(coord_match.group(1)); listing.longitude = float(coord_match.group(2)); logging.info(f"Geo found: {listing.latitude}, {listing.longitude}")
                        except ValueError: logging.warning(f"Geo convert fail: {coord_match.groups()}")
                    else: logging.warning(f"Geo parse fail: {gmaps_src}")
                else: logging.warning(f"No GMap iframe found for {listing.link}")

                listing.details_fetched = True; listing.fetch_status = "Details OK"; listing.detail_fetch_error_message = ""
                logging.info(f"✓ Full details fetched for: {listing.title}")

            except InterruptedError: listing.fetch_status = "Detail Fetch Error"; listing.detail_fetch_error_message = "Operation stopped"
            except requests.exceptions.RequestException as e: logging.warning(f"Net error details {listing.link}: {e!r}"); listing.fetch_status = "Detail Fetch Error"; listing.detail_fetch_error_message = str(e)
            except Exception as e: logging.error(f"Error parsing details {listing.link}: {e!r}", exc_info=True); listing.fetch_status = "Detail Parse Error"; listing.detail_fetch_error_message = str(e)
            finally: self.fetch_status_update.emit(""); self.listing_details_fetched.emit(listing)

    def stop_detail_fetching(self):
         logging.info("Signalling detail fetch threads to stop.")
         self.detail_fetch_stop_event.set()

    def clear_detail_fetch_stop(self):
         self.detail_fetch_stop_event.clear()

    def trigger_single_detail_fetch(self, listing_link):
        listing = self.get_listing_by_link(listing_link)
        if listing:
            logging.info(f"Triggering manual detail fetch for {listing.link}")
            listing.fetch_status = "Pending Details"; listing.detail_fetch_error_message = ""
            listing.details_fetched = False
            self.listings_updated.emit() 
            threading.Thread(target=self._fetch_listing_details_task, args=(listing,), daemon=True).start()
            return True
        else: logging.warning(f"Could not trigger fetch for non-existent link: {listing_link}"); return False

    def trigger_refresh_all_details(self):
        """Queues all known listings for detail fetching."""
        logging.info(f"Triggering detail refresh for all {len(self.all_listings_map)} listings.")
        self.clear_detail_fetch_stop() # ensure fetches can run, bug fix
        count = 0
        for listing in self.all_listings_map.values():
             listing.fetch_status = "Pending Details"
             listing.detail_fetch_error_message = ""
             listing.details_fetched = False
             threading.Thread(target=self._fetch_listing_details_task, args=(listing,), daemon=True).start()
             count += 1
             time.sleep(0.02) 
        self.listings_updated.emit() 
        logging.info(f"Queued {count} listings for detail refresh.")

    def get_all_listings(self): return list(self.all_listings_map.values())
    def get_listing_by_link(self, link): return self.all_listings_map.get(link)
    def get_known_links(self): return set(self.all_listings_map.keys())

    def toggle_favourite(self, listing_link):
         listing = self.get_listing_by_link(listing_link)
         if listing: listing.is_fav = not listing.is_fav; logging.debug(f"Toggled fav {listing.link} to {listing.is_fav}"); self.listings_updated.emit(); return True
         return False

    def get_filtered_listings(self, min_area, max_rent, sort_key_text, sort_reverse):
        temp_filtered_list = []
        for listing in self.all_listings_map.values():
            if listing.area is None or listing.middle_rent is None: continue
            if min_area > 0 and listing.area < min_area: continue
            if max_rent > 0 and listing.middle_rent > max_rent: continue
            temp_filtered_list.append(listing)
        try:
            key_func = None
            default_asc = float('inf')
            default_desc = float('-inf')
            use_datetime = False

            if sort_key_text == "Price": key_func = lambda l: l.middle_rent
            elif sort_key_text == "Area": key_func = lambda l: l.area
            elif sort_key_text == "Price per m²": key_func = lambda l: l.ppm2 if l.ppm2 is not None else (default_asc if not sort_reverse else default_desc)
            elif sort_key_text == "Build Year": key_func = lambda l: l.build_year if l.build_year is not None else (default_asc if not sort_reverse else default_desc)
            elif sort_key_text == "Date Added":
                 key_func = lambda l: l.date_added if l.date_added is not None else (datetime.max if not sort_reverse else datetime.min)
                 use_datetime = True 

            if key_func:
                temp_filtered_list.sort(key=lambda l: key_func(l) if (key_func(l) is not None or use_datetime) 
                                          else (default_asc if not sort_reverse else default_desc),
                                        reverse=sort_reverse)
        except Exception as e: logging.error(f"Sorting failed: {e}", exc_info=True)
        return temp_filtered_list

    def get_favourites(self):
        favs = [l for l in self.all_listings_map.values() if l.is_fav]
        favs.sort(key=lambda x: x.title)
        return favs

    def calculate_statistics(self, filtered_list):
        total_scraped = len(self.all_listings_map); displayed_count = len(filtered_list)
        fav_count = len(self.get_favourites()); avg_rent_str = "N/A"; avg_area_str = "N/A"; layout_counts = {}
        if displayed_count > 0:
            valid_rent = [l.middle_rent for l in filtered_list if l.middle_rent is not None]; valid_area = [l.area for l in filtered_list if l.area is not None and l.area > 0]
            avg_rent_str = f"¥{sum(valid_rent) / len(valid_rent):,.0f}" if valid_rent else "N/A"; avg_area_str = f"{sum(valid_area) / len(valid_area):.1f} m²" if valid_area else "N/A"
            for l in filtered_list: layout_counts[l.layout] = layout_counts.get(l.layout, 0) + 1
        return {"total_scraped": total_scraped, "displayed_count": displayed_count, "fav_count": fav_count, "avg_rent": avg_rent_str, "avg_area": avg_area_str, "layout_counts": layout_counts}

    def load_listings_cache(self):
        self.all_listings_map.clear()
        if not os.path.isfile(LISTINGS_CACHE_FILE):
            logging.info(f"Listings cache file {LISTINGS_CACHE_FILE} not found.")
            return False

        try:
            with open(LISTINGS_CACHE_FILE, 'r', encoding='utf-8') as f: cached_data = json.load(f)
            if not isinstance(cached_data, list): cached_data = []

            loaded_count = 0; pending_fetch_links = []
            for listing_dict in cached_data:
                l_obj = Listing.from_dict(listing_dict)
                if l_obj and l_obj.link:
                    self.all_listings_map[l_obj.link] = l_obj
                    if l_obj.fetch_status == "Pending Details":
                         pending_fetch_links.append(l_obj.link)
                    loaded_count += 1
                else: logging.warning(f"Skipped invalid listing data from cache: {listing_dict.get('link', 'NO LINK')}")

            logging.info(f"Loaded {loaded_count} listings from cache. Found {len(pending_fetch_links)} pending detail fetches.")
            self.listings_updated.emit() 

            if pending_fetch_links:
                 logging.info("Triggering automatic detail fetch for pending listings...")
                 self.clear_detail_fetch_stop() 
                 for link in pending_fetch_links:
                      self.trigger_single_detail_fetch(link)
                      time.sleep(0.05) 
            return True

        except Exception as e:
            logging.error(f"Failed to load listings cache {LISTINGS_CACHE_FILE}: {e!r}")
            return False

    def save_listings_cache(self):
        if not self.all_listings_map and not os.path.exists(LISTINGS_CACHE_FILE): return
        logging.info(f"Attempting to save {len(self.all_listings_map)} listings to cache.")
        data_to_save = [l_obj.to_dict() for l_obj in self.all_listings_map.values()]
        try:
            with open(LISTINGS_CACHE_FILE, 'w', encoding='utf-8') as f: json.dump(data_to_save, f, ensure_ascii=False, indent=2)
            logging.info(f"Saved {len(data_to_save)} listings to {LISTINGS_CACHE_FILE}")
        except TypeError as e: logging.error(f"TypeError during JSON serialization for cache: {e}.")
        except Exception as e: logging.warning(f"Could not save listings cache: {e!r}")


    def clear_cache_file_and_memory(self):
        cleared_file = False
        if os.path.exists(LISTINGS_CACHE_FILE):
            try: os.remove(LISTINGS_CACHE_FILE); logging.info(f"Cleared listings cache file: {LISTINGS_CACHE_FILE}"); cleared_file = True
            except OSError as e: logging.warning(f"Failed to delete listings cache file: {e}"); cleared_file = False
        self.all_listings_map.clear()
        self.listings_updated.emit()
        return cleared_file

    def get_photo_data(self, listing: Listing):
        photo_data = []
        if not listing or not listing.photo_urls: return photo_data
        for url in listing.photo_urls:
            cache_path = self._get_image_cache_path(url)
            img_bytes = None
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, 'rb') as f_img: img_bytes = f_img.read()
                except Exception as e: logging.warning(f"Failed to read image cache '{cache_path}': {e}")
            else: logging.debug(f"Image not in cache: {cache_path} for URL: {url}")
            photo_data.append(img_bytes) 
        return photo_data