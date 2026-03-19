const CACHE_NAME = 'modelRating-cache-v1';
const urlsToCache = [
  './',
  './index.html',
  './manifest.json',
  './a_digital_vector_icon_features_a_white_minimalist.png',
  './style.css'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(urlsToCache))
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => response || fetch(event.request))
  );
});