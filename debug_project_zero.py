#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup

# Session with headers to mimic a real browser
proxy_session = requests.Session()
proxy_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

# Try direct connection first
try:
    response = proxy_session.get("https://projectzero.google/", timeout=20)
    print("Direct connection successful")
except:
    print("Direct connection failed, trying proxy...")
    # If direct connection fails, try using the proxy
    proxy_session.proxies = {
        'http': 'http://192.168.36.1:7890',
        'https': 'http://192.168.36.1:7890'
    }
    response = proxy_session.get("https://projectzero.google/", timeout=20)

soup = BeautifulSoup(response.content, 'html.parser')

print("Looking for elements with class='grid'...")
grid_elements = soup.find_all(class_='grid')

print(f"Found {len(grid_elements)} elements with class='grid'")

for i, element in enumerate(grid_elements[:5]):  # Show first 5
    print(f"\n--- Grid Element {i+1} ---")
    print(f"Tag: {element.name}")
    print(f"Classes: {element.get('class', [])}")
    print("HTML snippet:")
    print(element.prettify()[:500])

    # Look for links in the element
    links = element.find_all('a')
    print(f"Found {len(links)} links in this element")
    for j, link in enumerate(links[:2]):
        print(f"  Link {j+1}: '{link.text.strip()[:50]}...' -> {link.get('href', 'N/A')}")

# Let's also check for any article elements
article_elements = soup.find_all('article')
print(f"\nFound {len(article_elements)} article elements")
for i, article in enumerate(article_elements[:3]):
    print(f"Article {i+1} classes: {article.get('class', [])}")
    if 'grid' in article.get('class', []):
        print(f"  This article has 'grid' class!")
        link = article.find('a')
        if link:
            print(f"  Link: '{link.text.strip()[:50]}...' -> {link.get('href', 'N/A')}")