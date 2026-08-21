# Security News Aggregator

**[简体中文](README.md)** | English

An automated security news aggregation platform that collects technical articles and news from major security communities every day, and uses AI to curate and categorize the important content.

## Data Sources

- **Sec-Today**: https://sec.today/pulses/
- **Tencent Security**: https://sectoday.tencent.com/
- **Xianzhi Community**: https://xz.aliyun.com/news
- **Project Zero**: https://projectzero.google/
- **SeeBug Paper**: https://paper.seebug.org/
- **Anquanke**: https://www.anquanke.com/
- **FreeBuf**: https://www.freebuf.com/
- **SecRSS**: https://www.secrss.com/
- **SecurityWeek**: https://www.securityweek.com/
- **The Hacker News**: https://thehackernews.com/
- **Kanxue Forum**: https://bbs.kanxue.com/

## Features

- Automatically collects the latest articles from major security news sources
- Separates content into technical articles and security news
- Extracts article titles, links, descriptions and publish dates
- Generates a polished static web page
- Automatic deduplication of articles
- Proper display of Chinese content
- **AI Curation**: analyzes recent articles with AI, selects the important ones and categorizes them
- **Category Navigation**: vulnerability research, mobile security, AI security, threat intelligence, security tools, cloud security and more
- **Dual Views**: the page supports "All Articles" and "AI Curated" views
- **Bilingual (Chinese/English)**: with an AI key configured, article titles and descriptions are translated automatically; a single toggle button switches the whole page between Chinese-only and English-only; without a key this is skipped and behavior stays identical
- **Light/Dark Theme**: 🌙/☀️ toggle in the top-right corner, preference remembered via localStorage, no AI key required
- **Back to Top**: ↑ button in the bottom-right corner, appears after scrolling past one screen, smooth scroll to top

## Auto Update

The project uses GitHub Actions to run daily at 00:00 UTC, refreshing the latest security news and generating AI-curated content.

## Installation & Usage

1. Install Python 3.9+
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the scraper:
   ```bash
   cd src
   python scrape_news.py              # Default mode, does not scrape Unsafe.sh
   python scrape_news.py --unsafe     # Include the Unsafe.sh source
   ```

The generated page is at `docs/index.html` and can be opened directly in a browser.

Raw data and AI curation results are archived by date:
- `docs/data/<year>/articles_<YYYYMMDD>.json` - raw article data
- `docs/ai/<year>/ai_curated_<YYYYMMDD>.json` - AI curated results
- `docs/data/index.json` - manifest of archived dates (newest first)

## AI Curation

### Overview

The AI curation feature analyzes security articles from the last 2 days, selects important content and groups it by topic:
- 🐛 Vulnerability Research
- 📱 Mobile Security
- 🤖 AI Security
- 🔍 Threat Intelligence
- 🔧 Security Tools
- ☁️ Cloud Security
- ⭐ Other Important

### Supported AI Services

This project uses OpenAI-compatible APIs and supports the following services:

| Service | Example Model | API URL |
|---------|--------------|---------|
| OpenAI | gpt-4o-mini | https://api.openai.com/v1 |
| DeepSeek | deepseek-chat | https://api.deepseek.com/v1 |
| Alibaba Bailian | glm-4, glm-5 | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| Zhipu AI | glm-4 | https://open.bigmodel.cn/api/paas/v4 |
| Moonshot | moonshot-v1 | https://api.moonshot.cn/v1 |

### Local Usage

**Option 1: environment variables**

Create a `.env` file in the project root (or in `src/` - both locations are read):
```env
AI_API_KEY=your-api-key-here
AI_MODEL=gpt-4o-mini
AI_BASE_URL=https://api.openai.com/v1   # Optional, auto-inferred per service
```

Run the scraper with AI analysis:
```bash
python scrape_news.py --unsafe --ai-curate --ai-days 2
```

**Option 2: command-line arguments**

```bash
python scrape_news.py --unsafe --ai-curate \
    --ai-key your-api-key \
    --ai-model gpt-4o-mini \
    --ai-base-url https://api.openai.com/v1
```

### Command-Line Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--ai-curate` | Enable AI curation | Disabled |
| `--ai-days` | Analyze articles from the last N days | 2 |
| `--ai-key` | AI API key | Read from environment |
| `--ai-model` | AI model name | gpt-4o-mini |
| `--ai-base-url` | API base URL | Auto-inferred |
| `--no-translate` | Disable AI bilingual translation | Enabled automatically when a key is present |

### GitHub Actions Configuration

Set the following Secrets and Variables in your GitHub repository:
1. Go to Settings → Secrets and variables → Actions
2. Under the **Secrets** tab, add:
   - `AI_API_KEY` (required): your AI API key
3. Under the **Variables** tab, add:
   - `AI_MODEL` (recommended): model name, e.g. `glm-5.1`, `gpt-4o-mini`, `deepseek-chat`
   - `AI_BASE_URL` (recommended): API base URL; for Alibaba Bailian use `https://dashscope.aliyuncs.com/compatible-mode/v1`

Notes:
- `AI_MODEL` and `AI_BASE_URL` are non-sensitive and belong under the Variables tab
- Both Alibaba Bailian and Zhipu AI offer GLM models but with different API endpoints - pick the URL matching the platform you use

### Cost Estimate

- Roughly 100-150 articles analyzed per day
- Processed in batches of 200
- Cost-effective models recommended (e.g. gpt-4o-mini, deepseek-chat)
- Estimated daily cost: $0.05-0.10

### Bilingual Translation

With `AI_API_KEY` configured (shared with AI curation), articles are automatically translated after scraping:

- Chinese articles get English fields (`title_en` / `description_en`) added, and vice versa
- Each article is only translated into the language it is missing, halving the cost; failed translations fall back to the original text
- Translations are validated - if the model echoes back the source language, the item is retried automatically
- The generated page shows a single floating toggle button in the top-right corner (shows `EN` in Chinese mode, `中` in English mode); the choice is remembered via localStorage
- Category names, summaries and recommendation reasons in the AI-curated view are translated as well
- Fully disabled without a key or with `--no-translate` - output is identical to the original

## Maintenance

If a data source becomes inaccessible, please update the corresponding scraper code to adapt to site changes.

## Disclaimer

This project is for learning and research purposes only. When using it, please follow these principles:

1. **Respect copyright**: all content belongs to its original authors; this project does not modify or redistribute the content
2. **Fair use**: for personal learning and technical research only; no commercial use
3. **robots.txt**: the scrapers respect each site's robots.txt
4. **Rate limiting**: reasonable delays are built in to avoid overloading target sites
5. **Content review**: users must judge and verify the accuracy of scraped content themselves

Users should understand and accept these risks:
- Sites may change their scraping rules or strengthen anti-bot measures at any time
- Some sites may require verification, login or CAPTCHAs
- Site restructuring may break scrapers
- Users bear all consequences arising from the use of this project
