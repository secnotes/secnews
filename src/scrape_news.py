#!/usr/bin/env python3
"""
Security News Aggregator
Scrapes cybersecurity news from multiple sources and generates a static HTML page
"""

import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime, timedelta
import os
import json
import logging
from urllib.parse import urljoin, urlparse
import re
import html
import sys

# Import brotli support to enable automatic decompression
try:
    import brotli
    # Install requests-toolbelt to provide Brotli support for requests
    import requests_toolbelt.adapters.appengine
    requests_toolbelt.adapters.appengine.monkeypatch()
except ImportError:
    # On some systems brotli might be available as _brotli
    try:
        import _brotli
        brotli = _brotli
    except ImportError:
        brotli = None
        # If brotli module is not installed, print warning
        import warnings
        warnings.warn("brotli module not found, some sites may not be scraped properly in compressed environments", ImportWarning)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Disable SSL warnings for proxy connections
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Session with headers to mimic a real browser
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
})
session.verify = False  # Ignore SSL errors (useful for proxy connections)

# Proxy configuration (can be set via environment variable or config file)
# Set HTTPS_PROXY environment variable, e.g., export HTTPS_PROXY=https://127.0.0.1:10808
PROXY_URL = os.environ.get('HTTPS_PROXY', os.environ.get('HTTP_PROXY', None))

def get_proxies():
    """Get proxy configuration from environment variable"""
    if PROXY_URL:
        return {
            'http': PROXY_URL,
            'https': PROXY_URL
        }
    return None

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

    def _parse_relative_time(self, time_text):
        """Parse relative time text and return date string (YYYY-MM-DD)"""
        if not time_text:
            return None

        # English patterns
        english_patterns = [
            (r'(\d+)\s*week[s]?\s*ago', 'weeks'),
            (r'(\d+)\s*day[s]?\s*ago', 'days'),
            (r'(\d+)\s*hour[s]?\s*ago', 'hours'),
            (r'(\d+)\s*minute[s]?\s*ago', 'minutes'),
            (r'(\d+)\s*second[s]?\s*ago', 'seconds'),
        ]

        for pattern, unit in english_patterns:
            match = re.search(pattern, time_text, re.IGNORECASE)
            if match:
                quantity = int(match.group(1))
                if unit == 'weeks':
                    past_date = datetime.now() - timedelta(weeks=quantity)
                elif unit == 'days':
                    past_date = datetime.now() - timedelta(days=quantity)
                elif unit == 'hours':
                    past_date = datetime.now() - timedelta(hours=quantity)
                elif unit == 'minutes':
                    past_date = datetime.now() - timedelta(minutes=quantity)
                elif unit == 'seconds':
                    past_date = datetime.now() - timedelta(seconds=quantity)
                return past_date.strftime('%Y-%m-%d')

        # Chinese patterns
        chinese_patterns = [
            (r'(\d+)\s*周\s*之\s*前', 'weeks'),    # "2周之前", "2 周 之前"
            (r'(\d+)\s*周前', 'weeks'),             # "2周前"
            (r'(\d+)\s*天前', 'days'),              # "2天前"
            (r'(\d+)\s*小时前', 'hours'),           # "2小时前"
            (r'(\d+)\s*分钟前', 'minutes'),         # "2分钟前"
            (r'(\d+)\s*秒前', 'seconds'),           # "2秒前"
        ]

        for pattern, unit in chinese_patterns:
            match = re.search(pattern, time_text)
            if match:
                quantity = int(match.group(1))
                if unit == 'weeks':
                    past_date = datetime.now() - timedelta(weeks=quantity)
                elif unit == 'days':
                    past_date = datetime.now() - timedelta(days=quantity)
                elif unit == 'hours':
                    past_date = datetime.now() - timedelta(hours=quantity)
                elif unit == 'minutes':
                    past_date = datetime.now() - timedelta(minutes=quantity)
                elif unit == 'seconds':
                    past_date = datetime.now() - timedelta(seconds=quantity)
                return past_date.strftime('%Y-%m-%d')

        return None

    def _decode_response_content(self, response):
        """
        Decode response content with proper encoding handling
        """
        # In most cases, we can just return the raw content since we've configured
        # the environment to handle compression automatically
        # But we still need to handle the character encoding issues mentioned in the logs

        try:
            # If apparent_encoding is None but we know the content is text,
            # it may need special handling as per the error logs
            if response.apparent_encoding is None and 'text' in response.headers.get('Content-Type', ''):
                # This mirrors the log message seen in the issue
                logger.warning("Some characters could not be decoded, and were replaced with REPLACEMENT CHARACTER")
                # Return content decoded with error replacement
                return response.content.decode('utf-8', errors='replace')

            # Otherwise, just return the content as received (requests should handle compression automatically now)
            return response.content
        except UnicodeDecodeError:
            # Handle the specific case mentioned in the logs
            logger.warning("Some characters could not be decoded, and were replaced with REPLACEMENT CHARACTER")
            return response.content.decode('utf-8', errors='replace')
        except Exception:
            # Fallback to original content
            return response.content

    def scrape_daily_security(self):
        """Scrape https://sec.today/pulses/ for security pulses (tech articles)"""
        logger.info("Scraping Daily Security...")
        try:
            # First, try using cloudscraper which is specifically designed to handle Cloudflare
            try:
                import cloudscraper

                # Create a cloudscraper session which handles Cloudflare challenges automatically
                scraper = cloudscraper.create_scraper(
                    browser={
                        'browser': 'firefox',
                        'platform': 'windows',
                        'mobile': False
                    },
                    disableCloudflareV1=True
                )

                # Set realistic headers for cloudscraper
                scraper.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'max-age=0',
                })

                response = scraper.get("https://sec.today/pulses/", timeout=20)

            except ImportError:
                # Fallback to requests with session approach if cloudscraper is not available
                sec_today_session = requests.Session()
                sec_today_session.verify = False  # Ignore SSL errors

                # Set realistic browser headers
                headers = {
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
                }

                sec_today_session.headers.update(headers)

                # Establish session by getting the main page first
                sec_today_session.get("https://sec.today/", timeout=20)
                time.sleep(2)

                response = sec_today_session.get("https://sec.today/pulses/", timeout=20)

            if response.status_code != 200:
                # If still getting blocked, try cloudscraper as a last resort
                if response.status_code == 403 or response.status_code == 429:
                    try:
                        import cloudscraper

                        scraper = cloudscraper.create_scraper(
                            browser={
                                'browser': 'chrome',
                                'platform': 'windows',
                                'mobile': False
                            }
                        )

                        response = scraper.get("https://sec.today/pulses/", timeout=30)
                    except ImportError:
                        logger.error("All methods failed: Cloudflare blocking requests and cloudscraper not available.")
                        return

                if response.status_code != 200:
                    logger.error(f"Failed to fetch sec.today content, status code: {response.status_code}")
                    return

            # Parse the successful response
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

                        # Try multiple methods to extract date
                        date_found = False

                        # Method 1: Look for <time> tag with datetime attribute
                        time_tag = card.find('time')
                        if time_tag:
                            datetime_attr = time_tag.get('datetime')
                            if datetime_attr:
                                try:
                                    # Try ISO format first
                                    parsed_date = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00').split('+')[0])
                                    date = parsed_date.strftime('%Y-%m-%d')
                                    date_found = True
                                    logger.debug(f"Found date from time tag datetime attr: {date}")
                                except ValueError:
                                    pass
                            if not date_found:
                                time_text = time_tag.get_text(strip=True)
                                # Try parsing time text
                                parsed_date = self._parse_relative_time(time_text)
                                if parsed_date:
                                    date = parsed_date
                                    date_found = True

                        # Method 2: Look for text containing relative time (English format)
                        if not date_found:
                            card_text = card.get_text()
                            # English relative time patterns (with or without space)
                            english_patterns = [
                                r'(\d+)\s*week[s]?\s*ago',     # "2 weeks ago", "1 week ago"
                                r'(\d+)\s*day[s]?\s*ago',      # "2 days ago", "2day ago"
                                r'(\d+)\s*hour[s]?\s*ago',     # "2 hours ago"
                                r'(\d+)\s*minute[s]?\s*ago',   # "2 minutes ago"
                                r'(\d+)\s*second[s]?\s*ago',   # "2 seconds ago"
                            ]
                            for pattern in english_patterns:
                                match = re.search(pattern, card_text, re.IGNORECASE)
                                if match:
                                    quantity = int(match.group(1))
                                    if 'week' in pattern.lower():
                                        past_date = datetime.now() - timedelta(weeks=quantity)
                                    elif 'day' in pattern.lower():
                                        past_date = datetime.now() - timedelta(days=quantity)
                                    elif 'hour' in pattern.lower():
                                        past_date = datetime.now() - timedelta(hours=quantity)
                                    elif 'minute' in pattern.lower():
                                        past_date = datetime.now() - timedelta(minutes=quantity)
                                    elif 'second' in pattern.lower():
                                        past_date = datetime.now() - timedelta(seconds=quantity)
                                    date = past_date.strftime('%Y-%m-%d')
                                    date_found = True
                                    logger.debug(f"Found date from English pattern: {date}")
                                    break

                        # Method 3: Chinese relative time patterns
                        if not date_found:
                            card_text = card.get_text()
                            chinese_patterns = [
                                (r'(\d+)\s*周\s*之\s*前', 'weeks'),    # "2周之前", "2 周 之前"
                                (r'(\d+)\s*周前', 'weeks'),             # "2周前"
                                (r'(\d+)\s*天前', 'days'),              # "2天前"
                                (r'(\d+)\s*小时前', 'hours'),           # "2小时前"
                                (r'(\d+)\s*分钟前', 'minutes'),         # "2分钟前"
                                (r'(\d+)\s*秒前', 'seconds'),           # "2秒前"
                            ]
                            for pattern, unit in chinese_patterns:
                                match = re.search(pattern, card_text)
                                if match:
                                    quantity = int(match.group(1))
                                    if unit == 'weeks':
                                        past_date = datetime.now() - timedelta(weeks=quantity)
                                    elif unit == 'days':
                                        past_date = datetime.now() - timedelta(days=quantity)
                                    elif unit == 'hours':
                                        past_date = datetime.now() - timedelta(hours=quantity)
                                    elif unit == 'minutes':
                                        past_date = datetime.now() - timedelta(minutes=quantity)
                                    elif unit == 'seconds':
                                        past_date = datetime.now() - timedelta(seconds=quantity)
                                    date = past_date.strftime('%Y-%m-%d')
                                    date_found = True
                                    logger.debug(f"Found date from Chinese pattern: {date}")
                                    break

                        # Method 4: Look for explicit date patterns as backup
                        if not date_found:
                            card_text = card.get_text()
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
                                            date_found = True
                                            break
                                        except ValueError:
                                            try:
                                                parsed_date = datetime.strptime(extracted_date, '%m/%d/%Y')
                                                date = parsed_date.strftime('%Y-%m-%d')
                                                date_found = True
                                                break
                                            except ValueError:
                                                pass
                                    else:
                                        date = extracted_date
                                        date_found = True
                                        break

                        if not date_found:
                            logger.debug(f"No date found for article '{title[:50]}...', using today's date")

                        # Add to tech articles
                        article = {
                            'title': title,
                            'url': url,
                            'source': 'Sec-Today',
                            'description': description,
                            'date': date,
                            'category': 'tech'
                        }
                        self.articles['tech'].append(article)
                except Exception as e:
                    continue

            logger.info(f"Completed scraping Daily Security, added {len(self.articles['tech'])} tech articles")
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
                                'source': '腾讯安全',
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
                                'source': '先知社区',
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
            # Create a new session
            pz_session = requests.Session()
            pz_session.verify = False  # Ignore SSL errors
            pz_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })

            # Set proxy from environment if available
            proxies = get_proxies()
            if proxies:
                pz_session.proxies = proxies

            response = pz_session.get("https://projectzero.google/", timeout=20)
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
        """Scrape https://www.anquanke.com/ for security news by parsing <li class="item"> elements"""
        logger.info("Scraping Anquanke...")
        try:
            # Request the main page
            response = session.get("https://www.anquanke.com/", timeout=20)
            response.raise_for_status()

            # Parse HTML content
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find all list items with class "item" as specified
            item_elements = soup.find_all('li', class_='item')

            for item in item_elements:
                try:
                    # Extract title - look for title inside .item-main .title a
                    title_elem = item.select_one('.item-main .title a')

                    if title_elem:
                        title = self.decode_html_entities(title_elem.get_text(strip=True))

                        # Get URL from the same anchor tag
                        url = title_elem.get('href')
                        if url:
                            if url.startswith('/'):
                                url = f"https://www.anquanke.com{url}"
                            elif not url.startswith('http'):
                                url = urljoin("https://www.anquanke.com/", url)
                        else:
                            # Generate a placeholder URL if none found
                            url = f"https://www.anquanke.com/"
                    else:
                        # Skip items without titles
                        continue

                    # Extract description if available - look for desc class
                    desc_elem = item.select_one('.desc.g-line2')
                    description = self.decode_html_entities(desc_elem.get_text(strip=True)) if desc_elem else ''

                    # Extract date - look for the time element
                    date_elem = item.select_one('.bottom-item.bottom-item-time')
                    date = ''
                    if date_elem:
                        date_str = date_elem.get_text(strip=True)
                        # Clean date string - extract the date part from "2026-02-25 17:11:48"
                        date_part = date_str.split()[0]  # Get just the date part

                        # Try to parse date in various formats
                        for fmt in ['%Y-%m-%d', '%Y.%m.%d', '%Y/%m/%d']:
                            try:
                                parsed_date = datetime.strptime(date_part, fmt)
                                date = parsed_date.strftime('%Y-%m-%d')
                                break
                            except ValueError:
                                continue

                        # If date parsing fails, try a different approach
                        if not date:
                            # Extract date-like pattern using regex
                            date_match = re.search(r'\d{4}[-/.]\d{1,2}[-/.]\d{1,2}', date_str)
                            if date_match:
                                date_part = date_match.group(0)
                                date_part = date_part.replace('/', '-').replace('.', '-')
                                try:
                                    parsed_date = datetime.strptime(date_part, '%Y-%m-%d')
                                    date = parsed_date.strftime('%Y-%m-%d')
                                except ValueError:
                                    date = datetime.now().strftime('%Y-%m-%d')

                    # Use today's date if no date was found
                    if not date:
                        date = datetime.now().strftime('%Y-%m-%d')

                    # Add to news articles
                    article = {
                        'title': title,
                        'url': url,
                        'source': '安全客',
                        'description': description,
                        'date': date,
                        'category': 'news'
                    }
                    self.articles['news'].append(article)

                except Exception as e:
                    logger.warning(f"Error processing Anquanke item: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error scraping Anquanke: {str(e)}")

    def scrape_freebuf(self):
        """Scrape https://www.freebuf.com/feed RSS feed for security news"""
        logger.info("Scraping FreeBuf RSS feed...")
        try:
            import xml.etree.ElementTree as ET

            # Fetch RSS feed
            response = session.get('https://www.freebuf.com/feed', proxies=get_proxies(), timeout=20)
            response.raise_for_status()

            # Parse XML
            root = ET.fromstring(response.content)

            # RSS namespace
            namespaces = {'rss': 'http://purl.org/rss/1.0/modules/content/'}

            articles_found = 0

            # Find all items in RSS feed
            items = root.findall('.//item')
            logger.info(f"Found {len(items)} items in FreeBuf RSS feed")

            for item in items[:30]:  # Limit to 30 articles
                try:
                    # Extract basic elements
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    desc_elem = item.find('description')
                    pub_date_elem = item.find('pubDate')

                    if title_elem is None or link_elem is None:
                        continue

                    title = title_elem.text
                    url = link_elem.text

                    # Skip non-article links
                    if not title or len(title) < 5 or '/tag/' in url or '/author/' in url:
                        continue

                    # Clean description (remove HTML tags)
                    description = ''
                    if desc_elem is not None and desc_elem.text:
                        # Simple HTML tag removal
                        import re
                        description = re.sub(r'<[^>]+>', '', desc_elem.text)
                        description = description.strip()[:200]

                    # Parse date
                    date = datetime.now().strftime('%Y-%m-%d')
                    if pub_date_elem is not None and pub_date_elem.text:
                        try:
                            # Parse RFC 2822 date format
                            from email.utils import parsedate_to_datetime
                            dt = parsedate_to_datetime(pub_date_elem.text)
                            date = dt.strftime('%Y-%m-%d')
                        except:
                            pass

                    article = {
                        'title': self.decode_html_entities(title),
                        'url': url,
                        'source': 'FreeBuf',
                        'description': description,
                        'date': date,
                        'category': 'news'
                    }
                    self.articles['news'].append(article)
                    articles_found += 1

                except Exception as e:
                    logger.warning(f"Error processing FreeBuf article: {str(e)}")
                    continue

            logger.info(f"Found {articles_found} FreeBuf articles from RSS feed")

        except Exception as e:
            logger.error(f"Error scraping FreeBuf: {str(e)}")

        except ImportError:
            logger.warning("Playwright not available, skipping FreeBuf")
        except Exception as e:
            logger.error(f"Error scraping FreeBuf: {str(e)}")

        except Exception as e:
            logger.error(f"Error scraping FreeBuf RSS: {str(e)}")

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
                                    'source': '安全内参',
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
            seebug_session.verify = False  # Ignore SSL errors

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
                                    'source': 'Seebug Paper',
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
                                        'source': 'Seebug Paper',
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

    def scrape_kanxue(self):
        """Scrape https://www.kanxue.com/ for security tech articles"""
        logger.info("Scraping KanXue...")
        try:
            # Create a session with appropriate headers for KanXue
            kanxue_session = requests.Session()
            kanxue_session.verify = False  # Ignore SSL errors
            kanxue_session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            })

            response = kanxue_session.get("https://www.kanxue.com/", timeout=20)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Find articles in the specified div with class "media p-3 home_article bg-white"
            article_elements = soup.find_all(class_='media p-3 home_article bg-white')

            if article_elements:
                logger.info(f"Found {len(article_elements)} articles on KanXue")

                for element in article_elements:
                    try:
                        # Find the article link and title
                        link_elem = element.find('a', class_='article_url')
                        if not link_elem:
                            # Fallback: find any link in the element
                            link_elem = element.find('a', href=True)

                        if link_elem:
                            # Extract title from h4 with class article_title or from link text
                            title_elem = element.find('h4', class_='article_title')
                            if title_elem:
                                title = self.decode_html_entities(title_elem.get_text(strip=True))
                            else:
                                # Use link text if no specific title element found
                                title = self.decode_html_entities(link_elem.get_text(strip=True))

                            if not title:
                                continue  # Skip if no title found

                            # Get the URL
                            url = link_elem.get('href')
                            if url:
                                if not url.startswith('http'):
                                    if url.startswith('//'):
                                        url = 'https:' + url
                                    else:
                                        url = urljoin("https://www.kanxue.com/", url)

                            # Extract description from article-excerpt div
                            excerpt_elem = element.find('div', class_='article-excerpt')
                            description = ''
                            if excerpt_elem:
                                description = self.decode_html_entities(excerpt_elem.get_text(strip=True)[:500] + "..." if len(excerpt_elem.get_text(strip=True)) > 500 else excerpt_elem.get_text(strip=True))

                            # Extract date if available
                            date = datetime.now().strftime('%Y-%m-%d')  # Default fallback

                            # Look for relative time in span elements (format: "4小时前", "1天前")
                            import re
                            from datetime import timedelta

                            # Find all span elements and look for relative time text
                            span_elems = element.find_all('span')
                            for span_elem in span_elems:
                                time_text = span_elem.get_text(strip=True)

                                # Match relative time patterns: "X小时前", "X天前", "X分钟前", "昨天", "刚刚"
                                relative_patterns = [
                                    (r'(\d+)\s*小时前', 'hours'),
                                    (r'(\d+)\s*天前', 'days'),
                                    (r'(\d+)\s*分钟前', 'minutes'),
                                    (r'昨天', 'yesterday'),
                                    (r'刚刚|刚刚发布', 'now'),
                                ]

                                for pattern, unit in relative_patterns:
                                    rel_match = re.search(pattern, time_text)
                                    if rel_match:
                                        if unit == 'hours':
                                            quantity = int(rel_match.group(1))
                                            past_date = datetime.now() - timedelta(hours=quantity)
                                            date = past_date.strftime('%Y-%m-%d')
                                        elif unit == 'days':
                                            quantity = int(rel_match.group(1))
                                            past_date = datetime.now() - timedelta(days=quantity)
                                            date = past_date.strftime('%Y-%m-%d')
                                        elif unit == 'minutes':
                                            # Minutes ago is still today
                                            date = datetime.now().strftime('%Y-%m-%d')
                                        elif unit == 'yesterday':
                                            past_date = datetime.now() - timedelta(days=1)
                                            date = past_date.strftime('%Y-%m-%d')
                                        elif unit == 'now':
                                            date = datetime.now().strftime('%Y-%m-%d')
                                        logger.debug(f"KanXue date from '{time_text}': {date}")
                                        break

                                # Also check for specific date formats as fallback
                                # Support both single-digit and double-digit month/day (e.g., "2026-5-22" or "2026-05-22")
                                date_patterns = [
                                    r'(\d{4}-\d{1,2}-\d{1,2})',
                                    r'(\d{4}/\d{1,2}/\d{1,2})',
                                ]
                                for pattern in date_patterns:
                                    date_match = re.search(pattern, time_text)
                                    if date_match:
                                        extracted_date = date_match.group(1).replace('/', '-')
                                        # Parse with flexible format (handle single-digit month/day)
                                        try:
                                            # Try strict format first (YYYY-MM-DD)
                                            parsed_date = datetime.strptime(extracted_date, '%Y-%m-%d')
                                            date = parsed_date.strftime('%Y-%m-%d')
                                            break
                                        except ValueError:
                                            try:
                                                # Fallback: parse parts manually and format
                                                parts = extracted_date.split('-')
                                                if len(parts) == 3:
                                                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                                                    parsed_date = datetime(year, month, day)
                                                    date = parsed_date.strftime('%Y-%m-%d')
                                                    break
                                            except (ValueError, IndexError):
                                                continue

                            # Add to tech articles as specified (KanXue is tech-focused)
                            article = {
                                'title': title,
                                'url': url,
                                'source': '看雪论坛',
                                'description': description,
                                'date': date,
                                'category': 'tech'  # KanXue is technology-focused
                            }
                            self.articles['tech'].append(article)

                    except Exception as e:
                        logger.warning(f"Error processing KanXue article: {str(e)}")
                        continue
            else:
                logger.info("Could not find articles with class 'media p-3 home_article bg-white' on KanXue")

        except requests.exceptions.RequestException as e:
            logger.warning(f"Network error while scraping KanXue: {str(e)}")
        except Exception as e:
            logger.error(f"Error scraping KanXue: {str(e)}")

    def scrape_the_hacker_news(self):
        """Scrape https://thehackernews.com/ for security news"""
        logger.info("Scraping The Hacker News...")

        import time
        import random

        # Multiple User-Agent strings to rotate
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.109 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]

        # Create a session to handle cookies and headers consistently
        thackernews_session = requests.Session()
        thackernews_session.verify = False  # Ignore SSL errors
        thackernews_session.headers.update({
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'DNT': '1',
            'Referer': 'https://www.google.com/'
        })

        # 随机延时，模拟人类行为
        time.sleep(random.uniform(1, 2))

        try:
            response = thackernews_session.get("https://thehackernews.com/", timeout=10)

            if response.status_code == 200:
                logger.info("Successfully connected to The Hacker News")

                # Use our helper function to properly decode response content
                content = self._decode_response_content(response)
                soup = BeautifulSoup(content, 'html.parser')

                # Find articles in the blog-posts container
                blog_posts_div = soup.find('div', class_='blog-posts clear')

                if blog_posts_div:
                    # Find all body-post elements (article cards)
                    body_posts = blog_posts_div.find_all('div', class_='body-post')

                    for body_post in body_posts:
                        try:
                            # Get the link
                            link_elem = body_post.find('a', class_='story-link')
                            if link_elem:
                                url = link_elem.get('href')

                                # Find home-right section containing title, date, and description
                                home_right = body_post.find('div', class_='home-right')
                                if home_right:
                                    # Get title
                                    title_elem = home_right.find('h2', class_='home-title')
                                    title = self.decode_html_entities(title_elem.get_text(strip=True)) if title_elem else 'No Title'

                                    # Get date from item-label
                                    date = datetime.now().strftime('%Y-%m-%d')  # Default
                                    item_label = home_right.find('div', class_='item-label')
                                    if item_label:
                                        date_text = item_label.get_text(strip=True)
                                        # Extract date like "May 13, 2026..." -> "May 13, 2026"
                                        import re
                                        # Remove icon characters, keep date format
                                        date_text = re.sub(r'[^\w\s,]', '', date_text).strip()
                                        # Split by whitespace and take first 3 parts (Month Day, Year)
                                        parts = date_text.split()
                                        if len(parts) >= 3:
                                            date_str = ' '.join(parts[:3])  # "May 13, 2026"
                                            parsed_date = self._parse_date_string(date_str)
                                            if parsed_date:
                                                date = parsed_date

                                    # Get description from home-desc
                                    description = ''
                                    desc_elem = home_right.find('div', class_='home-desc')
                                    if desc_elem:
                                        description = self.decode_html_entities(desc_elem.get_text(strip=True))

                                    if title and url:
                                        article = {
                                            'title': title,
                                            'url': url,
                                            'source': 'The Hacker News',
                                            'description': description,
                                            'date': date,
                                            'category': 'news'
                                        }
                                        self.articles['news'].append(article)

                        except Exception as e:
                            logger.warning(f"Error processing The Hacker News article: {str(e)}")
                            continue
                else:
                    logger.info("Could not find 'blog-posts clear' div in The Hacker News")

            else:
                logger.warning(f"Failed to fetch The Hacker News: HTTP {response.status_code}")

        except requests.exceptions.RequestException as e:
            logger.warning(f"Network error while scraping The Hacker News: {str(e)}")
        except Exception as e:
            logger.error(f"Error scraping The Hacker News: {str(e)}")

    def _parse_date_string(self, date_str):
        """Parse various date string formats and return YYYY-MM-DD format"""
        if not date_str:
            return None

        # Common date formats to try
        date_formats = [
            '%Y-%m-%d',           # 2026-05-13
            '%Y/%m/%d',           # 2026/05/13
            '%m/%d/%Y',           # 05/13/2026
            '%d/%m/%Y',           # 13/05/2026
            '%B %d, %Y',          # May 13, 2026
            '%b %d, %Y',          # May 13, 2026 (short month)
            '%d %B %Y',           # 13 May 2026
            '%d %b %Y',           # 13 May 2026 (short month)
            '%Y-%m-%dT%H:%M:%S',  # ISO format without timezone
            '%Y-%m-%dT%H:%M:%SZ', # ISO format with Z
            '%Y-%m-%dT%H:%M:%S%z', # ISO format with timezone
        ]

        # Clean the date string
        date_str = date_str.strip()

        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                return parsed_date.strftime('%Y-%m-%d')
            except ValueError:
                continue

        # Try to extract date pattern using regex
        # Look for patterns like "May 12, 2026" or "2026-05-12"
        import re
        patterns = [
            r'(\d{4}-\d{2}-\d{2})',                    # 2026-05-12
            r'(\d{4}/\d{2}/\d{2})',                    # 2026/05/12
            r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})',        # May 12, 2026
            r'(\d{1,2}\s+[A-Za-z]+\s+\d{4})',          # 12 May 2026
        ]

        for pattern in patterns:
            match = re.search(pattern, date_str)
            if match:
                extracted = match.group(1)
                # Try parsing the extracted date
                for fmt in date_formats:
                    try:
                        parsed_date = datetime.strptime(extracted, fmt)
                        return parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                        continue

        return None

    def scrape_security_week(self):
        """Scrape https://www.securityweek.com/feed (RSS) for security news"""
        logger.info("Scraping SecurityWeek RSS feed...")

        from email.utils import parsedate_to_datetime

        try:
            # Use Playwright to bypass Cloudflare
            from playwright.sync_api import sync_playwright
            import time

            with sync_playwright() as p:
                # Prefer system Google Chrome (no bundled-Chromium download required when installed);
                # fall back to bundled Chromium if Chrome is not present (e.g. minimal CI runners).
                def _launch_browser(extra_args=None):
                    args = ['--disable-blink-features=AutomationControlled']
                    if extra_args:
                        args.extend(extra_args)
                    try:
                        browser = p.chromium.launch(headless=True, channel='chrome', args=args)
                        logger.info("SecurityWeek: using system Google Chrome")
                        return browser
                    except Exception as e:
                        logger.info(
                            f"SecurityWeek: system Chrome unavailable ({type(e).__name__}: {e}), "
                            f"falling back to bundled Chromium"
                        )
                        return p.chromium.launch(headless=True, args=args)

                browser = _launch_browser()
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1280, 'height': 720}
                )
                page = context.new_page()
                page.add_init_script('Object.defineProperty(navigator, "webdriver", { get: () => undefined });')

                # Set proxy if available
                proxies = get_proxies()
                if proxies:
                    proxy_server = PROXY_URL.replace('https://', '').replace('http://', '')
                    logger.info(f"Using proxy for SecurityWeek: {proxy_server}")
                    # Relaunch with proxy
                    browser.close()
                    browser = _launch_browser(extra_args=[f'--proxy-server={proxy_server}'])
                    context = browser.new_context(
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        viewport={'width': 1280, 'height': 720}
                    )
                    page = context.new_page()
                    page.add_init_script('Object.defineProperty(navigator, "webdriver", { get: () => undefined });')

                # Navigate to RSS feed
                page.goto('https://www.securityweek.com/feed', timeout=60000)
                time.sleep(2)

                # Get page content (RSS XML)
                # The browser renders RSS as text inside a <pre> tag, so we need to extract the inner text
                pre_element = page.query_selector('pre')
                if pre_element:
                    content = pre_element.inner_text()
                else:
                    content = page.content()
                browser.close()

            # Parse RSS XML
            soup = BeautifulSoup(content, 'xml')

            # Find all items in RSS feed
            items = soup.find_all('item')
            logger.info(f"Found {len(items)} items in SecurityWeek RSS feed")

            for item in items:
                try:
                    title_elem = item.find('title')
                    link_elem = item.find('link')
                    desc_elem = item.find('description')
                    pub_date_elem = item.find('pubDate')

                    if title_elem and link_elem:
                        title = self.decode_html_entities(title_elem.text.strip())
                        url = link_elem.text.strip()

                        # Extract description
                        description = ''
                        if desc_elem:
                            desc_text = desc_elem.text.strip()
                            desc_soup = BeautifulSoup(desc_text, 'html.parser')
                            description = desc_soup.get_text(strip=True)[:200]
                            if len(desc_soup.get_text(strip=True)) > 200:
                                description += "..."

                        # Extract date
                        date = datetime.now().strftime('%Y-%m-%d')
                        if pub_date_elem:
                            pub_date_text = pub_date_elem.text.strip()
                            try:
                                parsed_date = parsedate_to_datetime(pub_date_text)
                                date = parsed_date.strftime('%Y-%m-%d')
                            except:
                                date_match = re.search(r'(\d{1,2})\s+(\w+)\s+(\d{4})', pub_date_text)
                                if date_match:
                                    day = date_match.group(1)
                                    month_name = date_match.group(2)
                                    year = date_match.group(3)
                                    months = {'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                                              'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12}
                                    if month_name in months:
                                        date = f"{year}-{months[month_name]:02d}-{int(day):02d}"

                        article = {
                            'title': title,
                            'url': url,
                            'source': 'SecurityWeek',
                            'description': description,
                            'date': date,
                            'category': 'news'
                        }
                        self.articles['news'].append(article)

                except Exception as e:
                    logger.warning(f"Error processing SecurityWeek RSS item: {str(e)}")
                    continue

            logger.info(f"Found {len([a for a in self.articles['news'] if a['source'] == 'SecurityWeek'])} SecurityWeek articles")

        except ImportError:
            logger.warning("Playwright not available, skipping SecurityWeek")
        except Exception as e:
            logger.error(f"Error scraping SecurityWeek: {str(e)}")

    def scrape_unsafe_sh(self):
        """Scrape https://unsafe.sh/ for security news - only articles within last 2 days"""
        logger.info("Scraping Unsafe.sh...")

        def get_original_url(detail_url):
            """Fetch detail page and extract original source URL"""
            try:
                detail_response = session.get(detail_url, timeout=15, proxies=proxies)
                if detail_response.status_code == 200:
                    detail_content = self._decode_response_content(detail_response)
                    # Ensure content is string
                    if isinstance(detail_content, bytes):
                        detail_content = detail_content.decode('utf-8', errors='ignore')
                    # Look for "文章来源:" followed by URL
                    source_match = re.search(r'文章来源:\s*(https?://[^\s<]+)', detail_content)
                    if source_match:
                        return source_match.group(1)
            except Exception as e:
                logger.warning(f"Error fetching detail page {detail_url}: {str(e)}")
            return None

        try:
            proxies = get_proxies()

            # Scrape first 5 pages to ensure we get recent articles
            for page_num in range(1, 6):
                url = f"https://unsafe.sh/?page={page_num}" if page_num > 1 else "https://unsafe.sh/"
                response = session.get(url, timeout=30, proxies=proxies)
                time.sleep(1)  # Rate limiting

                if response.status_code == 200:
                    content = self._decode_response_content(response)
                    soup = BeautifulSoup(content, 'html.parser')

                    # Find all article links with class "paper_list"
                    articles = soup.find_all('a', class_='paper_list')

                    for article_link in articles:
                        try:
                            title = self.decode_html_entities(article_link.text.strip())
                            href = article_link.get('href', '')

                            if not title or not href or len(title) < 10:
                                continue

                            # Build detail page URL
                            detail_url = f"https://unsafe.sh{href}" if href.startswith('/') else href

                            # Find date - look for the date pattern near the article
                            parent_td = article_link.find_parent('td')
                            if parent_td:
                                parent_text = parent_td.get_text()
                                date_match = re.search(r'(\d{4}-\d{1,2}-\d{1,2})\s+\d{1,2}:\d{1,2}:\d{1,2}', parent_text)
                                if date_match:
                                    date_str = date_match.group(1)
                                    try:
                                        parts = date_str.split('-')
                                        year = int(parts[0])
                                        month = int(parts[1])
                                        day = int(parts[2])
                                        article_date = datetime(year, month, day)
                                    except:
                                        article_date = datetime.now()
                                else:
                                    article_date = datetime.now()
                            else:
                                article_date = datetime.now()

                            date = article_date.strftime('%Y-%m-%d')

                            # Filter: only keep articles within last 2 days
                            two_days_ago = datetime.now() - timedelta(days=2)
                            if article_date < two_days_ago:
                                continue

                            # Fetch detail page to get original URL
                            article_url = get_original_url(detail_url)
                            if not article_url:
                                article_url = detail_url  # Fallback to internal link

                            time.sleep(0.5)  # Rate limiting for detail pages

                            # Get description
                            description = ""
                            if parent_td:
                                desc_span = parent_td.find('span', class_='d-block small opacity-50')
                                if desc_span:
                                    desc_text = desc_span.get_text(strip=True)
                                    desc_match = re.search(r'^(.*?)\s*\d{4}-\d{1,2}-\d{1,2}', desc_text)
                                    if desc_match:
                                        description = desc_match.group(1).strip()

                            if not description:
                                description = title[:100] + "..." if len(title) > 100 else title

                            article = {
                                'title': title,
                                'url': article_url,
                                'source': 'Unsafe.sh',
                                'description': description,
                                'date': date,
                                'category': 'news'
                            }
                            self.articles['news'].append(article)

                        except Exception as e:
                            logger.warning(f"Error processing Unsafe.sh article: {str(e)}")
                            continue

                    logger.info(f"Found articles on Unsafe.sh page {page_num}")

        except Exception as e:
            logger.error(f"Error scraping Unsafe.sh: {str(e)}")

    def scrape_all_sources(self, include_unsafe=False):
        """Scrape all security news sources

        Args:
            include_unsafe: If True, also scrape Unsafe.sh (default: False)
        """
        logger.info("Starting to scrape all security news sources...")

        # Tech-focused sources
        self.scrape_daily_security()
        self.scrape_tencent_security()
        self.scrape_xz_aliyun()
        self.scrape_project_zero()
        # self.scrape_seebug_paper()  # Temporarily disabled due to Aliyun WAF protection (521 error)
        self.scrape_kanxue()

        # News-focused sources
        self.scrape_anquanke()
        self.scrape_freebuf()
        self.scrape_secrss()
        self.scrape_the_hacker_news()
        self.scrape_security_week()

        # Unsafe.sh crawler (only when explicitly enabled)
        if include_unsafe:
            self.scrape_unsafe_sh()

        # Remove duplicates based on URL
        self.remove_duplicates()

        # Filter articles to keep only those published within the last 30 days
        self.filter_recent_articles(days=30)

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

    def filter_recent_articles(self, days=30):
        """Filter articles to keep only those published within the specified number of days"""
        from datetime import datetime, timedelta

        logger.info(f"Filtering articles to keep only those published within the last {days} days...")

        cutoff_date = datetime.now() - timedelta(days=days)

        # Filter tech articles
        filtered_tech = []
        for article in self.articles['tech']:
            try:
                # Parse the article date
                article_date = datetime.strptime(article['date'], '%Y-%m-%d')

                # Keep only articles newer than cutoff date
                if article_date >= cutoff_date:
                    filtered_tech.append(article)
                else:
                    logger.debug(f"Removing old tech article: {article['title']} (published on {article['date']})")
            except ValueError:
                # If date parsing fails, keep the article to be safe
                logger.warning(f"Could not parse date for tech article: {article['date']}, keeping article")
                filtered_tech.append(article)

        # Filter news articles
        filtered_news = []
        for article in self.articles['news']:
            try:
                # Parse the article date
                article_date = datetime.strptime(article['date'], '%Y-%m-%d')

                # Keep only articles newer than cutoff date
                if article_date >= cutoff_date:
                    filtered_news.append(article)
                else:
                    logger.debug(f"Removing old news article: {article['title']} (published on {article['date']})")
            except ValueError:
                # If date parsing fails, keep the article to be safe
                logger.warning(f"Could not parse date for news article: {article['date']}, keeping article")
                filtered_news.append(article)

        original_counts = {
            'tech': len(self.articles['tech']),
            'news': len(self.articles['news'])
        }

        self.articles['tech'] = filtered_tech
        self.articles['news'] = filtered_news

        filtered_counts = {
            'tech': len(self.articles['tech']),
            'news': len(self.articles['news'])
        }

        logger.info(f"Article filtering completed: {original_counts['tech']} -> {filtered_counts['tech']} tech articles, {original_counts['news']} -> {filtered_counts['news']} news articles")

    def get_recent_articles(self, days=2):
        """Get articles from the last N days"""
        cutoff_date = datetime.now() - timedelta(days=days)
        recent_articles = []

        for article in self.articles['tech'] + self.articles['news']:
            try:
                article_date = datetime.strptime(article['date'], '%Y-%m-%d')
                if article_date >= cutoff_date:
                    recent_articles.append(article)
            except ValueError:
                # Include article if date parsing fails
                recent_articles.append(article)

        logger.info(f"Found {len(recent_articles)} articles from the last {days} days")
        return recent_articles

    def ai_curate_articles(self, days=2, api_key=None, model=None, base_url=None):
        """Use AI to analyze and categorize recent articles

        Args:
            days: Number of days to look back for articles (default: 2)
            api_key: AI API key (optional, uses env var if not provided)
            model: AI model name (optional, uses env var if not provided)
            base_url: API base URL (optional, auto-inferred if not provided)

        Returns:
            Dict with categorized articles, or None if AI analysis fails
        """
        from ai_provider import get_ai_provider

        try:
            # Get recent articles
            recent_articles = self.get_recent_articles(days)

            if not recent_articles:
                logger.warning("No recent articles to analyze")
                return None

            # Initialize AI provider
            ai_provider = get_ai_provider(api_key=api_key, model=model, base_url=base_url)

            logger.info(f"Starting AI analysis of {len(recent_articles)} articles...")

            # Analyze articles
            curated_result = ai_provider.analyze_articles(recent_articles)

            logger.info(f"AI analysis completed: categorized articles into {len(curated_result.get('categories', {}))} categories")

            return curated_result

        except ValueError as e:
            logger.warning(f"AI curation skipped: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error during AI curation: {str(e)}")
            return None

    def save_ai_curated_json(self, curated_data, filename='ai_curated.json'):
        """Save AI curated data to a JSON file"""
        if not curated_data:
            logger.warning("No AI curated data to save")
            return

        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filename)

        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(curated_data, f, ensure_ascii=False, indent=2)

        logger.info(f"AI curated data saved to {full_path}")

    def save_articles_json(self, filename='articles.json'):
        """Save articles to a JSON file"""
        import os
        # Create full path relative to the script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        full_path = os.path.join(script_dir, filename)
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)
        logger.info(f"Articles saved to {full_path}")

    def load_articles_json(self, filename='articles.json'):
        """Load articles from a JSON file"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                self.articles = json.load(f)
            logger.info(f"Articles loaded from {filename}")
        except FileNotFoundError:
            logger.info(f"{filename} not found, starting with empty articles")
            self.articles = {'tech': [], 'news': []}


def _generate_ai_curated_html(ai_curated):
    """Generate HTML for AI curated view"""
    if not ai_curated:
        return '<div class="no-ai-data"><p>🤖 AI精选数据暂未生成</p></div>'

    categories_html = []
    category_icons = {
        '漏洞研究': '🐛',
        '移动安全': '📱',
        'AI安全': '🤖',
        '威胁情报': '🔍',
        '安全工具': '🔧',
        '云安全': '☁️',
        '其他重要': '⭐',
    }

    categories = ai_curated.get('categories', {})
    for category_name, articles in categories.items():
        if not articles:
            continue

        icon = category_icons.get(category_name, '📌')
        articles_html = []

        for article in articles:
            title = article.get('title', 'No Title')
            url = article.get('url', '')
            source = article.get('source', '')
            date = article.get('date', '')
            reason = article.get('reason', '')

            articles_html.append(f'''
            <div class="ai-article">
                <div class="ai-article-title">
                    <a href="{url}" target="_blank">{html.escape(title)}</a>
                </div>
                <div class="ai-meta">
                    <span>来源: {source}</span>
                    <span>日期: {date}</span>
                </div>
                {f'<div class="ai-article-reason">💡 推荐理由: {html.escape(reason)}</div>' if reason else ''}
            </div>''')

        categories_html.append(f'''
        <div class="ai-category">
            <h3 class="ai-category-title">{icon} {category_name}</h3>
            {"".join(articles_html)}
        </div>''')

    summary = ai_curated.get('summary', '')
    analysis_date = ai_curated.get('analysis_date', '')
    total_analyzed = ai_curated.get('total_analyzed', 0)

    result_html = f'''
    <div class="ai-summary">
        <h3>🤖 AI智能分析 <span class="model-badge" title="本批次 AI 精选所用模型">{html.escape(ai_curated.get('model', 'unknown'))}</span></h3>
        <div class="ai-summary-text">{html.escape(summary)}</div>
    </div>
    {"".join(categories_html)}
    '''

    return result_html


def _generate_ai_category_nav(ai_curated):
    """Generate category navigation for AI sidebar"""
    if not ai_curated:
        return ''

    category_icons = {
        '漏洞研究': '🐛',
        '移动安全': '📱',
        'AI安全': '🤖',
        '威胁情报': '🔍',
        '安全工具': '🔧',
        '云安全': '☁️',
        '其他重要': '⭐',
    }

    categories = ai_curated.get('categories', {})
    nav_items = []

    for category_name, articles in categories.items():
        if articles:
            icon = category_icons.get(category_name, '📌')
            count = len(articles)
            # Create anchor link to category section
            nav_items.append(f'<li onclick="scrollToCategory(\'{category_name}\')">{icon} {category_name} ({count})</li>')

    return ''.join(nav_items)


def generate_html(articles, output_file=None, ai_curated=None):
    """Generate HTML page with collected articles, optionally including AI curated view"""

    # 如果没有指定输出文件，则默认为项目根目录下的docs/index.html
    if output_file is None:
        import os
        # 获取项目根目录 (向上两级目录)
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_file = os.path.join(project_root, 'docs', 'index.html')
    else:
        # 如果传入的是相对路径 'docs/index.html'，将其转换为项目根目录下的路径
        if output_file == 'docs/index.html':
            import os
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            output_file = os.path.join(project_root, 'docs', 'index.html')

    # Create docs directory if it doesn't exist
    import os
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Sort articles by date (most recent first)
    tech_sorted = sorted(articles['tech'], key=lambda x: x['date'], reverse=True)
    news_sorted = sorted(articles['news'], key=lambda x: x['date'], reverse=True)

    # Calculate default visible count (excluding Unsafe.sh)
    default_visible_count = len([a for a in tech_sorted + news_sorted if a['source'] != 'Unsafe.sh'])

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

        .multi-select {{
            position: relative;
            width: 100%;
        }}

        .multi-select-header {{
            width: 100%;
            padding: 0.5rem;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: white url('data:image/svg+xml;charset=UTF-8,<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12"><path fill="%23666" d="M2 4l4 4 4-4"/></svg>') no-repeat right 0.5rem center;
            cursor: pointer;
            font-size: 0.9rem;
            color: #333;
        }}

        .multi-select-dropdown {{
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: white;
            border: 1px solid #ddd;
            border-radius: 4px;
            margin-top: 2px;
            max-height: 200px;
            overflow-y: auto;
            z-index: 100;
            display: none;
            font-size: 0.9rem;
        }}

        .multi-select-dropdown.show {{
            display: block;
        }}

        .multi-select-option {{
            display: flex;
            align-items: center;
            padding: 0.25rem 0.5rem;
            cursor: pointer;
            font-size: 0.9rem;
            line-height: 1.2;
        }}

        .multi-select-option input[type="checkbox"] {{
            margin: 0;
            margin-right: 0.35rem;
            width: 14px;
            height: 14px;
            flex-shrink: 0;
        }}

        .multi-select-option:hover {{
            background: #f5f5f5;
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

        .footer a {{
            color: #007bff;
            text-decoration: none;
        }}

        .footer a:hover {{
            text-decoration: underline;
        }}

        .footer .github-icon {{
            width: 16px;
            height: 16px;
            vertical-align: -0.15em;
            margin-right: 4px;
        }}

        .footer .separator {{
            margin: 0 8px;
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

        /* View toggle buttons - segmented control style */
        .view-toggle {{
            display: inline-flex;
            background: #f0f0f0;
            border-radius: 24px;
            padding: 4px;
            margin-bottom: 1rem;
        }}

        .view-toggle-btn {{
            padding: 8px 16px;
            border: none;
            background: transparent;
            color: #666;
            border-radius: 20px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 600;
            transition: all 0.2s ease;
        }}

        .view-toggle-btn:hover {{
            color: #333;
        }}

        .view-toggle-btn.active {{
            background: white;
            color: #667eea;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        }}

        /* Sidebar sections */
        .sidebar-section {{
            transition: all 0.3s ease;
        }}

        .sidebar-section.hidden {{
            display: none;
        }}

        /* AI category navigation */
        .ai-category-nav {{
            background: white;
            border-radius: 8px;
            padding: 1rem;
        }}

        .ai-category-nav h4 {{
            margin-bottom: 0.75rem;
            color: #495057;
        }}

        .ai-category-nav ul {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}

        .ai-category-nav li {{
            padding: 0.5rem 0;
            border-bottom: 1px solid #eee;
            cursor: pointer;
            color: #007bff;
            transition: all 0.2s ease;
        }}

        .ai-category-nav li:hover {{
            color: #0056b3;
            padding-left: 5px;
        }}

        .ai-category-nav li:last-child {{
            border-bottom: none;
        }}

        /* AI curated view styles */
        .ai-view {{
            display: none;
        }}

        .ai-view.active {{
            display: block;
        }}

        .original-view {{
            display: block;
        }}

        .original-view.hidden {{
            display: none;
        }}

        .ai-category {{
            margin-bottom: 2rem;
        }}

        .ai-category-title {{
            font-size: 1.4rem;
            color: #495057;
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid #667eea;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .ai-summary {{
            padding: 0.5rem 0 1.5rem 0;
            margin-bottom: 2rem;
            border-bottom: 1px solid #dee2e6;
        }}

        .ai-summary h3 {{
            margin-bottom: 0.75rem;
            color: #333;
            font-size: 1.2rem;
            font-weight: 600;
        }}

        .ai-summary-text {{
            color: #555;
            line-height: 1.7;
            padding-left: 1rem;
            border-left: 3px solid #667eea;
        }}

        .model-badge {{
            display: inline-block;
            background: #667eea;
            color: white;
            font-size: 0.7rem;
            padding: 3px 12px;
            border-radius: 12px;
            font-weight: 500;
            margin-left: 10px;
            vertical-align: middle;
            letter-spacing: 0.3px;
            box-shadow: 0 1px 3px rgba(102, 126, 234, 0.3);
        }}

        .ai-article {{
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .ai-article:hover {{
            transform: translateY(-5px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}

        .ai-article-title {{
            font-size: 1.1rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }}

        .ai-article-title a {{
            color: #007bff;
            text-decoration: none;
        }}

        .ai-article-title a:hover {{
            text-decoration: underline;
        }}

        .ai-article-reason {{
            color: #666;
            font-size: 0.9rem;
            margin-top: 0.5rem;
            padding-top: 0.5rem;
            border-top: 1px dashed #ddd;
        }}

        .ai-meta {{
            display: flex;
            gap: 1rem;
            color: #888;
            font-size: 0.85rem;
        }}

        .no-ai-data {{
            text-align: center;
            padding: 2rem;
            color: #666;
            background: #f8f9fa;
            border-radius: 8px;
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
            <!-- View Toggle Buttons -->
            <!-- Original View (All Articles) -->
            <div class="original-view" id="original-view">
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
            </div>

            <!-- AI Curated View -->
            <div class="ai-view" id="ai-view">
                {_generate_ai_curated_html(ai_curated) if ai_curated else '<div class="no-ai-data"><p>🤖 AI精选数据暂未生成</p><p>请启用 --ai-curate 参数来生成AI精选内容</p></div>'}
            </div>
        </main>

        <aside class="sidebar">
            <!-- View Toggle Buttons -->
            <div class="view-toggle">
                <button class="view-toggle-btn" onclick="switchView('ai')">🤖 AI精选</button>
                <button class="view-toggle-btn active" onclick="switchView('original')">📚 全部文章</button>
            </div>

            <!-- Original Sidebar (Filters) -->
            <div class="sidebar-section" id="original-sidebar">
                <div class="filters">
                    <div class="filter-group">
                        <label>📅 按日期筛选:</label>
                        <div class="multi-select" id="date-select">
                            <div class="multi-select-header" onclick="toggleDropdown('date-select')">全部日期</div>
                            <div class="multi-select-dropdown">
                                {''.join([f'<div class="multi-select-option"><input type="checkbox" id="date-{i}" value="{date}"> {date}</div>' for i, date in enumerate(sorted_dates)])}
                            </div>
                        </div>
                    </div>

                    <div class="filter-group">
                        <label>🏢 按来源筛选:</label>
                        <div class="multi-select" id="source-select">
                            <div class="multi-select-header" onclick="toggleDropdown('source-select')">全部来源[不包含Unsafe]</div>
                            <div class="multi-select-dropdown" id="source-dropdown"></div>
                        </div>
                    </div>

                    <div class="filter-group">
                        <label for="search-input">🔍 搜索关键词:</label>
                        <input type="text" id="search-input" placeholder="输入关键词搜索..." onkeyup="applyFilters()">
                    </div>

                    <button onclick="clearAllFilters()" style="margin-top: 10px; padding: 8px 16px; background: #6c757d; color: white; border: none; border-radius: 4px; cursor: pointer;">清除筛选</button>
                </div>

                <div style="margin-top: 1.5rem;">
                    <h4>统计信息</h4>
                    <p id="visible-count">当前显示: {default_visible_count}</p>
                    <p>总文章数: {len(tech_sorted) + len(news_sorted)}</p>
                    <p>技术文章: {len(tech_sorted)}</p>
                    <p>安全新闻: {len(news_sorted)}</p>
                    <p>更新日期: {datetime.now().strftime('%Y-%m-%d')}</p>
                </div>
            </div>

            <!-- AI Sidebar (Category Navigation) -->
            <div class="sidebar-section hidden" id="ai-sidebar">
                <div class="ai-category-nav">
                    <h4>📋 分类目录</h4>
                    <ul>
                        {_generate_ai_category_nav(ai_curated) if ai_curated else '<li style="color:#666">暂无分类数据</li>'}
                    </ul>
                </div>
                <div style="margin-top: 1rem; padding: 0.5rem; background: #f8f9fa; border-radius: 4px; font-size: 0.85rem; color: #666;">
                    <p>分析日期: {ai_curated.get('analysis_date', '-') if ai_curated else '-'}</p>
                    <p>筛选文章: {sum(len(arts) for arts in ai_curated.get('categories', {}).values()) if ai_curated else 0} 篇</p>
                    <p>原始文章: {ai_curated.get('total_analyzed', 0) if ai_curated else 0} 篇</p>
                    <p>模型来源: {html.escape(ai_curated.get('model', '-')) if ai_curated else '-'}</p>
                </div>
            </div>
        </aside>

        <div class="footer">
            <p>
                © 2026 <a href="https://github.com/secnotes" target="_blank">Security Notes</a>
                <span class="separator">|</span>
                <a href="https://github.com/secnotes/secnews" target="_blank">
                    <svg class="github-icon" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.938 9.9 9.207 11.387.68.113.893-.261.893-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.218.694.825.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                    </svg>
                    Star on GitHub
                </a>
                <span class="separator">|</span>
                <a href="https://github.com/secnotes/secnews/blob/main/src/articles.json" target="_blank">
                    📄 Json data
                </a>
            </p>
            <p>安全资讯聚合平台 | 更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>数据来源: Sec-Today, 先知社区, Project Zero, Seebug Paper, 腾讯安全, 安全客, 安全内参, SecurityWeek, The Hacker News, 看雪</p>
            <p>如有侵权，请联系删除</p>
        </div>
    </div>

    <script>
        document.addEventListener('click', function(e) {{
            if (!e.target.closest('.multi-select')) {{
                document.querySelectorAll('.multi-select-dropdown').forEach(d => d.classList.remove('show'));
            }}
        }});

        function toggleDropdown(id) {{
            var dropdown = document.querySelector('#' + id + ' .multi-select-dropdown');
            var isOpen = dropdown.classList.contains('show');
            // 先关闭所有下拉框
            document.querySelectorAll('.multi-select-dropdown').forEach(function(dd) {{
                dd.classList.remove('show');
            }});
            // 如果之前是关闭的，则打开
            if (!isOpen) {{
                dropdown.classList.add('show');
            }}
        }}

        window.onload = function() {{
            // 初始化来源下拉框
            const sources = new Set();
            document.querySelectorAll('.article-card').forEach(card => {{
                sources.add(card.querySelector('.article-source').textContent.replace('来源: ', ''));
            }});
            const dropdown = document.getElementById('source-dropdown');
            Array.from(sources).sort().forEach((source, i) => {{
                dropdown.innerHTML += '<div class="multi-select-option"><input type="checkbox" id="source-' + i + '" value="' + source + '"> ' + source + '</div>';
            }});

            // 绑定checkbox事件
            document.querySelectorAll('.multi-select-dropdown input[type="checkbox"]').forEach(cb => {{
                cb.addEventListener('change', applyFilters);
            }});

            applyFilters();
        }};

        function applyFilters() {{
            const selectedDates = Array.from(document.querySelectorAll('#date-select input:checked')).map(cb => cb.value);
            const selectedSources = Array.from(document.querySelectorAll('#source-select input:checked')).map(cb => cb.value);
            const searchTerm = document.getElementById('search-input').value.toLowerCase();

            // 更新下拉框标题
            document.querySelector('#date-select .multi-select-header').textContent = selectedDates.length ? (selectedDates.length > 1 ? selectedDates.length + '项已选' : selectedDates[0]) : '全部日期';
            document.querySelector('#source-select .multi-select-header').textContent = selectedSources.length ? (selectedSources.length > 1 ? selectedSources.length + '项已选' : selectedSources[0]) : '全部来源[不包含Unsafe]';

            // 筛选文章
            let visibleCount = 0;
            document.querySelectorAll('.article-card').forEach(card => {{
                const cardDate = card.getAttribute('data-date');
                const cardSource = card.querySelector('.article-source').textContent.replace('来源: ', '');
                const title = card.querySelector('.article-title').textContent.toLowerCase();
                const desc = card.querySelector('.article-description')?.textContent.toLowerCase() || '';

                const match = (selectedDates.length === 0 || selectedDates.includes(cardDate)) &&
                             (selectedSources.length === 0 || selectedSources.includes(cardSource)) &&
                             (searchTerm === '' || title.includes(searchTerm) || desc.includes(searchTerm)) &&
                             (selectedSources.includes('Unsafe.sh') || cardSource !== 'Unsafe.sh');
                card.style.display = match ? 'flex' : 'none';
                if (match) visibleCount++;
            }});
            document.getElementById('visible-count').textContent = '当前显示: ' + visibleCount;
        }}

        function clearAllFilters() {{
            document.querySelectorAll('.multi-select input[type="checkbox"]').forEach(cb => cb.checked = false);
            document.getElementById('search-input').value = '';
            document.querySelector('#date-select .multi-select-header').textContent = '全部日期';
            document.querySelector('#source-select .multi-select-header').textContent = '全部来源[不包含Unsafe]';
            document.querySelectorAll('.multi-select-dropdown').forEach(d => d.classList.remove('show'));
            applyFilters();
        }}

        function switchView(view) {{
            const originalView = document.getElementById('original-view');
            const aiView = document.getElementById('ai-view');
            const originalSidebar = document.getElementById('original-sidebar');
            const aiSidebar = document.getElementById('ai-sidebar');
            const buttons = document.querySelectorAll('.view-toggle-btn');

            buttons.forEach(btn => btn.classList.remove('active'));

            if (view === 'original') {{
                originalView.classList.remove('hidden');
                originalView.classList.add('active');
                aiView.classList.remove('active');
                originalSidebar.classList.remove('hidden');
                aiSidebar.classList.add('hidden');
                buttons[1].classList.add('active');
            }} else {{
                originalView.classList.add('hidden');
                originalView.classList.remove('active');
                aiView.classList.add('active');
                originalSidebar.classList.add('hidden');
                aiSidebar.classList.remove('hidden');
                buttons[0].classList.add('active');
            }}
        }}

        function scrollToCategory(categoryName) {{
            // Find the category title element
            const titles = document.querySelectorAll('.ai-category-title');
            for (const title of titles) {{
                if (title.textContent.includes(categoryName)) {{
                    title.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
                    break;
                }}
            }}
        }}
    </script>
</body>
</html>"""

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

    logger.info(f"HTML page generated: {output_file}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Security News Aggregator')
    parser.add_argument('--unsafe', action='store_true',
                        help='Include Unsafe.sh crawler (default: disabled)')
    parser.add_argument('--ai-curate', action='store_true',
                        help='Enable AI curation for recent articles')
    parser.add_argument('--ai-days', type=int, default=2,
                        help='Number of days to analyze for AI curation (default: 2)')
    parser.add_argument('--ai-key', type=str, default=None,
                        help='AI API key (default: from AI_API_KEY env var)')
    parser.add_argument('--ai-model', type=str, default=None,
                        help='AI model name (default: from AI_MODEL env var, or gpt-4o-mini)')
    parser.add_argument('--ai-base-url', type=str, default=None,
                        help='AI API base URL (default: auto-inferred from model)')
    args = parser.parse_args()

    aggregator = SecurityNewsAggregator()

    # Scrape all sources (unsafe crawler only enabled with --unsafe flag)
    aggregator.scrape_all_sources(include_unsafe=args.unsafe)

    # Save raw data
    aggregator.save_articles_json()

    # AI curation (optional)
    ai_curated = None
    if args.ai_curate:
        ai_curated = aggregator.ai_curate_articles(
            days=args.ai_days,
            api_key=args.ai_key,
            model=args.ai_model,
            base_url=args.ai_base_url
        )
        if ai_curated:
            aggregator.save_ai_curated_json(ai_curated)

    # Generate HTML page (this will go to project root docs directory)
    generate_html(aggregator.articles, ai_curated=ai_curated)

    print(f"\n完成！共收集到:")
    print(f"- 技术文章: {len(aggregator.articles['tech'])} 篇")
    print(f"- 新闻: {len(aggregator.articles['news'])} 篇")
    if ai_curated:
        total_curated = sum(len(arts) for arts in ai_curated.get('categories', {}).values())
        print(f"- AI精选: {total_curated} 篇")
    print(f"已生成 docs/index.html 文件")


if __name__ == "__main__":
    main()