// Keeps the app's own files so it opens instantly and without a connection.
// API responses are personal data and are never stored here.
const CACHE = 'creed-shell-v1';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) => Promise.all(names.filter((name) => name !== CACHE).map((name) => caches.delete(name))))
      .then(() => self.clients.claim()),
  );
});

async function remember(request, response) {
  if (response.ok) {
    const cache = await caches.open(CACHE);
    await cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) {
    return;
  }
  if (event.request.mode === 'navigate') {
    // The newest page when online, the saved one when not.
    event.respondWith(
      fetch(event.request)
        .then((response) => remember('/', response))
        .catch(() => caches.match('/')),
    );
    return;
  }
  // Built files have their content in their name, so a saved copy is never out of date.
  event.respondWith(
    caches.match(event.request).then((hit) => hit || fetch(event.request).then((r) => remember(event.request, r))),
  );
});
