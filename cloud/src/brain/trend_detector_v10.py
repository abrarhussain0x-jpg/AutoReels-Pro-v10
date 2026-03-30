"""
trend_detector_v10.py — Free trending topic detector.
Scrapes YouTube trending page with yt-dlp to find what's viral NOW.
Feeds trend data into content gen for more relevant captions + hooks.
No API key. No cost. Runs before each pipeline cycle.
"""
from __future__ import annotations
import json, logging, re, subprocess, time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

log = logging.getLogger(__name__)

TRENDING_URLS = {
    "movie":       "https://www.youtube.com/feed/trending?bp=4gINGgt5dG1hX2NoYXJ0cw%3D%3D",
    "gaming":      "https://www.youtube.com/feed/trending?bp=4gIcGhpnYW1pbmdfY29ycHVzX21vc3Rfd2F0Y2hlZA%3D%3D",
    "general":     "https://www.youtube.com/feed/trending",
}

STOP_WORDS = {
    "the","a","an","is","in","on","at","to","for","of","and","or","but",
    "it","this","that","with","from","by","as","we","you","i","my","your",
    "he","she","they","be","was","are","were","been","have","has","had",
}


@dataclass
class TrendData:
    keywords: List[str] = field(default_factory=list)
    titles:   List[str] = field(default_factory=list)
    fetched_at: float   = 0.0
    source: str         = ""

    @property
    def is_fresh(self) -> bool:
        return (time.time() - self.fetched_at) < 3600   # 1 hour cache


class TrendDetectorV10:
    """Fetches YouTube trending data and extracts keywords."""

    def __init__(self, niche: str = "movie", cookies_file: str = "",
                 cache_path: Optional[Path] = None):
        self.niche       = niche
        self.cookies     = cookies_file
        self.cache_path  = Path(cache_path) if cache_path else None
        self._cache: Optional[TrendData] = self._load_cache()

    def get_trending_keywords(self, max_kw: int = 15) -> List[str]:
        """Return trending keywords for current niche. Uses cache if fresh."""
        if self._cache and self._cache.is_fresh:
            return self._cache.keywords[:max_kw]

        data = self._fetch()
        if data:
            self._cache = data
            self._save_cache(data)
            return data.keywords[:max_kw]

        # Fallback static trending keywords per niche
        return self._static_fallback()[:max_kw]

    def get_trending_titles(self) -> List[str]:
        """Return raw trending video titles."""
        if self._cache and self._cache.is_fresh:
            return self._cache.titles
        return []

    def _fetch(self) -> Optional[TrendData]:
        """Fetch trending via yt-dlp flat playlist."""
        url = TRENDING_URLS.get(self.niche, TRENDING_URLS["general"])
        cmd = [
            "yt-dlp", "--flat-playlist", "--dump-json",
            "--playlist-end", "25", "--no-warnings",
        ]
        if self.cookies and Path(self.cookies).exists():
            cmd += ["--cookies", self.cookies]
        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            titles = []
            for line in result.stdout.splitlines():
                try:
                    data = json.loads(line)
                    title = data.get("title") or data.get("fulltitle", "")
                    if title:
                        titles.append(title)
                except Exception:
                    continue

            if not titles:
                return None

            keywords = self._extract_keywords(titles)
            log.info("[TrendDetector] fetched %d titles, %d keywords",
                     len(titles), len(keywords))
            return TrendData(keywords=keywords, titles=titles,
                             fetched_at=time.time(), source="youtube_trending")

        except FileNotFoundError:
            log.debug("[TrendDetector] yt-dlp not available")
            return None
        except Exception as e:
            log.debug("[TrendDetector] fetch error: %s", e)
            return None

    def _extract_keywords(self, titles: List[str]) -> List[str]:
        """Extract most common meaningful words from trending titles."""
        words = []
        for title in titles:
            clean = re.sub(r'[^\w\s]', ' ', title.lower())
            for word in clean.split():
                if len(word) >= 4 and word not in STOP_WORDS:
                    words.append(word)
        counter = Counter(words)
        return [word for word, _ in counter.most_common(30)]

    def _static_fallback(self) -> List[str]:
        fallbacks = {
            "movie":       ["explained","recap","plot twist","ending","hidden","secret","real","film"],
            "anime":       ["episode","season","arc","power","battle","reveal","manga","weekly"],
            "kdrama":      ["episode","season","romance","plot","twist","finale","react","recap"],
            "horror":      ["scary","ghost","haunted","terrifying","nightmare","paranormal","curse"],
            "documentary": ["truth","history","facts","revealed","secret","real story","exposed"],
            "general":     ["viral","trending","shocking","amazing","unbelievable","incredible"],
        }
        return fallbacks.get(self.niche, fallbacks["general"])

    def _save_cache(self, data: TrendData):
        if not self.cache_path:
            return
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({
                "keywords": data.keywords,
                "titles": data.titles,
                "fetched_at": data.fetched_at,
                "source": data.source,
            }))
        except Exception:
            pass

    def _load_cache(self) -> Optional[TrendData]:
        if not self.cache_path or not self.cache_path.exists():
            return None
        try:
            d = json.loads(self.cache_path.read_text())
            return TrendData(**d)
        except Exception:
            return None
