"""NFC manager for handling ACR122U reader and tag operations.

Supports multiple tag types:
- NTAG tags (NTAG213, NTAG215, NTAG216) via nfctagger
- MIFARE Ultralight tags via pyscard direct APDU commands
- MIFARE Classic tags via pyscard with authentication and NDEF formatting
It works with PC/SC running (no need to stop PC/SC daemon).
"""

import logging
import threading
import time
import errno
from typing import Optional, Dict, Any, Union
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
try:
    from PyQt6.QtWidgets import QApplication
    QT_APP_AVAILABLE = True
except ImportError:
    QT_APP_AVAILABLE = False

# nfctagger for NTAG support
try:
    from nfctagger import PCSCWaiter, decode_atr
    from nfctagger.devices.pcsc import PCSC
    from nfctagger.devices.ntag import NTag
    from nfctagger.ndef import NDEF
    NFCTAGGER_AVAILABLE = True
except ImportError:
    NFCTAGGER_AVAILABLE = False
    logging.warning("nfctagger not available")

# pyscard for MIFARE Ultralight and other tag support
try:
    from smartcard.System import readers as pyscard_readers
    from smartcard.util import toHexString
    PYSCARD_AVAILABLE = True
except ImportError:
    PYSCARD_AVAILABLE = False
    logging.warning("pyscard not available")

NFC_AVAILABLE = NFCTAGGER_AVAILABLE or PYSCARD_AVAILABLE


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


class NFCManager(QObject):
    """Manages NFC reader connection and tag operations."""
    
    # Signals for UI updates
    reader_status_changed = pyqtSignal(str)  # Reader name or "not found"
    tag_detected = pyqtSignal(str, dict)  # Tag type, tag info dict
    tag_removed = pyqtSignal()
    write_success = pyqtSignal()
    write_failed = pyqtSignal(str)  # Error message
    write_verified = pyqtSignal(bool, str)  # Verified (bool), message (str)
    tag_read = pyqtSignal(str, dict)  # URL (str), tag info (dict)
    operation_status = pyqtSignal(str)  # Current operation status (e.g., "Clearing tag...", "Writing...", "Verifying...")
    
    def __init__(self):
        """Initialize NFC manager."""
        super().__init__()
        self.waiter: Optional[PCSCWaiter] = None
        self.current_device: Optional[Union[PCSC, Any]] = None
        self.current_tag: Optional[Union[NTag, Any]] = None
        self.current_tag_info: Optional[Dict[str, Any]] = None
        self.current_connection: Optional[Any] = None  # pyscard connection for non-NTAG tags
        self.current_tag_type: Optional[str] = None  # 'ntag', 'mifare_ultralight', etc.
        self.polling_active = False
        self.polling_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self.last_connection_error: str = ""
        self._reset_requested = False  # Flag to signal polling loop to reset
        
        # Batch queue state
        self.batch_queue: list[dict] = []  # List of {url: str, status: str} dicts
        self.batch_queue_index: int = 0
        self.batch_mode_active: bool = False
        
        # Setup logging with safe stream handler
        # Only configure if not already configured (avoid duplicate handlers)
        if not logging.getLogger().handlers:
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                handlers=[
                    logging.FileHandler('nfc_url_writer.log'),
                    SafeStreamHandler()
                ]
            )
        self.logger = logging.getLogger(__name__)
    
    def _process_ui_events(self) -> None:
        """Process Qt events to allow UI updates, if QApplication is available."""
        if QT_APP_AVAILABLE:
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
    
    def _get_user_friendly_error(self, error_msg: str) -> tuple[str, str]:
        """
        Convert technical error messages to user-friendly ones with suggestions.
        
        Returns:
            tuple: (user_message, suggestion)
        """
        error_lower = error_msg.lower()
        
        # Error mappings
        if "unpowered" in error_lower or "card is unpowered" in error_lower:
            return (
                "Card connection lost",
                "The card may have been removed or moved. Please place the card back on the reader and try again."
            )
        elif "card was reset" in error_lower or "card reset" in error_lower:
            return (
                "Card connection interrupted",
                "The card connection was interrupted. Try removing and placing the card again, then retry."
            )
        elif "no smart card" in error_lower or "no card" in error_lower:
            return (
                "No card detected",
                "Please place an NFC tag on the reader and wait for it to be detected."
            )
        elif "authentication failed" in error_lower or "custom keys" in error_lower:
            return (
                "Tag authentication failed",
                "This tag uses custom security keys. Only tags with default keys (0xFFFFFFFFFFFF) are supported."
            )
        elif "too long" in error_lower or "capacity" in error_lower:
            return (
                "Content too large",
                "The URL or text is too long for this tag. Try a shorter URL or use a tag with more capacity (NTAG216)."
            )
        elif "not writable" in error_lower or "locked" in error_lower:
            return (
                "Tag is locked",
                "This tag is write-protected and cannot be written to. Use a different tag."
            )
        elif "reader not found" in error_lower or "no reader" in error_lower:
            return (
                "NFC reader not found",
                "Please ensure the ACR122U reader is connected via USB and the PC/SC service is running."
            )
        elif "verification failed" in error_lower:
            return (
                "Write verification failed",
                "The write may have succeeded but verification failed. Check the tag with a phone to confirm."
            )
        else:
            # Generic error
            return (
                "Write operation failed",
                f"Error: {error_msg}. Try removing and replacing the tag, then retry."
            )
        
        # Don't connect immediately - wait for UI to be ready
        # Connection will be initiated after a short delay
    
    def connect_reader(self, retry_count: int = 0, max_retries: int = 3) -> bool:
        """
        Connect to the NFC reader with retry mechanism.
        
        Args:
            retry_count: Current retry attempt (internal use)
            max_retries: Maximum number of retry attempts
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        if not NFC_AVAILABLE:
            self.reader_status_changed.emit("not found")
            self.last_connection_error = "NFC libraries not available"
            return False
        
        try:
            with self._lock:
                # Stop existing waiter if any
                if self.waiter is not None:
                    try:
                        self.waiter.stop()
                    except:
                        pass
                    self.waiter = None
                
                # Create new PCSCWaiter - this will monitor for cards
                # It works with PC/SC running, no need to stop PC/SC daemon
                if NFCTAGGER_AVAILABLE:
                    try:
                        self.waiter = PCSCWaiter()
                        # Give PC/SC a moment to initialize (especially on first connection)
                        if retry_count > 0:
                            time.sleep(0.5 * retry_count)  # Exponential backoff
                        
                        # Check if we can detect readers by trying to get a connection
                        # (with very short timeout to just test availability)
                        test_connection = self.waiter.get_next_connection(timeout=0.2)
                        if test_connection is None:
                            # No card present, but reader should be available
                            # Try to verify reader exists by checking pyscard
                            if PYSCARD_AVAILABLE:
                                # Give pyscard a moment to enumerate readers
                                time.sleep(0.1)
                                reader_list = pyscard_readers()
                                if reader_list:
                                    reader_name = str(reader_list[0])
                                    self.reader_status_changed.emit(reader_name)
                                    self.logger.info(f"NFC reader connected: {reader_name}")
                                    self.last_connection_error = ""
                                    return True
                                elif retry_count < max_retries:
                                    # Retry if no readers found yet
                                    self.logger.debug(f"Reader not found, retrying ({retry_count + 1}/{max_retries})...")
                                    time.sleep(1.0)  # Wait before retry
                                    return self.connect_reader(retry_count + 1, max_retries)
                        else:
                            # Got a connection, reader is working
                            reader_name = "ACR122U"
                            self.reader_status_changed.emit(reader_name)
                            self.logger.info(f"NFC reader connected: {reader_name}")
                            self.last_connection_error = ""
                            # Don't keep this connection, we'll get a new one in polling
                            return True
                    except Exception as e:
                        error_msg = f"Failed to connect to NFC reader: {str(e)}"
                        self.logger.debug(error_msg)
                        
                        # Retry on certain errors
                        if retry_count < max_retries:
                            self.logger.debug(f"Connection failed, retrying ({retry_count + 1}/{max_retries})...")
                            time.sleep(1.0 * (retry_count + 1))  # Exponential backoff
                            return self.connect_reader(retry_count + 1, max_retries)
                        
                        # Max retries reached, give up
                        self.logger.error(error_msg, exc_info=True)
                        self.last_connection_error = error_msg
                        self.reader_status_changed.emit("not found")
                        return False
                elif PYSCARD_AVAILABLE:
                    # Fallback to pyscard only
                    if retry_count > 0:
                        time.sleep(0.5 * retry_count)
                    time.sleep(0.1)  # Give pyscard time to enumerate
                    reader_list = pyscard_readers()
                    if reader_list:
                        reader_name = str(reader_list[0])
                        self.reader_status_changed.emit(reader_name)
                        self.logger.info(f"NFC reader connected: {reader_name}")
                        self.last_connection_error = ""
                        return True
                    elif retry_count < max_retries:
                        self.logger.debug(f"No readers found, retrying ({retry_count + 1}/{max_retries})...")
                        time.sleep(1.0)
                        return self.connect_reader(retry_count + 1, max_retries)
                    else:
                        self.logger.warning("No PC/SC readers found")
                        self.reader_status_changed.emit("not found")
                        self.last_connection_error = "No PC/SC readers found"
                        return False
        except Exception as e:
            self.logger.error(f"Failed to connect NFC reader: {e}", exc_info=True)
            self.last_connection_error = str(e)
            if retry_count < max_retries:
                time.sleep(1.0 * (retry_count + 1))
                return self.connect_reader(retry_count + 1, max_retries)
            self.reader_status_changed.emit("not found")
            return False
    
    def start_polling(self) -> None:
        """Start background polling for NFC tags."""
        if not NFC_AVAILABLE or (NFCTAGGER_AVAILABLE and self.waiter is None):
            return
        
        if self.polling_active:
            return
        
        self.polling_active = True
        self.polling_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.polling_thread.start()
    
    def stop_polling(self) -> None:
        """Stop background polling for NFC tags."""
        self.polling_active = False
        if self.polling_thread:
            self.polling_thread.join(timeout=2.0)
    
    def _identify_tag_from_atr(self, atr_bytes: bytes) -> Optional[Dict[str, str]]:
        """Identify tag type from ATR bytes using nfctagger's decode_atr."""
        if not NFCTAGGER_AVAILABLE:
            return None
        try:
            atr_hex = toHexString(atr_bytes) if PYSCARD_AVAILABLE else None
            if atr_hex:
                return decode_atr(atr_hex)
        except:
            pass
        return None
    
    def _detect_mifare_ultralight(self, connection) -> Optional[Dict[str, Any]]:
        """
        Detect and identify MIFARE Ultralight tag using pyscard APDU commands.
        
        Returns:
            dict with tag info if MIFARE Ultralight, None otherwise
        """
        if not PYSCARD_AVAILABLE:
            return None
        
        try:
            # Read page 0 to get UID
            # ACR122U command: FF B0 00 <page> <length>
            read_cmd = [0xFF, 0xB0, 0x00, 0x00, 0x10]  # Read 16 bytes from page 0
            data, sw1, sw2 = connection.transmit(read_cmd)
            
            if sw1 != 0x90 or sw2 != 0x00:
                return None
            
            if len(data) < 4:
                return None
            
            # Check if it looks like MIFARE Ultralight
            # MIFARE Ultralight UID starts with 0x04
            if data[0] != 0x04:
                return None
            
            # Read page 3 to check capability container
            read_cmd = [0xFF, 0xB0, 0x00, 0x03, 0x10]
            data, sw1, sw2 = connection.transmit(read_cmd)
            
            if sw1 != 0x90 or sw2 != 0x00:
                return None
            
            # Check for NDEF capability container (0xE1 0x10)
            if len(data) >= 2 and data[0] == 0xE1 and data[1] == 0x10:
                # MIFARE Ultralight with NDEF support
                uid = bytes(data[:7]) if len(data) >= 7 else bytes(data[:4])
                uid_hex = uid.hex().upper()
                
                # Determine capacity (Ultralight has 48 bytes, Ultralight C has 64 bytes)
                # Check page count - Ultralight has 16 pages (0-15), Ultralight C has more
                capacity = 48  # Default for MIFARE Ultralight
                
                return {
                    'type': 'mifare_ultralight',
                    'uid': uid_hex,
                    'ndef_capable': True,
                    'writable': True,
                    'capacity': capacity,
                    'connection': connection
                }
        except Exception as e:
            self.logger.debug(f"Error detecting MIFARE Ultralight: {e}")
            return None
        
        return None
    
    def _load_mifare_key(self, connection, key_slot: int, key: bytes) -> bool:
        """
        Load a MIFARE key into ACR122U's key slot.
        
        Args:
            connection: pyscard connection object
            key_slot: Key slot number (0x00-0x19, typically 0x00)
            key: 6-byte key
        
        Returns:
            bool: True if successful
        """
        if not PYSCARD_AVAILABLE:
            return False
        
        try:
            # ACR122U Load Keys command: FF 82 00 <key_slot> 06 <key[6]>
            load_cmd = [0xFF, 0x82, 0x00, key_slot, 0x06] + list(key)
            data, sw1, sw2 = connection.transmit(load_cmd)
            
            return sw1 == 0x90 and sw2 == 0x00
        except Exception as e:
            self.logger.debug(f"MIFARE Classic load key error: {e}")
            return False
    
    def _authenticate_mifare_classic(self, connection, sector: int, key_type: int = 0x60, key: bytes = None) -> bool:
        """
        Authenticate a MIFARE Classic sector.
        
        Args:
            connection: pyscard connection object
            sector: Sector number (0-15 for 1K, 0-39 for 4K)
            key_type: 0x60 for Key A, 0x61 for Key B
            key: 6-byte key (default: 0xFFFFFFFFFFFF)
        
        Returns:
            bool: True if authentication successful
        """
        if not PYSCARD_AVAILABLE:
            return False
        
        if key is None:
            # Default key (most common - factory default)
            key = bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        
        if len(key) != 6:
            return False
        
        try:
            # Calculate block number (first block of sector)
            block = sector * 4
            
            # Method 1: Load key into slot 0, then authenticate with slot
            if self._load_mifare_key(connection, 0x00, key):
                # ACR122U MIFARE authentication command: FF 86 00 00 05 <key_type> <block> <key_slot>
                auth_cmd = [0xFF, 0x86, 0x00, 0x00, 0x05, key_type, block, 0x00]
                data, sw1, sw2 = connection.transmit(auth_cmd)
                
                if sw1 == 0x90 and sw2 == 0x00:
                    return True
            
            # Method 2: Try direct authentication with key in command (fallback)
            # ACR122U MIFARE authentication command: FF 86 00 00 05 <key_type> <block> <key[6]>
            auth_cmd2 = [0xFF, 0x86, 0x00, 0x00, 0x05, key_type, block] + list(key)
            data, sw1, sw2 = connection.transmit(auth_cmd2)
            
            return sw1 == 0x90 and sw2 == 0x00
        except Exception as e:
            self.logger.debug(f"MIFARE Classic authentication error: {e}")
            return False
    
    def _try_authenticate_mifare_classic_multiple_keys(self, connection, sector: int) -> bool:
        """
        Try to authenticate MIFARE Classic sector with common default keys.
        
        Args:
            connection: pyscard connection object
            sector: Sector number
        
        Returns:
            bool: True if authentication successful with any key
        """
        # Common default keys (expanded list)
        default_keys = [
            bytes([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF]),  # Most common factory default
            bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # All zeros
            bytes([0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5]),  # MAD default key
            bytes([0xB0, 0xB1, 0xB2, 0xB3, 0xB4, 0xB5]),  # Another common default
            bytes([0xD3, 0xF7, 0xD3, 0xF7, 0xD3, 0xF7]),  # NDEF default key
            bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]),  # Another common pattern
            bytes([0x4D, 0x3A, 0x99, 0xC3, 0x51, 0xDD]),  # Another common default
            bytes([0x1A, 0x98, 0x2C, 0x7E, 0x45, 0x9A]),  # Another common default
        ]
        
        # Try Key A first, then Key B
        for key in default_keys:
            if self._authenticate_mifare_classic(connection, sector, key_type=0x60, key=key):
                self.logger.debug(f"MIFARE Classic sector {sector} authenticated with Key A: {key.hex().upper()}")
                return True
            if self._authenticate_mifare_classic(connection, sector, key_type=0x61, key=key):
                self.logger.debug(f"MIFARE Classic sector {sector} authenticated with Key B: {key.hex().upper()}")
                return True
        
        self.logger.debug(f"MIFARE Classic sector {sector} authentication failed with all default keys")
        return False
    
    def _read_mifare_block(self, connection, block: int) -> Optional[bytes]:
        """
        Read a MIFARE Classic block (16 bytes).
        
        Args:
            connection: pyscard connection object
            block: Block number (0-63 for 1K)
        
        Returns:
            bytes: Block data or None if failed
        """
        if not PYSCARD_AVAILABLE:
            return None
        
        try:
            # ACR122U read command: FF B0 00 <block> <length>
            read_cmd = [0xFF, 0xB0, 0x00, block, 0x10]  # 16 bytes
            data, sw1, sw2 = connection.transmit(read_cmd)
            
            if sw1 == 0x90 and sw2 == 0x00 and len(data) == 16:
                return bytes(data)
            return None
        except Exception as e:
            self.logger.debug(f"MIFARE Classic read error: {e}")
            return None
    
    def _write_mifare_block(self, connection, block: int, data: bytes) -> bool:
        """
        Write a MIFARE Classic block (16 bytes).
        
        Args:
            connection: pyscard connection object
            block: Block number (0-63 for 1K)
            data: 16 bytes of data to write
        
        Returns:
            bool: True if write successful
        """
        if not PYSCARD_AVAILABLE:
            return False
        
        if len(data) != 16:
            return False
        
        try:
            # ACR122U write command: FF D6 00 <block> <length> <data>
            write_cmd = [0xFF, 0xD6, 0x00, block, 0x10] + list(data)
            resp_data, sw1, sw2 = connection.transmit(write_cmd)
            
            return sw1 == 0x90 and sw2 == 0x00
        except Exception as e:
            self.logger.debug(f"MIFARE Classic write error: {e}")
            return False
    
    def _detect_mifare_classic(self, connection) -> Optional[Dict[str, Any]]:
        """
        Detect and identify MIFARE Classic tag.
        
        Returns:
            dict with tag info if MIFARE Classic, None otherwise
        """
        if not PYSCARD_AVAILABLE:
            return None
        
        try:
            # Try to read block 0 (UID and manufacturer data)
            # First, we need to authenticate sector 0
            # Try multiple common keys
            self.logger.debug("Attempting to authenticate MIFARE Classic sector 0...")
            if not self._try_authenticate_mifare_classic_multiple_keys(connection, 0):
                # If authentication fails, it might not be MIFARE Classic or uses custom keys
                self.logger.debug("MIFARE Classic sector 0 authentication failed - tag may use custom keys")
                return None
            
            # Read block 0
            block0 = self._read_mifare_block(connection, 0)
            if block0 is None or len(block0) < 4:
                return None
            
            # MIFARE Classic UID is in first 4 bytes (or 7 bytes for 4K)
            uid = block0[:4]
            uid_hex = uid.hex().upper()
            
            # Determine if 1K or 4K (simplified - assume 1K for now)
            # MIFARE Classic 1K has 16 sectors, 4K has 40 sectors
            # Usable NDEF capacity: sectors 1-15 = ~720 bytes (after accounting for sector trailers)
            capacity = 720  # Practical NDEF capacity for MIFARE Classic 1K
            
            # Check if already formatted for NDEF
            # Try to read sector 1, block 4 (first data block after sector 0)
            ndef_formatted = False
            try:
                if self._try_authenticate_mifare_classic_multiple_keys(connection, 1):
                    block4 = self._read_mifare_block(connection, 4)
                    if block4:
                        # Check for NDEF TLV marker (0x03) or MAD indicator
                        if block4[0] == 0x03 or (len(block4) > 0 and block4[0] == 0x01):
                            ndef_formatted = True
            except:
                pass
            
            return {
                'type': 'mifare_classic',
                'uid': uid_hex,
                'ndef_capable': True,  # Can be formatted for NDEF
                'writable': True,
                'capacity': capacity,
                'ndef_formatted': ndef_formatted,
                'connection': connection
            }
        except Exception as e:
            self.logger.debug(f"Error detecting MIFARE Classic: {e}")
            return None
        
        return None
    
    def _poll_loop(self) -> None:
        """
        Background polling loop for detecting NFC tags.
        
        This runs in a separate thread to keep the GUI responsive.
        It continuously waits for tags and identifies their type.
        """
        last_tag_uid = None
        current_device = None
        current_connection = None
        tag_detection_time = None  # Track when tag was last detected
        detection_grace_period = 1.0  # Grace period in seconds after detection before checking removal
        
        # Debouncing for tag detection - only emit tag_detected after tag is stable
        pending_detection_uid = None  # UID of tag we're waiting to confirm
        pending_detection_time = None  # When we first saw this tag
        detection_debounce_period = 0.1  # Wait 100ms before confirming detection
        
        while self.polling_active:
            try:
                # Check if reset was requested (after a write operation)
                if self._reset_requested:
                    self.logger.debug("Polling loop: Reset requested, clearing local state")
                    current_device = None
                    current_connection = None
                    last_tag_uid = None
                    tag_detection_time = None
                    pending_detection_uid = None
                    pending_detection_time = None
                    with self._lock:
                        self._reset_requested = False
                    # Brief wait to ensure state is fully reset
                    time.sleep(0.2)
                    continue
                
                if NFCTAGGER_AVAILABLE and self.waiter is None:
                    time.sleep(1.0)
                    continue
                
                # If we have a current device/connection, try to keep it alive
                if current_device is not None or current_connection is not None:
                    # Check if we're still in the grace period after tag detection
                    # Don't check for removal too soon after detection to avoid false positives
                    if tag_detection_time is not None:
                        time_since_detection = time.time() - tag_detection_time
                        if time_since_detection < detection_grace_period:
                            # Still in grace period - just wait and continue
                            time.sleep(0.5)
                            continue
                    
                    tag_still_present = False
                    try:
                        if current_device is not None:
                            # NTAG tag - check if still present
                            tag = current_device.get_tag()
                            if isinstance(tag, NTag):
                                # Try to read UID to verify tag is still there
                                try:
                                    uid = tag.get_uid()
                                    if uid is not None and len(uid) > 0:
                                        tag_still_present = True
                                except:
                                    # UID read failed - tag likely removed
                                    tag_still_present = False
                        elif current_connection is not None:
                            # MIFARE Ultralight or Classic - try to read to check if still present
                            if self.current_tag_type == 'mifare_ultralight':
                                read_cmd = [0xFF, 0xB0, 0x00, 0x00, 0x04]
                                data, sw1, sw2 = current_connection.transmit(read_cmd)
                                if sw1 == 0x90 and sw2 == 0x00:
                                    tag_still_present = True
                            elif self.current_tag_type == 'mifare_classic':
                                # Try to authenticate and read block 0
                                if self._try_authenticate_mifare_classic_multiple_keys(current_connection, 0):
                                    block0 = self._read_mifare_block(current_connection, 0)
                                    if block0 is not None:
                                        tag_still_present = True
                    except Exception as e:
                        # Connection lost or tag removed
                        self.logger.debug(f"Tag presence check failed: {e}")
                        tag_still_present = False
                    
                    if tag_still_present:
                        time.sleep(0.5)
                        continue
                    else:
                        # Tag was removed (but only if past grace period)
                        self.logger.info("Tag removed - connection lost")
                        current_device = None
                        current_connection = None
                        tag_detection_time = None
                        pending_detection_uid = None
                        pending_detection_time = None
                        if last_tag_uid is not None:
                            with self._lock:
                                self.current_device = None
                                self.current_tag = None
                                self.current_tag_info = None
                                self.current_connection = None
                                self.current_tag_type = None
                            last_tag_uid = None
                            tag_detection_time = None
                            self.tag_removed.emit()
                
                # Wait for a new card connection
                device = None
                connection = None
                
                if NFCTAGGER_AVAILABLE and self.waiter is not None:
                    device = self.waiter.get_next_connection(timeout=0.5)
                
                if device is None:
                    # No card detected via nfctagger
                    # Only reset pending detection if we've been waiting for a VERY long time
                    # (to avoid resetting on brief connection hiccups during debounce)
                    if pending_detection_uid is not None and pending_detection_time is not None:
                        time_since_pending = time.time() - pending_detection_time
                        # Only reset if we've been waiting much longer than debounce period
                        # This gives the tag many chances to be seen again even with connection hiccups
                        if time_since_pending > 2.0:  # 2 seconds - very patient
                            # Tag was pending but never confirmed after many attempts - reset
                            self.logger.debug(f"Pending detection for {pending_detection_uid} expired after {time_since_pending:.3f}s")
                            pending_detection_uid = None
                            pending_detection_time = None
                    # Check if we had a tag before - if so, it was removed
                    if last_tag_uid is not None:
                        self.logger.debug("Tag removed - no device connection available")
                        with self._lock:
                            self.current_device = None
                            self.current_tag = None
                            self.current_tag_info = None
                            self.current_connection = None
                            self.current_tag_type = None
                        last_tag_uid = None
                        tag_detection_time = None
                        pending_detection_uid = None
                        pending_detection_time = None
                        self.tag_removed.emit()
                    continue
                
                # Got a device, try to identify tag type
                try:
                    # First, try to get tag via nfctagger (for NTAG)
                    tag = None
                    tag_info = None
                    
                    if hasattr(device, '_child') and device._child is not None:
                        try:
                            tag = device.get_tag()
                            if isinstance(tag, NTag):
                                # NTAG tag detected
                                try:
                                    tag_uid = tag.get_uid()
                                    tag_uid_hex = tag_uid.hex().upper()
                                    tag_version = tag.get_tag_version(config=True)
                                except Exception as e:
                                    self.logger.warning(f"Error reading tag UID/version: {e}")
                                    continue
                                
                                if tag_uid_hex != last_tag_uid:
                                    # New tag detected - try to detect immediately
                                    # If we can successfully read the tag, it's stable enough
                                    try:
                                        # Small delay to let tag stabilize after initial detection
                                        # This helps with orientation-related connection issues
                                        time.sleep(0.15)
                                        
                                        fresh_tag = device.get_tag()
                                        if not isinstance(fresh_tag, NTag):
                                            # Tag type changed, skip
                                            continue
                                        
                                        # Additional small delay before reading tag info
                                        # Helps ensure connection is stable, especially for orientation issues
                                        time.sleep(0.1)
                                        
                                        # Try to read tag info to verify it's stable
                                        tag_info = self._identify_ntag(fresh_tag, tag_version, tag_uid_hex)
                                        
                                        # If we got here, tag is stable - detect it
                                        with self._lock:
                                            self.current_device = device
                                            self.current_tag = fresh_tag  # Use fresh tag object
                                            self.current_tag_info = tag_info
                                            self.current_connection = None
                                            self.current_tag_type = 'ntag'
                                        
                                        current_device = device
                                        current_connection = None
                                        last_tag_uid = tag_uid_hex
                                        tag_detection_time = time.time()
                                        pending_detection_uid = None
                                        pending_detection_time = None
                                        
                                        # Small delay before emitting signal to ensure tag is fully stable
                                        time.sleep(0.1)
                                        
                                        self.tag_detected.emit(tag_version, tag_info)
                                        self.logger.info(f"NTAG tag detected: {tag_version}, UID: {tag_uid_hex}")
                                    except Exception as e:
                                        # Tag read failed - might be unstable, skip for now
                                        error_str = str(e).lower()
                                        is_unpowered = "unpowered" in error_str or "card is unpowered" in error_str
                                        if is_unpowered:
                                            self.logger.debug(f"Tag {tag_uid_hex} read failed due to unpowered (orientation issue?): {e}")
                                        else:
                                            self.logger.debug(f"Tag {tag_uid_hex} read failed (might be unstable): {e}")
                                        continue
                                continue
                        except AssertionError:
                            # Not an NTAG tag, try MIFARE Ultralight
                            pass
                    
                    # Try MIFARE Ultralight detection
                    # Get the underlying pyscard connection from the device
                    connection = None
                    if hasattr(device, '_connection'):
                        connection = device._connection
                    elif hasattr(device, '_child') and hasattr(device._child, '_connection'):
                        connection = device._child._connection
                    
                    if connection is not None:
                        # Try MIFARE Ultralight first (simpler detection)
                        mifare_info = self._detect_mifare_ultralight(connection)
                        
                        if mifare_info:
                            tag_uid_hex = mifare_info['uid']
                            
                            if tag_uid_hex != last_tag_uid:
                                # Apply debouncing for MIFARE tags too
                                current_time = time.time()
                                
                                if pending_detection_uid != tag_uid_hex:
                                    # First time seeing this tag - start debounce timer
                                    pending_detection_uid = tag_uid_hex
                                    pending_detection_time = current_time
                                    self.logger.debug(f"MIFARE Ultralight tag {tag_uid_hex} detected, waiting {detection_debounce_period}s for stability...")
                                    continue
                                elif pending_detection_uid == tag_uid_hex:
                                    # Same tag - check if debounce period has passed
                                    time_since_first_seen = current_time - pending_detection_time
                                    if time_since_first_seen < detection_debounce_period:
                                        # Still in debounce period - wait
                                        continue
                                    # Debounce period passed - confirm detection
                                    # Store connection reference before removing from dict
                                    connection_ref = mifare_info.get('connection', connection)
                                    # Remove connection from mifare_info dict (don't store it in tag_info)
                                    if 'connection' in mifare_info:
                                        del mifare_info['connection']
                                    
                                    with self._lock:
                                        self.current_device = None
                                        self.current_tag = None
                                        self.current_tag_info = mifare_info
                                        self.current_connection = connection_ref
                                        self.current_tag_type = 'mifare_ultralight'
                                    
                                    current_device = None
                                    current_connection = connection_ref
                                    last_tag_uid = tag_uid_hex
                                    tag_detection_time = time.time()
                                    pending_detection_uid = None
                                    pending_detection_time = None
                                    self.tag_detected.emit('mifare_ultralight', mifare_info)
                                    self.logger.info(f"MIFARE Ultralight tag detected, UID: {tag_uid_hex}")
                            continue
                        
                        # Try MIFARE Classic detection
                        mifare_classic_info = self._detect_mifare_classic(connection)
                        
                        if mifare_classic_info:
                            tag_uid_hex = mifare_classic_info['uid']
                            
                            if tag_uid_hex != last_tag_uid:
                                # Apply debouncing for MIFARE Classic tags too
                                current_time = time.time()
                                
                                if pending_detection_uid != tag_uid_hex:
                                    # First time seeing this tag - start debounce timer
                                    pending_detection_uid = tag_uid_hex
                                    pending_detection_time = current_time
                                    self.logger.debug(f"MIFARE Classic tag {tag_uid_hex} detected, waiting {detection_debounce_period}s for stability...")
                                    continue
                                elif pending_detection_uid == tag_uid_hex:
                                    # Same tag - check if debounce period has passed
                                    time_since_first_seen = current_time - pending_detection_time
                                    if time_since_first_seen < detection_debounce_period:
                                        # Still in debounce period - wait
                                        continue
                                    # Debounce period passed - confirm detection
                                    # Store connection reference before removing from dict
                                    connection_ref = mifare_classic_info.get('connection', connection)
                                    # Remove connection from mifare_classic_info dict
                                    if 'connection' in mifare_classic_info:
                                        del mifare_classic_info['connection']
                                    
                                    with self._lock:
                                        self.current_device = None
                                        self.current_tag = None
                                        self.current_tag_info = mifare_classic_info
                                        self.current_connection = connection_ref
                                        self.current_tag_type = 'mifare_classic'
                                    
                                    current_device = None
                                    current_connection = connection_ref
                                    last_tag_uid = tag_uid_hex
                                    tag_detection_time = time.time()
                                    pending_detection_uid = None
                                    pending_detection_time = None
                                    self.tag_detected.emit('mifare_classic', mifare_classic_info)
                                    self.logger.info(f"MIFARE Classic tag detected, UID: {tag_uid_hex}")
                            continue
                    
                    # Unknown or unsupported tag type
                    # Try to get tag type from ATR first
                    tag_type_hint = "unknown"
                    atr_info = None
                    try:
                        # Get connection from device chain - try multiple paths
                        connection_for_atr = None
                        if hasattr(device, '_connection'):
                            connection_for_atr = device._connection
                        elif hasattr(device, '_child') and hasattr(device._child, '_connection'):
                            connection_for_atr = device._child._connection
                        elif hasattr(device, '_child') and hasattr(device._child, '_child') and hasattr(device._child._child, '_connection'):
                            connection_for_atr = device._child._child._connection
                        
                        if connection_for_atr is not None:
                            try:
                                atr = connection_for_atr.getATR()
                                if atr:
                                    # Convert ATR to hex string for decode_atr
                                    if PYSCARD_AVAILABLE:
                                        atr_hex = toHexString(list(atr))
                                    else:
                                        atr_hex = ' '.join(f'{b:02X}' for b in atr)
                                    
                                    atr_info = decode_atr(atr_hex) if NFCTAGGER_AVAILABLE else None
                                    if atr_info:
                                        tag_type_hint = atr_info.get('Card Name', 'unknown')
                                        
                                        # If ATR says MIFARE Classic, try detection again with the connection we have
                                        if 'MIFARE Classic' in tag_type_hint and connection is not None:
                                            self.logger.info(f"ATR indicates MIFARE Classic, attempting detection...")
                                            mifare_classic_info = self._detect_mifare_classic(connection)
                                            
                                            if mifare_classic_info:
                                                tag_uid_hex = mifare_classic_info['uid']
                                                
                                                if tag_uid_hex != last_tag_uid:
                                                    connection_ref = mifare_classic_info.get('connection', connection)
                                                    if 'connection' in mifare_classic_info:
                                                        del mifare_classic_info['connection']
                                                    
                                                    with self._lock:
                                                        self.current_device = None
                                                        self.current_tag = None
                                                        self.current_tag_info = mifare_classic_info
                                                        self.current_connection = connection_ref
                                                        self.current_tag_type = 'mifare_classic'
                                                    
                                                    current_device = None
                                                    current_connection = connection_ref
                                                    last_tag_uid = tag_uid_hex
                                                    tag_detection_time = time.time()
                                                    self.tag_detected.emit('mifare_classic', mifare_classic_info)
                                                    self.logger.info(f"MIFARE Classic tag detected, UID: {tag_uid_hex}")
                                                continue
                                            else:
                                                # MIFARE Classic detected from ATR but authentication failed
                                                # Still show it as detected but with a warning about custom keys
                                                error_msg = f"MIFARE Classic detected but authentication failed. This tag uses custom keys (not the default 0xFFFFFFFFFFFF). To write to this tag, you'll need to know the authentication keys for each sector."
                                                self.logger.warning(error_msg)
                                                
                                                # Try to get UID from ATR or other means if possible
                                                # For now, create a partial tag info
                                                tag_info_partial = {
                                                    'type': 'mifare_classic',
                                                    'uid': 'unknown',
                                                    'ndef_capable': True,  # Technically capable, but needs keys
                                                    'writable': False,  # Can't write without keys
                                                    'capacity': 720,
                                                    'message': error_msg,
                                                    'requires_custom_keys': True
                                                }
                                                
                                                self.tag_detected.emit("mifare_classic_locked", tag_info_partial)
                                                self.logger.info("MIFARE Classic tag detected (locked with custom keys)")
                                                continue
                            except Exception as e:
                                self.logger.debug(f"Could not decode ATR: {e}")
                    except Exception as e:
                        self.logger.debug(f"Could not get connection for ATR: {e}")
                    
                    error_msg = f"Tag type not supported ({tag_type_hint}). Supported types: NTAG213/215/216, MIFARE Ultralight, MIFARE Classic."
                    self.logger.warning(error_msg)
                    self.tag_detected.emit("unsupported", {
                        'type': tag_type_hint,
                        'ndef_capable': False,
                        'writable': False,
                        'message': error_msg
                    })
                    
                except Exception as e:
                    error_str = str(e).lower()
                    # Check if it's a transient connection error
                    is_transient = any(term in error_str for term in [
                        "unpowered", "reset", "no smart card", "card was reset", "card is unpowered"
                    ])
                    
                    if is_transient:
                        # Log as debug for transient errors during polling - these are normal
                        self.logger.debug(f"Transient connection error during tag processing: {e}")
                    else:
                        # Log as error for unexpected errors
                        self.logger.error(f"Error processing tag: {e}", exc_info=True)
                    continue
                    
            except Exception as e:
                self.logger.error(f"Error in polling loop: {e}", exc_info=True)
                time.sleep(1.0)
    
    def _identify_ntag(self, tag: NTag, tag_version: str, tag_uid: str) -> Dict[str, Any]:
        """
        Identify NTAG tag capabilities and return info dict.
        
        Args:
            tag: NTag instance
            tag_version: Tag version string (ntag213, ntag215, ntag216)
            tag_uid: Tag UID as hex string
        
        Returns:
            dict: Tag information including type, capacity, NDEF capability
        """
        tag_info = {
            'type': tag_version,
            'uid': tag_uid,
            'ndef_capable': True,
            'writable': True,
        }
        
        # Get capacity based on tag type
        capacity_map = {
            'ntag213': 132,  # bytes
            'ntag215': 504,  # bytes
            'ntag216': 888,  # bytes
        }
        tag_info['capacity'] = capacity_map.get(tag_version, 504)
        
        # Check if tag has existing NDEF data
        # Retry on unpowered errors (common with orientation issues)
        max_read_attempts = 3
        read_delay = 0.2
        
        for attempt in range(max_read_attempts):
            try:
                # Small delay before reading to let card stabilize (especially important for orientation)
                if attempt > 0:
                    time.sleep(read_delay * (attempt + 1))  # Increasing delay for retries
                else:
                    time.sleep(0.1)  # Small initial delay for stabilization
                
                user_data = tag.mem_read_user()
                if len(user_data) > 0 and user_data[0] == 0x03:
                    tag_info['has_ndef'] = True
                else:
                    tag_info['has_ndef'] = False
                break  # Success, exit retry loop
            except Exception as e:
                error_str = str(e).lower()
                is_unpowered = "unpowered" in error_str or "card is unpowered" in error_str
                
                if is_unpowered and attempt < max_read_attempts - 1:
                    # Retry on unpowered errors (orientation-related)
                    self.logger.debug(f"Tag read failed (attempt {attempt + 1}/{max_read_attempts}) due to unpowered, retrying...")
                    continue
                else:
                    # Not unpowered or max attempts reached
                    if attempt == max_read_attempts - 1:
                        self.logger.debug(f"Could not read tag data after {max_read_attempts} attempts: {e}")
                    tag_info['has_ndef'] = False
                    break
        
        return tag_info
    
    def _format_ntag_for_ndef(self, tag, tag_info: dict) -> None:
        """
        Format/clear existing NDEF data on NTAG tag before writing new data.
        
        This ensures previous URLs are completely overwritten by clearing all user memory.
        The method aggressively clears the entire user memory area to prevent any old data
        from remaining, while preserving the CC (Capability Container).
        
        Args:
            tag: NTag instance
            tag_info: Tag information dict
        """
        try:
            # Read existing user data to check if there's anything to clear
            try:
                user_data = tag.mem_read_user()
                has_existing_data = len(user_data) > 0 and (user_data[0] == 0x03 or user_data[0] == 0xFE)
            except:
                # If we can't read, assume there might be data and clear anyway
                has_existing_data = True
                user_data = None
            
            if not has_existing_data:
                # No existing NDEF data found
                self.logger.debug("No existing NDEF data found, skipping format")
                return
            
            self.logger.info("Clearing existing NDEF data before writing...")
            # Status is emitted by caller with step number
            
            # Get tag capacity
            capacity = tag_info.get('capacity', 504)
            
            # Aggressively clear the entire user memory area
            # This ensures no old data remains, regardless of TLV structure
            # We'll clear a large chunk (up to capacity) to be thorough
            bytes_to_clear = min(capacity, 512)  # Clear up to 512 bytes or capacity, whichever is smaller
            
            # Create cleared data: terminator TLV followed by zeros
            # This ensures the tag knows there's no more data
            clear_data = bytearray(bytes_to_clear)
            clear_data[0] = 0xFE  # Terminator TLV (indicates end of data)
            # Rest is already zeros (bytearray initializes to zeros)
            
            # Write the cleared data
            # mem_write_user will write starting from the user memory area (after CC)
            # This completely overwrites any existing NDEF data
            tag.mem_write_user(bytes(clear_data))
            
            # Verify the clear worked by reading back
            try:
                verify_data = tag.mem_read_user()
                if len(verify_data) > 0 and verify_data[0] == 0xFE:
                    self.logger.debug(f"Successfully cleared {bytes_to_clear} bytes - verified terminator written")
                else:
                    self.logger.warning("Clear verification: terminator not found, but continuing anyway")
            except Exception as verify_error:
                self.logger.debug(f"Could not verify clear (non-critical): {verify_error}")
            
            self.logger.info(f"Successfully cleared existing NDEF data ({bytes_to_clear} bytes)")
            
        except Exception as e:
            self.logger.warning(f"Error formatting NTAG tag: {e}")
            # Don't raise - formatting is best-effort
            # The write might still succeed even if format fails
            # But log it so we know if there are persistent issues
    
    def _write_ndef_to_mifare_ultralight(self, connection, ndef_bytes: bytes) -> bool:
        """
        Write NDEF message to MIFARE Ultralight tag using APDU commands.
        
        Args:
            connection: pyscard connection object
            ndef_bytes: NDEF message bytes (TLV format)
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not PYSCARD_AVAILABLE:
            return False
        
        try:
            # MIFARE Ultralight NDEF layout:
            # Page 3: Capability Container (0xE1 0x10 <size> 0x00)
            # Pages 4-15: NDEF message (48 bytes total)
            
            # Check capacity
            if len(ndef_bytes) > 48:
                raise ValueError("NDEF message too large for MIFARE Ultralight (max 48 bytes)")
            
            # Write capability container (page 3)
            # CC: 0xE1 0x10 <size> 0x00
            cc_size = min(len(ndef_bytes), 0xFF)
            cc_data = [0xE1, 0x10, cc_size, 0x00]
            # Pad to 4 bytes
            while len(cc_data) < 4:
                cc_data.append(0x00)
            
            # Write CC to page 3
            # ACR122U command: FF D6 00 <page> <length> <data>
            write_cmd = [0xFF, 0xD6, 0x00, 0x03, 0x04] + cc_data
            data, sw1, sw2 = connection.transmit(write_cmd)
            if sw1 != 0x90 or sw2 != 0x00:
                raise Exception(f"Failed to write capability container: {sw1:02X} {sw2:02X}")
            
            # Write NDEF message starting at page 4
            # Write in 4-byte chunks (one page at a time)
            ndef_data = list(ndef_bytes)
            # Pad to multiple of 4 bytes
            while len(ndef_data) % 4 != 0:
                ndef_data.append(0x00)
            
            page = 4
            for i in range(0, len(ndef_data), 4):
                page_data = ndef_data[i:i+4]
                # Pad to 4 bytes if needed
                while len(page_data) < 4:
                    page_data.append(0x00)
                
                write_cmd = [0xFF, 0xD6, 0x00, page, 0x04] + page_data
                data, sw1, sw2 = connection.transmit(write_cmd)
                if sw1 != 0x90 or sw2 != 0x00:
                    raise Exception(f"Failed to write page {page}: {sw1:02X} {sw2:02X}")
                page += 1
                
                # MIFARE Ultralight has pages 4-15 (12 pages = 48 bytes)
                if page > 15:
                    break
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error writing to MIFARE Ultralight: {e}", exc_info=True)
            return False
    
    def _write_ndef_to_mifare_classic(self, connection, ndef_bytes: bytes) -> bool:
        """
        Write NDEF message to MIFARE Classic tag using block-based writes.
        
        MIFARE Classic NDEF format:
        - Sector 0: UID + MAD (MIFARE Application Directory)
        - Sectors 1-15: NDEF data (48 bytes per sector, 720 bytes total)
        
        Args:
            connection: pyscard connection object
            ndef_bytes: NDEF message bytes (TLV format)
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not PYSCARD_AVAILABLE:
            return False
        
        try:
            # MIFARE Classic 1K has 16 sectors, 4 blocks per sector
            # Sector 0: Blocks 0-3 (UID + MAD)
            # Sectors 1-15: Blocks 4-63 (NDEF data)
            
            # Check capacity (max ~720 bytes for NDEF in sectors 1-15)
            if len(ndef_bytes) > 720:
                raise ValueError("NDEF message too large for MIFARE Classic (max ~720 bytes)")
            
            # Authenticate sector 0 first (try multiple keys)
            if not self._try_authenticate_mifare_classic_multiple_keys(connection, 0):
                raise Exception("Failed to authenticate sector 0. Tag may use custom keys (not default 0xFFFFFFFFFFFF).")
            
            # Read block 0 to get UID (we'll preserve it)
            block0 = self._read_mifare_block(connection, 0)
            if block0 is None:
                raise Exception("Failed to read block 0")
            
            # Create MAD (MIFARE Application Directory) in block 1
            # MAD format: [0x01, 0x03, 0xE1, 0x03, ...]
            # 0xE1 indicates NDEF application in sector 1
            mad_block = bytearray(16)
            mad_block[0] = 0x01  # MAD version
            mad_block[1] = 0x03  # CRC
            mad_block[2] = 0xE1  # NDEF application ID for sector 1
            mad_block[3] = 0x03  # NDEF application ID for sector 1 (continued)
            # Fill rest with 0x00
            for i in range(4, 16):
                mad_block[i] = 0x00
            
            # Write MAD to block 1
            if not self._write_mifare_block(connection, 1, bytes(mad_block)):
                raise Exception("Failed to write MAD to block 1")
            
            # Format NDEF data: TLV format with length
            # TLV: [0x03, <length>, <NDEF data>, 0xFE]
            ndef_tlv = bytearray([0x03, len(ndef_bytes)]) + list(ndef_bytes) + [0xFE]
            
            # Pad to multiple of 16 bytes (block size)
            while len(ndef_tlv) % 16 != 0:
                ndef_tlv.append(0x00)
            
            # Write NDEF data starting from sector 1, block 4
            # Sector 1: blocks 4-7 (64 bytes)
            # Sector 2: blocks 8-11 (64 bytes)
            # etc.
            ndef_offset = 0
            start_block = 4  # First data block of sector 1
            
            for block_num in range(start_block, min(start_block + (len(ndef_tlv) // 16) + 1, 64)):
                # Calculate which sector this block belongs to
                sector = block_num // 4
                
                # Authenticate the sector (try multiple keys)
                if not self._try_authenticate_mifare_classic_multiple_keys(connection, sector):
                    raise Exception(f"Failed to authenticate sector {sector}. Tag may use custom keys.")
                
                # Get 16 bytes of NDEF data for this block
                block_data = ndef_tlv[ndef_offset:ndef_offset + 16]
                # Pad to 16 bytes if needed
                while len(block_data) < 16:
                    block_data.append(0x00)
                
                # Write the block
                if not self._write_mifare_block(connection, block_num, bytes(block_data)):
                    raise Exception(f"Failed to write block {block_num}")
                
                ndef_offset += 16
                if ndef_offset >= len(ndef_tlv):
                    break
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error writing to MIFARE Classic: {e}", exc_info=True)
            return False
    
    def _reset_after_write(self, device=None, connection=None) -> None:
        """
        Perform a robust reset after a successful write operation.
        
        This method:
        1. Explicitly disconnects any active device/connection
        2. Clears all tag references and state
        3. Signals the polling loop to reset its local state
        4. Waits briefly for connections to fully close
        
        Args:
            device: NTAG device to disconnect (if any)
            connection: pyscard connection to disconnect (if any)
        """
        self.logger.debug("Performing robust reset after write...")
        
        # Step 1: Explicitly disconnect active connections
        try:
            if device is not None:
                # For NTAG devices, try to disconnect the underlying connection
                if hasattr(device, '_connection'):
                    try:
                        device._connection.disconnect()
                        self.logger.debug("Disconnected NTAG device connection")
                    except Exception as e:
                        self.logger.debug(f"Error disconnecting device: {e}")
        except Exception as e:
            self.logger.debug(f"Error during device disconnect: {e}")
        
        try:
            if connection is not None:
                try:
                    connection.disconnect()
                    self.logger.debug("Disconnected pyscard connection")
                except Exception as e:
                    self.logger.debug(f"Error disconnecting connection: {e}")
        except Exception as e:
            self.logger.debug(f"Error during connection disconnect: {e}")
        
        # Step 2: Clear all tag references with lock
        with self._lock:
            # Clear all state
            old_tag_info = self.current_tag_info
            self.current_tag = None
            self.current_device = None
            self.current_connection = None
            self.current_tag_type = None
            
            # Keep tag_info temporarily for UI feedback, but mark as written
            if old_tag_info:
                old_tag_info['just_written'] = True
                self.current_tag_info = old_tag_info
            
            # Signal polling loop to reset its local state
            self._reset_requested = True
        
        # Step 3: Brief wait for connections to fully close
        time.sleep(0.1)
        
        # Step 4: Emit tag_removed signal to notify UI and reset polling loop state
        # This ensures the polling loop knows the tag is gone and resets its local variables
        self.tag_removed.emit()
        
        # Step 5: Additional brief wait to ensure state is fully reset
        time.sleep(0.1)
        
        self.logger.debug("Reset complete - ready for next tag")
    
    def set_batch_queue(self, urls) -> None:
        """
        Set the batch queue with a list of URLs.
        
        Args:
            urls: List of URL strings
        """
        with self._lock:
            self.batch_queue = [{'url': url, 'status': 'pending'} for url in urls]
            self.batch_queue_index = 0
            self.batch_mode_active = True
            self.logger.info(f"Batch queue set with {len(urls)} URLs")
    
    def get_batch_queue(self) -> list[dict]:
        """Get current batch queue state."""
        with self._lock:
            return self.batch_queue.copy()
    
    def get_current_queue_url(self) -> Optional[str]:
        """Get the current URL from the queue that should be written."""
        with self._lock:
            if not self.batch_mode_active or self.batch_queue_index >= len(self.batch_queue):
                return None
            item = self.batch_queue[self.batch_queue_index]
            if item['status'] == 'pending':
                return item['url']
            return None
    
    def mark_queue_item_complete(self, success: bool) -> None:
        """Mark current queue item as completed or failed."""
        with self._lock:
            if self.batch_queue_index < len(self.batch_queue):
                self.batch_queue[self.batch_queue_index]['status'] = 'completed' if success else 'failed'
                if success:
                    self.batch_queue_index += 1
                    # Auto-advance to next pending item
                    while (self.batch_queue_index < len(self.batch_queue) and 
                           self.batch_queue[self.batch_queue_index]['status'] != 'pending'):
                        self.batch_queue_index += 1
    
    def clear_batch_queue(self) -> None:
        """Clear the batch queue and exit batch mode."""
        with self._lock:
            self.batch_queue = []
            self.batch_queue_index = 0
            self.batch_mode_active = False
            self.logger.info("Batch queue cleared")
    
    def reset_batch_progress(self) -> None:
        """Reset all queue items to pending status."""
        with self._lock:
            for item in self.batch_queue:
                item['status'] = 'pending'
            self.batch_queue_index = 0
            self.logger.info("Batch progress reset")
    
    def write_url(self, url: Optional[str] = None, record_type: str = "URL") -> None:
        """
        Write a URL or text to the current NFC tag as an NDEF record.
        
        If batch mode is active and url is None, uses current queue URL.
        
        Args:
            url: URL or text string to write (optional if batch mode is active)
            record_type: Type of record ("URL" or "Text")
        """
        if not NFC_AVAILABLE:
            self.write_failed.emit("NFC library not available")
            return
        
        # If batch mode is active and no URL provided, get from queue
        if url is None:
            url = self.get_current_queue_url()
            if url is None:
                self.write_failed.emit("No URL available (batch queue may be empty or complete)")
                return
        
        with self._lock:
            tag_info = self.current_tag_info
            tag_type = self.current_tag_type
            tag = self.current_tag
            device = self.current_device
            connection = self.current_connection
        
        if tag_info is None:
            self.write_failed.emit("No tag detected")
            return
        
        # Validate tag before writing
        is_valid, warnings, errors = self.validate_tag_for_write(url)
        if not is_valid:
            error_msg = "; ".join(errors)
            if warnings:
                error_msg += " (Warnings: " + "; ".join(warnings) + ")"
            self.write_failed.emit(error_msg)
            return
        
        # Log warnings if any
        if warnings:
            for warning in warnings:
                self.logger.warning(warning)
        
        # Debug: Log what we have
        self.logger.debug(f"Write attempt - tag_type: {tag_type}, device: {device is not None}, connection: {connection is not None}")
        
        # If device is None but we have an NTAG tag, try to get it from the waiter
        if tag_type and tag_type.startswith('ntag') and device is None:
            self.logger.warning("Device is None for NTAG tag, attempting to get fresh device...")
            if NFCTAGGER_AVAILABLE and self.waiter is not None:
                try:
                    # Try to get a fresh device connection with longer timeout
                    # This gives the card time to be properly detected
                    fresh_device = self.waiter.get_next_connection(timeout=0.5)
                    if fresh_device is not None:
                        # Wait a moment for the connection to stabilize
                        time.sleep(0.2)
                        
                        # Verify the device can actually access a tag
                        try:
                            test_tag = fresh_device.get_tag()
                            if isinstance(test_tag, NTag):
                                # Try to read UID to verify connection is working
                                test_uid = test_tag.get_uid()
                                if test_uid is None or len(test_uid) == 0:
                                    raise Exception("Tag UID read failed - connection not ready")
                                
                                device = fresh_device
                                # Update the stored device reference
                                with self._lock:
                                    self.current_device = device
                                    # Also update tag and tag_info if we have them
                                    if test_tag:
                                        self.current_tag = test_tag
                                        tag_uid_hex = test_uid.hex().upper()
                                        tag_version = test_tag.get_tag_version(config=True)
                                        if self.current_tag_info is None:
                                            self.current_tag_info = self._identify_ntag(test_tag, tag_version, tag_uid_hex)
                                
                                self.logger.info(f"Successfully retrieved and verified fresh device for write (UID: {tag_uid_hex})")
                            else:
                                raise Exception("Device does not have a valid NTAG tag")
                        except Exception as verify_error:
                            self.logger.warning(f"Fresh device verification failed: {verify_error}")
                            # Don't use the device if verification fails
                            device = None
                    else:
                        self.logger.warning("No device available from waiter")
                except Exception as e:
                    self.logger.warning(f"Failed to get fresh device: {e}")
        
        try:
            # Step 1: Prepare write operation
            self.operation_status.emit("Preparing write operation...")
            self._process_ui_events()  # Allow UI to update
            time.sleep(0.1)  # Brief delay to ensure UI updates
            
            # Create NDEF message with URI or Text record
            if NFCTAGGER_AVAILABLE:
                ndef = NDEF()
                if record_type == "Text":
                    # Try to add text record - nfctagger may support this
                    try:
                        if hasattr(ndef, 'add_text'):
                            ndef.add_text(url)
                        else:
                            # Fallback: use URI record with text:// prefix
                            self.logger.warning("Text records not directly supported, using URI format")
                            ndef.add_uri(f"text://{url}")
                    except Exception as e:
                        self.logger.warning(f"Could not add text record: {e}, using URI format")
                        ndef.add_uri(f"text://{url}")
                else:
                    ndef.add_uri(url)
                ndef_bytes = ndef.bytes()
            else:
                # Fallback: create basic NDEF manually
                # This is a simplified version - should use ndeflib if available
                self.write_failed.emit("NDEF library not available")
                return
            
            # Check message size against tag capacity
            if len(ndef_bytes) > tag_info.get('capacity', 504):
                self.write_failed.emit(f"URL too long for tag (max {tag_info.get('capacity', 504)} bytes)")
                return
            
            # Write based on tag type
            # Check for any NTAG variant (ntag, ntag213, ntag215, ntag216)
            if tag_type and tag_type.startswith('ntag') and device is not None:
                # Get a fresh tag object right before writing to avoid stale references
                # This is critical when writing to a second card without relaunching
                max_retries = 3
                retry_count = 0
                last_error = None
                
                while retry_count < max_retries:
                    try:
                        # Small delay before getting tag to ensure connection is stable
                        if retry_count > 0:
                            self.operation_status.emit(f"Preparing write operation... (retry {retry_count + 1}/{max_retries})")
                            self._process_ui_events()  # Allow UI to update
                            time.sleep(0.3)  # Longer delay on retry
                        else:
                            time.sleep(0.1)  # Brief delay on first attempt
                        
                        # Get fresh tag object
                        fresh_tag = device.get_tag()
                        if not isinstance(fresh_tag, NTag):
                            raise Exception("Failed to get fresh NTAG object")
                        
                        # Verify tag is still present by reading UID
                        # Add a longer delay after formatting to let connection stabilize
                        time.sleep(0.4)  # Longer delay after format operation
                        
                        # Try to verify tag presence, but don't fail if it doesn't work
                        # Format operation itself is a good indicator the tag is present
                        tag_verified = False
                        uid_attempts = 0
                        max_uid_attempts = 2
                        
                        while uid_attempts < max_uid_attempts and not tag_verified:
                            try:
                                uid = fresh_tag.get_uid()
                                if uid is not None and len(uid) > 0:
                                    self.logger.debug(f"Tag verified present, UID: {uid.hex().upper()}")
                                    tag_verified = True
                                    break
                            except Exception as verify_error:
                                uid_attempts += 1
                                error_str = str(verify_error).lower()
                                if ("reset" in error_str or "unpowered" in error_str) and uid_attempts < max_uid_attempts:
                                    self.logger.debug(f"Tag UID verification failed (attempt {uid_attempts}/{max_uid_attempts}): {verify_error}")
                                    # Try to get fresh tag for retry
                                    try:
                                        time.sleep(0.3)
                                        if self.waiter:
                                            fresh_device = self.waiter.get_next_connection(timeout=0.5)
                                            if fresh_device:
                                                time.sleep(0.2)
                                                fresh_tag = fresh_device.get_tag()
                                                if isinstance(fresh_tag, NTag):
                                                    device = fresh_device
                                                    with self._lock:
                                                        self.current_device = device
                                                        self.current_tag = fresh_tag
                                                    self.logger.debug("Got fresh tag after verification failure")
                                    except:
                                        pass
                                else:
                                    # Not a reset error or max attempts reached - continue anyway
                                    self.logger.debug(f"Tag UID verification failed (non-critical): {verify_error}")
                                    break
                        
                        # Continue anyway - format was successful, so tag is present
                        
                        # Format/clear existing NDEF data before writing
                        # This prevents "Card was reset" errors when overwriting
                        try:
                            self.operation_status.emit("Step 1/4: Clearing existing tag data...")
                            self._process_ui_events()  # Allow UI to update
                            time.sleep(0.1)  # Brief delay to ensure UI updates
                            self._format_ntag_for_ndef(fresh_tag, tag_info)
                        except Exception as e:
                            # If formatting fails with "unpowered", retry
                            if "unpowered" in str(e).lower() and retry_count < max_retries - 1:
                                self.logger.warning(f"Format failed, card may have lost contact (attempt {retry_count + 1}/{max_retries})")
                                retry_count += 1
                                time.sleep(0.2)
                                continue
                            else:
                                self.logger.warning(f"Failed to format tag before write (may still work): {e}")
                                # Continue anyway - some tags might not need formatting
                        
                        # Write to NTAG using nfctagger with fresh tag object
                        # Wrap write in try-except to handle card reset errors
                        write_success = False
                        write_attempts = 0
                        max_write_attempts = 3
                        
                        while write_attempts < max_write_attempts and not write_success:
                            try:
                                if write_attempts == 0:
                                    self.operation_status.emit("Step 2/4: Writing data to tag...")
                                else:
                                    self.operation_status.emit(f"Step 2/4: Writing data to tag... (retry {write_attempts + 1}/{max_write_attempts})")
                                self._process_ui_events()  # Allow UI to update
                                time.sleep(0.1)  # Brief delay to ensure UI updates
                                fresh_tag.mem_write_user(ndef_bytes)
                                self.logger.info(f"Successfully wrote URL to NTAG tag: {url}")
                                write_success = True
                            except Exception as write_error:
                                write_attempts += 1
                                error_str = str(write_error).lower()
                                is_reset_error = "reset" in error_str or "unpowered" in error_str
                                
                                if is_reset_error and write_attempts < max_write_attempts:
                                    self.logger.warning(f"Write failed due to card reset (attempt {write_attempts}/{max_write_attempts}), retrying...")
                                    # Get fresh tag/device for retry
                                    try:
                                        time.sleep(0.5)  # Wait for card to stabilize
                                        if self.waiter:
                                            fresh_device = self.waiter.get_next_connection(timeout=0.5)
                                            if fresh_device:
                                                time.sleep(0.2)
                                                fresh_tag = fresh_device.get_tag()
                                                if isinstance(fresh_tag, NTag):
                                                    device = fresh_device
                                                    with self._lock:
                                                        self.current_device = device
                                                        self.current_tag = fresh_tag
                                                    self.logger.debug("Got fresh tag/device for write retry")
                                    except:
                                        pass
                                    time.sleep(0.3)  # Additional delay before retry
                                    continue
                                else:
                                    # Not a reset error or max attempts reached
                                    raise
                        
                        if not write_success:
                            raise Exception("Write failed after all retry attempts")
                        
                        # Verify the write by reading back
                        # Use longer delay after write to ensure connection is stable
                        time.sleep(0.4)  # Longer delay to ensure write is complete and connection is stable
                        
                        # Try to get a fresh tag object for verification (connection may have changed)
                        verify_tag = fresh_tag
                        try:
                            verify_device = device
                            if verify_device:
                                verify_tag = verify_device.get_tag()
                        except:
                            # Use existing tag if we can't get fresh one
                            pass
                        
                        self.operation_status.emit("Step 3/4: Verifying write...")
                        self._process_ui_events()  # Allow UI to update
                        time.sleep(0.1)  # Brief delay to ensure UI updates
                        verify_success, verify_message = self.verify_write(url, verify_tag, device)
                        
                        if verify_success:
                            self.logger.info(f"Write verification: {verify_message}")
                            self.write_verified.emit(True, verify_message)
                            self.operation_status.emit("Step 4/4: Write complete!")
                            self._process_ui_events()  # Allow UI to update
                        else:
                            self.logger.warning(f"Write verification failed: {verify_message}")
                            # Retry verification once
                            self.operation_status.emit("Step 3/4: Verifying write... (retry)")
                            self._process_ui_events()  # Allow UI to update
                            time.sleep(0.2)
                            verify_success, verify_message = self.verify_write(url, fresh_tag, device)
                            if verify_success:
                                self.logger.info(f"Write verification (retry): {verify_message}")
                                self.write_verified.emit(True, verify_message)
                                self.operation_status.emit("Step 4/4: Write complete!")
                                self._process_ui_events()  # Allow UI to update
                            else:
                                self.logger.error(f"Write verification failed after retry: {verify_message}")
                                self.write_verified.emit(False, verify_message)
                                self.operation_status.emit("Write complete (verification warning)")
                        
                        # Don't clear tag references immediately after write
                        # Keep them so read operations can work right after write
                        # They will be cleared when tag is removed
                        with self._lock:
                            # Keep tag and device references for read operations
                            # Only mark as written
                            if self.current_tag_info:
                                self.current_tag_info['just_written'] = True
                                # Update tag reference to the one we just wrote to
                                self.current_tag = fresh_tag
                                self.current_device = device
                        
                        # Mark queue item as complete if in batch mode
                        if self.batch_mode_active:
                            self.mark_queue_item_complete(True)
                        
                        self.write_success.emit()
                        return  # Success, exit retry loop
                        
                    except Exception as e:
                        last_error = e
                        error_str = str(e).lower()
                        
                        # Check if it's a retryable error (unpowered, reset, etc.)
                        is_retryable = any(term in error_str for term in [
                            "unpowered", "reset", "no smart card", "card was reset"
                        ])
                        
                        if is_retryable and retry_count < max_retries - 1:
                            retry_count += 1
                            # Provide user-friendly status message
                            if "unpowered" in error_str:
                                self.operation_status.emit(f"Card lost contact, retrying... (attempt {retry_count}/{max_retries}) - Keep card on reader")
                            else:
                                self.operation_status.emit(f"Write failed, retrying... (attempt {retry_count}/{max_retries})")
                            self.logger.warning(
                                f"Write failed (attempt {retry_count}/{max_retries}): {e}. "
                                "Retrying..."
                            )
                            self._process_ui_events()  # Allow UI to update
                            # Longer delay for unpowered errors to let card stabilize
                            delay = 0.8 if "unpowered" in error_str else 0.5
                            time.sleep(delay)
                            continue
                        else:
                            # Not retryable or max retries reached
                            error_msg = f"Failed to get fresh tag object or write: {str(e)}"
                            if retry_count >= max_retries - 1:
                                error_msg += f" (after {max_retries} attempts)"
                            self.logger.error(error_msg, exc_info=True)
                            self.write_failed.emit(error_msg)
                            return
                
                # If we get here, all retries failed
                if last_error:
                    # Mark queue item as failed if in batch mode
                    if self.batch_mode_active:
                        self.mark_queue_item_complete(False)
                    error_msg = f"Failed to write after {max_retries} attempts: {str(last_error)}"
                    self.logger.error(error_msg)
                    self.write_failed.emit(error_msg)
            elif tag_type == 'mifare_ultralight' and connection is not None:
                # Write to MIFARE Ultralight using pyscard
                self.operation_status.emit("Step 1/3: Clearing existing tag data...")
                QApplication.processEvents()
                time.sleep(0.1)
                self.operation_status.emit("Step 2/3: Writing data to tag...")
                QApplication.processEvents()
                time.sleep(0.1)
                if self._write_ndef_to_mifare_ultralight(connection, ndef_bytes):
                    self.logger.info(f"Successfully wrote URL to MIFARE Ultralight tag: {url}")
                    
                    # Note: Verification for MIFARE Ultralight would require reading back,
                    # which is more complex. For now, we'll skip verification for MIFARE tags.
                    # The write operation itself is the verification.
                    self.operation_status.emit("Step 3/3: Write complete!")
                    QApplication.processEvents()
                    self.write_verified.emit(True, "Write completed (MIFARE Ultralight)")
                    
                    # Mark queue item as complete if in batch mode
                    if self.batch_mode_active:
                        self.mark_queue_item_complete(True)
                    
                    # Perform robust reset after successful write
                    self._reset_after_write(None, connection)
                    
                    self.write_success.emit()
                else:
                    # Mark queue item as failed if in batch mode
                    if self.batch_mode_active:
                        self.mark_queue_item_complete(False)
                    self.write_failed.emit("Failed to write to MIFARE Ultralight tag")
            elif tag_type == 'mifare_classic' and connection is not None:
                # Write to MIFARE Classic using pyscard
                self.operation_status.emit("Step 1/3: Clearing existing tag data...")
                QApplication.processEvents()
                time.sleep(0.1)
                self.operation_status.emit("Step 2/3: Writing data to tag...")
                QApplication.processEvents()
                time.sleep(0.1)
                if self._write_ndef_to_mifare_classic(connection, ndef_bytes):
                    self.logger.info(f"Successfully wrote URL to MIFARE Classic tag: {url}")
                    
                    # Note: Verification for MIFARE Classic would require reading back,
                    # which is more complex. For now, we'll skip verification for MIFARE tags.
                    # The write operation itself is the verification.
                    self.operation_status.emit("Step 3/3: Write complete!")
                    QApplication.processEvents()
                    self.write_verified.emit(True, "Write completed (MIFARE Classic)")
                    
                    # Mark queue item as complete if in batch mode
                    if self.batch_mode_active:
                        self.mark_queue_item_complete(True)
                    
                    # Perform robust reset after successful write
                    self._reset_after_write(None, connection)
                    
                    self.write_success.emit()
                else:
                    # Mark queue item as failed if in batch mode
                    if self.batch_mode_active:
                        self.mark_queue_item_complete(False)
                    self.write_failed.emit("Failed to write to MIFARE Classic tag. Make sure the tag uses default keys (0xFFFFFFFFFFFF).")
            else:
                self.write_failed.emit(f"Unsupported tag type for writing: {tag_type}")
            
        except Exception as e:
            error_msg = f"Failed to write URL: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.write_failed.emit(error_msg)
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        self.stop_polling()
        if self.waiter is not None:
            try:
                self.waiter.stop()
            except:
                pass
            self.waiter = None
        if self.current_connection is not None:
            try:
                self.current_connection.disconnect()
            except:
                pass
            self.current_connection = None
    
    def verify_write(self, expected_url: str, tag=None, device=None):
        """
        Verify that a URL was successfully written to a tag by reading it back.
        
        Args:
            expected_url: The URL that should have been written
            tag: NTag instance (optional, will get from device if not provided)
            device: Device instance (optional, will use current if not provided)
        
        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            # Get tag if not provided
            if tag is None:
                if device is None:
                    with self._lock:
                        device = self.current_device
                        tag = self.current_tag
                
                if device is not None and tag is None:
                    try:
                        tag = device.get_tag()
                    except Exception as e:
                        return False, f"Could not get tag for verification: {e}"
            
            if tag is None or not isinstance(tag, NTag):
                return False, "No valid tag available for verification"
            
            # Read NDEF data from tag
            try:
                user_data = tag.mem_read_user()
                if len(user_data) == 0 or user_data[0] != 0x03:
                    return False, "No NDEF data found on tag"
                
                # Parse NDEF message
                ndef = NDEF.parse(user_data)
                if ndef is None:
                    return False, "Failed to parse NDEF message"
                
                # Extract URI from NDEF records
                read_url = None
                for record in ndef.records:
                    if hasattr(record, 'uri') and record.uri:
                        read_url = record.uri
                        break
                
                if read_url is None:
                    return False, "No URI record found in NDEF message"
                
                # Normalize URLs for comparison (remove trailing slashes, etc.)
                expected_normalized = expected_url.rstrip('/')
                read_normalized = read_url.rstrip('/')
                
                if expected_normalized == read_normalized:
                    return True, f"Verification successful: {read_url}"
                else:
                    return False, f"URL mismatch. Expected: {expected_url}, Read: {read_url}"
                    
            except Exception as e:
                return False, f"Error reading tag for verification: {str(e)}"
                
        except Exception as e:
            return False, f"Verification failed: {str(e)}"
    
    def read_tag_url(self) -> None:
        """
        Read the existing URL from the current NFC tag.
        Emits tag_read signal with URL and tag info.
        """
        if not NFC_AVAILABLE:
            self.tag_read.emit("", {})
            return
        
        # Try to get current tag info, but also try to get fresh connection if needed
        with self._lock:
            tag_info = self.current_tag_info
            tag_type = self.current_tag_type
            tag = self.current_tag
            device = self.current_device
            connection = self.current_connection
        
        # If we don't have a device but have tag_info, try to get a fresh connection
        if tag_info is not None and device is None:
            self.logger.debug("No device available, attempting to get fresh connection for read...")
            try:
                if NFCTAGGER_AVAILABLE and self.waiter is not None:
                    fresh_device = self.waiter.get_next_connection(timeout=0.8)
                    if fresh_device:
                        time.sleep(0.3)  # Increased delay for connection to stabilize
                        fresh_tag = fresh_device.get_tag()
                        if isinstance(fresh_tag, NTag):
                            device = fresh_device
                            # Update stored references
                            with self._lock:
                                self.current_device = device
                                self.current_tag = fresh_tag
                            self.logger.debug("Got fresh device for read operation")
            except Exception as e:
                self.logger.warning(f"Failed to get fresh device for read: {e}")
        
        if tag_info is None:
            self.logger.warning("No tag detected for reading")
            self.tag_read.emit("", {})
            return
        
        try:
            read_url = None
            
            if tag_type and tag_type.startswith('ntag'):
                # Try to get device if we don't have one
                if device is None:
                    if NFCTAGGER_AVAILABLE and self.waiter is not None:
                        try:
                            device = self.waiter.get_next_connection(timeout=0.8)
                            if device:
                                time.sleep(0.3)  # Increased delay for connection stabilization
                        except:
                            pass
                
                if device is None:
                    self.logger.error("No device connection available for reading")
                    self.tag_read.emit("", tag_info)
                    return
                
                # Get fresh tag object
                try:
                    fresh_tag = device.get_tag()
                    if not isinstance(fresh_tag, NTag):
                        raise Exception("Failed to get NTAG object")
                    
                    # Small delay to ensure tag connection is stable before reading
                    time.sleep(0.15)
                    
                    # Read NDEF data
                    user_data = fresh_tag.mem_read_user()
                    self.logger.debug(f"Read {len(user_data)} bytes from tag")
                    
                    if len(user_data) > 0:
                        # Check for NDEF TLV (0x03)
                        if user_data[0] == 0x03:
                            # Parse NDEF message
                            try:
                                ndef = NDEF.parse(user_data)
                                if ndef is None:
                                    self.logger.error("Failed to parse NDEF message")
                                    self.tag_read.emit("", tag_info)
                                    return
                                
                                # Extract URI or text from NDEF records
                                for record in ndef.records:
                                    if hasattr(record, 'uri') and record.uri:
                                        read_url = record.uri
                                        break
                                    elif hasattr(record, 'text') and record.text:
                                        # For text records, return the text
                                        read_url = record.text
                                        break
                                
                                if read_url:
                                    self.logger.info(f"Read URL/text from tag: {read_url}")
                                    self.tag_read.emit(read_url, tag_info)
                                else:
                                    self.logger.info("No URL/text found in NDEF records")
                                    self.tag_read.emit("", tag_info)
                            except Exception as parse_error:
                                self.logger.error(f"Failed to parse NDEF: {parse_error}")
                                self.tag_read.emit("", tag_info)
                        else:
                            self.logger.info("Tag does not contain NDEF data (first byte: 0x{:02X})".format(user_data[0] if len(user_data) > 0 else 0))
                            self.tag_read.emit("", tag_info)
                    else:
                        self.logger.info("Tag is empty (no data)")
                        self.tag_read.emit("", tag_info)
                        
                except Exception as e:
                    error_str = str(e).lower()
                    
                    # Check if it's a transient connection error (unpowered, reset, etc.)
                    is_transient = any(term in error_str for term in [
                        "unpowered", "reset", "no smart card", "card was reset", "card is unpowered"
                    ])
                    
                    if is_transient:
                        # Log as warning for transient errors - these are expected during normal operation
                        self.logger.warning(f"Transient connection error during read: {e}. Retrying...")
                    else:
                        # Log as error for unexpected errors
                        self.logger.error(f"Failed to read tag: {e}")
                    
                    # Retry with exponential backoff - try up to 3 times
                    max_retries = 3
                    retry_delay = 0.3  # Start with 300ms
                    
                    self.logger.info(f"Starting read retry sequence (up to {max_retries} attempts)...")
                    
                    for retry_attempt in range(max_retries):
                        try:
                            if NFCTAGGER_AVAILABLE and self.waiter is not None:
                                self.logger.info(f"Read retry attempt {retry_attempt + 1}/{max_retries} - waiting {retry_delay:.2f}s before retry...")
                                time.sleep(retry_delay)
                                
                                # Increase delay for next retry (exponential backoff)
                                retry_delay *= 1.5
                                
                                self.logger.debug(f"Attempting to get fresh connection for retry {retry_attempt + 1}...")
                                fresh_device = self.waiter.get_next_connection(timeout=0.8)
                                if fresh_device:
                                    self.logger.debug(f"Got fresh device, stabilizing connection...")
                                    time.sleep(0.3)  # Increased stabilization delay
                                    fresh_tag = fresh_device.get_tag()
                                    if isinstance(fresh_tag, NTag):
                                        # Additional delay to ensure tag connection is stable
                                        time.sleep(0.15)
                                        # Read data with error handling
                                        try:
                                            self.logger.debug(f"Attempting to read tag data on retry {retry_attempt + 1}...")
                                            user_data = fresh_tag.mem_read_user()
                                            if user_data and len(user_data) > 0 and user_data[0] == 0x03:
                                                # Parse NDEF with error handling
                                                try:
                                                    ndef = NDEF.parse(user_data)
                                                    if ndef is not None and hasattr(ndef, 'records'):
                                                        # Safely iterate records
                                                        for record in ndef.records:
                                                            try:
                                                                if hasattr(record, 'uri') and record.uri:
                                                                    read_url = record.uri
                                                                    break
                                                                elif hasattr(record, 'text') and record.text:
                                                                    read_url = record.text
                                                                    break
                                                            except Exception as record_error:
                                                                self.logger.warning(f"Error accessing record: {record_error}")
                                                                continue
                                                    if read_url:
                                                        self.logger.info(f"Successfully read URL/text from tag on retry {retry_attempt + 1}: {read_url}")
                                                        self.tag_read.emit(read_url, tag_info)
                                                        return
                                                    else:
                                                        self.logger.warning(f"Retry {retry_attempt + 1} succeeded but no URL found in NDEF records")
                                                        if retry_attempt < max_retries - 1:
                                                            break  # Continue to next retry
                                                except Exception as parse_error:
                                                    self.logger.error(f"Failed to parse NDEF during retry {retry_attempt + 1}: {parse_error}")
                                                    if retry_attempt < max_retries - 1:
                                                        break  # Continue to next retry
                                        except Exception as read_error:
                                            error_str = str(read_error).lower()
                                            is_transient_retry = any(term in error_str for term in [
                                                "unpowered", "reset", "no smart card", "card was reset", "card is unpowered"
                                            ])
                                            if is_transient_retry and retry_attempt < max_retries - 1:
                                                # Continue to next retry
                                                self.logger.warning(f"Transient error during retry {retry_attempt + 1}: {read_error}. Will retry again...")
                                                break  # Break out of inner try, continue to next retry attempt
                                            else:
                                                self.logger.error(f"Failed to read tag data during retry {retry_attempt + 1}: {read_error}")
                                                # If this was the last retry, we'll fall through to emit empty result
                                                break
                                    else:
                                        self.logger.warning(f"Retry {retry_attempt + 1}: Got device but tag is not NTAG")
                                        if retry_attempt < max_retries - 1:
                                            continue  # Try next retry
                                else:
                                    self.logger.warning(f"Retry {retry_attempt + 1}: Could not get fresh device connection")
                                    if retry_attempt < max_retries - 1:
                                        continue  # Try next retry
                        except Exception as retry_error:
                                            error_str = str(read_error).lower()
                                            is_transient_retry = any(term in error_str for term in [
                                                "unpowered", "reset", "no smart card", "card was reset", "card is unpowered"
                                            ])
                                            if is_transient_retry and retry_attempt < max_retries - 1:
                                                # Continue to next retry
                                                self.logger.warning(f"Transient error during retry {retry_attempt + 1}: {read_error}. Will retry again...")
                                                break  # Break out of inner try, continue to next retry attempt
                                            else:
                                                self.logger.error(f"Failed to read tag data during retry {retry_attempt + 1}: {read_error}")
                                                # If this was the last retry, we'll fall through to emit empty result
                                                break
                        except Exception as retry_error:
                            error_str = str(retry_error).lower()
                            is_transient_retry = any(term in error_str for term in [
                                "unpowered", "reset", "no smart card", "card was reset", "card is unpowered"
                            ])
                            if is_transient_retry and retry_attempt < max_retries - 1:
                                # Continue to next retry
                                self.logger.warning(f"Transient error during retry connection {retry_attempt + 1}: {retry_error}. Will retry again...")
                                continue
                            else:
                                self.logger.error(f"Error during read retry {retry_attempt + 1}: {retry_error}")
                                if retry_attempt < max_retries - 1:
                                    continue  # Try next retry
                    
                    # All retries exhausted
                    self.logger.warning(f"Failed to read tag after {max_retries} retry attempts")
                    self.tag_read.emit("", tag_info)
            else:
                self.logger.warning(f"Tag type {tag_type} not supported for reading")
                self.tag_read.emit("", tag_info)
                
        except Exception as e:
            error_msg = f"Error reading tag URL: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            self.tag_read.emit("", {})
    
    def validate_tag_for_write(self, url: str):
        """
        Validate that the current tag is suitable for writing the given URL.
        
        Args:
            url: URL string to validate
        
        Returns:
            tuple: (is_valid: bool, warnings: list[str], errors: list[str])
        """
        warnings = []
        errors = []
        
        with self._lock:
            tag_info = self.current_tag_info
            tag_type = self.current_tag_type
        
        if tag_info is None:
            errors.append("No tag detected")
            return False, warnings, errors
        
        # Check if tag is writable
        if not tag_info.get('writable', True):
            errors.append("Tag is not writable (may be locked)")
            return False, warnings, errors
        
        # Check capacity
        capacity = tag_info.get('capacity', 504)
        # Estimate URL size (rough calculation)
        # NDEF overhead: ~10 bytes + URL length
        estimated_size = len(url.encode('utf-8')) + 20
        
        if estimated_size > capacity:
            errors.append(f"URL too long for tag (estimated {estimated_size} bytes, capacity: {capacity} bytes)")
            return False, warnings, errors
        
        # Check for existing data
        if tag_info.get('has_ndef', False):
            warnings.append("Tag contains existing NDEF data (will be overwritten)")
        
        # Check tag type support
        if tag_type not in ['ntag', 'ntag213', 'ntag215', 'ntag216', 'mifare_ultralight', 'mifare_classic']:
            if tag_type and not tag_type.startswith('ntag'):
                warnings.append(f"Tag type {tag_type} may have limited support")
        
        is_valid = len(errors) == 0
        return is_valid, warnings, errors
    
    def __del__(self):
        """Cleanup on destruction."""
        self.cleanup()
