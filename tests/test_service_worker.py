"""Execute the actual worker in Node's VM with browser-compatible response/crypto APIs.

The deterministic network and CacheStorage model never make external requests.
"""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node is required for service worker execution')
class ServiceWorkerTests(unittest.TestCase):
    def test_atomic_offline_generations_and_failure_boundaries(self):
        script = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const crypto = require('node:crypto');
const origin = 'https://offline.test';
const key = value => new URL(typeof value === 'string' ? value : value.url, origin).href;
const storage = new Map();
const caches = {
  async open(name) {
    if (!storage.has(name)) storage.set(name, new Map());
    const entries = storage.get(name);
    return {
      async put(url, response) { entries.set(key(url), response.clone()); },
      async match(url) { return entries.get(key(url))?.clone(); }
    };
  },
  async keys() { return [...storage.keys()]; },
  async delete(name) { return storage.delete(name); }
};
const listeners = {};
let network = new Map(), offline = false, interrupted = null;
const requested = [];
const context = vm.createContext({
  URL, Response, Request, Headers, TextEncoder, crypto: crypto.webcrypto, caches,
  self: {location: {origin}, clients: {claim: async () => {}}, skipWaiting: async () => {},
    addEventListener(type, listener) { listeners[type] = listener; }},
  fetch: async request => {
    const path = new URL(typeof request === 'string' ? request : request.url, origin).pathname;
    requested.push(path);
    if (offline || path === interrupted) throw new Error('simulated network interruption');
    return network.has(path) ? new Response(network.get(path)) : new Response('missing', {status: 404});
  }
});
vm.runInContext(fs.readFileSync('sw.js', 'utf8'), context);
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const required = ['index.html', 'history.html', 'about.html', 'privacy.html', 'terms.html',
  '404.html', 'assets/site.css', 'assets/vendor/chart.umd.min.js',
  'assets/vendor/lucide.min.js', 'js/site-data.js', 'data/site_summary.json',
  'site.webmanifest', 'favicon.svg', 'favicon.ico', 'apple-touch-icon.png'];
function publication(generation, frontend = 'one', omit = null) {
  const assets = Object.fromEntries(required.filter(path => path !== omit).map(path =>
    [path, path === 'data/site_summary.json' ? JSON.stringify({generation}) : path + frontend]));
  const hashes = Object.fromEntries(Object.keys(assets).sort().map(path => [path, digest(assets[path])]));
  const manifest = {schemaVersion: 1, generationId: digest(generation), shellArtifacts: hashes,
                    shellRevision: digest(JSON.stringify(hashes))};
  network = new Map(Object.entries(assets).map(([path, bytes]) => ['/' + path, bytes]));
  network.set('/data/publication.json', JSON.stringify(manifest));
  return manifest;
}
async function event(type, data = {}) {
  const pending = [];
  listeners[type]({...data, waitUntil(promise) {pending.push(promise);}});
  await Promise.all(pending);
}
async function active() {
  const meta = await caches.open('usvschina-shell-meta-v2');
  return (await meta.match('/.offline-generation'))?.text();
}
async function cached(path, mode = 'cors') {
  let response;
  const pending = [];
  listeners.fetch({request: {url: origin + path, method: 'GET', mode},
    waitUntil(promise) {pending.push(promise);}, respondWith(promise) {response = promise;}});
  const result = await response;
  await Promise.all(pending);
  return result;
}
async function refresh() { await event('message', {data: {type: 'REFRESH_PUBLICATION'}}); }
(async () => {
  offline = true;
  assert.equal((await cached('/data/missing.json', 'navigate')).status, 0, 'first offline visit must fail');
  offline = false;
  publication('generation-one');
  await event('install');
  const first = await active();
  assert.ok(first, 'complete shell activates');
  assert.ok(!requested.includes('/models.json'), 'raw archives are not precached');
  offline = true;
  assert.equal(await (await cached('/', 'navigate')).text(), 'index.htmlone');
  assert.equal(await (await cached('/assets/vendor/chart.umd.min.js')).text(), 'assets/vendor/chart.umd.min.jsone');
  assert.equal((await cached('/data/unknown.json', 'navigate')).status, 0, 'never return HTML as successful JSON');
  assert.equal((await cached('/models.json')).status, 0, 'raw archives are not precached');
  offline = false;
  publication('generation-two');
  interrupted = '/js/site-data.js';
  await refresh();
  assert.equal(await active(), first, 'interrupted stage retains old pointer');
  assert.equal((await caches.keys()).filter(name => name.startsWith('usvschina-shell-v2-')).length, 1);
  offline = true;
  assert.equal(await (await cached('/data/site_summary.json')).text(), JSON.stringify({generation: 'generation-one'}));
  offline = false;
  interrupted = null;
  publication('generation-two');
  network.set('/assets/site.css', 'mixed deployment bytes');
  await refresh();
  assert.equal(await active(), first, 'mixed hashes cannot replace usable shell');
  const corruptIdentity = publication('invalid-identity');
  corruptIdentity.shellRevision = '0'.repeat(64);
  network.set('/data/publication.json', JSON.stringify(corruptIdentity));
  await refresh();
  assert.equal(await active(), first, 'manifest identity must match the complete hash map');
  const unsafe = publication('unsafe-path');
  unsafe.shellArtifacts['../private.json'] = digest('private');
  unsafe.shellArtifacts = Object.fromEntries(Object.keys(unsafe.shellArtifacts).sort().map(path => [path, unsafe.shellArtifacts[path]]));
  unsafe.shellRevision = digest(JSON.stringify(unsafe.shellArtifacts));
  network.set('/data/publication.json', JSON.stringify(unsafe));
  await refresh();
  assert.equal(await active(), first, 'unsafe manifest paths cannot replace the complete generation');
  assert.ok(!requested.includes('/private.json'), 'unsafe paths must not trigger network reads');
  for (const missing of required) {
    publication('missing-' + missing, 'one', missing);
    await refresh();
    assert.equal(await active(), first, 'incomplete shell accepted without ' + missing);
  }
  const secondManifest = publication('generation-two');
  await refresh();
  const second = await active();
  assert.notEqual(second, first, 'new data changes cache identity');
  assert.ok(second.includes(secondManifest.generationId));
  const thirdManifest = publication('generation-two', 'frontend-change');
  await refresh();
  const third = await active();
  assert.notEqual(third, second, 'frontend-only update changes identity');
  assert.ok(third.includes(thirdManifest.shellRevision));
  for (let i = 3; i < 7; i++) { publication('generation-' + i); await refresh(); }
  assert.equal((await caches.keys()).filter(name => name.startsWith('usvschina-shell-v2-')).length, 2,
               'retain only active and previous complete shells');
  assert.ok(!requested.some(path => path.includes('model_catalog')), 'catalog is never precached');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        result = subprocess.run(['node', '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
