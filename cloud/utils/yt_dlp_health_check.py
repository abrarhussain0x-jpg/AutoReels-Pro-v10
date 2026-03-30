import subprocess, sys

COOKIES = "cloud/config/cookies.txt"
TEST_URL = "https://www.youtube.com/watch?v=8viqd3M7Kek"

def main():
    print("Testing yt-dlp with cookies:", COOKIES)
    cmd = [
        "yt-dlp", "--dump-json", "--no-playlist", "--skip-download",
        "--cookies", COOKIES, TEST_URL
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and result.stdout.strip().startswith("{"):
            print("✅ yt-dlp is working! Metadata fetched.")
            sys.exit(0)
        else:
            print("❌ yt-dlp failed. Error output:")
            print(result.stderr.strip() or result.stdout.strip())
            if "rate-limit" in result.stderr or "rate-limit" in result.stdout:
                print("You are rate-limited. Wait 1 hour or refresh cookies.")
            elif "cookies" in result.stderr or "cookies" in result.stdout:
                print("Cookies expired or invalid. Refresh cookies.txt.")
            elif "JS" in result.stderr or "JS" in result.stdout:
                print("JS challenge. Make sure Node.js is installed and in PATH.")
            else:
                print("Unknown error. Try updating yt-dlp and cookies.")
            sys.exit(1)
    except Exception as e:
        print("Exception running yt-dlp:", e)
        sys.exit(2)

if __name__ == "__main__":
    main()
