#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup

# Session with headers to mimic a real browser
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

response = session.get("https://sec.today/pulses/", timeout=10)
soup = BeautifulSoup(response.content, 'html.parser')
cards = soup.find_all('div', class_='card my-2')

print(f"Found {len(cards)} cards")

for i, card in enumerate(cards[:3]):  # Check first 3 cards
    print(f"\n--- Card {i+1} ---")
    print("All HTML:")
    print(card.prettify()[:1000])  # First 1000 chars

    print("\nSmall tags (potential date locations):")
    small_tags = card.find_all('small', class_='text-muted')
    for j, tag in enumerate(small_tags):
        print(f"  Small tag {j+1}: '{tag.get_text(strip=True)}'")

    print("\nAll text in card:")
    print(card.get_text(strip=True)[:300])