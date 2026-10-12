#!/usr/bin/env python3
"""
Static RSS Feed Generator
Writes daily-digest, language-specific RSS 2.0 feeds from the current
run's data:

- docs/feed.xml        / docs/feed_zh.xml      - all articles (en / zh)
- docs/ai/feed.xml     / docs/ai/feed_zh.xml   - AI curated (en / zh)

Design notes:
- Two monolingual feeds per family instead of one mixed-language feed
  (mirrors the cvedaily layout): feed.xml is English, feed_zh.xml is
  Chinese. Each item carries only its feed's language, falling back to
  the other language when that field is missing, so a feed item never
  shows a blank title. Without an AI key configured there are no
  translated fields and the two feeds share the original text.
- Feeds are rewritten from scratch each run with ONLY the current day's
  data (no history merging): subscribers keep their own history, and
  readers dedupe by guid (the article URL, isPermaLink), so daily
  replacement never shows items twice.
- When AI curation produced no data this run, the AI feeds are simply
  left untouched (stale from the previous day) rather than emptied.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from translator import CATEGORY_EN, SOURCE_EN

logger = logging.getLogger(__name__)

# GitHub Pages site (docs/ is the Pages root), used as the channel link
SITE_URL = 'https://secnotes.github.io/secnews/'

# Fixed offset for pubDate: article dates are bare YYYY-MM-DD, so a
# Beijing-time midnight anchor keeps the feed's ordering stable and
# matches the site's primary audience
_FEED_TZ = timezone(timedelta(hours=8))

# Per-language channel metadata: (title, description, <language> value)
_CHANNEL_META = {
    'articles': {
        'zh': ('安全资讯聚合 - SecNews',
               '每日自动聚合的网络安全资讯文章', 'zh-CN'),
        'en': ('SecNews - Cybersecurity News',
               'Daily aggregated cybersecurity news articles', 'en'),
    },
    'ai': {
        'zh': ('安全资讯 AI 精选 - SecNews',
               'AI 每日精选的重要安全文章（按主题分类，附推荐理由）', 'zh-CN'),
        'en': ('SecNews - AI Curated Security News',
               'Daily AI-curated important security articles, categorized '
               'with reasons', 'en'),
    },
}


def _pub_date(date_str: Optional[str]) -> str:
    """RFC 822 pubDate for a YYYY-MM-DD string (unparseable -> now)"""
    try:
        d = datetime.strptime(date_str or '', '%Y-%m-%d')
    except ValueError:
        d = None
    if d is None:
        d = datetime.now(_FEED_TZ)
    else:
        d = d.replace(tzinfo=_FEED_TZ)
    return format_datetime(d)


def _lang_field(obj: Dict[str, Any], name: str, lang: str) -> str:
    """Language-specific field with original-text fallback:
    zh prefers <name>_zh, en prefers <name>_en; both fall back to <name>"""
    return (obj.get(f'{name}_{lang}')
            or obj.get(name, '') or '')


def _item_xml(title: str, link: str, description: str,
              category: str, date_str: Optional[str]) -> str:
    return f"""    <item>
      <title>{escape(title)}</title>
      <link>{escape(link)}</link>
      <guid isPermaLink="true">{escape(link)}</guid>
      <description>{escape(description)}</description>
      <category>{escape(category)}</category>
      <pubDate>{_pub_date(date_str)}</pubDate>
    </item>
"""


def _channel_xml(meta_key: str, lang: str, items_xml: str) -> str:
    title, description, channel_lang = _CHANNEL_META[meta_key][lang]
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{escape(title)}</title>
    <link>{escape(SITE_URL)}</link>
    <description>{escape(description)}</description>
    <language>{channel_lang}</language>
    <lastBuildDate>{format_datetime(datetime.now(_FEED_TZ))}</lastBuildDate>
{items_xml}  </channel>
</rss>
"""


def _write_feed(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    logger.info(f"RSS feed saved to {path}")


def _articles_items(articles: List[Dict[str, Any]], lang: str) -> List[str]:
    items = []
    for a in articles:
        if not a.get('url') or not a.get('title'):
            continue
        source = a.get('source', '')
        if lang == 'en':
            source = SOURCE_EN.get(source, source)
        items.append(_item_xml(
            title=_lang_field(a, 'title', lang),
            link=a['url'],
            description=_lang_field(a, 'description', lang),
            category=source,
            date_str=a.get('date'),
        ))
    return items


def _curated_items(curated: Dict[str, Any], lang: str) -> List[str]:
    items = []
    for cat_name, cat_articles in curated.get('categories', {}).items():
        category = CATEGORY_EN.get(cat_name, cat_name) if lang == 'en' \
            else cat_name
        for a in cat_articles:
            if not a.get('url') or not a.get('title'):
                continue
            items.append(_item_xml(
                title=_lang_field(a, 'title', lang),
                link=a['url'],
                description=_lang_field(a, 'reason', lang),
                category=category,
                date_str=a.get('date') or curated.get('analysis_date'),
            ))
    return items


def generate_articles_feed(articles_data: Dict[str, Any], docs_dir: str,
                           lang: str) -> Optional[str]:
    """Write one language variant of the all-articles feed.

    Returns the written path, or None when there are no articles at all
    (an empty feed would only confuse subscribers, so it is skipped).
    """
    articles: List[Dict[str, Any]] = (articles_data.get('web', [])
                                      + articles_data.get('x', []))
    if not articles:
        logger.info("Articles feed skipped: no articles in this run")
        return None

    content = _channel_xml('articles', lang,
                           ''.join(_articles_items(articles, lang)))
    filename = 'feed.xml' if lang == 'en' else 'feed_zh.xml'
    path = os.path.join(docs_dir, filename)
    _write_feed(path, content)
    return path


def generate_ai_curated_feed(curated: Dict[str, Any], docs_dir: str,
                             lang: str) -> Optional[str]:
    """Write one language variant of the AI curated feed.

    Called only with actual curated data; a run without AI curation
    leaves the previous feeds untouched.
    """
    content = _channel_xml('ai', lang,
                           ''.join(_curated_items(curated, lang)))
    filename = 'feed.xml' if lang == 'en' else 'feed_zh.xml'
    path = os.path.join(docs_dir, 'ai', filename)
    _write_feed(path, content)
    return path


def generate_rss_feeds(articles_data: Dict[str, Any],
                       curated: Optional[Dict[str, Any]] = None,
                       docs_dir: Optional[str] = None) -> None:
    """Write all daily feeds, one monolingual file per language/family:

    docs/feed.xml + docs/feed_zh.xml (always when articles exist);
    docs/ai/feed.xml + docs/ai/feed_zh.xml (only when curated data exists).

    docs_dir defaults to the project's docs/ directory (the Pages root),
    the same location the HTML page and dated JSON archives live in.
    """
    if docs_dir is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        docs_dir = os.path.join(os.path.dirname(script_dir), 'docs')

    for lang in ('en', 'zh'):
        generate_articles_feed(articles_data, docs_dir, lang)

    if curated:
        for lang in ('en', 'zh'):
            generate_ai_curated_feed(curated, docs_dir, lang)
    else:
        logger.info("AI curated feeds skipped: no curated data in this run "
                    "(previous feeds, if any, left untouched)")
