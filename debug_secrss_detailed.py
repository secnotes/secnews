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

print("Looking for articles with common classes...")
possible_selectors = [
    'div.item',  # common article container
    'div.article-item',
    'li.article',
    'div.article-item',
    'div.media',
    'div.list-item',
    'div.post-item',
    'div.title',  # since we know "article-list-title" is just the section title
]

for selector in possible_selectors:
    elements = soup.select(selector)
    if elements:
        print(f"\nFound {len(elements)} with selector: {selector}")
        for i, elem in enumerate(elements[:2]):
            print(f"  Element {i+1}: {elem.get_text(strip=True)[:100]}...")

# Let's also look for links that might be article titles
all_links = soup.find_all('a', href=True)
article_related_links = []
for link in all_links:
    href = link.get('href', '')
    text = link.get_text(strip=True)
    # Look for links that might be articles
    if ('article' in href or 'post' in href or 'news' in href or len(text) > 5) and \
       ('/article' in href or '/post' in href or '/news' in href or '/archives' in href):
        article_related_links.append((href, text))

print(f"\nFound {len(article_related_links)} potential article links:")
for i, (href, text) in enumerate(article_related_links[:10]):
    print(f"  {i+1}. {text[:50]} -> {href}")

# Let's look for the section that follows "article-list-title"
article_list_title = soup.find('div', class_='article-list-title')
if article_list_title:
    print(f"\nElements following 'article-list-title':")
    for sibling in article_list_title.next_siblings:
        if sibling.name and sibling.get_text(strip=True):
            print(f"  Sibling tag: {sibling.name}, content: {sibling.get_text(strip=True)[:100]}...")
            # Look for links in this sibling
            links = sibling.find_all('a', href=True)
            for link in links[:3]:
                print(f"    Link: {link.get_text(strip=True)[:50]} -> {link.get('href')}")