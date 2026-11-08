/* OpenWar Intelligence — service worker (v13.3, 08/11/2026)
 *
 * Regole, nell'ordine in cui contano:
 *  1. Niente di finto: i feed dal vivo si leggono SEMPRE prima dalla rete. La copia in cache
 *     serve solo offline e porta la sua data (generated_at): la dashboard la mostra come eta'
 *     del dato e dopo 20 minuti la dichiara "non disponibile". Mai un dato vecchio spacciato per fresco.
 *  2. La shell (pagina, icone, manifest) e le librerie CDN si installano in cache per aprire l'app
 *     anche senza rete.
 *  3. Tutto il resto (tessere mappa, analytics, API live di terzi, proxy) NON viene intercettato.
 */
const VERSION = 'owi-v13.3-2026-11-08';
const SHELL_CACHE = 'owi-shell-' + VERSION;
const DATA_CACHE = 'owi-data-' + VERSION;
const SHELL = [
  '/monitor-guerra.html',
  '/manifest.webmanifest',
  '/openwar-icon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];
const CDN_HOSTS = ['cdnjs.cloudflare.com', 'fonts.googleapis.com', 'fonts.gstatic.com'];
const DATA_HOSTS = ['raw.githubusercontent.com'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL_CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((k) => k.startsWith('owi-') && k !== SHELL_CACHE && k !== DATA_CACHE).map((k) => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

function isDataRequest(url) {
  if (DATA_HOSTS.includes(url.hostname)) return true;
  if (url.origin === self.location.origin && url.pathname.startsWith('/data/') && url.pathname.endsWith('.json')) return true;
  return false;
}

async function networkFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(req, { ignoreSearch: true });
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res && res.ok) cache.put(req, res.clone());
  return res;
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  let url;
  try { url = new URL(req.url); } catch (_) { return; }

  if (isDataRequest(url)) {
    // feed dal vivo: rete prima, cache solo come ripiego offline (e' datata, la dashboard lo dice)
    e.respondWith(networkFirst(req, DATA_CACHE));
    return;
  }
  if (CDN_HOSTS.includes(url.hostname)) {
    e.respondWith(cacheFirst(req, SHELL_CACHE));
    return;
  }
  if (url.origin === self.location.origin) {
    if (req.mode === 'navigate' || url.pathname.endsWith('.html')) {
      e.respondWith(networkFirst(req, SHELL_CACHE));
      return;
    }
    if (/\.(png|svg|ico|webmanifest|css|js|woff2?)$/.test(url.pathname)) {
      e.respondWith(cacheFirst(req, SHELL_CACHE));
      return;
    }
  }
  // tutto il resto passa dritto alla rete
});

self.addEventListener('message', (e) => {
  if (e.data === 'SKIP_WAITING') self.skipWaiting();
});
