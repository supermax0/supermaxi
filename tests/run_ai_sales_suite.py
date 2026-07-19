"""Minimal no-dependency runner for the focused Sales AI regression suite."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_FILES = (
    ROOT / "tests" / "test_ai_sales_foundation.py",
    ROOT / "tests" / "test_ai_sales_intelligence.py",
)


def main() -> None:
    total = 0
    for index, path in enumerate(TEST_FILES, start=1):
        spec = importlib.util.spec_from_file_location(f"ai_sales_suite_{index}", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        tests = sorted(
            (name, value)
            for name, value in vars(module).items()
            if name.startswith("test_") and callable(value)
        )
        for name, test in tests:
            test()
            total += 1
            print(f"PASS {name}")
    print(f"Sales AI suite passed: {total} tests")


if __name__ == "__main__":
    main()
