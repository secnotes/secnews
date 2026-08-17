#!/usr/bin/env python3
"""
Article Translation Module
Adds Chinese/English dual-language fields to scraped articles via an
OpenAI-compatible AI API (reuses ai_provider.AIProvider).

Design notes:
- Each article is only translated INTO the language it is missing (a Chinese
  article gets title_en/description_en, an English one gets title_zh/...),
  so per-article cost is halved.
- The source-language fields are filled locally from the original text
  without any API call.
- When any single item fails to translate, the missing field falls back to
  the original text so the page never shows blanks.
- translate_all() is a no-op when no API key is configured, preserving the
  original single-language behavior.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Hardcoded English names for the fixed AI curation categories -
# deterministic and free, no API round-trip for known strings
CATEGORY_EN = {
    '漏洞研究': 'Vulnerability Research',
    '移动安全': 'Mobile Security',
    'AI安全': 'AI Security',
    '威胁情报': 'Threat Intelligence',
    '安全工具': 'Security Tools',
    '云安全': 'Cloud Security',
    '其他重要': 'Other Important',
}

# Hardcoded English names for known Chinese source names
SOURCE_EN = {
    '腾讯安全': 'Tencent Security',
    '先知社区': 'Xianzhi Community',
    '安全客': 'Anquanke',
    '安全内参': 'SecRSS',
    '看雪论坛': 'Kanxue Forum',
}

# Number of texts per AI translation batch
TRANSLATE_BATCH_SIZE = 30

# Max characters of description sent for translation (keeps prompts small)
MAX_DESC_CHARS = 300


def _cjk_count(text: str) -> int:
    """Return the number of CJK characters in text"""
    if not text:
        return 0
    return sum(1 for c in text if '一' <= c <= '鿿')


def _cjk_ratio(text: str) -> float:
    """Return ratio of CJK characters among non-space characters"""
    if not text:
        return 0.0
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    return _cjk_count(text) / len(chars)


def detect_language(text: str) -> str:
    """Detect whether text is Chinese ('zh') or English ('en').

    Any text containing a couple of hanzi is treated as Chinese: mixed
    security titles like "Linux内核漏洞利用之CVE-2026-64563" have a low
    CJK *ratio* (long CVE ids), but an English title would never contain
    hanzi at all.
    """
    return 'zh' if _cjk_count(text) >= 2 else 'en'


def _is_translated(text: str, target: str) -> bool:
    """Check whether a translated text actually reads like the target language.

    Models sometimes echo the source text back instead of translating (e.g.
    returning a Chinese title for a zh->en request), so translations are
    validated before being applied: English output must be virtually
    CJK-free, while Chinese output only needs a couple of hanzi - CVE ids
    and product names may keep it otherwise latin-heavy.
    """
    if not text:
        return False
    if target == 'en':
        return _cjk_ratio(text) <= 0.15
    return _cjk_count(text) >= 2


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from an AI response"""
    text = text.strip()
    if text.startswith('```json'):
        text = text[7:]
    elif text.startswith('```'):
        text = text[3:]
    if text.endswith('```'):
        text = text[:-3]
    return text.strip()


def _parse_translations(response: str) -> List[Dict[str, Any]]:
    """Parse {"translations":[{"index":N,"title":"...","description":"..."}]} from an AI response"""
    text = _strip_code_fences(response)

    data: Optional[Dict[str, Any]] = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Model wrapped the JSON in prose - slice between first/last brace
        first, last = text.find('{'), text.rfind('}')
        if first != -1 and last > first:
            try:
                data = json.loads(text[first:last + 1])
            except json.JSONDecodeError:
                data = None
    if data is None:
        logger.error("Failed to parse translation response as JSON")
        return []

    result = []
    for item in data.get('translations', []):
        if isinstance(item, dict) and 'index' in item:
            try:
                result.append({
                    'index': int(item['index']),
                    'title': str(item.get('title', '') or ''),
                    'description': str(item.get('description', '') or ''),
                })
            except (TypeError, ValueError):
                continue
    return result


def _run_translation(provider, requests: List[Dict[str, Any]]) -> Dict[int, Dict[str, str]]:
    """Translate a list of requests in batches, grouped by target language.

    Each request: {'index': int, 'lang': 'zh'|'en', 'title': str, 'description': str}
    where 'lang' is the SOURCE language. Returns {index: {'title','description'}}.
    """
    by_target: Dict[str, List[Dict[str, Any]]] = {'en': [], 'zh': []}
    for req in requests:
        target = 'en' if req['lang'] == 'zh' else 'zh'
        by_target[target].append(req)

    results: Dict[int, Dict[str, str]] = {}

    for target, group in by_target.items():
        direction_text = '中文 -> 英文' if target == 'en' else '英文 -> 中文'
        system_prompt = f"""你是专业的网络安全领域翻译引擎，负责将安全资讯文章的标题和描述按{direction_text}方向翻译。
规则:
1. 使用信息安全行业标准术语，标题翻译准确、简洁有力
2. 描述翻译保持原意、通顺自然
3. 描述为“(无)”时，对应 description 字段输出空字符串
4. 输出必须是目标语言：译为英文时结果中不得保留中文汉字；译为中文时仅保留必要的英文专有名词（CVE 编号、产品名等）
5. 唯一输出：一个可被 Python json.loads() 直接解析的 JSON 对象，禁止 markdown 围栏、前言、<think> 推理块等任何额外字符"""

        for i in range(0, len(group), TRANSLATE_BATCH_SIZE):
            batch = group[i:i + TRANSLATE_BATCH_SIZE]

            lines = []
            for req in batch:
                lines.append(f"{req['index']}. 标题: {req['title']}")
                lines.append(f"   描述: {req['description']}" if req['description'] else "   描述: (无)")

            prompt = f"""请翻译以下 {len(batch)} 篇安全资讯（方向：{direction_text}）。

## 文章列表
{chr(10).join(lines)}

## 输出格式
只输出一个 JSON 对象，index 必须与输入编号一一对应:
{{"translations":[{{"index":编号,"title":"翻译后标题","description":"翻译后描述"}}]}}"""

            try:
                response = provider.analyze(prompt, system_prompt, temperature=0.1)
                applied = 0
                valid_indexes = {req['index'] for req in batch}
                for item in _parse_translations(response):
                    if item['index'] in valid_indexes:
                        results[item['index']] = {
                            'title': item['title'],
                            'description': item['description'],
                        }
                        applied += 1
                logger.info(
                    f"Translation batch done ({direction_text}, "
                    f"{len(batch)} items, {applied} parsed)"
                )
            except Exception as e:
                logger.error(f"Translation batch failed ({direction_text}): {str(e)}")
                continue

    return results


def _fill_original_fields(article: Dict[str, Any]) -> str:
    """Fill source-language fields from the original title/description.

    Returns the detected source language.
    """
    lang = detect_language(article.get('title', ''))
    if lang == 'zh':
        article.setdefault('title_zh', article.get('title', ''))
        article.setdefault('description_zh', article.get('description', '') or '')
    else:
        article.setdefault('title_en', article.get('title', ''))
        article.setdefault('description_en', article.get('description', '') or '')
    return lang


def translate_articles(articles: List[Dict[str, Any]], provider) -> int:
    """Add title_zh/title_en/description_zh/description_en fields in place.

    Returns the number of articles that received an actual translation
    (fallback copies of the original text are not counted).
    """
    if not articles:
        return 0

    requests: List[Dict[str, Any]] = []
    lookup: Dict[int, Dict[str, Any]] = {}  # index -> {'article', 'target'}

    for article in articles:
        lang = _fill_original_fields(article)
        target = 'en' if lang == 'zh' else 'zh'
        index = len(requests)
        requests.append({
            'index': index,
            'lang': lang,
            'title': article.get('title', ''),
            'description': (article.get('description', '') or '')[:MAX_DESC_CHARS],
        })
        lookup[index] = {'article': article, 'target': target}

    results = _run_translation(provider, requests)

    def _apply(entry: Dict[str, Any], result: Optional[Dict[str, str]]) -> bool:
        """Apply a translation result if it actually is in the target language.
        Returns True when a valid title translation was applied."""
        article = entry['article']
        target = entry['target']
        if not result:
            return False
        title_ok = _is_translated(result['title'], target)
        if title_ok:
            article[f'title_{target}'] = result['title']
        if result['description'] and _is_translated(result['description'], target):
            article[f'description_{target}'] = result['description']
        return title_ok

    translated = 0
    invalid_indexes = []
    for index, entry in lookup.items():
        article = entry['article']
        target = entry['target']
        if _apply(entry, results.get(index)):
            translated += 1
        else:
            invalid_indexes.append(index)
        # Guarantee both language keys exist; fall back to the original text
        article.setdefault(f'title_{target}', article.get('title', ''))
        article.setdefault(f'description_{target}', article.get('description', '') or '')

    # One retry round for items the model echoed back in the source language
    if invalid_indexes:
        logger.info(
            f"Retrying {len(invalid_indexes)} items whose translation was "
            f"not in the target language"
        )
        retry_requests = [requests[i] for i in invalid_indexes]
        retry_results = _run_translation(provider, retry_requests)
        for i in invalid_indexes:
            entry = lookup[i]
            if _apply(entry, retry_results.get(i)):
                translated += 1

    logger.info(f"Translated {translated}/{len(articles)} articles")
    return translated


def translate_ai_curated(curated: Dict[str, Any], provider) -> None:
    """Add dual-language fields to AI curated data in place.

    Adds title_zh/title_en and reason_zh/reason_en per curated article,
    plus summary_zh/summary_en on the top-level dict. Category names are
    translated via the hardcoded CATEGORY_EN mapping at render time.
    """
    if not curated:
        return

    requests: List[Dict[str, Any]] = []
    lookup: Dict[int, Dict[str, Any]] = {}  # index -> {'obj', 'prefix', 'target'}

    def _add(obj: Dict[str, Any], prefix: str, text: str) -> None:
        if not text:
            return
        lang = detect_language(text)
        target = 'en' if lang == 'zh' else 'zh'
        obj.setdefault(f'{prefix}_{lang}', text)
        index = len(requests)
        requests.append({'index': index, 'lang': lang, 'title': text, 'description': ''})
        lookup[index] = {'obj': obj, 'prefix': prefix, 'target': target}

    for cat_articles in curated.get('categories', {}).values():
        for article in cat_articles:
            _add(article, 'title', article.get('title', ''))
            _add(article, 'reason', article.get('reason', ''))

    _add(curated, 'summary', curated.get('summary', ''))

    if not requests:
        return

    results = _run_translation(provider, requests)

    def _apply(entry: Dict[str, Any], result: Optional[Dict[str, str]]) -> bool:
        """Apply a translation result if it actually is in the target language"""
        obj, prefix, target = entry['obj'], entry['prefix'], entry['target']
        if not result or not _is_translated(result['title'], target):
            return False
        obj[f'{prefix}_{target}'] = result['title']
        return True

    invalid_indexes = []
    for index, entry in lookup.items():
        obj, prefix, target = entry['obj'], entry['prefix'], entry['target']
        if not _apply(entry, results.get(index)):
            invalid_indexes.append(index)
        # Fall back to the original text so rendering never shows blanks
        obj.setdefault(f'{prefix}_{target}', obj.get(prefix, ''))

    if invalid_indexes:
        logger.info(
            f"Retrying {len(invalid_indexes)} curated items whose translation "
            f"was not in the target language"
        )
        retry_requests = [requests[i] for i in invalid_indexes]
        retry_results = _run_translation(provider, retry_requests)
        for i in invalid_indexes:
            _apply(lookup[i], retry_results.get(i))


def translate_all(
    articles_data: Dict[str, Any],
    curated: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> bool:
    """Translate articles (and optionally curated data) in place.

    Returns False (no-op) when no API key is configured, so callers can
    keep their original behavior in that case.
    """
    try:
        from ai_provider import get_ai_provider
        provider = get_ai_provider(api_key=api_key, model=model, base_url=base_url)
    except ValueError as e:
        logger.info(f"Translation skipped: {str(e)}")
        return False
    except ImportError as e:
        logger.warning(f"Translation skipped: {str(e)}")
        return False

    all_articles = articles_data.get('tech', []) + articles_data.get('news', [])
    count = translate_articles(all_articles, provider)

    if curated:
        translate_ai_curated(curated, provider)

    logger.info(f"Translation completed: {count} articles translated")
    return True
