const CACHE_NAME = 'modelRating-cache-v2';

const urlsToCache = [
  './',
  './index.html',
  './forecast.html',
  './current_weather.html',
  './manifest.json',
  './verify.css',
  './current_weather.css',
  './a_digital_vector_icon_features_a_white_minimalist.png'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(urlsToCache))
  );
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => response || fetch(event.request))
  );
});