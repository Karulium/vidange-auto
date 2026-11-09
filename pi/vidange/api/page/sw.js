// Service worker de la page web (tâche 28 bis). Il garde UNIQUEMENT la « coquille » de la page
// (la page elle-même, son code, ses icônes) pour qu'elle s'ouvre même si le Pi est injoignable.
//
// Il ne garde JAMAIS une réponse de l'API (/api/...) : l'état de la machine, les alarmes, les
// photos, les vidéos viennent toujours du Pi, en direct. Hors ligne, la page s'ouvre mais dit que
// le Pi ne répond pas ; elle ne montre jamais un vieil état de la machine.
//
// Le numéro de version ci-dessous est fabriqué par le Pi à partir du contenu de tous les fichiers
// de la page : il change à chaque modification, l'ancien cache est alors effacé.
"use strict";

const VERSION = "__VERSION__";
const CACHE = "vidange-coquille-" + VERSION;
const PREFIXE_CACHE = "vidange-coquille-";
// Fichiers publics gardés dès l'installation (la page « / » est ajoutée si c'est la vraie page).
const COQUILLE = ["/manifeste.webmanifest", "/icones/icone-192.png", "/icones/icone.svg"];
// En-tête que le Pi pose sur la vraie page (pas sur la page « aucun compte »).
const MARQUE_PAGE = "x-vidange-coquille";

async function garderPage(reponse) {
  // Seulement la vraie page, en réponse normale.
  if (reponse.ok && reponse.headers.get(MARQUE_PAGE)) {
    const cache = await caches.open(CACHE);
    await cache.put("/", reponse.clone());
  }
}

self.addEventListener("install", (evenement) => {
  evenement.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    await Promise.all(COQUILLE.map((chemin) => cache.add(chemin).catch(() => {})));
    try { await garderPage(await fetch("/", { cache: "no-cache" })); } catch (e) { /* Pi injoignable */ }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (evenement) => {
  evenement.waitUntil((async () => {
    for (const nom of await caches.keys()) {
      if (nom.startsWith(PREFIXE_CACHE) && nom !== CACHE) await caches.delete(nom);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (evenement) => {
  const requete = evenement.request;
  const url = new URL(requete.url);
  if (requete.method !== "GET" || url.origin !== self.location.origin) return;
  // L'API et tout ce qui n'est pas la coquille : le navigateur s'en occupe, sans nous.
  if (url.pathname.startsWith("/api/")) return;
  const estPage = requete.mode === "navigate" && url.pathname === "/";
  const estCoquille = estPage || url.pathname.startsWith("/statique/")
    || url.pathname.startsWith("/icones/") || url.pathname === "/manifeste.webmanifest";
  if (!estCoquille) return;
  // Réseau d'abord : si le Pi répond, on prend sa réponse (toujours la plus récente). Le cache ne
  // sert que si le Pi est injoignable.
  evenement.respondWith((async () => {
    try {
      const reponse = await fetch(requete);
      if (estPage) await garderPage(reponse);
      else if (reponse.ok) {
        const cache = await caches.open(CACHE);
        await cache.put(requete, reponse.clone());
      }
      return reponse;
    } catch (erreur) {
      const gardee = await caches.match(estPage ? "/" : requete, { cacheName: CACHE });
      if (gardee) return gardee;
      throw erreur;
    }
  })());
});
