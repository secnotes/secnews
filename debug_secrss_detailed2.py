#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup

# Session with headers to mimic a real browser
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

response = session.get("https://www.secrss.com/", timeout=10)
soup = BeautifulSoup(response.content, 'html.parser')

# Find the article list title and its following ul
article_list_title = soup.find('div', class_='article-list-title')
if article_list_title:
    print("'article-list-title' found!")

    # Find the next ul sibling which contains articles
    next_ul = article_list_title.find_next_sibling('ul')
    if next_ul:
        print("Found UL following article-list-title")

        # Get all list items from this UL
        list_items = next_ul.find_all('li')
        print(f"Found {len(list_items)} list items")

        for i, li in enumerate(list_items[:5]):  # Show first 5
            print(f"\n--- Article {i+1} ---")
            print("Full HTML:")
            print(li.prettify()[:1000])

            # Find link in the li
            link = li.find('a')
            if link:
                print(f"Link text: '{link.text.strip()}'")
                print(f"Link href: {link.get('href', 'N/A')}")

            # Find time/date info
            time_elem = li.find('span', class_='time') or li.find('div', class_='time')
            if time_elem:
                print(f"Time element: '{time_elem.text.strip()}'")

            # Find description
            desc_elem = li.find('div', class_='desc') or li.find('p', class_='desc')
            if desc_elem:
                print(f"Description: '{desc_elem.text.strip()}'")