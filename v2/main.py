import sys
import logging
import atexit
from PyQt5.QtWidgets import QApplication

from main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(funcName)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

if __name__ == '__main__':

    app = QApplication(sys.argv)

    main_window = MainWindow()

    main_window.show()
    sys.exit(app.exec_())