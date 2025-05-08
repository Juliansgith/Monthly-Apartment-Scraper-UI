import logging
from functools import partial
import webbrowser

from PyQt5.QtCore import Qt, pyqtSlot, QModelIndex, QPoint
from PyQt5.QtGui  import QPixmap, QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QMessageBox, QPushButton, QHBoxLayout, QSpinBox,
    QFileDialog, QSplitter, QScrollArea, QGroupBox, QFormLayout,
    QSizePolicy, QCheckBox, QComboBox, QTabWidget, QToolButton, QMenu, QListView,
    QAction
)
from PyQt5.QtWebEngineWidgets import QWebEngineView

from listing import Listing
from listing_model import ListingModel
from scraper import Scraper, LAYOUT_PARAM_MAP
from settings_manager import SettingsManager
from data_manager import DataManager
from map_manager import MapManager

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Monthly Mansion Scraper Deluxe")
        self.resize(1200, 800)

        self.settings_manager = SettingsManager()
        self.data_manager = DataManager()

        self.currently_displayed_listing = None
        self.current_photo_index = 0
        self.mainPhotoLabel = None
        self.photoNavWidget = None
        self.photosThumbScrollArea = None
        self.prevPhotoBtn = None
        self.nextPhotoBtn = None

        self.map_maximized = False 
        self.original_splitter_sizes = None 

        self._setup_ui()
        self.map_manager = MapManager(self.mapView)
        self.map_manager.connect_show_details_signal(self.display_listing_details_by_link)

        self.scraper = Scraper()
        self._connect_signals()
        self._update_models_and_stats()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        self.top_splitter = QSplitter(Qt.Horizontal) 

        self.left_pane_widget = QWidget() 
        left_pane_layout = QVBoxLayout(self.left_pane_widget)

        self.filters_gb = QGroupBox("Filters & Search") 
        filters_form = QFormLayout()
        self.minArea = QSpinBox(); self.minArea.setRange(0, 500); self.minArea.setValue(self.settings_manager.get_setting("min_area"))
        self.maxRent = QSpinBox(); self.maxRent.setRange(0,3_000_000); self.maxRent.setValue(self.settings_manager.get_setting("max_rent")); self.maxRent.setSingleStep(10_000)
        layout_checkboxes_widget = QWidget(); layout_cb_layout = QHBoxLayout(layout_checkboxes_widget); layout_cb_layout.setContentsMargins(0,0,0,0)
        self.layoutCheckboxes = []
        saved_layouts_state = self.settings_manager.get_setting("layouts_checked")
        for t_layout in LAYOUT_PARAM_MAP:
            cb = QCheckBox(t_layout); cb.setChecked(saved_layouts_state.get(t_layout, True))
            self.layoutCheckboxes.append(cb); layout_cb_layout.addWidget(cb)
        self.sortCombo = QComboBox(); self.sortCombo.addItems(["-- none --", "Price", "Area", "Price per m²", "Build Year", "Date Added"])
        self.sortCombo.setCurrentIndex(self.settings_manager.get_setting("sort_combo_idx"))
        self.sortDesc  = QCheckBox("Descending"); self.sortDesc.setChecked(self.settings_manager.get_setting("sort_desc"))
        self.searchBtn = QPushButton("Search")
        self.skipCachedCheckbox = QCheckBox("Only fetch new (skip cached in list)"); self.skipCachedCheckbox.setChecked(self.settings_manager.get_setting("skip_cached_search"))
        self.recheckDetailsCheckbox = QCheckBox("Re-check details for cached listings"); self.recheckDetailsCheckbox.setChecked(self.settings_manager.get_setting("recheck_details"))
        filters_form.addRow("Min Area (m²):", self.minArea); filters_form.addRow("Max Rent (¥):",  self.maxRent)
        filters_form.addRow("Layouts (for Search):", layout_checkboxes_widget); filters_form.addRow(self.skipCachedCheckbox)
        filters_form.addRow(self.recheckDetailsCheckbox); filters_form.addRow("Sort:", self.sortCombo)
        filters_form.addRow("", self.sortDesc); filters_form.addRow(self.searchBtn)
        self.filters_gb.setLayout(filters_form)
        left_pane_layout.addWidget(self.filters_gb)

        self.main_tabs = QTabWidget() 
        self.resultsListView = QListView(); self.resultsModel = ListingModel()
        self.resultsListView.setModel(self.resultsModel); self.resultsListView.setContextMenuPolicy(Qt.CustomContextMenu)
        self.favListView = QListView(); self.favModel = ListingModel()
        self.favListView.setModel(self.favModel); self.favListView.setContextMenuPolicy(Qt.CustomContextMenu)

        self.mapViewWidget = QWidget()
        map_widget_layout = QVBoxLayout(self.mapViewWidget) 
        
        map_controls_layout = QHBoxLayout() 
        self.refreshMapBtn = QPushButton("Show/Refresh Filtered on Map")
        self.toggleMaximizeMapBtn = QPushButton("Maximize Map") 
        map_controls_layout.addWidget(self.refreshMapBtn)
        map_controls_layout.addWidget(self.toggleMaximizeMapBtn)
        map_controls_layout.addStretch()
        map_widget_layout.addLayout(map_controls_layout) 

        self.mapView = QWebEngineView()
        map_widget_layout.addWidget(self.mapView) 

        resTab = QWidget(); resL = QVBoxLayout(resTab); resL.addWidget(self.resultsListView)
        favTab = QWidget(); favL = QVBoxLayout(favTab); favL.addWidget(self.favListView)
        self.main_tabs.addTab(resTab,"Results"); self.main_tabs.addTab(favTab,"Favourites"); self.main_tabs.addTab(self.mapViewWidget, "Map View")
        left_pane_layout.addWidget(self.main_tabs) 

        self.stats_gb = QGroupBox("Statistics") 
        stats_layout = QVBoxLayout(self.stats_gb)
        self.statsLabel = QLabel("Statistics will appear here."); self.statsLabel.setWordWrap(True)
        stats_layout.addWidget(self.statsLabel)
        left_pane_layout.addWidget(self.stats_gb)

        self.maint_gb = QGroupBox("Maintenance") 
        maint_layout = QFormLayout(self.maint_gb)
        self.clearListingsCacheBtn = QPushButton("Clear Listings Cache")
        self.clearAppSettingsBtn = QPushButton("Clear App Settings")
        self.refreshAllDetailsBtn = QPushButton("Refresh All Details")
        maint_layout.addRow(self.clearListingsCacheBtn); maint_layout.addRow(self.clearAppSettingsBtn)
        maint_layout.addRow(self.refreshAllDetailsBtn)
        left_pane_layout.addWidget(self.maint_gb)

        self.top_splitter.addWidget(self.left_pane_widget)

        self.detailArea   = QScrollArea(); self.detailWidget = QWidget()
        self.detailLayout = QVBoxLayout(self.detailWidget)
        self.detailArea.setWidgetResizable(True); self.detailArea.setWidget(self.detailWidget)
        self.top_splitter.addWidget(self.detailArea)
        self.original_splitter_sizes = [450, 750] 
        self.top_splitter.setSizes(self.original_splitter_sizes)
        main_layout.addWidget(self.top_splitter)

        bottom_bar_layout = QHBoxLayout()
        self.statusLabel  = QLabel("Idle. Load cache or start a new search.")
        self.stopBtn = QPushButton("Stop Scraper"); self.stopBtn.setEnabled(False)
        self.starBtn = QToolButton(); self.starBtn.setText("✩"); self.starBtn.setToolTip("Toggle favourite"); self.starBtn.setEnabled(False)
        export_menu_btn = QPushButton("Export...")
        self.export_menu = QMenu(self)
        self.exportFilteredCsvAction = self.export_menu.addAction("Export Filtered to CSV")
        self.exportFilteredJsonAction = self.export_menu.addAction("Export Filtered to JSON")
        self.exportFavCsvAction = self.export_menu.addAction("Export Favourites to CSV")
        self.exportFavJsonAction = self.export_menu.addAction("Export Favourites to JSON")
        self.exportSelectedCsvAction = self.export_menu.addAction("Export Selected to CSV")
        self.exportSelectedJsonAction = self.export_menu.addAction("Export Selected to JSON")
        export_menu_btn.setMenu(self.export_menu)
        bottom_bar_layout.addWidget(self.statusLabel); bottom_bar_layout.addStretch()
        bottom_bar_layout.addWidget(export_menu_btn)
        bottom_bar_layout.addWidget(self.starBtn); bottom_bar_layout.addWidget(self.stopBtn)
        main_layout.addLayout(bottom_bar_layout)

        self.toggleMaximizeMapBtn.setEnabled(self.main_tabs.currentWidget() == self.mapViewWidget)


    def _connect_signals(self):
        self.minArea.valueChanged.connect(self._update_models_and_stats)
        self.maxRent.valueChanged.connect(self._update_models_and_stats)
        self.sortCombo.currentIndexChanged.connect(self._update_models_and_stats)
        self.sortDesc.stateChanged.connect(self._update_models_and_stats)
        self.searchBtn.clicked.connect(self.start_scraping)
        self.stopBtn.clicked.connect(self.scraper.stop)
        self.scraper.new_listing.connect(self.handle_new_listing_scraped)
        self.scraper.finished.connect(self.on_scraper_finished)
        self.scraper.error.connect(self.on_scraper_error)
        self.scraper.progress.connect(self.update_status_label)
        self.data_manager.listing_details_fetched.connect(self.on_listing_details_fetched)
        self.data_manager.listings_updated.connect(self._update_models_and_stats)
        self.data_manager.fetch_status_update.connect(self.update_status_label)
        self.resultsListView.clicked.connect(self.on_results_list_item_clicked)
        self.favListView.clicked.connect(self.on_fav_list_item_clicked)
        self.resultsListView.customContextMenuRequested.connect(self.show_list_context_menu)
        self.favListView.customContextMenuRequested.connect(self.show_list_context_menu)
        self.starBtn.clicked.connect(self.toggle_favourite)
        self.clearListingsCacheBtn.clicked.connect(self._ui_clear_listings_cache)
        self.clearAppSettingsBtn.clicked.connect(self._ui_clear_app_settings)
        self.refreshAllDetailsBtn.clicked.connect(self._ui_refresh_all_details) # Connect new button
        self.exportFilteredCsvAction.triggered.connect(lambda: self.export_data('csv', 'filtered'))
        self.exportFilteredJsonAction.triggered.connect(lambda: self.export_data('json', 'filtered'))
        self.exportFavCsvAction.triggered.connect(lambda: self.export_data('csv', 'favourites'))
        self.exportFavJsonAction.triggered.connect(lambda: self.export_data('json', 'favourites'))
        self.exportSelectedCsvAction.triggered.connect(lambda: self.export_data('csv', 'selected'))
        self.exportSelectedJsonAction.triggered.connect(lambda: self.export_data('json', 'selected'))
        self.refreshMapBtn.clicked.connect(self._render_map_view_action)
        self.toggleMaximizeMapBtn.clicked.connect(self._toggle_maximize_map)
        self.main_tabs.currentChanged.connect(self._on_main_tab_changed) 

    def _on_main_tab_changed(self, index):
        """Enable/disable map maximize button based on current tab."""
        is_map_tab_current = (self.main_tabs.widget(index) == self.mapViewWidget)
        self.toggleMaximizeMapBtn.setEnabled(is_map_tab_current)
        if not is_map_tab_current and self.map_maximized:
            self._toggle_maximize_map() # restore fucntion

    def _toggle_maximize_map(self):
        if not self.map_maximized: 
            self.widgets_to_hide_for_map = [self.filters_gb, self.stats_gb, self.maint_gb]
            for i in range(self.left_pane_widget.layout().count()):
                item = self.left_pane_widget.layout().itemAt(i)
                widget = item.widget()
                if widget and widget != self.main_tabs: 
                    widget.setVisible(False)
            
            
            for i in range(self.main_tabs.count()):
                if self.main_tabs.widget(i) != self.mapViewWidget:
                    self.main_tabs.setTabVisible(i, False)
            
            self.main_tabs.setCurrentWidget(self.mapViewWidget) 

            if self.original_splitter_sizes is None:
                 self.original_splitter_sizes = self.top_splitter.sizes()

            self.top_splitter.setSizes([1, 999]) 
            self.toggleMaximizeMapBtn.setText("Restore View")
            self.map_maximized = True
            logging.debug("Map Maximized")
        else: 
            for i in range(self.left_pane_widget.layout().count()):
                item = self.left_pane_widget.layout().itemAt(i)
                widget = item.widget()
                if widget and widget != self.main_tabs:
                    widget.setVisible(True)
            for i in range(self.main_tabs.count()):
                 self.main_tabs.setTabVisible(i, True)
            if self.original_splitter_sizes:
                self.top_splitter.setSizes(self.original_splitter_sizes)
            else: # fallback
                self.top_splitter.setSizes([450,750])
            self.toggleMaximizeMapBtn.setText("Maximize Map")
            self.map_maximized = False
            logging.debug("Map Restored")

    def start_scraping(self):
        logging.info("Initiating new scrape.")
        if not self.skipCachedCheckbox.isChecked():
            if QMessageBox.question(self, "Confirm", "Clear existing listings and cache?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.No: return
            self.data_manager.clear_cache_file_and_memory()
        self.clear_detail_pane(); self.starBtn.setEnabled(False)
        selected_layouts = [cb.text() for cb in self.layoutCheckboxes if cb.isChecked()]
        if not selected_layouts: QMessageBox.warning(self, "Input Error", "Select at least one layout."); return
        known_links = self.data_manager.get_known_links()
        skip_cached = self.skipCachedCheckbox.isChecked()
        self.data_manager.clear_detail_fetch_stop()
        logging.debug(f"Start scraper: Layouts={selected_layouts}, SkipCached={skip_cached}")
        self.statusLabel.setText("Starting search…"); self.stopBtn.setEnabled(True); self.searchBtn.setEnabled(False)
        self.scraper.start(selected_layouts, known_links, skip_cached)

    @pyqtSlot(Listing)
    def handle_new_listing_scraped(self, basic_listing):
        recheck = self.recheckDetailsCheckbox.isChecked()
        self.data_manager.add_or_update_listing(basic_listing, recheck)

    @pyqtSlot()
    def on_scraper_finished(self):
        logging.info("Scraper finished.")
        self.statusLabel.setText(f"Search finished. {len(self.data_manager.get_all_listings())} total known.")
        self.stopBtn.setEnabled(False); self.searchBtn.setEnabled(True)
        self._update_models_and_stats()

    @pyqtSlot(str)
    def on_scraper_error(self, error_msg):
        logging.error(f"Scraper error: {error_msg}")
        QMessageBox.critical(self, "Scraper Error", error_msg)
        self.statusLabel.setText(f"Scraper failed: {error_msg}")
        self.stopBtn.setEnabled(False); self.searchBtn.setEnabled(True)

    @pyqtSlot(Listing)
    def on_listing_details_fetched(self, listing):
        if self.currently_displayed_listing and self.currently_displayed_listing.link == listing.link:
            if self.detailLayout: self.render_detail_pane(listing)
            else: logging.warning("Detail layout None during detail fetch update.")
        self.resultsModel.dataChangedForItem(listing)
        self.favModel.dataChangedForItem(listing)

    @pyqtSlot()
    def _update_models_and_stats(self):
        min_area = self.minArea.value(); max_rent = self.maxRent.value()
        sort_key = self.sortCombo.currentText(); sort_desc = self.sortDesc.isChecked()
        filtered = self.data_manager.get_filtered_listings(min_area, max_rent, sort_key, sort_desc)
        favs = self.data_manager.get_favourites()
        self.resultsModel.update_listings(filtered); self.favModel.update_listings(favs)
        stats = self.data_manager.calculate_statistics(filtered); self._display_statistics(stats)

    def _display_statistics(self, stats):
        layout_summary = ", ".join([f"{k}: {v}" for k, v in sorted(stats["layout_counts"].items())]) or "N/A"
        stats_text = (f"<b>Total Known:</b> {stats['total_scraped']}<br><b>Displayed:</b> {stats['displayed_count']}<br><b>Favourites:</b> {stats['fav_count']}<br>"
                      f"<b>Avg Rent (Disp):</b> {stats['avg_rent']}<br><b>Avg Area (Disp):</b> {stats['avg_area']}<br><b>Layouts (Disp):</b> {layout_summary}")
        self.statsLabel.setText(stats_text)

    @pyqtSlot(QModelIndex)
    def on_results_list_item_clicked(self, index):
        filtered_list = self.resultsModel.listings_ref
        if 0 <= index.row() < len(filtered_list): self.render_detail_pane(filtered_list[index.row()])

    @pyqtSlot(QModelIndex)
    def on_fav_list_item_clicked(self, index):
        fav_list = self.favModel.listings_ref
        if 0 <= index.row() < len(fav_list): self.render_detail_pane(fav_list[index.row()])

    @pyqtSlot()
    def toggle_favourite(self):
        if not self.currently_displayed_listing: return
        link = self.currently_displayed_listing.link
        if self.data_manager.toggle_favourite(link):
            listing = self.data_manager.get_listing_by_link(link)
            if listing: self.starBtn.setText("⭐" if listing.is_fav else "✩")

    @pyqtSlot(QPoint)
    def show_list_context_menu(self, point):
        sender_list_view = self.sender()
        if not isinstance(sender_list_view, QListView): return
        index = sender_list_view.indexAt(point)
        if not index.isValid(): return
        model = sender_list_view.model()
        if not isinstance(model, ListingModel): return
        try: listing = model.listings_ref[index.row()]
        except IndexError: return
        context_menu = QMenu(self)
        retry_action = QAction("Retry Detail Fetch", self)
        retry_action.setEnabled(listing.fetch_status != "Details OK")
        retry_action.triggered.connect(lambda: self.handle_retry_fetch_action(listing.link))
        context_menu.addAction(retry_action)
        mark_viewed_action = QAction("Mark as Viewed" if not listing.is_viewed else "Mark as Unviewed", self)
        mark_viewed_action.triggered.connect(lambda: self.handle_mark_viewed_action(listing))
        context_menu.addAction(mark_viewed_action)
        context_menu.exec_(sender_list_view.viewport().mapToGlobal(point))

    def handle_retry_fetch_action(self, listing_link):
        logging.info(f"Context menu: Retry fetch for {listing_link}")
        if self.data_manager.trigger_single_detail_fetch(listing_link): self.statusLabel.setText(f"Retrying details for {listing_link}...")
        else: QMessageBox.warning(self, "Retry Failed", "Could not find listing.")

    def handle_mark_viewed_action(self, listing):
        listing.is_viewed = not listing.is_viewed
        logging.info(f"Context menu: Marked {listing.link} as viewed={listing.is_viewed}")
        self.resultsModel.dataChangedForItem(listing); self.favModel.dataChangedForItem(listing)

    @pyqtSlot()
    def _ui_clear_listings_cache(self):
        if QMessageBox.question(self, "Confirm", "Delete cache file AND clear memory?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            if self.data_manager.clear_cache_file_and_memory(): QMessageBox.information(self, "Cache Cleared", "Cache file deleted and memory cleared.")
            else: QMessageBox.warning(self, "Cache Clear Error", "Could not delete cache file (memory cleared).")
            self.clear_detail_pane(); self.statusLabel.setText("Cache cleared.")

    @pyqtSlot()
    def _ui_clear_app_settings(self):
        if QMessageBox.question(self, "Confirm", "Delete settings file?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            if self.settings_manager.clear_settings_file():
                 QMessageBox.information(self, "Settings Cleared", "Settings file deleted. Defaults used on next launch. Restart suggested.")
                 self._reset_ui_to_defaults()
            else: QMessageBox.warning(self, "Settings Error", "Could not delete settings file.")
            self.statusLabel.setText("Settings cleared.")

    @pyqtSlot()
    def _ui_refresh_all_details(self):
        num_listings = len(self.data_manager.get_all_listings())
        if num_listings == 0: QMessageBox.information(self, "Refresh All", "No listings to refresh."); return
        reply = QMessageBox.question(self, "Confirm Refresh All", f"Refresh details for all {num_listings} listings?\n(May take time & network resources)", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.statusLabel.setText(f"Queueing {num_listings} for detail refresh..."); QApplication.processEvents()
            self.data_manager.trigger_refresh_all_details()
            self.statusLabel.setText(f"Queued {num_listings} listings. Check logs/status.")

    def _reset_ui_to_defaults(self):
        defaults = self.settings_manager.settings
        self.minArea.setValue(defaults.get("min_area", 0))
        self.maxRent.setValue(defaults.get("max_rent", 250000))
        default_layouts = defaults.get("layouts_checked", {})
        for cb in self.layoutCheckboxes: cb.setChecked(default_layouts.get(cb.text(), True))
        self.sortCombo.setCurrentIndex(defaults.get("sort_combo_idx", 0))
        self.sortDesc.setChecked(defaults.get("sort_desc", False))
        self.skipCachedCheckbox.setChecked(defaults.get("skip_cached_search", False))
        self.recheckDetailsCheckbox.setChecked(defaults.get("recheck_details", False))

    def clear_detail_pane(self):
        while self.detailLayout.count() > 0:
            item = self.detailLayout.takeAt(self.detailLayout.count() - 1)
            widget = item.widget(); layout_item = item.layout()
            if widget: widget.deleteLater()
            elif layout_item:
                while layout_item.count() > 0:
                    sub_item = layout_item.takeAt(layout_item.count() - 1)
                    sub_widget = sub_item.widget()
                    if sub_widget: sub_widget.deleteLater()
        self.mainPhotoLabel=None; self.photoNavWidget=None; self.photosThumbScrollArea=None; self.prevPhotoBtn=None; self.nextPhotoBtn=None
        self.currently_displayed_listing=None; self.current_photo_index=0
        if hasattr(self, 'starBtn') and self.starBtn: self.starBtn.setEnabled(False); self.starBtn.setText("✩")

    def render_detail_pane(self, listing):
        self.clear_detail_pane();
        if not listing: return
        self.currently_displayed_listing = listing; self.current_photo_index = 0
        if not listing.is_viewed: listing.is_viewed = True; self.resultsModel.dataChangedForItem(listing); self.favModel.dataChangedForItem(listing)

        title_label = QLabel(f"<h2>{listing.title}</h2>"); self.detailLayout.addWidget(title_label)
        info_parts = [ f"<b>Address:</b> {listing.address}" + (f" (Lat: {listing.latitude:.4f}, Lon: {listing.longitude:.4f})" if listing.latitude is not None else ""),
                       f"<b>Stations:</b> {listing.stations}", f"<b>Area:</b> {listing.area:.1f} m²", f"<b>Layout:</b> {listing.layout}",
                       f"<b>Build:</b> {listing.build}" + (f" ({listing.build_year})" if listing.build_year else ""),
                       f"<b>Rent:</b> ¥{listing.middle_rent:,}/mo ({listing.ppm2:.1f}/m²)", f"<b>Utilities:</b> {listing.utilities}",
                       f"<b>Cleaning:</b> {listing.cleaning}", f"<b>Pay Methods:</b> {listing.pay_methods}"]
        if listing.details_fetched: info_parts.extend([f"<b>Appliances:</b> {'; '.join(listing.appliances) if listing.appliances else 'N/A'}", f"<b>Remarks:</b><br>{listing.remarks.replace(chr(10), '<br>') if listing.remarks else 'N/A'}"])
        elif listing.fetch_status == "Pending Details": info_parts.append("<i>Detailed information is being fetched...</i>")
        elif "Error" in listing.fetch_status: info_parts.append(f"<i style='color:red;'>Error fetching details: {listing.detail_fetch_error_message}</i>")
        info_parts.append(f"<b>Link:</b> <a href='{listing.link}'>{listing.link}</a>")
        info_label = QLabel("<br>".join(info_parts)); info_label.setWordWrap(True); info_label.setOpenExternalLinks(True); info_label.setTextInteractionFlags(Qt.TextBrowserInteraction); self.detailLayout.addWidget(info_label)

        photo_data_list = self.data_manager.get_photo_data(listing)
        if photo_data_list:
            self.mainPhotoLabel = QLabel(); self.mainPhotoLabel.setAlignment(Qt.AlignCenter); self.mainPhotoLabel.setMinimumHeight(200); self.detailLayout.addWidget(self.mainPhotoLabel)
            photo_nav_layout = QHBoxLayout(); self.prevPhotoBtn = QToolButton(); self.prevPhotoBtn.setText("◀ Prev"); self.nextPhotoBtn = QToolButton(); self.nextPhotoBtn.setText("Next ▶"); self.prevPhotoBtn.clicked.connect(self._show_prev_photo); self.nextPhotoBtn.clicked.connect(self.show_next_photo); photo_nav_layout.addStretch(); photo_nav_layout.addWidget(self.prevPhotoBtn); photo_nav_layout.addWidget(self.nextPhotoBtn); photo_nav_layout.addStretch(); self.photoNavWidget = QWidget(); self.photoNavWidget.setLayout(photo_nav_layout); self.detailLayout.addWidget(self.photoNavWidget)
            self.photosThumbScrollArea = QScrollArea(); thumb_widget = QWidget(); thumb_layout = QHBoxLayout(thumb_widget); thumb_layout.setContentsMargins(5,5,5,5); self._current_listing_pixmaps = []
            for i, data in enumerate(photo_data_list):
                pixmap = None
                if data: pix = QPixmap(); pix.loadFromData(data); pixmap = pix if not pix.isNull() else None
                self._current_listing_pixmaps.append(pixmap)
                if pixmap:
                    thumb_pix = pixmap.scaledToHeight(80, Qt.SmoothTransformation); thumb_label = QLabel(); thumb_label.setPixmap(thumb_pix); thumb_label.setFixedSize(thumb_pix.width(), thumb_pix.height()); thumb_label.setCursor(Qt.PointingHandCursor); thumb_label.setStyleSheet("QLabel { border: 1px solid lightgrey; } QLabel:hover { border: 1px solid blue; }"); thumb_label.mousePressEvent = partial(self._show_photo_by_index, i); thumb_layout.addWidget(thumb_label)
                else: placeholder_label = QLabel(f"Img {i+1}\n(Error)"); placeholder_label.setFixedSize(80, 80); placeholder_label.setAlignment(Qt.AlignCenter); placeholder_label.setStyleSheet("border: 1px dashed grey; color: grey;"); thumb_layout.addWidget(placeholder_label)
            thumb_widget.adjustSize(); self.photosThumbScrollArea.setWidget(thumb_widget); self.photosThumbScrollArea.setWidgetResizable(True); self.photosThumbScrollArea.setFixedHeight(thumb_widget.sizeHint().height() + self.photosThumbScrollArea.horizontalScrollBar().sizeHint().height() + 10); self.detailLayout.addWidget(self.photosThumbScrollArea)
            self._display_current_photo()
        elif listing.details_fetched and not listing.photo_urls: self.detailLayout.addWidget(QLabel("<i>No photos available.</i>"))
        elif listing.fetch_status == "Pending Details": self.detailLayout.addWidget(QLabel("<i>Photos loading...</i>"))
        elif "Error" in listing.fetch_status: self.detailLayout.addWidget(QLabel(f"<i style='color:red;'>Could not load photos: {listing.detail_fetch_error_message}</i>"))

        self.detailLayout.addStretch(); self.starBtn.setEnabled(True); self.starBtn.setText("⭐" if listing.is_fav else "✩")

    def _display_current_photo(self):
        if not hasattr(self, 'mainPhotoLabel') or not self.mainPhotoLabel: return
        if not self.currently_displayed_listing or not hasattr(self, '_current_listing_pixmaps') or not self._current_listing_pixmaps:
            self.mainPhotoLabel.clear();
            if hasattr(self,'prevPhotoBtn') and self.prevPhotoBtn: self.prevPhotoBtn.setEnabled(False)
            if hasattr(self,'nextPhotoBtn') and self.nextPhotoBtn: self.nextPhotoBtn.setEnabled(False)
            return
        num_photos = len(self._current_listing_pixmaps)
        if not (0 <= self.current_photo_index < num_photos):
            self.mainPhotoLabel.clear();
            if hasattr(self,'prevPhotoBtn') and self.prevPhotoBtn: self.prevPhotoBtn.setEnabled(False)
            if hasattr(self,'nextPhotoBtn') and self.nextPhotoBtn: self.nextPhotoBtn.setEnabled(False)
            return
        pix = self._current_listing_pixmaps[self.current_photo_index]
        if pix and not pix.isNull():
            detail_area_width = self.detailArea.viewport().width() if self.detailArea else 400
            scaled_pix = pix.scaledToWidth(max(detail_area_width - 40, 100), Qt.SmoothTransformation); self.mainPhotoLabel.setPixmap(scaled_pix)
        else: self.mainPhotoLabel.setText("Error loading image")
        if hasattr(self,'prevPhotoBtn') and self.prevPhotoBtn: self.prevPhotoBtn.setEnabled(self.current_photo_index > 0)
        if hasattr(self,'nextPhotoBtn') and self.nextPhotoBtn: self.nextPhotoBtn.setEnabled(self.current_photo_index < num_photos - 1)

    def _show_photo_by_index(self, index, event=None):
        if not self.currently_displayed_listing or not hasattr(self, '_current_listing_pixmaps'): return
        if 0 <= index < len(self._current_listing_pixmaps): self.current_photo_index = index; self._display_current_photo()

    def _show_prev_photo(self):
        if not self.currently_displayed_listing or not hasattr(self, '_current_listing_pixmaps') or self.current_photo_index <= 0: return
        self.current_photo_index -= 1; self._display_current_photo()

    def show_next_photo(self):
        if not self.currently_displayed_listing or not hasattr(self, '_current_listing_pixmaps'): return
        if self.current_photo_index < len(self._current_listing_pixmaps) - 1: self.current_photo_index += 1; self._display_current_photo()

    @pyqtSlot()
    def _render_map_view_action(self):
        count = self.map_manager.render_map(self.resultsModel.listings_ref)
        if count > 0: self.statusLabel.setText(f"Map updated with {count} listings.")

    @pyqtSlot(str)
    def display_listing_details_by_link(self, link_str):
        logging.info(f"Attempting to display details for link from map: {link_str}")
        listing_to_display = self.data_manager.get_listing_by_link(link_str)
        if listing_to_display: self.render_detail_pane(listing_to_display); self.detailArea.ensureVisible(0, 0)
        else: logging.warning(f"Map link not found: {link_str}"); QMessageBox.warning(self, "Not Found", f"Could not find listing: {link_str}")

    def get_selected_listings(self):
        selected_listings = []; active_list_view = None; active_model_source = None
        current_tab_widget = self.main_tabs.currentWidget(); list_views_in_tab = current_tab_widget.findChildren(QListView)
        if list_views_in_tab:
            active_list_view = list_views_in_tab[0]
            if active_list_view == self.resultsListView: active_model_source = self.resultsModel.listings_ref
            elif active_list_view == self.favListView: active_model_source = self.favModel.listings_ref
        if active_list_view and active_model_source is not None:
            selected_indexes = active_list_view.selectedIndexes(); added_links = set()
            for index in selected_indexes:
                if 0 <= index.row() < len(active_model_source):
                    list_obj = active_model_source[index.row()]
                    if list_obj.link not in added_links: selected_listings.append(list_obj); added_links.add(list_obj.link)
        return selected_listings

    def export_data(self, file_format, export_type):
        listings_to_export = []; default_filename = "listings"
        if export_type == 'filtered': listings_to_export = self.resultsModel.listings_ref; default_filename = "filtered_listings"
        elif export_type == 'favourites': listings_to_export = self.favModel.listings_ref; default_filename = "favourite_listings"
        elif export_type == 'selected':
            listings_to_export = self.get_selected_listings(); default_filename = "selected_listings"
            if not listings_to_export: QMessageBox.information(self, f"Export {file_format.upper()}", "No listings selected."); return
        if not listings_to_export and export_type != 'selected': QMessageBox.information(self, f"Export {file_format.upper()}", f"No {export_type} listings."); return
        file_dialog_filter = "CSV Files (*.csv)" if file_format == 'csv' else "JSON Files (*.json)"
        path, _ = QFileDialog.getSaveFileName(self, f"Save {export_type.capitalize()} {file_format.upper()}", f"{default_filename}.{file_format}", file_dialog_filter)
        if not path: return
        try:
            if file_format == 'csv':
                with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f); writer.writerow(["Favourite","Title","Link","Address","Latitude","Longitude","Stations","Area_m2","Layout","Build","BuildYear","DateAdded","PayMethods","Rent_JPY","Price_per_m2","Utilities","Cleaning","Appliances","Remarks","PhotoURLs", "FetchStatus", "FetchError","IsViewed"])
                    for l_obj in listings_to_export:
                        writer.writerow(["Yes" if l_obj.is_fav else "No", l_obj.title, l_obj.link, l_obj.address, l_obj.latitude, l_obj.longitude, l_obj.stations, f"{l_obj.area:.2f}", l_obj.layout, l_obj.build, l_obj.build_year, l_obj.date_added.isoformat() if l_obj.date_added else "", l_obj.pay_methods, l_obj.middle_rent, f"{l_obj.ppm2:.1f}", l_obj.utilities, l_obj.cleaning, ";".join(l_obj.appliances), l_obj.remarks, ";".join(l_obj.photo_urls), l_obj.fetch_status, l_obj.detail_fetch_error_message, "Yes" if l_obj.is_viewed else "No"])
            elif file_format == 'json':
                data_dicts = [l_obj.to_dict() for l_obj in listings_to_export];
                with open(path, 'w', encoding='utf-8') as f: json.dump(data_dicts, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, f"Export {file_format.upper()}", f"Exported {len(listings_to_export)} listings to:\n{path}")
        except Exception as e: QMessageBox.critical(self, "Export Error", f"Could not export {file_format.upper()}: {e}"); logging.error(f"{file_format.upper()} Export failed: {e!r}")

    def save_current_settings(self):
        current_settings = { "min_area": self.minArea.value(), "max_rent": self.maxRent.value(), "layouts_checked": {cb.text(): cb.isChecked() for cb in self.layoutCheckboxes}, "sort_combo_idx": self.sortCombo.currentIndex(), "sort_desc": self.sortDesc.isChecked(), "skip_cached_search": self.skipCachedCheckbox.isChecked(), "recheck_details": self.recheckDetailsCheckbox.isChecked()}
        self.settings_manager.save_settings(current_settings)

    def closeEvent(self, event):
        logging.info("Close event triggered.")
        self.scraper.stop(); self.data_manager.stop_detail_fetching()
        self.save_current_settings(); self.data_manager.save_listings_cache()
        if hasattr(self, 'map_manager') and self.map_manager: self.map_manager.cleanup_map_file()
        logging.info("Shutdown routines complete.")
        event.accept()

    @pyqtSlot(str)
    def update_status_label(self, message):
        if hasattr(self, 'statusLabel') and self.statusLabel: self.statusLabel.setText(message)
        else: logging.warning("Status label update attempted but label missing.")