Repo readiness checklist

1) Local dev setup
   - Run: `cd cloud` then `python -m venv .venv` and activate.
   - Install deps: `pip install -r requirements.txt` (ffmpeg required system-wide).

2) Secrets (do NOT commit)
   - Create `cloud/.env` with keys: `ANTHROPIC_API_KEY`, `FB_PAGE_ACCESS_TOKEN`, etc.
   - Place YouTube cookies at `cloud/config/cookies.txt` (gitignored).

3) Smoke test (safe)
   - `python cloud/run_pipeline.py --dry-run` — validates orchestrator start-up.
   - `python cloud/main.py --check` — check tokens.

4) Real run (uploads will occur)
   - Ensure secrets and cookies are set.
   - Optional: force run: `set AUTOREELS_FORCE_RUN=1` (Windows) then `python cloud/run_pipeline.py`.

5) CI
   - A GitHub Actions workflow `ci-smoke-test.yml` runs a dry-run smoke test on push/PR.

6) Before pushing
   - Confirm `.gitignore` contains `.env` and `cloud/config/cookies.txt`.
   - Remove any accidentally committed secrets from history if present.
