"""QR code scanning dialog."""

import logging
from pathlib import Path
from typing import Optional
from PyQt6.QtWidgets import QDialog, QMessageBox
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6 import uic

from ..qr.qr_scanner import QRScanner, QRScannerWorker


class QRScanDialog(QDialog):
    """Dialog for scanning QR codes from camera."""
    
    def __init__(self, parent=None, default_camera_index: Optional[int] = None, default_camera_name: Optional[str] = None, settings=None):
        """Initialize QR scan dialog.
        
        Args:
            parent: Parent widget
            default_camera_index: Preferred camera index
            default_camera_name: Preferred camera name (for better matching)
            settings: Settings object to save camera selection
        """
        super().__init__(parent)
        
        # Load UI from .ui file
        ui_file = Path(__file__).parent / "qr_dialog.ui"
        uic.loadUi(ui_file, self)
        
        self.scanner_worker: Optional[QRScannerWorker] = None
        self.logger = logging.getLogger(__name__)
        self.settings = settings
        
        # Set up preview label styling
        self.preview_label.setStyleSheet("background-color: black; color: white;")
        
        # Connect signals
        self.camera_combo.currentIndexChanged.connect(self._on_camera_changed)
        self.start_button.clicked.connect(self._start_camera)
        self.stop_button.clicked.connect(self._stop_camera)
        self.cancel_button.clicked.connect(self.reject)
        
        # Populate camera list
        self._populate_cameras(default_camera_index, default_camera_name)
        
        # Auto-start camera after a short delay
        QTimer.singleShot(100, self._auto_start_camera)
    
    def _populate_cameras(self, default_index: Optional[int] = None, default_name: Optional[str] = None) -> None:
        """Populate camera combo box with available cameras.
        
        Args:
            default_index: Preferred camera index
            default_name: Preferred camera name (for matching)
        """
        # Clear existing items first
        self.camera_combo.clear()
        
        cameras = QRScanner.get_available_cameras()
        if not cameras:
            self.camera_combo.addItem("No cameras found", None)
            self.start_button.setEnabled(False)
            return
        
        selected_index = 0
        best_match_score = -1
        
        for i, (index, name) in enumerate(cameras):
            # Store camera index as user data, display name as text
            self.camera_combo.addItem(name, index)
            
            # Calculate match score for this camera
            # Higher score = better match
            match_score = 0
            name_lower = name.lower()
            is_logitech = any(term in name_lower for term in [
                'logitech', 'c922', 'c920', 'c930', 'c270', 'c310', 'brio'
            ])
            is_virtual = any(term in name_lower for term in [
                'obs', 'virtual', 'screen', 'display'
            ])
            
            # Scoring:
            # 1. Exact match by index AND name: score 100
            # 2. Exact match by name: score 90
            # 3. Partial name match: score 60
            # 4. Match by index only: score 20
            # 5. Logitech camera (if no default): score 20
            # 6. Non-virtual camera (if no default): score 10
            # 7. Virtual camera: score -10 (penalty)
            
            # Names are stable across reconnects; indices shift as devices
            # come and go - so name matches must always outrank index-only
            # matches, or a stale saved index can select the wrong camera.
            if default_index is not None and default_name is not None:
                if index == default_index and name == default_name:
                    match_score = 100  # Perfect match
                elif default_name.lower() == name_lower:
                    match_score = 90  # Exact name match (index went stale)
                elif default_name.lower() in name_lower or name_lower in default_name.lower():
                    match_score = 60  # Partial name match
                elif index == default_index:
                    match_score = 20  # Index-only match (weakest signal)
            elif default_index is not None:
                if index == default_index:
                    match_score = 20
            elif default_name is not None:
                if default_name.lower() == name_lower:
                    match_score = 90
                elif default_name.lower() in name_lower or name_lower in default_name.lower():
                    match_score = 60
            
            # If no default specified, prefer Logitech and avoid virtual
            if default_index is None and default_name is None:
                if is_logitech:
                    match_score = 20
                elif not is_virtual:
                    match_score = 10
                else:
                    match_score = -10  # Penalty for virtual cameras
            
            # Update selected index if this is a better match
            if match_score > best_match_score:
                best_match_score = match_score
                selected_index = i
        
        self.camera_combo.setCurrentIndex(selected_index)
        self.logger.debug(f"Selected camera: {cameras[selected_index][1]} (index {cameras[selected_index][0]})")
    
    def _auto_start_camera(self) -> None:
        """Automatically start the camera when dialog opens."""
        if self.camera_combo.count() > 0 and self.camera_combo.currentData() is not None:
            self._start_camera()
    
    def _on_camera_changed(self) -> None:
        """Handle camera selection change - stop previous camera and start new one."""
        # Stop previous camera if running
        was_running = False
        if self.scanner_worker and self.scanner_worker.isRunning():
            was_running = True
            self._stop_camera()
        
        # Save camera selection to settings
        if self.settings:
            camera_index = self.camera_combo.currentData()
            camera_name = self.camera_combo.currentText()
            if camera_index is not None:
                self.settings.set_default_camera(camera_index, camera_name)
                self.logger.debug(f"Selected camera: {camera_name} (Index {camera_index})")
        
        # Automatically start the newly selected camera if one was running before
        if was_running:
            camera_index = self.camera_combo.currentData()
            if camera_index is not None:
                # Use a longer delay to ensure previous camera thread is fully stopped and released
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(300, self._start_camera)
    
    def _start_camera(self) -> None:
        """Start camera and begin scanning."""
        camera_index = self.camera_combo.currentData()
        camera_text = self.camera_combo.currentText()
        
        if camera_index is None:
            QMessageBox.warning(self, "No Camera", "Please select a valid camera.")
            return
        
        # Re-resolve the index in case devices changed since detection
        camera_index = QRScanner.resolve_camera_index(camera_text, camera_index)
        
        # Log which camera is being started for debugging
        self.logger.info(f"Starting camera: {camera_text} (Index {camera_index})")
        
        # Stop any existing scanner
        if self.scanner_worker:
            self._stop_camera()
        
        # Create and start scanner worker with the camera index from combo box data
        self.scanner_worker = QRScannerWorker(camera_index)
        self.scanner_worker.frame_ready.connect(self._on_frame_ready)
        self.scanner_worker.qr_decoded.connect(self._on_qr_decoded)
        self.scanner_worker.error_occurred.connect(self._on_error)
        self.scanner_worker.start()
        
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText(f"Using camera: {camera_text}")
    
    def _stop_camera(self) -> None:
        """Stop camera and scanning."""
        if self.scanner_worker:
            # Disconnect signals first to prevent any callbacks during shutdown
            try:
                self.scanner_worker.frame_ready.disconnect()
                self.scanner_worker.qr_decoded.disconnect()
                self.scanner_worker.error_occurred.disconnect()
            except:
                pass
            
            # Stop the worker
            self.scanner_worker.stop()
            
            # Wait for thread to finish, but don't block indefinitely
            if not self.scanner_worker.wait(3000):  # Wait up to 3 seconds
                self.logger.warning("Camera worker thread did not stop within timeout")
                # Terminate if it's still running (last resort)
                if self.scanner_worker.isRunning():
                    self.scanner_worker.terminate()
                    self.scanner_worker.wait(1000)
            
            self.scanner_worker = None
        
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.preview_label.setText("Camera stopped")
        self.preview_label.setStyleSheet("background-color: black; color: white;")
    
    @pyqtSlot(QImage)
    def _on_frame_ready(self, image: QImage) -> None:
        """Handle new frame from camera."""
        # Scale image to fit preview label while maintaining aspect ratio
        pixmap = QPixmap.fromImage(image)
        scaled_pixmap = pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled_pixmap)
    
    @pyqtSlot(str)
    def _on_qr_decoded(self, data: str) -> None:
        """Handle successfully decoded QR code."""
        # Validate that it's a URL
        data = data.strip()
        
        # Basic URL validation
        if not data:
            self.status_label.setText("QR code does not contain a valid URL")
            return
        
        # Store the decoded URL and accept dialog
        self.decoded_url = data
        self._stop_camera()
        self.accept()
    
    @pyqtSlot(str)
    def _on_error(self, error_msg: str) -> None:
        """Handle scanner errors."""
        self.logger.error(f"QR scanner error: {error_msg}")
        self.status_label.setText(f"Error: {error_msg}")
        QMessageBox.warning(self, "Scanner Error", f"An error occurred: {error_msg}")
        self._stop_camera()
    
    def get_decoded_url(self) -> Optional[str]:
        """Get the decoded URL if dialog was accepted."""
        return getattr(self, 'decoded_url', None)
    
    def closeEvent(self, event) -> None:
        """Ensure camera is released when dialog closes."""
        self._stop_camera()
        super().closeEvent(event)

