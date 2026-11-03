# -*- coding: utf-8 -*-
"""轻量测试 runner：无 pytest 环境下用 unittest 跑 tests/ 里的 pytest 风格裸函数。

用法：python _run_all_tests.py
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))


def main() -> int:
    suite = unittest.TestSuite()
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        module = __import__(path.stem)
        for name in sorted(dir(module)):
            if name.startswith("test_") and callable(getattr(module, name)):
                suite.addTest(unittest.FunctionTestCase(getattr(module, name)))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
