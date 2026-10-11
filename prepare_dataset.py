import csv
import sys
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
raw_file = BASE_DIR / "data" / "raw" / "pincodes.csv"
source_file = BASE_DIR / "data" / "raw" / "pincodes.source"
tn_out = BASE_DIR / "data" / "tamil_nadu_pincodes.txt"
blr_out = BASE_DIR / "data" / "bengaluru_pincodes.txt"
target_out = BASE_DIR / "data" / "target_pincodes.txt"
report_out = BASE_DIR / "data" / "validation_report.json"

def write_list(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        for p in data:
            f.write(f"{p}\n")


def main():
    if not raw_file.exists():
        print(f"Error: {raw_file} not found. Run fetch_pincodes.py first.", file=sys.stderr)
        return 1

    source_url = source_file.read_text(encoding="utf-8").strip() if source_file.exists() else "unknown"

    tn_pincodes = set()
    blr_pincodes = set()
    malformed = 0
    duplicates = 0
    unknown = 0
    total_processed = 0

    with open(raw_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_processed += 1
            po_name = row.get("PostOfficeName", "")
            pincode = row.get("Pincode", "").strip()
            district = row.get("DistrictsName", "").strip()
            city = row.get("City", "").strip()
            state = row.get("State", "").strip()
        
            if not pincode or len(pincode) != 6 or not pincode.isdigit():
                malformed += 1
                continue
            
            if not state:
                unknown += 1
            
            # Tamil Nadu logic
            if state.lower() == "tamil nadu":
                if pincode in tn_pincodes:
                    duplicates += 1
                else:
                    tn_pincodes.add(pincode)
                
            # Bengaluru City logic
            # To strictly target Bengaluru City and not Rural/Metro, we filter for "Karnataka", 
            # district/city containing "Bangalore" or "Bengaluru", AND pincode starting with '560'
            # which is the standard India Post classification for Bangalore city post offices.
            if state.lower() == "karnataka":
                if "bangalore" in city.lower() or "bengaluru" in city.lower() or "bangalore" in district.lower():
                    if pincode.startswith("560"):
                        if pincode in blr_pincodes:
                            duplicates += 1
                        else:
                            blr_pincodes.add(pincode)

    # Sort them for consistency
    tn_list = sorted(list(tn_pincodes))
    blr_list = sorted(list(blr_pincodes))
    target_list = sorted(list(tn_pincodes.union(blr_pincodes)))

    # Write output
    write_list(tn_out, tn_list)
    write_list(blr_out, blr_list)
    write_list(target_out, target_list)

    # Generate report
    report = {
        "source_url": source_url,
        "timestamp": datetime.now().isoformat(),
        "validation": {
            "total_processed_records": total_processed,
            "malformed_pincodes": malformed,
            "missing_state_records": unknown,
            "duplicates_skipped": duplicates
        },
        "results": {
            "tamil_nadu_count": len(tn_list),
            "bengaluru_count": len(blr_list),
            "combined_unique_count": len(target_list)
        },
        "definition_used_for_bengaluru_city": "State='Karnataka', City or District contains 'Bangalore' or 'Bengaluru', AND Pincode starts with '560'. (560 prefix strictly identifies Bangalore City post offices, filtering out Bangalore Rural and Metro areas like 562xxx)."
    }

    with open(report_out, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    print("Validation Report:")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
