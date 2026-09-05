<div align="center">

# 🛡️ 安全资讯聚合平台

简体中文 | **[English](README_EN.md)**

[![Daily Update](https://github.com/secnotes/secnews/actions/workflows/daily_update.yml/badge.svg)](https://github.com/secnotes/secnews/actions/workflows/daily_update.yml)
[![Last Commit](https://img.shields.io/github/last-commit/secnotes/secnews)](https://github.com/secnotes/secnews/commits/main)
[![License: MIT](https://img.shields.io/github/license/secnotes/secnews)](https://github.com/secnotes/secnews/blob/main/LICENSE)
![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776ab?logo=python&logoColor=white)

[![Sec-Today](https://img.shields.io/badge/Sec--Today-555?style=flat-square)](https://sec.today/pulses/)
[![腾讯安全](https://img.shields.io/badge/腾讯安全-555?style=flat-square)](https://sectoday.tencent.com/)
[![先知社区](https://img.shields.io/badge/先知社区-555?style=flat-square)](https://xz.aliyun.com/news)
[![Project Zero](https://img.shields.io/badge/Project_Zero-555?style=flat-square)](https://projectzero.google/)
[![SeeBug Paper](https://img.shields.io/badge/SeeBug_Paper-555?style=flat-square)](https://paper.seebug.org/)
[![安全客](https://img.shields.io/badge/安全客-555?style=flat-square)](https://www.anquanke.com/)
[![FreeBuf](https://img.shields.io/badge/FreeBuf-555?style=flat-square)](https://www.freebuf.com/)
[![安全内参](https://img.shields.io/badge/安全内参-555?style=flat-square)](https://www.secrss.com/)
[![SecurityWeek](https://img.shields.io/badge/SecurityWeek-555?style=flat-square)](https://www.securityweek.com/)
[![The Hacker News](https://img.shields.io/badge/The_Hacker_News-555?style=flat-square)](https://thehackernews.com/)
[![Security Online](https://img.shields.io/badge/Security_Online-555?style=flat-square)](https://securityonline.info/)
[![看雪论坛](https://img.shields.io/badge/看雪论坛-555?style=flat-square)](https://bbs.kanxue.com/)
[![X](https://img.shields.io/badge/X-1d9bf0?style=flat-square&logo=x&logoColor=white)](https://x.com)

一个自动化的安全资讯聚合平台，每日自动收集来自各大安全社区的技术文章和新闻资讯，并通过AI智能筛选和分类重要内容。

</div>

## 功能特性

- 自动收集各大安全资讯源的最新文章
- 区分技术文章和安全新闻两类
- 提取文章标题、链接、描述和发布时间
- 生成美观的静态网页展示
- 自动去重，避免重复文章
- 支持中文内容正确显示
- **AI智能精选**：通过AI分析最近文章，筛选重要内容并分类
- **分类导航**：支持漏洞研究、移动安全、AI安全、威胁情报、安全工具、云安全等分类
- **双视图切换**：网页支持"全部文章"和"AI精选"两种视图
- **中英双语**：配置AI密钥后自动翻译文章标题与描述，网页支持 🇨🇳中文 / 🌐English 一键切换（中文状态只显示中文，英文状态只显示英文）；无密钥时自动跳过，行为与原版一致
- **白天/夜间主题**：右上角 🌙/☀️ 一键切换，偏好通过 localStorage 记住，无需AI密钥
- **回到顶部**：右下角 ↑ 按钮，滚动超过一屏后出现，平滑回到顶部

## 自动更新

项目配置了GitHub Actions，每日凌晨0点（UTC时间）自动运行，更新最新的安全资讯并生成AI精选内容。

## 安装与运行

1. 安装Python 3.9+
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 运行爬虫：
   ```bash
   cd src
   python scrape_news.py              # 默认模式，不爬取 Unsafe.sh
   python scrape_news.py --unsafe     # 包含 Unsafe.sh 数据源
   ```

生成的网页将位于 `docs/index.html`，可以直接在浏览器中打开查看。

原始数据与AI精选结果按日期存档：
- `docs/data/<年>/articles_<YYYYMMDD>.json` - 原始文章数据
- `docs/ai/<年>/ai_curated_<YYYYMMDD>.json` - AI精选结果
- `docs/data/index.json` - 数据存档日期清单（新日期在前）

## AI精选功能

### 功能说明

AI精选功能会分析最近2天的安全文章，筛选出重要内容并按主题分类：
- 🐛 漏洞研究
- 📱 移动安全
- 🤖 AI安全
- 🔍 威胁情报
- 🔧 安全工具
- ☁️ 云安全
- ⭐ 其他重要

### 支持的AI服务

本项目使用OpenAI-compatible API接口，支持以下AI服务：

| AI服务 | 模型示例 | API地址 |
|-------|---------|--------|
| OpenAI | gpt-4o-mini | https://api.openai.com/v1 |
| DeepSeek | deepseek-chat | https://api.deepseek.com/v1 |
| 阿里百练 | glm-4, glm-5 | https://dashscope.aliyuncs.com/compatible-mode/v1 |
| 智谱AI | glm-4 | https://open.bigmodel.cn/api/paas/v4 |
| Moonshot | moonshot-v1 | https://api.moonshot.cn/v1 |

### 本地使用

**方式一：使用环境变量**

在项目根目录下创建 `.env` 文件（放在 `src/` 目录下也可以，两者都会被读取）：
```env
AI_API_KEY=your-api-key-here
AI_MODEL=gpt-4o-mini
AI_BASE_URL=https://api.openai.com/v1   # 可选，根据AI服务自动推断
```

运行带AI分析的爬虫：
```bash
python scrape_news.py --unsafe --ai-curate --ai-days 2
```

**方式二：使用命令行参数**

```bash
python scrape_news.py --unsafe --ai-curate \
    --ai-key your-api-key \
    --ai-model gpt-4o-mini \
    --ai-base-url https://api.openai.com/v1
```

### 命令行参数

| 参数 | 说明 | 默认值 |
|-----|------|-------|
| `--ai-curate` | 启用AI精选功能 | 不启用 |
| `--ai-days` | 分析最近N天的文章 | 2 |
| `--ai-key` | AI API密钥 | 从环境变量读取 |
| `--ai-model` | AI模型名称 | gpt-4o-mini |
| `--ai-base-url` | API地址 | 自动推断 |
| `--no-translate` | 禁用AI双语翻译 | 不禁用（有密钥即自动翻译） |

### GitHub Actions配置

在GitHub仓库中设置Secrets和Variables：
1. 进入 Settings → Secrets and variables → Actions
2. 在 **Secrets** 标签下添加：
   - `AI_API_KEY`（必须）：你的AI API密钥
3. 在 **Variables** 标签下添加：
   - `AI_MODEL`（推荐）：AI模型名称，如 `glm-5.1`、`gpt-4o-mini`、`deepseek-chat`
   - `AI_BASE_URL`（推荐）：API地址，如使用阿里百练需设置为 `https://dashscope.aliyuncs.com/compatible-mode/v1`

注意：
- `AI_MODEL` 和 `AI_BASE_URL` 为非敏感配置，应设置在 Variables 标签下
- 阿里百练和智谱AI官方都提供GLM模型，但API地址不同，需根据使用的平台选择正确的地址

### X数据源代理（可选）

2026-08-30 起 x.com 对数据中心 IP（含 GitHub Actions 的 Azure runner）直接返回
403，X 爬虫在 CI 中无法直连。解决方案是一个免费的 Cloudflare Worker 转发代理，
部署与配置说明见 [`x-proxy-worker/`](x-proxy-worker/README.md)：

1. 按说明部署 Worker，获得地址并设置 `PROXY_TOKEN`
2. 仓库中配置：**Variables** 添加 `X_PROXY_BASE`（Worker 地址），**Secrets** 添加
   `X_PROXY_TOKEN`（token）

不配置时 X 爬虫回退直连（本地走代理出口可用），失败仅记录日志、不影响其他数据源。

### 成本估算

- 每日约分析100-150篇文章
- 使用分批处理（每批200篇）
- 推荐使用高性价比模型（如 gpt-4o-mini、deepseek-chat）
- 预估每日成本约 $0.05-0.10

### 中英双语翻译

配置 `AI_API_KEY` 后（与AI精选共用同一密钥和模型配置），爬取完成时会自动将文章翻译为双语：

- 中文文章自动补翻英文（`title_en` / `description_en`），英文文章自动补翻中文
- 每篇文章只翻译缺失的语言方向，成本减半；翻译失败时回退显示原文
- 生成的网页右上角出现双语切换悬浮按钮（中文态显示 EN，英文态显示 中），点击一键切换，选择会通过 localStorage 记住
- AI精选视图的标题、推荐理由、分类名、摘要同步双语化
- 未配置密钥或使用 `--no-translate` 时完全不启用，输出与原版一致

## 维护

如发现某些数据源无法访问，请及时更新相应的爬虫代码以适配网站变化。

## 免责声明

本项目仅供学习和研究使用。使用本项目时，请遵守以下原则：

1. **尊重版权**：所有内容版权归原作者所有，本项目不对内容进行任何修改或再分发
2. **合理使用**：仅用于个人学习和技术研究目的，请勿用于商业用途
3. **遵守robots.txt**：本项目遵循各网站的robots.txt协议
4. **频率限制**：爬虫实现中加入了合理的延时，避免对目标网站造成过大负担
5. **内容审查**：对于爬取的内容，使用者需自行判断和核实准确性

使用者应当了解并承担以下风险：
- 各网站可能会不定期更改爬取规则或加强反爬措施
- 部分网站可能需要验证、登录或验证码才能正常访问
- 由于网站结构调整可能导致爬虫失效
- 因使用本项目产生的一切后果由使用者自行承担