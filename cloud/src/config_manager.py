"""config_manager.py v8.0"""
import os
import re
from pathlib import Path

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

class ConfigError(Exception):
    pass

class ConfigManager:
    def __init__(self, path: Path):
        self.path = Path(path)
        if not self.path.exists():
            raise ConfigError(f"Config not found: {self.path}")
        raw = self.path.read_text(encoding="utf-8")
        raw = re.sub(r'\$\{(\w+)\}', lambda m: os.environ.get(m.group(1), ""), raw)
        if _HAS_YAML:
            self.data = yaml.safe_load(raw) or {}
        else:
            raise ConfigError("PyYAML not installed — run: pip install PyYAML")

    @property
    def config(self):
        return self.data

    def get(self, key, default=None):
        return self.data.get(key, default)

    def validate(self):
        if not self.data.get("channels"):
            raise ConfigError("No channels configured")
