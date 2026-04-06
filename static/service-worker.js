
/* =====================================
   DairyMitr Service Worker
   Version: v12
   App Shell + Offline Navigation Fix
===================================== */

const CACHE_NAME = "dairy-mitr-cache-v12";

const APP_SHELL = [

  "/",
  "/dashboard",
  "/milk_collection",

  "/static/css/style.css",
  "/static/css/receipt.css",
  "/static/css/about.css",

  "/static/manifest.json"

];


/* =====================================
   INSTALL
===================================== */

self.addEventListener("install", event => {

  console.log("Service Worker Installing");

  event.waitUntil(

    caches.open(CACHE_NAME)
      .then(cache => {

        console.log("Caching App Shell");

        return cache.addAll(APP_SHELL);

      })

  );

  self.skipWaiting();

});


/* =====================================
   ACTIVATE
===================================== */

self.addEventListener("activate", event => {

  console.log("Service Worker Activated");

  event.waitUntil(

    caches.keys().then(keys => {

      return Promise.all(

        keys.map(key => {

          if(key !== CACHE_NAME){
            console.log("Deleting old cache:", key);
            return caches.delete(key);
          }

        })

      );

    })

  );

  self.clients.claim();

});


/* =====================================
   FETCH
===================================== */

self.addEventListener("fetch", event => {

  const request = event.request;

  if(request.method !== "GET") return;


  /* -------- NAVIGATION REQUESTS -------- */

  if(request.mode === "navigate"){

    event.respondWith(

      caches.match(request)
        .then(cachedPage => {

          if(cachedPage){
            return cachedPage;
          }

          return fetch(request)
            .then(networkResponse => {

              const clone = networkResponse.clone();

              caches.open(CACHE_NAME)
              .then(cache => cache.put(request, clone));

              return networkResponse;

            })
            .catch(() => caches.match("/dashboard"));

        })

    );

    return;

  }


  /* -------- STATIC FILES -------- */

  event.respondWith(

    caches.match(request)
      .then(cached => {

        if(cached){
          return cached;
        }

        return fetch(request)
          .then(response => {

            const clone = response.clone();

            caches.open(CACHE_NAME)
            .then(cache => cache.put(request, clone));

            return response;

          })
          .catch(() => caches.match(request));

      })

  );

});

