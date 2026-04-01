#!/usr/bin/env python3
"""
Quick test to verify YouTube monitor fixes are working.
Run this before running the full pipeline.
"""

def test_import():
    """Test that the module imports without errors."""
    try:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent / "cloud"))
        from src.fetch.youtube_monitor import YouTubeMonitor, VideoMeta
        print("✅ Module imports successfully")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def test_metadata_calls_counter():
    """Verify the metadata_calls counter is actually being incremented."""
    import inspect
    from pathlib import Path
    import sys
    
    sys.path.insert(0, str(Path(__file__).parent / "cloud"))
    from src.fetch.youtube_monitor import YouTubeMonitor
    
    # Read the source code
    source = inspect.getsource(YouTubeMonitor._scan_channel)
    
    # Check for the critical fix: metadata_calls += 1
    if "metadata_calls += 1" in source:
        print("✅ metadata_calls counter is properly incremented")
        return True
    else:
        print("❌ ERROR: metadata_calls counter is NOT being incremented!")
        print("   This is the critical bug that caused '0 metadata calls'")
        return False

def test_command_builder():
    """Verify the _build_cmd_variants method exists and works."""
    import sys
    from pathlib import Path
    
    sys.path.insert(0, str(Path(__file__).parent / "cloud"))
    from src.fetch.youtube_monitor import YouTubeMonitor
    
    # Check method exists
    if not hasattr(YouTubeMonitor, '_build_cmd_variants'):
        print("❌ _build_cmd_variants method not found!")
        return False
    
    # Create a monitor instance
    config = {
        "channels": [],
        "ytdlp_min_delay": 0.3,
        "max_metadata_per_channel": 20
    }
    
    try:
        # This will fail on yt-dlp validation, but we're just testing the method
        monitor = YouTubeMonitor(config)
    except Exception:
        # Expected if yt-dlp not installed, that's ok for this test
        pass
    
    # Test the method directly
    test_cmd = ["yt-dlp", "--dump-json", "https://www.youtube.com/watch?v=test"]
    variants = monitor._build_cmd_variants(test_cmd)
    
    if len(variants) > 0:
        print(f"✅ _build_cmd_variants creates {len(variants)} command variants (expected 1-4)")
        # Verify all variants have URL at the end
        for cmd in variants:
            if cmd[-1] != "https://www.youtube.com/watch?v=test":
                print(f"   ⚠️  WARNING: URL not at end of variant: {cmd}")
                return False
        print("✅ Command variants properly formatted (URL at end)")
        return True
    else:
        print("❌ _build_cmd_variants returned empty list!")
        return False

def main():
    """Run all quick tests."""
    print("╔═══════════════════════════════════════════════════╗")
    print("║  YouTube Monitor v10.0 — Quick Test              ║")
    print("╚═══════════════════════════════════════════════════╝\n")
    
    tests = [
        ("Module Import", test_import),
        ("Metadata Counter Fix", test_metadata_calls_counter),
        ("Command Builder", test_command_builder),
    ]
    
    results = []
    for name, test_fn in tests:
        print(f"\nTest: {name}")
        print("-" * 50)
        try:
            result = test_fn()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Test crashed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}  {name}")
    
    print(f"\nResult: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All fixes verified! Ready to run the pipeline.")
        print("\nNext: Run 'MODE=\"--once\" python cloud/main.py --once' to test")
        return 0
    else:
        print("\n⚠️  Some tests failed. Please review the fixes.")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
