#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup

# Session with headers to mimic a real browser
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

try:
    response = session.get("https://www.freebuf.com/", timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, 'html.parser')

    print("Looking for div.article-list...")
    article_lists = soup.find_all('div', class_='article-list')

    print(f"Found {len(article_lists)} div.article-list elements")

    for i, article_list in enumerate(article_lists):
        print(f"\n--- Article List {i+1} ---")

        # Look for article-item inside article-list
        article_items = article_list.find_all('div', class_='article-item')
        print(f"Found {len(article_items)} div.article-item elements in this list")

        for j, item in enumerate(article_items[:3]):  # Show first 3 items
            print(f"\n  Article Item {j+1}:")
            print(f"    HTML snippet: {item.prettify()[:500]}...")

            # Find link in the item
            link_tag = item.find('a')
            if link_tag:
                print(f"    Link text: '{link_tag.text.strip()[:100]}...'")
                print(f"    Link href: {link_tag.get('href', 'N/A')}")

            # Look for descriptions
            desc_elem = item.find('p', class_='desc') or item.find('div', class_='desc') or \
                      item.find('p', class_='description') or item.find('div', class_='description') or \
                      item.find('div', class_='summary')

            if desc_elem:
                print(f"    Description: '{desc_elem.get_text(strip=True)[:100]}...'")

            # Look for time/date
            time_elem = item.find('time') or item.find('span', class_='time') or \
                       item.find('span', class_='date') or item.find('div', class_='time')

            if time_elem:
                print(f"    Time/Date: '{time_elem.get_text(strip=True)}'")

    # If no article-list found, look for other common selectors
    if not article_lists:
        print("\nNo div.article-list found. Looking for alternative selectors...")

        # Try other common selectors
        alternative_selectors = [
            'div.feed-item',
            'div.news-item',
            'div.list-item',
            'article',
            '.article-item'  # class-only selector
        ]

        for selector in alternative_selectors:
            elements = soup.select(selector)
            if elements:
                print(f"Found {len(elements)} elements with selector '{selector}'")
                break

except Exception as e:
    print(f"Error fetching FreeBuf: {str(e)}")