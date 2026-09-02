// Versioned cache name for easy invalidation
const CACHE_VERSION = 'v1';
const PRECACHE = `aft-precache-${CACHE_VERSION}`;
const RUNTIME = `aft-runtime-${CACHE_VERSION}`;

// Core resources to precache (minimal – extend later)
const PRECACHE_URLS = [
  '/',
  '/status',
  '/weather',
  '/sea-temp-test',
  '/offline',
  '/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(PRECACHE).then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.filter(k => ![PRECACHE, RUNTIME].includes(k)).map(k => caches.delete(k))
    )).then(() => self.clients.claim())
  );
});

// Utility: determine if request is a navigation
function isNavigationRequest(request) {
  return request.mode === 'navigate';
}

self.addEventListener('fetch', event => {
  const { request } = event;

  // Skip non-GET
  if (request.method !== 'GET') return;

  // Navigation requests: Network first, fallback to offline page
  if (isNavigationRequest(request)) {
    event.respondWith(
      fetch(request).catch(() => caches.open(PRECACHE).then(c => c.match('/offline')))
    );
    return;
  }

  const url = new URL(request.url);

  // Same-origin static: Cache-first
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(request).then(cached => {
        if (cached) return cached;
        return caches.open(RUNTIME).then(cache =>
          fetch(request).then(response => {
            // Only cache successful basic responses
            if (response && response.status === 200 && response.type === 'basic') {
              cache.put(request, response.clone());
            }
            return response;
          })
        );
      })
    );
    return;
  }

  // Cross-origin (e.g., badatime iframe) – just try network; no cache
  event.respondWith(fetch(request));
});

// ---------------------------------------------------------------------------
// Web Push (Phase C)
// 여기가 없으면 서버가 푸시를 보내도 브라우저가 아무것도 하지 않는다.
// ---------------------------------------------------------------------------

self.addEventListener('push', event => {
  // 페이로드가 없거나 깨져도 알림은 띄운다. 조용히 삼키면 원인을 알 수 없다.
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: '낚시배 알림', body: event.data ? event.data.text() : '' };
  }

  const title = data.title || '낚시배 알림';
  const options = {
    body: data.body || '',
    icon: '/img/icons/icon-192.png',
    badge: '/img/icons/icon-192.png',
    // 같은 배·날짜의 알림이 여러 개 쌓이지 않고 갱신되도록 tag 를 준다
    tag: data.tag || 'aft-notify',
    renotify: true,
    data: { url: data.url || '/status' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/status';

  // 이미 열려 있는 탭이 있으면 그 탭을 쓴다. 누를 때마다 새 창이 뜨면 성가시다.
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      for (const client of windowClients) {
        if (client.url === target && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(target);
    })
  );
});
