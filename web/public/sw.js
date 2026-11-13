// Keeps the app's own files so it opens instantly and without a connection.
// API responses are personal data and are never stored here.
const CACHE = 'creed-shell-v2';

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
  // The public pages aren't part of the app: leave them to the network so they're never saved as the app's page.
  if (['/welcome', '/try', '/feedback'].some((page) => url.pathname.startsWith(page))) {
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

// Notifications from Creed's server, such as a reminder to log food. The message arrives encrypted for this phone.
self.addEventListener('push', (event) => {
  let message = {};
  try {
    message = event.data ? event.data.json() : {};
  } catch {
    message = { body: event.data ? event.data.text() : '' };
  }
  event.waitUntil(
    self.registration.showNotification(message.title || 'Creed', {
      body: message.body || '',
      icon: '/icons/icon-192.png',
      badge: '/icons/icon-192.png',
      tag: message.tag || 'creed',
      data: { url: message.url || '/' },
    }),
  );
});

// Tapping a notification opens the app at the right screen, reusing it if it's already open.
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || '/', self.location.origin);
  if (target.origin !== self.location.origin) return;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if ('focus' in client) {
          client.navigate?.(target.href);
          return client.focus();
        }
      }
      return self.clients.openWindow(target.href);
    }),
  );
});
