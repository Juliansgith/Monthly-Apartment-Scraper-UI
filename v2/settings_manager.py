import json
import os
import logging

CONFIG_FILE = "scraper_settings.json"
# Define default settings structure
DEFAULT_SETTINGS = {
    "min_area": 0,
    "max_rent": 250000,
    "layouts_checked": {"1R": True, "1K": True, "1DK": True, "1LDK": True,
                        "2K": True, "2DK": True, "2LDK": True, "3LDK": True},
    "sort_combo_idx": 0,
    "sort_desc": False,
    "skip_cached_search": False,
    "recheck_details": False,
}

class SettingsManager:
    def __init__(self):
        self.settings = {}
        self.load_settings()

    def load_settings(self):
        if os.path.isfile(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded_settings = json.load(f)
                # Merge loaded settings with defaults to ensure all keys exist
                self.settings = {**DEFAULT_SETTINGS, **loaded_settings}
                # Ensure layouts_checked is a dict
                if not isinstance(self.settings.get("layouts_checked"), dict):
                     self.settings["layouts_checked"] = DEFAULT_SETTINGS["layouts_checked"]
                logging.info(f"Loaded settings from {CONFIG_FILE}")
            except Exception as e:
                logging.warning(f"Could not load settings from {CONFIG_FILE}: {e!r}. Using defaults.")
                self.settings = DEFAULT_SETTINGS.copy()
        else:
            logging.info(f"Settings file {CONFIG_FILE} not found. Using defaults.")
            self.settings = DEFAULT_SETTINGS.copy()

        if not isinstance(self.settings, dict): # last check
            logging.error("Settings became non-dict after load/default. Resetting.")
            self.settings = DEFAULT_SETTINGS.copy()


    def save_settings(self, current_ui_settings):
        """Saves the provided settings to config file."""
        try:
            self.settings.update(current_ui_settings)
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            logging.info(f"Saved settings to {CONFIG_FILE}")
        except Exception as e:
            logging.warning(f"Could not save settings: {e!r}")

    def get_setting(self, key, default=None):
        """Gets a specific setting value, falling back to default."""
        # Use the default from DEFAULT_SETTINGS
        default_value = DEFAULT_SETTINGS.get(key, default)
        return self.settings.get(key, default_value)

    def clear_settings_file(self):
        """Deletes settings file."""
        if os.path.exists(CONFIG_FILE):
            try:
                os.remove(CONFIG_FILE)
                logging.info(f"Cleared settings file: {CONFIG_FILE}")
                # Reset in-memory settings to defaults after clearing file
                self.settings = DEFAULT_SETTINGS.copy()
                return True
            except OSError as e:
                logging.warning(f"Failed to delete settings file: {e}")
                return False
        return True