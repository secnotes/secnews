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

# Translation module (translate_all is a no-op without an AI API key;
# CATEGORY_EN / SOURCE_EN are plain dicts used when rendering bilingual
# category and source names)
from translator import translate_all, CATEGORY_EN, SOURCE_EN

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

# Proxy configuration (can be set via environment variable or .env file)
# Set HTTPS_PROXY environment variable, e.g., export HTTPS_PROXY=https://127.0.0.1:10808
# Load .env (same locations as ai_provider.py: src/.env, project_root/.env, ./.env)
# before reading PROXY_URL below, so a proxy configured in .env reaches the
# crawlers. Existing environment variables are never overridden.
try:
    from dotenv import load_dotenv
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    for _env_path in (
        os.path.join(_script_dir, '.env'),                       # src/.env
        os.path.join(os.path.dirname(_script_dir), '.env'),      # project_root/.env
        '.env',                                                   # current working directory
    ):
        if os.path.exists(_env_path):
            load_dotenv(_env_path)
            break
except ImportError:
    pass  # python-dotenv not installed, rely on environment variables

PROXY_URL = os.environ.get('HTTPS_PROXY', os.environ.get('HTTP_PROXY', None))

def get_proxies():
    """Get proxy configuration from environment variable"""
    if PROXY_URL:
        return {
            'http': PROXY_URL,
            'https': PROXY_URL
        }
    return None


def _load_x_accounts():
    """Load X account screen names from x_accounts.txt at project root.

    One per line; blank lines and lines starting with '#' are ignored.
    A leading '@' is stripped. Returns [] when the file is absent (the X
    source then stays disabled, mirroring translate_all's no-op-when-unset).
    """
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'x_accounts.txt')
    accounts = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                accounts.append(line.lstrip('@'))
    if accounts:
        logger.info(f"Loaded {len(accounts)} X account(s) from x_accounts.txt")
    return accounts

X_ACCOUNTS = _load_x_accounts()

def _docs_dir():
    """Project docs directory (generated HTML and dated data archives live here)"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(script_dir), 'docs')


def _dated_archive_path(kind, filename_prefix, date=None):
    """Dated archive path mirroring the dailycve layout:
    docs/data/2026/articles_20260821.json
    docs/ai/2026/ai_curated_20260821.json
    """
    d = date or datetime.now()
    return os.path.join(_docs_dir(), kind, str(d.year),
                        f"{filename_prefix}_{d.strftime('%Y%m%d')}.json")


# Keep articles published today or yesterday (48h sliding window). Feeds
# lag behind publication and the CI runs at 00:00 UTC (= 08:00 CST), so a
# today-only window would permanently drop articles; the one-day overlap
# also self-heals a failed run. Applied centrally in main() so individual
# scrapers stay as-is, and it bounds what each dated archive contains:
# with the in-page date picker, every day's view holds only fresh items.
MAX_ARTICLE_AGE_DAYS = 1

# English display names for per-source log lines ("Scraping X..." /
# "Found N articles on X"), keyed by the article 'source' field so the
# count helper and the scraper logs stay in sync
SOURCE_LOG_NAMES = {
    'Sec-Today': 'Sec-Today',
    '腾讯安全': 'Tencent Security',
    '先知社区': 'Xianzhi',
    'Project Zero': 'Project Zero',
    'Seebug Paper': 'SeeBug Paper',
    '看雪论坛': 'Kanxue',
    '安全客': 'Anquanke',
    'FreeBuf': 'FreeBuf',
    '安全内参': 'SecRSS',
    'The Hacker News': 'The Hacker News',
    'SecurityWeek': 'SecurityWeek',
    'Security Online': 'Security Online',
    'Unsafe.sh': 'Unsafe.sh',
}


class SecurityNewsAggregator:
    def __init__(self):
        self.articles = {
            'web': [],
            'x': []
        }

    def _log_found(self, source, category, fetched=None):
        """Emit the standardized per-source result line. Articles start
        empty each run, so the source's current total in self.articles
        equals what its scraper just added.

        `fetched` is how many candidate items the source page/feed offered
        (before parsing skips, filters and errors); when given, the line
        shows both numbers so page-structure changes are visible in logs
        (fetched suddenly at 0 while count holds => source layout changed).
        """
        display = SOURCE_LOG_NAMES.get(source, source)
        count = sum(1 for a in self.articles[category] if a['source'] == source)
        if fetched is None:
            logger.info(f"Found {count} articles on {display}")
        else:
            logger.info(f"Found {count} articles on {display} (fetched {fetched})")

    def decode_html_entities(self, text):
        """Decode HTML entities in text"""
        if text:
            return html.unescape(text)
        return text

    def _relative_past_date(self, unit, quantity):
        """Return a datetime `quantity` `unit`s before now, or None if unknown.

        timedelta has no month or year unit, so months are approximated as
        30 days and years as 365 days - accurate enough for relative-time
        text like "1 month ago" on news cards.
        """
        now = datetime.now()
        if unit == 'years':
            return now - timedelta(days=quantity * 365)
        if unit == 'months':
            return now - timedelta(days=quantity * 30)
        if unit == 'weeks':
            return now - timedelta(weeks=quantity)
        if unit == 'days':
            return now - timedelta(days=quantity)
        if unit == 'hours':
            return now - timedelta(hours=quantity)
        if unit == 'minutes':
            return now - timedelta(minutes=quantity)
        if unit == 'seconds':
            return now - timedelta(seconds=quantity)
        return None

    def _parse_relative_time(self, time_text):
        """Parse relative time text and return date string (YYYY-MM-DD)"""
        if not time_text:
            return None

        # English patterns
        english_patterns = [
            (r'(\d+)\s*year[s]?\s*ago', 'years'),     # "1 year ago", "2 years ago"
            (r'(\d+)\s*month[s]?\s*ago', 'months'),   # "1 month ago", "2 months ago"
            (r'(\d+)\s*week[s]?\s*ago', 'weeks'),
            (r'(\d+)\s*day[s]?\s*ago', 'days'),
            (r'(\d+)\s*hour[s]?\s*ago', 'hours'),
            (r'(\d+)\s*minute[s]?\s*ago', 'minutes'),
            (r'(\d+)\s*second[s]?\s*ago', 'seconds'),
        ]

        for pattern, unit in english_patterns:
            match = re.search(pattern, time_text, re.IGNORECASE)
            if match:
                past_date = self._relative_past_date(unit, int(match.group(1)))
                if past_date:
                    return past_date.strftime('%Y-%m-%d')

        # Chinese patterns
        chinese_patterns = [
            (r'(\d+)\s*年\s*之\s*前', 'years'),        # "2年之前", "2 年 之前"
            (r'(\d+)\s*年前', 'years'),                # "2年前"
            (r'(\d+)\s*个\s*月\s*之\s*前', 'months'),   # "2个月之前", "2 个月 之前"
            (r'(\d+)\s*个月前', 'months'),             # "2个月前"
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
                past_date = self._relative_past_date(unit, int(match.group(1)))
                if past_date:
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
        logger.info("Scraping Sec-Today...")
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

                        # Method 2/3: Look for relative time text anywhere in the
                        # card (English or Chinese). Reuses _parse_relative_time so
                        # every unit - including "month(s) ago" / "year(s) ago" and
                        # the Chinese equivalents - is handled consistently with the
                        # <time> tag path above. Previously this inline copy only
                        # knew week/day/hour/minute/second, so text like
                        # "SecTodayBot • 1 month ago" matched nothing and silently
                        # fell back to today's date.
                        if not date_found:
                            card_text = card.get_text()
                            parsed_date = self._parse_relative_time(card_text)
                            if parsed_date:
                                date = parsed_date
                                date_found = True
                                logger.debug(f"Found date from relative time text: {date}")

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
                            'category': 'web'
                        }
                        self.articles['web'].append(article)
                except Exception as e:
                    continue

            self._log_found('Sec-Today', 'web', fetched=len(cards))
        except Exception as e:
            logger.error(f"Error scraping Sec-Today: {str(e)}")

    def scrape_tencent_security(self):
        """Scrape https://sectoday.tencent.com/api/atom.xml (玄武实验室每日安全)
        for tech articles.

        The site's pages are JS-rendered MUI components, so the old HTML
        scrape (MuiPaper-root cards) had been matching nothing and the
        source silently produced 0 articles; the feed endpoint returns
        plain RSS 2.0 (despite the atom.xml name) that parses directly.
        Note: the feed itself has gone quiet before (stale for weeks in
        2026-07/08), which the unified "Found N (fetched M)" line makes
        visible in logs.
        """
        logger.info("Scraping Tencent Security (atom feed)...")
        try:
            import xml.etree.ElementTree as ET
            from email.utils import parsedate_to_datetime

            response = session.get("https://sectoday.tencent.com/api/atom.xml",
                                   headers={'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'},
                                   timeout=20)
            response.raise_for_status()

            root = ET.fromstring(response.content)
            items = root.findall('.//item')

            for item in items:
                try:
                    title = (item.findtext('title') or '').strip()
                    url = (item.findtext('link') or '').strip()
                    if not title or not url:
                        continue

                    description = (item.findtext('description') or '').strip()
                    description = description[:200] + '...' if len(description) > 200 else description

                    # pubDate is UTC ("Sun, 26 Jul 2026 03:35:35 +0000");
                    # convert to the local date the freshness filter compares
                    date = datetime.now().strftime('%Y-%m-%d')
                    pub_date_text = (item.findtext('pubDate') or '').strip()
                    if pub_date_text:
                        try:
                            parsed_date = parsedate_to_datetime(pub_date_text)
                            date = parsed_date.astimezone().strftime('%Y-%m-%d')
                        except Exception:
                            pass

                    article = {
                        'title': self.decode_html_entities(title),
                        'url': url,
                        'source': '腾讯安全',
                        'description': self.decode_html_entities(description),
                        'date': date,
                        'category': 'web'
                    }
                    self.articles['web'].append(article)

                except Exception as e:
                    logger.warning(f"Error processing Tencent Security feed item: {str(e)}")
                    continue

            self._log_found('腾讯安全', 'web', fetched=len(items))
        except Exception as e:
            logger.error(f"Error scraping Tencent Security: {str(e)}")

    def scrape_xz_aliyun(self):
        """Scrape https://xz.aliyun.com/news for security news (tech) using the proper GET request"""
        logger.info("Scraping Xianzhi (xz.aliyun.com)...")
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
                                'category': 'web'
                            }
                            self.articles['web'].append(article)
                    except Exception as e:
                        logger.warning(f"Error processing XZ Aliyun item: {str(e)}")
                        continue
            else:
                logger.warning("Unexpected response structure from XZ Aliyun API")

            self._log_found('先知社区', 'web', fetched=len(cards))

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
                            'category': 'web'
                        }
                        self.articles['web'].append(article_dict)
                except Exception as e:
                    logger.warning(f"Error processing Project Zero item: {str(e)}")
                    continue
            self._log_found('Project Zero', 'web', fetched=len(grid_articles))
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
                        'category': 'web'
                    }
                    self.articles['web'].append(article)

                except Exception as e:
                    logger.warning(f"Error processing Anquanke item: {str(e)}")
                    continue

            self._log_found('安全客', 'web', fetched=len(item_elements))

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

            # Find all items in RSS feed
            items = root.findall('.//item')

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
                        'category': 'web'
                    }
                    self.articles['web'].append(article)

                except Exception as e:
                    logger.warning(f"Error processing FreeBuf article: {str(e)}")
                    continue

            self._log_found('FreeBuf', 'web', fetched=len(items))

        except Exception as e:
            logger.error(f"Error scraping FreeBuf: {str(e)}")

    def scrape_secrss(self):
        """Scrape https://www.secrss.com/ for security news"""
        logger.info("Scraping SecRSS (secrss.com)...")
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
                                    'category': 'web'
                                }
                                self.articles['web'].append(article)
                        except Exception as e:
                            logger.warning(f"Error processing Secrss item: {str(e)}")
                            continue
            self._log_found('安全内参', 'web',
                            fetched=len(list_items) if article_list_title and article_list_title.find_next_sibling('ul') else 0)
        except Exception as e:
            logger.error(f"Error scraping Secrss: {str(e)}")

    def scrape_seebug_paper(self):
        """Scrape https://paper.seebug.org/rss for security research papers (tech)

        The HTML pages sit behind an aggressive WAF (521 even with
        browser-like headers), but the RSS endpoint is served without the
        shield, so the old HTML scraping was replaced by plain feed
        parsing.

        TLS note: the server only serves its leaf certificate (the Let's
        Encrypt intermediate is missing from the chain), so strict
        verification fails with CERTIFICATE_VERIFY_FAILED. We still try
        verifying first, and only fall back to an unverified request for
        this single feed when that specific error occurs - better than
        the blanket verify=False the HTML scraper used.
        """
        logger.info("Scraping SeeBug Paper (RSS)...")
        try:
            import xml.etree.ElementTree as ET
            from email.utils import parsedate_to_datetime

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8',
            }

            # Strict TLS first; the server's chain is missing the Let's
            # Encrypt intermediate, so verification legitimately fails and
            # we retry just this feed unverified
            response = None
            try:
                response = requests.get("https://paper.seebug.org/rss",
                                        headers=headers, timeout=20)
            except requests.exceptions.SSLError:
                logger.warning("SeeBug Paper TLS verification failed "
                               "(incomplete server chain), retrying unverified")
                response = requests.get("https://paper.seebug.org/rss",
                                        headers=headers, timeout=20, verify=False)

            response.raise_for_status()

            root = ET.fromstring(response.content)
            items = root.findall('.//item')

            for item in items:
                try:
                    title = (item.findtext('title') or '').strip()
                    url = (item.findtext('link') or '').strip()
                    if not title or not url:
                        continue

                    # Description arrives as CDATA text shaped like
                    # "作者：... 原文链接：... 摘要 <abstract>"
                    description = (item.findtext('description') or '').strip()
                    m = re.search(r'摘要\s*(.*)', description, re.S)
                    if m:
                        description = m.group(1).strip()
                    description = description[:200] + '...' if len(description) > 200 else description

                    # pubDate like "Thu, 20 Aug 2026 16:49:44 +0800" (RFC 822)
                    date = datetime.now().strftime('%Y-%m-%d')
                    pub_date_text = (item.findtext('pubDate') or '').strip()
                    if pub_date_text:
                        try:
                            parsed_date = parsedate_to_datetime(pub_date_text)
                            date = parsed_date.strftime('%Y-%m-%d')
                        except Exception:
                            pass

                    article = {
                        'title': self.decode_html_entities(title),
                        'url': url,
                        'source': 'Seebug Paper',
                        'description': self.decode_html_entities(description),
                        'date': date,
                        'category': 'web'
                    }
                    self.articles['web'].append(article)

                except Exception as e:
                    logger.warning(f"Error processing SeeBug Paper RSS item: {str(e)}")
                    continue

            self._log_found('Seebug Paper', 'web', fetched=len(items))

        except requests.exceptions.RequestException as e:
            logger.warning(f"Network error while scraping SeeBug Paper RSS: {str(e)}")
        except Exception as e:
            logger.error(f"Error scraping SeeBug Paper RSS: {str(e)}")

    def scrape_kanxue(self):
        """Scrape https://www.kanxue.com/ for security tech articles"""
        logger.info("Scraping Kanxue (kanxue.com)...")
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
                                'category': 'web'  # KanXue is technology-focused
                            }
                            self.articles['web'].append(article)

                    except Exception as e:
                        logger.warning(f"Error processing KanXue article: {str(e)}")
                        continue
            else:
                logger.info("Could not find articles with class 'media p-3 home_article bg-white' on Kanxue")

            self._log_found('看雪论坛', 'web', fetched=len(article_elements))

        except requests.exceptions.RequestException as e:
            logger.warning(f"Network error while scraping Kanxue: {str(e)}")
        except Exception as e:
            logger.error(f"Error scraping Kanxue: {str(e)}")

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
                body_posts = blog_posts_div.find_all('div', class_='body-post') if blog_posts_div else []

                if blog_posts_div:
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
                                            'category': 'web'
                                        }
                                        self.articles['web'].append(article)

                        except Exception as e:
                            logger.warning(f"Error processing The Hacker News article: {str(e)}")
                            continue
                else:
                    logger.info("Could not find 'blog-posts clear' div in The Hacker News")

            else:
                logger.warning(f"Failed to fetch The Hacker News: HTTP {response.status_code}")

            self._log_found('The Hacker News', 'web', fetched=len(body_posts))

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
                            'category': 'web'
                        }
                        self.articles['web'].append(article)

                except Exception as e:
                    logger.warning(f"Error processing SecurityWeek RSS item: {str(e)}")
                    continue

            self._log_found('SecurityWeek', 'web', fetched=len(items))

        except ImportError:
            logger.warning("Playwright not available, skipping SecurityWeek")
        except Exception as e:
            logger.error(f"Error scraping SecurityWeek: {str(e)}")

    def scrape_securityonline(self):
        """Scrape https://securityonline.info/feed RSS for security news.

        Plain RSS 2.0; requires a proxy in CN environments (the host is
        reachable but slow/blocked without one). Replaces the coverage
        previously pulled from @Daily_CyberSec tweets.
        """
        logger.info("Scraping Security Online RSS feed...")
        try:
            import xml.etree.ElementTree as ET
            from email.utils import parsedate_to_datetime

            response = session.get('https://securityonline.info/feed',
                                   headers={'Accept': 'application/rss+xml, application/xml;q=0.9, */*;q=0.8'},
                                   proxies=get_proxies(), timeout=25)
            response.raise_for_status()

            root = ET.fromstring(response.content)
            items = root.findall('.//item')

            for item in items[:30]:  # Limit to 30 articles
                try:
                    title = (item.findtext('title') or '').strip()
                    url = (item.findtext('link') or '').strip()
                    if not title or not url:
                        continue

                    # Description arrives as HTML; strip tags for the card
                    description = ''
                    desc_raw = item.findtext('description') or ''
                    if desc_raw:
                        description = re.sub(r'<[^>]+>', '', desc_raw).strip()
                        description = description[:200] + '...' if len(description) > 200 else description

                    # pubDate is RFC 822 ("Wed, 26 Aug 2026 08:01:36 +0000")
                    date = datetime.now().strftime('%Y-%m-%d')
                    pub_date_text = (item.findtext('pubDate') or '').strip()
                    if pub_date_text:
                        try:
                            parsed_date = parsedate_to_datetime(pub_date_text)
                            date = parsed_date.astimezone().strftime('%Y-%m-%d')
                        except Exception:
                            pass

                    article = {
                        'title': self.decode_html_entities(title),
                        'url': url,
                        'source': 'Security Online',
                        'description': self.decode_html_entities(description),
                        'date': date,
                        'category': 'web'
                    }
                    self.articles['web'].append(article)

                except Exception as e:
                    logger.warning(f"Error processing Security Online RSS item: {str(e)}")
                    continue

            self._log_found('Security Online', 'web', fetched=len(items))

        except Exception as e:
            logger.error(f"Error scraping Security Online: {str(e)}")

    def scrape_x_account(self, screen_name):
        """Scrape one X account's recent tweets via SSR Schema.org microdata.

        X server-side renders ~5 most-recent tweets as SocialMediaPosting
        microdata for SEO, so a plain HTML fetch (no login, no guest
        token, no JS) yields them directly. Returns early with an error
        if the fetch fails; logs fetched=0 if the SSR markup is absent
        (layout changed / blocked).
        """
        logger.info(f"Scraping X (@{screen_name})...")
        try:
            response = session.get(
                f"https://x.com/{screen_name}",
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                                  'Chrome/120.0.0.0 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                timeout=20,
            )
            if response.status_code != 200:
                logger.error(f"Failed to fetch x.com/{screen_name}: HTTP {response.status_code}")
                return
            soup = BeautifulSoup(response.content, 'html.parser')
            articles = soup.find_all('article', attrs={'itemtype': 'https://schema.org/SocialMediaPosting'})

            # Canonical screen name from SSR (handles case-insensitive input:
            # /portswigger -> og:title "PortSwigger (@PortSwigger)")
            canonical = screen_name
            og_title = soup.find('meta', attrs={'property': 'og:title'})
            if og_title and og_title.get('content'):
                m = re.search(r'\(@([^)]+)\)', og_title['content'])
                if m:
                    canonical = m.group(1)
            source_name = f'X (@{canonical})'

            for art in articles:
                try:
                    def ip(name):
                        meta = art.find('meta', attrs={'itemprop': name})
                        return meta['content'] if meta and meta.has_attr('content') else ''
                    text = ip('text')
                    url = ip('url')
                    if not text or not url:
                        continue
                    # Tweet has no title: first ~80 chars as title, full text as description
                    title = text[:80] + ('…' if len(text) > 80 else '')
                    # Date '2026-08-06T22:29:00.000Z' -> local YYYY-MM-DD
                    # (matches Tencent's .astimezone() so the freshness filter
                    # compares against the local cutoff consistently)
                    date = datetime.now().strftime('%Y-%m-%d')
                    iso = ip('datePublished')
                    if iso:
                        try:
                            date = datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d')
                        except ValueError:
                            pass
                    # Author block (avatar / display name / @handle) feeds the
                    # tweet-style card; all fields optional, card degrades
                    # gracefully when absent
                    author_name = ''
                    author_handle = canonical
                    author_avatar = ''
                    author_block = art.find('div', attrs={'itemprop': 'author'})
                    if author_block:
                        def aip(name):
                            meta = author_block.find('meta', attrs={'itemprop': name})
                            return meta['content'] if meta and meta.has_attr('content') else ''
                        author_name = aip('name')
                        author_handle = aip('alternateName') or canonical
                        author_avatar = aip('image')
                    self.articles['x'].append({
                        'title': self.decode_html_entities(title),
                        'url': url,
                        'source': source_name,
                        'description': self.decode_html_entities(text[:500] + ('...' if len(text) > 500 else '')),
                        'date': date,
                        'category': 'x',
                        'author_name': author_name,
                        'author_handle': author_handle,
                        'author_avatar': author_avatar,
                    })
                except Exception as e:
                    logger.warning(f"Error processing X tweet for @{screen_name}: {str(e)}")
                    continue

            self._log_found(source_name, 'x', fetched=len(articles))
        except Exception as e:
            logger.error(f"Error scraping X (@{screen_name}): {str(e)}")

    def scrape_x(self):
        """Scrape all X accounts listed in x_accounts.txt (no-op if absent/empty)."""
        if not X_ACCOUNTS:
            return
        for screen_name in X_ACCOUNTS:
            self.scrape_x_account(screen_name)

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
            fetched_count = 0

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
                    fetched_count += len(articles)

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
                                'category': 'web'
                            }
                            self.articles['web'].append(article)

                        except Exception as e:
                            logger.warning(f"Error processing Unsafe.sh article: {str(e)}")
                            continue

            self._log_found('Unsafe.sh', 'web', fetched=fetched_count)

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
        self.scrape_seebug_paper()  # RSS-based; HTML pages remain WAF-blocked (521)
        self.scrape_kanxue()

        # News-focused sources
        self.scrape_anquanke()
        self.scrape_freebuf()
        self.scrape_secrss()
        self.scrape_the_hacker_news()
        self.scrape_security_week()
        self.scrape_securityonline()

        # X (Twitter) accounts configured via x_accounts.txt
        self.scrape_x()

        # Unsafe.sh crawler (only when explicitly enabled)
        if include_unsafe:
            self.scrape_unsafe_sh()

        # Remove duplicates based on URL
        self.remove_duplicates()

        # Filter articles to keep only those published within the last 30 days
        self.filter_recent_articles(days=30)

        logger.info(f"Scraping completed. Collected {len(self.articles['web'])} web articles and {len(self.articles['x'])} X tweets")

    def remove_duplicates(self):
        """Remove duplicate articles based on URL"""
        seen_urls = set()
        unique_web = []
        unique_x = []

        for article in self.articles['web']:
            if article['url'] not in seen_urls:
                seen_urls.add(article['url'])
                unique_web.append(article)

        for article in self.articles['x']:
            if article['url'] not in seen_urls:
                seen_urls.add(article['url'])
                unique_x.append(article)

        self.articles['web'] = unique_web
        self.articles['x'] = unique_x

    def filter_recent_articles(self, days=30):
        """Filter articles to keep only those published within the specified number of days"""
        from datetime import datetime, timedelta

        logger.info(f"Filtering articles to keep only those published within the last {days} days...")

        cutoff_date = datetime.now() - timedelta(days=days)

        # Filter web articles
        filtered_web = []
        for article in self.articles['web']:
            try:
                # Parse the article date
                article_date = datetime.strptime(article['date'], '%Y-%m-%d')

                # Keep only articles newer than cutoff date
                if article_date >= cutoff_date:
                    filtered_web.append(article)
                else:
                    logger.debug(f"Removing old web article: {article['title']} (published on {article['date']})")
            except ValueError:
                # If date parsing fails, keep the article to be safe
                logger.warning(f"Could not parse date for web article: {article['date']}, keeping article")
                filtered_web.append(article)

        # Filter X tweets
        filtered_x = []
        for article in self.articles['x']:
            try:
                # Parse the article date
                article_date = datetime.strptime(article['date'], '%Y-%m-%d')

                # Keep only articles newer than cutoff date
                if article_date >= cutoff_date:
                    filtered_x.append(article)
                else:
                    logger.debug(f"Removing old X tweet: {article['title']} (published on {article['date']})")
            except ValueError:
                # If date parsing fails, keep the article to be safe
                logger.warning(f"Could not parse date for X tweet: {article['date']}, keeping tweet")
                filtered_x.append(article)

        original_counts = {
            'web': len(self.articles['web']),
            'x': len(self.articles['x'])
        }

        self.articles['web'] = filtered_web
        self.articles['x'] = filtered_x

        filtered_counts = {
            'web': len(self.articles['web']),
            'x': len(self.articles['x'])
        }

        logger.info(f"Article filtering completed: {original_counts['web']} -> {filtered_counts['web']} web articles, {original_counts['x']} -> {filtered_counts['x']} X tweets")

    def get_recent_articles(self, days=2):
        """Get web articles from the last N days.

        X tweets are deliberately excluded: AI curation selects in-depth
        articles with reasons, and tweet alerts largely duplicate what the
        web sources already cover (see translate_all for the bilingual
        pass, which DOES include X tweets).
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        recent_articles = []

        for article in self.articles['web']:
            try:
                article_date = datetime.strptime(article['date'], '%Y-%m-%d')
                if article_date >= cutoff_date:
                    recent_articles.append(article)
            except ValueError:
                # Include article if date parsing fails
                recent_articles.append(article)

        logger.info(f"Found {len(recent_articles)} web articles from the last {days} days (X tweets excluded)")
        return recent_articles

    def filter_to_recent_days(self, max_age_days=MAX_ARTICLE_AGE_DAYS):
        """Drop articles published before (today - max_age_days), in place.

        Compared by date string (not datetime) so anything dated yesterday
        survives regardless of the current time of day; articles with an
        unparseable date are kept, and future dates (source timezone skew)
        pass naturally.
        """
        cutoff = (datetime.now() - timedelta(days=max_age_days)).strftime('%Y-%m-%d')
        before = len(self.articles['web']) + len(self.articles['x'])
        for section in ('web', 'x'):
            self.articles[section] = [
                a for a in self.articles[section]
                if not re.match(r'\d{4}-\d{2}-\d{2}$', a.get('date') or '')
                or a['date'] >= cutoff
            ]
        after = len(self.articles['web']) + len(self.articles['x'])
        logger.info(f"Freshness filter (>= {cutoff}): {before} -> {after} articles "
                    f"({before - after} dropped as older than {max_age_days} day(s))")

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

    def save_ai_curated_json(self, curated_data, filename=None):
        """Save AI curated data to a dated archive: docs/ai/<year>/ai_curated_<YYYYMMDD>.json

        An explicit filename (used by tests or one-off exports) overrides the
        dated path.
        """
        if not curated_data:
            logger.warning("No AI curated data to save")
            return

        full_path = filename or _dated_archive_path('ai', 'ai_curated')
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(curated_data, f, ensure_ascii=False, indent=2)

        logger.info(f"AI curated data saved to {full_path}")

    def save_articles_json(self, filename=None):
        """Save articles to a dated archive: docs/data/<year>/articles_<YYYYMMDD>.json"""
        full_path = filename or _dated_archive_path('data', 'articles')
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(self.articles, f, ensure_ascii=False, indent=2)
        logger.info(f"Articles saved to {full_path}")
        self._write_data_manifest()

    def _write_data_manifest(self):
        """Write docs/data/index.json listing every date that has a data file
        (newest first), mirroring the dailycve layout"""
        data_dir = os.path.join(_docs_dir(), 'data')
        dates = []
        if os.path.isdir(data_dir):
            for entry in os.listdir(data_dir):
                year_dir = os.path.join(data_dir, entry)
                if os.path.isdir(year_dir) and entry.isdigit():
                    for fn in os.listdir(year_dir):
                        m = re.match(r'articles_(\d{8})\.json$', fn)
                        if m:
                            s = m.group(1)
                            dates.append(f"{s[:4]}-{s[4:6]}-{s[6:]}")
        dates.sort(reverse=True)

        os.makedirs(data_dir, exist_ok=True)
        manifest_path = os.path.join(data_dir, 'index.json')
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump({'dates': dates}, f, ensure_ascii=False, indent=2)
        logger.info(f"Data manifest saved to {manifest_path}")

    def load_articles_json(self, filename=None):
        """Load articles from the most recent dated archive (or a given file)"""
        if filename is None:
            candidates = []
            data_dir = os.path.join(_docs_dir(), 'data')
            if os.path.isdir(data_dir):
                for entry in os.listdir(data_dir):
                    year_dir = os.path.join(data_dir, entry)
                    if os.path.isdir(year_dir) and entry.isdigit():
                        for fn in os.listdir(year_dir):
                            if re.match(r'articles_\d{8}\.json$', fn):
                                candidates.append(os.path.join(year_dir, fn))
            if not candidates:
                logger.info("No article archives found, starting with empty articles")
                self.articles = {'web': [], 'x': []}
                return
            filename = max(candidates)
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                self.articles = json.load(f)
            logger.info(f"Articles loaded from {filename}")
        except FileNotFoundError:
            logger.info(f"{filename} not found, starting with empty articles")
            self.articles = {'web': [], 'x': []}


def generate_html(articles, output_file=None, ai_curated=None):
    """Generate the client-rendered HTML shell.

    The page carries no article markup: every day (today included) is
    fetched from the JSON archives (data/<year>/articles_*.json and
    ai/<year>/ai_curated_*.json) and rendered by loadNewsDate() in the
    browser. ``articles``/``ai_curated`` are still inspected to decide
    whether the bilingual UI applies.
    """

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

    # The page is a client-rendered shell: no article markup is baked in
    # here. Every day (today included) is fetched from the JSON archives
    # by loadNewsDate() in the browser, so article data lives only in
    # docs/data/ and docs/ai/.

    # Bilingual support: dual-language rendering only kicks in when the
    # articles actually carry translation fields (i.e. an AI key was
    # configured at scrape time). Without them the output is identical
    # to the original single-language page.
    def _has_translation(article):
        """Article has both language versions of the title"""
        return bool(article.get('title_zh')) and bool(article.get('title_en'))

    translations_available = any(
        _has_translation(a) for a in articles['web'] + articles['x']
    )
    curated_bilingual = bool(ai_curated) and any(
        a.get('title_zh') and a.get('title_en')
        for arts in ai_curated.get('categories', {}).values() for a in arts
    )

    def T(zh, en):
        """Static UI label: dual-language spans when bilingual, plain zh otherwise"""
        if translations_available:
            return (f'<span class="lang-zh">{zh}</span>'
                    f'<span class="lang-en">{en}</span>')
        return zh

    # Fragments injected into the template below. Kept as plain (non-f)
    # strings so their braces don't need escaping. Empty when no
    # translations exist -> template renders exactly as before.
    lang_css = ''
    lang_toggle_html = ''
    lang_js = ''
    lang_restore_js = ''

    if translations_available or curated_bilingual:
        lang_css = """
        /* Bilingual content: Chinese by default, English only in EN mode */
        .lang-en { display: none; }
        body.lang-mode-en .lang-zh { display: none; }
        body.lang-mode-en .lang-en { display: inline; }
        """

    if translations_available:
        lang_toggle_html = '''
            <button class="float-btn" id="lang-toggle-btn" onclick="toggleLang()" title="切换到 English" style="font-weight: 700;"><span class="lang-zh">EN</span><span class="lang-en">中</span></button>
        '''
        lang_js = """
        function toggleLang() {
            setLang(currentLang === 'zh' ? 'en' : 'zh');
        }
        function setLang(lang) {
            currentLang = lang;
            document.body.classList.toggle('lang-mode-en', lang === 'en');
            localStorage.setItem('news-lang', lang);
            var langBtn = document.getElementById('lang-toggle-btn');
            if (langBtn) {
                langBtn.title = lang === 'zh' ? '切换到 English' : 'Switch to Chinese';
            }
            var searchInput = document.getElementById('search-input');
            if (searchInput) {
                searchInput.placeholder = t('输入关键词搜索...', 'Type keyword to search...');
            }
            var themeBtn = document.getElementById('theme-toggle');
            if (themeBtn) {
                var dark = document.body.classList.contains('theme-dark');
                themeBtn.title = dark ? t('日间模式', 'Light mode') : t('夜间模式', 'Dark mode');
            }
            var topBtn = document.getElementById('back-to-top');
            if (topBtn) {
                topBtn.title = t('回到顶部', 'Back to top');
            }
            applyFilters();
        }
        """
        lang_restore_js = """
            const savedLang = localStorage.getItem('news-lang');
            if (savedLang === 'en' || savedLang === 'zh') {
                setLang(savedLang);
            }
        """

    # Data date baked into the page: initial value of the subtitle date
    # picker and anchor for resolving the archive URLs of other days.
    update_date = datetime.now().strftime('%Y-%m-%d')

    # Always present so filter JS can stay language-aware; on non-bilingual
    # pages t() simply returns the Chinese text and nothing else changes.
    # NEWS_CURRENT_DATE / CATEGORY_NAME_EN feed the subtitle date switcher.
    lang_i18n_stub = f"""
        var currentLang = 'zh';
        function t(zh, en) {{ return currentLang === 'en' ? en : zh; }}
        var BILINGUAL = {'true' if translations_available else 'false'};
        var SOURCE_NAME_EN = {json.dumps(SOURCE_EN, ensure_ascii=False)};
        var CATEGORY_NAME_EN = {json.dumps(CATEGORY_EN, ensure_ascii=False)};
        var TYPE_LABELS = {json.dumps({'web': {'zh': '媒体文章', 'en': 'Media Articles'}, 'x': {'zh': 'X 推特', 'en': 'X (Twitter)'}}, ensure_ascii=False)};
        window.NEWS_CURRENT_DATE = '{update_date}';
    """

    # Date-switcher JS: loads another day's archive (data/<year>/articles_*
    # + ai/<year>/ai_curated_*) and re-renders cards / AI view / filters /
    # stats client-side. Plain (non-f) string -> braces stay literal. The
    # renderers mirror the Python card/AI markup exactly so applyFilters()
    # and cardSource() keep working unchanged.
    date_switch_js = """
        // ---------- subtitle date switcher (dailycve-style) ----------
        var newsDates = [];                 // manifest dates, newest first
        var currentNewsDate = window.NEWS_CURRENT_DATE;
        var newsLoaded = false;             // true once a day's JSON has rendered
        var AI_CATEGORY_ICONS = {'漏洞研究':'🐛','移动安全':'📱','AI安全':'🤖','威胁情报':'🔍','安全工具':'🔧','云安全':'☁️','其他重要':'⭐'};

        function esc(s) {
            return String(s == null ? '' : s)
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        }
        function dataUrlFor(d) { return 'data/' + d.slice(0, 4) + '/articles_' + d.replace(/-/g, '') + '.json'; }
        function aiUrlFor(d) { return 'ai/' + d.slice(0, 4) + '/ai_curated_' + d.replace(/-/g, '') + '.json'; }

        // Bilingual helpers (all card markup is rendered JS-side now)
        function Tjs(zh, en) {
            return BILINGUAL ? '<span class="lang-zh">' + zh + '</span><span class="lang-en">' + en + '</span>' : zh;
        }
        function dualSpans(zh, en, fallback) {
            return '<span class="lang-zh">' + esc(zh || fallback) + '</span>' +
                   '<span class="lang-en">' + esc(en || fallback) + '</span>';
        }
        function hasTr(a) { return !!(a && a.title_zh && a.title_en); }

        // Helpers for the tweet-style card
        function tweetCardHtml(a) {
            var avatar = a.author_avatar ? '<img class="tweet-avatar" src="' + esc(a.author_avatar) + '" alt="">' : '<span class="tweet-avatar"></span>';
            var displayName = esc(a.author_name || a.author_handle || '');
            var handle = a.author_handle ? '@' + esc(a.author_handle) : '';
            var text = a.description ? esc(a.description.length > 500 ? a.description.slice(0, 500) + '...' : a.description) : '';
            var textHtml = BILINGUAL && (a.description_zh || a.description_en)
                ? dualSpans(a.description_zh, a.description_en, a.description || '')
                : text;
            var meta = BILINGUAL
                ? '<span class="lang-zh">' + handle + ' · ' + esc(a.date) + '</span>' +
                  '<span class="lang-en">' + (a.author_handle ? '@' + esc(a.author_handle) : '') + ' · ' + esc(a.date) + '</span>'
                : handle + ' · ' + esc(a.date);
            return '<div class="tweet-header">' +
                       avatar +
                       '<div class="tweet-author">' +
                           '<div class="tweet-name-line">' +
                               '<span class="tweet-name">' + displayName + '</span>' +
                               '<span class="tweet-badge"></span>' +
                           '</div>' +
                           '<div class="tweet-meta">' + meta + '</div>' +
                       '</div>' +
                   '</div>' +
                   '<p class="tweet-text"><a href="' + esc(a.url) + '" target="_blank">' + textHtml + '</a></p>';
        }

        // The one and only article-card renderer (initial load + date switches)
        function renderCard(a) {
            var bil = BILINGUAL && hasTr(a);
            var src;
            if (BILINGUAL) {
                src = '<div class="article-source"><span class="lang-zh">来源: ' + esc(a.source) + '</span>' +
                      '<span class="lang-en">Source: ' + esc(SOURCE_NAME_EN[a.source] || a.source) + '</span></div>';
            } else {
                src = '<div class="article-source">来源: ' + esc(a.source) + '</div>';
            }
            if (a.category === 'x') {
                return '<div class="article-card tweet-card" data-date="' + esc(a.date) + '" data-category="' + esc(a.category || '') + '" data-source="' + esc(a.source) + '">' + tweetCardHtml(a) + '</div>';
            }
            var title = bil
                ? '<a href="' + esc(a.url) + '" target="_blank">' + dualSpans(a.title_zh, a.title_en, a.title) + '</a>'
                : '<a href="' + esc(a.url) + '" target="_blank">' + esc(a.title) + '</a>';
            var desc = '';
            if (a.description) {
                var d = a.description.length > 500 ? a.description.slice(0, 500) + '...' : a.description;
                desc = bil
                    ? '<p class="article-description">' + dualSpans(a.description_zh, a.description_en, d) + '</p>'
                    : '<p class="article-description">' + esc(d) + '</p>';
            }
            var dateLine = BILINGUAL
                ? '<div class="article-date"><span class="lang-zh">发布日期: </span><span class="lang-en">Date: </span>' + esc(a.date) + '</div>'
                : '<div class="article-date">发布日期: ' + esc(a.date) + '</div>';
            return '<div class="article-card" data-date="' + esc(a.date) + '" data-category="' + esc(a.category || '') + '" data-source="' + esc(a.source) + '">' + src +
                   '<h3 class="article-title">' + title + '</h3>' + desc + dateLine + '</div>';
        }

        // The one and only AI-view renderer (initial load + date switches)
        function renderAiView(c) {
            var el = document.getElementById('ai-view');
            if (!el) return;
            if (!c || !c.categories) {
                el.innerHTML = '<div class="no-ai-data"><p>🤖 AI精选数据暂未生成</p></div>';
                renderAiSidebar(null, '');
                return;
            }
            var bil = false;
            Object.keys(c.categories).forEach(function(k) {
                (c.categories[k] || []).forEach(function(a) { if (a.title_zh && a.title_en) bil = true; });
            });
            function dual(zh, en, fb) {
                return (bil && (zh || en)) ? dualSpans(zh, en, fb) : esc(fb);
            }
            function lbl(zh, en) { return bil ? '<span class="lang-zh">' + zh + '</span><span class="lang-en">' + en + '</span>' : zh; }

            var out = '<div class="ai-summary"><h3>' + lbl('🤖 AI智能分析', '🤖 AI Analysis') +
                ' <span class="model-badge" title="本批次 AI 精选所用模型">' + esc(c.model || 'unknown') + '</span></h3>' +
                '<div class="ai-summary-text">' + dual(c.summary_zh, c.summary_en, c.summary || '') + '</div></div>';

            var nav = '';
            Object.keys(c.categories).forEach(function(name) {
                var arts = c.categories[name] || [];
                if (!arts.length) return;
                var icon = AI_CATEGORY_ICONS[name] || '📌';
                var nameHtml = bil
                    ? '<span class="lang-zh">' + icon + ' ' + esc(name) + '</span><span class="lang-en">' + icon + ' ' + esc(CATEGORY_NAME_EN[name] || name) + '</span>'
                    : icon + ' ' + esc(name);
                var cards = arts.map(function(a) {
                    var titleHtml = dual(a.title_zh, a.title_en, a.title || 'No Title');
                    var meta;
                    if (bil) {
                        meta = '<span><span class="lang-zh">来源: ' + esc(a.source) + '</span><span class="lang-en">Source: ' + esc(SOURCE_NAME_EN[a.source] || a.source) + '</span></span>' +
                               '<span><span class="lang-zh">日期: </span><span class="lang-en">Date: </span>' + esc(a.date) + '</span>';
                    } else {
                        meta = '<span>来源: ' + esc(a.source) + '</span><span>日期: ' + esc(a.date) + '</span>';
                    }
                    var reason = a.reason
                        ? '<div class="ai-article-reason">' + lbl('💡 推荐理由: ', '💡 Reason: ') + dual(a.reason_zh, a.reason_en, a.reason) + '</div>'
                        : '';
                    return '<div class="ai-article"><div class="ai-article-title"><a href="' + esc(a.url) + '" target="_blank">' + titleHtml + '</a></div>' +
                           '<div class="ai-meta">' + meta + '</div>' + reason + '</div>';
                }).join('');
                out += '<div class="ai-category"><h3 class="ai-category-title">' + nameHtml + '</h3>' + cards + '</div>';
                var label = bil
                    ? '<span class="lang-zh">' + icon + ' ' + esc(name) + ' (' + arts.length + ')</span><span class="lang-en">' + icon + ' ' + esc(CATEGORY_NAME_EN[name] || name) + ' (' + arts.length + ')</span>'
                    : icon + ' ' + esc(name) + ' (' + arts.length + ')';
                nav += '<li data-cat="' + esc(name) + '" onclick="scrollToCategory(this.dataset.cat)">' + label + '</li>';
            });
            el.innerHTML = out;
            renderAiSidebar(c, nav);
        }

        function renderAiSidebar(c, nav) {
            var list = document.getElementById('ai-category-nav-list');
            var box = document.getElementById('ai-info-box');
            if (list) list.innerHTML = c ? (nav || '') : '<li style="color: var(--text-3)">暂无分类数据</li>';
            if (!box) return;
            var curated = 0;
            if (c) Object.keys(c.categories || {}).forEach(function(k) { curated += (c.categories[k] || []).length; });
            box.innerHTML =
                '<p>' + Tjs('分析日期', 'Analysis Date') + ': ' + esc(c ? (c.analysis_date || '-') : '-') + '</p>' +
                '<p>' + Tjs('筛选文章', 'Curated') + ': ' + curated + Tjs(' 篇', '') + '</p>' +
                '<p>' + Tjs('原始文章', 'Analyzed') + ': ' + (c ? (c.total_analyzed || 0) : 0) + Tjs(' 篇', '') + '</p>' +
                '<p>' + Tjs('模型来源', 'Model') + ': ' + esc(c ? (c.model || '-') : '-') + '</p>';
        }

        function cardMedium(category) {
            // Old archives have category='tech' or 'news'; all web content maps to 'web'
            return category === 'x' ? 'x' : 'web';
        }

        // Rebuild sidebar filter options from the currently rendered cards
        // (factored out of the original window.onload so date switches reuse it)
        function rebuildFilterOptions() {
            var types = {};
            var sources = {};
            document.querySelectorAll('.article-card').forEach(function(card) {
                types[cardMedium(card.getAttribute('data-category'))] = 1;
                sources[card.getAttribute('data-source') || cardSource(card)] = 1;
            });
            // Fixed display order: web, x (only those present in today's cards)
            var typeOrder = ['web', 'x'].filter(function(c) { return types[c]; });
            var typeDropdown = document.querySelector('#type-select .multi-select-dropdown');
            if (typeDropdown) {
                typeDropdown.innerHTML = typeOrder.map(function(c, i) {
                    var lbl = BILINGUAL
                        ? '<span class="lang-zh">' + esc(TYPE_LABELS[c].zh) + '</span><span class="lang-en">' + esc(TYPE_LABELS[c].en) + '</span>'
                        : esc(TYPE_LABELS[c].zh);
                    return '<div class="multi-select-option"><input type="checkbox" id="type-' + i + '" value="' + c + '"> ' + lbl + '</div>';
                }).join('');
            }
            var dropdown = document.getElementById('source-dropdown');
            if (dropdown) {
                dropdown.innerHTML = '';
                Object.keys(sources).sort().forEach(function(source, i) {
                    var label = BILINGUAL
                        ? '<span class="lang-zh">' + source + '</span><span class="lang-en">' + (SOURCE_NAME_EN[source] || source) + '</span>'
                        : source;
                    dropdown.innerHTML += '<div class="multi-select-option"><input type="checkbox" id="source-' + i + '" value="' + source + '"> ' + label + '</div>';
                });
            }
            document.querySelectorAll('.multi-select-dropdown input[type="checkbox"]').forEach(function(cb) {
                cb.addEventListener('change', applyFilters);
            });
            document.querySelectorAll('.multi-select-dropdown').forEach(function(dd) { dd.classList.remove('show'); });
            var typeHeader = document.querySelector('#type-select .multi-select-header');
            if (typeHeader) typeHeader.textContent = t('全部类型', 'All types');
            var sourceHeader = document.querySelector('#source-select .multi-select-header');
            if (sourceHeader) sourceHeader.textContent = t('全部来源[不包含Unsafe]', 'All sources');
        }

        function updateStats(data) {
            var total = (data.tech || []).length + (data.news || []).length + (data.web || []).length + (data.x || []).length;
            document.getElementById('stat-total').innerHTML = Tjs('总资讯数', 'Total News') + ': ' + total;
            document.getElementById('stat-date').innerHTML = Tjs('更新日期', 'Updated') + ': ' + currentNewsDate;
        }

        function applyNewsDate(data) {
            // Old archives use {tech,news}; new archives use {web,x}. Support both.
            // Web articles first (sorted by date desc), then X tweets at the
            // end as a separate group — the two card styles stay visually
            // distinct instead of interleaved. Each group gets its own
            // section header so the page reads as two titled sections.
            var byDateDesc = function(a, b) { return b.date.localeCompare(a.date); };
            var webArticles = (data.tech || []).concat(data.news || []).concat(data.web || []).slice().sort(byDateDesc);
            var xTweets = (data.x || []).slice().sort(byDateDesc);
            var parts = [];
            if (webArticles.length) {
                parts.push('<div class="articles-section-header" data-category="web">' +
                    Tjs('📰 媒体文章', '📰 Media Articles') +
                    '</div>');
                parts = parts.concat(webArticles.map(renderCard));
            }
            if (xTweets.length) {
                // Section header spanning the full grid width; carries
                // data-category='x' so the type filter hides it together
                // with the tweets when X is unchecked.
                parts.push('<div class="articles-section-header" data-category="x">' +
                    Tjs('𝕏 来自 X', '𝕏 From X') +
                    '</div>');
                parts = parts.concat(xTweets.map(renderCard));
            }
            document.getElementById('articles-grid').innerHTML = parts.join('');
            rebuildFilterOptions();
            updateStats(data);
            applyFilters();
        }

        function loadAiDate(dateStr) {
            fetch(aiUrlFor(dateStr)).then(function(r) { return r.ok ? r.json() : null; })
                .then(renderAiView)
                .catch(function() { renderAiView(null); });
        }

        function loadNewsDate(dateStr) {
            if (!dateStr || (newsLoaded && dateStr === currentNewsDate)) return Promise.resolve(false);
            return fetch(dataUrlFor(dateStr)).then(function(r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            }).then(function(data) {
                currentNewsDate = dateStr;
                newsLoaded = true;
                applyNewsDate(data);
                loadAiDate(dateStr);
                location.hash = dateStr;
                setNewsDateSelect();
                return true;
            }).catch(function(err) {
                console.warn('Failed to load news for ' + dateStr + ':', err);
                if (!newsLoaded) {
                    // Initial load failure: the shell ships no baked-in content
                    var grid = document.getElementById('articles-grid');
                    if (grid) grid.innerHTML = '<div class="grid-message">' + t('⚠️ 资讯数据加载失败，请通过 HTTP 访问本页后刷新', '⚠️ Failed to load data. Serve this page over HTTP and refresh.') + '</div>';
                }
                var sel = document.getElementById('news-date-select');
                if (sel) {
                    sel.value = currentNewsDate;
                    sel.classList.add('load-error');
                    setTimeout(function() { sel.classList.remove('load-error'); }, 1500);
                }
                return false;
            });
        }

        function switchNewsDate(v) { loadNewsDate(v); }

        // newsDates is newest-first: › (delta=+1) moves toward newer, ‹ toward older
        function stepNewsDate(delta) {
            var idx = newsDates.indexOf(currentNewsDate);
            if (idx === -1) return;
            var target = newsDates[idx - delta];
            if (target) loadNewsDate(target);
        }

        function setNewsDateSelect() {
            var sel = document.getElementById('news-date-select');
            if (sel) sel.value = currentNewsDate;
            var idx = newsDates.indexOf(currentNewsDate);
            var prev = document.getElementById('news-date-prev');   // older
            var next = document.getElementById('news-date-next');   // newer
            if (prev) prev.disabled = idx === -1 || idx >= newsDates.length - 1;
            if (next) next.disabled = idx <= 0;
        }

        // Browser back/forward between visited dates
        window.addEventListener('hashchange', function() {
            var d = decodeURIComponent(location.hash.replace(/^#/, ''));
            if (d && d !== currentNewsDate && newsDates.indexOf(d) !== -1) loadNewsDate(d);
        });
    """

    # Floating controls + dark theme work on every page (no API key needed)
    static_css = """
        /* Floating controls: theme + language (top-right), back-to-top (bottom-right) */
        .float-controls {
            position: fixed;
            top: 16px;
            right: 16px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            z-index: 1000;
        }
        .float-btn {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            border: 1px solid var(--float-btn-border);
            background: var(--float-btn-bg);
            color: var(--float-btn-fg);
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            cursor: pointer;
            font-size: 1.05rem;
            line-height: 1;
            transition: all 0.2s ease;
        }
        .float-btn:hover {
            transform: translateY(-2px);
            background: var(--float-btn-bg-hover);
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }
        .float-btn.active {
            outline: 2px solid var(--accent);
            outline-offset: 2px;
        }
        #back-to-top {
            position: fixed;
            bottom: 24px;
            right: 16px;
            width: 44px;
            height: 44px;
            border-radius: 50%;
            border: none;
            background: var(--accent);  /* dailycve --ai-accent */
            color: var(--accent-on);
            font-size: 1.3rem;
            cursor: pointer;
            box-shadow: 0 4px 10px rgba(0,0,0,0.25);
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.3s ease, visibility 0.3s ease;
            z-index: 1000;
        }
        #back-to-top.show {
            opacity: 1;
            visibility: visible;
        }

        /* Grid-level status line (loading / load error): the shell's
           placeholder inside the articles grid and the AI view */
        .grid-message {
            grid-column: 1 / -1;
            padding: 56px 0;
            text-align: center;
            color: var(--text-3);
            font-size: 15px;
        }

        /* Dark theme: colors flip via the CSS variables declared on
           body.theme-dark (see :root token block above) — no per-element
           overrides needed. Only the toggle-icon visibility rules remain. */
        .theme-icon-sun { display: none; }
        body.theme-dark .theme-icon-moon { display: none; }
        body.theme-dark .theme-icon-sun { display: inline; }

        /* GitHub corner ribbon (top-left) — the standard top-right ribbon
           SVG mirrored into the top-left corner, same as dailycve */
        .github-corner-svg {
            fill: #24292e;
            color: #ffffff;
            position: fixed;
            top: 0;
            left: 0;
            border: 0;
            transform: translateX(80px) scaleX(-1);
            transform-origin: 0 0;
            z-index: 1000;
            transition: fill 0.3s ease;
        }
        body.theme-dark .github-corner-svg {
            fill: #d1d5db;
            color: #1f2937;
        }
        .github-corner:hover .octo-arm { animation: octocat-wave 560ms ease-in-out; }
        @keyframes octocat-wave {
            0%, 100% { transform: rotate(0); }
            20%, 60% { transform: rotate(-25deg); }
            40%, 80% { transform: rotate(10deg); }
        }
        @media (max-width: 500px) {
            .github-corner:hover .octo-arm { animation: none; }
            .github-corner .octo-arm { animation: octocat-wave 560ms ease-in-out; }
        }

        /* Subtitle date picker: typography, not chrome (dailycve-style).
           Dark theme adapts automatically via currentColor inheritance. */
        .subtitle .title-date {
            display: inline-flex;
            align-items: center;
            gap: 2px;
        }
        .subtitle #news-date-select {
            font-size: inherit;
            font-family: inherit;
            font-weight: 600;
            color: inherit;
            background: transparent;
            border: none;
            border-bottom: 2px solid transparent;
            border-radius: 0;
            /* no top padding: keeps the date on the subtitle's baseline;
               the 2px bottom padding reserves room for the hover underline */
            padding: 0 2px 2px;
            line-height: inherit;
            cursor: pointer;
            transition: border-color 0.2s ease;
        }
        .subtitle #news-date-select:hover,
        .subtitle #news-date-select:focus {
            border-bottom-color: currentColor;
            outline: none;
        }
        .subtitle #news-date-select.load-error { border-bottom-color: var(--danger); }
        .date-nav-btn {
            width: 16px;
            height: 16px;
            border: none;
            border-radius: 4px;
            background: transparent;
            color: inherit;
            font-size: 0.8rem;
            line-height: 1;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            opacity: 0.45;
            transition: opacity 0.2s ease;
        }
        .subtitle .title-date:hover .date-nav-btn,
        .date-nav-btn:focus { opacity: 1; }
        .date-nav-btn:disabled { opacity: 0.15; cursor: default; }

        /* Mobile: sidebar becomes a slide-in drawer opened by the ☰ button */
        #sidebar-backdrop {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.5);
            z-index: 1050;
        }
        #sidebar-toggle {
            display: none;
        }
        .sidebar-close {
            display: none;
        }
        @media (max-width: 768px) {
            #sidebar-toggle {
                display: block;
            }
            /* The inline sidebar is redundant on mobile now that the ☰
               button opens it as a centered dialog - hide it from the
               page flow; body.sidebar-open re-displays it as the popup */
            .sidebar {
                display: none;
            }
            body.sidebar-open #sidebar-backdrop {
                display: block;
            }
            body.sidebar-open {
                overflow: hidden;
            }
            body.sidebar-open .sidebar {
                display: block;
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                width: min(90vw, 400px);
                max-height: 85vh;
                margin: 0;
                overflow-y: auto;
                z-index: 1100;
                box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
                padding-top: 3rem;
            }
            body.sidebar-open .sidebar-close {
                display: block;
                position: absolute;
                top: 12px;
                right: 12px;
                width: 32px;
                height: 32px;
                border: 1px solid var(--float-btn-border);
                border-radius: 50%;
                background: var(--float-btn-bg);
                color: var(--float-btn-fg);
                font-size: 1rem;
                cursor: pointer;
            }
        }
    """
    static_js = """
        function toggleTheme() {
            var dark = document.body.classList.toggle('theme-dark');
            localStorage.setItem('news-theme', dark ? 'dark' : 'light');
            var btn = document.getElementById('theme-toggle');
            btn.title = dark ? t('日间模式', 'Light mode') : t('夜间模式', 'Dark mode');
        }
        function scrollToTop() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        window.addEventListener('scroll', function() {
            document.getElementById('back-to-top').classList.toggle('show', window.scrollY > 600);
        });
        function toggleSidebar(forceOpen) {
            var open = typeof forceOpen === 'boolean'
                ? forceOpen
                : !document.body.classList.contains('sidebar-open');
            document.body.classList.toggle('sidebar-open', open);
        }
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') toggleSidebar(false);
        });
    """

    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>网络安全资讯聚合 - Cybersecurity News Aggregator</title>
    <style>
        /* Design tokens: one palette, two themes. Light values on :root,
           dark values flipped by body.theme-dark - rules below reference
           the vars, so dark mode needs no per-element color overrides. */
        :root {{
            --page-bg: #f8f9fa;
            --card-bg: #ffffff;
            --text-1: #1f2937;      /* headings */
            --text-2: #4b5563;      /* body copy */
            --text-3: #6b7280;      /* secondary: sources, dates, footer */
            --border-strong: #d1d5db;
            --border-weak: #e5e7eb;
            --fill-subtle: #f3f4f6; /* inset fills, hover wells */
            --accent: #1d9bf0;      /* solid accent: badges, header rule (X blue) */
            --accent-text: #0c7ab8; /* text links (AA on white) */
            --accent-hover: #0c7ab8;
            --accent-on: #ffffff;  /* text on accent-filled surfaces */
            --danger: #d32f2f;
            --scrollbar-thumb: #c1c1c1;
            --scrollbar-track: #f1f1f1;
            --float-btn-bg: #ffffff;
            --float-btn-fg: #333333;
            --float-btn-border: transparent;
            --float-btn-bg-hover: #ffffff;
        }}
        body.theme-dark {{
            --page-bg: #1a1d24;
            --card-bg: #22262f;
            --text-1: #d8dce3;
            --text-2: #c2c8d4;
            --text-3: #8b93a1;
            --border-strong: #343a46;
            --border-weak: #2a303c;
            --fill-subtle: #14171c;
            --accent: #4aa8e8;
            --accent-text: #7bc5f2;
            --accent-hover: #9dd6f7;
            --accent-on: #14171c;  /* dark text: light accent fills need it for contrast */
            --danger: #ef5350;
            --scrollbar-thumb: #4a5160;
            --scrollbar-track: #1a1e25;
            --float-btn-bg: #2a303c;
            --float-btn-fg: #e2e6ee;
            --float-btn-border: #414a5c;
            --float-btn-bg-hover: #333b49;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: var(--text-2);
            background-color: var(--page-bg);
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
            /* One sheet: header + article lists live on a single card,
               mirroring the dailycve layout (sidebar is its own card) */
            background: var(--card-bg);
            padding: 1.5rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            /* Grid item: allow shrinking below min-content so long
               unbreakable words cannot push cards past the viewport */
            min-width: 0;
        }}

        .sidebar {{
            grid-column: 2;
            background: var(--card-bg);
            padding: 1.5rem;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            height: fit-content;
            position: sticky;
            top: 20px;
            max-height: 90vh;  /* dailycve-style: cap so the sticky card never
                                  outgrows the viewport and slides cleanly to
                                  bottom-align with the main card */
            overflow-y: auto;  /* tall filter lists scroll inside the card */
        }}

        /* Slim inner scrollbar for the sidebar (dailycve-style) */
        .sidebar::-webkit-scrollbar {{ width: 8px; }}
        .sidebar::-webkit-scrollbar-track {{ background: var(--scrollbar-track); border-radius: 4px; }}
        .sidebar::-webkit-scrollbar-thumb {{ background: var(--scrollbar-thumb); border-radius: 4px; }}
        .sidebar::-webkit-scrollbar-thumb:hover {{ background: var(--scrollbar-thumb); filter: brightness(0.85); }}
        .sidebar {{ scrollbar-width: thin; scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track); }}

        header {{
            /* dailycve-style editorial header: sits inside the main-content
               card, an accent rule separating the headline from the content */
            text-align: center;
            padding: 0.5rem 0 15px;
            margin-bottom: 2rem;
            border-bottom: 3px solid var(--accent);
        }}

        h1 {{
            font-size: 2.2em;  /* match dailycve h1 */
            color: var(--text-1);
            margin-bottom: 0.5rem;
        }}

        .subtitle {{
            font-size: 1.1rem;
            color: var(--text-3);
        }}

        .filters {{
            background: var(--card-bg);
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
            color: var(--text-2);
        }}

        .filter-group select, .filter-group input {{
            width: 100%;
            padding: 0.5rem;
            border: 1px solid var(--border-strong);
            border-radius: 4px;
            font-size: 0.9rem;
            background: var(--fill-subtle);
            color: var(--text-1);
        }}

        .multi-select {{
            position: relative;
            width: 100%;
        }}

        .multi-select-header {{
            width: 100%;
            padding: 0.5rem;
            border: 1px solid var(--border-strong);
            border-radius: 4px;
            background: var(--card-bg) url('data:image/svg+xml;charset=UTF-8,<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 12 12"><path fill="%23666" d="M2 4l4 4 4-4"/></svg>') no-repeat right 0.5rem center;
            cursor: pointer;
            font-size: 0.9rem;
            color: var(--text-2);
        }}

        .multi-select-dropdown {{
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: var(--card-bg);
            border: 1px solid var(--border-strong);
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
            background: var(--fill-subtle);
        }}

        .stats {{
            background: var(--card-bg);
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
            margin-bottom: 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}

        .category-section {{
            margin-bottom: 3rem;
        }}

        .articles-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 1.5rem;
        }}

        /* Section header for each card group (Media Articles / From X).
           Spans the full grid row; font-size matches .ai-category-title
           so the two views read at the same heading scale. No underline —
           the page <h1> already carries the accent rule. */
        .articles-section-header {{
            grid-column: 1 / -1;
            margin-top: 1.5rem;
            color: var(--text-1);
            font-size: 1.4rem;
            font-weight: 700;
        }}
        /* First group sits at the top of the grid — no extra top gap */
        .articles-grid > .articles-section-header:first-of-type {{
            margin-top: 0;
        }}

        .article-card {{
            background: var(--card-bg);
            border: 1px solid var(--border-weak);  /* dailycve-style: border separates inner cards on the white sheet */
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
            height: 100%;
            display: flex;
            flex-direction: column;
            /* Grid/flex items default to min-width:auto, so a long URL or
               CVE id would overflow the card past the screen edge on
               mobile; allow the card to shrink and long words to wrap */
            min-width: 0;
            overflow-wrap: break-word;
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
            color: var(--text-3);
            margin-bottom: 0.5rem;
        }}

        .article-title {{
            font-size: 1.1rem;
            margin-bottom: 0.75rem;
            color: var(--text-1);
        }}

        .article-title a {{
            color: var(--accent-text);
            text-decoration: none;
        }}

        .article-title a:hover {{
            color: var(--accent-hover);
            text-decoration: underline;
        }}

        .article-description {{
            color: var(--text-2);
            font-size: 0.95rem;
            margin-bottom: 1rem;
            flex-grow: 1;
        }}

        .article-date {{
            font-size: 0.85rem;
            color: var(--text-3);
        }}

        .footer {{
            text-align: center;
            padding: 2rem 0;
            color: var(--text-3);
            font-size: 0.9rem;
            margin-top: 3rem;
        }}

        .footer a {{
            color: var(--accent-text);
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
                /* single-column flow: no sticky card, so no viewport cap */
                height: auto;
                max-height: none;
                overflow-y: visible;
            }}
        }}

        @media (max-width: 768px) {{
            .container {{
                padding: 10px;
            }}

            .main-content {{
                padding: 1rem;  /* slimmer than the 1.5rem desktop padding, dailycve-style */
            }}

            h1 {{
                font-size: 1.75em;
            }}

            .articles-grid {{
                grid-template-columns: 1fr;
            }}
        }}

        /* View toggle buttons - segmented control style */
        .view-toggle {{
            display: inline-flex;
            background: var(--fill-subtle);
            border-radius: 24px;
            padding: 4px;
            margin-bottom: 1rem;
        }}

        .view-toggle-btn {{
            padding: 8px 16px;
            border: none;
            background: transparent;
            color: var(--text-3);
            border-radius: 20px;
            cursor: pointer;
            font-size: 0.9rem;
            font-weight: 600;
            transition: all 0.2s ease;
        }}

        .view-toggle-btn:hover {{
            color: var(--text-2);
        }}

        .view-toggle-btn.active {{
            background: var(--card-bg);
            color: var(--accent);
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
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
            background: var(--card-bg);
            border-radius: 8px;
            padding: 1rem;
        }}

        .ai-category-nav h4 {{
            margin-bottom: 0.75rem;
            color: var(--text-2);
        }}

        .ai-category-nav ul {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}

        .ai-category-nav li {{
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--border-weak);
            cursor: pointer;
            color: var(--accent-text);
            transition: all 0.2s ease;
        }}

        .ai-category-nav li:hover {{
            color: var(--accent-hover);
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
            color: var(--text-2);
            margin-bottom: 1rem;
            padding-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .ai-summary {{
            padding: 0.5rem 0 1.5rem 0;
            margin-bottom: 2rem;
        }}

        .ai-summary h3 {{
            margin-bottom: 0.75rem;
            color: var(--text-1);
            font-size: 1.2rem;
            font-weight: 600;
        }}

        .ai-summary-text {{
            color: var(--text-2);
            line-height: 1.7;
            padding-left: 1rem;
            border-left: 3px solid var(--accent);
        }}

        .model-badge {{
            display: inline-block;
            background: var(--accent);  /* dailycve --ai-badge-bg */
            color: var(--accent-on);
            font-size: 0.7rem;
            padding: 3px 12px;
            border-radius: 12px;
            font-weight: 500;
            margin-left: 10px;
            vertical-align: middle;
            letter-spacing: 0.3px;
            box-shadow: 0 1px 3px rgba(29, 155, 240, 0.3);
        }}

        .ai-article {{
            background: var(--card-bg);
            border: 1px solid var(--border-weak);  /* same inner-card border as .article-card */
            border-radius: 8px;
            padding: 1.5rem;
            margin-bottom: 1rem;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
            min-width: 0;
            overflow-wrap: break-word;
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
            color: var(--accent-text);
            text-decoration: none;
        }}

        .ai-article-title a:hover {{
            text-decoration: underline;
        }}

        .ai-article-reason {{
            color: var(--text-3);
            font-size: 0.9rem;
            margin-top: 0.5rem;
            padding-top: 0.5rem;
        }}

        .ai-meta {{
            display: flex;
            gap: 1rem;
            color: var(--text-3);
            font-size: 0.85rem;
        }}

        .no-ai-data {{
            text-align: center;
            padding: 2rem;
            color: var(--text-3);
            background: var(--fill-subtle);
            border-radius: 8px;
        }}

        .ai-info-box {{
            margin-top: 1rem;
            padding: 0.5rem;
            background: var(--fill-subtle);
            border-radius: 4px;
            font-size: 0.85rem;
            color: var(--text-3);
        }}

        /* Tweet-style card (X source) */
        .tweet-card {{
            /* No top accent border — keep tweet cards visually consistent
               with web article cards; the 𝕏 badge is enough identity. */
        }}
        .tweet-header {{
            display: flex;
            align-items: flex-start;
            gap: 0.75rem;
            margin-bottom: 0.75rem;
        }}
        .tweet-avatar {{
            width: 42px;
            height: 42px;
            min-width: 42px;
            border-radius: 50%;
            object-fit: cover;
            background: var(--fill-subtle);
            border: 1px solid var(--border-weak);
        }}
        .tweet-author {{
            flex: 1;
            min-width: 0;
        }}
        .tweet-name-line {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}
        .tweet-name {{
            font-weight: 700;
            color: var(--text-1);
            font-size: 0.98rem;
        }}
        .tweet-badge {{
            display: inline-block;
            font-size: 0.7rem;
            font-weight: 700;
            color: #fff;
            background: #1d9bf0;
            border-radius: 4px;
            padding: 1px 6px;
            letter-spacing: 0.05em;
        }}
        .tweet-badge::before {{
            content: "𝕏";
        }}
        .tweet-meta {{
            color: var(--text-3);
            font-size: 0.85rem;
            margin-top: 2px;
        }}
        .tweet-text {{
            color: var(--text-2);
            font-size: 0.95rem;
            line-height: 1.6;
            flex-grow: 1;
            overflow-wrap: break-word;
        }}
        .tweet-text a {{
            color: inherit;
            text-decoration: none;
        }}
        .tweet-text a:hover {{
            color: var(--accent-hover);
        }}
    {static_css}{lang_css}</style>
</head>
<body>
    <noscript>
        <div style="max-width: 640px; margin: 24px auto; padding: 14px 20px; text-align: center; border: 1px solid #d32f2f; border-radius: 8px; color: #d32f2f;">
            本页资讯数据由 JavaScript 从 JSON 加载，请启用 JavaScript 后刷新 / JavaScript is required to load the news data.
        </div>
    </noscript>
    <script>
        // Apply saved theme (falling back to the system preference) and saved
        // language BEFORE first paint to avoid a light-theme flash on dark pages
        (function () {{
            var theme = null;
            try {{ theme = localStorage.getItem('news-theme'); }} catch (e) {{}}
            var dark = theme === 'dark' ||
                (!theme && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
            if (dark) document.body.classList.add('theme-dark');
            try {{
                if (localStorage.getItem('news-lang') === 'en') {{
                    document.body.classList.add('lang-mode-en');
                }}
            }} catch (e) {{}}
        }})();
    </script>
    <!-- GitHub corner ribbon (top-left), same as dailycve -->
    <a href="https://github.com/secnotes/secnews" class="github-corner" aria-label="View source on GitHub">
        <svg width="80" height="80" viewBox="0 0 250 250" class="github-corner-svg" aria-hidden="true">
            <path d="M0,0 L115,115 L130,115 L142,142 L250,250 L250,0 Z" class="github-corner-bg"></path>
            <path d="M128.3,109.0 C113.8,99.7 119.0,89.6 119.0,89.6 C122.0,82.7 120.5,78.6 120.5,78.6 C119.2,72.0 123.4,76.3 123.4,76.3 C127.3,80.9 125.5,87.3 125.5,87.3 C122.9,97.6 130.6,101.9 134.4,103.2" fill="currentColor" style="transform-origin: 130px 106px;" class="octo-arm"></path>
            <path d="M115.0,115.0 C114.9,115.1 118.7,116.5 119.8,115.4 L133.7,101.6 C136.9,99.2 139.9,98.4 142.2,98.6 C133.8,88.0 127.5,74.4 143.8,58.0 C148.5,53.4 154.0,51.2 159.7,51.0 C160.3,49.4 163.2,43.6 171.4,40.1 C171.4,40.1 176.1,42.5 178.8,56.2 C183.1,58.6 187.2,61.8 190.9,65.4 C194.5,69.0 197.7,73.2 200.1,77.6 C213.8,80.2 216.3,84.9 216.3,84.9 C212.7,93.1 206.9,96.0 205.4,96.6 C205.1,102.4 203.0,107.8 198.3,112.5 C181.9,128.9 168.3,122.5 157.7,114.1 C157.9,116.9 156.7,120.9 152.7,124.9 L141.0,136.5 C139.8,137.7 141.6,141.9 141.8,141.8 Z" fill="currentColor" class="octo-body"></path>
        </svg>
    </a>
    <!-- Floating controls: sidebar drawer (mobile only), theme, language -->
    <div class="float-controls">
        <button class="float-btn" id="sidebar-toggle" onclick="toggleSidebar()" title="筛选面板 / Filters">☰</button>
        <button class="float-btn" id="theme-toggle" onclick="toggleTheme()" title="夜间模式">
            <span class="theme-icon-moon">🌙</span><span class="theme-icon-sun">☀️</span>
        </button>
        {lang_toggle_html}
    </div>
    <button id="back-to-top" onclick="scrollToTop()" title="Back to top / 回到顶部">↑</button>
    <div id="sidebar-backdrop" onclick="toggleSidebar(false)"></div>
    <div class="container">
        <main class="main-content">
            <header>
                <h1>🛡️ {T('网络安全资讯聚合', 'Cybersecurity News')}</h1>
                <div class="subtitle">{T('汇聚最新网络安全资讯 · 更新于 ', 'Latest security news · Updated ')}<span class="title-date"><button class="date-nav-btn" id="news-date-prev" onclick="stepNewsDate(-1)" aria-label="前一天 / Previous day">‹</button><select id="news-date-select" onchange="switchNewsDate(this.value)" aria-label="报告日期 / Report date"></select><button class="date-nav-btn" id="news-date-next" onclick="stepNewsDate(1)" aria-label="后一天 / Next day">›</button></span></div>
            </header>

            <!-- View Toggle Buttons -->
            <!-- Original View (All Articles) -->
            <div class="original-view" id="original-view">
            <div class="category-section">
                <div class="articles-grid" id="articles-grid">
                    <div class="grid-message">{T('⏳ 正在加载资讯…', '⏳ Loading news…')}</div>
                </div>
            </div>
            </div>

            <!-- AI Curated View -->
            <div class="ai-view" id="ai-view">
                <div class="grid-message">{T('⏳ 正在加载AI精选…', '⏳ Loading AI picks…')}</div>
            </div>
        </main>

        <aside class="sidebar">
            <button class="sidebar-close" onclick="toggleSidebar(false)" title="关闭 / Close">✕</button>
            <!-- View Toggle Buttons -->
            <div class="view-toggle">
                <button class="view-toggle-btn" onclick="switchView('ai')">{T('🤖 AI精选', '🤖 AI Curated')}</button>
                <button class="view-toggle-btn active" onclick="switchView('original')">{T('📚 全部资讯', '📚 All News')}</button>
            </div>

            <!-- Original Sidebar (Filters) -->
            <div class="sidebar-section" id="original-sidebar">
                <div class="filters">
                    <div class="filter-group">
                        <label>{T('🏷️ 按类型筛选:', '🏷️ Filter by Type:')}</label>
                        <div class="multi-select" id="type-select">
                            <div class="multi-select-header" onclick="toggleDropdown('type-select')">{T('全部类型', 'All types')}</div>
                            <div class="multi-select-dropdown"></div>
                        </div>
                    </div>

                    <div class="filter-group">
                        <label>{T('🏢 按来源筛选:', '🏢 Filter by Source:')}</label>
                        <div class="multi-select" id="source-select">
                            <div class="multi-select-header" onclick="toggleDropdown('source-select')">全部来源[不包含Unsafe]</div>
                            <div class="multi-select-dropdown" id="source-dropdown"></div>
                        </div>
                    </div>

                    <div class="filter-group">
                        <label for="search-input">{T('🔍 搜索关键词:', '🔍 Search:')}</label>
                        <input type="text" id="search-input" placeholder="输入关键词搜索..." onkeyup="applyFilters()">
                    </div>

                    <button onclick="clearAllFilters()" style="margin-top: 10px; padding: 8px 16px; background: var(--fill-subtle); color: var(--text-2); border: 1px solid var(--border-strong); border-radius: 4px; cursor: pointer;">{T('清除筛选', 'Clear Filters')}</button>
                </div>

                <div style="margin-top: 1.5rem;">
                    <h4>{T('统计信息', 'Statistics')}</h4>
                    <p id="visible-count">{T('当前显示', 'Showing')}: 0</p>
                    <p id="stat-total">{T('总资讯数', 'Total News')}: 0</p>
                    <p id="stat-date">{T('更新日期', 'Updated')}: {update_date}</p>
                </div>
            </div>

            <!-- AI Sidebar (Category Navigation) -->
            <div class="sidebar-section hidden" id="ai-sidebar">
                <div class="ai-category-nav">
                    <h4>{T('📋 分类目录', '📋 Categories')}</h4>
                    <ul id="ai-category-nav-list">
                        <li style="color: var(--text-3)">…</li>
                    </ul>
                </div>
                <div class="ai-info-box" id="ai-info-box">
                    <p>{T('分析日期', 'Analysis Date')}: -</p>
                    <p>{T('筛选文章', 'Curated')}: 0{T(' 篇', '')}</p>
                    <p>{T('原始文章', 'Analyzed')}: 0{T(' 篇', '')}</p>
                    <p>{T('模型来源', 'Model')}: -</p>
                </div>
            </div>
        </aside>
    </div>

    <!-- Footer sits OUTSIDE .container (dailycve-style): the sticky
         sidebar is constrained by the container's content box, so an
         in-grid footer row would let the slid-down sidebar invade it -->
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
                <a href="https://github.com/secnotes/secnews/tree/main/docs/data" target="_blank">
                    📄 Json data
                </a>
            </p>
            <p>{T('安全资讯聚合平台', 'Security News Aggregator')} | {T('更新时间', 'Updated')}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            <p>{T('数据来源', 'Sources')}: {('<span class="lang-zh">Sec-Today, 先知社区, Project Zero, Seebug Paper, 腾讯安全, 安全客, 安全内参, SecurityWeek, The Hacker News, 看雪</span><span class="lang-en">Sec-Today, Xianzhi, Project Zero, Seebug Paper, Tencent Security, Anquanke, SecRSS, SecurityWeek, The Hacker News, Kanxue</span>' if translations_available else 'Sec-Today, 先知社区, Project Zero, Seebug Paper, 腾讯安全, 安全客, 安全内参, SecurityWeek, The Hacker News, 看雪')}</p>
            <p>{T('如有侵权，请联系删除', 'Contact us for removal if any content infringes copyright')}</p>
    </div>

    <script>
        {lang_i18n_stub}
        {static_js}
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

        {lang_js}
        function cardSource(card) {{
            // All rendered cards carry a data-source attribute; fall back to
            // the DOM for safety (bilingual pages keep the source in a span)
            if (card.dataset && card.dataset.source) return card.dataset.source;
            var el = card.querySelector('.article-source');
            if (!el) return '';
            var zh = el.querySelector('.lang-zh');
            return (zh || el).textContent.replace('来源: ', '');
        }}

        {date_switch_js}

        window.onload = function() {{
            {lang_restore_js}
            // 日期清单来自 data/index.json；hash 深链优先。页面不含文章
            // 数据 —— 当天也一样走 loadNewsDate() fetch 渲染。
            fetch('data/index.json').then(function(r) {{ return r.ok ? r.json() : null; }}).then(function(m) {{
                newsDates = (m && m.dates && m.dates.length) ? m.dates : [window.NEWS_CURRENT_DATE];
                var sel = document.getElementById('news-date-select');
                if (sel) sel.innerHTML = newsDates.map(function(d) {{ return '<option value="' + d + '">' + d + '</option>'; }}).join('');
                setNewsDateSelect();
                var hash = decodeURIComponent(location.hash.replace(/^#/, ''));
                loadNewsDate(newsDates.includes(hash) ? hash : currentNewsDate);
            }}).catch(function() {{
                newsDates = [window.NEWS_CURRENT_DATE];
                setNewsDateSelect();
                loadNewsDate(currentNewsDate);
            }});
        }};

        function applyFilters() {{
            const selectedTypes = Array.from(document.querySelectorAll('#type-select input:checked')).map(cb => cb.value);
            const selectedSources = Array.from(document.querySelectorAll('#source-select input:checked')).map(cb => cb.value);
            const searchTerm = document.getElementById('search-input').value.toLowerCase();

            // 更新下拉框标题
            document.querySelector('#type-select .multi-select-header').textContent = selectedTypes.length ? (selectedTypes.length > 1 ? selectedTypes.length + t('项已选', ' selected') : (currentLang === 'en' ? TYPE_LABELS[selectedTypes[0]].en : TYPE_LABELS[selectedTypes[0]].zh)) : t('全部类型', 'All types');
            document.querySelector('#source-select .multi-select-header').textContent = selectedSources.length ? (selectedSources.length > 1 ? selectedSources.length + t('项已选', ' selected') : (currentLang === 'en' ? (SOURCE_NAME_EN[selectedSources[0]] || selectedSources[0]) : selectedSources[0])) : t('全部来源[不包含Unsafe]', 'All sources');

            // 筛选文章
            let visibleCount = 0;
            document.querySelectorAll('.article-card').forEach(card => {{
                const medium = cardMedium(card.getAttribute('data-category'));
                const cardSource = window.cardSource(card);
                const titleEl = card.querySelector('.article-title');
                const title = titleEl ? titleEl.textContent.toLowerCase() : '';
                const descEl = card.querySelector('.article-description') || card.querySelector('.tweet-text');
                const desc = descEl ? descEl.textContent.toLowerCase() : '';

                const match = (selectedTypes.length === 0 || selectedTypes.includes(medium)) &&
                             (selectedSources.length === 0 || selectedSources.includes(cardSource)) &&
                             (searchTerm === '' || title.includes(searchTerm) || desc.includes(searchTerm)) &&
                             (selectedSources.includes('Unsafe.sh') || cardSource !== 'Unsafe.sh');
                card.style.display = match ? 'flex' : 'none';
                if (match) visibleCount++;
            }});
            // X section header: hide when X is filtered out, or when no X
            // tweet is visible (search/source narrowed it to zero)
            document.querySelectorAll('.articles-section-header').forEach(function(h) {{
                var medium = cardMedium(h.getAttribute('data-category'));
                // Header shows only if its medium passes the type filter AND
                // at least one card of that medium is visible (search/source
                // may have narrowed it to zero — hide the header then)
                var anyVisible = false;
                document.querySelectorAll('.article-card').forEach(function(c) {{
                    if (cardMedium(c.getAttribute('data-category')) === medium && c.style.display !== 'none') anyVisible = true;
                }});
                var show = (selectedTypes.length === 0 || selectedTypes.includes(medium)) && anyVisible;
                h.style.display = show ? 'block' : 'none';
            }});
            document.getElementById('visible-count').textContent = t('当前显示: ', 'Showing: ') + visibleCount;
        }}

        function clearAllFilters() {{
            document.querySelectorAll('.multi-select input[type="checkbox"]').forEach(cb => cb.checked = false);
            document.getElementById('search-input').value = '';
            document.querySelector('#type-select .multi-select-header').textContent = t('全部类型', 'All types');
            document.querySelector('#source-select .multi-select-header').textContent = t('全部来源[不包含Unsafe]', 'All sources');
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
    parser.add_argument('--no-translate', action='store_true',
                        help='Disable AI translation even when an API key is available')
    args = parser.parse_args()

    aggregator = SecurityNewsAggregator()

    # Scrape all sources (unsafe crawler only enabled with --unsafe flag)
    aggregator.scrape_all_sources(include_unsafe=args.unsafe)

    # Keep only fresh articles so each dated archive (and thus each day's
    # view in the date picker) holds today's + yesterday's items only
    aggregator.filter_to_recent_days()

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

    # AI translation (automatic when an API key is available; silently
    # skipped otherwise so behavior without a key is unchanged)
    translated = False
    if not args.no_translate:
        translated = translate_all(
            aggregator.articles,
            curated=ai_curated,
            api_key=args.ai_key,
            model=args.ai_model,
            base_url=args.ai_base_url,
        )
        if translated:
            # Re-save the data files, now carrying bilingual fields
            aggregator.save_articles_json()
            if ai_curated:
                aggregator.save_ai_curated_json(ai_curated)

    # Generate HTML page (this will go to project root docs directory)
    generate_html(aggregator.articles, ai_curated=ai_curated)

    print(f"\n完成！共收集到:")
    print(f"- 网站文章: {len(aggregator.articles['web'])} 篇")
    print(f"- X 推文: {len(aggregator.articles['x'])} 篇")
    if ai_curated:
        total_curated = sum(len(arts) for arts in ai_curated.get('categories', {}).values())
        print(f"- AI精选: {total_curated} 篇")
    if translated:
        print("- 双语翻译: 已启用 (网页支持 中文/English 切换)")
    print(f"已生成 docs/index.html 文件")
    now = datetime.now()
    print(f"数据存档: docs/data/{now.year}/articles_{now.strftime('%Y%m%d')}.json")
    if ai_curated:
        print(f"AI精选存档: docs/ai/{now.year}/ai_curated_{now.strftime('%Y%m%d')}.json")


if __name__ == "__main__":
    main()