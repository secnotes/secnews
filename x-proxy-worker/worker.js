/**
 * secnews — fetch proxy for sources that block datacenter IPs
 * (Cloudflare Worker)
 *
 * Why this exists: some sources reject requests from datacenter IP
 * ranges — x.com since ~2026-08-30 (GitHub Actions runners on Azure get
 * an instant HTTP 403 on logged-out profile fetches) and freebuf.com
 * similarly blocks the CI runner on its /feed endpoint — while
 * Cloudflare's egress IPs are still allowed. This Worker forwards
 * locked-down GETs so the CI scraper can reach them. Deploy steps: see
 * README.md in this folder.
 *
 * Usage:
 *   GET /?token=<PROXY_TOKEN>&url=https://x.com/<handle>
 *   GET /?token=<PROXY_TOKEN>&url=https://www.freebuf.com/feed
 *
 * Constraints baked in on purpose:
 *   - GET only
 *   - https hosts listed in ALLOWED_HOSTS only, each limited to the
 *     exact path shapes its scraper needs
 *   - shared-secret token required (set PROXY_TOKEN, deny-all while unset)
 */

// Per-host allowlist: each entry maps a host to the path shapes its
// scraper actually fetches, so a leaked token cannot turn this Worker
// into a general-purpose proxy — only x.com profile/tweet pages and the
// freebuf.com RSS feed are reachable.
const ALLOWED_HOSTS = {
  'x.com': [
    /^\/[A-Za-z0-9_]{1,15}$/,
    /^\/[A-Za-z0-9_]{1,15}\/status\/\d+$/,
  ],
  'www.freebuf.com': [
    /^\/feed$/,
  ],
};

// Same identity the scraper sends on direct fetches, so the upstream
// HTML (and thus the parsing in scrape_news.py) is identical either way.
const FETCH_HEADERS = {
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Accept-Language': 'en-US,en;q=0.9',
};

function deny(status, message) {
  return new Response(message, {
    status,
    headers: { 'cache-control': 'no-store' },
  });
}

export default {
  async fetch(request, env) {
    if (request.method !== 'GET') {
      return deny(405, 'method not allowed');
    }

    // Shared-secret guard. Set via `wrangler secret put PROXY_TOKEN`
    // or dashboard → Settings → Variables and Secrets. While unset the
    // Worker denies everything, so an unconfigured deployment can never
    // be abused as an open proxy.
    const expected = env.PROXY_TOKEN;
    const url = new URL(request.url);
    if (!expected || url.searchParams.get('token') !== expected) {
      return deny(403, 'forbidden');
    }

    const target = url.searchParams.get('url');
    if (!target) {
      return deny(400, 'missing url');
    }

    let targetUrl;
    try {
      targetUrl = new URL(target);
    } catch {
      return deny(400, 'bad url');
    }
    if (targetUrl.protocol !== 'https:') {
      return deny(400, 'protocol not allowed');
    }
    const allowedPaths = ALLOWED_HOSTS[targetUrl.hostname];
    if (!allowedPaths) {
      return deny(400, 'host not allowed');
    }
    if (!allowedPaths.some((re) => re.test(targetUrl.pathname))) {
      return deny(400, 'path not allowed');
    }

    try {
      const upstream = await fetch(targetUrl.toString(), {
        method: 'GET',
        headers: FETCH_HEADERS,
        redirect: 'follow',
      });

      // Stream the upstream body through untouched: status code, content
      // type and all. A 403 from x.com propagates as 403 so the scraper
      // sees the real upstream status, not a masked one.
      return new Response(upstream.body, {
        status: upstream.status,
        headers: {
          'content-type':
            upstream.headers.get('content-type') || 'text/html; charset=utf-8',
          'cache-control': 'no-store',
        },
      });
    } catch (e) {
      return deny(502, `upstream fetch failed: ${e}`);
    }
  },
};
