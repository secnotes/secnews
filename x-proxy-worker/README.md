# X Profile Fetch Proxy (Cloudflare Worker)

为 secnews 的 X (Twitter) 爬虫提供的一个免费转发代理。

## 为什么需要它

2026-08-30 前后，x.com 在改版 SSR 标记（移除 microdata）的同时，开始对数据中心
IP 段拒绝未登录访问。GitHub Actions 的 runner 跑在 Azure 上，直连
`https://x.com/<handle>` 会得到**毫秒级 HTTP 403**，导致每日自动更新里的 X
数据源归零（解析代码本身是好的，本地走代理出口可正常抓取）。

实测各出口 IP 对 x.com 的可达性：

| 出口 | 结果 |
|---|---|
| GitHub Actions / Azure（数据中心） | HTTP 403，直接拒绝 |
| 常见公共数据中心代理 | 520 / 522 |
| 住宅类代理出口（本地 `.env` 配置的代理） | HTTP 200，完整 SSR 页面 |
| **Cloudflare Workers 出口** | **HTTP 200，完整 SSR 页面** |

X 目前封的是 Azure/AWS 这类云主机段，没有封 Cloudflare 的出口。Worker 免费
版每天 10 万请求，本项目只需 ~5 请求/天（每个账号 1 次），余量充足。

## 文件说明

| 文件 | 作用 |
|---|---|
| `worker.js` | Worker 源码：带 token 校验、只转发 x.com 的 GET 请求 |
| `wrangler.toml` | wrangler 部署配置（token 是 secret，不在文件里） |

Worker 刻意收窄了能力面，即使 token 泄露也只是一个只读的 x.com 页面代理：

- 仅接受 `GET`
- 仅允许 `https://x.com` 主机
- 仅允许两种路径：`/<handle>`（个人主页）和 `/<handle>/status/<id>`（推文 permalink）
- 必须携带 `X_PROXY_TOKEN` 对应的共享密钥；未配置 `PROXY_TOKEN` 时拒绝一切请求

## 部署（二选一）

### 方式 A：控制台粘贴（无需本地工具，推荐先跑通用这个）

1. 注册/登录 [Cloudflare Dashboard](https://dash.cloudflare.com/)（免费账户即可）
2. 左侧 **Workers & Pages** → **Create** → Worker → 随便起个名（如
   `secnews-x-proxy`）→ **Deploy**
3. 点 **Edit code**，用 `worker.js` 的内容整体替换默认代码 → **Deploy**
4. **Settings → Variables and Secrets → Add**：
   - Type 选 **Secret**，Name 填 `PROXY_TOKEN`，Value 填一个随机长字符串
     （例如 `openssl rand -hex 24` 的输出）
5. 记下 Worker 地址，形如 `https://secnews-x-proxy.<你的子域>.workers.dev`

### 方式 B：wrangler CLI

```bash
npm install -g wrangler
wrangler login
cd x-proxy-worker
wrangler deploy
wrangler secret put PROXY_TOKEN   # 粘贴一个随机长字符串
```

## 验证

```bash
# 应返回 200 和 PortSwigger 主页 HTML（约 200KB）
curl -s -o /dev/null -w "%{http_code} %{size_download}B\n" \
  "https://<你的worker地址>/?token=<你的token>&url=https://x.com/portswigger"

# 缺 token 应返回 403
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://<你的worker地址>/?url=https://x.com/portswigger"

# 非 x.com 目标应返回 400
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://<你的worker地址>/?token=<你的token>&url=https://example.com"
```

## 接入 secnews

爬虫通过两个环境变量识别 Worker，**均为可选**——不配置时行为与现在完全一致
（直连 x.com）：

| 环境变量 | 说明 |
|---|---|
| `X_PROXY_BASE` | Worker **完整地址，必须带 `https://` 协议头**，如 `https://secnews-x-proxy.xxx.workers.dev` 或 `https://proxy.example.cn`。只写域名（缺协议头）会被当成无效 URL，Worker 路径直接失败（随后自动回退直连） |
| `X_PROXY_TOKEN` | 部署时设置的 `PROXY_TOKEN` |

### GitHub Actions（CI）

在仓库 **Settings → Secrets and variables → Actions** 中配置：

- **Variables** 标签：`X_PROXY_BASE` = Worker 地址（非敏感，与 `AI_MODEL`、
  `AI_BASE_URL` 同类；放在 Secrets 标签下也能被读取）
- **Secrets** 标签：`X_PROXY_TOKEN` = token

workflow 已配置把这两个 secret 注入运行环境，配置好即生效。

### 本地运行

在项目根目录 `.env` 里添加（参考 `.env.example`）：

```
X_PROXY_BASE=https://secnews-x-proxy.xxx.workers.dev
X_PROXY_TOKEN=你的token
```

## 失败降级行为（不影响其他爬虫源）

爬虫的取页顺序是：**Worker 优先 → 失败则回退直连 → 再失败仅记录一条 ERROR 日志
并跳过该账号**。任何一层失败都不会抛出异常中断流程，其余 13 个数据源照常抓取、
AI 精选和页面生成照常进行——这正是 9 月初 X 归零期间项目其他部分一直正常的
原因，Worker 方案完整保留了这个特性。

## 局限与维护

- **X 政策会变**：它随时可能也封 Cloudflare 出口（8/30 的改版就是先例）。届时的
  症状是日志里出现 `via worker: HTTP 403`，爬虫会自动降级、其余源不受影响。
  若需更换方案（RSSHub 等），改动点集中在 `src/scrape_news.py` 的
  `_x_profile_urls()`。
- **免费额度**：Workers 免费版 10 万请求/天、单请求 CPU 10ms。纯转发的等待
  时间不计入 CPU，本项目用量（5 请求/天）远不构成压力；token 校验就是为了防止
  别人扫到你的 Worker 蹭额度。
- **无缓存**：响应带 `cache-control: no-store`，保证拿到的是实时页面。
