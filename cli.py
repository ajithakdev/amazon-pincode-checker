import re
import argparse
import sys
import json
from pathlib import Path
from checker import AmazonPincodeChecker

def main():
    parser = argparse.ArgumentParser(description="Amazon.in Pincode Serviceability Checker")
    parser.add_argument("--asin", help="Amazon ASIN to test")
    parser.add_argument("--url", help="Full Amazon product URL to test")
    parser.add_argument("--pincodes", help="File containing list of pincodes (one per line)")
    parser.add_argument("--pincode", help="Single pincode to test")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode (visible)")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode (default)")
    parser.add_argument("--delay", type=float, help="Delay between checks in seconds")
    parser.add_argument("--retries", type=int, help="Max retries for a pincode")
    parser.add_argument("--resume", action="store_true", help="Resume from previous results")
    parser.add_argument("--screenshots", action="store_true", help="Save screenshots of results")
    parser.add_argument("--output", help="Output JSON file path", default="results/results.json")
    parser.add_argument("--max-tests", type=int, help="Maximum number of pincodes to test")
    parser.add_argument("--region", help="Region label for grouping results", default="unknown")
    parser.add_argument("--strategy", choices=["sequential", "adaptive"], help="Search strategy (default: sequential if --pincodes/--pincode is given, else adaptive)")
    parser.add_argument("--show-queue", action="store_true", help="Display the initial prioritized queue and exit")
    parser.add_argument("--workers", type=int, default=1, help="Parallel browser workers, each with its own profile (default: 1)")
    parser.add_argument("--load-images", action="store_true", help="Load images, media and fonts (blocked by default for speed)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.strategy is None:
        args.strategy = "sequential" if (args.pincodes or args.pincode) else "adaptive"

    if not args.asin and not args.url and not args.show_queue:
        print("Error: Must provide either --asin or --url")
        sys.exit(1)

    if not args.pincodes and not args.pincode and args.strategy != "adaptive":
        print("Error: Must provide either --pincodes file or a single --pincode")
        sys.exit(1)

    pincodes_list = []
    
    if args.strategy == "adaptive":
        queue_path = Path("data/prioritized_pincodes.json")
        if not queue_path.exists():
            print("Error: data/prioritized_pincodes.json not found. Run prioritize_dataset.py first.")
            sys.exit(1)
            
        with open(queue_path, "r", encoding="utf-8") as f:
            queue_data = json.load(f)
            
        if args.show_queue:
            print(f"Total prioritized pincodes: {len(queue_data)}")
            print("Top 20 items in queue:")
            for item in queue_data[:20]:
                print(f"Pincode: {item['pincode']} | City: {item['city']} | Tier: {item['tier']} | Score: {item['priority_score']} | Reason: {item['priority_reason']}")
            sys.exit(0)
            
        for item in queue_data:
            pincodes_list.append((item['pincode'], item['city'], item))
            
    else:
        # Sequential
        if args.show_queue:
            print("Show queue only applies to adaptive strategy.")
            sys.exit(0)
            
        if args.pincodes:
            pincodes_path = Path(args.pincodes)
            if not pincodes_path.exists():
                print(f"Error: Pincodes file {args.pincodes} does not exist.")
                sys.exit(1)
            inferred_region = "unknown"
            filename = pincodes_path.name.lower()
            if "tamil_nadu" in filename: inferred_region = "tamil_nadu"
            elif "bengaluru" in filename or "bangalore" in filename: inferred_region = "bengaluru"
            elif "target" in filename: inferred_region = "combined"
                
            region = args.region if args.region != "unknown" else inferred_region
            with open(pincodes_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        pincodes_list.append((line, region, {}))
        elif args.pincode:
            pincodes_list.append((args.pincode.strip(), args.region, {}))

    if not pincodes_list:
        print("Error: No pincodes to test.")
        sys.exit(1)

    headless = True
    if args.headed:
        headless = False

    checker = AmazonPincodeChecker(
        asin=args.asin,
        url=args.url,
        headless=headless,
        delay=args.delay,
        retries=args.retries,
        resume=args.resume,
        screenshots=args.screenshots,
        output_path=args.output,
        debug=args.debug,
        block_resources=not args.load_images
    )

    # Drop malformed pincodes before any browser work
    valid = [item for item in pincodes_list if re.fullmatch(r"[1-9][0-9]{5}", str(item[0]))]
    if len(valid) != len(pincodes_list):
        print(f"Warning: skipping {len(pincodes_list) - len(valid)} malformed pincode(s).")
    if not valid:
        print("Error: No valid pincodes to test.")
        sys.exit(1)

    checker.run(valid, max_tests=args.max_tests, workers=args.workers)

if __name__ == "__main__":
    main()
