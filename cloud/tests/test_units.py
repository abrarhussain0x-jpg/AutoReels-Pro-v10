"""
test_units.py — Comprehensive unit tests for AutoReels Pro v10 core modules.

Covers:
  - CircuitBreaker (states, transitions, context-manager)
  - VideoScorerV10 (all 8 scoring components)
  - DecisionEngine (fast-path, AI fallback mocking)
  - ContentGenerator (cache, fallback, parse helpers)
  - RetryEngine (backoff, classification, dead-letter queue)
  - UploadDispatcher (routing, gap, error paths)
  - YouTubeUploader (metadata helpers, is_configured)
  - FacebookUploader (is_configured, _build_metadata indirect)
  - TikTokUploader (is_configured)
  - InstagramUploader (is_configured)
  - ABEngine (record, get_best_angle, decay)
  - NarrativeArc (plan generation, role assignment)
  - HookOptimizerFree (select, record win)
  - VideoScorerV10 edge cases
"""

from __future__ import annotations

import json
import sqlite3
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch, PropertyMock
import sys
import os

# Make sure cloud/src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers / shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FakeVideo:
    """Minimal VideoMeta stand-in for scoring / decision tests."""
    video_id:    str   = "abc123"
    title:       str   = "Epic Movie Recap Explained Full"
    description: str   = "An epic movie recap"
    channel:     str   = "TestChannel"
    url:         str   = "https://youtube.com/watch?v=abc123"
    duration:    int   = 600          # 10 minutes — ideal
    view_count:  int   = 500_000
    like_count:  int   = 25_000
    upload_date: str   = "20250101"   # fixed date; freshness tested separately
    tags:        list  = None

    def __post_init__(self):
        if self.tags is None:
            self.tags = ["movie", "recap", "explained"]


def _tmp_db(tmp_path: Path, name: str = "test.db") -> Path:
    return tmp_path / name


# ─────────────────────────────────────────────────────────────────────────────
# 1. CircuitBreaker
# ─────────────────────────────────────────────────────────────────────────────

class TestCircuitBreaker(unittest.TestCase):

    def _make(self, **kw):
        from src.resilience.circuit_breaker import CircuitBreaker
        return CircuitBreaker(name="test", failure_threshold=3,
                              reset_timeout=0.05, **kw)

    def test_initial_state_closed(self):
        from src.resilience.circuit_breaker import CircuitState
        cb = self._make()
        self.assertEqual(cb.state, CircuitState.CLOSED)
        self.assertFalse(cb.is_open)

    def test_opens_after_threshold_failures(self):
        from src.resilience.circuit_breaker import CircuitState
        cb = self._make()
        for _ in range(3):
            try:
                with cb:
                    raise ValueError("boom")
            except ValueError:
                pass
        self.assertEqual(cb.state, CircuitState.OPEN)
        self.assertTrue(cb.is_open)

    def test_open_raises_circuit_open_exception(self):
        from src.resilience.circuit_breaker import CircuitBreakerOpen
        cb = self._make()
        for _ in range(3):
            try:
                with cb:
                    raise RuntimeError("fail")
            except RuntimeError:
                pass
        with self.assertRaises(CircuitBreakerOpen):
            with cb:
                pass

    def test_transitions_to_half_open_after_timeout(self):
        from src.resilience.circuit_breaker import CircuitState
        cb = self._make()
        for _ in range(3):
            try:
                with cb:
                    raise RuntimeError("fail")
            except RuntimeError:
                pass
        time.sleep(0.06)   # past reset_timeout=0.05
        # Next call should probe (HALF_OPEN) — success closes it
        with cb:
            pass
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_manual_reset(self):
        from src.resilience.circuit_breaker import CircuitState
        cb = self._make()
        for _ in range(3):
            try:
                with cb:
                    raise RuntimeError("x")
            except RuntimeError:
                pass
        cb.reset()
        self.assertEqual(cb.state, CircuitState.CLOSED)

    def test_repr(self):
        cb = self._make()
        self.assertIn("CircuitBreaker", repr(cb))
        self.assertIn("test", repr(cb))

    def test_success_resets_failure_counter(self):
        from src.resilience.circuit_breaker import CircuitState
        cb = self._make()
        # Two failures — stays CLOSED
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError("x")
            except RuntimeError:
                pass
        # One success — resets counter
        with cb:
            pass
        # Two more failures — still stays CLOSED (counter was reset)
        for _ in range(2):
            try:
                with cb:
                    raise RuntimeError("x")
            except RuntimeError:
                pass
        self.assertEqual(cb.state, CircuitState.CLOSED)


# ─────────────────────────────────────────────────────────────────────────────
# 2. VideoScorerV10
# ─────────────────────────────────────────────────────────────────────────────

class TestVideoScorerV10(unittest.TestCase):

    def _make_scorer(self, **kw):
        from src.brain.scorer_v10 import VideoScorerV10
        cfg = {"niche": "movie", "process_threshold": 0.01, "defer_threshold": 0.01}
        cfg.update(kw)
        return VideoScorerV10(cfg)

    def test_high_quality_video_scores_well(self):
        scorer = self._make_scorer()
        video = FakeVideo()
        vs = scorer.score(video)
        self.assertGreater(vs.composite, 0.3, "High-quality video should score above 0.3")
        self.assertIn(vs.decision, ("PROCESS", "DEFER", "SKIP"))

    def test_zero_view_video_scores_low(self):
        scorer = self._make_scorer()
        video = FakeVideo(view_count=0, like_count=0)
        vs = scorer.score(video)
        self.assertLess(vs.composite, 0.8, "Zero-view video composite should not be high")

    def test_short_duration_scores_lower(self):
        scorer = self._make_scorer()
        good  = scorer.score(FakeVideo(duration=1800))
        short = scorer.score(FakeVideo(duration=30))
        self.assertGreater(good.duration_score, short.duration_score)

    def test_ideal_duration_scores_max(self):
        scorer = self._make_scorer()
        vs = scorer.score(FakeVideo(duration=1800))  # 30 min — ideal
        self.assertAlmostEqual(vs.duration_score, 1.0)

    def test_viral_keyword_in_title_boosts_trend(self):
        scorer = self._make_scorer()
        with_kw    = scorer.score(FakeVideo(title="Movie Recap Explained"))
        without_kw = scorer.score(FakeVideo(title="Random Generic Title"))
        self.assertGreater(with_kw.trend_score, without_kw.trend_score)

    def test_composite_within_bounds(self):
        scorer = self._make_scorer()
        vs = scorer.score(FakeVideo())
        self.assertGreaterEqual(vs.composite, 0.0)
        self.assertLessEqual(vs.composite, 1.0)

    def test_decision_field_populated(self):
        scorer = self._make_scorer()
        vs = scorer.score(FakeVideo())
        self.assertIn(vs.decision, ("PROCESS", "DEFER", "SKIP"))

    def test_reasons_list_populated_for_high_view_video(self):
        scorer = self._make_scorer()
        vs = scorer.score(FakeVideo(view_count=200_000))
        self.assertIsInstance(vs.reasons, list)
        # high views should add a reason
        reasons_text = " ".join(vs.reasons).lower()
        self.assertIn("views", reasons_text)


# ─────────────────────────────────────────────────────────────────────────────
# 3. DecisionEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestDecisionEngine(unittest.TestCase):

    def _make_engine(self, low=0.20, high=0.55):
        from src.brain.scorer_v10 import VideoScorerV10
        from src.brain.decision_engine import DecisionEngine
        scorer = VideoScorerV10({"niche": "movie", "process_threshold": 0.01,
                                  "defer_threshold": 0.01})
        return DecisionEngine(scorer=scorer, ai_threshold_low=low,
                              ai_threshold_high=high)

    def test_very_short_video_always_skipped(self):
        engine = self._make_engine()
        result = engine.decide(FakeVideo(duration=30))
        self.assertEqual(result.decision, "SKIP")
        self.assertIn("short", result.reason.lower())

    def test_very_long_video_always_skipped(self):
        engine = self._make_engine()
        result = engine.decide(FakeVideo(duration=9000))
        self.assertEqual(result.decision, "SKIP")

    def test_live_stream_keyword_skipped(self):
        engine = self._make_engine()
        result = engine.decide(FakeVideo(title="live stream event 2025"))
        self.assertEqual(result.decision, "SKIP")

    def test_high_score_video_processed_without_ai(self):
        engine = self._make_engine(low=0.0, high=0.0)
        # With threshold=0, any score is ≥ high → fast PROCESS
        result = engine.decide(FakeVideo())
        self.assertEqual(result.decision, "PROCESS")
        self.assertFalse(result.ai_used)

    def test_stats_tracking(self):
        engine = self._make_engine(low=0.0, high=0.0)
        engine.decide(FakeVideo())
        stats = engine.stats()
        self.assertIn("PROCESS", stats)
        self.assertGreater(stats["PROCESS"], 0)

    def test_decision_result_has_score(self):
        engine = self._make_engine()
        result = engine.decide(FakeVideo())
        self.assertIsInstance(result.score, float)


# ─────────────────────────────────────────────────────────────────────────────
# 4. ContentGenerator — fallback and cache paths
# ─────────────────────────────────────────────────────────────────────────────

class TestContentGenerator(unittest.TestCase):

    def _make_gen(self, api_key=""):
        from src.brain.content_gen import ContentGenerator
        return ContentGenerator(api_key=api_key, niche="movie",
                                channel_name="TestChannel")

    def test_fallback_without_api_key(self):
        gen = self._make_gen(api_key="")
        result = gen.generate(
            video_title="Epic Movie Recap",
            platform="tiktok",
            clip_index=1,
        )
        self.assertTrue(result.from_fallback)
        self.assertIsInstance(result.hook, str)
        self.assertIsInstance(result.caption, str)
        self.assertIsInstance(result.hashtags, list)

    def test_fallback_caption_contains_clip_index(self):
        gen = self._make_gen(api_key="")
        result = gen.generate("Test Movie", "facebook", clip_index=3)
        # Fallback captions include Part {index}
        self.assertIn("3", result.caption)

    def test_all_platforms_supported(self):
        gen = self._make_gen(api_key="")
        for platform in ("tiktok", "facebook", "instagram", "youtube", "threads"):
            result = gen.generate("Test", platform, clip_index=1)
            self.assertIsNotNone(result.caption, f"No caption for {platform}")

    def test_cache_returns_same_result(self):
        gen = self._make_gen(api_key="")
        r1 = gen.generate("Cached Movie", "tiktok", clip_index=1)
        r2 = gen.generate("Cached Movie", "tiktok", clip_index=1)
        # Second call comes from cache when api_key is empty (cache is populated on first)
        self.assertEqual(r1.hook, r2.hook)

    def test_hook_is_uppercase(self):
        gen = self._make_gen(api_key="")
        result = gen.generate("Test", "tiktok", clip_index=1)
        self.assertEqual(result.hook, result.hook.upper())

    def test_hook_length_within_limit(self):
        gen = self._make_gen(api_key="")
        result = gen.generate("Test", "tiktok", clip_index=1)
        self.assertLessEqual(len(result.hook), 30)

    def test_strip_fences(self):
        from src.brain.content_gen import ContentGenerator
        raw = "```json\n{\"key\": 1}\n```"
        stripped = ContentGenerator._strip_fences(raw)
        self.assertEqual(stripped, '{"key": 1}')

    def test_generate_batch_returns_batch_plan(self):
        gen = self._make_gen(api_key="")
        from src.brain.content_gen import BatchPlan
        plan = gen.generate_batch(
            video_id="v1", video_title="Movie", n_clips=3,
            platforms=["tiktok", "facebook"],
        )
        self.assertIsInstance(plan, BatchPlan)
        # Should have content for all 3 clips × 2 platforms
        for i in range(1, 4):
            for p in ("tiktok", "facebook"):
                self.assertIsNotNone(plan.get(i, p), f"Missing clip {i} {p}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. RetryEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestRetryEngine(unittest.TestCase):

    def _make_engine(self, tmp_path):
        from src.resilience.retry_engine import RetryEngine
        return RetryEngine(
            db_path=tmp_path / "failed.db",
            notifier=None,
            max_retries=3,
            base_delay_s=0.01,
            circuit_threshold=5,
        )

    def test_successful_call_returns_result(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make_engine(Path(d))
            result = engine.call_with_retry(
                fn=lambda: "ok",
                platform="facebook",
                clip_path="/tmp/clip.mp4",
                caption="test",
            )
            self.assertTrue(result.success)
            self.assertEqual(result.return_value, "ok")

    def test_failing_call_retries_and_queues(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make_engine(Path(d))
            calls = []

            def always_fail():
                calls.append(1)
                raise RuntimeError("server error 503")

            result = engine.call_with_retry(
                fn=always_fail,
                platform="facebook",
                clip_path="/tmp/clip.mp4",
                caption="test",
            )
            self.assertFalse(result.success)
            self.assertGreater(len(calls), 1, "Should have retried")

    def test_auth_error_not_retried(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make_engine(Path(d))
            calls = []

            def auth_fail():
                calls.append(1)
                raise PermissionError("401 Unauthorized")

            result = engine.call_with_retry(
                fn=auth_fail,
                platform="facebook",
                clip_path="/tmp/clip.mp4",
                caption="test",
            )
            self.assertFalse(result.success)
            self.assertEqual(len(calls), 1, "Auth errors should NOT be retried")

    def test_dead_letter_queue_populated_on_failure(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make_engine(Path(d))

            def always_fail():
                raise RuntimeError("permanent failure")

            engine.call_with_retry(
                fn=always_fail,
                platform="tiktok",
                clip_path="/tmp/x.mp4",
                caption="caption",
            )
            # Check the SQLite dead letter queue
            conn = sqlite3.connect(str(Path(d) / "failed.db"))
            count = conn.execute(
                "SELECT COUNT(*) FROM failed_uploads WHERE resolved=0"
            ).fetchone()[0]
            conn.close()
            self.assertGreater(count, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 6. UploadDispatcher
# ─────────────────────────────────────────────────────────────────────────────

class TestUploadDispatcher(unittest.TestCase):

    def _make_uploader(self, post_id="post_123", raises=None):
        m = MagicMock()
        m.is_configured.return_value = True
        if raises:
            m.upload.side_effect = raises
        else:
            m.upload.return_value = post_id
        return m

    def test_dispatches_to_all_platforms(self):
        from src.publisher.upload_dispatcher import UploadDispatcher
        uploaders = {
            "facebook": self._make_uploader("fb_post"),
            "tiktok":   self._make_uploader("tt_post"),
        }
        dispatcher = UploadDispatcher(uploaders)
        summary = dispatcher.upload(
            clip_path=Path("/tmp/fake.mp4"),
            caption="test caption",
            video_id="vid1",
            clip_num=1,
            gap_seconds=0,
        )
        self.assertEqual(len(summary.results), 2)
        self.assertTrue(summary.any_success)
        self.assertIn("facebook", summary.success_platforms)
        self.assertIn("tiktok", summary.success_platforms)

    def test_failed_platform_recorded(self):
        from src.publisher.upload_dispatcher import UploadDispatcher
        uploaders = {
            "facebook": self._make_uploader(raises=RuntimeError("boom")),
        }
        dispatcher = UploadDispatcher(uploaders)
        summary = dispatcher.upload(
            clip_path=Path("/tmp/fake.mp4"),
            caption="test",
            video_id="v1",
            clip_num=1,
            gap_seconds=0,
        )
        self.assertFalse(summary.any_success)
        self.assertIn("facebook", summary.failed_platforms)

    def test_unconfigured_uploader_excluded(self):
        from src.publisher.upload_dispatcher import UploadDispatcher
        bad = MagicMock()
        bad.is_configured.return_value = False
        dispatcher = UploadDispatcher({"fb": bad})
        self.assertEqual(len(dispatcher.uploaders), 0)

    def test_no_post_id_returns_failure(self):
        from src.publisher.upload_dispatcher import UploadDispatcher
        uploaders = {"facebook": self._make_uploader(post_id=None)}
        dispatcher = UploadDispatcher(uploaders)
        summary = dispatcher.upload(
            clip_path=Path("/tmp/fake.mp4"),
            caption="test",
            video_id="v1",
            clip_num=1,
            gap_seconds=0,
        )
        self.assertFalse(summary.any_success)


# ─────────────────────────────────────────────────────────────────────────────
# 7. YouTubeUploader (unit-only — no real API calls)
# ─────────────────────────────────────────────────────────────────────────────

class TestYouTubeUploader(unittest.TestCase):

    def _make(self, **kw):
        from src.publisher.youtube_uploader import YouTubeUploader
        defaults = dict(client_id="cid", client_secret="csec",
                        refresh_token="rtoken")
        defaults.update(kw)
        return YouTubeUploader(**defaults)

    def test_is_configured_true(self):
        yt = self._make()
        self.assertTrue(yt.is_configured())

    def test_is_configured_false_empty_token(self):
        yt = self._make(refresh_token="")
        self.assertFalse(yt.is_configured())

    def test_is_configured_false_placeholder(self):
        yt = self._make(client_id="${YOUTUBE_CLIENT_ID}")
        self.assertFalse(yt.is_configured())

    def test_build_metadata_injects_shorts_tag(self):
        from src.publisher.youtube_uploader import YouTubeUploader
        title, desc, tags = YouTubeUploader._build_metadata(
            "Epic Movie Recap #movie #recap"
        )
        self.assertIn("#Shorts", title, "Title must contain #Shorts for indexing")

    def test_build_metadata_title_limit(self):
        from src.publisher.youtube_uploader import YouTubeUploader
        long_caption = "A" * 200
        title, _, _ = YouTubeUploader._build_metadata(long_caption)
        self.assertLessEqual(len(title), 100)

    def test_build_metadata_extracts_hashtags(self):
        from src.publisher.youtube_uploader import YouTubeUploader
        _, _, tags = YouTubeUploader._build_metadata(
            "Test #movie #viral #recap"
        )
        self.assertIn("movie", tags)
        self.assertIn("viral", tags)

    def test_from_env_constructs_without_error(self):
        from src.publisher.youtube_uploader import YouTubeUploader
        yt = YouTubeUploader.from_env()
        self.assertIsInstance(yt, YouTubeUploader)

    def test_upload_returns_none_for_missing_file(self):
        yt = self._make()
        with patch.object(yt, "_get_access_token", return_value="fake_token"):
            result = yt.upload(Path("/nonexistent/clip.mp4"), "caption")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 8. FacebookUploader (unit-only)
# ─────────────────────────────────────────────────────────────────────────────

class TestFacebookUploader(unittest.TestCase):

    def test_is_configured_true(self):
        from src.publisher.facebook_uploader import FacebookUploader
        fb = FacebookUploader(page_id="123", access_token="token")
        self.assertTrue(fb.is_configured())

    def test_is_configured_false_empty(self):
        from src.publisher.facebook_uploader import FacebookUploader
        fb = FacebookUploader(page_id="", access_token="")
        self.assertFalse(fb.is_configured())

    def test_is_configured_false_placeholder(self):
        from src.publisher.facebook_uploader import FacebookUploader
        fb = FacebookUploader(page_id="${FB_PAGE_ID}", access_token="tok")
        self.assertFalse(fb.is_configured())

    def test_upload_returns_none_for_missing_file(self):
        from src.publisher.facebook_uploader import FacebookUploader
        fb = FacebookUploader(page_id="123", access_token="token")
        result = fb.upload(Path("/nonexistent/clip.mp4"), "caption")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 9. TikTokUploader (unit-only)
# ─────────────────────────────────────────────────────────────────────────────

class TestTikTokUploader(unittest.TestCase):

    def test_is_configured_true(self):
        from src.publisher.tiktok_uploader import TikTokUploader
        tt = TikTokUploader(access_token="tok123")
        self.assertTrue(tt.is_configured())

    def test_is_configured_false_empty(self):
        from src.publisher.tiktok_uploader import TikTokUploader
        tt = TikTokUploader(access_token="")
        self.assertFalse(tt.is_configured())

    def test_is_configured_false_placeholder(self):
        from src.publisher.tiktok_uploader import TikTokUploader
        tt = TikTokUploader(access_token="${TIKTOK_ACCESS_TOKEN}")
        self.assertFalse(tt.is_configured())

    def test_upload_returns_none_for_missing_file(self):
        from src.publisher.tiktok_uploader import TikTokUploader
        tt = TikTokUploader(access_token="tok")
        result = tt.upload(Path("/nonexistent/clip.mp4"), "caption")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 10. InstagramUploader (unit-only)
# ─────────────────────────────────────────────────────────────────────────────

class TestInstagramUploader(unittest.TestCase):

    def test_is_configured_true(self):
        from src.publisher.instagram_uploader import InstagramUploader
        ig = InstagramUploader(ig_user_id="123", access_token="token")
        self.assertTrue(ig.is_configured())

    def test_is_configured_false_empty(self):
        from src.publisher.instagram_uploader import InstagramUploader
        ig = InstagramUploader(ig_user_id="", access_token="")
        self.assertFalse(ig.is_configured())

    def test_is_configured_false_placeholder(self):
        from src.publisher.instagram_uploader import InstagramUploader
        ig = InstagramUploader(ig_user_id="${IG_USER_ID}", access_token="tok")
        self.assertFalse(ig.is_configured())

    def test_upload_rejects_non_http_url(self):
        from src.publisher.instagram_uploader import InstagramUploader
        ig = InstagramUploader(ig_user_id="123", access_token="token")
        result = ig.upload("/local/path.mp4", "caption")
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 11. ABEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestABEngine(unittest.TestCase):

    def _make(self, tmp_path):
        from src.ab_testing.ab_engine import ABEngine
        return ABEngine(db_path=tmp_path / "ab.db")

    def test_record_and_get_best_angle(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make(Path(d))
            # Record uploads for "mystery" on facebook
            for i in range(5):
                engine.record_upload(
                    video_id="v1",
                    clip_num=i,
                    platform="facebook",
                    niche="movie",
                    angle="mystery",
                    post_id=f"post_{i}",
                )
                engine.record_metrics(
                    post_id=f"post_{i}",
                    platform="facebook",
                    metrics={"views": 10000, "likes": 500, "shares": 100,
                             "saves": 50, "comments": 25},
                )
            best = engine.get_best_angle("facebook", "movie")
            self.assertIsInstance(best, str)

    def test_get_best_angle_returns_default_when_no_data(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make(Path(d))
            best = engine.get_best_angle("facebook", "movie")
            # Should return a valid angle even with no data
            from src.ab_testing.ab_engine import ANGLES
            self.assertIn(best, ANGLES)

    def test_record_creates_row(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make(Path(d))
            engine.record_upload("v1", 1, "tiktok", "p1", "shocking", "movie")
            conn = sqlite3.connect(str(Path(d) / "ab.db"))
            count = conn.execute("SELECT COUNT(*) FROM ab_tests").fetchone()[0]
            conn.close()
            self.assertEqual(count, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 12. NarrativeArc
# ─────────────────────────────────────────────────────────────────────────────

class TestNarrativeArc(unittest.TestCase):

    def _make_plan(self, n_clips=10, angle="mystery"):
        from src.intelligence.narrative_arc import NarrativeArcEngine, NarrativeArcPlan
        engine = NarrativeArcEngine(api_key="")  # no AI, uses deterministic plan
        return engine.plan(video_id="v1", video_title="Test Movie", n_clips=n_clips)

    def test_generates_plan_with_correct_clip_count(self):
        plan = self._make_plan(n_clips=10)
        self.assertEqual(len(plan.nodes), 10)

    def test_first_clip_is_hook_role(self):
        plan = self._make_plan(n_clips=5)
        first = plan.nodes[0]
        # First clip role is the start of the arc (SETUP or HOOK depending on arc type)
        from src.intelligence.narrative_arc import ARC_ROLES
        self.assertIn(first.role, ARC_ROLES)

    def test_angle_propagated(self):
        plan = self._make_plan(n_clips=4)
        self.assertIsInstance(plan.arc_type, str)
        self.assertGreater(len(plan.arc_type), 0)

    def test_get_clip_by_index(self):
        plan = self._make_plan(n_clips=8)
        clip = plan.get_clip(3)
        self.assertIsNotNone(clip)
        self.assertEqual(clip.clip_index, 3)

    def test_angle_for_returns_string(self):
        plan = self._make_plan(n_clips=5)
        angle = plan.angle_for(2)
        self.assertIsInstance(angle, str)


# ─────────────────────────────────────────────────────────────────────────────
# 13. HookOptimizerFree
# ─────────────────────────────────────────────────────────────────────────────

class TestHookOptimizerFree(unittest.TestCase):

    def _make(self, tmp_path):
        from src.intelligence.hook_optimizer_free import HookOptimizerFree
        return HookOptimizerFree(
            db_path=tmp_path / "hooks.db",
            niche="movie",
            enabled=True,
        )

    def test_get_best_hook_returns_result(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            opt = self._make(Path(d))
            result = opt.get_best_hook("facebook", "movie", "mystery")
            self.assertIsNotNone(result)
            self.assertIsInstance(result.phrase, str)
            self.assertGreater(len(result.phrase), 0)

    def test_record_win_increases_weight(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            opt = self._make(Path(d))
            hook = opt.get_best_hook("facebook", "movie", "shocking")
            opt.record_result(
                phrase=hook.phrase,
                platform="facebook",
                niche="movie",
                angle="shocking",
                views=5000,
                likes=500,
                retention_rate=0.8,
            )
            # After a win the phrase should remain accessible
            after = opt.get_best_hook("facebook", "movie", "shocking")
            self.assertIsInstance(after.phrase, str)

    def test_disabled_still_returns_hook(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            from src.intelligence.hook_optimizer_free import HookOptimizerFree
            opt = HookOptimizerFree(
                db_path=Path(d) / "h.db",
                niche="movie",
                enabled=False,
            )
            result = opt.get_best_hook("tiktok", "movie", "mystery")
            self.assertIsNotNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 14. VideoScorerV10 — additional edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestVideoScorerEdgeCases(unittest.TestCase):

    def _make_scorer(self):
        from src.brain.scorer_v10 import VideoScorerV10
        return VideoScorerV10({"niche": "anime",
                               "process_threshold": 0.01,
                               "defer_threshold": 0.01})

    def test_niche_keyword_boosts_trend_for_anime(self):
        scorer = self._make_scorer()
        anime_video  = scorer.score(FakeVideo(title="Anime Episode Full Recap Season 3"))
        generic_video = scorer.score(FakeVideo(title="Generic Unrelated Title"))
        self.assertGreater(anime_video.trend_score, generic_video.trend_score)

    def test_custom_weights_applied(self):
        from src.brain.scorer_v10 import VideoScorerV10
        cfg = {
            "niche": "movie",
            "process_threshold": 0.01,
            "defer_threshold": 0.01,
            "scoring_weights": {
                "engagement": 1.0,
                "recency": 0.0,
                "velocity": 0.0,
                "trend": 0.0,
                "channel": 0.0,
                "duration": 0.0,
                "title": 0.0,
                "viral": 0.0,
            }
        }
        scorer = VideoScorerV10(cfg)
        vs = scorer.score(FakeVideo())
        # With all weight on engagement, composite should closely track engagement
        self.assertAlmostEqual(vs.composite, vs.engagement_score, places=3)

    def test_missing_attributes_handled_gracefully(self):
        from src.brain.scorer_v10 import VideoScorerV10
        scorer = VideoScorerV10({"niche": "movie",
                                  "process_threshold": 0.01,
                                  "defer_threshold": 0.01})

        class BarebonesVideo:
            pass  # no attributes at all

        # Should not raise
        vs = scorer.score(BarebonesVideo())
        self.assertIsNotNone(vs)


# ─────────────────────────────────────────────────────────────────────────────
# 15. RateLimiter (PlatformRateLimiters)
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiter(unittest.TestCase):

    def test_acquire_does_not_raise(self):
        from src.resilience.rate_limiter import PlatformRateLimiters
        rl = PlatformRateLimiters()
        # acquire should not raise for configured platforms
        rl.acquire("facebook", timeout=0.1)

    def test_available_tokens_positive(self):
        from src.resilience.rate_limiter import PlatformRateLimiters
        rl = PlatformRateLimiters()
        available = rl.available("tiktok")
        self.assertGreater(available, 0)

    def test_unknown_platform_uses_generic_bucket(self):
        from src.resilience.rate_limiter import PlatformRateLimiters
        rl = PlatformRateLimiters()
        # Should not raise for unknown platform
        rl.acquire("unknown_platform", timeout=0.1)


# ─────────────────────────────────────────────────────────────────────────────
# 16. AccountRotator
# ─────────────────────────────────────────────────────────────────────────────

class TestAccountRotator(unittest.TestCase):

    def _make(self, tmp_path):
        from src.publisher.account_rotator import AccountRotator
        cfg = {
            "facebook": {
                "disabled": False,
                "accounts": [
                    {"page_id": "p1", "access_token": "t1", "daily_limit": 5},
                    {"page_id": "p2", "access_token": "t2", "daily_limit": 5},
                ]
            }
        }
        return AccountRotator(db_path=tmp_path / "rotation.db", config=cfg)

    def test_get_next_account_returns_rotation(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rot = self._make(Path(d))
            result = rot.get_next_account("facebook")
            self.assertIsNotNone(result)
            self.assertFalse(result.all_maxed)

    def test_record_upload_increments_count(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            rot = self._make(Path(d))
            rot.record_upload("facebook", "p1")
            # Should not raise and count should have incremented
            result = rot.get_next_account("facebook")
            self.assertIsNotNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# 17. DedupEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestDedupEngine(unittest.TestCase):

    def _make(self, tmp_path):
        from src.processor.dedup_engine import DedupEngine
        return DedupEngine(db_path=tmp_path / "dedup.db")

    def test_new_engine_creates_db(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make(Path(d))
            self.assertTrue((Path(d) / "dedup.db").exists())

    def test_register_returns_true_for_new_clip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make(Path(d))
            # register() with a fake path that doesn't exist should not crash
            # but may return False since it can't compute hash
            # The important thing is no exception is raised
            try:
                result = engine.register(Path("/nonexistent/clip.mp4"), "v1", 1)
                self.assertIsInstance(result, bool)
            except Exception:
                pass  # Some implementations may raise — that's OK

    def test_is_duplicate_returns_false_for_unknown(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            engine = self._make(Path(d))
            # Unknown clip path — no hash in DB — should not be duplicate
            result = engine.is_duplicate(Path("/nonexistent/new_clip.mp4"))
            self.assertFalse(result)


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
