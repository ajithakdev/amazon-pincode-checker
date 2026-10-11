# Enhancement Plan

Scope: all tracked Python, shell, config and README files, plus the format of the data files. Line numbers refer to the tree at commit `ba602bd`. Nothing was run against Amazon; every bug below was confirmed by reading the code (and, where noted, a small offline check). Items I could not confirm are marked "Unverified".

## 1. Summary

Status on branch `fix/bugs-and-speed`: fixed B1 to B9, B12 to B15, B17, B18, B19, B21 to B26. Open: B10 and B11 (classification rules; need real Amazon pages to change safely), B16 (tier design), B20. Parallel workers, resource blocking and an offline test suite are added. None of this has been run against the live site.

The project is a single-threaded Playwright script that drives the Amazon.in location widget one pincode at a time, with a prioritised Tamil Nadu / Bengaluru queue. The core idea works, but the default CLI path does not do what the README says, the output writes are not crash-safe, and the serviceability classifier has several false-positive paths. There are no tests, no CI and no packaging.

Do these five first:

1. B1: the default `--strategy adaptive` ignores `--pincode` and `--pincodes`, so every README example and `run_all.sh` runs the full 2913-pincode queue.
2. B2/B3: stop hard-coding `/usr/bin/chromium-browser` and make sure `results/` exists before writing.
3. B4: write results atomically so an interrupt cannot destroy the resume file.
4. B5/B6: fix the `"bot" in title` CAPTCHA test and stop treating CAPTCHA/UNKNOWN as "done" on resume.
5. P1: stop rewriting 288 summary files after every pincode.

## 2. Bugs

### Critical

**B1. Default strategy ignores the pincode arguments** - `cli.py:22`, `cli.py:32-38`, `cli.py:54-55`, `run_all.sh:4,6`
`--strategy` defaults to `adaptive`. The validation at line 32 only requires `--pincode(s)` when the strategy is not adaptive, and the adaptive branch (line 38) always loads `data/prioritized_pincodes.json` and never looks at `args.pincodes`, `args.pincode` or `args.region`. So `python cli.py --asin X --pincode 600034` (README sections 4, 6), `--pincodes pincodes.txt` (sections 5, 7, 8, 15) and both commands in `run_all.sh` all run the whole 2913-pincode adaptive queue against Amazon. `run_all.sh` therefore runs the same adaptive scan twice and never reads the TN/Bengaluru files. A user following the README for a one-pincode test starts a multi-hour scan that risks an IP block.
Fix: infer the strategy from the arguments and reject conflicts.
```python
parser.add_argument("--strategy", choices=["sequential", "adaptive"], default=None)
...
if args.strategy is None:
    args.strategy = "sequential" if (args.pincode or args.pincodes) else "adaptive"
if args.strategy == "adaptive" and (args.pincode or args.pincodes):
    parser.error("--pincode/--pincodes cannot be combined with --strategy adaptive")
```

### High

**B2. Hard-coded browser path** - `checker.py:70`
`executable_path='/usr/bin/chromium-browser'` makes `launch_persistent_context` fail on any machine without that exact file (macOS, Windows, Fedora where it is `chromium`, snap installs, Chrome-only machines). README sections 2-3 claim Playwright "automatically uses your system Chromium/Chrome"; it does not, and the code never falls back to the bundled browser.
Fix: take the path from `config.json` or `--browser-path`, default to Playwright's bundled Chromium (`channel="chromium"` or no `executable_path`), and use `channel="chrome"` when asked.

**B3. `results/` is never created for the analysis files** - `checker.py:32,428,433,437`
The constructor creates only `output_path.parent`, `screenshots` and `logs`. `generate_analysis` writes to the literal path `results/...`. With `--output out/run1.json` (or any path outside `results/`) and no existing `results/`, the first save succeeds and `generate_analysis` raises `FileNotFoundError` at line 429, killing the run after one pincode. Even with the default output the directory only exists as a side effect of `output_path.parent`.
Fix: `self.results_dir = self.output_path.parent`, create it, and write all derived files there.

**B4. Non-atomic result writes can destroy resume state** - `checker.py:346-347,355-359`, `checker.py:52-59`
`open(self.output_path, "w")` truncates the file before `json.dump` writes. Ctrl+C, a kill, or a full disk during the write leaves a truncated `results.json`. On the next `--resume` the load fails inside the broad `except` (line 58), only a warning is logged, `self.results` is empty, and the very next save overwrites the file, losing every earlier result. The CSV and the summary/list files have the same problem.
Fix: write to a temp file in the same directory and `os.replace`.
```python
def _atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
```
On a load failure under `--resume`, abort (or move the bad file to `.corrupt`) instead of continuing with empty state.

**B5. CAPTCHA test matches any title containing "bot"** - `checker.py:332`
`"bot" in title` is a substring test on the lowercased page title. Product titles with "both", "bottle", "robot", "abbott", "botanical" and similar match (`'bot' in 'both'` is `True`). The check runs at `checker.py:168` before every attempt, so for such a product every pincode is recorded as `CAPTCHA` without ever testing it.
Fix: match specific titles/markers, for example `"robot check"`, `"sorry! something went wrong"`, `form[action*='validateCaptcha']`, `#captchacharacters`, and keep the `amazon sign in` check.

**B6. Resume treats CAPTCHA and UNKNOWN as finished** - `checker.py:55,110`
Load (line 55) drops only `ERROR`; the skip test (line 110) then skips `DELIVERABLE`, `NOT_DELIVERABLE`, `UNKNOWN` and `CAPTCHA`. A run that hit a CAPTCHA wall (or B5) records the remaining pincodes as `CAPTCHA`, and `--resume` will never retry them. README section 8 says only "successfully checked" pincodes are skipped, and section 13 tells the user to rerun after solving a CAPTCHA, which silently does nothing for those pincodes.
Fix: skip only `DELIVERABLE` and `NOT_DELIVERABLE` by default; add `--retry-unknown` for UNKNOWN. Drop `CAPTCHA` and `ERROR` when loading.

**B7. `--max-tests` with `--resume` never advances** - `cli.py:83-84`, `checker.py:108-114`
The list is sliced to the first N entries before the checker removes already-tested pincodes. README sections 7 and 15 recommend `--max-tests` to "chunk your runs" together with `--resume`. After the first chunk, the next run takes the same first N, skips them all as done, and finishes having tested nothing.
Fix: apply the limit in the checker after resume filtering (count only newly tested pincodes), or filter the already-done pincodes in `cli.py` before slicing.

**B8. Results mix across ASINs** - `checker.py:50-56,129,341-347`, `README.md` section 14
Results are keyed by pincode only and the loader never compares `data["asin"]` to `self.asin`. Re-running with another ASIN and the default `--output` (README section 14 shows exactly this) with `--resume` skips every pincode tested for the previous product; without `--resume` it overwrites the previous product's results (see B9). Screenshots are also named only by pincode (line 126), so they overwrite across ASINs.
Fix: include the ASIN in the default output name (`results/<asin>/results.json`), and refuse to resume when the stored ASIN differs.

### Medium

**B9. Non-resume run silently overwrites prior results** - `checker.py:146,346`
Without `--resume`, the first save replaces `results/results.json` and `.csv` with one row. Combined with B4's lack of backups, a forgotten `--resume` deletes days of data. Fix: refuse to overwrite a non-empty output unless `--force` is given, or write to a timestamped file.

**B10. "Currently unavailable" is reported as NOT_DELIVERABLE** - `checker.py:310-311`
A product that is out of stock everywhere gets `NOT_DELIVERABLE` for every pincode, which answers a different question (stock vs serviceability). Fix: add a distinct `OUT_OF_STOCK` status and keep `NOT_DELIVERABLE` for the "cannot be shipped to your location" family.

**B11. DELIVERABLE is inferred from the Add to Cart button alone** - `checker.py:313-318`
The branch at 313-315 and the branch at 317-318 both require `#add-to-cart-button`, so the phrase check (`free delivery`, `delivery by`, `deliver to`, `arrives:`) has no effect and the README's "scoring logic" (section 11) does not exist. Add to Cart can be present for pincodes where the buy box offers only a different seller or an unconfirmed delivery estimate, so this can be a false positive. The negative-phrase list is also English only and misses variants such as "not available for delivery to your location" (Unverified: capture real not-serviceable pages and check which wording appears). Also, `.a-color-error` (line 286) collects any red text on the page, so unrelated warnings can trip the negative phrases.
Fix: require a positive delivery-date/message element for DELIVERABLE and treat "button only" as `UNKNOWN` (or a low-confidence `DELIVERABLE`). Scope selectors to `#desktop_buybox`/`#deliveryBlockMessage`. Record which rule fired in a `rule` field.

**B12. Retry path never returns to the product page** - `checker.py:179-182`, `checker.py:186-247`
Retries call `page.reload()`. If the first attempt left the page on a CAPTCHA, error or sign-in URL, the reload stays there and all retries fail the same way. Fix: `page.goto(self.url, ...)` on retry instead of `reload`, and re-check the bot challenge afterwards.

**B13. `--retries 0` crashes** - `checker.py:166-184`, `checker.py:120`
With `retries=0` the `for` loop body never runs, the function falls off the end and returns `None`; the caller's 4-way unpack raises `TypeError`. Same if `max_retries` is 0 in config. Fix: `max(1, retries)` in the constructor and `argparse` validation.

**B14. Permanent errors are retried; real "not serviceable" may be hidden as ERROR** - `checker.py:224-226,172-173`
"Invalid pincode entered" (line 226) returns `ERROR`, which the retry wrapper turns into an exception and retries three times with a 5 s sleep and reload each time. `ERROR` rows are also dropped on resume (line 55), so they are retried every run. If Amazon shows the "valid pincode" error for pincodes it does not serve (Unverified: enter a known-unserved pincode manually and read `#GLUXZipError`), real non-serviceable pincodes would be mislabelled. Fix: return a distinct `INVALID_PINCODE` status that is not retried, and validate pincodes (`^[1-9][0-9]{5}$`) in `cli.py`.

**B15. Ctrl+C and exceptions skip cleanup** - `checker.py:65-151`
`context.close()` is only on the normal path (line 150). A `KeyboardInterrupt`, or any exception from `page.screenshot` (line 127) or `generate_analysis`, leaves Chromium running and the `profile/` lock (`SingletonLock`) held, so the next run can fail to launch. Fix: wrap the loop in `try/finally`, catch `KeyboardInterrupt` to save and exit cleanly, and wrap the screenshot in its own try/except.

**B16. Tier is a district-size proxy, not a city size** - `prioritize_dataset.py:31,47-55`, `data/search_priority.json`
The "city" is the CSV `City` column, falling back to the district; `search_priority.json` lists Vellore as tier 1 next to Chennai and Bengaluru. Tier comes from the count of post offices, which measures postal fragmentation, so the "representative first, then expand where deliverable" ordering is weaker than it looks. Fix: tier by population or by an explicit metro list (see F5).

### Low

**B17. Bare `except:` blocks swallow everything, including `KeyboardInterrupt`** - `checker.py:97,181,205,234`. Use `except Exception` and log at debug level.

**B18. Comment disagrees with code** - `prioritize_dataset.py:67-68` says "Tier 1 rep = 1000"; the formula gives 900.

**B19. `completion_percentage` is hard-coded to 100.0 and `LOGIN_REQUIRED` is never set** - `checker.py:403-404`. The field is misleading; compute it from the queue size or remove it.

**B20. `--headless` flag does nothing and `--region` is ignored in adaptive mode** - `cli.py:14,90-92,21`. Make `--headed/--headless` a single `BooleanOptionalAction`.

**B21. `snippet` for non-"cannot be shipped" matches** - `checker.py:307-308`. The evidence always searches for `"cannot be shipped"`; when the match came from "not deliverable" or "does not ship" it falls back to the first 100 characters. Search for the phrase that actually matched.

**B22. `input()` crashes without a TTY** - `checker.py:87`. In headed mode launched from a service or CI it raises `EOFError`. Catch it and exit.

**B23. `fetch_pincodes.py` does not match its consumers** - `fetch_pincodes.py:6-12,18,26-32`, `prepare_dataset.py:6,23-27,72`
It tries three different CSV sources but `prepare_dataset.py` requires the columns `PostOfficeName, Pincode, DistrictsName, City, State`; if the first URL fails and another has a different schema, the data step breaks later with empty output. `validation_report.json` hard-codes a fourth source (`kishorek/India-Codes`) that is not in the fetch list. `urlopen` has no timeout, `data/raw/` is not created, and a failed download that leaves the old file prints stale headers. Fix: one pinned source with a checksum, a schema check, a timeout, and write via a temp file.

**B24. Scripts run on import and only work from the repo root** - all of `fetch_pincodes.py`, `prepare_dataset.py`, `prioritize_dataset.py`, `inspect_amazon.py`, plus relative paths in `checker.py:22,33-35,428` and `cli.py:39`. Importing any of them triggers work, and running from another directory breaks config, data and log paths. Use `Path(__file__).parent` and `if __name__ == "__main__"`.

**B25. Shell scripts are fragile** - `run_adaptive.sh:2`, `run_all.sh:2`
`source venv/bin/activate` is relative to the current directory and fails (and the script carries on) when run elsewhere or when the venv is named `.venv`. There is no `set -euo pipefail`, so "Done!" prints after a failure, and the ASIN is hard-coded. Fix: `cd "$(dirname "$0")"`, `set -euo pipefail`, take the ASIN as `$1`.

**B26. README and config disagree with the code**
- README section 14 says to change the ASIN by editing `config.json`; the code never reads an ASIN or `base_url` from config (`config.json:2` is unused).
- README section 11 describes scoring that does not exist (see B11).
- README section 1 says CSV and JSON; the extra `results/*_summary.json`, `deliverable_pincodes.txt` and `not_deliverable_pincodes.txt` files are not documented in section 10.
- README never mentions adaptive mode, `--strategy`, `--show-queue`, `--region`, or the data preparation scripts.
- README section 16 (see H6) overstates what AGPL requires.

## 3. Robustness improvements

**R1. Backoff and CAPTCHA handling.** On `CAPTCHA`, the loop (checker.py:169, 120-148) immediately moves to the next pincode and keeps hammering. Add a consecutive-block counter: after 2-3 blocks, pause with exponential backoff and jitter (for example 5, 10, 20, 40 minutes), and abort cleanly after N pauses with a clear "blocked, resume later" message. Do not record the interrupted pincodes as results (B6).

**R2. Replace fixed sleeps with waits.** `time.sleep(2)` after Apply (line 222), the 5x1 s polling loop (229-233) and `time.sleep(2)` after reload (238) cost about 4-9 s per pincode and are still racy. Use `page.wait_for_function` on the location slot text containing the pincode, and `wait_for_selector` on `#availability`/`#deliveryBlockMessage` after reload.

**R3. Handle the confirm step and popups.** After Apply, Amazon can show a confirmation dialog with a "Continue"/"Done" button (`#GLUXConfirmClose`, `.a-popover-footer button`). The code relies on the reload to hide it. Handle the button explicitly and dismiss cookie/location popups before reading. Unverified: confirm with `--headed --debug` on a real run.

**R4. Per-attempt timeouts and navigation guards.** `page.reload` at line 237 uses the default 30 s and ignores `page_timeout` from config. Set `context.set_default_timeout(...)` and `set_default_navigation_timeout(...)` from config once.

**R5. Config validation.** `config.json` is read with no schema (`checker.py:22-29`); a typo silently uses defaults and a malformed file crashes with a traceback. Validate keys and types (dataclass or pydantic), reject unknown keys, and print the effective config at start.

**R6. Randomised delay.** A fixed 2.0 s cadence (line 148) is easy to fingerprint. Use `delay * uniform(0.7, 1.5)`, and let the delay grow after soft failures.

**R7. Guard against single-instance conflicts.** A persistent profile can only be opened by one Chromium. Add a lock file with a clear error message, or allow `--profile-dir` so parallel workers each get their own profile.

**R8. Page-markup drift detection.** Selectors (`#GLUXZipUpdateInput`, `#nav-global-location-slot`, `#add-to-cart-button`) are hard-coded in methods. Move them to one constants block (or config), and when N consecutive results are `UNKNOWN`/`ERROR` with missing key elements, stop and report "markup changed" instead of filling the file with garbage. Save the HTML of failing pages for debugging.

**R9. Log rotation and file handler duplication.** `logging.basicConfig` in the constructor (checker.py:39) adds handlers on every instantiation and the log file grows without bound. Configure logging once in `cli.py` and use `RotatingFileHandler`.

## 4. Performance and optimisation

**P1. Full rewrite of derived files after every pincode.** `save_results` + `generate_analysis` (checker.py:146-147) rewrite the JSON, the CSV, one `results/<region>_summary.json` per region, plus two lists. The adaptive data has 286 cities, so about 290 files and O(n) rows each are rewritten per pincode: roughly 2913 x 290 file writes per scan, and the work grows quadratically with the results count. Fix: append each result as one line to a JSONL journal (O(1), crash safe), write snapshots/summaries every N pincodes and at exit.

**P2. Region index.** `generate_analysis` regroups all results each call. Keep running counters per region, update them on each result.

**P3. Queue operations.** `self.queue.pop(0)` (line 104) and the full rebuild in `promote_city_in_queue` (153-163) are O(n) per call. Fine at 2913 items, but use `collections.deque` plus a `dict[city] -> deque` of pending items so promotion is O(k).

**P4. Memory and listing.** The whole prioritised JSON (703 KB) and every result is held in memory; adequate for India's ~19k pincodes, but for the full list stream the input with a generator and keep only a set of done pincodes in memory.

**P5. Skip pincodes before the browser starts.** On resume, filter the queue in `cli.py` before launching Chromium and log the count, rather than iterating and logging a line for each skipped item (checker.py:108-114).

**P6. Avoid reloading the whole product page per pincode.** A reload plus 4-9 s of sleeps dominates runtime. Options in order of effort: (a) condition-based waits (R2); (b) read the delivery text from the AJAX update without a full reload if the DOM-update race can be proven safe (README section 12 says it was avoided for stale-state reasons); (c) use an HTTP-level approach (F2).

**P7. Concurrency.** The design is strictly serial. With separate contexts/profiles and a shared rate limiter, 2-3 workers would give a near-linear speed-up, but this raises block risk. Do it only after R1, R7 and P1 exist (see F3).

**P8. Reduce locator round trips.** `analyze_delivery_state` issues a `count()` plus `text_content()` for each field (lines 260-277) and loops `locs.nth(i).text_content()` per element (293-296), each a separate browser call. Use one `page.evaluate` that returns all needed texts, which cuts per-pincode calls from about 30 to 1.

## 5. Code quality and structure

**Q1. Split `checker.py`.** One 439-line class does browser setup, navigation, parsing, state, persistence, analysis and logging. Suggested modules: `browser.py` (session), `classifier.py` (pure function `classify(texts) -> Result`), `store.py` (results + resume), `report.py` (summaries), `cli.py`.

**Q2. Make the classifier a pure function.** Pass the extracted texts in and get a status, rule name and evidence out. This makes B10/B11 testable with saved HTML fixtures.

**Q3. Use an enum and dataclasses.** Status strings are repeated in `checker.py:110,363-368,397-402,417-425`. Use `class Status(str, Enum)` and `@dataclass Result`. Add type hints (the constructor takes 9 untyped positionals; use keyword-only arguments or a config object).

**Q4. Queue items are loose tuples.** `(pincode, city, meta)` with `meta` merged into the result via `**meta` (checker.py:129) lets stray fields (`status: "PENDING"`) leak and be overwritten. Use a `PincodeTask` dataclass.

**Q5. Shared data-prep logic.** The TN/Bengaluru filter is duplicated in `prepare_dataset.py:36-53` and `prioritize_dataset.py:24-25`. Put it in one module with one function and one set of tests. `prepare_dataset.py` writes the TN/BLR/target text files; `prioritize_dataset.py` re-reads the same CSV.

**Q6. Duplicated data files.** `pincodes.txt` and `data/smoke_test.txt` are identical; `target_pincodes.txt` equals `prioritized_pincodes.txt` as a set; `data/raw/IN.csv` is referenced nowhere in the code. Remove or generate on demand.

**Q7. Logging and output.** Mix of `print` (cli.py, `print_summary`) and `logging`. Use logging everywhere, plus a `--quiet` flag and a progress bar with ETA (`tqdm` or a simple counter).

**Q8. CLI ergonomics.** Use argparse subcommands: `check`, `prepare-data`, `show-queue`, `inspect`. Validate mutually exclusive options (`add_mutually_exclusive_group` for `--asin`/`--url`, `--pincode`/`--pincodes`). Accept an ASIN extracted from a URL so both give consistent output names. Fail early with exit code 2 and a usage message instead of `print` + `sys.exit(1)`.

**Q9. Output format.** The CSV omits `tier`, `state`, `district` that the JSON has (checker.py:354-356). Write the same columns to both, add `asin`, `rule`, `confidence`.

**Q10. `inspect_amazon.py` is a one-off probe** with a hard-coded ASIN and a fixed `sleep(3)`. Move it to `tools/` and parameterise, or delete it once R8 covers diagnostics.

**Q11. Unused imports/names.** `Error` imported (checker.py:8), `TimeoutError` shadows the builtin (use `PlaywrightTimeoutError`), `city_district` unused (prioritize_dataset.py:11,36), `sys`/`Path` fine.

## 6. Testing, CI and project hygiene

**H1. No tests.** Add `tests/` with pytest:
- classifier tests from saved HTML snippets (deliverable, cannot-be-shipped, out-of-stock, captcha page, product title containing "both");
- `cli` argument tests (B1, B7, B13);
- store tests for atomic write, resume filtering and ASIN mismatch;
- data-prep tests on a 20-row CSV fixture.
Use Playwright's `page.set_content()` with static HTML so no network is needed. The pure functions can be tested offline today.

**H2. CI.** Add `.github/workflows/ci.yml`: install, `ruff check`, `ruff format --check`, `mypy`, `pytest` on Python 3.9-3.12. No network tests in CI; add an opt-in `live` marker for manual runs.

**H3. Dependencies and packaging.** `requirements.txt` pins only `playwright==1.49.1`. Add `pyproject.toml` with the project metadata, a console script `amazon-pincode-checker = cli:main` (after moving code into a package), a `dev` extra (pytest, ruff, mypy), and either a lock file (`pip-compile`/`uv lock`) or hashes. README says Python 3.8+; verify (the code works on 3.8 syntax, but 1.49 Playwright supports 3.9+; set `requires-python` accordingly).

**H4. Large and derived data in git.** Committed: `data/raw/pincodes.csv` (2.3 MB), `data/raw/IN.csv` (537 KB, unused), `data/prioritized_pincodes.json` (703 KB), three TXT lists and `search_priority.json`, all regenerable by the scripts. Keep only the small seed files, add `data/raw/` and generated outputs to `.gitignore`, and let `prepare-data` fetch and build them. If the raw source must stay, record its licence and URL next to it. `validation_report.json` embeds a timestamp, which makes every regeneration a noisy diff.

**H5. `.gitignore` gaps.** Missing: `.venv/`, `.env`, `*.egg-info/`, `build/`, `dist/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.coverage`, `htmlcov/` and `*.corrupt`. Note `profile/` is correctly ignored; keep it, since it holds Amazon session cookies.

**H6. Licence text.** README section 16 says forks "must retain explicit attribution to the original author" and that relicensing "is strictly prohibited". AGPL-3.0 requires preserving copyright and licence notices, not named attribution, and the copyright holder is free to relicense their own code. If extra terms are wanted, state them as Section 7 additional terms; otherwise reword to "Licensed under AGPL-3.0; see LICENSE". Add SPDX headers (`# SPDX-License-Identifier: AGPL-3.0-only`) to source files.

**H7. Terms-of-service and responsible use.** The tool uses `--disable-blink-features=AutomationControlled` (checker.py:73) to hide automation and a persistent logged-in profile. Add a README section on Amazon's conditions of use, rate limits, and a recommendation to use a non-primary account. Consider whether the stealth flag is needed at all.

**H8. Data provenance.** `validation_report.json` lists a source URL that the fetch script does not use. Record the actual source and download date, and keep the processing report in `results/` or `data/generated/`.

**H9. Contributor basics.** Add `CHANGELOG.md`, `CONTRIBUTING.md` (how to run tests, how to capture a fixture), and a short architecture section in the README.

## 7. Feature ideas and alternative approaches

**F1. Journal-based state store (replaces JSON/CSV rewrites).** Append-only `results.jsonl` (or SQLite with `INSERT OR REPLACE`) as the source of truth; JSON/CSV are exported on demand. This fixes B4, B8, B9 and P1 in one change. SQLite also gives free querying and an ASIN column.

**F2. API-level check instead of full browser (investigate first).** The location widget posts to Amazon's address-change endpoint and the product page loads delivery text from AJAX endpoints. A `requests`/`httpx` session that copies cookies from the persistent profile and calls those endpoints could be 10-50x faster. Risks: endpoints are undocumented and change, and tokens (CSRF, session) are needed. Keep the browser path as fallback. Unverified: capture the network calls with DevTools or Playwright `page.on("request")` to see whether the delivery state is available in a JSON response.

**F3. Worker pool with shared limiter.** N Playwright workers, each with its own profile and a token-bucket rate limiter, pulling from one queue (P7). Only after R1 and R7.

**F4. Statistical sampling in adaptive mode.** Today "adaptive" only reorders (checker.py:153-163); it never prunes. Add real pruning: if the representative and K sampled pincodes of a city are all `NOT_DELIVERABLE`, mark the rest `INFERRED_NOT_DELIVERABLE` and skip them; if all are deliverable, sample the rest rather than testing all. Keep a `--exhaustive` switch. This cuts a scan by 50-90% for sparse coverage.

**F5. Better prioritisation data.** Replace the post-office-count tier with real population or with the PIN first-three-digits (sorting-district) grouping; the PIN prefix is a more reliable "service area" key than a free-text city name. Use `data/raw/IN.csv` (GeoNames, has lat/long) if geographic clustering is wanted, otherwise delete it.

**F6. Multi-state / all-India coverage.** The state filter is hard-coded to Tamil Nadu and Bengaluru in both data scripts. Make it `--states "Tamil Nadu,Karnataka"` or `--all-india`, with the first three digits as the grouping unit.

**F7. Multiple ASINs in one run.** Accept `--asin-file`, share the browser session, and output one matrix (pincode x ASIN).

**F8. Reporting.** A `report` command that renders the results as a single HTML or Markdown file (coverage by state/city, deliverable map, failed list), and a `diff` command comparing two runs to detect serviceability changes over time.

**F9. Retry-failures command.** `--only-status ERROR,UNKNOWN,CAPTCHA` to rerun a subset without editing files (replaces the implicit behaviour in B6).

**F10. Notifications and scheduling.** Optional webhook/email when blocked or finished, and a documented cron/systemd timer for periodic re-checks.

**F11. Confidence and evidence capture.** Store the matched rule, the raw delivery text and (optionally) the compressed page HTML for `UNKNOWN`/`ERROR` rows so classifier fixes can be validated without re-scanning.

## 8. Suggested roadmap

### Phase 1 - quick fixes (effort S, about one day)
- [ ] B1 strategy inference and argument conflicts (S)
- [ ] B2 configurable browser path (S)
- [ ] B3 create/derive results directory (S)
- [ ] B4 atomic writes, abort on corrupt resume file (S)
- [ ] B5 CAPTCHA title test (S)
- [ ] B6 resume skip rules (S)
- [ ] B7 `--max-tests` after resume filter (S)
- [ ] B13 `--retries` lower bound (S)
- [ ] B15 `try/finally` cleanup (S)
- [ ] B17, B18, B20, B21, B22 small cleanups (S)
- [ ] B25 shell script hardening (S)
- [ ] B26 README corrections, H6 licence wording, H5 `.gitignore` (S)

### Phase 2 - correctness and robustness (effort M, about one week)
- [ ] B8, B9 ASIN-aware output paths and overwrite guard (M)
- [ ] B10, B11, B12, B14 classifier and retry logic with new statuses (M)
- [ ] R1 CAPTCHA backoff and abort, R6 jitter (M)
- [ ] R2, R3, R4 condition-based waits and popup handling (M)
- [ ] R5 config validation, R9 logging setup (S)
- [ ] P1, P2, P5 journal store and cheaper summaries, early filtering (M)
- [ ] P8 single-call extraction (S)
- [ ] B19, B23, B24 data-script fixes and `__main__` guards (M)
- [ ] Q2, Q3, Q4 pure classifier, enum, dataclasses (M)
- [ ] H1 tests with HTML fixtures, H2 CI, H3 `pyproject.toml` (M)

### Phase 3 - structure and features (effort L, multi-week)
- [ ] Q1, Q5, Q8, Q9 module split, shared data-prep module, subcommand CLI (L)
- [ ] F1 SQLite or JSONL store with exports (M)
- [ ] F4 real adaptive pruning, B16, F5 better prioritisation (M)
- [ ] F6, F7 multi-state and multi-ASIN support (M)
- [ ] F2 HTTP-level checker investigation (L, research first)
- [ ] F3, P3, P7, R7 worker pool with shared rate limiter (L)
- [ ] F8-F11 reporting, retry-failures, notifications, evidence capture (M)
- [ ] H4, H8 data hygiene: remove generated and unused data from git, record provenance (S-M)
- [ ] R8 markup-drift detection (M)
- [ ] H7, H9 usage policy, changelog, contributing guide (S)
