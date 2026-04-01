# AutoReels-Pro-v10 Remaining Bugs & Issues Report
**Analysis Date:** April 1, 2026
**Focus:** Pipeline execution failures (YouTube scanning, video processing, Facebook uploading)

---

## CRITICAL Issues (Pipeline Blockers)

### 1. UNINITIALIZED VARIABLE: `optimized` scope issue
**Severity:** CRITICAL  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L430-L482)  
**Issue:** Variable `optimized` is only defined inside the `if fb_algo:` block (line ~440), but is referenced unconditionally on line 481:
```python
log.info("✅ clip %d → %s (predicted reach=%.1fx)",
         i, summary.success_platforms,
         optimized.predicted_reach_multiplier if fb_algo else 1.0)
```
If `fb_algo` is None, `optimized` will never be defined, causing `NameError` when trying to log success message even though `fb_algo` check is there in the if statement. The ternary operator doesn't save the variable scope issue.

**Impact:** Pipeline crashes immediately after first successful upload if fb_algo is not configured.

**Fix:** Define `optimized` before the conditional or move the reference inside the if block.

---

### 2. MISSING ERROR HANDLING: hooked_optimizer.get_best_hook() returns None without fallback
**Severity:** CRITICAL  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L410)  
**Issue:** 
```python
hook = ho.get_best_hook("facebook", niche, result.angle).phrase
```
If `get_best_hook()` returns None (due to DB errors, missing hooks, etc.), calling `.phrase` will raise `AttributeError`. The code has no try-catch or None check.

**Impact:** Pipeline crashes during hook selection for any clip.

**Fix:** Add try-catch or check if result is None:
```python
hook_result = ho.get_best_hook("facebook", niche, result.angle) if ho else None
hook = hook_result.phrase if hook_result else "WATCH THIS"
```

---

### 3. INCOMPLETE IMPLEMENTATION: extract_thumbnail() called but implementation may fail silently
**Severity:** CRITICAL  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L466-L470)  
**Issue:**
```python
pro.extract_thumbnail(clip_path, 5.0, frame_path)
# ... code assumes frame_path exists ...
tgen.generate(frame_path, ..., thumb_path)
```
The `extract_thumbnail()` method returns `bool` but the code ignores the result and assumes success. If frame extraction fails, `tgen.generate()` will fail with missing file error.

**Impact:** Thumbnail generation fails silently, creating broken output, or crashes with file not found error.

**Fix:** Check return value:
```python
if not pro.extract_thumbnail(clip_path, 5.0, frame_path):
    log.warning("Thumbnail extraction failed, skipping tgen")
    thumb_path = None
```

---

### 4. MISSING ERROR HANDLING: batch.get() returns None without proper fallback chain
**Severity:** CRITICAL  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L407-L428)  
**Issue:**
```python
content = batch.get(i, "facebook")
base_caption = content.caption if content else f"Part {i} 🎬 Follow {channel}!"
tags = content.hashtags if content else ["movierecap", "viral"]
```
The fallback captions are basic strings without platform optimization. If content generation fails for multiple clips, all subsequent captions become generic, degrading content quality. More critically, if `gen.generate_batch()` itself fails or returns incomplete data:

**Impact:** Poor quality captions uploaded, or worse: if batch generation crashes mid-execution, pipeline stops without proper error logging.

**Fix:** Add explicit error handling for batch generation:
```python
try:
    batch = gen.generate_batch(...)
except Exception as e:
    log.error("Batch generation failed: %s", e)
    aq.mark_failed(video.video_id, f"content gen: {str(e)[:100]}")
    continue
```

---

### 5. MISSING VALIDATION: platform uploaders not guaranteed to exist
**Severity:** CRITICAL  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L476-L485)  
**Issue:**
```python
if disp and disp.uploaders:
    summary = disp.upload(...)
    if summary.any_success:
        # ... process success ...
else:
    log.warning("No uploaders configured — add FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN to .env")
    break
```
The code logs warning and breaks, but this happens INSIDE the clip processing loop. Breaking here silently abandons remaining clips from the same video without marking them as failed. Queue will never be told processing stopped prematurely.

**Impact:** Partial uploads marked as complete, next run processes same video again, duplicate content on Facebook.

**Fix:** Track partial completion properly:
```python
else:
    log.error("No uploaders configured, marking video as failed")
    aq.mark_failed(video.video_id, "no uploaders configured")
    break
```

---

## HIGH Severity Issues

### 6. UNINITIALIZED VARIABLE: result.angle used without guaranteed definition
**Severity:** HIGH  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L403)  
**Issue:**
```python
result = dec.decide(video)
if result.decision != "PROCESS":
    # ... skip ...
    continue

# Later, line 410+:
hook = ho.get_best_hook("facebook", niche, result.angle).phrase
```
If decision is SKIP or DEFER, code continues without executing the inner block. But `result.angle` is only guaranteed if decision is PROCESS. The decision engine DOES set angle, but relying on a non-PROCESS decision's angle value is dangerous.

**Actually, reviewing DecisionResult dataclass:** angle is set even for SKIP with default "mystery". **This is OK.**

**Status:** FALSE ALARM - DecisionResult always has angle set.

---

### 7. MISSING DEPENDENCY CHECK: ffprobe not validated before use
**Severity:** HIGH  
**Location:** [cloud/src/processor/video_processor.py](cloud/src/processor/video_processor.py#L245-L253)  
**Issue:**
```python
def get_duration(self, video_path: Path) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
           "-of", "json", str(video_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0
```
Only `ffmpeg` is checked in `_check_ffmpeg()`, not `ffprobe`. If ffprobe is missing, duration returns 0.0, causing:
- `duration < 60` check fails silently → video marked as "too short"
- `actual_clips = min(clips_per, int(duration // clip_length))` returns 0 clips
- `pro.smart_clip_times(0, 0, ...)` returns empty list
- Video finishes with 0 clips uploaded but marked as DONE

**Impact:** Valid videos skipped with no notification, user thinks video was processed.

**Fix:** Validate ffprobe exists:
```python
def _check_ffmpeg(self):
    for tool in ["ffmpeg", "ffprobe"]:
        try:
            subprocess.run([tool, "-version"], capture_output=True, timeout=5)
            log.info("[Processor] %s OK", tool)
        except FileNotFoundError:
            raise RuntimeError(f"{tool} NOT FOUND. Install: sudo apt install ffmpeg")
```

---

### 8. MISSING CONFIGURATION VALIDATION: config file missing causes cryptic error
**Severity:** HIGH  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L556-L560)  
**Issue:**
```python
cfg = ConfigManager(ROOT / args.config).config
```
ConfigManager will raise `ConfigError("Config not found: {path}")` with no guidance on where to place file or what format. If user runs in wrong directory or config.yaml doesn't exist, they get unhelpful error.

**Impact:** Users can't bootstrap the system without reading source code.

**Fix:** Add validation with helpful error message:
```python
config_path = ROOT / args.config
if not config_path.exists():
    log.error("Config file not found: %s", config_path)
    log.error("Create config/config.yaml or pass --config path/to/config.yaml")
    sys.exit(1)
try:
    cfg = ConfigManager(config_path).config
except Exception as e:
    log.error("Failed to load config: %s", e)
    sys.exit(1)
```

---

### 9. LOGIC ERROR: smart_clip_times() can return empty list
**Severity:** HIGH  
**Location:** [cloud/src/processor/video_processor.py](cloud/src/processor/video_processor.py#L255-L272)  
**Issue:**
```python
def smart_clip_times(self, duration: float, n_clips: int, clip_length: int = 55):
    start_skip = duration * skip_start_pct  # 8%
    end_skip   = duration * (1.0 - skip_end_pct)  # 95%
    usable     = end_skip - start_skip
    step       = usable / max(1, n_clips)
    
    clips = []
    for i in range(n_clips):
        start = start_skip + i * step
        end   = min(start + clip_length, end_skip)
        if end - start < 20:  # Skip if less than 20s
            continue  # ← PROBLEM: silently skips clip without logging
        clips.append(...)
    return clips  # Could be empty!
```
If `start + clip_length > end_skip` (clip would extend past outro), `end - start < 20`, so clip is skipped. If all clips would exceed the usable window, the function silently returns `[]`.

**Call site in run_pipeline.py:**
```python
clip_times = pro.smart_clip_times(duration, actual_clips, clip_length=clip_length)

for i, clip_time in enumerate(clip_times, 1):  # Loop never executes if empty
    # ... process clip ...
```
Result: 0 clips generated, video marked as DONE with 0 uploads, no error logged.

**Impact:** Silent failure - video marked as processed with no output.

**Fix:** Log warning and return safe default or raise error:
```python
if not clips:
    log.warning("[Processor] no valid clip times for duration %.0f, all would be < 20s", duration)
    # Either return a single clip from the middle, or raise error
    if duration > clip_length + 40:
        clips.append({"start_s": (duration - clip_length) / 2, "duration_s": clip_length})
return clips
```

---

### 10. MISSING ERROR TRACKING: video download can fail but continue processing
**Severity:** HIGH  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L369-L378)  
**Issue:**
```python
src_path = yt.download(video, tmp_dir / video.video_id)
if not src_path:
    aq.mark_failed(video.video_id, "download failed")
    continue
```
The download can fail due to:
- Network timeout
- Rate limiting (YouTube blocks yt-dlp)
- Geo-blocking
- Video unavailable

Currently, only returns None with a generic "download failed" message. No retry attempt, no detailed error context captured. Next run will scan the same video again and retry, creating infinite retry loop.

**Impact:** Stuck on videos that legitimately can't be downloaded (geo-blocked, deleted, etc.) - wastes API quota and time.

**Fix:** Track failed download attempts per video:
```python
src_path = yt.download(video, tmp_dir / video.video_id)
if not src_path:
    fail_count = aq.get_fail_count(video.video_id) or 0
    if fail_count > 3:
        aq.mark_failed(video.video_id, "download failed after 3 attempts")
    else:
        log.warning("Download failed, will retry next run")
    continue
```

---

### 11. UNVERIFIED RETURN TYPE: process_all_clips() assumes all clips succeed
**Severity:** HIGH  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L419)  
**Issue:**
```python
proc_results = pro.process_all_clips(src_path, video.video_id, out_dir, [clip_time])
if not proc_results or not proc_results[0].success:
    log.warning("Clip %d processing failed", i)
    continue
```
Code checks `proc_results[0].success`, but:
1. `process_all_clips()` iterates and calls `process_clip()` once per clip
2. If clip_time dict is missing required keys (start_s, duration_s), `ClipJob` initialization could fail
3. Function could raise exception or return empty list

The list could have 1 element with `.success = False`, or could be empty (should check length first).

**Impact:** IndexError if process_all_clips returns empty list.

**Fix:** Add defensive check:
```python
proc_results = pro.process_all_clips(...)
if not proc_results:
    log.error("process_all_clips returned empty list for clip %d", i)
    continue
if not proc_results[0].success:
    log.warning("Clip processing failed: %s", proc_results[0].error)
    continue
```

---

### 12. MISSING ERROR HANDLING: first comment poster thread can crash silently
**Severity:** HIGH  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L498-L507)  
**Issue:**
```python
if first_cmt and pres.platform == "facebook" and pres.post_id:
    import threading
    t = threading.Thread(
        target=first_cmt.post_and_pin,
        args=(pres.post_id, first_comment_text, 30),
        daemon=True
    )
    t.start()
```
Daemon threads don't propagate exceptions to main thread. If `first_cmt.post_and_pin()` fails (API error, rate limit, etc.), error is silently swallowed and user never knows.

**Impact:** First comment strategy never executes but user thinks it does. Engagement boost never happens.

**Fix:** Add exception handler to thread function:
```python
def post_comment_safe(post_id, text, timeout):
    try:
        first_cmt.post_and_pin(post_id, text, timeout)
    except Exception as e:
        log.error("[FirstComment] failed for post %s: %s", post_id, e)

t = threading.Thread(target=post_comment_safe, args=(pres.post_id, first_comment_text, 30), daemon=True)
t.start()
```

---

## MEDIUM Severity Issues

### 13. INCOMPLETE IMPLEMENTATION: get_python_environment_details missing
**Severity:** MEDIUM  
**Location:** [cloud/src/processor/video_processor.py](cloud/src/processor/video_processor.py#L72-L78)  
**Issue:** `_check_ffmpeg()` only logs errors, doesn't raise. Pipeline continues with missing ffmpeg but later commands fail.

**Impact:** Confusing errors deep in processing instead of immediate failure on startup.

**Fix:** Make _check_ffmpeg raise on missing dependencies:
```python
def _check_ffmpeg(self):
    for tool in ["ffmpeg", "ffprobe"]:
        try:
            subprocess.run([tool, "-version"], capture_output=True, timeout=5)
        except FileNotFoundError:
            raise RuntimeError(f"CRITICAL: {tool} not installed. Run: sudo apt install ffmpeg")
```

---

### 14. UNTRUSTWORTHY VARIABLE: tgen (thumbnail generator) optional but referenced unconditionally
**Severity:** MEDIUM  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L395, #L466)  
**Issue:**
```python
tgen = engines.get("thumb_gen")  # Could be None
...
if tgen:
    frame_path = out_dir / f"..."
    pro.extract_thumbnail(clip_path, 5.0, frame_path)
    thumb_path = out_dir / f"..."
    tgen.generate(frame_path, ...)  # ← Safe if checked
else:
    thumb_path = None
```
This part is actually safe (it's inside `if tgen:`), but immediately after:
```python
if disp and disp.uploaders:
    summary = disp.upload(..., thumbnail_path=thumb_path)  # thumb_path could be None
```
If tgen is None, thumb_path is None, which the uploader might fail on. Code should handle gracefully.

**Impact:** Low - uploaders typically handle None thumbnails, but not explicitly documented.

---

### 15. MISSING CONFIGURATION SECTION: decision engine might not have all required thresholds
**Severity:** MEDIUM  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L50-L58)  
**Issue:**
```python
scorer = VideoScorer(
    feedback_db=None,
    trend_topics=None,
    weights=scorer_weights,
    process_threshold=float(cfg.get("process_threshold", 0.35)),
    defer_threshold=float(cfg.get("defer_threshold", 0.20)),
)
```
If config.yaml doesn't have `process_threshold` and `defer_threshold`, defaults are used. But what if user sets `process_threshold=0.5` without understanding it should be < defer_threshold? No validation at load time.

**Impact:** Silent misconfiguration causes video filtering to be completely inverted (nothing passes threshold).

**Fix:** Add validation in config_manager or video_processor:
```python
process_t = float(cfg.get("process_threshold", 0.35))
defer_t = float(cfg.get("defer_threshold", 0.20))
if process_t >= defer_t:
    log.warning("process_threshold (%.2f) should be < defer_threshold (%.2f)", process_t, defer_t)
```

---

### 16. MISSING ERROR CONTEXT: YouTubeMonitor rate limit cooldown file could be unreadable
**Severity:** MEDIUM  
**Location:** [cloud/src/fetch/youtube_monitor.py](cloud/src/fetch/youtube_monitor.py#L299-L309)  
**Issue:**
```python
def _is_rate_limited(self) -> bool:
    try:
        if self._cooldown_file.exists():
            try:
                data = json.loads(self._cooldown_file.read_text(encoding="utf-8"))
```
If cooldown file is corrupted, JSON parsing fails silently (caught by inner try), and function returns False assuming no rate limit. Then yt-dlp gets hammered again immediately.

**Impact:** Rate limit avoidance mechanism fails if file corruption occurs.

**Fix:** Log the error:
```python
try:
    data = json.loads(...)
except json.JSONDecodeError as e:
    log.warning("Corrupted cooldown file, removing: %s", e)
    self._cooldown_file.unlink(missing_ok=True)
    return False
```

---

### 17. MISSING VARIABLE INITIALIZATION: result object might lose angle value
**Severity:** MEDIUM  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L380-L410)  
**Issue:**
```python
result = dec.decide(video)
if result.decision != "PROCESS":
    log.info("Skip %s: %s", video.video_id, result.reason)
    aq.mark_skipped(video.video_id, result.reason)
    continue

log.info("PROCESS: %s (score=%.3f angle=%s)", video.title[:50], result.score, result.angle)
```
If `dec.decide()` returns result with decision="PROCESS" but angle is empty string or "mystery" by default, the log message is confusing. More critically, this angle is used throughout the pipeline:

```python
hook = ho.get_best_hook("facebook", niche, result.angle)
```

If angle is blank, hook selection fails to find specialized hooks. Code relies on angle always being set properly.

**Review of decision_engine_free.py:**
```python
return DecisionResult("PROCESS", f"Score {score:.3f}", score, angle=angle)
```
Angle IS set. **This is OK.**

---

### 18. MISSING ERROR HANDLING: arc.plan() might fail without exception
**Severity:** MEDIUM  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L378-L381)  
**Issue:**
```python
arc_plan = arc.plan(video.video_id, video.title, len(clip_times))

batch = gen.generate_batch(
    video_id=video.video_id,
    video_title=video.title,
    n_clips=len(clip_times),
    platforms=["facebook"],
    arc_plan=arc_plan,
)
```
If `arc.plan()` returns None or malformed object, `gen.generate_batch()` might fail cryptically trying to call `arc_plan.angle_for()`.

**Review of narrative_arc_free.py:**
```python
def plan(self, video_id: str, video_title: str, n_clips: int) -> NarrativeArcPlan:
    nodes = []
    for i in range(1, n_clips + 1):
        role = ARC_ROLES[(i - 1) % len(ARC_ROLES)]
        nodes.append(NarrativeNode(...))
    return NarrativeArcPlan(...)
```
Always returns NarrativeArcPlan object. **This is OK.**

---

### 19. UNVERIFIED BEHAVIOR: clip_time dict might be missing required keys
**Severity:** MEDIUM  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L408-L413)  
**Issue:**
```python
for i, clip_time in enumerate(clip_times, 1):
    if today_uploads + total_uploaded >= daily_limit:
        break

    content = batch.get(i, "facebook")
    hook    = ho.get_best_hook("facebook", niche, result.angle).phrase
    clip_time["hook_text"] = hook  # ← Mutating dict from smart_clip_times()

    proc_results = pro.process_all_clips(src_path, video.video_id, out_dir, [clip_time])
```
The code is mutating `clip_time` (adding "hook_text") before passing to `process_all_clips()`. If `smart_clip_times()` returned a dict missing "start_s" or "duration_s", ClipJob initialization will fail with KeyError.

**Review of smart_clip_times():**
```python
clips.append({"start_s": round(start, 2), "duration_s": round(end - start, 2)})
return clips
```
Always returns dicts with required keys. **This is OK.** But ClipJob construction doesn't validate:

```python
@dataclass
class ClipJob:
    source_path: Path
    output_path: Path
    start_s: float  # ← Required
    duration_s: float  # ← Required
```

If dict is missing a key, will raise KeyError at line ~413.

**Fix:** Add validation:
```python
required_keys = {"start_s", "duration_s"}
if not all(k in clip_time for k in required_keys):
    log.error("Clip time missing required keys: %s", clip_time)
    continue
```

---

## LOW Severity Issues

### 20. MISSING CLEANUP: temporary video files not always deleted on error
**Severity:** LOW  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L538-L540)  
**Issue:**
```python
# 8. Cleanup
try:
    src_path.unlink(missing_ok=True)
except Exception:
    pass
```
Only the source video is deleted. If clip processing or uploading fails midway, generated clips in `out_dir / video.video_id / "clips"` remain. Over time, temp directory fills up.

**Impact:** Disk space eventually exhausted, causing later runs to crash with "no space left" error.

**Fix:** Add proper cleanup:
```python
finally:
    # Cleanup tmp files
    try:
        src_path.unlink(missing_ok=True)
        import shutil
        clip_dir = out_dir / video.video_id
        if clip_dir.exists():
            shutil.rmtree(clip_dir, ignore_errors=True)
    except Exception:
        pass
```

---

### 21. MISSING LOGGING: successful video completion not recorded with metrics
**Severity:** LOW  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L536)  
**Issue:**
```python
aq.mark_done(video.video_id, clips_done)
total_uploaded += clips_done
log.info("Video done: %s | %d clips uploaded", video.video_id, clips_done)
```
The log doesn't include:
- How many clips were attempted
- How long processing took
- Total file size uploaded
- Which platforms succeeded

Makes it hard to debug why a video generated fewer clips than expected.

**Fix:** Add detailed logging:
```python
aq.mark_done(video.video_id, clips_done)
total_uploaded += clips_done
log.info("✅ Video complete: %s | %d/%d clips → %d platforms | %.1fs total",
         video.video_id, clips_done, len(clip_times),
         len(summary.success_platforms) if 'summary' in locals() else 0,
         time.time() - video_start_time)
```

---

### 22. MISSING FEATURE: No validation that required Python packages are installed
**Severity:** LOW  
**Location:** [cloud/src/config_manager.py](cloud/src/config_manager.py#L7-12)  
**Issue:**
```python
try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False
```
If YAML is missing, code raises error: `ConfigError("PyYAML not installed — run: pip install PyYAML")`. But other packages (like Jinja2) used in advanced_notifier.py are imported without fallback:

```python
from jinja2 import Template  # [cloud/src/notifier/advanced_notifier.py:line 8]
```

If Jinja2 missing, ImportError at startup before user can see helpful message.

**Impact:** Cryptic import error instead of helpful setup guide.

**Fix:** Add setup validation script or requirements.txt check at startup.

---

### 23. UNSET ENVIRONMENT VARIABLE: AUTOREELS_DEBUG could cause AttributeError
**Severity:** LOW  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L16-20)  
**Issue:**
```python
DEBUG = os.environ.get("AUTOREELS_DEBUG", "").strip() == "1"
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    ...
)
```
This is safe - defaults to empty string. **Actually, this is OK.**

---

### 24. INEFFICIENT QUERY: _count_today_uploads() creates new DB connection each call
**Severity:** LOW  
**Location:** [cloud/run_pipeline.py](cloud/run_pipeline.py#L545-558)  
**Issue:**
```python
def _count_today_uploads(queue_dir: Path) -> int:
    try:
        import sqlite3, time
        from datetime import datetime
        db = queue_dir / "jobs.db"
        if not db.exists():
            return 0
        today_start = datetime.now().replace(hour=0, minute=0, second=0).timestamp()
        with sqlite3.connect(db, timeout=5) as c:
            row = c.execute(
                "SELECT COUNT(*) FROM jobs WHERE state='DONE' AND finished_at >= ?",
                (today_start,)
            ).fetchone()
```
Called once per pipeline run. Not a performance issue, but should use the existing JobQueue instance instead of opening DB directly.

**Impact:** Minor - slight performance loss, increase in DB connection overhead.

---

## Configuration Issues

### 25. DEFAULT CONFIG MISSING FROM REPO
**Severity:** MEDIUM  
**Location:** [cloud/config/config.yaml](cloud/config/config.yaml)  
**Issue:** Config file exists but is incomplete. Missing critical sections:
- `facebook.accounts` - uploader will fail if missing
- `branding.channel_name` - used everywhere, defaults to "AutoReels" (OK but fragile)
- `output.width/height` - defaults hardcoded (OK but not configurable)
- `notifications.*` - notifier silently skips if missing (OK)

**Impact:** Users must know to fill in facebook config section or uploads fail.

---

## Summary Table

| # | Severity | Category | Location | Brief | Fix Complexity |
|---|----------|----------|----------|-------|---|
| 1 | CRITICAL | Scope | run_pipeline.py:481 | `optimized` undefined | Low |
| 2 | CRITICAL | Error | run_pipeline.py:410 | `get_best_hook()` can return None | Low |
| 3 | CRITICAL | Error | run_pipeline.py:466 | extract_thumbnail result ignored | Low |
| 4 | CRITICAL | Error | run_pipeline.py:407 | batch.get() None handling incomplete | Medium |
| 5 | CRITICAL | Logic | run_pipeline.py:476 | Uploader failure breaks instead of marking failed | Low |
| 6 | HIGH | Dependency | video_processor.py:247 | ffprobe not validated | Medium |
| 7 | HIGH | Config | run_pipeline.py:560 | No config file path validation | Low |
| 8 | HIGH | Logic | video_processor.py:255 | smart_clip_times returns empty list | Medium |
| 9 | HIGH | Error | run_pipeline.py:369 | Download failure not retried | Medium |
| 10 | HIGH | Error | run_pipeline.py:419 | process_all_clips assumes success | Low |
| 11 | HIGH | Error | run_pipeline.py:498 | Thread exception silent | Low |
| 12 | HIGH | Startup | video_processor.py:72 | _check_ffmpeg doesn't raise | Low |
| 13 | MEDIUM | Dict | run_pipeline.py:408 | clip_time dict key validation | Low |
| 14 | MEDIUM | Error | youtube_monitor.py:301 | Cooldown file corruption silently ignored | Low |
| 15 | MEDIUM | Config | run_pipeline.py:50 | Threshold validation missing | Low |
| 16 | LOW | Cleanup | run_pipeline.py:538 | Temp files not cleaned | Low |
| 17 | LOW | Logging | run_pipeline.py:536 | Missing detailed completion metrics | Low |
| 18 | LOW | Dependencies | notifier.py:8 | Missing packages no validation | Low |

---

## Recommended Fix Priority

**Must Fix (Blocks Pipeline):**
1. Issue #1: optimized variable scope
2. Issue #2: get_best_hook() None check
3. Issue #3: extract_thumbnail result validation
4. Issue #5: Failed upload handling
5. Issue #6: ffprobe validation
6. Issue #8: empty clip times handling
7. Issue #7: config file path validation

**Should Fix (High Risk):**
8. Issue #4: batch generation error handling
9. Issue #9: download failure retry logic
10. Issue #11: thread exception handling
11. Issue #13: dict key validation

**Nice to Fix:**
12. Issue #12, #14, #15, #16, #17, #18 (Low/Medium, covered by error handling improvements above)

---

## Testing Recommendations

1. **Test missing dependencies:** Run without ffmpeg, ffprobe, yt-dlp, YAML
2. **Test download failures:** Mock yt-dlp to return None, test retry logic
3. **Test empty clips:** Video with duration < 60s or < required clip length
4. **Test missing config:** No config.yaml present
5. **Test partial failures:** Uploader fails on first 2 clips, succeeds on 3rd
6. **Test thread crashes:** First comment poster fails, verify main thread continues
7. **Test disk full:** Temp directory fills up during clip generation

