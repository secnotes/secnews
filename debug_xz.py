#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup
import html
import re

# Session with headers to mimic a real browser
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

# First, get the main page to extract CSRF token
response = session.get("https://xz.aliyun.com/news", timeout=15)
soup = BeautifulSoup(response.content, 'html.parser')
csrf_token_meta = soup.find('meta', attrs={'name': '_token'})
csrf_token = csrf_token_meta.get('content') if csrf_token_meta else None

# Prepare headers for the AJAX request
headers = {
    'X-CSRF-TOKEN': csrf_token,
    'X-Requested-With': 'XMLHttpRequest',
    'Referer': 'https://xz.aliyun.com/news',
    'Accept': 'application/json, text/plain, */*',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
}

# Make the AJAX request to get the news list as HTML
ajax_response = session.get("https://xz.aliyun.com/news",
                          params={'isAjax': 'true', 'type': 'recommend'},
                          headers=headers,
                          timeout=15)

print("Response status:", ajax_response.status_code)
print("Response content type:", ajax_response.headers.get('content-type'))

# Print a sample of the response
response_text = ajax_response.text
print("\nFirst 1000 characters of response:")
print(repr(response_text[:1000]))

print("\nActual first 1000 characters of response:")
print(response_text[:1000])

# Parse the response as HTML
ajax_soup = BeautifulSoup(ajax_response.content, 'html.parser')

# Find news items - let's try various selectors
cards = ajax_soup.select('div.news_item, .news_item, .news_list a')
if not cards:
    cards = ajax_soup.find_all('a', href=re.compile(r'/news/\d+'))

print(f"\nFound {len(cards)} potential items")
for i, card in enumerate(cards[:3]):  # Just check first 3
    print(f"\nCard {i+1}:")
    print(f"  Tag: {card.name}")
    print(f"  Attributes: {card.attrs}")
    print(f"  Text (first 200 chars): {repr(card.get_text(strip=True)[:200])}")
    print(f"  Href: {card.get('href', 'None')}")

    # Try to find children
    if card.name != 'a':
        link = card.find('a')
        if link:
            print(f"  Child link text: {repr(link.get_text(strip=True)[:200])}")
            print(f"  Child link href: {link.get('href', 'None')}")