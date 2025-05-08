from PyQt5.QtCore import QAbstractListModel, QModelIndex, Qt
from PyQt5.QtGui import QColor
from listing import Listing

class ListingModel(QAbstractListModel):
    def __init__(self, listings_ref=None):
        super().__init__()
        self.listings_ref = listings_ref if listings_ref is not None else []

    def rowCount(self, parent=QModelIndex()):
        return len(self.listings_ref)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.listings_ref)):
            return None
        listing = self.listings_ref[index.row()]

        if role == Qt.DisplayRole:
            return str(listing)

        elif role == Qt.ForegroundRole:
            if listing.is_viewed:
                return QColor(Qt.gray) 

        return None

    def update_listings(self, new_listings_ref):
        self.beginResetModel()
        self.listings_ref = new_listings_ref
        self.endResetModel()

    def dataChangedForItem(self, listing):
        """Find the index for the listing and emit dataChanged."""
        try:
            row = self.listings_ref.index(listing)
            index = self.index(row)
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.ForegroundRole])
        except ValueError:

            pass