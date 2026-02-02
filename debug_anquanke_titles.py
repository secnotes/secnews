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

container = soup.select('#app > div.g-body.g-w > div.g-main > div._89 > div:nth-child(2) > ul')

if container:
    items = container[0].find_all('li', class_='item')
    print(f"Found {len(items)} items")

    for i, item in enumerate(items[:3]):
        print(f"\n--- Item {i+1} ---")
        print("Full HTML:")
        print(item.prettify()[:1000])

        # Find the title link (inside .title div)
        title_div = item.find('div', class_='title')
        if title_div:
            title_link = title_div.find('a')
            if title_link:
                print(f"Title link text: '{title_link.text.strip()}'")
                print(f"Title link href: {title_link.get('href')}")

        # Find main item cover link
        item_cover = item.find('a', class_='item-cover')
        if item_cover:
            print(f"Cover link href: {item_cover.get('href')}")

        # Find description
        desc_p = item.find('p', class_='desc')
        if desc_p:
            print(f"Description: '{desc_p.text.strip()}'")