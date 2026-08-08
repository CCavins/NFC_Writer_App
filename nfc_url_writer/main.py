"""Main entry point for NFC URL Writer application."""

import sys
import logging
import errno
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from .ui.main_window import MainWindow


class SafeStreamHandler(logging.StreamHandler):
    """StreamHandler that gracefully handles EPIPE errors."""
    
    def emit(self, record):
        """Emit a record, handling EPIPE errors gracefully."""
        try:
            super().emit(record)
        except (OSError, IOError) as e:
            # Ignore EPIPE errors (broken pipe) - stdout/stderr may be closed
            if e.errno != errno.EPIPE:
                # Re-raise if it's not an EPIPE error
                self.handleError(record)
        except Exception:
            # Handle any other exceptions
            self.handleError(record)


def main():
    """Main application entry point."""
    # Setup logging with safe stream handler
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('nfc_url_writer.log'),
            SafeStreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting NFC URL Writer")
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("NFC URL Writer")
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    # Run event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

