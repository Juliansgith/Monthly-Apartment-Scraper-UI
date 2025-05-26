import pytest
import requests
import os
import logging # Added for caplog
from PyQt5.QtCore import QCoreApplication # Required for Qt event loop in tests
from pytestqt.qt_compat import qt_api

# Make sure the v2 directory is in the Python path for imports
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scraper import Scraper, BASE_URL
from listing import Listing

# Directory containing mock HTML files
MOCK_HTML_DIR = os.path.join(os.path.dirname(__file__), 'mock_html')

@pytest.fixture
def scraper_qtbot(qtbot):
    # Ensure a QCoreApplication instance exists for signal handling
    if QCoreApplication.instance() is None:
        QCoreApplication(sys.argv if hasattr(sys, 'argv') else []) # sys.argv might not exist in some test envs
    
    scraper = Scraper()
    # qtbot.addWidget(scraper) # Scraper is QObject, not QWidget. Not needed for signal testing.
    return scraper, qtbot

def read_mock_html(filename):
    with open(os.path.join(MOCK_HTML_DIR, filename), 'r', encoding='utf-8') as f:
        return f.read()

# Test Case 1: Scraping multiple listings
def test_scrape_multiple_listings(scraper_qtbot, requests_mock):
    scraper, qtbot = scraper_qtbot
    page_content = read_mock_html('page_with_listings.html')
    
    # Mock the request for page 1
    requests_mock.get(scraper._build_url(page=1), text=page_content, headers={'Content-Type': 'text/html; charset=EUC-JP'})
    # Mock the request for page 2 (empty, to stop the scraper)
    requests_mock.get(scraper._build_url(page=2), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})
    # Mock the request for page 3 (empty, to stop the scraper, ensuring empty_in_a_row logic works)
    requests_mock.get(scraper._build_url(page=3), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})

    listings_received = []
    scraper.new_listing.connect(listings_received.append)

    with qtbot.waitSignal(scraper.finished, timeout=10000) as blocker:
        scraper.start(layout_params=["1K", "1DK", "1R"], known_links=set(), skip_cached=False)
    
    blocker.wait() # Ensure all signals processed after finished

    assert len(listings_received) == 3
    assert requests_mock.call_count == 3 # page 1, page 2, page 3

    # Verify details of the first listing
    listing1 = next((l for l in listings_received if l.link == BASE_URL + "/tokyo/rent/1001"), None)
    assert listing1 is not None
    assert listing1.title == "Test Apartment 1"
    assert listing1.address == "Test Address 1"
    assert listing1.area == 25.0
    assert listing1.layout == "1K"
    assert listing1.middle_rent == 80000
    assert listing1.utilities == "5,000円" # As per scraper logic, this is text

    # Verify details of the second listing
    listing2 = next((l for l in listings_received if l.link == BASE_URL + "/tokyo/rent/1002"), None)
    assert listing2 is not None
    assert listing2.title == "Test Apartment 2"
    assert listing2.area == 30.5
    assert listing2.layout == "1DK" # Parsed from '間取り'
    assert listing2.middle_rent == 90000

    # Verify details of the third listing (minimal, fallback rent)
    listing3 = next((l for l in listings_received if l.link == BASE_URL + "/tokyo/rent/1003"), None)
    assert listing3 is not None
    assert listing3.title == "Test Apartment 3 Minimal"
    assert listing3.area == 19.0
    assert listing3.layout == "1R" # Parsed from 'タイプ'
    assert listing3.middle_rent == 75000 # Parsed from '75000円' (no /月)


# Test Case 2: Scraping a single listing
def test_scrape_single_listing(scraper_qtbot, requests_mock):
    scraper, qtbot = scraper_qtbot
    page_content = read_mock_html('page_with_one_listing.html')

    requests_mock.get(scraper._build_url(page=1), text=page_content, headers={'Content-Type': 'text/html; charset=EUC-JP'})
    requests_mock.get(scraper._build_url(page=2), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})
    requests_mock.get(scraper._build_url(page=3), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})

    listings_received = []
    scraper.new_listing.connect(listings_received.append)

    with qtbot.waitSignal(scraper.finished, timeout=5000) as blocker:
        scraper.start(layout_params=["1K"], known_links=set(), skip_cached=False)
    
    blocker.wait()

    assert len(listings_received) == 1
    assert requests_mock.call_count == 3 # page 1, page 2, page 3

    listing = listings_received[0]
    assert listing.title == "Solo Test Apartment"
    assert listing.link == BASE_URL + "/tokyo/rent/2001"
    assert listing.area == 22.5
    assert listing.middle_rent == 70000


# Test Case 3: Scraping an empty page
def test_scrape_empty_page(scraper_qtbot, requests_mock):
    scraper, qtbot = scraper_qtbot
    
    # Scraper stops after 2 consecutive empty pages
    requests_mock.get(scraper._build_url(page=1), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})
    requests_mock.get(scraper._build_url(page=2), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})

    listings_received = []
    scraper.new_listing.connect(listings_received.append)
    
    # Keep track of error signals
    errors_received = []
    scraper.error.connect(errors_received.append)

    with qtbot.waitSignal(scraper.finished, timeout=5000) as blocker:
        scraper.start(layout_params=["1K"], known_links=set(), skip_cached=False)
    
    blocker.wait()

    assert len(listings_received) == 0
    assert len(errors_received) == 0 # No errors should be emitted for empty pages
    assert requests_mock.call_count == 2 # page 1, page 2 (stops after this)


# Test Case 4: Scraping with skip_cached enabled
def test_scrape_skip_cached_listings(scraper_qtbot, requests_mock):
    scraper, qtbot = scraper_qtbot
    page_content = read_mock_html('page_known_links.html') # Contains 3 listings

    requests_mock.get(scraper._build_url(page=1), text=page_content, headers={'Content-Type': 'text/html; charset=EUC-JP'})
    requests_mock.get(scraper._build_url(page=2), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})
    requests_mock.get(scraper._build_url(page=3), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})

    # Define some links as already known
    known_links = {
        BASE_URL + "/tokyo/rent/4001", # Known Apartment 1
        BASE_URL + "/tokyo/rent/4003", # Known Apartment 2
    }

    listings_received = []
    scraper.new_listing.connect(listings_received.append)

    with qtbot.waitSignal(scraper.finished, timeout=5000) as blocker:
        # Start scraper with skip_cached=True and the set of known_links
        scraper.start(layout_params=["1K", "1DK", "1R"], known_links=known_links, skip_cached=True)
    
    blocker.wait()

    assert len(listings_received) == 1 # Only one new listing should be processed
    assert requests_mock.call_count == 3

    # Verify that the received listing is the new one
    new_listing = listings_received[0]
    assert new_listing.link == BASE_URL + "/tokyo/rent/4002"
    assert new_listing.title == "New Apartment 1"


# Test Case 5: Error handling for malformed listing data
def test_scrape_malformed_listing_data(scraper_qtbot, requests_mock, caplog):
    scraper, qtbot = scraper_qtbot
    page_content = read_mock_html('page_error.html') # Contains 2 valid and 3 malformed listings

    requests_mock.get(scraper._build_url(page=1), text=page_content, headers={'Content-Type': 'text/html; charset=EUC-JP'})
    requests_mock.get(scraper._build_url(page=2), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})
    requests_mock.get(scraper._build_url(page=3), text=read_mock_html('page_empty.html'), headers={'Content-Type': 'text/html; charset=EUC-JP'})
    
    listings_received = []
    scraper.new_listing.connect(listings_received.append)
    
    # Capture logging output
    caplog.set_level(logging.WARNING)

    with qtbot.waitSignal(scraper.finished, timeout=5000) as blocker:
        scraper.start(layout_params=["1K", "1DK", "1R", "1LDK"], known_links=set(), skip_cached=False)
    
    blocker.wait()

    assert len(listings_received) == 2 # Only two listings are valid
    assert requests_mock.call_count == 3

    # Verify the valid listings
    titles_received = {l.title for l in listings_received}
    assert "Good Apartment Before Error" in titles_received
    assert "Good Apartment After Error" in titles_received

    # Check for expected logging messages (scraper logs warnings for bad items)
    # Order of log messages might vary due to concurrent processing or dict iteration order in scraper.
    # So, we check for the presence of key parts of the expected log messages.
    
    log_text = caplog.text
    # Listing 2 (Error: Missing rent table)
    assert "Rent table not found for 'Apartment Missing Rent'" in log_text
    # Listing 3 (Error: Unparseable area)
    assert "Bad area value 'Twenty Sq Meters' for 'Apartment Bad Area'" in log_text
    # Listing 4 (Error: Missing title link href)
    assert "Title tag or href not found. Skipping." in log_text # Check for the actual log message


# Test Case 6: HTTP client error (e.g., 403 Forbidden) handling
def test_scrape_http_client_error_then_gives_up(scraper_qtbot, requests_mock):
    scraper, qtbot = scraper_qtbot
    
    # Simulate a 403 error for all attempts on page 1
    # The scraper is configured with MAX_SCRAPER_RETRIES = 5 and backoff
    url_page1 = scraper._build_url(page=1)
    requests_mock.get(url_page1, status_code=403)

    error_message = ""
    def handle_error(msg):
        nonlocal error_message
        error_message = msg
    
    scraper.error.connect(handle_error)
    listings_received = []
    scraper.new_listing.connect(listings_received.append)

    # Reduce retry delays for faster test execution
    # global INITIAL_BACKOFF_TIME, MAX_BACKOFF_TIME, MAX_SCRAPER_RETRIES # Not needed here, using scraper_module
    
    # Temporarily modify global constants from scraper module for this test
    # This is generally not ideal, but for testing retry logic it's pragmatic
    # A better way would be to make these configurable on the Scraper instance
    import scraper as scraper_module # Local import for modifying module globals
    original_initial_backoff = scraper_module.INITIAL_BACKOFF_TIME
    original_max_backoff = scraper_module.MAX_BACKOFF_TIME
    original_max_retries = scraper_module.MAX_SCRAPER_RETRIES
    
    scraper_module.INITIAL_BACKOFF_TIME = 0.1 
    scraper_module.MAX_BACKOFF_TIME = 0.2
    scraper_module.MAX_SCRAPER_RETRIES = 2 # Reduce retries to speed up test

    try:
        with qtbot.waitSignal(scraper.finished, timeout=5000) as blocker_finished, \
             qtbot.waitSignal(scraper.error, timeout=5000) as blocker_error:
            scraper.start(layout_params=["1K"], known_links=set(), skip_cached=False)
        
        blocker_finished.wait() # finished should always be emitted
        blocker_error.wait() # error should be emitted

    finally:
        # Restore original values
        scraper_module.INITIAL_BACKOFF_TIME = original_initial_backoff
        scraper_module.MAX_BACKOFF_TIME = original_max_backoff
        scraper_module.MAX_SCRAPER_RETRIES = original_max_retries

    assert len(listings_received) == 0
    assert "Max retries exceeded" in error_message
    assert "403" in error_message
    # Total calls = 1 initial + current MAX_SCRAPER_RETRIES (which is 2 for this test)
    assert requests_mock.call_count == 1 + 2 # Use the actual value set for the test (2)


# Test Case 7: HTTP server error (e.g., 500 Internal Server Error) handling
def test_scrape_http_server_error_then_gives_up(scraper_qtbot, requests_mock):
    scraper, qtbot = scraper_qtbot
    
    url_page1 = scraper._build_url(page=1)
    requests_mock.get(url_page1, status_code=500)

    error_message = ""
    def handle_error(msg):
        nonlocal error_message
        error_message = msg
    
    scraper.error.connect(handle_error)
    listings_received = []
    scraper.new_listing.connect(listings_received.append)

    import scraper as scraper_module
    original_initial_backoff = scraper_module.INITIAL_BACKOFF_TIME
    original_max_backoff = scraper_module.MAX_BACKOFF_TIME
    original_max_retries = scraper_module.MAX_SCRAPER_RETRIES
    
    scraper_module.INITIAL_BACKOFF_TIME = 0.05 # even shorter for this test
    scraper_module.MAX_BACKOFF_TIME = 0.1
    scraper_module.MAX_SCRAPER_RETRIES = 2

    try:
        with qtbot.waitSignal(scraper.finished, timeout=5000) as blocker_finished,              qtbot.waitSignal(scraper.error, timeout=5000) as blocker_error:
            scraper.start(layout_params=["1K"], known_links=set(), skip_cached=False)
        
        blocker_finished.wait()
        blocker_error.wait()
    finally:
        scraper_module.INITIAL_BACKOFF_TIME = original_initial_backoff
        scraper_module.MAX_BACKOFF_TIME = original_max_backoff
        scraper_module.MAX_SCRAPER_RETRIES = original_max_retries

    assert len(listings_received) == 0
    assert "Max retries exceeded" in error_message
    assert "500" in error_message
    assert requests_mock.call_count == 1 + 2 # Use the actual value set for the test (2)


# Test Case 8: Network error (e.g., Connection Timeout) handling
def test_scrape_network_error_then_gives_up(scraper_qtbot, requests_mock):
    scraper, qtbot = scraper_qtbot
    
    url_page1 = scraper._build_url(page=1)
    requests_mock.get(url_page1, exc=requests.exceptions.ConnectTimeout) # Simulate a connection timeout

    error_message = ""
    def handle_error(msg):
        nonlocal error_message
        error_message = msg
    
    scraper.error.connect(handle_error)
    listings_received = []
    scraper.new_listing.connect(listings_received.append)

    import scraper as scraper_module
    original_initial_backoff = scraper_module.INITIAL_BACKOFF_TIME
    original_max_backoff = scraper_module.MAX_BACKOFF_TIME
    original_max_retries = scraper_module.MAX_SCRAPER_RETRIES
    
    scraper_module.INITIAL_BACKOFF_TIME = 0.05
    scraper_module.MAX_BACKOFF_TIME = 0.1
    scraper_module.MAX_SCRAPER_RETRIES = 2

    try:
        with qtbot.waitSignal(scraper.finished, timeout=5000) as blocker_finished,              qtbot.waitSignal(scraper.error, timeout=5000) as blocker_error:
            scraper.start(layout_params=["1K"], known_links=set(), skip_cached=False)
        
        blocker_finished.wait()
        blocker_error.wait()
    finally:
        scraper_module.INITIAL_BACKOFF_TIME = original_initial_backoff
        scraper_module.MAX_BACKOFF_TIME = original_max_backoff
        scraper_module.MAX_SCRAPER_RETRIES = original_max_retries

    assert len(listings_received) == 0
    assert "Max retries exceeded" in error_message
    assert "ConnectTimeout" in error_message # Check for the exception type in the message
    assert requests_mock.call_count == 1 + 2 # Use the actual value set for the test (2)
