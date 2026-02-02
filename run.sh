#!/bin/bash
# 快速运行脚本 - 在项目根目录运行整个安全资讯聚合流程

echo "开始运行安全资讯聚合器..."

# 确保docs目录存在
mkdir -p docs

# 进入src目录并运行脚本
cd src
python3 scrape_news.py

echo "运行完成！"
echo "检查输出文件:"
echo "- articles.json (原始数据)"
echo "- docs/index.html (生成的静态网页)"