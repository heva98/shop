// Lets the app itself open with no connection, so the till can keep
// selling (see src/offline/). Only the app's own files and fonts are kept
// here; API data is never cached by this worker — the till keeps its own
// copy in IndexedDB and decides what is safe to use offline.

const CACHE = 'duka-erp-app-v1'
const SHELL = '/index.html'

// Every script and stylesheet of this deploy, from asset-list.json (written
// by the build, see vite.config.js). Screens load on demand, so it is more
// than what index.html references; without the list (the dev server) fall
// back to those.
async function buildAssets(html) {
  try {
    const response = await fetch('/asset-list.json', { cache: 'no-cache' })
    if (response.ok) return new Set(await response.json())
  } catch { /* offline or dev: use the page's own references */ }
  return new Set([...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]))
}

// The page's own scripts and styles load before this worker first runs, so
// save them now too, along with the screens it may open later.
async function saveShell() {
  const cache = await caches.open(CACHE)
  const response = await fetch(SHELL, { cache: 'no-cache' })
  const html = await response.clone().text()
  await cache.put(SHELL, response)
  const assets = await buildAssets(html)
  const missing = []
  for (const path of assets) if (!(await cache.match(path))) missing.push(path)
  await cache.addAll(missing)
  // Drop the previous deploy's files; their names never come back.
  for (const req of await cache.keys()) {
    const { pathname } = new URL(req.url)
    if (pathname.startsWith('/assets/') && /\.(js|css)$/.test(pathname) && !assets.has(pathname)) await cache.delete(req)
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil(saveShell())
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key !== CACHE) await caches.delete(key)
    await self.clients.claim()
  })())
})

const isFont = (url) => url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com'

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  const sameOrigin = url.origin === self.location.origin
  if (sameOrigin && /^\/(api|admin)\//.test(url.pathname)) return
  if (!sameOrigin && !isFont(url)) return

  // Pages: the newest app when online (so a deploy is picked up), the
  // saved one when not.
  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const response = await fetch(request)
        // A new deploy: save its index.html and assets for the next offline start.
        if (response.ok) event.waitUntil(saveShell().catch(() => {}))
        return response
      } catch {
        return (await caches.match(SHELL)) || Response.error()
      }
    })())
    return
  }

  // Built assets have hashed names, so a saved copy never goes stale; the
  // rest (logo, favicon, fonts) is served saved and refreshed behind.
  event.respondWith((async () => {
    const cache = await caches.open(CACHE)
    const saved = await cache.match(request)
    if (saved && sameOrigin && url.pathname.startsWith('/assets/')) return saved
    const fresh = fetch(request).then((response) => {
      if (response.ok || response.type === 'opaque') cache.put(request, response.clone())
      return response
    })
    if (saved) {
      fresh.catch(() => {})
      return saved
    }
    return fresh
  })())
})
