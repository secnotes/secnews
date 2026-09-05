/**
 * secnews — X (Twitter) profile fetch proxy
 *
 * Why this exists: since ~2026-08-30 x.com rejects logged-out profile
 * fetches from datacenter IP ranges (GitHub Actions runners on Azure get
 * an instant HTTP 403), while Cloudflare's egress IPs are still allowed.
 * This Worker forwards a locked-down GET to x.com so the CI scraper can
 * reach it. Deploy steps: see README.md in this folder.
 *
 * Usage:
 *   GET /?token=<PROXY_TOKEN>&url=https://x.com/<handle>
 *
 * Constraints baked in on purpose:
 *   - GET only
 *   - https://x.com host only
 *   - profile paths (/<handle>) and tweet permalinks (/<handle>/status/<id>) only
 *   - shared-secret token required (set PROXY_TOKEN, deny-all while unset)
 */

const ALLOWED_HOST = 'x.com';

// Locked down to the two path shapes the scraper actually needs, so a
// leaked token cannot turn this Worker into a general-purpose proxy.
const ALLOWED_PATHS = [
  /^\/[A-Za-z0-9_]{1,15}$/,
  /^\/[A-Za-z0-9_]{1,15}\/status\/\d+$/,
];

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
    if (targetUrl.protocol !== 'https:' || targetUrl.hostname !== ALLOWED_HOST) {
      return deny(400, 'host not allowed');
    }
    if (!ALLOWED_PATHS.some((re) => re.test(targetUrl.pathname))) {
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
