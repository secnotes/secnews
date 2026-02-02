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

    print("Checking common article selectors on FreeBuf...")

    # Look for common article selectors
    selectors_to_check = [
        'div[class*="article"]',
        'div[class*="news"]',
        'div[class*="list"]',
        'div[class*="item"]',
        'article',
        '.item',
        '.list-item',
        '.article-item',
        '.news-item',
        '[class*="feed"]',
        '[class*="card"]'
    ]

    for selector in selectors_to_check:
        elements = soup.select(selector)
        if elements:
            print(f"\nFound {len(elements)} elements with selector: {selector}")
            # Show first element's attributes and first few characters of text
            if elements[0].name and elements[0].attrs:
                print(f"  First element tag: {elements[0].name}, attributes: {elements[0].attrs}")

            text_preview = elements[0].get_text(strip=True)[:100]
            print(f"  Text preview: '{text_preview}...'")

            # Look for links in the first element
            link = elements[0].find('a')
            if link:
                print(f"  Link text: '{link.text.strip()[:50]}...'")
                print(f"  Link href: {link.get('href', 'N/A')}")

    # Also check for any divs with article-related classes
    all_divs = soup.find_all('div')
    article_related_classes = []

    for div in all_divs:
        classes = div.get('class', [])
        if any('article' in cls.lower() or 'list' in cls.lower() or 'item' in cls.lower() for cls in classes):
            if div not in article_related_classes:
                article_related_classes.append(div)

    print(f"\nFound {len(article_related_classes)} divs with article/list/item related classes:")
    for i, div in enumerate(article_related_classes[:10]):
        classes = div.get('class', [])
        print(f"  {i+1}. Classes: {classes}, Tag preview: {str(div)[:100]}...")

except Exception as e:
    print(f"Error fetching FreeBuf: {str(e)}")