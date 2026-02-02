#!/usr/bin/env python3

import requests
from bs4 import BeautifulSoup

# Session with headers to mimic a real browser
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

try:
    response = session.get("https://paper.seebug.org/", timeout=15)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, 'html.parser')

    print("Looking for div.main-inner...")
    main_inner_divs = soup.find_all('div', class_='main-inner')

    print(f"Found {len(main_inner_divs)} div.main-inner elements")

    for i, main_div in enumerate(main_inner_divs[:3]):  # Show first 3
        print(f"\n--- Main Inner Div {i+1} ---")

        # Look for post-header inside main-inner
        post_headers = main_div.find_all('div', class_='post-header')
        print(f"Found {len(post_headers)} post-header elements in this main-inner")

        for j, post_header in enumerate(post_headers[:2]):  # Show first 2
            print(f"\n  Post Header {j+1}:")
            print(f"    HTML snippet: {post_header.prettify()[:500]}...")

            # Find the link in the post-header
            link_tag = post_header.find('a')
            if link_tag:
                print(f"    Link text: '{link_tag.text.strip()[:100]}...'")

            # Find href
            href = link_tag.get('href') if link_tag else 'N/A'
            print(f"    Link href: {href}")

            # Look for time or date in post-header
            time_elem = post_header.find('time') or post_header.find('span', class_='post-date')
            if time_elem:
                print(f"    Date/time element: '{time_elem.get_text(strip=True)}'")

            # Find parent to look for description/excerpt
            parent = post_header.find_parent()
            if parent:
                excerpt_elem = parent.find('div', class_='post-excerpt') or \
                             parent.find('p', class_='post-excerpt') or \
                             parent.find('div', class_='post-content')

                if excerpt_elem:
                    print(f"    Excerpt: '{excerpt_elem.get_text(strip=True)[:200]}...'")

except Exception as e:
    print(f"Error fetching SeeBug Paper: {str(e)}")