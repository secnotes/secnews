# 安全资讯聚合平台

一个自动化的安全资讯聚合平台，每日自动收集来自各大安全社区的技术文章和新闻资讯。

## 项目结构

```
.
├── src/                    # 源代码目录
│   ├── scrape_news.py      # 主爬虫脚本
│   └── run_scraping.sh     # 运行脚本
├── docs/                   # 生成的网页文件目录
│   └── index.html          # 生成的静态网页
├── .github/workflows/      # GitHub Actions 工作流
│   └── daily_update.yml    # 每日自动更新工作流
└── requirements.txt        # Python依赖包列表
```

## 数据源

- **Sec-Today**: https://sec.today/pulses/
- **腾讯安全**: https://sectoday.tencent.com/
- **先知社区**: https://xz.aliyun.com/news
- **Project Zero**: https://projectzero.google/
- **SeeBug Paper**: https://paper.seebug.org/
- **安全客**: https://www.anquanke.com/
- **FreeBuf**: https://www.freebuf.com/
- **安全内参**: https://www.secrss.com/
- **SecurityWeek**: https://www.securityweek.com/
- **看雪**: https://bbs.kanxue.com/

## 功能特性

- 自动收集各大安全资讯源的最新文章
- 区分技术文章和安全新闻两类
- 提取文章标题、链接、描述和发布时间
- 生成美观的静态网页展示
- 自动去重，避免重复文章
- 支持中文内容正确显示

## 自动更新

项目配置了GitHub Actions，每日凌晨0点（UTC时间）自动运行，更新最新的安全资讯。

## 安装与运行

1. 安装Python 3.9+
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 运行爬虫：
   ```bash
   cd src
   python scrape_news.py
   ```

生成的网页将位于 `docs/index.html`，可以直接在浏览器中打开查看。

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