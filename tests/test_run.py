import json
import threading
from contextlib import contextmanager

import helpers
from helpers import TempDirTestCase


class SimLocator:
    def __init__(self, page, sel):
        self.page = page
        self.sel = sel

    @property
    def first(self):
        return self

    def nth(self, i):
        return self

    def count(self):
        return 1 if self.text_content() is not None else 0

    def is_visible(self):
        return self.count() > 0

    def wait_for(self, **kwargs):
        pass

    def fill(self, value):
        self.page.pending = value

    def click(self):
        if "GLUXZipUpdate" in self.sel and self.page.pending not in self.page.site.invalid:
            self.page.current = self.page.pending

    def text_content(self):
        page, site = self.page, self.page.site
        if self.sel == "#nav-global-location-slot":
            return f"Deliver to {page.current}"
        if self.sel == "#GLUXZipUpdateInput":
            return ""
        if self.sel.startswith("#GLUXZipUpdate "):
            return "Apply"
        if self.sel == "#GLUXZipError":
            return "Please enter a valid pincode" if page.pending in site.invalid else None
        if self.sel == "#productTitle":
            return "Steel Bottle 1L"
        if self.sel == "#deliveryBlockMessage":
            if page.current in site.deliverable:
                return "FREE delivery Monday"
            return "This item cannot be shipped to your selected delivery location."
        if self.sel == "#add-to-cart-button":
            return "Add to Cart" if page.current in site.deliverable else None
        return None


class SimPage:
    def __init__(self, site):
        self.site = site
        self.pending = ""
        self.current = "000000"
        self.keyboard = self

    def locator(self, sel):
        return SimLocator(self, sel)

    def title(self):
        if self.site.captcha_after is not None and self.site.checks >= self.site.captcha_after:
            return "Robot Check"
        self.site.checks += 1
        return "Steel Bottle 1L : Amazon.in"

    def goto(self, url, **kwargs):
        pass

    def reload(self, **kwargs):
        pass

    def wait_for_selector(self, sel, **kwargs):
        pass

    def press(self, key):
        pass

    def screenshot(self, **kwargs):
        pass


class SimSite:
    """Shared fake Amazon: which pincodes are deliverable or rejected."""

    def __init__(self, deliverable=(), invalid=(), captcha_after=None):
        self.deliverable = set(deliverable)
        self.invalid = set(invalid)
        self.captcha_after = captcha_after
        self.checks = 0
        self.profiles = []
        self.closed = 0
        self.lock = threading.Lock()

    def install(self, checker_module):
        site = self

        class Context:
            def __init__(self):
                self.pages = [SimPage(site)]

            def route(self, pattern, handler):
                pass

            def close(self):
                with site.lock:
                    site.closed += 1

        class Chromium:
            def launch_persistent_context(self, **kwargs):
                with site.lock:
                    site.profiles.append(kwargs["user_data_dir"])
                return Context()

        class Playwright:
            chromium = Chromium()

        @contextmanager
        def fake_sync_playwright():
            yield Playwright()

        checker_module.sync_playwright = fake_sync_playwright


class RunLoopTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        import checker
        self.checker_module = checker
        self._orig = checker.sync_playwright

    def tearDown(self):
        self.checker_module.sync_playwright = self._orig
        super().tearDown()

    def items(self, *pins, city="chennai"):
        return [(p, city, {}) for p in pins]

    def statuses(self, c):
        return {p: r["status"] for p, r in c.results.items()}

    def test_classifies_each_pincode(self):
        SimSite(deliverable={"600001"}, invalid={"600003"}).install(self.checker_module)
        c = self.make_checker()
        c.run(self.items("600001", "600002", "600003"))
        self.assertEqual(self.statuses(c), {
            "600001": "DELIVERABLE", "600002": "NOT_DELIVERABLE", "600003": "INVALID_PINCODE"})
        saved = json.loads((self.tmp / "results/results.json").read_text())
        self.assertEqual(len(saved["results"]), 3)
        self.assertTrue((self.tmp / "results/combined_summary.json").exists())

    def test_product_title_with_bot_is_not_captcha(self):
        SimSite(deliverable={"600001"}).install(self.checker_module)
        c = self.make_checker()
        c.run(self.items("600001"))
        self.assertEqual(self.statuses(c), {"600001": "DELIVERABLE"})

    def test_max_tests_counts_only_new_pincodes_on_resume(self):
        SimSite(deliverable={"600001", "600002", "600003", "600004"}).install(self.checker_module)
        pins = self.items("600001", "600002", "600003", "600004")
        c = self.make_checker()
        c.run(pins, max_tests=2)
        self.assertEqual(set(c.results), {"600001", "600002"})
        c = self.make_checker(resume=True)
        c.run(pins, max_tests=2)
        self.assertEqual(set(c.results), {"600001", "600002", "600003", "600004"})

    def test_resume_retests_captcha_and_unknown(self):
        SimSite(deliverable={"600001", "600002"}).install(self.checker_module)
        out = self.tmp / "results/results.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"asin": "B000TEST", "results": [
            {"pincode": "600001", "status": "CAPTCHA", "region": "chennai"},
            {"pincode": "600002", "status": "UNKNOWN", "region": "chennai"},
            {"pincode": "600003", "status": "NOT_DELIVERABLE", "region": "chennai"}]}))
        c = self.make_checker(resume=True)
        c.run(self.items("600001", "600002", "600003"))
        self.assertEqual(self.statuses(c), {
            "600001": "DELIVERABLE", "600002": "DELIVERABLE", "600003": "NOT_DELIVERABLE"})

    def test_resume_refuses_other_asin(self):
        out = self.tmp / "results/results.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"asin": "OTHERASIN", "results": []}))
        with self.assertRaises(SystemExit):
            self.make_checker(resume=True)

    def test_run_without_resume_backs_up_old_results(self):
        SimSite(deliverable={"600001"}).install(self.checker_module)
        out = self.tmp / "results/results.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"asin": "B000TEST", "results": [
            {"pincode": "600009", "status": "DELIVERABLE", "region": "chennai"}]}))
        c = self.make_checker()
        c.run(self.items("600001"))
        backups = list((self.tmp / "results").glob("results.json.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text())["results"][0]["pincode"], "600009")

    def test_consecutive_captcha_stops_run(self):
        site = SimSite(deliverable={"600001"}, captcha_after=3)
        site.install(self.checker_module)
        c = self.make_checker()
        c.captcha_limit = 2
        c.run(self.items(*[f"6000{i:02d}" for i in range(1, 11)]))
        counts = list(self.statuses(c).values())
        self.assertEqual(counts.count("CAPTCHA"), 2)
        self.assertLess(len(c.results), 10)
        self.assertEqual(site.closed, 1)

    def test_workers_share_queue_without_duplicates(self):
        site = SimSite(deliverable={f"6000{i:02d}" for i in range(1, 41, 2)})
        site.install(self.checker_module)
        pins = [f"6000{i:02d}" for i in range(1, 41)]
        c = self.make_checker()
        c.run(self.items(*pins), workers=4)
        self.assertEqual(set(c.results), set(pins))
        self.assertEqual(sum(1 for s in self.statuses(c).values() if s == "DELIVERABLE"), 20)
        self.assertEqual(len(set(site.profiles)), 4)
        self.assertEqual(site.closed, 4)
        self.assertEqual(c.tested, 40)

    def test_deliverable_promotes_same_city(self):
        SimSite(deliverable={"600001"}).install(self.checker_module)
        c = self.make_checker()
        order = []
        real = c.test_pincode_with_retries
        c.test_pincode_with_retries = lambda page, pin: (order.append(pin), real(page, pin))[1]
        c.run([("600001", "chennai", {}), ("641001", "coimbatore", {}), ("600002", "chennai", {})])
        self.assertEqual(order, ["600001", "600002", "641001"])

    def test_retries_zero_does_not_crash(self):
        from checker import AmazonPincodeChecker
        SimSite(deliverable={"600001"}).install(self.checker_module)
        c = AmazonPincodeChecker(asin="B000TEST", url=None, headless=True, delay=0, retries=0,
                                 resume=False, screenshots=False, output_path="results/results.json", debug=False)
        c.run(self.items("600001"))
        self.assertEqual(self.statuses(c), {"600001": "DELIVERABLE"})
