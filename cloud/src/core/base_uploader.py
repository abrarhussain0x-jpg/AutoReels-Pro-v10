"""base_uploader.py v8.0"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class UploadResult:
    success: bool
    post_id: str  = ""
    url:     str  = ""
    error:   str  = ""


class BaseUploader(ABC):
    @abstractmethod
    def is_configured(self) -> bool: ...
    @abstractmethod
    def verify_token(self) -> bool: ...
    @abstractmethod
    def token_expires_in_days(self) -> int: ...
    @abstractmethod
    def upload(self, clip_path: Path, title: str, caption: str,
               hashtags: list, clip_num: int,
               thumbnail_path: Optional[Path] = None) -> UploadResult: ...
    def get_metrics(self, post_id: str) -> Optional[dict]:
        return None
