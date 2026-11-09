// Vérifie la page de la vue 3D dans un vrai navigateur (Playwright, Chromium sans écran).
// Lancé par pi/tests/test_vue3d_navigateur.py ; à la main :
//   node verifier_vue3d.mjs ADRESSE NOM MOT_DE_PASSE BOITES ZONES ALARME [CAPTURE.png]
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [adresse, nom, motDePasse, boites, zones, alarme, capture] = process.argv.slice(2);
const erreurs = [];
const verifier = (condition, texte) => { if (!condition) erreurs.push(texte); };

const navigateur = await chromium.launch({
  args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
try {
  const contexte = await navigateur.newContext({ viewport: { width: 1000, height: 900 }, deviceScaleFactor: 1 });
  const page = await contexte.newPage();
  page.on("pageerror", (e) => erreurs.push("erreur de la page : " + e.message));
  // Seules comptent les erreurs de la vue 3D (l'icône de l'onglet, ou une autre carte de la page
  // que ce banc d'essai n'a pas, ne sont pas son affaire).
  page.on("console", (m) => {
    const url = m.location().url;
    if (m.type() === "error" && (url === "" || url.includes("/vue3d") || url.includes("/statique/")))
      erreurs.push("console : " + m.text() + " " + url);
  });
  page.on("requestfailed", (r) => erreurs.push("requête ratée : " + r.url()));
  page.on("request", (r) => verifier(new URL(r.url()).origin === new URL(adresse).origin, "requête vers un autre site : " + r.url()));

  const connexion = await contexte.request.post(adresse + "/api/connexion", { data: { nom, mot_de_passe: motDePasse } });
  verifier(connexion.ok(), "connexion refusée");
  await page.goto(adresse + "/");
  await page.click('nav button[data-vue="3d"]');
  await page.waitForFunction(() => window.__vue3d && window.__vue3d.pret && window.__vue3d.recues >= 3, null, { timeout: 20000 });

  const direct = await page.evaluate(() => ({ ...window.__vue3d, pont: window.__vue3d.position("pont") }));
  verifier(direct.boites === Number(boites), `boîtes dans la scène : ${direct.boites}, attendu ${boites}`);
  verifier(direct.zones === Number(zones), `zones dans la scène : ${direct.zones}, attendu ${zones}`);
  verifier(!direct.erreur, "erreur de la vue : " + direct.erreur);
  // Les positions arrivent plusieurs fois par seconde et la boîte du pont bouge.
  await page.waitForFunction((avant) => window.__vue3d.position("pont")[0] !== avant, direct.pont[0], { timeout: 10000 });
  if (capture) await page.locator("#vue3d-scene").screenshot({ path: capture });

  // Rejeu : choisir l'alarme, lancer la lecture, l'indice avance.
  await page.click(`#vue3d-alarmes button:has-text("N° ${alarme} ")`);
  await page.waitForFunction(() => window.__vue3d.mode === "rejeu", null, { timeout: 10000 });
  await page.selectOption("#vue3d-vitesse", { index: 3 });
  await page.click("#vue3d-lecture");
  await page.waitForFunction(() => window.__vue3d.indice > 2, null, { timeout: 15000 });
  const curseur = Number(await page.inputValue("#vue3d-curseur"));
  verifier(curseur > -1e9, "curseur du rejeu illisible");
  await page.click("#vue3d-lecture");
  verifier((await page.textContent("#vue3d-titre-rejeu")).includes("n° " + alarme), "titre du rejeu");
  // Retour en direct.
  await page.click("#vue3d-bouton-direct");
  await page.waitForFunction(() => window.__vue3d.mode === "direct", null, { timeout: 5000 });
} catch (erreur) {
  erreurs.push(String(erreur));
} finally {
  await navigateur.close();
}
if (erreurs.length) { console.error(erreurs.join("\n")); process.exit(1); }
console.log("vue 3D : ok");
