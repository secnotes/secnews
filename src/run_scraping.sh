#!/bin/bash
# 安全资讯聚合器 - 运行脚本
# 执行Python脚本来聚合多个来源的安全新闻

echo "开始运行安全资讯聚合脚本..."

# 检查虚拟环境是否存在
if [ -d "../venv" ]; then
    echo "激活虚拟环境..."
    source ../venv/bin/activate
fi

# 确保docs目录存在
mkdir -p ../docs

# 运行爬虫 - 保存到 docs 目录
python3 scrape_news.py

# 如果使用了虚拟环境，则退出
if [ -d "../venv" ]; then
    deactivate
fi

echo "脚本执行完成！"
echo "检查输出文件:"
echo "- articles.json (原始数据)"
echo "- docs/index.html (生成的静态网页)"