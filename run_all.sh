#!/bin/bash
source venv/bin/activate
echo "Running Tamil Nadu..."
python cli.py --asin B0B5V5VHB6 --pincodes data/tamil_nadu_pincodes.txt --resume
echo "Running Bengaluru..."
python cli.py --asin B0B5V5VHB6 --pincodes data/bengaluru_pincodes.txt --resume
echo "Done!"
