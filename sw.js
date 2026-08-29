/* Service worker for usvschina.ai.
 *
 * Strategy:
 *  - Precache the app shell on install.
 *  - Network-first with cache fallback for same-origin GETs, so data stays
 *    fresh online and the last-seen leaderboard still renders offline.
 *  - models.json (multi-MB full archive) is deliberately never cached;
 *    current.json (~40 KB) is what the main page uses.
 */
const CACHE_NAME = 'usvschina-v1';

const PRECACHE = [
  '/',
  '/index.html',
  '/history.html',
  '/about.html',
  '/current.json',
  '/news.json',
  '/site.webmanifest',
  '/favicon.svg',
];

const NEVER_CACHE = ['/models.json'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER_CACHE.some((p) => url.pathname === p)) return;

  event.respondWith(
    fetch(req)
      .then((resp) => {
        if (resp && resp.ok) {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        }
        return resp;
      })
      .catch(() =>
        caches.match(req).then((cached) => {
          if (cached) return cached;
          // Offline navigation with nothing cached for that URL: fall back
          // to the cached shell.
          if (req.mode === 'navigate') return caches.match('/');
          return Response.error();
        })
      )
  );
});
