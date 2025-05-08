# Monthly Apartment UI

Makes it easier to compare apartments and their locations without relying on outdated website.

## Prerequisites

- Python 3.x installed
- `virtualenv` (or use the built-in `venv` module)

## Setup & Installation

1. **Create a virtual environment**  
   
   python -m venv .venv

Activate it:

# Windows

.\.venv\Scripts\activate

# macOS/Linux

source .venv/bin/activate


# Install dependencies


pip install -r requirements.txt

# Usage
Change into the v2 directory:

cd v2


# Run the main script:

python main.py

# Project Structure

.
├── .gitignore
├── README.md
├── requirements.txt
└── v2
    ├── __pycache__/           # Python bytecode cache (ignored)
    ├── image_cache/           # Cached images (ignored)
    ├── data_manager.py
    ├── listing_model.py
    ├── listing.py
    ├── listings_cache.json    # Listings cache (ignored)
    ├── main_window.py
    ├── main.py                # Entry point
    ├── map_manager.py
    ├── scraper.py
    ├── scraper_settings.json  # Scraper configuration (ignored)
    ├── settings_manager.py
    └── station_data.py              # Entry point


# Notes
All cache and environment folders/files are excluded via .gitignore.

Adjust the virtual environment name (.venv) or paths if you prefer a different setup.

