import json
import logging
import os
import shutil
import sys
import threading
import time
import csv
import re
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError, Error

class AmazonPincodeChecker:
    # Statuses that --resume does not test again
    DONE_STATUSES = ('DELIVERABLE', 'NOT_DELIVERABLE', 'INVALID_PINCODE')

    def __init__(self, asin, url, headless, delay, retries, resume, screenshots, output_path, debug, block_resources=True):
        self.asin = asin
        self.url = url or f"https://www.amazon.in/dp/{asin}"
        self.headless = headless
        self.resume = resume
        self.screenshots = screenshots
        self.output_path = Path(output_path)
        self.debug = debug

        # Load config
        self.config = {}
        config_path = Path("config.json")
        if config_path.exists():
            with open(config_path, "r") as f:
                self.config = json.load(f)

        self.delay = delay if delay is not None else self.config.get("delay_between_requests", 2.0)
        self.retries = max(1, retries if retries is not None else self.config.get("max_retries", 3))
        # Images, media and fonts are not needed to read delivery text; keep them when taking screenshots
        self.block_resources = block_resources and not screenshots
        self.captcha_limit = self.config.get("max_consecutive_captcha", 5)
        self.analysis_every = self.config.get("analysis_every", 10)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.retry_delay = self.config.get("retry_delay", 5.0)

        # Ensure directories exist
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        Path("screenshots").mkdir(exist_ok=True)
        Path("results").mkdir(exist_ok=True)
        Path("logs").mkdir(exist_ok=True)
        self.profile_dir = Path("profile").absolute()

        # Setup logging
        log_level = logging.DEBUG if self.debug else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler("logs/checker.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

        self.results = {}
        if self.resume and self.output_path.exists():
            try:
                with open(self.output_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    stored_asin = data.get("asin")
                    if stored_asin and self.asin and stored_asin != self.asin:
                        print(f"Error: {self.output_path} holds results for ASIN {stored_asin}, not {self.asin}. Use a different --output.")
                        sys.exit(1)
                    for r in data.get("results", []):
                        if r["status"] != "ERROR":
                            self.results[r["pincode"]] = r
                self.logger.info(f"Loaded {len(self.results)} previous results for resume.")
            except (OSError, ValueError, KeyError) as e:
                self.logger.warning(f"Failed to load resume data: {e}")

    def run(self, pincodes_list, max_tests=None, workers=1):
        self.queue = list(pincodes_list)
        self.total_initial = len(self.queue)
        self.max_tests = max_tests
        self.processed = 0
        self.tested = 0
        self.since_analysis = 0
        self.stop_event.clear()
        workers = max(1, min(workers or 1, len(self.queue) or 1))
        self.backup_previous_output()

        threads = []
        try:
            if workers == 1:
                self.worker_loop(0)
            else:
                self.logger.info(f"Starting {workers} browser workers...")
                for idx in range(workers):
                    t = threading.Thread(target=self.worker_loop, args=(idx,), daemon=True)
                    t.start()
                    threads.append(t)
                # Join with a timeout so Ctrl+C reaches the main thread
                while any(t.is_alive() for t in threads):
                    for t in threads:
                        t.join(timeout=0.5)
        except KeyboardInterrupt:
            self.logger.warning("Interrupted. Stopping workers and saving results...")
            self.stop_event.set()
            for t in threads:
                t.join(timeout=30)
        finally:
            with self.lock:
                if self.results:
                    self.save_results()
                    self.generate_analysis()

        self.print_summary()

    def backup_previous_output(self):
        # A run without --resume must not silently destroy earlier results
        if self.resume or not self.output_path.exists():
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for path in (self.output_path, self.output_path.with_suffix('.csv')):
            if path.exists():
                backup = path.with_name(f"{path.name}.bak-{stamp}")
                os.replace(path, backup)
                self.logger.info(f"Existing {path} moved to {backup}")

    def next_item(self):
        with self.lock:
            while self.queue and not self.stop_event.is_set():
                if self.max_tests and self.tested >= self.max_tests:
                    self.logger.info(f"Reached --max-tests limit ({self.max_tests}). Stopping.")
                    self.stop_event.set()
                    return None
                item = self.queue.pop(0)
                pincode, city, meta = item
                self.processed += 1

                if pincode in self.results and self.resume:
                    existing_status = self.results[pincode].get('status', '')
                    if existing_status in self.DONE_STATUSES:
                        self.logger.info(f"[{self.processed}/{self.total_initial}] {pincode} - Skipping (already tested: {existing_status})")
                        if existing_status == 'DELIVERABLE':
                            self.promote_city_in_queue(city)
                        continue

                self.tested += 1
                return item, self.processed
            return None

    def block_heavy_resources(self, route):
        if route.request.resource_type in ("image", "media", "font"):
            route.abort()
        else:
            route.continue_()

    def worker_loop(self, idx):
        # Each worker needs its own profile: the delivery pincode is stored per browser session
        profile_dir = self.profile_dir if idx == 0 else self.profile_dir.with_name(f"{self.profile_dir.name}_w{idx}")
        tag = f"[w{idx}] " if idx else ""

        with sync_playwright() as p:
            self.logger.info(f"{tag}Launching browser (headless={self.headless})...")

            launch_kwargs = {
                "user_data_dir": str(profile_dir),
                "headless": self.headless,
                "viewport": {"width": 1280, "height": 800},
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            # Prefer a system browser; fall back to Playwright's bundled Chromium
            for name in ("chromium-browser", "chromium", "google-chrome", "google-chrome-stable"):
                browser_path = shutil.which(name)
                if browser_path:
                    launch_kwargs["executable_path"] = browser_path
                    break

            context = p.chromium.launch_persistent_context(**launch_kwargs)
            try:
                if self.block_resources:
                    context.route("**/*", self.block_heavy_resources)

                page = context.pages[0] if context.pages else context.new_page()

                self.logger.info(f"{tag}Navigating to {self.url} ...")
                try:
                    page.goto(self.url, wait_until="domcontentloaded", timeout=self.config.get("page_timeout", 30000))
                except TimeoutError:
                    self.logger.error(f"{tag}Timeout loading page. Proceeding anyway.")

                if self.check_for_bot_challenge(page):
                    self.logger.error(f"{tag}CAPTCHA/Login required on initial load.")
                    if not self.headless and idx == 0:
                        try:
                            input("Solve the challenge, then press Enter to continue...")
                        except EOFError:
                            self.logger.error("No terminal available to confirm. Exiting.")
                            return
                    else:
                        self.logger.error(f"{tag}Cannot solve challenge here. Run once with --headed (profile: {profile_dir}). Worker exiting.")
                        return

                try:
                    close_btn = page.locator(".a-popover-header .a-icon-close, [data-action='a-popover-close']")
                    if close_btn.count() > 0 and close_btn.first.is_visible():
                        close_btn.first.click()
                except Exception as e:
                    self.logger.debug(f"{tag}Popover close skipped: {e}")

                self.logger.info(f"{tag}Ready to process pincodes.")

                consecutive_captcha = 0
                while not self.stop_event.is_set():
                    nxt = self.next_item()
                    if nxt is None:
                        break
                    (pincode, city, meta), position = nxt

                    tier = meta.get('tier', 'Unknown')
                    score = meta.get('priority_score', 0)
                    self.logger.info(f"{tag}[{position}/{self.total_initial}] Testing pincode {pincode} (City: {city}, Tier: {tier}, Score: {score})...")

                    status, evidence, prod_details, retries = self.test_pincode_with_retries(page, pincode)

                    self.logger.info(f"{tag}  Product delivery state: {status}")

                    screenshot_path = ""
                    if self.screenshots:
                        screenshot_path = str(Path("screenshots") / f"{pincode}.png")
                        try:
                            page.screenshot(path=screenshot_path)
                        except Exception as e:
                            self.logger.warning(f"{tag}Screenshot failed for {pincode}: {e}")
                            screenshot_path = ""

                    with self.lock:
                        self.results[pincode] = {
                            **meta,
                            **prod_details,
                            "pincode": pincode,
                            "region": city,
                            "status": status,
                            "evidence": evidence,
                            "timestamp": datetime.now().isoformat(),
                            "screenshot": screenshot_path,
                            "retries": retries
                        }

                        if status == "DELIVERABLE":
                            self.logger.info(f">>> DELIVERY SUCCESS FOUND for {city} ({pincode})")
                            self.logger.info(f">>> Expanding search within {city}")
                            self.promote_city_in_queue(city)

                        self.save_results()
                        self.since_analysis += 1
                        if self.since_analysis >= self.analysis_every:
                            self.generate_analysis()
                            self.since_analysis = 0

                    if status == "CAPTCHA":
                        consecutive_captcha += 1
                        if consecutive_captcha >= self.captcha_limit:
                            self.logger.error(f"{tag}{consecutive_captcha} CAPTCHA results in a row. Worker stopping; solve it with --headed, then rerun with --resume.")
                            break
                    else:
                        consecutive_captcha = 0

                    time.sleep(self.delay)
            finally:
                try:
                    context.close()
                except Exception as e:
                    self.logger.debug(f"{tag}Context close failed: {e}")

    def promote_city_in_queue(self, city):
        promoted = []
        remaining = []
        for item in self.queue:
            if item[1] == city:
                promoted.append(item)
            else:
                remaining.append(item)
        if promoted:
            self.logger.info(f">>> Prioritizing {len(promoted)} remaining {city} pincodes")
        self.queue = promoted + remaining

    def test_pincode_with_retries(self, page, pincode):
        for attempt in range(self.retries):
            try:
                if self.check_for_bot_challenge(page):
                    return "CAPTCHA", "Detected captcha or login challenge", {}, attempt
                
                status, evidence, prod_details = self.test_pincode(page, pincode)
                if status == "ERROR":
                    raise Exception(f"Internal error: {evidence}")
                return status, evidence, prod_details, attempt
            except Exception as e:
                self.logger.error(f"Attempt {attempt+1}/{self.retries} failed for {pincode}: {e}")
                if attempt < self.retries - 1:
                    time.sleep(self.retry_delay)
                    try:
                        # Go back to the product page; a reload would stay on an error or sign-in page
                        page.goto(self.url, wait_until="domcontentloaded", timeout=20000)
                    except Exception as nav_err:
                        self.logger.debug(f"Navigation before retry failed: {nav_err}")
                else:
                    return "ERROR", str(e), {}, attempt
                    
    def test_pincode(self, page, pincode):
        # 1. Open location modal
        loc_button = page.locator("#nav-global-location-slot")
        if loc_button.count() == 0:
            return "ERROR", "Location button not found", {}
            
        loc_button.click()
        
        # 2. Wait for modal
        try:
            inp = page.locator("#GLUXZipUpdateInput")
            inp.wait_for(state="visible", timeout=10000)
        except TimeoutError:
            if page.locator("#GLUXZipUpdateInput").count() == 0:
                try:
                    change_link = page.locator("a:has-text('Enter an Indian pincode')")
                    if change_link.is_visible():
                        change_link.click()
                        page.locator("#GLUXZipUpdateInput").wait_for(state="visible", timeout=5000)
                except Exception as e:
                    self.logger.debug(f"Pincode link fallback failed: {e}")

        inp = page.locator("#GLUXZipUpdateInput")
        if not inp.is_visible():
            return "ERROR", "Pincode input not visible", {}
            
        # 3. Enter pincode
        inp.fill(str(pincode))
        
        # 4. Click apply
        apply_btn = page.locator("#GLUXZipUpdate .a-button-input, #GLUXZipUpdate-announce")
        if apply_btn.count() > 0:
            apply_btn.first.click()
        else:
            page.keyboard.press("Enter")

        # 5. Poll until the location updates or Amazon rejects the pincode (up to 7s)
        for _ in range(28):
            try:
                invalid_err = page.locator("#GLUXZipError")
                if invalid_err.is_visible() and "valid" in (invalid_err.text_content() or "").lower():
                    return "INVALID_PINCODE", "Amazon rejected the pincode as invalid", {}
                loc_text = page.locator("#nav-global-location-slot").text_content()
                if loc_text and str(pincode) in loc_text:
                    break
            except Exception as e:
                # The page may be navigating after the pincode was applied
                self.logger.debug(f"Location poll error: {e}")
            time.sleep(0.25)

        page.reload(wait_until="domcontentloaded")
        try:
            page.wait_for_selector(
                "#deliveryBlockMessage, #availability, #add-to-cart-button, #outOfStock",
                state="attached", timeout=5000
            )
        except TimeoutError:
            self.logger.debug("Delivery block did not appear within 5s.")
        
        # 6. Verify location updated
        loc_text = page.locator("#nav-global-location-slot").text_content() or ""
        if str(pincode) not in loc_text:
            self.logger.warning(f"Location text '{loc_text.strip()}' does not contain {pincode}. It failed to update.")
            return "ERROR", "Location did not update successfully", {}
            
        # 7. Check delivery state on product page
        return self.analyze_delivery_state(page)

    def analyze_delivery_state(self, page):
        # Extract product details
        prod_details = {
            "title": "",
            "seller": "",
            "ships_from": "",
            "price": "",
            "stock_message": ""
        }
        
        try:
            prod_details["title"] = page.locator("#productTitle").first.text_content().strip() if page.locator("#productTitle").count() > 0 else ""
            prod_details["price"] = page.locator(".a-price .a-offscreen").first.text_content().strip() if page.locator(".a-price .a-offscreen").count() > 0 else ""
            
            # Stock message
            if page.locator("#availability").count() > 0:
                prod_details["stock_message"] = page.locator("#availability").first.text_content().strip()
                prod_details["stock_message"] = re.sub(r'\s+', ' ', prod_details["stock_message"])
                
            # Seller info
            if page.locator("#sellerProfileTriggerId").count() > 0:
                prod_details["seller"] = page.locator("#sellerProfileTriggerId").first.text_content().strip()
            elif page.locator("#merchant-info").count() > 0:
                prod_details["seller"] = page.locator("#merchant-info").first.text_content().strip()
                prod_details["seller"] = re.sub(r'\s+', ' ', prod_details["seller"])
                
            # Ships from
            if page.locator(".tabular-buybox-text[tabular-attribute-name='Ships from']").count() > 0:
                prod_details["ships_from"] = page.locator(".tabular-buybox-text[tabular-attribute-name='Ships from']").first.text_content().strip()
        except Exception as e:
            self.logger.error(f"Error extracting product details: {e}")

        # We need to collect text from the delivery/availability sections
        selectors_to_check = [
            "#deliveryBlockMessage",
            "#availability",
            "#mir-layout-DELIVERY_BLOCK-legalese",
            ".a-color-error",
            "#add-to-cart-button"
        ]
        
        evidence = []
        for sel in selectors_to_check:
            locs = page.locator(sel)
            for i in range(locs.count()):
                text = locs.nth(i).text_content()
                if text:
                    evidence.append(text.strip())
                    
        combined_text = " ".join(evidence).lower()
        combined_text = re.sub(r'\s+', ' ', combined_text)
        
        if not combined_text:
            right_col = page.locator("#rightCol")
            if right_col.count() > 0:
                combined_text = right_col.text_content().lower()
                combined_text = re.sub(r'\s+', ' ', combined_text)
        
        for phrase in ("cannot be shipped", "not deliverable", "does not ship"):
            if phrase in combined_text:
                return "NOT_DELIVERABLE", self.extract_snippet(combined_text, phrase), prod_details
            
        if "currently unavailable" in combined_text and "we don't know when or if this item will be back in stock" in combined_text:
            return "NOT_DELIVERABLE", "Currently unavailable", prod_details
            
        if "free delivery" in combined_text or "delivery by" in combined_text or "deliver to" in combined_text or "arrives:" in combined_text:
            if page.locator("#add-to-cart-button").count() > 0:
                return "DELIVERABLE", self.extract_snippet(combined_text, "delivery"), prod_details
        
        if page.locator("#add-to-cart-button").count() > 0:
            return "DELIVERABLE", "Add to cart button available", prod_details
            
        return "UNKNOWN", combined_text[:200], prod_details
        
    def extract_snippet(self, text, keyword):
        idx = text.find(keyword)
        if idx == -1:
            return text[:100]
        start = max(0, idx - 30)
        end = min(len(text), idx + 70)
        return "..." + text[start:end] + "..."

    def check_for_bot_challenge(self, page):
        title = page.title().lower()
        if re.search(r"captcha|\b(ro)?bot check\b", title):
            return True
        if page.locator("form[action*='captcha']").count() > 0:
            return True
        if "amazon sign in" in title or "amazon sign-in" in title:
            return True
        return False

    def save_results(self):
        output = {
            "asin": self.asin,
            "tested_at": datetime.now().isoformat(),
            "results": list(self.results.values())
        }
        # Write to a temp file first so an interrupt cannot corrupt the resume file
        tmp_path = self.output_path.with_name(self.output_path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        os.replace(tmp_path, self.output_path)
            
        # Also save CSV
        csv_path = self.output_path.with_suffix('.csv')
        if not self.results:
            return
            
        keys = ["pincode", "region", "status", "title", "seller", "ships_from", "price", "stock_message", "evidence", "timestamp", "screenshot", "retries"]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction='ignore')
            writer.writeheader()
            for r in self.results.values():
                writer.writerow(r)

    def print_summary(self):
        summary = {
            "DELIVERABLE": 0,
            "NOT_DELIVERABLE": 0,
            "UNKNOWN": 0,
            "INVALID_PINCODE": 0,
            "CAPTCHA": 0,
            "ERROR": 0
        }
        for r in self.results.values():
            st = r["status"]
            if st in summary:
                summary[st] += 1
            else:
                summary[st] = 1
                
        print("\n=== SUMMARY ===")
        for k, v in summary.items():
            print(f"{k.ljust(17)} {v}")
            
    def generate_analysis(self):
        # group by region
        regions = {}
        for r in self.results.values():
            reg = r.get("region", "unknown")
            if reg not in regions:
                regions[reg] = []
            regions[reg].append(r)
            
        # combined
        regions["combined"] = list(self.results.values())
        
        deliverable_pins = []
        not_deliverable_pins = []
        
        for reg, items in regions.items():
            stats = {
                "total_tested": len(items),
                "DELIVERABLE": 0,
                "NOT_DELIVERABLE": 0,
                "UNKNOWN": 0,
                "CAPTCHA": 0,
                "INVALID_PINCODE": 0,
                "ERROR": 0,
                "deliverable_pincodes": [],
                "not_deliverable_pincodes": [],
                "unknown_pincodes": [],
                "failed_pincodes": []
            }
            
            for item in items:
                st = item["status"]
                pin = item["pincode"]
                if st in stats:
                    stats[st] += 1
                    
                if st == "DELIVERABLE":
                    stats["deliverable_pincodes"].append(pin)
                    if reg == "combined": deliverable_pins.append(pin)
                elif st == "NOT_DELIVERABLE":
                    stats["not_deliverable_pincodes"].append(pin)
                    if reg == "combined": not_deliverable_pins.append(pin)
                elif st == "UNKNOWN":
                    stats["unknown_pincodes"].append(pin)
                elif st in ["ERROR", "CAPTCHA"]:
                    stats["failed_pincodes"].append(pin)
                    
            summary_path = Path(f"results/{reg}_summary.json")
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2)
                
        # Write specific lists
        with open("results/deliverable_pincodes.txt", "w", encoding="utf-8") as f:
            for p in deliverable_pins:
                f.write(f"{p}\n")
                
        with open("results/not_deliverable_pincodes.txt", "w", encoding="utf-8") as f:
            for p in not_deliverable_pins:
                f.write(f"{p}\n")
