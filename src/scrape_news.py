#!/usr/bin/env python3
"""
Security News Aggregator
Scrapes cybersecurity news from multiple sources and generates a static HTML page
"""

import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
import os
import json
import logging
from urllib.parse import urljoin, urlparse
import re
import html

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Session with headers to mimic a real browser
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})

class SecurityNewsAggregator:
    def __init__(self):
        self.articles = {
            'tech': [],
            'news': []
        }

    def decode_html_entities(self, text):
        """Decode HTML entities in text"""
        if text:
            return html.unescape(text)
        return text

    def scrape_daily_security(self):
        """Scrape https://sec.today/pulses/ for security pulses (tech articles)"""
        logger.info("Scraping Daily Security...")
        try:
            response = session.get("https://sec.today/pulses/", timeout=20)  # Increased timeout
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            cards = soup.find_all('div', class_='card my-2')

            for card in cards:  # Process all available cards
                try:
                    link_tag = card.find('a')
                    if link_tag:
                        title = self.decode_html_entities(link_tag.text.strip()) or 'No Title'
                        url = urljoin("https://sec.today/pulses/", link_tag.get('href'))

                        # Extract description if available
                        desc_tag = card.find('p')
                        description = self.decode_html_entities(desc_tag.text.strip()) if desc_tag else ''

                        # Extract date from relative time text like "• 2 days ago"
                        date = datetime.now().strftime('%Y-%m-%d')  # Default fallback

                        import re
                        from datetime import timedelta

                        # Look for time-relative text in the card
                        card_text = card.get_text()
                        time_ago_pattern = r'(\d+)\s+(day|days|hour|hours|minute|minutes|second|seconds)\s+ago'
                        match = re.search(time_ago_pattern, card_text)

                        if match:
                            quantity = int(match.group(1))
                            unit = match.group(2)

                            # Calculate actual date based on the relative time
                            if 'day' in unit:
                                past_date = datetime.now() - timedelta(days=quantity)
                            elif 'hour' in unit:
                                past_date = datetime.now() - timedelta(hours=quantity)
                            elif 'minute' in unit:
                                past_date = datetime.now() - timedelta(minutes=quantity)
                            elif 'second' in unit:
                                past_date = datetime.now() - timedelta(seconds=quantity)
                            else:
                                past_date = datetime.now()

                            date = past_date.strftime('%Y-%m-%d')
                        else:
                            # Look for explicit date patterns as backup
                            date_patterns = [
                                r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
                                r'(\d{4}/\d{2}/\d{2})',  # YYYY/MM/DD
                                r'(\d{2}/\d{2}/\d{4})',  # MM/DD/YYYY
                            ]

                            for pattern in date_patterns:
                                date_match = re.search(pattern, card_text)
                                if date_match:
                                    extracted_date = date_match.group(1)
                                    if '/' in extracted_date:
                                        try:
                                            parsed_date = datetime.strptime(extracted_date, '%Y/%m/%d')
                                            date = parsed_date.strftime('%Y-%m-%d')
                                            break
                                        except ValueError:
                                            try:
                                                parsed_date = datetime.strptime(extracted_date, '%m/%d/%Y')
                                                date = parsed_date.strftime('%Y-%m-%d')
                                            except ValueError:
                                                pass
                                    else:
                                        date = extracted_date
                                    break

                        # Add to tech articles
                        article = {
                            'title': title,
                            'url': url,
                            'source': 'Daily Security',
                            'description': description,
                            'date': date,
                            'category': 'tech'
                        }
                        self.articles['tech'].append(article)
                except Exception as e:
                    logger.warning(f"Error processing Daily Security card: {str(e)}")
                    continue
        except Exception as e:
            logger.error(f"Error scraping Daily Security: {str(e)}")

    def scrape_tencent_security(self):
        """Scrape https://sectoday.tencent.com/ for tech articles"""
        logger.info("Scraping Tencent Security...")
        try:
            response = session.get("https://sectoday.tencent.com/", timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            cards = soup.find_all('div', class_='MuiPaper-root')

            for card in cards:  # Process all available cards
                try:
                    # Look for links in the card
                    link_tags = card.find_all('a')
                    for link_tag in link_tags:
                        href = link_tag.get('href')
                        if href and '/detail/' in href:  # Likely an article link
                            title = self.decode_html_entities(link_tag.text.strip()) or 'No Title'
                            url = urljoin("https://sectoday.tencent.com/", href)

                            # Extract description if available
                            p_tags = card.find_all('p')
                            description = self.decode_html_entities(p_tags[0].text.strip()) if p_tags else ''

                            # Add to tech articles
                            article = {
                                'title': title,
                                'url': url,
                                'source': 'Tencent Security',
                                'description': description,
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'category': 'tech'
                            }
                            self.articles['tech'].append(article)
                            break  # Processed the first valid link
                except Exception as e:
                    logger.warning(f"Error processing Tencent Security card: {str(e)}")
                    continue
        except Exception as e:
            logger.error(f"Error scraping Tencent Security: {str(e)}")

    def scrape_xz_aliyun(self):
        """Scrape https://xz.aliyun.com/news for security news (tech) using the proper GET request"""
        logger.info("Scraping XZ Aliyun...")
        try:
            # First, get the main page to extract CSRF token
            response = session.get("https://xz.aliyun.com/news", timeout=15)
            response.raise_for_status()

            # Parse the page to extract CSRF token
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

            # Make the AJAX request to get the news list as JSON containing HTML
            ajax_response = session.get("https://xz.aliyun.com/news",
                                      params={'isAjax': 'true', 'type': 'recommend'},
                                      headers=headers,
                                      timeout=15)
            ajax_response.raise_for_status()

            # The response is JSON with HTML content in the 'data' field
            json_data = ajax_response.json()

            if 'data' in json_data and isinstance(json_data['data'], str):
                # Parse the HTML content from the JSON response
                html_content = json_data['data']
                ajax_soup = BeautifulSoup(html_content, 'html.parser')

                # Find the news items in the returned HTML
                cards = ajax_soup.select('div.news_item, .news_item')

                for card in cards:
                    try:
                        # Find the main link in the card
                        link_tag = card.find('a')

                        if link_tag:
                            # Extract title from the link's text or alt attribute of image
                            img_tag = card.find('img')

                            # Try to get title from image alt attribute first
                            if img_tag and img_tag.get('alt'):
                                title = self.decode_html_entities(img_tag.get('alt', '').strip())
                            else:
                                # Fallback to link text
                                title = self.decode_html_entities(link_tag.get_text(strip=True))

                            if not title or title == '':
                                continue  # Skip if no title

                            url = link_tag.get('href')
                            if url and not url.startswith('http'):
                                url = urljoin("https://xz.aliyun.com", url)

                            # Extract description - look for text elements near the link
                            description = ""

                            # Look for paragraph tags, divs with text, or spans that might contain description
                            # Try to find other text in the card excluding the link with the title

                            # Find elements that could contain description (excluding the main link)
                            possible_desc_elements = card.find_all(['p', 'div', 'span'], recursive=True)

                            desc_texts = []
                            for elem in possible_desc_elements:
                                # Only add text if it's not inside the main link tag
                                if not link_tag.find_all(recursive=True) or elem not in link_tag.find_all(recursive=True):
                                    elem_text = elem.get_text(strip=True)
                                    # Only add substantial text (more than 5 characters and not just numbers)
                                    if elem_text and len(elem_text) > 5 and not elem_text.isdigit():
                                        # Exclude common non-descriptive text
                                        if elem_text.lower() not in ['read more', 'more', 'details', 'view', 'click', '继续阅读']:
                                            desc_texts.append(self.decode_html_entities(elem_text))

                            # Alternative: Get all text from the card and remove the title/link text
                            if not desc_texts:
                                card_text = card.get_text(separator=' ', strip=True)
                                if img_tag and img_tag.get('alt'):
                                    title_to_remove = img_tag.get('alt', '').strip()
                                else:
                                    title_to_remove = link_tag.get_text(strip=True)

                                if title_to_remove and title_to_remove in card_text:
                                    # Remove title from full text to get potential description
                                    remaining_text = card_text.replace(title_to_remove, '', 1).strip()
                                    # Look for meaningful text (excluding author names, dates, etc.)
                                    if remaining_text:
                                        # Split by common separators and look for content
                                        parts = [part.strip() for part in remaining_text.split('\n') if part.strip()]
                                        for part in parts:
                                            if len(part) > 20 and '发表于' not in part and '作者' not in part and '浏览' not in part:
                                                desc_texts.append(self.decode_html_entities(part))
                                                break

                            if desc_texts:
                                description = desc_texts[0][:200] + "..." if len(desc_texts[0]) > 200 else desc_texts[0]
                            else:
                                # Last resort: try to find any descriptive text near the link
                                parent = link_tag.parent
                                if parent:
                                    # Get siblings and their text
                                    for sibling in parent.children:
                                        if sibling != link_tag and hasattr(sibling, 'get_text'):
                                            sibling_text = sibling.get_text(strip=True)
                                            if sibling_text and len(sibling_text) > 20:
                                                description = self.decode_html_entities(sibling_text)[:200] + "..." if len(sibling_text) > 200 else self.decode_html_entities(sibling_text)
                                                break

                            # Clean up description - remove excessive whitespace
                            if description:
                                description = ' '.join(description.split())

                            # Try to extract publication date from the card
                            date = datetime.now().strftime('%Y-%m-%d')  # Default fallback

                            # Look for date patterns in the card
                            card_text = card.get_text(separator=' ', strip=True)

                            # Look for Chinese date patterns like "2026-01-29", "2026/01/29", etc.
                            # Or patterns like "发表于 YYYY-MM-DD" (published on)
                            import re
                            # Match dates like: 2026-01-29, 2026/01/29, 2026.01.29, etc.
                            date_pattern = r'(?:\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}|发表于\D*(\d{4}-\d{2}-\d{2})|发表于\D*(\d{4}/\d{2}/\d{2}))'
                            date_match = re.search(date_pattern, card_text)
                            if date_match:
                                # Get the matched date or any captured groups
                                full_match = date_match.group(0)
                                # Extract just the date part
                                actual_date = re.search(r'\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}', full_match)
                                if actual_date:
                                    extracted_date = actual_date.group(0)
                                    # Convert to standard format
                                    try:
                                        parsed_date = datetime.strptime(extracted_date.replace('/', '-'), '%Y-%m-%d')
                                        date = parsed_date.strftime('%Y-%m-%d')
                                    except ValueError:
                                        # If date parsing fails, use today's date
                                        date = datetime.now().strftime('%Y-%m-%d')

                            # Look for additional text elements that might have date information
                            date_elements = card.find_all(string=re.compile(r'发表于|发布于|发布时间|时间|日期'))
                            for element in date_elements:
                                parent = element.parent
                                if parent:
                                    parent_text = parent.get_text(strip=True)
                                    date_match2 = re.search(r'\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}', parent_text)
                                    if date_match2:
                                        extracted_date = date_match2.group(0)
                                        try:
                                            parsed_date = datetime.strptime(extracted_date.replace('/', '-'), '%Y-%m-%d')
                                            date = parsed_date.strftime('%Y-%m-%d')
                                            break
                                        except ValueError:
                                            continue

                            # Add to tech articles
                            article = {
                                'title': title,
                                'url': url,
                                'source': 'XZ Aliyun',
                                'description': description,
                                'date': date,
                                'category': 'tech'
                            }
                            self.articles['tech'].append(article)
                    except Exception as e:
                        logger.warning(f"Error processing XZ Aliyun item: {str(e)}")
                        continue
            else:
                logger.warning("Unexpected response structure from XZ Aliyun API")

        except Exception as e:
            logger.error(f"Error scraping XZ Aliyun: {str(e)}")

    def scrape_project_zero(self):
        """Scrape https://projectzero.google/ for security research (tech)"""
        logger.info("Scraping Project Zero...")
        try:
            # Create a new session that can use proxy for testing
            proxy_session = requests.Session()
            proxy_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })

            # Check if we're in testing environment by attempting to connect directly first
            try:
                response = proxy_session.get("https://projectzero.google/", timeout=20)
                response.raise_for_status()
            except:
                # If direct connection fails, try using the proxy
                logger.info("Direct connection to Project Zero failed, trying proxy...")
                proxy_session.proxies = {
                    'http': 'http://192.168.36.1:7890',  # Updated to match user's proxy address
                    'https': 'http://192.168.36.1:7890'  # Updated to match user's proxy address
                }
                response = proxy_session.get("https://projectzero.google/", timeout=20)

            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Find articles with the specific article class="grid" as mentioned
            grid_articles = soup.find_all('article', class_='grid')

            for article in grid_articles:  # Process all available grid articles
                try:
                    # Find the title link within the post-title div
                    title_div = article.find('div', class_='post-title')
                    link_tag = None
                    if title_div:
                        link_tag = title_div.find('a')

                    if link_tag:
                        title = self.decode_html_entities(link_tag.text.strip()) or 'No Title'
                        url = urljoin("https://projectzero.google/", link_tag.get('href'))

                        # Extract description from post-content-snippet
                        description = ''
                        content_snippet = article.find('section', class_='post-content-snippet')
                        if content_snippet:
                            p_tag = content_snippet.find('p')
                            if p_tag:
                                description = self.decode_html_entities(p_tag.text.strip())

                        if not description:
                            # Fallback: find any p tag in the article
                            p_tags = article.find_all('p')
                            if p_tags:
                                description = self.decode_html_entities(p_tags[0].text.strip()[:200] + "..." if len(p_tags[0].text.strip()) > 200 else p_tags[0].text.strip())

                        # Extract date from post-meta
                        date = datetime.now().strftime('%Y-%m-%d')  # Default fallback
                        date_div = article.find('div', class_='post-meta')
                        if date_div:
                            date_link = date_div.find('a', class_='post-date')
                            if date_link:
                                date_text = date_link.text.strip()
                                # Parse date in format like "2026-Jan-30"
                                import re
                                date_match = re.search(r'(\d{4})-(\w+)-(\d{2})', date_text)
                                if date_match:
                                    year = date_match.group(1)
                                    month_str = date_match.group(2)
                                    day = date_match.group(3)

                                    # Convert month abbreviation to number
                                    months = {
                                        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                                        'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                                        'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
                                    }

                                    if month_str in months:
                                        month = months[month_str]
                                        try:
                                            parsed_date = datetime.strptime(f"{year}-{month}-{day}", '%Y-%m-%d')
                                            date = parsed_date.strftime('%Y-%m-%d')
                                        except ValueError:
                                            pass

                        # Add to tech articles
                        article_dict = {
                            'title': title,
                            'url': url,
                            'source': 'Project Zero',
                            'description': description,
                            'date': date,
                            'category': 'tech'
                        }
                        self.articles['tech'].append(article_dict)
                except Exception as e:
                    logger.warning(f"Error processing Project Zero item: {str(e)}")
                    continue
        except Exception as e:
            logger.error(f"Error scraping Project Zero: {str(e)}")

    def scrape_anquanke(self):
        """Scrape https://www.anquanke.com/ for security news using API"""
        logger.info("Scraping Anquanke...")
        try:
            import time
            import random

            # Get current timestamp to mimic the API call
            timestamp = int(time.time() * 1000)

            # Scrape multiple pages (page < 5 as requested)
            for page in range(1, 5):
                # Construct API URL with timestamp and page
                api_url = f"https://www.anquanke.com/webapi/api/index/top/list?page={page}&_={timestamp + page}"

                try:
                    response = session.get(api_url, timeout=10)
                    response.raise_for_status()

                    # Parse JSON response
                    data = response.json()

                    # Check if response has expected structure
                    if 'data' in data and 'list' in data['data']:
                        articles_list = data['data']['list']

                        for article_data in articles_list:
                            try:
                                title = self.decode_html_entities(article_data.get('title', 'No Title'))

                                # Build URL from article ID
                                article_id = article_data.get('id')
                                url_raw = article_data.get('url', '')

                                # Prioritize using article ID to build canonical URL
                                if article_id:
                                    url = f"https://www.anquanke.com/post/id/{article_id}"
                                elif url_raw and url_raw.startswith('/'):
                                    # If URL is relative, make it absolute
                                    url = f"https://www.anquanke.com{url_raw}"
                                elif url_raw:
                                    # If URL is already absolute, use as-is
                                    url = url_raw
                                else:
                                    # Fallback to a default empty URL
                                    url = f"https://www.anquanke.com/post/id/{article_id}" if article_id else ""

                                description = self.decode_html_entities(article_data.get('desc', '') or article_data.get('summary', ''))

                                # Extract and format date
                                date = datetime.now().strftime('%Y-%m-%d')  # Default fallback

                                publish_time = article_data.get('publish_time')
                                if publish_time:
                                    try:
                                        # Handle different date formats
                                        if isinstance(publish_time, str):
                                            # If date is in string format like "2026-01-30 10:30:00"
                                            if ' ' in publish_time:
                                                parsed_date = datetime.strptime(publish_time.split()[0], '%Y-%m-%d')
                                            else:
                                                parsed_date = datetime.strptime(publish_time, '%Y-%m-%d')
                                            date = parsed_date.strftime('%Y-%m-%d')
                                    except ValueError:
                                        # If date parsing fails, keep default date
                                        pass

                                # Add to news articles (default category as per requirement)
                                article = {
                                    'title': title,
                                    'url': url,
                                    'source': 'Anquanke',
                                    'description': description,
                                    'date': date,
                                    'category': 'news'  # Default category as specified
                                }
                                self.articles['news'].append(article)

                            except Exception as e:
                                logger.warning(f"Error processing Anquanke article data: {str(e)}")
                                continue
                    else:
                        logger.warning(f"Unexpected response structure from Anquanke API on page {page}")

                except Exception as e:
                    logger.error(f"Error scraping Anquanke API page {page}: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error scraping Anquanke: {str(e)}")

    def scrape_freebuf(self):
        """Scrape https://www.freebuf.com/ for security news"""
        logger.info("Scraping FreeBuf...")
        try:
            # Create a specialized session for FreeBuf to handle anti-bot measures
            import time
            import random

            # Create a new session with more realistic browser headers
            freebuf_session = requests.Session()

            # Set very realistic browser headers to mimic a real user
            headers_list = [
                {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'max-age=0',
                    'DNT': '1'
                },
                {
                    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'max-age=0',
                    'DNT': '1'
                }
            ]

            # Randomly select headers to vary the requests
            selected_headers = random.choice(headers_list)
            freebuf_session.headers.update(selected_headers)

            # First, establish a session by visiting the homepage to get cookies
            response = freebuf_session.get("https://www.freebuf.com/", timeout=15)

            # Check if page requires verification/captcha
            if "verification" in response.text.lower() or "captcha" in response.text.lower() or "aliyun_waf" in response.text.lower():
                logger.info("FreeBuf may require verification, trying with different approach...")

                # Add more human-like behaviors
                time.sleep(random.uniform(2, 5))  # Simulate initial page load time

                # Try with different headers that look more like a returning user
                freebuf_session.headers.update({
                    'Referer': 'https://www.google.com/',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120"',
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': '"Windows"',
                    'Sec-Gpc': '1'
                })

                # Try visiting a specific section instead of homepage
                response = freebuf_session.get("https://www.freebuf.com/news", timeout=15)

            # Check again if page still requires verification
            if "verification" in response.text.lower() or "captcha" in response.text.lower() or "aliyun_waf" in response.text.lower():
                logger.warning("FreeBuf requires verification/captcha - unable to scrape content")
                # Still return gracefully without adding any articles
                return

            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Find articles using the specified structure: div class="article-list" > div class="article-item"
            article_list = soup.find('div', class_='article-list')

            if article_list:
                # Find all article items within the article-list container
                article_items = article_list.find_all('div', class_='article-item')

                for item in article_items:
                    try:
                        # Find the link in the article-item
                        link_tag = item.find('a')

                        if link_tag:
                            title = self.decode_html_entities(link_tag.text.strip()) or 'No Title'
                            url = link_tag.get('href')

                            # Ensure URL is complete
                            if url:
                                if not url.startswith('http'):
                                    url = urljoin("https://www.freebuf.com/", url)

                            # Extract description if available
                            description = ''

                            # Look for description in the item - could be in p tag or div with description class
                            desc_elem = item.find('p', class_='desc') or item.find('div', class_='desc') or \
                                      item.find('p', class_='description') or item.find('div', class_='description') or \
                                      item.find('div', class_='summary')

                            if desc_elem:
                                description = self.decode_html_entities(desc_elem.get_text(strip=True))

                            # If no description found in specific elements, try to get any text content excluding the title
                            if not description:
                                # Get all text from the item and exclude the title
                                all_text = item.get_text(separator=' ', strip=True)
                                if title and title in all_text:
                                    remaining_text = all_text.replace(title, '', 1).strip()
                                    # Take first sentence or first 200 characters as description
                                    if remaining_text:
                                        description = self.decode_html_entities(remaining_text[:200] + "..." if len(remaining_text) > 200 else remaining_text)

                            # Extract date if available
                            date = datetime.now().strftime('%Y-%m-%d')  # Default fallback

                            # Look for date in time element or other date-related classes
                            time_elem = item.find('time') or item.find('span', class_='time') or \
                                       item.find('span', class_='date') or item.find('div', class_='time')

                            if time_elem:
                                time_text = time_elem.get_text(strip=True)
                                import re
                                # Try to extract date in various formats
                                date_match = re.search(r'(\d{4}[-/年]\d{1,2}[/-月]\d{1,2}日?)', time_text)
                                if date_match:
                                    extracted_date = date_match.group(1)
                                    # Clean up the date string
                                    extracted_date = extracted_date.replace('年', '-').replace('月', '-').replace('日', '')
                                    try:
                                        parsed_date = datetime.strptime(extracted_date, '%Y-%m-%d')
                                        date = parsed_date.strftime('%Y-%m-%d')
                                    except ValueError:
                                        pass

                            # Add to news articles as specified (these are mostly news)
                            article = {
                                'title': title,
                                'url': url,
                                'source': 'FreeBuf',
                                'description': description,
                                'date': date,
                                'category': 'news'  # Most FreeBuf articles are news
                            }
                            self.articles['news'].append(article)
                    except Exception as e:
                        logger.warning(f"Error processing FreeBuf item: {str(e)}")
                        continue
            else:
                # If article-list not found, try other common selectors
                logger.info("Could not find article-list container, trying alternative selectors...")

                # Try other possible article containers
                possible_selectors = [
                    'div.feed-item',
                    'div.news-item',
                    'div.list-item',
                    'article',
                    '.item',
                    '.list-item',
                    '.article-item',
                    '.news-item',
                    '[class*="feed"]',
                    '[class*="card"]'
                ]

                articles_found = False
                for selector in possible_selectors:
                    elements = soup.select(selector)
                    if elements:
                        logger.info(f"Found {len(elements)} elements with selector '{selector}'")

                        for element in elements[:10]:  # Limit to first 10 to prevent too many
                            try:
                                link_tag = element.find('a')

                                if link_tag:
                                    title = self.decode_html_entities(link_tag.text.strip()) or 'No Title'
                                    url = link_tag.get('href')

                                    if url and not url.startswith('http'):
                                        url = urljoin("https://www.freebuf.com/", url)

                                    # Extract description
                                    desc_elem = element.find('p') or element.find('div', class_='content') or element.find('div', class_='summary')
                                    description = self.decode_html_entities(desc_elem.get_text(strip=True)) if desc_elem else ''

                                    # Extract date
                                    time_elem = element.find('time') or element.find('span', class_='time') or element.find('span', class_='date')
                                    date = datetime.now().strftime('%Y-%m-%d')
                                    if time_elem:
                                        time_text = time_elem.get_text(strip=True)
                                        import re
                                        date_match = re.search(r'(\d{4}[-/年]\d{1,2}[/-月]\d{1,2}日?)', time_text)
                                        if date_match:
                                            extracted_date = date_match.group(1).replace('年', '-').replace('月', '-').replace('日', '')
                                            try:
                                                parsed_date = datetime.strptime(extracted_date, '%Y-%m-%d')
                                                date = parsed_date.strftime('%Y-%m-%d')
                                            except ValueError:
                                                pass

                                    article = {
                                        'title': title,
                                        'url': url,
                                        'source': 'FreeBuf',
                                        'description': description,
                                        'date': date,
                                        'category': 'news'
                                    }
                                    self.articles['news'].append(article)
                                    articles_found = True
                            except Exception as e:
                                logger.warning(f"Error processing FreeBuf alternative element: {str(e)}")
                                continue
                        break  # Stop after finding articles with first valid selector

                if not articles_found:
                    logger.info("Could not find article-list container on FreeBuf - may be protected by security measures")

        except requests.exceptions.RequestException as e:
            if "403" in str(e) or "503" in str(e) or "captcha" in str(e).lower():
                logger.warning(f"FreeBuf blocked the request (likely protected by security): {str(e)}")
            else:
                logger.error(f"Network error while scraping FreeBuf: {str(e)}")
        except Exception as e:
            logger.error(f"Error scraping FreeBuf: {str(e)}")

    def scrape_secrss(self):
        """Scrape https://www.secrss.com/ for security news"""
        logger.info("Scraping Secrss...")
        try:
            response = session.get("https://www.secrss.com/", timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Find the article list title and its following ul
            article_list_title = soup.find('div', class_='article-list-title')

            if article_list_title:
                # Find the next ul sibling which contains articles
                next_ul = article_list_title.find_next_sibling('ul')

                if next_ul:
                    # Get all list items from this UL
                    list_items = next_ul.find_all('li', class_='list-item')

                    for li in list_items:
                        try:
                            # Find the title link within the article
                            title_elem = li.find('h2', class_='title') or li.find('div', class_='title')
                            link_tag = None
                            if title_elem:
                                link_tag = title_elem.find('a')

                            # Fallback: find any link in the list item
                            if not link_tag:
                                link_tag = li.find('a')

                            if link_tag:
                                title = self.decode_html_entities(link_tag.text.strip()) or 'No Title'
                                url = link_tag.get('href')
                                if url and not url.startswith('http'):
                                    url = urljoin("https://www.secrss.com/", url)

                                # Extract description from intro/partial content
                                description = ''
                                intro_elem = li.find('p', class_='intro') or li.find('div', class_='intro')
                                if intro_elem:
                                    # Get text from the intro element, excluding any links inside it
                                    intro_text = intro_elem.get_text(strip=True)
                                    description = self.decode_html_entities(intro_text[:200] + "..." if len(intro_text) > 200 else intro_text)

                                # Extract date from time element
                                date = datetime.now().strftime('%Y-%m-%d')  # Default fallback

                                time_elem = li.find('span', class_='time') or li.find('div', class_='time')
                                if time_elem:
                                    time_text = time_elem.get_text(strip=True)
                                    import re
                                    from datetime import timedelta

                                    # Check if time_text contains relative time like "X小时前"
                                    hours_ago_match = re.search(r'(\d+)小时前', time_text)
                                    if hours_ago_match:
                                        hours_ago = int(hours_ago_match.group(1))
                                        past_date = datetime.now() - timedelta(hours=hours_ago)
                                        date = past_date.strftime('%Y-%m-%d')
                                    else:
                                        # Check for date format like "2026-01-31"
                                        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', time_text)
                                        if date_match:
                                            extracted_date = date_match.group(1)
                                            try:
                                                parsed_date = datetime.strptime(extracted_date, '%Y-%m-%d')
                                                date = parsed_date.strftime('%Y-%m-%d')
                                            except ValueError:
                                                pass

                                # Add to news articles
                                article = {
                                    'title': title,
                                    'url': url,
                                    'source': 'Secrss',
                                    'description': description,
                                    'date': date,
                                    'category': 'news'
                                }
                                self.articles['news'].append(article)
                        except Exception as e:
                            logger.warning(f"Error processing Secrss item: {str(e)}")
                            continue
        except Exception as e:
            logger.error(f"Error scraping Secrss: {str(e)}")

    def scrape_seebug_paper(self):
        """Scrape https://paper.seebug.org/ for security research papers (tech)"""
        logger.info("Scraping SeeBug Paper...")
        try:
            # Create a specialized session for SeeBug Paper to handle anti-bot measures
            import time

            # Create a new session with more realistic headers
            seebug_session = requests.Session()

            # Set headers to mimic a real browser
            seebug_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.64',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0'
            })

            # First, try to establish a session by getting the main page
            response = seebug_session.get("https://paper.seebug.org/", timeout=20)

            # Add a delay to simulate human-like behavior
            time.sleep(2)

            # If first request was blocked, try again
            if response.status_code in [403, 503, 521, 522, 524]:
                # Add additional delays and different headers
                time.sleep(5)
                seebug_session.headers.update({
                    'Referer': 'https://google.com/',
                    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120"',
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': '"Windows"'
                })
                response = seebug_session.get("https://paper.seebug.org/", timeout=20)

            # Check response status
            if response.status_code in [403, 503, 521, 522, 524]:
                logger.warning(f"SeeBug Paper blocked the request (status: {response.status_code}), server may be protected by shield.")
                return  # Exit gracefully if still blocked

            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Alternative approach: look for common blog/article patterns if main-inner isn't available
            # Try multiple selectors to find articles

            # First, try the specified selector
            articles_found = False
            main_inner_divs = soup.find_all('div', class_='main-inner')

            if main_inner_divs:
                logger.info(f"Found {len(main_inner_divs)} main-inner divs in SeeBug Paper")

                for main_div in main_inner_divs:
                    try:
                        # Look for post-header inside main-inner
                        post_headers = main_div.find_all('div', class_='post-header')

                        for post_header in post_headers:
                            # Find the link in the post-header
                            link_tag = post_header.find('a')

                            if link_tag:
                                title = self.decode_html_entities(link_tag.text.strip()) or 'No Title'
                                url = link_tag.get('href')
                                if url and not url.startswith('http'):
                                    url = urljoin("https://paper.seebug.org/", url)

                                # Extract description from nearby elements (typically post-excerpt)
                                description = ''

                                # Look for the post-excerpt in the parent context
                                parent = post_header.find_parent()
                                if parent:
                                    excerpt_elem = parent.find('div', class_='post-excerpt') or \
                                                 parent.find('p', class_='post-excerpt') or \
                                                 parent.find('div', class_='post-content') or \
                                                 parent.find('div', class_='excerpt')

                                    if excerpt_elem:
                                        description = self.decode_html_entities(excerpt_elem.get_text(strip=True)[:200] + "..." if len(excerpt_elem.get_text(strip=True)) > 200 else excerpt_elem.get_text(strip=True))

                                # Extract date from post-meta or time element
                                date = datetime.now().strftime('%Y-%m-%d')  # Default fallback

                                # Look for date in the post-header or nearby
                                time_elem = post_header.find('time') or post_header.find('span', class_='post-date') or post_header.find('span', class_='date')
                                if time_elem:
                                    time_text = time_elem.get_text(strip=True)
                                    import re
                                    # Try to extract date in format like "2026-01-29" or "January 29, 2026"
                                    date_match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})', time_text)
                                    if date_match:
                                        extracted_date = date_match.group(1)
                                        try:
                                            parsed_date = datetime.strptime(extracted_date.replace('/', '-'), '%Y-%m-%d')
                                            date = parsed_date.strftime('%Y-%m-%d')
                                        except ValueError:
                                            pass
                                    else:
                                        # Try month-day-year format
                                        month_day_year_patterns = [
                                            r'(\w+\s+\d{1,2},?\s+\d{4})',  # Month DD, YYYY
                                            r'(\d{1,2}\s+\w+\s+\d{4})'      # DD Month YYYY
                                        ]
                                        for pattern in month_day_year_patterns:
                                            date_match = re.search(pattern, time_text)
                                            if date_match:
                                                try:
                                                    parsed_date = datetime.strptime(date_match.group(1), '%B %d, %Y')
                                                    date = parsed_date.strftime('%Y-%m-%d')
                                                    break
                                                except ValueError:
                                                    try:
                                                        parsed_date = datetime.strptime(date_match.group(1), '%b %d, %Y')
                                                        date = parsed_date.strftime('%Y-%m-%d')
                                                        break
                                                    except ValueError:
                                                        try:
                                                            # Try DD Month YYYY format
                                                            parsed_date = datetime.strptime(date_match.group(1), '%d %B %Y')
                                                            date = parsed_date.strftime('%Y-%m-%d')
                                                            break
                                                        except ValueError:
                                                            continue

                                # Add to tech articles as specified (these are security tech papers)
                                article = {
                                    'title': title,
                                    'url': url,
                                    'source': 'SeeBug Paper',
                                    'description': description,
                                    'date': date,
                                    'category': 'tech'  # Security research papers belong to tech category
                                }
                                self.articles['tech'].append(article)
                                articles_found = True
                    except Exception as e:
                        logger.warning(f"Error processing SeeBug Paper item in main-inner: {str(e)}")
                        continue
            else:
                # Try alternative selectors if main-inner isn't found
                logger.info("main-inner not found, trying alternative selectors...")

                # Look for other common article selectors
                alternative_selectors = [
                    'article',  # Standard article tag
                    'div.post',  # Posts in div with post class
                    'div.entry',  # Entries in div with entry class
                    'div.article',  # Articles in div with article class
                    'div.list-item',  # List items
                    '.post-item',  # Post items with class
                ]

                for selector in alternative_selectors:
                    alternative_elements = soup.select(selector)
                    if alternative_elements:
                        logger.info(f"Found {len(alternative_elements)} elements with selector '{selector}'")

                        for element in alternative_elements[:10]:  # Limit to first 10 to avoid too many
                            try:
                                # Try to find a link in the element
                                link_tag = element.find('a')

                                if link_tag:
                                    title = self.decode_html_entities(link_tag.text.strip()) or 'No Title'
                                    url = link_tag.get('href')
                                    if url and not url.startswith('http'):
                                        url = urljoin("https://paper.seebug.org/", url)

                                    # Extract description
                                    description = ''
                                    desc_elem = element.find('p') or element.find('div', class_='content') or element.find('div', class_='summary')
                                    if desc_elem:
                                        description = self.decode_html_entities(desc_elem.get_text(strip=True)[:200] + "..." if len(desc_elem.get_text(strip=True)) > 200 else desc_elem.get_text(strip=True))

                                    # Extract date
                                    date = datetime.now().strftime('%Y-%m-%d')
                                    date_elem = element.find('time') or element.find('span', class_='date') or element.find('span', class_='time')
                                    if date_elem:
                                        date_text = date_elem.get_text(strip=True)
                                        import re
                                        date_match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})', date_text)
                                        if date_match:
                                            extracted_date = date_match.group(1)
                                            try:
                                                parsed_date = datetime.strptime(extracted_date.replace('/', '-'), '%Y-%m-%d')
                                                date = parsed_date.strftime('%Y-%m-%d')
                                            except ValueError:
                                                pass

                                    article = {
                                        'title': title,
                                        'url': url,
                                        'source': 'SeeBug Paper',
                                        'description': description,
                                        'date': date,
                                        'category': 'tech'
                                    }
                                    self.articles['tech'].append(article)
                                    articles_found = True

                            except Exception as e:
                                logger.warning(f"Error processing SeeBug Paper alternative element: {str(e)}")
                                continue
                        break  # Stop after finding one valid selector

            if not articles_found:
                logger.info("No articles found on SeeBug Paper site - may be protected by shield")

        except requests.exceptions.RequestException as e:
            if "521" in str(e) or "403" in str(e) or "503" in str(e):
                logger.warning(f"SeeBug Paper is protected by shield (got {type(e).__name__}: {str(e)})")
            else:
                logger.error(f"Network error while scraping SeeBug Paper: {str(e)}")
        except Exception as e:
            logger.error(f"Error scraping SeeBug Paper: {str(e)}")

    def scrape_all_sources(self):
        """Scrape all security news sources"""
        logger.info("Starting to scrape all security news sources...")

        # Tech-focused sources
        self.scrape_daily_security()
        self.scrape_tencent_security()
        self.scrape_xz_aliyun()
        self.scrape_project_zero()
        self.scrape_seebug_paper()

        # News-focused sources
        self.scrape_anquanke()
        self.scrape_freebuf()
        self.scrape_secrss()

        # Remove duplicates based on URL
        self.remove_duplicates()

        logger.info(f"Scraping completed. Collected {len(self.articles['tech'])} tech articles and {len(self.articles['news'])} news articles")

    def remove_duplicates(self):
        """Remove duplicate articles based on URL"""
        seen_urls = set()
        unique_tech = []
        unique_news = []

        for article in self.articles['tech']:
            if article['url'] not in seen_urls:
                seen_urls.add(article['url'])
                unique_tech.append(article)

        for article in self.articles['news']:
            if article['url'] not in seen_urls:
                seen_urls.add(article['url'])
                unique_news.append(article)

        self.articles['tech'] = unique_tech
        self.articles['news'] = unique_news

    def save_articles_json(self, filename='articles.json'):
        """Save articles to a JSON file"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)
        logger.info(f"Articles saved to {filename}")

    def load_articles_json(self, filename='articles.json'):
        """Load articles from a JSON file"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                self.articles = json.load(f)
            logger.info(f"Articles loaded from {filename}")
        except FileNotFoundError:
            logger.info(f"{filename} not found, starting with empty articles")
            self.articles = {'tech': [], 'news': []}


def generate_html(articles, output_file='docs/index.html'):
    """Generate HTML page with collected articles"""

    # Create docs directory if it doesn't exist
    import os
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Sort articles by date (most recent first)
    tech_sorted = sorted(articles['tech'], key=lambda x: x['date'], reverse=True)
    news_sorted = sorted(articles['news'], key=lambda x: x['date'], reverse=True)

    # Function to truncate description if too long
    def truncate_description(desc, max_length=500):
        if not desc:
            return desc
        if len(desc) > max_length:
            return desc[:max_length] + "..."
        return desc

    # Get all unique dates for the filter dropdown
    all_dates = set()
    for article in articles['tech'] + articles['news']:
        all_dates.add(article['date'])
    sorted_dates = sorted(list(all_dates), reverse=True)

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>网络安全资讯聚合 - Cybersecurity News Aggregator</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            background-color: #f8f9fa;
        }}

        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
            display: grid;
            grid-template-columns: 1fr 300px;
            gap: 20px;
        }}

        .main-content {{
            grid-column: 1;
        }}

        .sidebar {{
            grid-column: 2;
            background: white;
            padding: 1.5rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            align-self: start;
            position: sticky;
            top: 20px;
        }}

        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
            padding: 2rem 0;
            margin-bottom: 2rem;
            border-radius: 8px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}

        h1 {{
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
        }}

        .subtitle {{
            font-size: 1.1rem;
            opacity: 0.9;
        }}

        .filters {{
            background: white;
            padding: 1.5rem;
            border-radius: 8px;
            margin-bottom: 1.5rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .filter-group {{
            margin-bottom: 1rem;
        }}

        .filter-group label {{
            display: block;
            margin-bottom: 0.5rem;
            font-weight: bold;
            color: #495057;
        }}

        .filter-group select, .filter-group input {{
            width: 100%;
            padding: 0.5rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 0.9rem;
        }}

        .stats {{
            background: white;
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .category-section {{
            margin-bottom: 3rem;
        }}

        .section-title {{
            font-size: 1.8rem;
            color: #495057;
            margin-bottom: 1.5rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #dee2e6;
        }}

        .articles-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 1.5rem;
        }}

        .article-card {{
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
            height: 100%;
            display: flex;
            flex-direction: column;
        }}

        .article-card[data-date] {{
            /* Add data attribute for filtering */
        }}

        .article-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}

        .article-source {{
            font-size: 0.85rem;
            color: #6c757d;
            margin-bottom: 0.5rem;
        }}

        .article-title {{
            font-size: 1.1rem;
            margin-bottom: 0.75rem;
            color: #212529;
        }}

        .article-title a {{
            color: #007bff;
            text-decoration: none;
        }}

        .article-title a:hover {{
            color: #0056b3;
            text-decoration: underline;
        }}

        .article-description {{
            color: #495057;
            font-size: 0.95rem;
            margin-bottom: 1rem;
            flex-grow: 1;
        }}

        .article-date {{
            font-size: 0.85rem;
            color: #6c757d;
        }}

        .footer {{
            grid-column: 1 / -1;
            text-align: center;
            padding: 2rem 0;
            color: #6c757d;
            font-size: 0.9rem;
            margin-top: 3rem;
            border-top: 1px solid #dee2e6;
        }}

        @media (max-width: 1100px) {{
            .container {{
                grid-template-columns: 1fr;
            }}

            .sidebar {{
                grid-column: 1;
                position: static;
            }}
        }}

        @media (max-width: 768px) {{
            .container {{
                padding: 10px;
            }}

            h1 {{
                font-size: 2rem;
            }}

            .articles-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>网络安全资讯聚合</h1>
            <div class="subtitle">Cybersecurity News Aggregator - 汇聚最新网络安全资讯</div>
        </header>

        <main class="main-content">
            <div class="category-section">
                <h2 class="section-title">🎯 技术文章 (Technical Articles)</h2>
                <div class="articles-grid" id="tech-articles">
                    {"".join([f'''
                    <div class="article-card" data-date="{article['date']}">
                        <div class="article-source">来源: {article['source']}</div>
                        <h3 class="article-title"><a href="{article['url']}" target="_blank">{html.escape(article['title'])}</a></h3>
                        {f'<p class="article-description">{html.escape(truncate_description(article["description"]))}</p>' if article["description"] else ''}
                        <div class="article-date">发布日期: {article['date']}</div>
                    </div>''' for article in tech_sorted])}
                </div>
            </div>

            <div class="category-section">
                <h2 class="section-title">📰 安全新闻 (Security News)</h2>
                <div class="articles-grid" id="news-articles">
                    {"".join([f'''
                    <div class="article-card" data-date="{article['date']}">
                        <div class="article-source">来源: {article['source']}</div>
                        <h3 class="article-title"><a href="{article['url']}" target="_blank">{html.escape(article['title'])}</a></h3>
                        {f'<p class="article-description">{html.escape(truncate_description(article["description"]))}</p>' if article["description"] else ''}
                        <div class="article-date">发布日期: {article['date']}</div>
                    </div>''' for article in news_sorted])}
                </div>
            </div>
        </main>

        <aside class="sidebar">
            <h3>筛选器</h3>
            <div class="filters">
                <div class="filter-group">
                    <label for="date-filter">📅 按日期筛选:</label>
                    <select id="date-filter" onchange="filterByDate()">
                        <option value="">全部日期</option>
                        {''.join([f'<option value="{date}">{date}</option>' for date in sorted_dates])}
                    </select>
                </div>

                <div class="filter-group">
                    <label for="source-filter">🏢 按来源筛选:</label>
                    <select id="source-filter" onchange="filterBySource()">
                        <option value="">全部来源</option>
                    </select>
                </div>

                <div class="filter-group">
                    <label for="search-input">🔍 搜索关键词:</label>
                    <input type="text" id="search-input" placeholder="输入关键词搜索..." onkeyup="filterBySearch()">
                </div>

                <button onclick="clearAllFilters()" style="margin-top: 10px; padding: 8px 16px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer;">清除筛选</button>
            </div>

            <div style="margin-top: 1.5rem;">
                <h4>统计信息</h4>
                <p>总文章数: {len(tech_sorted) + len(news_sorted)}</p>
                <p>技术文章: {len(tech_sorted)}</p>
                <p>安全新闻: {len(news_sorted)}</p>
                <p>更新日期: {datetime.now().strftime('%Y-%m-%d')}</p>
            </div>
        </aside>

        <div class="footer">
            <p>© 2026 <a href="https://github.com/secnotes">SecNotes</a> | <a href="https://github.com/secnotes/secnews">站点源码</a></p>
            <p>安全资讯聚合平台 | 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>数据来源: Sec-Today, 先知社区, Project Zero, Seebug Paper, 腾讯安全, 安全客, 安全内参</p>
            <p>如有侵权，请联系删除</p>
        </div>
    </div>

    <script>
        // Initialize sources filter
        window.onload = function() {{
            const sources = new Set();
            document.querySelectorAll('.article-card').forEach(card => {{
                const source = card.querySelector('.article-source').textContent.replace('来源: ', '');
                sources.add(source);
            }});

            const sourceFilter = document.getElementById('source-filter');
            Array.from(sources).sort().forEach(source => {{
                const option = document.createElement('option');
                option.value = source;
                option.textContent = source;
                sourceFilter.appendChild(option);
            }});

            // Initialize with all articles shown
            updateArticleCounts();
        }};

        function filterByDate() {{
            const dateFilter = document.getElementById('date-filter').value;
            const techCards = document.querySelectorAll('#tech-articles .article-card');
            const newsCards = document.querySelectorAll('#news-articles .article-card');
            let visibleCount = 0;

            // Show/hide tech articles
            techCards.forEach(card => {{
                const cardDate = card.getAttribute('data-date');
                if (dateFilter === '' || cardDate === dateFilter) {{
                    card.style.display = 'flex';
                    visibleCount++;
                }} else {{
                    card.style.display = 'none';
                }}
            }});

            // Show/hide news articles
            newsCards.forEach(card => {{
                const cardDate = card.getAttribute('data-date');
                if (dateFilter === '' || cardDate === dateFilter) {{
                    card.style.display = 'flex';
                    visibleCount++;
                }} else {{
                    card.style.display = 'none';
                }}
            }});

            updateArticleCounts();
        }}

        function filterBySource() {{
            const sourceFilter = document.getElementById('source-filter').value;
            const techCards = document.querySelectorAll('#tech-articles .article-card');
            const newsCards = document.querySelectorAll('#news-articles .article-card');
            let visibleCount = 0;

            // Show/hide tech articles
            techCards.forEach(card => {{
                const cardSource = card.querySelector('.article-source').textContent.replace('来源: ', '');
                if (sourceFilter === '' || cardSource === sourceFilter) {{
                    if (isVisibleByDateFilter(card)) {{
                        card.style.display = 'flex';
                        visibleCount++;
                    }}
                }} else {{
                    card.style.display = 'none';
                }}
            }});

            // Show/hide news articles
            newsCards.forEach(card => {{
                const cardSource = card.querySelector('.article-source').textContent.replace('来源: ', '');
                if (sourceFilter === '' || cardSource === sourceFilter) {{
                    if (isVisibleByDateFilter(card)) {{
                        card.style.display = 'flex';
                        visibleCount++;
                    }}
                }} else {{
                    card.style.display = 'none';
                }}
            }});

            updateArticleCounts();
        }}

        function filterBySearch() {{
            const searchTerm = document.getElementById('search-input').value.toLowerCase();
            const techCards = document.querySelectorAll('#tech-articles .article-card');
            const newsCards = document.querySelectorAll('#news-articles .article-card');
            let visibleCount = 0;

            // Show/hide tech articles
            techCards.forEach(card => {{
                const title = card.querySelector('.article-title').textContent.toLowerCase();
                const description = card.querySelector('.article-description') ?
                    card.querySelector('.article-description').textContent.toLowerCase() : '';
                const source = card.querySelector('.article-source').textContent.toLowerCase();

                const matches = title.includes(searchTerm) ||
                               description.includes(searchTerm) ||
                               source.includes(searchTerm);

                if (matches && isVisibleByDateFilter(card) && isVisibleBySourceFilter(card)) {{
                    card.style.display = 'flex';
                    visibleCount++;
                }} else {{
                    card.style.display = 'none';
                }}
            }});

            // Show/hide news articles
            newsCards.forEach(card => {{
                const title = card.querySelector('.article-title').textContent.toLowerCase();
                const description = card.querySelector('.article-description') ?
                    card.querySelector('.article-description').textContent.toLowerCase() : '';
                const source = card.querySelector('.article-source').textContent.toLowerCase();

                const matches = title.includes(searchTerm) ||
                               description.includes(searchTerm) ||
                               source.includes(searchTerm);

                if (matches && isVisibleByDateFilter(card) && isVisibleBySourceFilter(card)) {{
                    card.style.display = 'flex';
                    visibleCount++;
                }} else {{
                    card.style.display = 'none';
                }}
            }});

            updateArticleCounts();
        }}

        function isVisibleByDateFilter(card) {{
            const dateFilter = document.getElementById('date-filter').value;
            const cardDate = card.getAttribute('data-date');
            return dateFilter === '' || cardDate === dateFilter;
        }}

        function isVisibleBySourceFilter(card) {{
            const sourceFilter = document.getElementById('source-filter').value;
            const cardSource = card.querySelector('.article-source').textContent.replace('来源: ', '');
            return sourceFilter === '' || cardSource === sourceFilter;
        }}

        function clearAllFilters() {{
            document.getElementById('date-filter').value = '';
            document.getElementById('source-filter').value = '';
            document.getElementById('search-input').value = '';

            // Reset all cards to visible
            document.querySelectorAll('.article-card').forEach(card => {{
                card.style.display = 'flex';
            }});

            updateArticleCounts();
        }}

        function updateArticleCounts() {{
            const visibleCards = document.querySelectorAll('.article-card[style*="display: flex"]').length;
            const totalCount = document.querySelectorAll('.article-card').length;

            // Update stats or provide some visual feedback about filtered results
            console.log(`Showing ${{visibleCards}} of ${{totalCount}} articles`);
        }}
    </script>
</body>
</html>"""

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logger.info(f"HTML page generated: {output_file}")


def main():
    aggregator = SecurityNewsAggregator()

    # Scrape all sources
    aggregator.scrape_all_sources()

    # Save raw data
    aggregator.save_articles_json()

    # Create docs directory if it doesn't exist
    os.makedirs('docs', exist_ok=True)
    # Generate HTML page in docs directory
    generate_html(aggregator.articles, output_file='docs/index.html')

    print(f"\n完成！共收集到:")
    print(f"- 技术文章: {len(aggregator.articles['tech'])} 篇")
    print(f"- 新闻: {len(aggregator.articles['news'])} 篇")
    print(f"已生成 docs/index.html 文件")


if __name__ == "__main__":
    main()