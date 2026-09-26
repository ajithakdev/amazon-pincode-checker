import json
import logging
import time
import csv
import re
from pathlib import Path
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError, Error

class AmazonPincodeChecker:
    def __init__(self, asin, url, headless, delay, retries, resume, screenshots, output_path, debug):
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
        self.retries = retries if retries is not None else self.config.get("max_retries", 3)
        self.retry_delay = self.config.get("retry_delay", 5.0)

        # Ensure directories exist
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        Path("screenshots").mkdir(exist_ok=True)
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
                    for r in data.get("results", []):
                        if r["status"] != "ERROR":
                            self.results[r["pincode"]] = r
                self.logger.info(f"Loaded {len(self.results)} previous results for resume.")
            except Exception as e:
                self.logger.warning(f"Failed to load resume data: {e}")

    def run(self, pincodes_list):
        self.queue = list(pincodes_list)
        total_initial = len(self.queue)
        
        with sync_playwright() as p:
            self.logger.info(f"Launching browser (headless={self.headless})...")
            
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                executable_path='/usr/bin/chromium-browser',
                headless=self.headless,
                viewport={"width": 1280, "height": 800},
                args=["--disable-blink-features=AutomationControlled"]
            )
            
            page = context.pages[0] if context.pages else context.new_page()

            self.logger.info(f"Navigating to {self.url} ...")
            try:
                page.goto(self.url, wait_until="domcontentloaded", timeout=self.config.get("page_timeout", 30000))
            except TimeoutError:
                self.logger.error("Timeout loading page. Proceeding anyway.")

            if self.check_for_bot_challenge(page):
                self.logger.error("CAPTCHA/Login required on initial load.")
                if not self.headless:
                    input("Solve the challenge, then press Enter to continue...")
                else:
                    self.logger.error("Running headless. Cannot solve challenge. Exiting.")
                    context.close()
                    return
            
            try:
                close_btn = page.locator(".a-popover-header [data-action='a-popover-close']")
                if close_btn.is_visible(timeout=2000):
                    close_btn.click()
            except:
                pass

            self.logger.info("Ready to process pincodes.")
            
            processed = 0
            while self.queue:
                item = self.queue.pop(0)
                pincode, city, meta = item
                processed += 1
                
                if pincode in self.results and self.resume:
                    existing_status = self.results[pincode].get('status', '')
                    if existing_status in ['DELIVERABLE', 'NOT_DELIVERABLE', 'UNKNOWN', 'CAPTCHA']:
                        self.logger.info(f"[{processed}/{total_initial}] {pincode} - Skipping (already tested: {existing_status})")
                        if existing_status == 'DELIVERABLE':
                            self.promote_city_in_queue(city)
                        continue
                
                tier = meta.get('tier', 'Unknown')
                score = meta.get('priority_score', 0)
                self.logger.info(f"[{processed}/{total_initial}] Testing pincode {pincode} (City: {city}, Tier: {tier}, Score: {score})...")
                
                status, evidence, prod_details, retries = self.test_pincode_with_retries(page, pincode)
                
                self.logger.info(f"  Product delivery state: {status}")
                
                screenshot_path = ""
                if self.screenshots:
                    screenshot_path = str(Path("screenshots") / f"{pincode}.png")
                    page.screenshot(path=screenshot_path)
                
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
                self.generate_analysis()
                time.sleep(self.delay)

            context.close()
            self.print_summary()

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
                        page.reload(wait_until="domcontentloaded", timeout=20000)
                    except:
                        pass
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
                except:
                    pass

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
            
        time.sleep(2)
        
        invalid_err = page.locator("#GLUXZipError")
        if invalid_err.is_visible() and "valid" in invalid_err.text_content().lower():
            return "ERROR", "Invalid pincode entered", {}

        try:
            for _ in range(5):
                loc_text = page.locator("#nav-global-location-slot").text_content()
                if loc_text and str(pincode) in loc_text:
                    break
                time.sleep(1)
        except:
            pass
            
        page.reload(wait_until="domcontentloaded")
        time.sleep(2)
        
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
        
        if "cannot be shipped" in combined_text or "not deliverable" in combined_text or "does not ship" in combined_text:
            return "NOT_DELIVERABLE", self.extract_snippet(combined_text, "cannot be shipped"), prod_details
            
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
        if "captcha" in title or "bot" in title:
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
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
            
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
                "LOGIN_REQUIRED": 0,
                "ERROR": 0,
                "completion_percentage": 100.0,
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
