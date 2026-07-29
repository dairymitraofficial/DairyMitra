/* =====================================
   DairyMitr Service Worker
   Production Ready
===================================== */

const CACHE_NAME = "dairy-mitr-cache-v21";

const APP_SHELL = [
  "/",
  "/customer/dashboard",
  "/customer/notifications",
  "/customer/profile",

  "/static/css/style.css",
  "/static/css/receipt.css",
  "/static/css/about.css",

  "/static/manifest.json"
];

/* =====================================
   INSTALL
===================================== */

self.addEventListener("install", event => {

  event.waitUntil(

    caches.open(CACHE_NAME).then(async cache => {

      for (const url of APP_SHELL) {

        try {
          await cache.add(url);
          console.log("Cached:", url);

        } catch (err) {
          console.log("Skipped:", url);
        }

      }

    })

  );

  self.skipWaiting();

});


/* =====================================
   ACTIVATE
===================================== */

self.addEventListener("activate", event => {

  event.waitUntil(

    caches.keys().then(keys =>

      Promise.all(

        keys.map(key => {

          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }

        })

      )

    )

  );

  self.clients.claim();

});


/* =====================================
   FETCH
===================================== */

self.addEventListener("fetch", event => {

  const request = event.request;

  if (request.method !== "GET") return;

  if (request.mode === "navigate") {

    event.respondWith(

      caches.match(request).then(cached => {

        if (cached) {
          return cached;
        }

        return fetch(request)

          .then(response => {

            if (response.ok) {

              const clone = response.clone();

              caches.open(CACHE_NAME)
                .then(cache => cache.put(request, clone));

            }

            return response;

          })

          .catch(() => {

            return caches.match("/");

          });

      })

    );

    return;

  }

  event.respondWith(

    caches.match(request).then(cached => {

      if (cached) {

        return cached;

      }

      return fetch(request)

        .then(response => {

          if (
            response &&
            response.status === 200 &&
            response.type === "basic"
          ) {

            const clone = response.clone();

            caches.open(CACHE_NAME)
              .then(cache => cache.put(request, clone));

          }

          return response;

        })

        .catch(() => caches.match(request));

    })

  );

});


/* =====================================
   PUSH
===================================== */

self.addEventListener("push", event => {

  if (!event.data) return;

  let data;

  try {

    data = event.data.json();

  } catch {

    data = {
      title: "DairyMitr",
      body: event.data.text()
    };

  }

  event.waitUntil(

    self.registration.showNotification(

      data.title || "DairyMitr",

      {

        body: data.body || "",

        icon: "/static/images/logo.png",

        badge: "/static/images/logo.png",

        vibrate: [200, 100, 200],

        data: {

          url: data.url || "/customer/dashboard"

        }

      }

    )

  );

});


/* =====================================
   NOTIFICATION CLICK
===================================== */

self.addEventListener("notificationclick", event => {

  event.notification.close();

  const url = event.notification.data.url || "/customer/dashboard";

  event.waitUntil(

    clients.matchAll({

      type: "window",

      includeUncontrolled: true

    }).then(windowClients => {

      for (const client of windowClients) {

        if (client.url.includes(url)) {

          return client.focus();

        }

      }

      return clients.openWindow(url);

    })

  );

});