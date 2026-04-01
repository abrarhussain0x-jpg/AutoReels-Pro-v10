#!/usr/bin/env python3
"""
Diagnostic and repair script for YouTube monitor issues.
Validates yt-dlp installation, checks metadata extraction, and tests the monitor.
"""
import subprocess
import sys
import json
from pathlib import Path

def run_cmd(cmd, timeout=30):
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except Exception as e:
        return -2, "", str(e)

def check_ytdlp():
    """Check if yt-dlp is installed and working."""
    print("\n=== Checking yt-dlp Installation ===")
    code, stdout, stderr = run_cmd("yt-dlp --version")
    if code != 0:
        print(f"❌ yt-dlp not found or broken")
        print(f"   Error: {stderr}")
        print(f"\n📦 Installing yt-dlp...")
        code, _, err = run_cmd("pip install -U yt-dlp", timeout=60)
        if code == 0:
            print("✅ yt-dlp installed successfully")
            code, stdout, stderr = run_cmd("yt-dlp --version")
        else:
            print(f"❌ Failed to install yt-dlp: {err}")
            return False
    
    if code == 0:
        print(f"✅ yt-dlp is installed: {stdout.strip()}")
        return True
    return False

def check_python_deps():
    """Ensure required Python packages are installed."""
    print("\n=== Checking Python Dependencies ===")
    required = ["requests", "pyyaml", "python-dotenv"]
    missing = []
    
    for pkg in required:
        try:
            __import__(pkg.replace("-", "_"))
            print(f"✅ {pkg}")
        except ImportError:
            print(f"❌ {pkg} - missing")
            missing.append(pkg)
    
    if missing:
        print(f"\n📦 Installing missing packages: {', '.join(missing)}")
        code, _, _ = run_cmd(f"pip install {' '.join(missing)}", timeout=60)
        return code == 0
    return True

def test_metadata_fetch():
    """Test if yt-dlp can fetch metadata for a video."""
    print("\n=== Testing yt-dlp Metadata Extraction ===")
    test_video = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    print(f"Testing with: {test_video}")
    
    cmd = f'yt-dlp --dump-json --skip-download --no-warnings "{test_video}"'
    code, stdout, stderr = run_cmd(cmd, timeout=60)
    
    if code == 0 and stdout:
        try:
            data = json.loads(stdout)
            print(f"✅ Metadata fetch successful:")
            print(f"   Title: {data.get('title', 'N/A')[:50]}")
            print(f"   Channel: {data.get('channel', 'N/A')}")
            print(f"   Duration: {data.get('duration', 'N/A')} seconds")
            return True
        except Exception as e:
            print(f"❌ JSON parse error: {e}")
            return False
    else:
        print(f"❌ Metadata fetch failed (code={code})")
        print(f"   Error: {stderr[:500]}")
        return False

def test_flat_playlist():
    """Test if yt-dlp can fetch a channel playlist."""
    print("\n=== Testing yt-dlp Channel Scan ===")
    test_channel = "https://www.youtube.com/@YouTube/videos"
    print(f"Testing with: {test_channel}")
    
    cmd = f'yt-dlp --flat-playlist --dump-json --playlist-end 3 --no-warnings "{test_channel}"'
    code, stdout, stderr = run_cmd(cmd, timeout=60)
    
    if code == 0 and stdout:
        lines = [l for l in stdout.splitlines() if l.strip()]
        print(f"✅ Channel scan successful: got {len(lines)} entries")
        if lines:
            try:
                data = json.loads(lines[0])
                print(f"   Sample entry: {data.get('id', data.get('url', 'N/A'))[:50]}")
            except:
                pass
        return True
    else:
        print(f"❌ Channel scan failed (code={code})")
        print(f"   Error: {stderr[:300]}")
        return False

def main():
    """Run all diagnostics."""
    print("╔═══════════════════════════════════════════════════╗")
    print("║  YouTube Monitor Diagnostics & Repair v10.0      ║")
    print("╚═══════════════════════════════════════════════════╝")
    
    results = []
    
    # Run checks
    results.append(("yt-dlp Installation", check_ytdlp()))
    results.append(("Python Dependencies", check_python_deps()))
    results.append(("Metadata Extraction", test_metadata_fetch()))
    results.append(("Channel Scanning", test_flat_playlist()))
    
    # Summary
    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}  {name}")
    
    print(f"\nResult: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n🎉 All checks passed! YouTube monitor should work.")
        print("\nNext step: Run 'MODE=\"--once\" python cloud/main.py' to test the pipeline")
        return 0
    else:
        print("\n⚠️  Some checks failed. Please review the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
