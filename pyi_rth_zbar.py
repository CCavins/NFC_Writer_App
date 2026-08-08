"""PyInstaller runtime hook: let pyzbar find the bundled libzbar.

pyzbar locates zbar via ctypes.util.find_library, which consults
DYLD_LIBRARY_PATH on macOS. The bundled libzbar.dylib lives in the
frozen app's Frameworks directory (sys._MEIPASS), so prepend it.
"""

import os
import sys

if hasattr(sys, "_MEIPASS"):
    os.environ["DYLD_LIBRARY_PATH"] = (
        sys._MEIPASS + os.pathsep + os.environ.get("DYLD_LIBRARY_PATH", "")
    )
