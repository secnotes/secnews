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