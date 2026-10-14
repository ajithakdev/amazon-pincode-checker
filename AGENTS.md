# AGENTS.md

State of the code as read on 2026-10-11 (single commit `ba602bd`). Line numbers refer to that state.

Changes made after that commit (uncommitted; sections below still describe `ba602bd` where they differ):
- `--strategy` has no fixed default: `sequential` when `--pincodes` or `--pincode` is given, else `adaptive` (`cli.py`).
- Browser: first of `chromium-browser`, `chromium`, `google-chrome`, `google-chrome-stable` found on PATH, else Playwright's bundled Chromium (`checker.py`, `run`).
- `results/` is always created.
- `results.json` is written to a `.tmp` file and renamed, so an interrupt cannot corrupt it.
- Bot check matches `captcha`, `bot check` or `robot check` in the title, not any title containing `bot`.
- `--resume` skips only DELIVERABLE and NOT_DELIVERABLE. UNKNOWN, CAPTCHA and ERROR are retested.
- `--max-tests` counts pincodes tested in this run and is enforced in `AmazonPincodeChecker.run(pincodes_list, max_tests)`.
- `run` is now `run(pincodes_list, max_tests=None, workers=1)`. It starts `worker_loop(idx)` once per worker (threads when `workers > 1`); `next_item()` hands out queue items under `self.lock`. Each worker has its own profile directory (`profile/`, `profile_w1/`, ...).
- Images, media and fonts are blocked through `context.route` unless `--load-images` or `--screenshots` is set. Fixed sleeps in `test_pincode` are replaced by polling and `wait_for_selector`.
- New status `INVALID_PINCODE` (not retried, skipped on resume). `cli.py` drops pincodes that do not match `[1-9][0-9]{5}`.
- `--resume` exits if the results file holds another ASIN. A run without `--resume` moves old results to `*.bak-<timestamp>`.
- A worker stops after `max_consecutive_captcha` (default 5) CAPTCHA results in a row. Summary files are rewritten every `analysis_every` (default 10) results and at the end.
- Retries navigate back to the product URL. `retries` is at least 1. The browser closes in `finally`; Ctrl+C saves results first.
- Data and shell scripts have `main()` guards, repo-root-relative paths, `set -euo pipefail`, and an ASIN argument.
- Tests: `python3 -m unittest discover tests` (31 tests, fake browser, no network).
- README updated to match.

## 1. What the project does

Checks whether one Amazon.in product (an ASIN) can be delivered to Indian pincodes. It drives a real Chromium browser with Playwright: open the product page, set the delivery pincode in Amazon's location modal, reload, and classify the page text as DELIVERABLE, NOT_DELIVERABLE, UNKNOWN, CAPTCHA or ERROR. The bundled dataset covers Tamil Nadu and Bengaluru only. Results go to JSON, CSV and per-region summary files under `results/`.

The code is plain scripts. There is no package, no tests, and no CI.

## 2. Setup and run

Setup (from README; the pin is in `requirements.txt`, which holds one line, `playwright==1.49.1`):

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

The browser path is hardcoded (see section 6). `/usr/bin/chromium-browser` must exist. `playwright install` is not enough.

All commands run from the repo root. Paths such as `config.json`, `data/...`, `profile/`, `results/`, `logs/` and `screenshots/` are relative to the current directory.

### cli.py (the checker)

`python cli.py [flags]`. Flags, verified against argparse in `cli.py:8-24`:

| Flag | Type / default | Effect |
|---|---|---|
| `--asin` | str | ASIN. URL becomes `https://www.amazon.in/dp/<asin>`. |
| `--url` | str | Full product URL. Wins over `--asin` for navigation. |
| `--pincodes` | path | Text file, one pincode per line, `#` lines skipped. Used only with `--strategy sequential`. |
| `--pincode` | str | Single pincode. Used only with `--strategy sequential`. |
| `--headed` | flag | Visible browser. |
| `--headless` | flag | Accepted, never read. Headless is already the default. |
| `--delay` | float | Seconds between pincodes. Falls back to `config.json`. |
| `--retries` | int | Attempts per pincode. Falls back to `config.json`. |
| `--resume` | flag | Load earlier results from `--output` and skip finished pincodes. |
| `--screenshots` | flag | Save `screenshots/<pincode>.png` after each check. |
| `--output` | path, default `results/results.json` | JSON output path. CSV is written next to it. |
| `--max-tests` | int | Truncate the pincode list to the first N. |
| `--region` | str, default `unknown` | Region label. Used only in sequential mode. |
| `--strategy` | `sequential` or `adaptive`, default `adaptive` | Pincode source. See below. |
| `--show-queue` | flag | Print the first 20 items of the adaptive queue and exit. Needs no ASIN. |
| `--debug` | flag | Sets log level to DEBUG. |

Important behaviour of `--strategy` (`cli.py:28-81`):
- The default is `adaptive`. In that mode the pincode list always comes from `data/prioritized_pincodes.json`. `--pincodes` and `--pincode` are silently ignored.
- Sequential mode requires `--pincodes` or `--pincode` (`cli.py:32`). Without `--strategy sequential`, README examples such as `python cli.py --asin B0B5V5VHB6 --pincodes pincodes.txt` do not use `pincodes.txt`.
- Exits with code 1 if neither `--asin` nor `--url` is given (unless `--show-queue`), if the adaptive JSON is missing, if the file is missing, or if the list is empty.
- Sequential region label: `--region` if not `unknown`, else inferred from the file name. `tamil_nadu` gives `tamil_nadu`. `bengaluru` or `bangalore` gives `bengaluru`. `target` gives `combined`. Otherwise `unknown` (`cli.py:68-74`).
- `--max-tests` is applied after the list is built (`cli.py:83`).

Examples that work as written:

```bash
python cli.py --asin B0B5V5VHB6 --strategy adaptive --resume
python cli.py --asin B0B5V5VHB6 --strategy sequential --pincodes data/smoke_test.txt --screenshots
python cli.py --asin B0B5V5VHB6 --strategy sequential --pincode 600034 --headed
python cli.py --show-queue
```

### Shell scripts

- `run_adaptive.sh`: activates `venv`, runs `python cli.py --asin B0B5V5VHB6 --strategy adaptive --resume`.
- `run_all.sh`: activates `venv`, then runs `cli.py --asin B0B5V5VHB6 --pincodes data/tamil_nadu_pincodes.txt --resume` and the same for `data/bengaluru_pincodes.txt`. It does not pass `--strategy sequential`. Because the default is adaptive, both runs execute the adaptive queue and ignore the files (see section 8).
- Both are executable, have no `set -e`, and hardcode the ASIN.

### Data scripts (run from the repo root, no flags)

- `python fetch_pincodes.py`: downloads `data/raw/pincodes.csv` from the first working GitHub URL. Needs network. `data/raw/` must already exist.
- `python prepare_dataset.py`: builds the Tamil Nadu, Bengaluru and combined lists plus a validation report.
- `python prioritize_dataset.py`: builds the adaptive queue files.
- `python inspect_amazon.py`: manual debugging probe. Needs network. Not used by anything else.

## 3. Code map

### `checker.py` (439 lines): class `AmazonPincodeChecker`

- `__init__` `checker.py:11`. Loads `config.json` (`:21-25`), resolves delay, retries and retry delay (`:27-29`), creates `screenshots/` and `logs/` and the output parent dir (`:32-34`), sets `profile_dir` (`:35`), configures logging (`:39-46`), and loads resume data (`:49-59`).
- `run(pincodes_list)` `:61`. Main loop. Launches a persistent Chromium context (`:68`), loads the product page (`:80`), checks for a bot challenge (`:84`), runs the queue loop (`:103-148`), and prints a summary (`:151`).
- `promote_city_in_queue(city)` `:153`. Moves every queued item with the same city to the front.
- `test_pincode_with_retries(page, pincode)` `:165`. Retry wrapper. Returns `(status, evidence, prod_details, attempt_index)`.
- `test_pincode(page, pincode)` `:186`. Browser steps: open modal, enter pincode, apply, reload, verify, then classify.
- `analyze_delivery_state(page)` `:249`. Extracts product details, collects text from selectors, classifies.
- `extract_snippet(text, keyword)` `:322`. Returns a substring window around the keyword.
- `check_for_bot_challenge(page)` `:330`. Page title or form heuristic.
- `save_results()` `:340`. Writes JSON and CSV.
- `print_summary()` `:361`. Prints status counts to stdout.
- `generate_analysis()` `:380`. Writes per-region summary files and the two pincode lists.

### `cli.py` (109 lines)

- `main()` `:7`. Argparse, builds `pincodes_list` as `(pincode, city_or_region, meta_dict)` tuples, constructs the checker, calls `run`. Guarded by `__main__` at `:108`.

### Data scripts (no functions except where listed; logic runs at import)

- `fetch_pincodes.py` (32 lines). Tries three GitHub CSV URLs (`:6-10`), writes the first success to `data/raw/pincodes.csv`, prints headers and the first row (`:26-32`).
- `inspect_amazon.py` (30 lines). Launches Playwright's own headless Chromium (not the system path), opens the hardcoded ASIN B0B5V5VHB6 page, prints the location slot text and whether the modal input and apply button are visible.
- `prepare_dataset.py` (92 lines). Reads `data/raw/pincodes.csv`. Filters and writes outputs. Helper `write_list` at `:61`.
- `prioritize_dataset.py` (108 lines). Reads the same CSV. Helper `assign_tier` at `:47`. Writes the three prioritized files.

## 4. Data pipeline and file formats

Order: `fetch_pincodes.py` then `prepare_dataset.py` and `prioritize_dataset.py` (independent of each other, both read only `data/raw/pincodes.csv`) then `cli.py`.

| File | Produced by | Format |
|---|---|---|
| `data/raw/pincodes.csv` | `fetch_pincodes.py` | CSV, quoted. Header `PostOfficeName,Pincode,DistrictsName,City,State`. Input to both prep scripts. |
| `data/raw/IN.csv` | not produced by any script | CSV, header `key,place_name,admin_name1,latitude,longitude,accuracy`, keys like `IN/110001`. Read by no script. Origin unknown. |
| `data/tamil_nadu_pincodes.txt` | `prepare_dataset.py` | One 6-digit pincode per line, sorted, unique. 2820 lines. |
| `data/bengaluru_pincodes.txt` | `prepare_dataset.py` | Same format. 93 lines. |
| `data/target_pincodes.txt` | `prepare_dataset.py` | Union of the two, sorted. 2913 lines. |
| `data/validation_report.json` | `prepare_dataset.py` | Object: `source_url`, `timestamp`, `validation{total_processed_records, malformed_pincodes, missing_state_records, duplicates_skipped}`, `results{tamil_nadu_count, bengaluru_count, combined_unique_count}`, `definition_used_for_bengaluru_city`. |
| `data/prioritized_pincodes.json` | `prioritize_dataset.py` | JSON array, 2913 objects: `pincode, state, city, district, tier, priority_score, priority_reason, status` (always `"PENDING"`). Sorted by score descending. This is the adaptive queue read by `cli.py`. |
| `data/prioritized_pincodes.txt` | `prioritize_dataset.py` | Pincodes only, same order as the JSON. Not read by any script. |
| `data/search_priority.json` | `prioritize_dataset.py` | Object: `tier_logic`, `tier_1` to `tier_4` descriptions, `city_tiers` (city to tier int). Documentation only; not read by code. |
| `data/smoke_test.txt` and `pincodes.txt` | hand-written | Same 5 pincodes: 600034, 600001, 600004, 560001, 641001. |

Filtering rules:
- Valid pincode: non-empty, length 6, digits only (`prepare_dataset.py:29`, `prioritize_dataset.py:21`).
- Tamil Nadu: `State` equals "tamil nadu", case-insensitive.
- Bengaluru: `State` is "karnataka", and `City` contains "bangalore" or "bengaluru" (or `DistrictsName` contains "bangalore"), and the pincode starts with `560`.
- `prepare_dataset.py` counts duplicates only for pincodes already in its sets. Only the first occurrence is kept.

Prioritization (`prioritize_dataset.py`):
- City name: Title-cased `City`, or `DistrictsName` if `City` is empty. All Bengaluru rows are renamed `Bengaluru` (`:31-33`).
- Tier by number of pincodes in the city (`:47-51`): at least 40 gives 1, at least 15 gives 2, at least 5 gives 3, else 4.
- The lowest pincode in each city is the representative. Score is `1000 - tier*100` for the representative and `500 - tier*100` for the rest. The first sample is therefore ahead of all non-representatives.
- The sort is stable, so ties keep city insertion order and then ascending pincode within a city.

## 5. Config (`config.json`)

| Key | Value | Read at | Effect |
|---|---|---|---|
| `delay_between_requests` | 2.0 | `checker.py:27` | Seconds slept after each pincode. A `--delay` flag overrides it. |
| `max_retries` | 3 | `checker.py:28` | Attempts per pincode. A `--retries` flag overrides it. |
| `retry_delay` | 5.0 | `checker.py:29` | Seconds slept between failed attempts. No CLI override. |
| `page_timeout` | 30000 | `checker.py:80` | Milliseconds for the initial `page.goto`. Only the initial load uses it. |
| `base_url` | `https://www.amazon.in/dp/` | not read | Unused. `checker.py:13` hardcodes the same prefix. |

`config.json` is read from the current directory. If missing, defaults in the `.get(...)` calls apply. It has no ASIN key.

## 6. How the checker works

Request flow in `run` (`checker.py:61-151`):
1. Launch `p.chromium.launch_persistent_context` with `user_data_dir=profile/` (absolute path), `executable_path='/usr/bin/chromium-browser'` (hardcoded, `:70`), the `headless` flag, viewport 1280x800, and arg `--disable-blink-features=AutomationControlled`. The `profile/` directory keeps cookies and login between runs.
2. `page.goto(url, wait_until="domcontentloaded")`. On timeout it logs an error and carries on.
3. If `check_for_bot_challenge` is true: headed mode waits on `input(...)` for Enter. Headless closes the context and returns without a summary (`:84-91`).
4. Tries to close an `.a-popover-header` popover (bare `except`).
5. Queue loop: pop the first item, skip it if resumed and finished, otherwise test it, store the result, write files, sleep `delay`.

Per-pincode steps in `test_pincode` (`:186-247`):
1. Click `#nav-global-location-slot`. If it is missing, return ERROR.
2. Wait up to 10 s for `#GLUXZipUpdateInput`. If it times out, try the link "Enter an Indian pincode".
3. Fill the pincode. Click `#GLUXZipUpdate .a-button-input` or `#GLUXZipUpdate-announce`, or press Enter if neither is found.
4. Sleep 2 s. If `#GLUXZipError` is visible and its text contains "valid", return ERROR.
5. Poll up to 5 times (1 s each) for the pincode to appear in the location slot text.
6. `page.reload(domcontentloaded)` and sleep 2 s. The reload is there to avoid stale AJAX state.
7. The location text must contain the pincode, otherwise ERROR "Location did not update successfully".
8. Call `analyze_delivery_state`.

Classification in `analyze_delivery_state` (`:249-320`):
- Product details (title, price, stock message, seller, ships-from) are read from fixed selectors. Failures are logged and ignored.
- Evidence text is the lower-cased, whitespace-collapsed text of `#deliveryBlockMessage`, `#availability`, `#mir-layout-DELIVERY_BLOCK-legalese`, `.a-color-error` and `#add-to-cart-button`. If that is empty, it uses `#rightCol` text.
- Rules, in order:
  1. Contains "cannot be shipped", "not deliverable" or "does not ship": NOT_DELIVERABLE.
  2. Contains "currently unavailable" and "we don't know when or if this item will be back in stock": NOT_DELIVERABLE.
  3. Contains "free delivery", "delivery by", "deliver to" or "arrives:", and `#add-to-cart-button` exists: DELIVERABLE.
  4. `#add-to-cart-button` exists: DELIVERABLE.
  5. Otherwise UNKNOWN with the first 200 characters of text.
- Status ERROR is never returned from this function. `test_pincode` returns ERROR for its own failures.

Bot challenge (`:330`): title contains "captcha", "bot", "amazon sign in" or "amazon sign-in", or a `form[action*='captcha']` exists. The check runs at the start of each attempt. A hit returns status CAPTCHA at once with no pause and no retry. The loop moves on to the next pincode.

Retries (`:165-184`): up to `retries` attempts. An ERROR from `test_pincode` is raised as an exception. After a failure, sleep `retry_delay` and reload the page, except on the last attempt, which returns ERROR. The attempt index is stored as `retries` in the result.

Concurrency: none. One browser, one page, one pincode at a time. Rate limiting is only the `time.sleep(delay)` after each pincode, plus the fixed sleeps inside `test_pincode`.

Adaptive reordering: when a pincode is DELIVERABLE (tested now or skipped on resume), `promote_city_in_queue(city)` moves all queued items of that city to the front. In sequential mode all items share the region label, so this does nothing useful.

State and output files:
- `results/results.json`: `{asin, tested_at, results: [...]}`. Rewritten after every pincode (`save_results`). Each result is `{...queue meta, title, seller, ships_from, price, stock_message, pincode, region, status, evidence, timestamp, screenshot, retries}`. `region` holds the city name in adaptive mode. The result `status` overwrites the queue's `"PENDING"`.
- `results/results.csv`: fixed columns `pincode, region, status, title, seller, ships_from, price, stock_message, evidence, timestamp, screenshot, retries`. It is derived from `--output` by suffix swap.
- `results/<region>_summary.json` (one per city, plus `combined_summary.json`): counts and pincode lists per status. Rewritten after every pincode. `completion_percentage` is always 100.0 and `LOGIN_REQUIRED` is always 0. The directory `results/` is hardcoded and must exist. It is created only if `--output` lives there.
- `results/deliverable_pincodes.txt` and `results/not_deliverable_pincodes.txt`.
- `logs/checker.log` (append) plus stdout.
- `screenshots/<pincode>.png` with `--screenshots`.
- `print_summary` runs only when the queue empties normally.

Resume (`__init__:49-59`, `run:108-114`): needs `--resume` and an existing `--output`. It loads previous results whose status is not ERROR. In the loop it skips pincodes with status DELIVERABLE, NOT_DELIVERABLE, UNKNOWN or CAPTCHA. ERROR pincodes are retried. The resume file is keyed by pincode, so a rerun with a different ASIN and the same `--output` mixes results.

## 7. Conventions

- Style: flat scripts, 4-space indent, double quotes mostly, f-strings, `pathlib.Path`. No type hints, no docstrings, few comments. Data scripts run at module level with no `main()` guard.
- Naming: snake_case. Status strings are upper-case literals repeated inline, not constants.
- Errors: user errors in `cli.py` use `print("Error: ...")` then `sys.exit(1)`. In `checker.py`, `test_pincode` returns `("ERROR", message, {})` tuples. The retry wrapper turns them into exceptions. Several bare `except:` blocks swallow errors (`checker.py:97,205,234,181`).
- Logging: the stdlib `logging` module with `basicConfig` inside `AmazonPincodeChecker.__init__`. It goes to `logs/checker.log` and the console, in the format `%(asctime)s [%(levelname)s] %(message)s`. Progress lines look like `[i/total] Testing pincode ...`. `print` is used for the summary and for the CLI and data scripts.
- Selectors are inline string literals in the methods. There is no central selector table.
- Timing is a mix of Playwright waits and fixed `time.sleep`.
- Queue items are `(pincode, city, meta_dict)` tuples throughout.
- Commit style: one commit, `feat: ...`.

## 8. Known gaps

- No tests, no CI config, no lint or format config, no `pyproject.toml`. `requirements.txt` pins only `playwright`.
- Hardcoded browser path `/usr/bin/chromium-browser` (`checker.py:70`). The README says system Chrome or Chromium is picked up automatically, and that `playwright install` is an option. The code supports neither. `inspect_amazon.py:5` does use Playwright's bundled browser.
- README mismatches with the code:
  - Default strategy is `adaptive` (`cli.py:22`), so README sections 5 to 8 and 15 (`--pincodes`, `--pincode`) are ignored unless `--strategy sequential` is added. Section 4's `--pincode 600034 --headed` is likewise ignored.
  - README never mentions `--strategy`, `--show-queue`, `--region`, `data/prioritized_pincodes.json`, or the adaptive queue.
  - `run_all.sh:4,6` passes `--pincodes` without `--strategy sequential`, so both runs process the same adaptive queue.
  - README section 14 says to "edit the `config.json` file" to change the ASIN. `config.json` has no ASIN key, and `base_url` is never read.
  - README section 4 and the argparse help call `--headless` a mode switch (default). The flag does nothing (`cli.py:14`, `:90-92`).
  - README section 13 says to press Enter after solving a CAPTCHA. That prompt exists only at the initial page load in headed mode (`checker.py:86-87`). A CAPTCHA seen mid-run is recorded as CAPTCHA and the run continues.
  - README section 10 lists only `results.json`, `results.csv`, `screenshots/` and `logs/checker.log`. The code also writes `results/*_summary.json`, `results/deliverable_pincodes.txt` and `results/not_deliverable_pincodes.txt`.
  - README section 2 says Python 3.8+. This was not verified; no version is declared in the repo.
  - README section 11 says "currently unavailable" alone gives NOT_DELIVERABLE. The code also requires the "we don't know when or if..." phrase (`checker.py:310`).
- `prepare_dataset.py:72` records `source_url` as `kishorek/India-Codes`, which is not one of the three URLs in `fetch_pincodes.py:6-10`. The true source of `data/raw/pincodes.csv` is therefore unclear.
- `data/raw/IN.csv`, `data/prioritized_pincodes.txt` and `data/search_priority.json` are not read by any code.
- The `profile/`, `results/`, `logs/`, `screenshots/` directories are git-ignored (`.gitignore`) and absent from the repo.
- Not run or tested here: `py_compile` passes for `checker.py` and `cli.py`. No network behaviour was exercised, so the Amazon selectors and text rules are unverified against the live site.
