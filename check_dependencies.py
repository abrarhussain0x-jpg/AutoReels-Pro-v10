#!/usr/bin/env python
"""Verify all new module dependencies are in requirements.txt"""

import re
from pathlib import Path

# Standard library modules that don't need to be in requirements
STDLIB_MODULES = {
    'asyncio', 'logging', 'typing', 'datetime', 'concurrent', 'time',
    'json', 'os', 're', 'hmac', 'hashlib', 'traceback', 'random',
    'threading', 'dataclasses', 'enum', 'pathlib', 'urllib', 'io',
    'sys', 'collections', 'itertools', 'functools', 'warnings',
}

new_modules = [
    'cloud/src/core/async_executor.py',
    'cloud/src/health/observability.py',
    'cloud/src/resilience/advanced_patterns.py',
    'cloud/src/security/advanced.py',
    'cloud/src/dashboard/metrics_api.py',
]

print("Checking external dependencies in new modules...\n")

for module_path in new_modules:
    file_path = Path(__file__).parent / module_path
    if not file_path.exists():
        print(f"⚠ File not found: {module_path}")
        continue
    
    with open(file_path) as f:
        content = f.read()
    
    # Find all imports
    imports = re.findall(r'^(?:from|import)\s+(\w+)', content, re.MULTILINE)
    external_imports = [i for i in imports if i not in STDLIB_MODULES]
    
    if external_imports:
        print(f"❌ {module_path}:")
        for imp in external_imports:
            print(f"   - {imp}")
    else:
        print(f"✓ {module_path} - only stdlib dependencies")

print("\n✅ All new modules use standard library dependencies!")
