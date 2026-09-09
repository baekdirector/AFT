// Versioned cache name for easy invalidation
const CACHE_VERSION = 'v2';
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

  // API 응답은 매번 최신이어야 한다(감시 목록/체크 기록/예약현황 등) - 캐시하면
  // "재등록해도 화면이 그대로"인 버그가 난다(폰은 서비스워커가 PC보다 오래
  // 살아있어 캐시가 안 갱신된 채 굳어버린다). 네트워크로만 보낸다.
  if (url.origin === self.location.origin && url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

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
    // 예전엔 icon 과 badge 둘 다 앱 아이덴티티용 큰 "AFT" 정사각 로고를
    // 그대로 썼다 - Windows/Chrome 토스트에서 88px로 커져 본문 폭을 절반
    // 잡아먹었다("푸시 알림 디자인" 스펙 D절). 알림 전용 아이콘(초록 종)과
    // 안드로이드 상태바용 단색 실루엣 배지를 따로 둔다.
    icon: '/img/icons/notify-bell-192.png',
    badge: '/img/icons/badge-anchor-96.png',
    // 같은 배·날짜의 알림이 여러 개 쌓이지 않고 갱신되도록 tag 를 준다
    tag: data.tag || 'aft-notify',
    renotify: true,
    requireInteraction: false,
    data: {
      url: data.url || '/status',
      boatId: data.boatId ?? null,
      shipName: data.shipName || null,
      targetDate: data.targetDate || null,
    },
  };
  // 실제 감시 전환 알림만 액션 버튼을 준다(테스트 알림은 실제 배/URL이 없어 생략).
  if (Array.isArray(data.actions) && data.actions.length) options.actions = data.actions;

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', event => {
  const info = event.notification.data || {};
  const action = event.action;   // '' = 본문 클릭, 그 외 = 액션 버튼
  event.notification.close();

  if (action === 'mute') {
    event.waitUntil(muteFromNotification(info));
    return;
  }

  const target = info.url || '/status';

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

// 알림의 "알림 끄기" 버튼 - 이 배 하나(그 알림이 가리키는 boat/ship/date)의
// 감시만 해제한다. 이 서비스워커가 곧 그 구독자이므로 자기 구독 endpoint 를
// 다시 물어봐서(이미 로그인/토큰 없이 endpoint 자체가 신원이다) DELETE
// /api/watches 를 그대로 호출한다 - 새 API를 만들지 않는다.
async function muteFromNotification(info) {
  if (!info.boatId || !info.shipName || !info.targetDate) return;
  try {
    const sub = await self.registration.pushManager.getSubscription();
    if (!sub) return;
    await fetch('/api/watches', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoint: sub.endpoint,
        boat_id: info.boatId,
        ship_name: info.shipName,
        target_date: info.targetDate,
      }),
    });
  } catch (e) {
    // 조용히 실패 - 이 배는 /watches 화면에서 직접 끌 수 있다.
  }
}
