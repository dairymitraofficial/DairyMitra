const CACHE_NAME = "dairy-mitr-cache-v5";

const STATIC_FILES = [

  "/static/css/style.css",
  "/static/css/receipt.css",
  "/static/css/about.css",
  "/static/manifest.json"

];

// INSTALL
self.addEventListener("install", event => {

  event.waitUntil(

    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_FILES))

  );

  self.skipWaiting();

});


// ACTIVATE
self.addEventListener("activate", event => {

  event.waitUntil(

    caches.keys().then(keys => {

      return Promise.all(

        keys.map(key => {

          if(key !== CACHE_NAME){

            return caches.delete(key);

          }

        })

      );

    })

  );

  self.clients.claim();

});


// FETCH
self.addEventListener("fetch", event => {

  if(event.request.method !== "GET") return;

  event.respondWith(

    fetch(event.request)

      .then(response => {

        const clone = response.clone();

        caches.open(CACHE_NAME)
          .then(cache => cache.put(event.request, clone));

        return response;

      })

      .catch(() => {

        return caches.match(event.request);

      })

  );

});