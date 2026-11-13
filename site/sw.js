// Offline support: network first, falling back to the last copy. The build stamps VERSION on each deploy.
const VERSION = "dev";
const SHELL = `spiti-shell-${VERSION}`;
const DATA = "spiti-data";
const FILES = ["./", "index.html", "styles.css", "app.js", "schema.json",
  "prompts/collect-sources.md", "prompts/claude-notes.md"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)).catch(() => {}).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("spiti-shell-") && k !== SHELL).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin) return;
  const cacheName = url.pathname.includes("/data/") ? DATA : SHELL;
  event.respondWith(fetch(event.request).then((res) => {
    if (res.ok) {
      const copy = res.clone();
      caches.open(cacheName).then((c) => c.put(event.request, copy));
    }
    return res;
  }).catch(async () => {
    const hit = await caches.match(event.request, { ignoreSearch: true });
    if (!hit) return Response.error();
    const headers = new Headers(hit.headers);
    headers.set("x-from-cache", "1");
    return new Response(await hit.blob(), { status: hit.status, headers });
  }));
});
