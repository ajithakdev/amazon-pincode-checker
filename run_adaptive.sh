#!/bin/bash
source venv/bin/activate
echo "Starting adaptive scan..."
python cli.py --asin B0B5V5VHB6 --strategy adaptive --resume
echo "Done!"
