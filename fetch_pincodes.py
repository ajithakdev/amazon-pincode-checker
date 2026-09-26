import urllib.request
import csv
import json
from pathlib import Path

urls = [
    "https://raw.githubusercontent.com/dropdevrahul/pincodes-india/master/pincode.csv",
    "https://raw.githubusercontent.com/sjlouji/Indian-Pincode-Dataset/master/Pincode_30052019.csv",
    "https://raw.githubusercontent.com/bilal-webdev/india-postal-pincode-dataset/main/pincode.csv"
]

out_file = Path("data/raw/pincodes.csv")

for url in urls:
    try:
        print(f"Trying {url}...")
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            with open(out_file, 'wb') as out:
                out.write(response.read())
        print(f"Successfully downloaded from {url}")
        break
    except Exception as e:
        print(f"Failed: {e}")

if out_file.exists():
    with open(out_file, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        headers = next(reader)
        print("Headers:", headers)
        row1 = next(reader)
        print("Row 1:", row1)
