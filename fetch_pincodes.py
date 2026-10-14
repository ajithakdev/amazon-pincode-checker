import urllib.request
import csv
import sys
from pathlib import Path

urls = [
    "https://raw.githubusercontent.com/dropdevrahul/pincodes-india/master/pincode.csv",
    "https://raw.githubusercontent.com/sjlouji/Indian-Pincode-Dataset/master/Pincode_30052019.csv",
    "https://raw.githubusercontent.com/bilal-webdev/india-postal-pincode-dataset/main/pincode.csv"
]

BASE_DIR = Path(__file__).resolve().parent
out_file = BASE_DIR / "data" / "raw" / "pincodes.csv"
source_file = BASE_DIR / "data" / "raw" / "pincodes.source"
REQUIRED_COLUMNS = {"Pincode", "DistrictsName", "City", "State"}
TIMEOUT = 30


def download(url, tmp_file):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        data = response.read()
    with open(tmp_file, 'wb') as out:
        out.write(data)
    # Schema check so prepare_dataset.py does not fail later on empty output
    with open(tmp_file, 'r', encoding='utf-8', errors='replace') as f:
        headers = next(csv.reader(f), [])
    missing = REQUIRED_COLUMNS - set(h.strip() for h in headers)
    if missing:
        raise ValueError(f"missing columns {sorted(missing)}")


def main():
    out_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = out_file.with_suffix(".csv.tmp")
    success = False

    for url in urls:
        try:
            print(f"Trying {url}...")
            download(url, tmp_file)
            tmp_file.replace(out_file)
            source_file.write_text(url + "\n", encoding="utf-8")
            print(f"Successfully downloaded from {url}")
            success = True
            break
        except Exception as e:
            print(f"Failed: {e}")
            if tmp_file.exists():
                tmp_file.unlink()

    if not success:
        print("Error: all sources failed; existing file (if any) left untouched.", file=sys.stderr)
        return 1

    with open(out_file, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        headers = next(reader)
        print("Headers:", headers)
        row1 = next(reader, None)
        print("Row 1:", row1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
