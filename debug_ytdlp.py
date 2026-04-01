#!/usr/bin/env python3
"""Debug script to test yt-dlp metadata extraction."""

import subprocess
import json
import sys
from pathlib import Path

def test_yt_dlp_version():
    """Test if yt-dlp is installed and get version."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=10
        )
        print(f"✓ yt-dlp version: {result.stdout.strip()}")
        return True
    except Exception as e:
        print(f"✗ yt-dlp not available: {e}")
        return False

def test_flat_playlist():
    """Test flat-playlist extraction from a sample channel."""
    print("\n[Testing flat-playlist extraction]")
    channel_url = "https://www.youtube.com/@Plotpulse01/videos"
    
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--playlist-end", "5",
        "--no-warnings",
        channel_url
    ]
    
    print(f"Running: {' '.join(cmd[:5])} ...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            print(f"✗ flat-playlist failed with code {result.returncode}")
            print(f"  stderr: {result.stderr[:500]}")
            return None
        
        lines = [l for l in result.stdout.splitlines() if l.strip()]
        print(f"✓ Got {len(lines)} entries from flat-playlist")
        
        # Parse and show first entry
        if lines:
            try:
                first = json.loads(lines[0])
                print(f"  First entry keys: {list(first.keys())[:10]}")
                print(f"  URL field: {first.get('url', 'N/A')[:80]}")
                print(f"  ID field: {first.get('id', 'N/A')[:80]}")
                return first  # Return for testing in metadata extraction
            except json.JSONDecodeError as e:
                print(f"  JSON parse error: {e}")
                return None
        return None
        
    except subprocess.TimeoutExpired:
        print("✗ flat-playlist timed out")
        return None
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return None

def test_metadata_extraction(video_entry):
    """Test individual video metadata extraction."""
    if not video_entry:
        print("\n[Skipping metadata test - no video entry]")
        return
    
    print("\n[Testing individual video metadata extraction]")
    
    # Try both URL and ID
    url = video_entry.get("url")
    vid_id = video_entry.get("id")
    
    if not url and not vid_id:
        print("✗ No URL or ID found in entry")
        return
    
    for identifier, label in [(url, "URL"), (vid_id, "ID")]:
        if not identifier:
            continue
        
        # Construct video URL if needed
        if identifier.startswith("http"):
            test_url = identifier
        else:
            test_url = f"https://www.youtube.com/watch?v={identifier}"
        
        print(f"\nTesting with {label}: {test_url[:80]}")
        
        # Test basic metadata extraction
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-playlist",
            "--skip-download",
            "--no-warnings",
            test_url
        ]
        
        print(f"  cmd: {' '.join(cmd[:5])} ...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    meta = json.loads(result.stdout)
                    print(f"  ✓ SUCCESS: Got metadata for '{meta.get('title', 'N/A')[:50]}'")
                    return True
                except json.JSONDecodeError:
                    print(f"  ✗ Invalid JSON response")
            else:
                print(f"  ✗ Failed with code {result.returncode}")
                if result.stderr:
                    print(f"  stderr: {result.stderr[:300]}")
        
        except subprocess.TimeoutExpired:
            print(f"  ✗ Timeout after 60 seconds")
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    return False

def test_with_js_runtime():
    """Test with JS runtime if available."""
    print("\n[Testing with JS runtime]")
    
    # Check for node
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, timeout=5)
        print(f"✓ found: {result.stdout.decode().strip()}")
    except Exception as e:
        print(f"✗ Node.js not available: {e}")
        return
    
    # Test a video with JS runtime
    test_url = "https://www.youtube.com/watch?v=DfPREvuTdQM"  # From the pipeline logs
    
    cmd = [
        "yt-dlp",
        "--dump-json",
        "--no-playlist",
        "--skip-download",
        "--no-warnings",
        "--js-runtimes", "node",
        test_url
    ]
    
    print(f"Testing: {test_url}")
    print(f"Command: yt-dlp --dump-json ... --js-runtimes node {test_url}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0 and result.stdout.strip():
            try:
                meta = json.loads(result.stdout)
                print(f"✓ SUCCESS with JS runtime: '{meta.get('title', '')[:50]}'")
            except json.JSONDecodeError:
                print(f"✗ Invalid JSON from JS runtime")
        else:
            print(f"✗ Failed with code {result.returncode}")
            if result.stderr:
                print(f"Error: {result.stderr[:500]}")
    
    except subprocess.TimeoutExpired:
        print(f"✗ Timeout after 60 seconds")
    except Exception as e:
        print(f"✗ Error: {e}")

def main():
    """Run all tests."""
    print("=" * 70)
    print("yt-dlp Debug Script")
    print("=" * 70)
    
    # Test 1: Version
    if not test_yt_dlp_version():
        print("\n✗ FATAL: yt-dlp not available. Cannot proceed.")
        sys.exit(1)
    
    # Test 2: Flat-playlist
    entry = test_flat_playlist()
    
    # Test 3: Individual video metadata
    if test_metadata_extraction(entry):
        print("\n✓ Metadata extraction works!")
    else:
        print("\n✗ Metadata extraction is failing")
    
    # Test 4: With JS runtime
    test_with_js_runtime()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()
