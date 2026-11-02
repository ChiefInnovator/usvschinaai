/* Offline access uses only complete, hash-verified publication generations. */
const CACHE_PREFIX = 'usvschina-shell-v2-';
const META_CACHE = 'usvschina-shell-meta-v2';
const ACTIVE_KEY = new URL('/.offline-generation', self.location.origin).href;
const MANIFEST_PATH = '/data/publication.json';
let refreshInFlight = null;

const sha256 = async (bytes) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)))
    .map(value => value.toString(16).padStart(2, '0')).join('');

const activeName = async () => {
    const meta = await caches.open(META_CACHE);
    const response = await meta.match(ACTIVE_KEY);
    if (!response) return null;
    const name = await response.text();
    return name.startsWith(CACHE_PREFIX) ? name : null;
};

const safePath = (path) => typeof path === 'string' && !path.startsWith('/') &&
    !path.includes('..') && !/[?#:\\]/.test(path);

async function stageGeneration() {
    const response = await fetch(MANIFEST_PATH, {cache: 'no-store'});
    if (!response.ok) throw new Error('Publication manifest unavailable');
    const manifestText = await response.text();
    const manifest = JSON.parse(manifestText);
    const hashes = manifest.shellArtifacts;
    if (manifest.schemaVersion !== 1 || !/^[a-f0-9]{64}$/.test(manifest.generationId || '') ||
        !/^[a-f0-9]{64}$/.test(manifest.shellRevision || '') || !hashes) {
        throw new Error('Complete offline shell is unavailable');
    }
    const required = ['index.html', 'history.html', 'about.html', 'privacy.html', 'terms.html',
        '404.html', 'assets/site.css', 'assets/vendor/chart.umd.min.js',
        'assets/vendor/lucide.min.js', 'js/site-data.js', 'data/site_summary.json',
        'site.webmanifest', 'favicon.svg', 'favicon.ico', 'apple-touch-icon.png'];
    if (required.some(path => !hashes[path])) throw new Error('Incomplete offline shell manifest');
    const sorted = Object.fromEntries(Object.keys(hashes).sort().map(key => [key, hashes[key]]));
    if (await sha256(new TextEncoder().encode(JSON.stringify(sorted))) !== manifest.shellRevision) {
        throw new Error('Offline shell identity mismatch');
    }
    const name = CACHE_PREFIX + manifest.generationId + '-' + manifest.shellRevision;
    const previous = await activeName();
    if (previous === name && (await caches.keys()).includes(name)) return;
    await caches.delete(name);
    const staging = await caches.open(name);
    try {
        for (const [path, digest] of Object.entries(sorted)) {
            if (!safePath(path) || !/^[a-f0-9]{64}$/.test(digest)) throw new Error('Unsafe shell asset');
            const asset = await fetch('/' + path, {cache: 'no-store'});
            if (!asset.ok || await sha256(await asset.clone().arrayBuffer()) !== digest) {
                throw new Error('Incomplete publication; previous offline generation retained');
            }
            await staging.put('/' + path, asset);
        }
        await staging.put(MANIFEST_PATH, new Response(manifestText, {headers: {'Content-Type': 'application/json'}}));
        const meta = await caches.open(META_CACHE);
        // This single pointer changes only after every asset has been verified.
        await meta.put(ACTIVE_KEY, new Response(name));
    } catch (error) {
        await caches.delete(name);
        throw error;
    }
    const keep = new Set([name, previous].filter(Boolean));
    await Promise.all((await caches.keys()).filter(key =>
        key.startsWith('usvschina-') && key !== META_CACHE && !keep.has(key))
        .map(key => caches.delete(key)));
}

const refreshGeneration = () => {
    if (!refreshInFlight) refreshInFlight = stageGeneration().finally(() => { refreshInFlight = null; });
    return refreshInFlight;
};

self.addEventListener('install', event => {
    event.waitUntil(refreshGeneration().catch(() => {}).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
    event.waitUntil(self.clients.claim());
});
self.addEventListener('message', event => {
    if (event.data && event.data.type === 'REFRESH_PUBLICATION') {
        event.waitUntil(refreshGeneration().catch(() => {}));
    }
});
self.addEventListener('fetch', event => {
    const request = event.request;
    if (request.method !== 'GET' || new URL(request.url).origin !== self.location.origin) return;
    if (request.mode === 'navigate') event.waitUntil(refreshGeneration().catch(() => {}));
    event.respondWith(fetch(request).catch(async () => {
        const name = await activeName();
        if (!name) return Response.error();
        const cache = await caches.open(name);
        const url = new URL(request.url);
        if (url.pathname === '/') url.pathname = '/index.html';
        url.search = '';
        const stored = await cache.match(url.href);
        if (!stored) return Response.error();
        const headers = new Headers(stored.headers);
        headers.set('X-Site-Cache', 'offline');
        return new Response(await stored.arrayBuffer(), {status: stored.status,
            statusText: stored.statusText, headers});
    }));
});
