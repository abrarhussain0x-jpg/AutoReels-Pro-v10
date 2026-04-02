#!/usr/bin/env python3
"""
get_fb_token.py — Interactive guide to get your Facebook Page Access Token.
Walks you through every step. Opens browser links automatically.
Saves token directly to your .env file when done.

Usage: python3 get_fb_token.py
"""
import json, os, sys, urllib.parse, urllib.request, webbrowser
from pathlib import Path

ROOT    = Path(__file__).parent
ENV     = ROOT / ".env"
GRAPH   = "https://graph.facebook.com/v19.0"


def print_step(n: int, title: str):
    print(f"\n{'='*60}")
    print(f"  STEP {n}: {title}")
    print('='*60)


def open_url(url: str, label: str = ""):
    print(f"\n  🔗 {label or url}")
    try:
        webbrowser.open(url)
        print("  (opened in your browser)")
    except Exception:
        print("  → Open this URL manually in your browser")


def get_pages(user_token: str) -> list:
    url = f"{GRAPH}/me/accounts?access_token={user_token}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("data", [])
    except Exception as e:
        print(f"  ❌ API error: {e}")
        return []


def save_to_env(page_id: str, token: str):
    if ENV.exists():
        content = ENV.read_text()
        lines   = content.splitlines()
        updated = []
        found_id    = False
        found_token = False
        for line in lines:
            if line.startswith("FB_PAGE_ID="):
                updated.append(f"FB_PAGE_ID={page_id}")
                found_id = True
            elif line.startswith("FB_PAGE_ACCESS_TOKEN="):
                updated.append(f"FB_PAGE_ACCESS_TOKEN={token}")
                found_token = True
            else:
                updated.append(line)
        if not found_id:
            updated.append(f"FB_PAGE_ID={page_id}")
        if not found_token:
            updated.append(f"FB_PAGE_ACCESS_TOKEN={token}")
        try:
            ENV.write_text("\n".join(updated) + "\n")
        except OSError as e:
            print(f"❌ Failed to write {ENV}: {e}")
            raise
    else:
        try:
            ENV.write_text(f"FB_PAGE_ID={page_id}\nFB_PAGE_ACCESS_TOKEN={token}\n")
        except OSError as e:
            print(f"❌ Failed to write {ENV}: {e}")
            raise
    print(f"\n  ✅ Saved to {ENV}")


def main():
    print("\n" + "="*60)
    print("  AUTO-REELS Facebook Token Setup Wizard")
    print("="*60)
    print("\n  This wizard will get your Facebook Page Access Token.")
    print("  You'll need: a Facebook account + a Facebook Page.\n")

    input("  Press ENTER to start...")

    # ── Step 1: Create Facebook App ───────────────────────────────────────────
    print_step(1, "Create a Facebook Developer App")
    print("""
  1. Go to: https://developers.facebook.com/apps/
  2. Click "Create App"
  3. Choose "Business" type
  4. Give it any name (e.g. "AutoReels")
  5. Complete the setup wizard
""")
    open_url("https://developers.facebook.com/apps/", "Open Facebook Developer Apps")
    input("\n  Press ENTER when your app is created...")

    # ── Step 2: Get App ID + Secret ────────────────────────────────────────────
    print_step(2, "Get Your App ID and Secret")
    print("""
  In your app dashboard:
  - Go to Settings → Basic
  - Copy your App ID and App Secret
""")
    app_id     = input("  Paste your App ID: ").strip()
    app_secret = input("  Paste your App Secret: ").strip()

    if not app_id or not app_secret:
        print("  ❌ App ID and Secret are required.")
        sys.exit(1)

    # ── Step 3: Get User Token via Graph Explorer ──────────────────────────────
    print_step(3, "Get a User Access Token")
    explorer_url = (
        f"https://developers.facebook.com/tools/explorer/"
        f"?app_id={app_id}&redirect_uri=https://www.facebook.com/connect/login_success.html"
    )
    print("""
  1. Open Graph API Explorer (link below)
  2. Select YOUR app from the "Meta App" dropdown (top right)
  3. Click "Generate Access Token"
  4. Grant permissions: pages_show_list, pages_read_engagement,
     pages_manage_posts, pages_manage_engagement
  5. Copy the generated token
""")
    open_url(explorer_url, "Open Graph API Explorer")
    user_token = input("\n  Paste your User Access Token: ").strip()

    if not user_token:
        print("  ❌ Token required.")
        sys.exit(1)

    # ── Step 4: Exchange for long-lived token ──────────────────────────────────
    print_step(4, "Exchange for Long-Lived Token (60 days)")
    url    = f"{GRAPH}/oauth/access_token"
    params = urllib.parse.urlencode({
        "grant_type":        "fb_exchange_token",
        "client_id":         app_id,
        "client_secret":     app_secret,
        "fb_exchange_token": user_token,
    })
    try:
        with urllib.request.urlopen(f"{url}?{params}", timeout=10) as resp:
            data = json.loads(resp.read())
        long_token = data.get("access_token")
        print(f"  ✅ Got long-lived token (60 days)")
    except Exception as e:
        print(f"  ⚠️  Token exchange failed: {e}")
        print("  Using short-lived token instead...")
        long_token = user_token

    # ── Step 5: Pick your Page ──────────────────────────────────────────────────
    print_step(5, "Select Your Facebook Page")
    pages = get_pages(long_token)

    if not pages:
        print("  ❌ No pages found. Make sure your token has pages_show_list permission.")
        print("  You can still enter your page details manually:")
        page_id    = input("  Your Page ID: ").strip()
        page_token = long_token
    else:
        print(f"\n  Found {len(pages)} page(s):\n")
        for i, page in enumerate(pages, 1):
            print(f"  {i}. {page.get('name')} (ID: {page.get('id')})")

        choice = input(f"\n  Enter number (1-{len(pages)}): ").strip()
        try:
            chosen     = pages[int(choice) - 1]
            page_id    = chosen["id"]
            page_token = chosen["access_token"]
            print(f"\n  ✅ Selected: {chosen.get('name')} (ID: {page_id})")
        except (ValueError, IndexError):
            print("  ❌ Invalid choice")
            sys.exit(1)

    # ── Step 6: Save ───────────────────────────────────────────────────────────
    print_step(6, "Save to .env")
    save_to_env(page_id, page_token)

    print(f"""
  🎉 Done! Your Facebook Page is configured.

  Page ID:    {page_id}
  Token:      {page_token[:20]}...

  Next steps:
    python3 health_check.py           ← verify everything is ready
    python3 run_pipeline.py --dry-run ← test without uploading
    python3 run_pipeline.py           ← go live!
""")


if __name__ == "__main__":
    main()
