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

print("Looking for div class='article-list-title'...")
article_titles = soup.find_all('div', class_='article-list-title')

print(f"Found {len(article_titles)} articles with class 'article-list-title'")

for i, container in enumerate(article_titles[:3]):
    print(f"\n--- Article {i+1} ---")
    print("Full HTML:")
    print(container.prettify()[:1000])

    link_tag = container.find('a')
    if link_tag:
        print(f"Link text: '{link_tag.text.strip()}'")
        print(f"Link href: {link_tag.get('href')}")

    # Look for parent to find description and date
    parent = container.find_parent()
    if parent:
        print(f"Parent tag: {parent.name}, Classes: {parent.get('class', [])}")

        # Look for content/description elements
        content_elem = parent.find('div', class_='content') or parent.find('p', class_='summary') or parent.find('div', class_='description')
        if content_elem:
            print(f"Content/Description: '{content_elem.text.strip()}'")

        # Look for date elements
        date_elem = parent.find('span', class_='date') or parent.find('div', class_='date') or parent.find('time')
        if date_elem:
            print(f"Date element: '{date_elem.text.strip()}'")