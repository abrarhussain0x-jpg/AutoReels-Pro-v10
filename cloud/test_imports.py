#!/usr/bin/env python
"""Test all module imports to verify integration."""

import sys
sys.path.insert(0, '.')

print("Testing imports of all new modules...\n")

modules_to_test = [
    ("async_executor", "src.core.async_executor", ["AsyncExecutor", "BatchProcessor"]),
    ("observability", "src.health.observability", ["StructuredLogger", "HealthCheck", "MetricsCollector"]),
    ("advanced_patterns", "src.resilience.advanced_patterns", ["CircuitBreaker", "AdaptiveRetry", "Bulkhead"]),
    ("security.advanced", "src.security.advanced", ["InputValidator", "SecretManager", "RateLimiter"]),
    ("metrics_api", "src.dashboard.metrics_api", ["DashboardMetrics", "MetricsAPI", "DashboardHTML"]),
    ("facebook_uploader", "src.publisher.facebook_uploader", ["FacebookUploader"]),
]

failed = []
for name, module_path, classes in modules_to_test:
    try:
        mod = __import__(module_path, fromlist=classes)
        for cls in classes:
            if not hasattr(mod, cls):
                raise AttributeError(f"Missing class: {cls}")
        print(f"✓ {name}")
    except Exception as e:
        print(f"✗ {name}: {e}")
        failed.append((name, str(e)))

if not failed:
    print("\n✅ All modules loaded successfully!")
else:
    print(f"\n❌ {len(failed)} module(s) failed to import:")
    for name, error in failed:
        print(f"  - {name}: {error}")
    sys.exit(1)
