import csv
import json
from collections import defaultdict
from pathlib import Path

raw_file = Path("data/raw/pincodes.csv")

# We want only Tamil Nadu and Bengaluru (as defined previously)
pincode_data = {}
city_pincodes = defaultdict(set)
city_district = {}

with open(raw_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        pincode = row.get("Pincode", "").strip()
        state = row.get("State", "").strip()
        city = row.get("City", "").strip()
        district = row.get("DistrictsName", "").strip()
        
        if not pincode or len(pincode) != 6 or not pincode.isdigit():
            continue
            
        is_tn = state.lower() == "tamil nadu"
        is_blr = state.lower() == "karnataka" and ("bangalore" in city.lower() or "bengaluru" in city.lower() or "bangalore" in district.lower()) and pincode.startswith("560")
        
        if is_tn or is_blr:
            if pincode in pincode_data:
                continue
                
            norm_city = city.title() if city else district.title()
            if is_blr:
                norm_city = "Bengaluru"
                
            city_pincodes[norm_city].add(pincode)
            city_district[norm_city] = district.title()
            
            pincode_data[pincode] = {
                "pincode": pincode,
                "state": "Tamil Nadu" if is_tn else "Karnataka",
                "city": norm_city,
                "district": district.title()
            }

# Determine tiers based on number of pincodes (larger city = more postal codes)
# Chennai > 100, Coimbatore ~ 40, etc.
def assign_tier(count):
    if count >= 40: return 1
    if count >= 15: return 2
    if count >= 5: return 3
    return 4

city_tiers = {}
for city, pins in city_pincodes.items():
    city_tiers[city] = assign_tier(len(pins))

prioritized = []

# Select representative: we'll pick the lowest numeric pincode for a city as representative, often ending in 001
for city, pins in city_pincodes.items():
    sorted_pins = sorted(list(pins))
    rep = sorted_pins[0]
    
    tier = city_tiers[city]
    
    # Representative priority score (higher is better). 
    # Tier 1 rep = 1000, Tier 2 rep = 900, etc.
    rep_score = 1000 - (tier * 100)
    
    for p in sorted_pins:
        is_rep = (p == rep)
        score = rep_score if is_rep else (500 - (tier * 100))
        reason = f"Representative for Tier {tier} city" if is_rep else f"Additional sample for Tier {tier} city"
        
        prioritized.append({
            "pincode": p,
            "state": pincode_data[p]["state"],
            "city": city,
            "district": pincode_data[p]["district"],
            "tier": tier,
            "priority_score": score,
            "priority_reason": reason,
            "status": "PENDING"
        })

# Sort by priority score descending
prioritized.sort(key=lambda x: x["priority_score"], reverse=True)

with open("data/prioritized_pincodes.json", "w", encoding="utf-8") as f:
    json.dump(prioritized, f, indent=2)

with open("data/prioritized_pincodes.txt", "w", encoding="utf-8") as f:
    for item in prioritized:
        f.write(f"{item['pincode']}\n")

# Save search priority documentation
doc = {
    "tier_logic": "Tier assigned by proxy of population/urban size using the number of postal areas in the city.",
    "tier_1": ">= 40 postal codes",
    "tier_2": "15-39 postal codes",
    "tier_3": "5-14 postal codes",
    "tier_4": "1-4 postal codes",
    "city_tiers": {city: tier for city, tier in sorted(city_tiers.items(), key=lambda item: item[1])}
}
with open("data/search_priority.json", "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2)

print(f"Generated priority queue with {len(prioritized)} pincodes.")
