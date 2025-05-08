import logging
import re
from datetime import datetime 

class Listing:
    """Represents a single property listing."""
    def __init__(self, title, link, address, stations, area, layout, build,
                 pay_methods, middle_rent, utilities, cleaning,
                 appliances=None, remarks=None, photo_urls=None): 

        self.title        = title
        self.link         = link
        self.address      = address
        self.stations     = stations
        self.area         = float(area) if area else 0.0
        self.layout       = layout
        self.build        = build 
        self.pay_methods  = pay_methods
        try:
            self.middle_rent = int(middle_rent) if middle_rent is not None else 0
        except (ValueError, TypeError):
             logging.warning(f"Could not convert middle_rent '{middle_rent}' to int for {link}. Setting to 0.")
             self.middle_rent = 0

        self.utilities    = utilities
        self.cleaning     = cleaning
        self.appliances   = appliances if appliances is not None else []
        self.remarks      = remarks if remarks is not None else ""
        self.photo_urls   = photo_urls if photo_urls is not None else []

        self.ppm2         = (self.middle_rent / self.area) if self.area > 0 else 0
        self.is_fav       = False
        self.is_viewed    = False 

        self.details_fetched = False
        self.fetch_status = "Pending Details"
        self.detail_fetch_error_message = ""
        self.latitude = None
        self.longitude = None


        self.build_year = self._parse_build_year(build)
        self.date_added = datetime.now() 

    #find build year
    def _parse_build_year(self, build_str):
        """Attempts to parse the year from the Japanese build date string."""
        if not build_str:
            return None
        match = re.search(r'(\d{4})年', build_str)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    def __str__(self):
        fav_marker = "⭐ " if self.is_fav else ""
        status_marker = ""
        if self.fetch_status == "Pending Details": status_marker = "[P] "
        elif self.fetch_status == "Detail Fetch Error": status_marker = "[E!] "
        elif self.fetch_status == "Detail Parse Error": status_marker = "[Ep] "
        rent_str = f"¥{self.middle_rent:,}/mo" if self.middle_rent is not None else "N/A"
        area_str = f"{self.area:.1f}m²" if self.area is not None else "N/A"
        prefix = f"{status_marker}{fav_marker}"
        return f"{prefix}{self.title} — {area_str} — {rent_str}"

    def to_dict(self):
        return {
            "title": self.title, "link": self.link, "address": self.address,
            "stations": self.stations, "area": float(self.area) if self.area is not None else None,
            "layout": self.layout, "build": self.build, 
            "build_year": self.build_year, 
            "date_added": self.date_added.isoformat() if self.date_added else None, 
            "pay_methods": self.pay_methods,
            "middle_rent": int(self.middle_rent) if self.middle_rent is not None else None,
            "utilities": self.utilities, "cleaning": self.cleaning,
            "appliances": self.appliances, "remarks": self.remarks,
            "photo_urls": self.photo_urls, 
            "ppm2": float(self.ppm2) if self.ppm2 is not None else None,
            "is_fav": self.is_fav,
            "is_viewed": self.is_viewed, 
            "details_fetched": self.details_fetched,
            "fetch_status": self.fetch_status,
            "detail_fetch_error_message": self.detail_fetch_error_message,
            "latitude": float(self.latitude) if self.latitude is not None else None,
            "longitude": float(self.longitude) if self.longitude is not None else None,
        }

    @staticmethod
    def from_dict(d):
        try:
            build_str = d.get("build", "")
            l = Listing(
                d.get("title", "N/A"), d.get("link", ""), d.get("address", ""),
                d.get("stations", ""), d.get("area", 0.0), d.get("layout", ""),
                build_str, d.get("pay_methods", ""), d.get("middle_rent", 0),
                d.get("utilities", ""), d.get("cleaning", ""), d.get("appliances",[]),
                d.get("remarks",""), d.get("photo_urls",[])
            )
            l.ppm2   = d.get("ppm2", l.ppm2)
            l.is_fav = d.get("is_fav", False)
            l.is_viewed = d.get("is_viewed", False) 
            l.details_fetched = d.get("details_fetched", False)
            l.fetch_status = d.get("fetch_status", "Pending Details" if not l.details_fetched else "Details OK")
            l.detail_fetch_error_message = d.get("detail_fetch_error_message", "")
            l.latitude = d.get("latitude")
            l.longitude = d.get("longitude")
            l.build_year = d.get("build_year", l._parse_build_year(build_str)) 
            date_added_iso = d.get("date_added")
            if date_added_iso:
                 try:
                      l.date_added = datetime.fromisoformat(date_added_iso)
                 except (ValueError, TypeError):
                      logging.warning(f"Could not parse date_added '{date_added_iso}' for {l.link}. Using current time.")
                      l.date_added = datetime.now()
            else:
                 l.date_added = datetime.now() 

            return l
        except Exception as e:
             logging.error(f"Error creating Listing from dict for link {d.get('link', 'UNKNOWN')}: {e}", exc_info=True)
             return None