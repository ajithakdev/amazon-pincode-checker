import csv
import json
import unittest

from helpers import FakePage, TempDirTestCase


class AnalyzeTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.c = self.make_checker()

    def analyze(self, sels):
        return self.c.analyze_delivery_state(FakePage(sels))

    def test_cannot_be_shipped(self):
        s, ev, _ = self.analyze({"#deliveryBlockMessage": "This item cannot be shipped to your selected delivery location."})
        self.assertEqual(s, "NOT_DELIVERABLE")
        self.assertIn("cannot be shipped", ev)

    def test_currently_unavailable(self):
        s, _, _ = self.analyze({"#availability": "Currently unavailable. We don't know when or if this item will be back in stock."})
        self.assertEqual(s, "NOT_DELIVERABLE")

    def test_currently_unavailable_alone_not_enough(self):
        s, _, _ = self.analyze({"#availability": "Currently unavailable."})
        self.assertEqual(s, "UNKNOWN")

    def test_delivery_and_cart(self):
        s, ev, _ = self.analyze({"#deliveryBlockMessage": "FREE delivery Tomorrow", "#add-to-cart-button": "Add to Cart"})
        self.assertEqual(s, "DELIVERABLE")
        self.assertIn("delivery", ev)

    def test_cart_only(self):
        s, ev, _ = self.analyze({"#add-to-cart-button": "Add to Cart"})
        self.assertEqual(s, "DELIVERABLE")

    def test_nothing(self):
        s, ev, _ = self.analyze({})
        self.assertEqual(s, "UNKNOWN")

    def test_prod_details(self):
        _, _, d = self.analyze({"#productTitle": "  Widget ", ".a-price .a-offscreen": "Rs 99",
                                "#merchant-info": "Sold  by\n X", "#add-to-cart-button": "x"})
        self.assertEqual(d["title"], "Widget")
        self.assertEqual(d["price"], "Rs 99")
        self.assertEqual(d["seller"], "Sold by X")


class BotTests(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.c = self.make_checker()

    def test_true_titles(self):
        for t in ["Robot Check", "Bot Check", "Amazon.in CAPTCHA", "Amazon Sign In"]:
            self.assertTrue(self.c.check_for_bot_challenge(FakePage(title=t)), t)

    def test_false_titles(self):
        for t in ["Water Bottle 1L", "Robot Vacuum Cleaner", "Both Sides"]:
            self.assertFalse(self.c.check_for_bot_challenge(FakePage(title=t)), t)

    def test_captcha_form(self):
        p = FakePage({"form[action*='captcha']": "x"}, title="Whatever")
        self.assertTrue(self.c.check_for_bot_challenge(p))


class SaveResumeTests(TempDirTestCase):
    def test_save_results(self):
        c = self.make_checker()
        c.results = {"560001": {"pincode": "560001", "region": "b", "status": "DELIVERABLE"}}
        c.save_results()
        out = self.tmp / "results" / "results.json"
        data = json.loads(out.read_text())
        self.assertEqual(data["asin"], "B000TEST")
        self.assertIn("tested_at", data)
        self.assertEqual(data["results"][0]["pincode"], "560001")
        rows = list(csv.DictReader(open(out.with_suffix(".csv"))))
        self.assertEqual(rows[0]["status"], "DELIVERABLE")
        self.assertEqual(list(self.tmp.rglob("*.tmp")), [])

    def test_resume_skips_error(self):
        out = self.tmp / "results" / "results.json"
        out.parent.mkdir()
        out.write_text(json.dumps({"results": [
            {"pincode": "1", "status": "ERROR"},
            {"pincode": "2", "status": "DELIVERABLE"},
            {"pincode": "3", "status": "NOT_DELIVERABLE"}]}))
        c = self.make_checker(resume=True)
        self.assertEqual(sorted(c.results), ["2", "3"])

    def test_no_resume_ignores_file(self):
        out = self.tmp / "results" / "results.json"
        out.parent.mkdir()
        out.write_text(json.dumps({"results": [{"pincode": "2", "status": "DELIVERABLE"}]}))
        self.assertEqual(self.make_checker(resume=False).results, {})


class QueueSnippetTests(TempDirTestCase):
    def test_promote(self):
        c = self.make_checker()
        c.queue = [("1", "A", {}), ("2", "B", {}), ("3", "A", {}), ("4", "C", {}), ("5", "B", {})]
        c.promote_city_in_queue("B")
        self.assertEqual([i[0] for i in c.queue], ["2", "5", "1", "3", "4"])

    def test_promote_missing_city(self):
        c = self.make_checker()
        c.queue = [("1", "A", {}), ("2", "B", {})]
        c.promote_city_in_queue("Z")
        self.assertEqual([i[0] for i in c.queue], ["1", "2"])

    def test_snippet(self):
        c = self.make_checker()
        text = "x" * 50 + "KEY" + "y" * 100
        s = c.extract_snippet(text, "KEY")
        self.assertTrue(s.startswith("...") and s.endswith("..."))
        self.assertIn("KEY", s)
        self.assertEqual(len(s), 3 + 30 + 70 + 3)

    def test_snippet_missing_and_start(self):
        c = self.make_checker()
        self.assertEqual(c.extract_snippet("a" * 300, "zzz"), "a" * 100)
        self.assertEqual(c.extract_snippet("KEY rest", "KEY"), "...KEY rest...")


if __name__ == "__main__":
    unittest.main()
