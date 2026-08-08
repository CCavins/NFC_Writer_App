"""QR code scanner using OpenCV and pyzbar."""

import cv2
import logging
from typing import Optional, List, Tuple
from PyQt6.QtCore import QObject, pyqtSignal, QThread
from PyQt6.QtGui import QImage

try:
    from pyzbar.pyzbar import decode
    PYZBAR_AVAILABLE = True
except ImportError:
    PYZBAR_AVAILABLE = False
    decode = None
    logging.warning("pyzbar not available")

from . import macos_cameras


class QRScannerWorker(QThread):
    """Worker thread for QR code scanning from camera."""
    
    # Signals
    frame_ready = pyqtSignal(QImage)  # Emitted when a new frame is captured
    qr_decoded = pyqtSignal(str)  # Emitted when a QR code is successfully decoded
    error_occurred = pyqtSignal(str)  # Emitted on errors
    
    def __init__(self, camera_index: int = 0):
        """Initialize QR scanner worker."""
        super().__init__()
        self.camera_index = camera_index
        self.camera: Optional[cv2.VideoCapture] = None
        self.running = False
        self.logger = logging.getLogger(__name__)
    
    def run(self) -> None:
        """Main scanning loop running in background thread."""
        if not PYZBAR_AVAILABLE:
            self.error_occurred.emit("pyzbar library not available")
            return
        
        try:
            # Use AVFoundation backend on macOS for better camera handling
            import platform
            is_macos = platform.system() == 'Darwin'
            
            if is_macos:
                # On macOS, try to set properties before opening (some backends support this)
                # Create camera with specific backend
                self.camera = cv2.VideoCapture(self.camera_index, cv2.CAP_AVFOUNDATION)
            else:
                self.camera = cv2.VideoCapture(self.camera_index)
            
            if not self.camera.isOpened():
                self.error_occurred.emit(f"Could not open camera {self.camera_index}")
                return
            
            # Set camera properties: 720p (1280x720) at 30fps minimum
            # Set resolution first
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            
            # For macOS AVFoundation, FPS setting can be tricky
            # Try multiple approaches to get 30fps
            if is_macos:
                # AVFoundation property IDs (OpenCV constants)
                # Try setting FPS before reading frames
                fps_set = False
                
                # Method 1: Standard FPS property
                self.camera.set(cv2.CAP_PROP_FPS, 30)
                
                # Method 2: Try setting via mode (some cameras support preset modes)
                # CAP_PROP_MODE might help on some backends
                try:
                    # Try to set a mode that supports 30fps
                    # This is backend-specific and may not work on all cameras
                    pass
                except:
                    pass
                
                # Method 3: Try 60fps (may fall back to 30fps)
                actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
                if actual_fps < 30:
                    self.camera.set(cv2.CAP_PROP_FPS, 60)
                    actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
                
                # Method 4: Force a frame read to "activate" the settings
                # Sometimes settings only take effect after first frame
                ret, test_frame = self.camera.read()
                if ret:
                    # Re-check FPS after first frame
                    actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
            else:
                # Non-macOS: standard FPS setting
                self.camera.set(cv2.CAP_PROP_FPS, 30)
                actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
            
            # Verify the settings were applied
            actual_width = self.camera.get(cv2.CAP_PROP_FRAME_WIDTH)
            actual_height = self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT)
            actual_fps = self.camera.get(cv2.CAP_PROP_FPS)
            
            self.logger.info(f"Camera {self.camera_index} resolution: {int(actual_width)}x{int(actual_height)} @ {actual_fps:.1f}fps")
            
            if actual_fps < 30:
                self.logger.warning(
                    f"Camera {self.camera_index} running at {actual_fps:.1f}fps (target: 30fps minimum). "
                    "This may be a hardware limitation of the camera."
                )
                # Try one more time with a different approach
                if is_macos:
                    # Some cameras need the FPS set after opening and reading a frame
                    self.camera.set(cv2.CAP_PROP_FPS, 30)
                    # Read another frame to activate
                    ret, _ = self.camera.read()
                    if ret:
                        final_fps = self.camera.get(cv2.CAP_PROP_FPS)
                        if final_fps >= 30:
                            self.logger.info(f"FPS successfully set to {final_fps:.1f}fps after frame read")
                        else:
                            self.logger.warning(f"Camera hardware limitation: {final_fps:.1f}fps maximum")
            
            self.logger.info(f"Opened camera {self.camera_index}")
            
            # Frame rate measurement and optimization
            import time
            frame_count = 0
            qr_decode_count = 0
            fps_start_time = time.time()
            last_fps_log = fps_start_time
            
            # Optimize QR decoding: only decode every Nth frame to improve FPS
            # Decode every 2nd frame (still responsive but faster)
            qr_decode_interval = 2
            
            self.running = True
            
            while self.running:
                ret, frame = self.camera.read()
                if not ret:
                    break
                
                frame_count += 1
                current_time = time.time()
                
                # Log actual FPS every 5 seconds
                if current_time - last_fps_log >= 5.0:
                    elapsed = current_time - fps_start_time
                    if elapsed > 0:
                        actual_fps = frame_count / elapsed
                        qr_fps = qr_decode_count / elapsed if qr_decode_count > 0 else 0
                        self.logger.info(
                            f"Camera {self.camera_index} actual FPS: {actual_fps:.1f} "
                            f"(QR decode: {qr_fps:.1f}fps, measured over {elapsed:.1f}s)"
                        )
                    last_fps_log = current_time
                
                # Convert BGR to RGB for Qt
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb_frame.shape
                bytes_per_line = ch * w
                qt_image = QImage(rgb_frame.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
                
                # Emit frame for preview (always show all frames for smooth preview)
                self.frame_ready.emit(qt_image)
                
                # Try to decode QR code (only on every Nth frame to improve FPS)
                if frame_count % qr_decode_interval == 0:
                    qr_decode_count += 1
                    try:
                        decoded_objects = decode(frame)
                        if decoded_objects:
                            # Get the first decoded QR code
                            qr_data = decoded_objects[0].data.decode('utf-8')
                            self.qr_decoded.emit(qr_data)
                            # Don't break here - let the dialog handle stopping
                    except Exception as e:
                        # Continue scanning even if decode fails
                        self.logger.debug(f"QR decode error: {e}")
                
                # Minimal delay - let the camera run at its native rate
                # For 30fps we need ~33ms, but we'll let the camera and processing determine the rate
                # Only add a tiny delay to prevent 100% CPU usage
                self.msleep(5)  # 5ms delay allows up to 200fps, but camera/processing will limit it
        
        except Exception as e:
            self.logger.error(f"Error in QR scanner: {e}")
            self.error_occurred.emit(str(e))
        finally:
            self.stop()
    
    def stop(self) -> None:
        """Stop scanning and release camera."""
        self.running = False
        
        # Give the loop a moment to exit
        self.msleep(100)
        
        if self.camera is not None:
            try:
                # Release camera resources
                self.camera.release()
            except Exception as e:
                self.logger.debug(f"Error releasing camera: {e}")
            finally:
                self.camera = None


class QRScanner:
    """High-level QR scanner interface."""
    
    @staticmethod
    def _is_camera_excluded(name: str, model_id: Optional[str] = None,
                            device_type: Optional[str] = None) -> bool:
        """
        Check if a camera should be excluded from the list.
        
        Excludes ALL iPhone/iPad cameras (mobile devices), including
        Continuity Camera and Desk View. Regular UVC/USB webcams, built-in
        cameras, and virtual cameras are included for user selection.
        """
        # AVFoundation device types that are always the user's iPhone
        if device_type:
            type_lower = device_type.lower()
            if 'continuitycamera' in type_lower or 'deskviewcamera' in type_lower:
                return True
        
        mobile_terms = ['iphone', 'ipad', 'ipod', 'desk view']
        name_lower = (name or "").lower()
        if any(term in name_lower for term in mobile_terms):
            return True
        
        model_lower = (model_id or "").lower()
        if any(term in model_lower for term in mobile_terms):
            return True
        
        return False
    
    @staticmethod
    def get_available_cameras() -> List[Tuple[int, str]]:
        """
        Get list of available cameras with their names.
        
        Returns list of tuples: (index, name)
        Cameras are sorted by priority: Logitech > USB > Built-in > Virtual.
        
        This method does NOT open cameras, only detects them using system information.
        iPhone/iPad cameras (including Continuity Camera and Desk View) are
        filtered out. Built-in and virtual cameras are included for selection.
        """
        logger = logging.getLogger(__name__)
        
        # Preferred path (macOS): enumerate via AVFoundation. Device order
        # matches OpenCV indices exactly, no camera is ever opened, and
        # iPhones are excluded reliably by device type/model.
        avf_devices = macos_cameras.list_cameras()
        if avf_devices is not None:
            cameras = []
            for idx, dev in enumerate(avf_devices):
                if QRScanner._is_camera_excluded(dev['name'], dev['model'], dev['device_type']):
                    logger.info(
                        f"Excluding mobile camera at index {idx}: "
                        f"{dev['name']} (model: {dev['model']}, type: {dev['device_type']})"
                    )
                    continue
                cameras.append((idx, dev['name']))
            cameras.sort(key=QRScanner._camera_sort_key)
            logger.info(f"AVFoundation cameras: {cameras}")
            return cameras
        
        # Fallback path: system_profiler + OpenCV probing with heuristic
        # index mapping (less reliable; may briefly open cameras)
        cameras = []
        filtered_camera_info = []  # List of (name, model_id) tuples from system_profiler
        
        # Get camera information from system (macOS) without opening cameras
        system_profiler_success = False
        try:
            import platform
            if platform.system() == 'Darwin':  # macOS
                import subprocess
                import json
                try:
                    # Get camera names from system_profiler
                    result = subprocess.run(
                        ['system_profiler', 'SPCameraDataType', '-json'],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        data = json.loads(result.stdout)
                        if 'SPCameraDataType' in data:
                            system_profiler_success = True
                            for cam_data in data['SPCameraDataType']:
                                name = cam_data.get('_name', '')
                                model_id = cam_data.get('spcamera_model-id', '')
                                
                                # Filter out ALL iPhone/iPad cameras
                                if name:
                                    if QRScanner._is_camera_excluded(name, model_id):
                                        # Log excluded cameras for debugging
                                        logger = logging.getLogger(__name__)
                                        logger.debug(f"Excluded iPhone/iPad camera: {name} (model: {model_id})")
                                    else:
                                        filtered_camera_info.append((name, model_id))
                except Exception as e:
                    logging.getLogger(__name__).debug(f"Error getting camera info from system_profiler: {e}")
        except Exception as e:
            logging.getLogger(__name__).debug(f"Error in camera detection: {e}")
        
        # Map filtered cameras to OpenCV indices
        # IMPORTANT: We need to avoid opening iPhone cameras during detection
        # Strategy: Only test OpenCV indices that we think correspond to filtered cameras
        # On macOS, system_profiler order often matches OpenCV index order
        # So if we have 2 filtered cameras at system_profiler positions 0 and 1,
        # we only test OpenCV indices 0 and 1 (not 2, 3, etc. which might be iPhone)
        if filtered_camera_info:
            logger = logging.getLogger(__name__)
            num_filtered = len(filtered_camera_info)
            
            # Test a reasonable range of OpenCV indices
            # We'll test up to 10 indices to find all available cameras
            # This is safe because we're only testing if cameras are accessible, not streaming
            max_test_range = 10  # Test indices 0-9 (most systems have < 5 cameras)
            
            logger.debug(
                f"Testing OpenCV indices 0-{max_test_range-1} to find cameras "
                f"(found {num_filtered} cameras from system_profiler)"
            )
            
            # Test all OpenCV indices and collect information about each
            tested_cameras = []  # List of accessible OpenCV indices
            
            for test_idx in range(max_test_range):
                cap = None
                try:
                    # Create VideoCapture object (minimal activation - doesn't start streaming)
                    cap = cv2.VideoCapture(test_idx, cv2.CAP_AVFOUNDATION)
                    if cap.isOpened():
                        backend = cap.getBackendName()
                        if backend:  # Camera is accessible
                            tested_cameras.append(test_idx)
                            logger.debug(f"Found accessible camera at OpenCV index {test_idx}")
                except Exception as e:
                    logger.debug(f"Error testing OpenCV index {test_idx}: {e}")
                finally:
                    if cap is not None:
                        cap.release()
                        import time
                        time.sleep(0.05)  # Slightly longer delay to ensure proper release
            
            # Step 2: Map tested OpenCV indices to system_profiler cameras
            # IMPORTANT: The order may not match between OpenCV and system_profiler
            # We'll collect camera properties and match them more intelligently
            logger = logging.getLogger(__name__)
            
            # First, collect properties for all tested cameras
            camera_properties = []  # List of (index, width, height, fps) tuples
            for test_idx in tested_cameras:
                cap = None
                try:
                    cap = cv2.VideoCapture(test_idx, cv2.CAP_AVFOUNDATION)
                    if cap.isOpened():
                        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                        fps = cap.get(cv2.CAP_PROP_FPS)
                        camera_properties.append((test_idx, width, height, fps))
                        logger.info(f"Camera at OpenCV index {test_idx}: {width}x{height} @ {fps:.1f}fps")
                except Exception as e:
                    logger.debug(f"Error getting properties for camera at index {test_idx}: {e}")
                finally:
                    if cap is not None:
                        cap.release()
                        import time
                        time.sleep(0.05)
            
            # Now match cameras based on characteristics
            # Strategy: Match by resolution hints and camera type
            mapped_cameras = []  # List of (index, name) tuples
            used_indices = set()
            used_names = set()
            
            # Sort filtered cameras by priority (built-in first, then others, virtual last)
            sorted_cameras = sorted(filtered_camera_info, key=lambda x: (
                0 if any(term in x[0].lower() for term in ['macbook', 'facetime', 'built-in', 'builtin', 'integrated', 'internal']) else
                1 if any(term in x[0].lower() for term in ['obs', 'virtual', 'screen', 'display']) else
                2,  # Other cameras
                x[0].lower()
            ))
            
            # Match cameras: try to match by characteristics, fallback to positional
            for name, model_id in sorted_cameras:
                if name in used_names or QRScanner._is_camera_excluded(name, model_id):
                    continue
                
                name_lower = name.lower()
                is_builtin = any(term in name_lower for term in [
                    'macbook', 'facetime', 'built-in', 'builtin', 'integrated', 'internal'
                ])
                is_virtual = any(term in name_lower for term in [
                    'obs', 'virtual', 'screen', 'display'
                ])
                
                # Try to find best matching OpenCV index
                best_match_idx = None
                best_match_score = -1
                
                for test_idx, width, height, fps in camera_properties:
                    if test_idx in used_indices:
                        continue
                    
                    score = 0
                    total_pixels = width * height
                    
                    # Match by resolution and FPS characteristics
                    # Based on actual usage when cameras are opened:
                    # - MacBook Pro Camera at OpenCV index 0: shows 1280x720 @ 30fps when opened
                    # - OBS Virtual Camera at OpenCV index 1: shows 1920x1080 @ 60fps when opened
                    # During detection, properties may differ:
                    # - Index 0 during detection: 1920x1080 @ 30.0fps (but opens as 720p @ 30fps) = MacBook Pro
                    # - Index 1 during detection: 1920x1080 @ 60.0fps (opens as 1080p @ 60fps) = OBS Virtual
                    # So we need to match based on what we see during detection
                    if is_builtin:
                        # Built-in cameras: Actually at OpenCV index 0
                        # During detection shows 30fps (medium), when opened shows 720p @ 30fps
                        # Prefer medium FPS during detection (30fps) and lower index
                        if fps <= 35 and fps >= 25:  # Medium FPS during detection (30fps = MacBook Pro at index 0)
                            score = 100
                        elif fps <= 40:  # Medium-low FPS
                            score = 80
                        elif fps <= 60:  # Medium-high FPS
                            score = 40
                        else:  # Higher or lower FPS
                            score = 20
                        # Strongly prefer lower index (0) for built-in cameras
                        index_penalty = test_idx * 20  # Heavy penalty for higher indices
                        score -= index_penalty
                    elif is_virtual:
                        # Virtual cameras: Actually at OpenCV index 1
                        # During detection shows 60fps (higher), when opened shows 1080p @ 60fps
                        # Prefer higher FPS during detection (60fps) and higher index
                        if fps >= 60:  # High FPS during detection (60fps = OBS Virtual at index 1)
                            score = 100
                        elif fps >= 40:  # Medium-high FPS
                            score = 80
                        elif fps >= 30:  # Medium FPS
                            score = 40
                        else:  # Lower FPS
                            score = 20
                        # Strongly prefer higher index (1) for virtual cameras
                        index_bonus = test_idx * 20  # Heavy bonus for higher indices
                        score += index_bonus
                    else:
                        # Unknown type: medium score, slight preference for higher resolutions
                        if total_pixels >= 1920 * 1080:
                            score = 40
                        else:
                            score = 25
                    
                    if score > best_match_score:
                        best_match_score = score
                        best_match_idx = test_idx
                
                # If we found a match, use it; otherwise use first available
                if best_match_idx is not None:
                    # Find the resolution for logging
                    resolution_info = ""
                    for idx, w, h, f in camera_properties:
                        if idx == best_match_idx:
                            resolution_info = f" ({w}x{h} @ {f:.1f}fps)"
                            break
                    mapped_cameras.append((best_match_idx, name))
                    used_indices.add(best_match_idx)
                    used_names.add(name)
                    logger.info(f"Mapped OpenCV index {best_match_idx} to camera: {name}{resolution_info}")
                elif camera_properties:
                    # Fallback: use first available camera index
                    for test_idx, _, _, _ in camera_properties:
                        if test_idx not in used_indices:
                            mapped_cameras.append((test_idx, name))
                            used_indices.add(test_idx)
                            used_names.add(name)
                            logger.warning(f"Fallback: Mapped OpenCV index {test_idx} to camera: {name} (no better match found)")
                            break
            
            # Add mapped cameras to result
            for test_idx, name in mapped_cameras:
                cameras.append((test_idx, name))
            
            mapped_count = len(mapped_cameras)
            
            # Log info about mapping
            if mapped_count < len(tested_cameras):
                logger.warning(
                    f"Mapped {mapped_count} of {len(tested_cameras)} accessible cameras. "
                    f"Some OpenCV indices may not have matching system_profiler entries."
                )
            elif mapped_count < len(filtered_camera_info):
                logger.warning(
                    f"Mapped {mapped_count} of {len(filtered_camera_info)} system_profiler cameras. "
                    f"Some cameras from system_profiler may not be accessible via OpenCV."
                )
            
            if mapped_count < len(filtered_camera_info):
                logger.warning(
                    f"Only mapped {mapped_count} of {len(filtered_camera_info)} system_profiler cameras. "
                    f"Some cameras may not be accessible or may be at higher OpenCV indices."
                )
        else:
            # Fallback: if system_profiler didn't work or all cameras were filtered,
            # we can't safely detect cameras without potentially activating unwanted ones
            # Return empty list - user can manually specify camera if needed
            logger = logging.getLogger(__name__)
            if system_profiler_success:  # system_profiler worked but all were filtered
                logger.info(
                    "All detected cameras were filtered out (iPhone/iPad cameras only). "
                    "No other cameras found."
                )
            else:  # system_profiler failed
                logger.warning(
                    "Could not get camera info from system. "
                    "Camera detection skipped to avoid activating unwanted cameras."
                )
        
        cameras.sort(key=QRScanner._camera_sort_key)
        return cameras
    
    @staticmethod
    def _camera_sort_key(cam_tuple):
        """Sort priority: Logitech > other USB > built-in > virtual."""
        index, name = cam_tuple
        name_lower = name.lower()
        
        is_logitech = any(term in name_lower for term in [
            'logitech', 'c922', 'c920', 'c930', 'c270', 'c310', 'brio'
        ])
        is_builtin = any(term in name_lower for term in [
            'macbook', 'facetime', 'built-in', 'builtin',
            'integrated', 'internal'
        ])
        is_virtual = any(term in name_lower for term in [
            'obs', 'virtual', 'screen', 'display', 'webcamoid',
            'manycam', 'camo', 'epoccam', 'droidcam', 'snap camera',
            'zoom', 'teams', 'webex', 'skype'
        ])
        
        if is_logitech:
            return (-2, name_lower)  # Highest priority
        elif is_builtin:
            return (-1, name_lower)  # Medium-high priority
        elif is_virtual:
            return (1, name_lower)   # Lower priority (positive value)
        else:
            return (0, name_lower)   # Normal priority
    
    @staticmethod
    def resolve_camera_index(camera_name: str, fallback_index: int) -> int:
        """Re-resolve a camera's current OpenCV index by name.
        
        Continuity Cameras appearing or disappearing shifts OpenCV device
        indices, so the index stored at detection time can go stale. Called
        right before opening a camera to get its up-to-date index.
        """
        logger = logging.getLogger(__name__)
        avf_devices = macos_cameras.list_cameras()
        if avf_devices is None:
            return fallback_index
        for idx, dev in enumerate(avf_devices):
            if dev['name'] == camera_name:
                if idx != fallback_index:
                    logger.info(
                        f"Camera '{camera_name}' moved from index "
                        f"{fallback_index} to {idx}"
                    )
                return idx
        logger.warning(
            f"Camera '{camera_name}' not found during re-resolution; "
            f"using stored index {fallback_index}"
        )
        return fallback_index

