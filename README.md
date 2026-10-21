# Amazon Pincode Serviceability Checker

Every link and how-to is in [RESOURCES-AND-GUIDE.md](RESOURCES-AND-GUIDE.md).

A robust, local automation tool to determine if a specific Amazon.in product (ASIN) is deliverable to a list of Indian pincodes.

## 1. What the tool does
Given an Amazon.in product URL or ASIN and a list of pincodes, this tool uses Playwright (browser automation) to visit the product page, change the delivery location to each pincode sequentially, and check the resulting serviceability status. It categorizes the result as `DELIVERABLE`, `NOT_DELIVERABLE`, `UNKNOWN`, `CAPTCHA`, or `ERROR` and saves the result to a CSV/JSON file along with screenshots.

## 2. Requirements
- Linux (or macOS/Windows with minor tweaks)
- Python 3.8+
- `pip`
- Google Chrome or Chromium installed on the system (optional, see section 3)
- Playwright for Python

## 3. Installation
1. Clone or download this project.
2. Create a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   The checker looks for a system Chromium/Chrome on `PATH` (`chromium-browser`, `chromium`, `google-chrome`, `google-chrome-stable`). If none is found, it falls back to Playwright's bundled Chromium. Install it with:
   ```bash
   playwright install chromium
   ```

## 4. First-time Amazon login
Amazon often blocks automated browsers with CAPTCHAs or asks for a login when you first connect from a new profile.
To handle this, run the tool once in **headed** mode:
```bash
python cli.py --asin B0B5V5VHB6 --pincode 600034 --headed
```
The browser will open visibly. If you see a CAPTCHA or a login prompt, solve it manually in the window. After you solve it, the session is saved in the local `profile/` directory. Future runs can be executed headless, and they will reuse this saved session! `--headless` is the default, so the flag is optional.

## 5. Basic usage
You can pass either `--asin` or `--url`. The tool requires a pincodes file or a single pincode. When `--pincodes` or `--pincode` is given, the strategy is `sequential` and that file or pincode is used (see section 9 for the adaptive mode used otherwise).
```bash
python cli.py --asin B0B5V5VHB6 --pincodes pincodes.txt
```

## 6. Single-pincode usage
To quickly test just one pincode without a file:
```bash
python cli.py --asin B0B5V5VHB6 --pincode 600034
```

## 7. Batch usage
Put your pincodes in a text file (one per line, comments with `#` are ignored) like `pincodes.txt`.
```bash
python cli.py --url "https://www.amazon.in/dp/B0B5V5VHB6" --pincodes pincodes.txt --screenshots
```
Use `--max-tests 10` to limit how many pincodes are actually tested in a single run. Pincodes skipped by `--resume` do not count.

## 8. Resume mode
If the script fails, is stopped, or hits a CAPTCHA halfway through, you can resume exactly where you left off by passing the `--resume` flag. It will read `results/results.json` and skip only pincodes already recorded as `DELIVERABLE`, `NOT_DELIVERABLE` or `INVALID_PINCODE`. `--resume` refuses a results file that belongs to a different ASIN; use another `--output` per product. A run without `--resume` moves an existing results file to `results.json.bak-<timestamp>` first. Pincodes recorded as `UNKNOWN`, `CAPTCHA` or `ERROR` are tested again.
```bash
python cli.py --asin B0B5V5VHB6 --pincodes pincodes.txt --resume
```

## 9. Adaptive mode
If you pass neither `--pincodes` nor `--pincode`, the strategy is `adaptive`. It reads `data/prioritized_pincodes.json` and, whenever a pincode is `DELIVERABLE`, moves the other queued pincodes of the same city to the front. You can also pass `--strategy sequential` or `--strategy adaptive` explicitly.
```bash
python cli.py --asin B0B5V5VHB6 --strategy adaptive --show-queue
python cli.py --asin B0B5V5VHB6 --pincodes pincodes.txt --region chennai
./run_adaptive.sh
```
- `--strategy sequential|adaptive`: pick the queue strategy. Default: `sequential` with `--pincodes`/`--pincode`, otherwise `adaptive`.
- `--show-queue`: print the top 20 items of the prioritized queue and exit.
- `--region`: region label used to group results with `--pincodes`/`--pincode` (summary files are written per region). It does not filter the adaptive queue.
- `data/prioritized_pincodes.json`: the adaptive queue. Build it by running the data scripts in this order: `fetch_pincodes.py`, then `prepare_dataset.py`, then `prioritize_dataset.py`.
- `run_adaptive.sh`: runs `cli.py --strategy adaptive --resume`. It hardcodes the ASIN.

## 10. Debug mode
If selectors stop working or you want to see verbose logging of what text was extracted from the page, add `--debug`:
```bash
python cli.py --asin B0B5V5VHB6 --pincode 600034 --debug
```

## 11. Output files
- **`results/results.json`**: Machine-readable full results.
- **`results/results.csv`**: Tabular format of the results.
- **`results/<region>_summary.json`**: Counts and pincode lists per status for each region.
- **`results/combined_summary.json`**: The same summary across all regions.
- **`results/deliverable_pincodes.txt`**: Pincodes found `DELIVERABLE`.
- **`results/not_deliverable_pincodes.txt`**: Pincodes found `NOT_DELIVERABLE`.
- **`screenshots/`**: PNG images capturing the state of the page (if `--screenshots` is used).
- **`logs/checker.log`**: Standard log file containing execution details.

## 12. How classification works
The tool does not rely on a single brittle CSS selector. Instead, it extracts the combined text from the right-hand column (availability section, delivery block, add-to-cart button area) and applies a scoring logic:
Rules are applied in order:
1. `NOT_DELIVERABLE`: the text contains "cannot be shipped", "not deliverable" or "does not ship".
2. `NOT_DELIVERABLE`: the text contains "currently unavailable" and "we don't know when or if this item will be back in stock".
3. `DELIVERABLE`: the text contains "free delivery", "delivery by", "deliver to" or "arrives:", and the Add to Cart button exists.
4. `DELIVERABLE`: the Add to Cart button exists.
5. `UNKNOWN`: none of the above; the page text is ambiguous.
- `INVALID_PINCODE`: Amazon's location box rejected the pincode. It is not retried and `--resume` skips it.
- `CAPTCHA` / `ERROR`: Technical issues or Amazon bot protection.

## 13. Known limitations
- **Rate Limiting**: Amazon can block you if you send too many requests. We have built-in delays in `config.json`. Do not lower them too much.
- **Stale DOM**: Sometimes Amazon uses AJAX to update the delivery status without reloading. The tool forces a page reload after entering the pincode to prevent false positives (inheriting the previous pincode's state).

## 14. How to troubleshoot CAPTCHA/login failures
If you see `CAPTCHA/Login required` in your terminal:
1. Stop the script.
2. Run it again with `--headed`.
3. The browser will open. Solve the CAPTCHA or log into Amazon.
4. Press Enter in the terminal when asked. This prompt appears only at the initial page load in headed mode. The session is cached, so later runs can be headless.

A CAPTCHA that appears in the middle of a run is recorded as `CAPTCHA` for that pincode and the run continues. Those pincodes are tested again on the next `--resume` run.

## 15. How to change the ASIN
The ASIN is not stored in `config.json`. Set it with `--asin` or `--url`:
```bash
python cli.py --asin B0B85X491B --pincodes pincodes.txt
```
The shell scripts (`run_adaptive.sh`, `run_all.sh`) hardcode the ASIN, so edit them to change it.

`config.json` only holds tuning values: `delay_between_requests`, `max_retries`, `retry_delay` and `page_timeout`.

## 16. How to supply a larger pincode list
Create a new `.txt` file, e.g., `all_india.txt`. Put one pincode per line. Then run:
```bash
python cli.py --asin B0B5V5VHB6 --pincodes all_india.txt --resume
```
**Warning**: Do not scan hundreds of thousands of pincodes rapidly. Amazon will block your account/IP. Use the `--max-tests` argument to chunk your runs or rely on the delay logic.

## 17. Speed and parallel workers
Images, media and fonts are blocked by default, and the checker waits for page elements instead of sleeping for fixed times. Pass `--load-images` to load everything (screenshots load everything automatically).

To go faster, run several browsers at once:
```bash
python cli.py --asin B0B5V5VHB6 --pincodes data/tamil_nadu_pincodes.txt --resume --workers 3 --delay 1
```
- Each worker uses its own browser profile: `profile/` for the first, `profile_w1/`, `profile_w2/`, ... for the rest. Amazon stores the delivery pincode per session, so workers cannot share one.
- A new profile has no saved session. If a worker hits a CAPTCHA on its first page it logs the profile path and exits; the other workers continue.
- A worker stops after 5 CAPTCHA results in a row (`max_consecutive_captcha` in `config.json`). Solve the CAPTCHA with `--headed`, then rerun with `--resume`.
- More workers and a lower `--delay` raise the chance of CAPTCHAs. Start with 2 or 3.

## 18. Tests
The tests use a fake browser, so they need no network and no Playwright install:
```bash
python3 -m unittest discover tests
```

## 19. License & Attribution

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE).

### Attribution Notice
Copyright (c) 2026 ajithakdev.

Under the terms of the GNU AGPLv3:
- If you fork, clone, modify, or distribute this project or integrate it into any service or network application, you **must retain explicit attribution** to the original author (`ajithakdev`).
- Any modified or derived work must also remain open source under the same GNU AGPLv3 license.
- Proprietary re-licensing or closed-source commercial redistribution of derivative works without source disclosure is strictly prohibited under AGPLv3.

