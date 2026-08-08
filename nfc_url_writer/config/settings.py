"""Configuration management for NFC URL Writer."""

import json
import os
from pathlib import Path
from typing import Optional


class Settings:
    """Manages application settings stored in a JSON config file."""
    
    def __init__(self):
        """Initialize settings and load from config file."""
        # Determine config directory based on platform
        if os.name == 'nt':  # Windows
            # Use AppData\Roaming on Windows
            appdata = os.getenv('APPDATA', Path.home() / 'AppData' / 'Roaming')
            config_dir = Path(appdata) / "NFCUrlWriter"
        else:  # macOS and Linux
            config_dir = Path.home() / "Library" / "Application Support" / "NFCUrlWriter"
        
        config_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = config_dir / "config.json"
        
        # Default settings
        self.last_written_url: Optional[str] = None
        self.default_camera_index: Optional[int] = None
        self.default_camera_name: Optional[str] = None  # Store camera name for better matching
        self.auto_add_https: bool = True
        self.clear_url_after_write: bool = True  # Clear URL input field after successful write
        self.auto_read_on_detect: bool = True  # Automatically read tag when detected
        self.auto_read_after_write: bool = True  # Automatically read tag after successful write
        self.recent_urls = []  # List of recent URLs (max 20)
        self.auto_start_camera: bool = True
        self.notify_on_success: bool = True
        self.notify_on_verify: bool = True
        self.log_level: str = "INFO"
        self.url_prefix: str = "https://"
        self.dark_mode: Optional[bool] = None  # None = auto-detect, True/False = manual
        
        self.load()
    
    def load(self) -> None:
        """Load settings from config file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.last_written_url = data.get('last_written_url')
                    self.default_camera_index = data.get('default_camera_index')
                    self.default_camera_name = data.get('default_camera_name')
                    self.auto_add_https = data.get('auto_add_https', True)
                    self.clear_url_after_write = data.get('clear_url_after_write', True)
                    self.auto_read_on_detect = data.get('auto_read_on_detect', True)
                    self.auto_read_after_write = data.get('auto_read_after_write', True)
                    self.recent_urls = data.get('recent_urls', [])
                    # Ensure recent_urls is a list and limit to 20
                    if not isinstance(self.recent_urls, list):
                        self.recent_urls = []
                    self.recent_urls = self.recent_urls[:20]
                    self.auto_start_camera = data.get('auto_start_camera', True)
                    self.notify_on_success = data.get('notify_on_success', True)
                    self.notify_on_verify = data.get('notify_on_verify', True)
                    self.log_level = data.get('log_level', 'INFO')
                    self.url_prefix = data.get('url_prefix', 'https://')
                    dark_mode_val = data.get('dark_mode')
                    self.dark_mode = dark_mode_val if dark_mode_val is not None else None
            except (json.JSONDecodeError, IOError) as e:
                # If config is corrupted, use defaults
                print(f"Warning: Could not load config: {e}")
    
    def save(self) -> None:
        """Save current settings to config file."""
        data = {
            'last_written_url': self.last_written_url,
            'default_camera_index': self.default_camera_index,
            'default_camera_name': self.default_camera_name,
            'auto_add_https': self.auto_add_https,
            'clear_url_after_write': self.clear_url_after_write,
            'auto_read_on_detect': self.auto_read_on_detect,
            'auto_read_after_write': self.auto_read_after_write,
            'recent_urls': self.recent_urls,
            'auto_start_camera': self.auto_start_camera,
            'notify_on_success': self.notify_on_success,
            'notify_on_verify': self.notify_on_verify,
            'log_level': self.log_level,
            'url_prefix': self.url_prefix,
            'dark_mode': self.dark_mode
        }
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            print(f"Error: Could not save config: {e}")
    
    def set_last_written_url(self, url: str) -> None:
        """Set and save the last written URL."""
        self.last_written_url = url
        self.save()
    
    def set_default_camera_index(self, index: Optional[int]) -> None:
        """Set and save the default camera index."""
        self.default_camera_index = index
        self.save()
    
    def set_default_camera(self, index: Optional[int], name: Optional[str] = None) -> None:
        """Set and save the default camera index and name."""
        self.default_camera_index = index
        self.default_camera_name = name
        self.save()
    
    def set_auto_add_https(self, enabled: bool) -> None:
        """Set and save the auto-add-https setting."""
        self.auto_add_https = enabled
        self.save()
    
    def add_recent_url(self, url: str) -> None:
        """Add a URL to recent URLs list (max 20)."""
        if not url:
            return
        
        # Remove if already exists (to move to top)
        if url in self.recent_urls:
            self.recent_urls.remove(url)
        
        # Add to beginning
        self.recent_urls.insert(0, url)
        
        # Limit to 20
        self.recent_urls = self.recent_urls[:20]
        
        self.save()
    
    def get_recent_urls(self):
        """Get list of recent URLs."""
        return self.recent_urls.copy()
    
    def clear_recent_urls(self) -> None:
        """Clear all recent URLs."""
        self.recent_urls = []
        self.save()

