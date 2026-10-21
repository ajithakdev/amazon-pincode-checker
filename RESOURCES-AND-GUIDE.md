# amazon-pincode-checker: resources and guide

Every link for the Amazon pincode checker, what it is for, and how to run it. Passwords and keys are never written here.

## TL;DR

- Checks whether an Amazon.in product ASIN is deliverable to Indian pincodes using Playwright.
- First run needs headed mode (`--headed`) to solve any initial CAPTCHA or login and cache the session in `profile/`.
- Resuming with `--resume` skips finished pincodes and re-tests failed or ambiguous checks.
- Results and per-region summaries are saved to `results/` in JSON and CSV formats.
- The project repository is at https://github.com/ajithakdev/amazon-pincode-checker.

## Links and what each one is for

### Public

| Link | Use it for |
| --- | --- |
| https://github.com/ajithakdev/amazon-pincode-checker | Source code and documentation |
| https://www.amazon.in | Product and delivery destination site |

### Behind the scenes

| Link | Use it for |
| --- | --- |
| https://raw.githubusercontent.com/dropdevrahul/pincodes-india/master/pincode.csv | Primary raw pincodes dataset |
| https://raw.githubusercontent.com/sjlouji/Indian-Pincode-Dataset/master/Pincode_30052019.csv | Fallback raw pincodes dataset |
| https://raw.githubusercontent.com/bilal-webdev/india-postal-pincode-dataset/main/pincode.csv | Fallback raw pincodes dataset |

## Accounts

| Service | Account | Role |
| --- | --- | --- |
| GitHub | `ajithakdev` | Owner |

## Run and release

| Job | How |
| --- | --- |
| Install virtual environment and dependencies | `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt` |
| Install browser fallback | `playwright install chromium` |
| First-time session setup | `python cli.py --asin B0B5V5VHB6 --pincode 600034 --headed` |
| Run sequential check | `python cli.py --asin B0B5V5VHB6 --pincodes pincodes.txt` |
| Run single pincode | `python cli.py --asin B0B5V5VHB6 --pincode 600034` |
| Resume earlier run | `python cli.py --asin B0B5V5VHB6 --pincodes pincodes.txt --resume` |
| Run parallel workers | `python cli.py --asin B0B5V5VHB6 --pincodes data/tamil_nadu_pincodes.txt --resume --workers 3 --delay 1` |
| Run adaptive mode | `./run_adaptive.sh` |
| Run unit tests | `python3 -m unittest discover tests` |
| View results and summaries | Read `results/results.json`, `results/results.csv`, and `results/*_summary.json` |
| View logs and screenshots | Read `logs/checker.log` and check `screenshots/` |

## When something goes wrong

| Problem | Fix |
| --- | --- |
| Amazon shows CAPTCHA or asks for login | Run with `--headed`, solve the prompt in the window, and press Enter in the terminal |
| Worker stops after consecutive CAPTCHAs | Solve the CAPTCHA in headed mode with `--headed`, then rerun with `--resume` |
| System Chromium or Chrome not found | Run `playwright install chromium` to install the bundled browser |
| Resume fails with ASIN mismatch | Use a separate output path with `--output <path>` for each product |
| Rate limiting from Amazon | Increase `delay_between_requests` in `config.json` or pass `--delay`, and lower `--workers` |
| Pincode rejected as invalid | Amazon rejected the code; it is tagged `INVALID_PINCODE` and skipped on `--resume` |

## More detail

- `README.md`: tool overview, CLI options, classification rules, and troubleshooting
- `AGENTS.md`: code map, request flow, data pipeline, and architecture details
- `config.json`: request delay, retry count, and page timeout settings
- `cli.py`: command line flag parser and execution entry point
- `checker.py`: browser automation, location modal interactions, and classification logic
- `tests/`: unit tests running against fake browser pages
