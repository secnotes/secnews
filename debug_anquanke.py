#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import re

# Session with headers to mimic a real browser
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

response = session.get("https://www.anquanke.com/", timeout=10)
soup = BeautifulSoup(response.content, 'html.parser')

print("Looking for the specified selector...")
container = soup.select('#app > div.g-body.g-w > div.g-main > div._89 > div:nth-child(2) > ul')

print(f"Container found: {len(container) > 0}")
if container:
    print("First 1000 chars of container:")
    print(container[0].prettify()[:1000])

    # Check for div items with class "item"
    items = container[0].find_all('div', class_='item')
    print(f"\nFound {len(items)} div items with class 'item'")

    lis = container[0].find_all('li')
    print(f"Found {len(lis)} li elements")

    # If no items found with class "item", let's see what elements are there
    all_divs = container[0].find_all('div')
    print(f"Total divs in container: {len(all_divs)}")

    for i, div in enumerate(all_divs[:5]):
        class_names = div.get('class', [])
        print(f"Div {i} classes: {class_names}")

else:
    print("Trying to find similar structure in the page...")
    # Let's find any divs with class 'item' on the page
    item_divs = soup.find_all('div', class_='item')
    print(f"Found {len(item_divs)} divs with class 'item' anywhere on page")

    if item_divs:
        for i, div in enumerate(item_divs[:3]):
            print(f"\nItem {i+1}:")
            print(div.prettify()[:500])