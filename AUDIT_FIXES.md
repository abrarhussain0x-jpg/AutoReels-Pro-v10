# AutoReels Pro v10 — Audit Fix Log
**Fixed:** 2026-03-27 | All 19 issues from deep audit resolved

---

## 🔴 Critical Fixes

| ID | Fix |
|---|---|
| C-1 | `config/cookies.txt` — real YouTube session cookies removed; replaced with setup instructions template. **Action required: rotate your Google account session at myaccount.google.com → Security → Your devices.** |
| C-2 | `.gitignore` created at project root covering `.env`, cookies, `*.db`, cache dirs, logs, video files |
| C-3 | `api.py` — `"admin_secret_key"` literal removed; replaced with `require_admin()` FastAPI dependency reading `ADMIN_API_KEY` env var; startup warning if unset |
| C-4 | `api.py` + `api_endpoints.py` — CORS wildcard `"*"` replaced with `_get_allowed_origins()` reading from `ALLOWED_ORIGINS` env var (comma-separated); sensible dev defaults; wildcard+credentials combo eliminated |
| C-5 | *(Architecture note)* Legal/ToS concern documented in README. The pipeline must only be used with content you own or have explicit written permission to redistribute. The example channels in `config.yaml` are illustrative only — replace with your own licensed source. |

---

## 🟠 High Fixes

| ID | Fix |
|---|---|
| H-1 | Created 4 previously missing modules: `src/resilience/circuit_breaker.py` (thread-safe state machine), `src/resilience/rate_limiter.py` (token-bucket per platform), `src/optimizer/hashtag_engine.py` (UCB1 bandit selection), `src/utils/lock.py` (atomic POSIX file counters). All fully implemented, not stubs. |
| H-2 | `Dockerfile` — HEALTHCHECK port changed from 5000 → **8000** to match `uvicorn --port 8000`. Kubernetes service manifest updated to match. |
| H-3 | `config/config.yaml` + `START.sh` — hardcoded Facebook Page ID `992847493905061` replaced with `${FB_PAGE_ID}` env var reference. Added `FB_PAGE_ID` to `.env.example`. |
| H-4 | `middleware.py` — `hmac.new(self.secret, body, 'sha256')` fixed to `hmac.new(self.secret, body, hashlib.sha256)` (correct Python 3 API; `hashlib` import added). |

---

## 🟡 Medium Fixes

| ID | Fix |
|---|---|
| M-1 | `middleware.py` `RateLimiter.is_allowed()` — fail-open (`return True`) replaced with `_in_process_check()` sliding-window fallback using `collections.deque`; rate limiting now degrades safely when Redis is down instead of silently disabling. |
| M-2 | `api.py` + `api_endpoints.py` — SQLAlchemy engine moved to module-level singleton (`_engine`, `_SessionLocal`); `get_db()` now yields a session from the shared pool per request. Eliminates connection pool leak on every request. |
| M-3 | `pipeline_v2.py` — docstring updated from `v9.0` to `v10.0`; v10 additions (CircuitBreaker, PlatformRateLimiters, HashtagEngine, atomic counters) properly documented alongside retained v9 features. |
| M-4 | `docker-compose.yml` — `api:` service was accidentally nested inside the `volumes:` top-level key (silently ignored by Compose). Moved to correct position in `services:` block. Also added `ADMIN_API_KEY` and `ALLOWED_ORIGINS` to the `api` service environment. |
| M-5 | `facebook_uploader.py` — Graph API version extracted from `os.getenv("FB_API_VERSION", "v19.0")` instead of hardcoded `v19.0`. Both `graph.facebook.com` and `rupload.facebook.com` URLs updated. `.env.example` updated to `FB_API_VERSION=v19.0`. |

---

## 🔵 Low Fixes

| ID | Fix |
|---|---|
| L-1 | `requirements.txt` — `yt-dlp` updated from `==2024.3.10` (2+ years old) to `>=2025.1.0` to track YouTube anti-bot countermeasures. |
| L-2 | `requirements.txt` — `anthropic` updated from `==0.25.0` to `>=0.40.0`; model in `.env.example` and `config.py` updated from deprecated `claude-3-haiku-20240307` to `claude-haiku-4-5-20251001`. All other dependencies refreshed to latest stable. |
| L-3 | Empty ghost directory `src/core` at project root (artifact of incorrect zip) removed. Only `cloud/src/core/` remains. |
| L-4 | `AuditLogger` — `metadata.create_all()` removed from `log_action()` (was called on every audit write). New class method `AuditLogger.init_schema(engine)` must be called once at application startup. |
| L-5 | `cache_response` decorator — Redis connection now uses a module-level singleton `_get_redis()` instead of creating a new connection per call. Fixed `functools.wraps`, stable cache key derivation, and graceful skip when Redis is down. |

---

## New Files Created

| File | Purpose |
|---|---|
| `.gitignore` | Prevents secrets, cookies, DBs, caches from being committed |
| `cloud/src/resilience/circuit_breaker.py` | Thread-safe circuit breaker (CLOSED/OPEN/HALF_OPEN state machine) |
| `cloud/src/resilience/rate_limiter.py` | Token-bucket per-platform rate limiters |
| `cloud/src/optimizer/hashtag_engine.py` | UCB1 bandit hashtag selection with SQLite performance tracking |
| `cloud/src/utils/lock.py` | Atomic POSIX file counters for cross-process upload tracking |
| `AUDIT_FIXES.md` | This document |

---

## Still Requires Manual Action

1. **Rotate YouTube Google session** — even if repo was never pushed, treat cookies as compromised.
2. **Set `ADMIN_API_KEY`** in your `.env` before first run: `python -c "import secrets; print(secrets.token_hex(32))"`
3. **Set `ALLOWED_ORIGINS`** in `.env` to your actual dashboard domain in production.
4. **Replace example YouTube channel URLs** in `config/config.yaml` with channels you have rights to use.
5. **Set `FB_PAGE_ID`** and `FB_PAGE_ACCESS_TOKEN` in `.env`.
