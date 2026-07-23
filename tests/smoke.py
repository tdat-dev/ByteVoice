"""Smoke test cuối — kiểm tra mọi module import + compile + summary."""
import os
import sys
import importlib
import py_compile

ROOT = r"d:\ByteWaker\WakerVoice"
sys.path.insert(0, ROOT)

print("=== Importing all modules ===")
for m in ["config", "history", "snippets", "providers", "engine", "settings_ui"]:
    importlib.import_module(m)
    print(f"  {m}: OK")

print()
print("=== Compiling all production files ===")
files = ["config.py", "engine.py", "history.py", "snippets.py",
         "providers.py", "settings_ui.py", "app_qt.py"]
for f in files:
    py_compile.compile(os.path.join(ROOT, f), doraise=True)
    print(f"  {f}: OK")

print()
print("=== Module summary ===")
import providers as p
print(f"  built-in providers: {len(p.BUILTIN_PROVIDERS)} "
      f"({list(p.BUILTIN_PROVIDERS.keys())})")
import config as cfg
print(f"  config DEFAULTS keys: {len(cfg.DEFAULTS)}")
print(f"  history path: {__import__('history').history_path()}")
print(f"  snippets path: {__import__('snippets').snippets_path()}")

print()
print("=== ALL SMOKE TESTS PASSED ===")
