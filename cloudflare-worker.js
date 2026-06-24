const RAW_CACHE_URL = "https://raw.githubusercontent.com/yuhangjiang22/wc2026/main/data/cache.json";
const CACHE_TTL_SECONDS = 45;

function jsonResponse(data, init = {}) {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": `public, max-age=${CACHE_TTL_SECONDS}`,
      "access-control-allow-origin": "*",
      ...(init.headers || {}),
    },
  });
}

async function fetchCacheJson(request, env, ctx) {
  const cache = caches.default;
  const cacheKey = new Request(new URL("/api/cache", request.url), request);
  const cached = await cache.match(cacheKey);
  if (cached) return cached;

  const upstream = await fetch(`${RAW_CACHE_URL}?ts=${Date.now()}`, {
    headers: { "user-agent": "worldcup-knockout-worker/1.0" },
    cf: { cacheTtl: 0, cacheEverything: false },
  });

  if (!upstream.ok) {
    return jsonResponse({ error: `upstream ${upstream.status}` }, { status: 502 });
  }

  const payload = await upstream.json();
  const response = jsonResponse({
    ...payload,
    servedBy: "cloudflare-worker",
    workerFetchedAt: new Date().toISOString(),
  });
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  return response;
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: { "access-control-allow-origin": "*" } });
    if (url.pathname === "/api/cache") return fetchCacheJson(request, env, ctx);
    return new Response("Not found", { status: 404 });
  },
};
