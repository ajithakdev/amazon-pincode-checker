import shutil
import sys
import unittest
from unittest import mock

from helpers import ROOT, TempDirTestCase


class FakeChecker:
    calls = []

    def __init__(self, **kw):
        self.kw = kw

    def run(self, pincodes_list, max_tests=None, workers=1):
        FakeChecker.calls.append((self.kw, pincodes_list, max_tests))


class CliTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        FakeChecker.calls = []
        import cli
        self.cli = cli
        p = mock.patch.object(cli, "AmazonPincodeChecker", FakeChecker)
        p.start()
        self.addCleanup(p.stop)

    def run_main(self, *argv):
        with mock.patch.object(sys, "argv", ["cli.py", *argv]):
            self.cli.main()

    def test_single_pincode(self):
        self.run_main("--asin", "B1", "--pincode", "600034")
        kw, lst, mt = FakeChecker.calls[0]
        self.assertEqual(lst, [("600034", "unknown", {})])
        self.assertIsNone(mt)
        self.assertEqual(kw["asin"], "B1")

    def test_pincodes_file(self):
        f = self.tmp / "list.txt"
        f.write_text("# comment\n600001\n\n  600002  \n#x\n600003\n")
        self.run_main("--url", "http://x", "--pincodes", str(f), "--max-tests", "2")
        _, lst, mt = FakeChecker.calls[0]
        self.assertEqual([p[0] for p in lst], ["600001", "600002", "600003"])
        self.assertEqual(mt, 2)

    def test_adaptive_default(self):
        (self.tmp / "data").mkdir()
        shutil.copy(ROOT / "data" / "prioritized_pincodes.json", self.tmp / "data")
        self.run_main("--asin", "B1")
        _, lst, _ = FakeChecker.calls[0]
        self.assertTrue(lst)
        pin, city, meta = lst[0]
        self.assertEqual(meta["pincode"], pin)
        self.assertEqual(meta["city"], city)

    def test_missing_asin_url(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_main("--pincode", "600034")
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(FakeChecker.calls, [])


if __name__ == "__main__":
    unittest.main()
