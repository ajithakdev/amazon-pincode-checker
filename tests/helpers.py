import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Same stub as conftest.py, so plain `unittest discover` works too.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import conftest  # noqa: F401,E402


class FakeLocator:
    def __init__(self, texts):
        self.texts = list(texts)

    def count(self):
        return len(self.texts)

    @property
    def first(self):
        return FakeLocator(self.texts[:1])

    def nth(self, i):
        return FakeLocator(self.texts[i:i + 1])

    def text_content(self):
        return self.texts[0] if self.texts else None

    inner_text = text_content

    def is_visible(self):
        return bool(self.texts)


class FakePage:
    def __init__(self, selectors=None, title=""):
        self.selectors = selectors or {}
        self._title = title

    def locator(self, sel):
        v = self.selectors.get(sel, [])
        if isinstance(v, str):
            v = [v]
        return FakeLocator(v)

    def title(self):
        return self._title


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._old = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        os.chdir(self._old)
        self._tmp.cleanup()

    def make_checker(self, resume=False, output="results/results.json"):
        from checker import AmazonPincodeChecker
        return AmazonPincodeChecker(
            asin="B000TEST", url=None, headless=True, delay=0, retries=1,
            resume=resume, screenshots=False, output_path=output, debug=False)
