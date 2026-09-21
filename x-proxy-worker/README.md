# Fetch Proxy for Datacenter-Blocked Sources (Cloudflare Worker)

为 secnews 里被数据中心 IP 屏蔽的数据源提供的免费转发代理（当前覆盖 X
个人主页与 FreeBuf RSS）。

## 为什么需要它

部分站点对数据中心 IP 段拒绝访问，而 GitHub Actions 的 runner 跑在 Azure
数据中心上，直连即被拒：

- **x.com**：2026-08-30 前后在改版 SSR 标记（移除 microdata）的同时开始拒绝，
  直连 `https://x.com/<handle>` 得到**毫秒级 HTTP 403**，X 数据源在 CI 中归零
  （解析代码本身是好的，本地走代理出口可正常抓取）。
- **freebuf.com**：`https://www.freebuf.com/feed` 对 CI runner 同样拒绝，
  本地直连正常。

实测各出口 IP 对 x.com 的可达性：

| 出口 | 结果 |
|---|---|
| GitHub Actions / Azure（数据中心） | HTTP 403，直接拒绝 |
| 常见公共数据中心代理 | 520 / 522 |
| 住宅类代理出口（本地 `.env` 配置的代理） | HTTP 200，完整 SSR 页面 |
| **Cloudflare Workers 出口** | **HTTP 200，完整 SSR 页面** |

这些站点目前封的是 Azure/AWS 这类云主机段，没有封 Cloudflare 的出口。Worker
免费版每天 10 万请求，本项目只需个位数请求/天，余量充足。

## 文件说明

| 文件 | 作用 |
|---|---|
| `worker.js` | Worker 源码：带 token 校验、只转发允许清单内主机的 GET 请求 |
| `wrangler.toml` | wrangler 部署配置（token 是 secret，不在文件里） |

Worker 刻意收窄了能力面，即使 token 泄露也只是几个只读页面的代理：

- 仅接受 `GET`
- 仅允许 `https` 协议
- 仅允许主机允许清单中的目标，且每个主机只开放其爬虫需要的路径：
  - `x.com`：`/<handle>`（个人主页）和 `/<handle>/status/<id>`（推文 permalink）
  - `www.freebuf.com`：`/feed`（RSS）
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

# 应返回 200 和 FreeBuf RSS XML
curl -s -o /dev/null -w "%{http_code} %{size_download}B\n" \
  "https://<你的worker地址>/?token=<你的token>&url=https://www.freebuf.com/feed"

# 缺 token 应返回 403
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://<你的worker地址>/?url=https://x.com/portswigger"

# 允许清单之外的目标应返回 400
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://<你的worker地址>/?token=<你的token>&url=https://example.com"

# 允许主机但不在允许路径内也应返回 400
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://<你的worker地址>/?token=<你的token>&url=https://www.freebuf.com/articles"
```

## 接入 secnews

爬虫通过两个环境变量识别 Worker，**均为可选**——不配置时行为与原来完全一致。
变量名带 `X_` 前缀是历史原因（最初只为 X 服务），现在由所有需要代理的数据源
共用同一个 Worker 实例：

| 环境变量 | 说明 |
|---|---|
| `X_PROXY_BASE` | Worker **完整地址，必须带 `https://` 协议头**，如 `https://secnews-x-proxy.xxx.workers.dev` 或 `https://proxy.example.cn`。只写域名（缺协议头）会被当成无效 URL，Worker 路径直接失败（随后自动回退直连） |
| `X_PROXY_TOKEN` | 部署时设置的 `PROXY_TOKEN` |

### GitHub Actions（CI）

在仓库 **Settings → Secrets and variables → Actions** 中配置：

- **Variables** 标签：`X_PROXY_BASE` = Worker 地址（非敏感，与 `AI_MODEL`、
  `AI_BASE_URL` 同类；放在 Secrets 标签下也能被读取）
- **Secrets** 标签：`X_PROXY_TOKEN` = token

workflow 已配置把这两个 secret 注入运行环境，配置好即生效，X 和 FreeBuf
两个数据源同时受益。

### 本地运行

在项目根目录 `.env` 里添加（参考 `.env.example`）：

```
X_PROXY_BASE=https://secnews-x-proxy.xxx.workers.dev
X_PROXY_TOKEN=你的token
```

## 失败降级行为（不影响其他爬虫源）

两个接入源的取页顺序互为镜像，取决于该站点在本地是否可用：

- **X**：x.com 对数据中心和多数住宅网络都拒绝，本地通常也抓不到 →
  **Worker 优先 → 失败则回退直连** → 再失败仅记录一条 ERROR 日志并跳过该账号。
- **FreeBuf**：freebuf.com 只屏蔽数据中心 IP，本地直连正常 →
  **直连优先 → 失败（仅 CI 场景）才走 Worker** → 再失败仅记录一条 ERROR
  日志，跳过该源。

任何一层失败都不会抛出异常中断流程，其余数据源照常抓取、AI 精选和页面生成
照常进行——这正是 9 月初 X 归零期间项目其他部分一直正常的原因，Worker 方案
完整保留了这个特性。

## 局限与维护

- **站点政策会变**：x.com 随时可能也封 Cloudflare 出口（8/30 的改版就是先例）。
  届时的症状是日志里出现 `via worker: HTTP 403`，爬虫会自动降级、其余源不受
  影响。若需更换方案（RSSHub 等），改动点集中在 `src/scrape_news.py` 的
  `_x_profile_urls()`（X）与 `scrape_freebuf()`（FreeBuf）。
- **免费额度**：Workers 免费版 10 万请求/天、单请求 CPU 10ms。纯转发的等待
  时间不计入 CPU，本项目用量（每天个位数请求）远不构成压力；token 校验就是
  为了防止别人扫到你的 Worker 蹭额度。
- **无缓存**：响应带 `cache-control: no-store`，保证拿到的是实时页面。
