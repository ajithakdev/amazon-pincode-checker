# Amazon Pincode Serviceability Checker

A robust, local automation tool to determine if a specific Amazon.in product (ASIN) is deliverable to a list of Indian pincodes.

## 1. What the tool does
Given an Amazon.in product URL or ASIN and a list of pincodes, this tool uses Playwright (browser automation) to visit the product page, change the delivery location to each pincode sequentially, and check the resulting serviceability status. It categorizes the result as `DELIVERABLE`, `NOT_DELIVERABLE`, `UNKNOWN`, `CAPTCHA`, or `ERROR` and saves the result to a CSV/JSON file along with screenshots.

## 2. Requirements
- Linux (or macOS/Windows with minor tweaks)
- Python 3.8+
- `pip`
- Google Chrome or Chromium installed on the system
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
   *(Playwright automatically uses your system Chromium/Chrome, or you can run `playwright install` to install its own).*

## 4. First-time Amazon login
Amazon often blocks automated browsers with CAPTCHAs or asks for a login when you first connect from a new profile.
To handle this, run the tool once in **headed** mode:
```bash
python cli.py --asin B0B5V5VHB6 --pincode 600034 --headed
```
The browser will open visibly. If you see a CAPTCHA or a login prompt, solve it manually in the window. After you solve it, the session is saved in the local `profile/` directory. Future runs can be executed in `--headless` mode, and they will reuse this saved session!

## 5. Basic usage
You can pass either `--asin` or `--url`. The tool requires a pincodes file or a single pincode.
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
Use `--max-tests 10` to limit how many pincodes from the file are tested in a single run.

## 8. Resume mode
If the script fails, is stopped, or hits a CAPTCHA halfway through, you can resume exactly where you left off by passing the `--resume` flag. It will read `results/results.json` and skip any pincode that has already been successfully checked.
```bash
python cli.py --asin B0B5V5VHB6 --pincodes pincodes.txt --resume
```

## 9. Debug mode
If selectors stop working or you want to see verbose logging of what text was extracted from the page, add `--debug`:
```bash
python cli.py --asin B0B5V5VHB6 --pincode 600034 --debug
```

## 10. Output files
- **`results/results.json`**: Machine-readable full results.
- **`results/results.csv`**: Tabular format of the results.
- **`screenshots/`**: PNG images capturing the state of the page (if `--screenshots` is used).
- **`logs/checker.log`**: Standard log file containing execution details.

## 11. How classification works
The tool does not rely on a single brittle CSS selector. Instead, it extracts the combined text from the right-hand column (availability section, delivery block, add-to-cart button area) and applies a scoring logic:
- `NOT_DELIVERABLE`: Triggered by explicit phrases like "cannot be shipped to your selected delivery location", "not deliverable", or "currently unavailable".
- `DELIVERABLE`: Triggered by phrases like "FREE delivery", "Deliver to", or the presence of the Add to Cart button without negative constraints.
- `UNKNOWN`: The page text is ambiguous.
- `CAPTCHA` / `ERROR`: Technical issues or Amazon bot protection.

## 12. Known limitations
- **Rate Limiting**: Amazon can block you if you send too many requests. We have built-in delays in `config.json`. Do not lower them too much.
- **Stale DOM**: Sometimes Amazon uses AJAX to update the delivery status without reloading. The tool forces a page reload after entering the pincode to prevent false positives (inheriting the previous pincode's state).

## 13. How to troubleshoot CAPTCHA/login failures
If you see `CAPTCHA/Login required` in your terminal:
1. Stop the headless script.
2. Run it again with `--headed`.
3. The browser will open. Solve the CAPTCHA or log into Amazon.
4. Press Enter in the terminal to let the script continue, or stop it and restart headless. The session is cached.

## 14. How to change the ASIN
Simply provide a different ASIN via the CLI:
```bash
python cli.py --asin B0B85X491B --pincodes pincodes.txt
```
Or edit the `config.json` file.

## 15. How to supply a larger pincode list
Create a new `.txt` file, e.g., `all_india.txt`. Put one pincode per line. Then run:
```bash
python cli.py --asin B0B5V5VHB6 --pincodes all_india.txt --resume
```
**Warning**: Do not scan hundreds of thousands of pincodes rapidly. Amazon will block your account/IP. Use the `--max-tests` argument to chunk your runs or rely on the delay logic.

## 16. License & Attribution

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE).

### Attribution Notice
Copyright (c) 2026 ajithakdev.

Under the terms of the GNU AGPLv3:
- If you fork, clone, modify, or distribute this project or integrate it into any service or network application, you **must retain explicit attribution** to the original author (`ajithakdev`).
- Any modified or derived work must also remain open source under the same GNU AGPLv3 license.
- Proprietary re-licensing or closed-source commercial redistribution of derivative works without source disclosure is strictly prohibited under AGPLv3.

