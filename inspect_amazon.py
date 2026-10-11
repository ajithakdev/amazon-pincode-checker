import sys
import time
from playwright.sync_api import sync_playwright

DEFAULT_ASIN = "B0B5V5VHB6"


def main():
    asin = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ASIN
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(f"https://www.amazon.in/dp/{asin}", timeout=60000)
            time.sleep(3)

            # Dump location element
            loc = page.locator("#nav-global-location-slot")
            print("Location slot text:", loc.text_content() if loc.count() > 0 else "Not found")

            # Try clicking the delivery location
            try:
                page.click("#nav-global-location-slot", timeout=15000)
                time.sleep(3)
                print("Modal appeared.")
                # Find input
                inp = page.locator("#GLUXZipUpdateInput")
                print("Input visible:", inp.is_visible() if inp.count() > 0 else "Not found")

                # Look for the apply button
                apply_btn = page.locator("#GLUXZipUpdate")
                print("Apply visible:", apply_btn.is_visible() if apply_btn.count() > 0 else "Not found")

            except Exception as e:
                print("Error interacting:", e)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
