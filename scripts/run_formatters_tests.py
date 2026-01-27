"""Lightweight test runner for formatters tests (avoids pytest/conftest imports).

This script imports the test module directly and runs its test functions, printing
simple pass/fail output. It is intended to run quickly in dev environments where
the full test harness may pull heavy dependencies.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

test_file = ROOT / "tests" / "test_lsp_formatters.py"
spec = importlib.util.spec_from_file_location("test_lsp_formatters", str(test_file))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore

tests = [name for name in dir(mod) if name.startswith("test_")]
failed = 0

for t in tests:
    func = getattr(mod, t)
    try:
        # Some tests use tmp_path fixture; provide a temporary directory for those
        import tempfile
        from pathlib import Path

        if "tmp_path" in func.__code__.co_varnames:
            with tempfile.TemporaryDirectory() as td:
                func(Path(td))
        else:
            func()
        print(f"PASS: {t}")
    except AssertionError as ae:
        print(f"FAIL: {t} - AssertionError: {ae}")
        failed += 1
    except Exception as e:
        print(f"ERROR: {t} - Exception: {e}")
        failed += 1

if failed:
    print(f"{failed} tests failed")
    sys.exit(1)
else:
    print(f"All {len(tests)} tests passed")
    sys.exit(0)
