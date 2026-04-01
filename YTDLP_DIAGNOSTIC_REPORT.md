# YouTube Monitor Metadata Extraction Failure - Diagnostic Report

## Status
🔴 **CRITICAL**: All individual video metadata extraction attempts are failing, though channel scanning works.

## Symptoms

From GitHub Actions run with `MODE="--once"`:
```
13:52:11 [INFO] flat-playlist returned 69 raw entries for https://www.youtube.com/@Plotpulse01/videos
13:52:11+ [INFO] Skipped video at idx=0-8: no metadata returned (yt-dlp fail, rate-limit, or filtered)
```

**Key Observation**: 
- ✓ `--flat-playlist` works (gets 69 entries from channel)
- ✗ Individual `--dump-json` calls for each video **ALL FAIL**

This is a **specific failure pattern** indicating the problem is with individual video metadata extraction, not yt-dlp installation or network access.

---

##  Root Cause Analysis

### What We Know
1. **yt-dlp is installed** (`version: 2026.03.17` logged successfully)
2. **Node.js JS runtime is available** (required for JS code execution on YouTube)
3. **Flat-playlist extraction works** (can retrieve list of 69 videos)
4. **All individual metadata calls fail** (100% failure rate on video URLs)

### Likely Causes

#### 1. **Video URLs Format Issue** (MOST LIKELY)
The flat-playlist command returns Video objects, but the extracted `url` or `id` field might not be in the format that individual `yt-dlp` calls expect.

**Flat-playlist structure:**
```json
{
  "id": "DfPREvuTdQM",
  "url": "https://youtu.be/DfPREvuTdQM"  // shorthand format!
  // ... other fields
}
```

**Our metadata extraction expects:**
```bash
yt-dlp --dump-json https://www.youtube.com/watch?v=DfPREvuTdQM
```

**Issue**: If flat-playlist is returning `youtu.be` shorthand URLs instead of `youtube.com/watch?v=` format, yt-dlp might not recognize them or might fail silently.

#### 2. **Rate Limiting (After First Batch)**
If YouTube rate-limits after the initial flat-playlist call, all subsequent individual video lookups would fail.

**Evidence**:  
- 14-second gaps between "Skipped" messages
- Could indicate: 14 seconds per attempt × multiple variants × retry backoff

#### 3. **yt-dlp Command Syntax Error**
A malformed argument in any of the command variants could cause failures, though we'd expect to see stderr output.

---

## Enhanced Diagnostics Already Deployed (Commit 91d3f03)

### Changes Made to `cloud/src/fetch/youtube_monitor.py`

**1. New logging at START of metadata extraction:**
```python
log.info("[Monitor] _get_metadata START for: %s", video_url[:80])
log.info("[Monitor] _get_metadata: prepared %d command variants", len(all_cmds))
```
This shows us HOW MANY variants are being tried.

**2. Each attempt is now logged:**
```python
log.info("[Monitor] metadata attempt %d/%d for %s: %s", attempt, len(all_cmds), video_url, "...")
```
Shows which variant # failed (important for pattern detection).

**3. Detailed failure reasons:**
```python
log.info("[Monitor]   → attempt %d FAILED: code=%d, stdout_len=%d, stderr=...", attempt, r.returncode, len(...), ...)
log.info("[Monitor]   → attempt %d TIMEOUT (60s) for %s", attempt, video_url)
log.info("[Monitor]   → attempt %d ERROR: %s for %s", attempt, type(e).__name__, ...)
```

**4. Success indication:**
```python
log.info("[Monitor]   → attempt %d SUCCESS: got title='%s'", attempt, meta.title[:40])
```

### What These Logs Will Tell Us

**Scenario 1: All attempts fail with returncode=1**
→ Likely yt-dlp error (URL format, permissions, or YouTube error)

**Scenario 2: First attempt fails, later ones succeed**
→ Confirms fallback chain is working

**Scenario 3: Timeouts on all attempts**
→ yt-dlp is hanging (network issue or infinite retry)

**Scenario 4: JSON parse errors on attempts that don't timeout**
→ yt-dlp returns data but it's malformed

---

## Next Steps

### 1. **Trigger New Pipeline Run**
```bash
# Option A: Via GitHub Actions UI
Settings → Actions → Run workflow

# Option B: Via git push
git commit --allow-empty -m "Trigger pipeline with diagnostics"
git push origin master
```

### 2. **Capture Diagnostic Output**

The enhanced logs will show in GitHub Actions:
1. Go to: `https://github.com/abrarhussain0x-jpg/AutoReels-Pro-v10/actions`
2. Click latest run
3. Expand "Run: python cloud/main.py --once"
4. Look for lines like:
   - `[Monitor] _get_metadata START for: https://www.youtube.com/watch?v=...`
   - `[Monitor] metadata attempt 1/20 for ...`
   - `[Monitor]   → attempt 1 FAILED: code=1, stderr=...`

This will reveal the EXACT why metadata extraction is failing.

### 3. **Fix Based on Diagnostics**

**If URL format issue:**
```python
# Add URL normalization in _scan_channel before calling _get_metadata
if vid_url.startswith("youtu.be"):
    vid_url = f"https://www.youtube.com/watch?v={vid_url.split('/')[-1]}"
```

**If rate limiting:** 
```python
# Increase delays between attempts
self.min_delay_between_calls = 2.0  # instead of 0.3
```

**If yt-dlp stderr indicates issue:**
```python
# Add stderr to log file for analysis
log.error("[Monitor] yt-dlp stderr: %s", stderr)
```

---

## Files Modified

- `cloud/src/fetch/youtube_monitor.py` (Lines 189-290): Enhanced logging in `_get_metadata()` method
- `debug_ytdlp.py`: New diagnostic script (not currently used in pipeline)

## Recent Commits

- **91d3f03**: Add detailed logging to youtube_monitor._get_metadata for diagnostics
- **5a0c6da**: GitHub Secrets setup documentation  
- **1b07a30**: Pipeline critical bug fixes

---

## Rollback Plan

If the enhanced logging introduces issues:
```bash
git revert 91d3f03
```

---

## Questions for User

1. Can you trigger a new GitHub Actions run and share the full logs?
2. Are you seeing `[Monitor] _get_metadata START for:` lines in the output?
3. Does the pipeline work locally when you run `cd cloud && MODE=--once python main.py $MODE`?

---

**Last Updated**: April 1, 2026  
**Priority**: CRITICAL (pipeline non-functional)  
**Estimated Fix Time**: 15-30 minutes once diagnostic output is available
