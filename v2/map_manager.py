import logging
import os
import re 
import folium
from folium.plugins import MarkerCluster
from PyQt5.QtCore import QObject, pyqtSlot, QUrl, pyqtSignal
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWidgets import QMessageBox

# import local station data
from station_data import STATION_COORDINATES 

class MapInteractor(QObject):
    request_show_details = pyqtSignal(str)
    def __init__(self): super().__init__()
    @pyqtSlot(str)
    def showListingDetailsByLink(self, listing_link_str):
        logging.debug(f"[MapInteractor] Request for link: {listing_link_str}")
        self.request_show_details.emit(listing_link_str)

class MapManager:
    def __init__(self, web_view_widget):
        self.web_view = web_view_widget
        self.interactor = MapInteractor()
        self.channel = None
        self._setup_webchannel()

    def _setup_webchannel(self):
        self.channel = QWebChannel(self.web_view.page())
        self.web_view.page().setWebChannel(self.channel)
        self.channel.registerObject("map_interactor_js", self.interactor)
        logging.info("QWebChannel and MapInteractor registered.")

    def render_map(self, listings_to_display): 
        if not listings_to_display:
            logging.info("No property listings to display, but will plot defined stations.")

        geocoded_listings = [l for l in listings_to_display if l.latitude is not None and l.longitude is not None]
        
        # determine map center
        if geocoded_listings:
            try:
                avg_lat = sum(l.latitude for l in geocoded_listings) / len(geocoded_listings)
                avg_lon = sum(l.longitude for l in geocoded_listings) / len(geocoded_listings)
                map_center = [avg_lat, avg_lon]
            except ZeroDivisionError:
                 map_center = [35.6895, 139.6917] # Tokyo
        else:
            if STATION_COORDINATES:
                first_station_coords = next(iter(STATION_COORDINATES.values()))
                map_center = [first_station_coords[0], first_station_coords[1]]
            else:
                map_center = [35.6895, 139.6917] # Tokyo
        
        try:
            m = folium.Map(location=map_center, zoom_start=11, tiles="CartoDB positron") 
            listing_marker_cluster = MarkerCluster(name="Properties").add_to(m)
            station_marker_group = folium.FeatureGroup(name="Train Stations").add_to(m)

            # --- Add Listing Markers (if any) ---
            if geocoded_listings:
                for listing in geocoded_listings:
                    escaped_link = listing.link.replace("'", "\\'").replace('"', '\\"')
                    popup_title = listing.title.replace("<", "<").replace(">", ">")
                    popup_html = (f"<b>{popup_title[:50]}{'...' if len(popup_title)>50 else ''}</b><br>"
                                  f"Rent: ¥{listing.middle_rent:,}/mo<br>"
                                  f"<a href='#' onclick='if(typeof showListingInApp === \"function\") {{ showListingInApp(\"{escaped_link}\"); }} else {{ alert(\"Map interaction not ready.\"); }} return false;'>Details</a>")
                    folium.Marker(location=[listing.latitude, listing.longitude], popup=folium.Popup(popup_html, max_width=250),
                                  tooltip=listing.title, icon=folium.Icon(color='blue', icon='home')
                    ).add_to(listing_marker_cluster)

            # Station Markers from station_data.py
            plotted_station_count = 0
            if not STATION_COORDINATES:
                logging.warning("STATION_COORDINATES dictionary is empty in station_data.py. No stations will be plotted.")
            else:
                logging.info(f"Plotting all {len(STATION_COORDINATES)} stations from station_data.py")
                for jp_name, (lat, lon, name_en) in STATION_COORDINATES.items():
                    if lat is not None and lon is not None and name_en: # data check
                        folium.Marker(
                            location=[lat, lon],
                            tooltip=f"Station: {name_en}",
                            icon=folium.Icon(color='green', icon='train', prefix='fa')
                        ).add_to(station_marker_group)
                        plotted_station_count += 1
                        logging.debug(f"Plotted station: {name_en} ({jp_name}) at {lat},{lon}")
                    else:
                        logging.warning(f"Skipping station '{jp_name}' due to missing data: lat={lat}, lon={lon}, name_en='{name_en}'")
            
            folium.LayerControl().add_to(m)

            map_html_content = m.get_root().render()
            js_injection = """
            <script type="text/javascript" src="qrc:///qtwebchannel/qwebchannel.js"></script>
            <script type="text/javascript">
                var map_interactor_js_obj = null;
                document.addEventListener('DOMContentLoaded', function() {
                    if (typeof QWebChannel === 'undefined') { console.error("QWebChannel.js not loaded."); return; }
                    initializeChannel();
                });
                function initializeChannel() {
                    if (typeof qt !== 'undefined' && qt.webChannelTransport) {
                        new QWebChannel(qt.webChannelTransport, function(channel) {
                            map_interactor_js_obj = channel.objects.map_interactor_js;
                            console.log(map_interactor_js_obj ? "map_interactor_js registered." : "map_interactor_js NOT FOUND.");
                        });
                    } else { console.error("qt.webChannelTransport not available."); }
                }
                window.showListingInApp = function(link) {
                    if (map_interactor_js_obj) {
                        try { map_interactor_js_obj.showListingDetailsByLink(link); }
                        catch (e) { console.error("Error calling Python slot: ", e); alert("Error communicating."); }
                    } else { alert("Map interaction features not ready."); console.error("map_interactor_js_obj missing."); }
                }
            </script>
            """
            if "</head>" in map_html_content: map_html_content = map_html_content.replace("</head>", js_injection + "</head>", 1)
            else: map_html_content += js_injection

            map_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map.html")
            with open(map_file_path, "w", encoding="utf-8") as f: f.write(map_html_content)
            self.web_view.setUrl(QUrl.fromLocalFile(map_file_path))
            logging.info(f"Map rendered with {len(geocoded_listings)} listings and {plotted_station_count} defined stations.")
            return len(geocoded_listings) 

        except Exception as e:
            logging.error(f"Error generating or displaying map: {e!r}", exc_info=True)
            parent_widget = self.web_view.parentWidget() if self.web_view else None
            QMessageBox.critical(parent_widget, "Map Error", f"Could not generate map: {e}")
            self.web_view.setHtml(f"<html><body><p>Error generating map: {e}</p></body></html>")
            return 0

    def cleanup_map_file(self):
         map_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map.html")
         if os.path.exists(map_file_path):
            try: os.remove(map_file_path); logging.info(f"Cleaned up map file: {map_file_path}")
            except OSError as e: logging.warning(f"Could not remove map file: {e}")

    def connect_show_details_signal(self, slot):
         try: self.interactor.request_show_details.connect(slot); logging.info("Connected MapInteractor signal.")
         except TypeError as e: logging.error(f"Failed to connect MapInteractor signal: {e}")