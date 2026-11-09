// Vérifie les onglets Statistiques, Carnet, Réglages et l'appli installable dans un vrai
// navigateur (Playwright, Chromium sans écran). Lancé par pi/tests/test_onglets_navigateur.py ;
// à la main :
//   node verifier_onglets.mjs ADRESSE NOM_KARULIUM NOM_EMPLOYE MOT_DE_PASSE [DOSSIER_CAPTURES]
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const [adresse, chef, aide, motDePasse, captures] = process.argv.slice(2);
const erreurs = [];
const verifier = (condition, texte) => { if (!condition) erreurs.push(texte); };

const navigateur = await chromium.launch({ args: ["--no-sandbox"] });
try {
  const contexte = await navigateur.newContext({ viewport: { width: 420, height: 900 }, deviceScaleFactor: 1 });
  const page = await contexte.newPage();
  page.on("pageerror", (e) => erreurs.push("erreur de la page : " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !m.location().url.includes("/api/")) erreurs.push("console : " + m.text() + " " + m.location().url);
  });
  page.on("request", (r) => verifier(new URL(r.url()).origin === new URL(adresse).origin, "requête vers un autre site : " + r.url()));
  const connecter = async (ctx, nom) => {
    const r = await ctx.request.post(adresse + "/api/connexion", { data: { nom, mot_de_passe: motDePasse } });
    verifier(r.ok(), "connexion refusée pour " + nom);
  };
  await connecter(contexte, chef);
  await page.goto(adresse + "/");
  await page.waitForSelector("#appli:not([hidden])");

  // ---- Statistiques : 5 graphiques, avec les chiffres du registre.
  await page.click('nav button[data-vue="stats"]');
  await page.waitForSelector("#stats svg.graphique");
  verifier((await page.locator("#stats svg.graphique").count()) === 5, "5 graphiques attendus");
  verifier((await page.locator("#stats svg.graphique rect.barre").count()) > 0, "aucune barre dessinée");
  const stats = await page.textContent("#stats");
  verifier(stats.includes("2 seaux"), "le total de seaux (2) manque : " + stats.slice(0, 300));
  verifier(stats.includes("prehension"), "le module de l'alarme manque");
  for (const echelle of ["semaine", "mois"]) {
    await page.click(`#stats button[data-echelle="${echelle}"]`);
    await page.waitForFunction((e) => document.querySelector(`#stats button.actif[data-echelle="${e}"]`), echelle);
    verifier((await page.locator("#stats svg.graphique").count()) === 5, "graphiques " + echelle);
  }
  if (captures) await page.screenshot({ path: captures + "/statistiques.png", fullPage: true });

  // ---- Carnet : écrire, chercher, barrer.
  await page.click('nav button[data-vue="carnet"]');
  await page.waitForSelector("#carnet form textarea");
  await page.fill("#carnet textarea", "Seau 4 un peu sec <b>ce matin</b>");
  await page.fill('#carnet input[placeholder="code du seau (S1293)"]', "S1");
  await page.click('#carnet button:has-text("Écrire la note")');
  await page.waitForSelector("#carnet .note");
  const note = await page.textContent("#carnet .note");
  verifier(note.includes("chef") && note.includes("seau S1"), "auteur ou seau manquant : " + note);
  verifier(note.includes("<b>ce matin</b>"), "le texte doit rester du texte (pas de HTML)");
  verifier((await page.locator("#carnet .note b").count()) === 0, "du HTML a été interprété");
  await page.fill('#carnet input[type="search"]', "introuvable");
  await page.click('#carnet button:has-text("Chercher")');
  await page.waitForSelector("#carnet:has-text('Aucune note')");
  await page.fill('#carnet input[type="search"]', "sec");
  await page.click('#carnet button:has-text("Chercher")');
  await page.waitForSelector("#carnet .note");
  page.once("dialog", (d) => d.accept("doublon"));
  await page.click('#carnet .note button:has-text("Barrer")');
  await page.waitForSelector("#carnet .note .barree");
  verifier((await page.textContent("#carnet .note")).includes("doublon"), "raison de la rature manquante");
  verifier((await page.locator('#carnet .note button:has-text("Barrer")').count()) === 0, "une note barrée ne se barre plus");
  if (captures) await page.screenshot({ path: captures + "/carnet.png", fullPage: true });

  // ---- Réglages : refus hors bornes, changement, redémarrage, retour.
  await page.click('nav button[data-vue="reglages"]');
  await page.waitForSelector('#reglages [data-reglage="calmes_fin"]');
  const carte = page.locator('#reglages [data-reglage="calmes_fin"]');
  await carte.locator("input").fill("23:00");
  page.once("dialog", (d) => d.accept());
  await carte.locator('button:has-text("Enregistrer")').click();
  await page.waitForFunction(() => document.querySelector("#message").textContent.includes("bornes"));
  await carte.locator("input").fill("07:00");
  page.once("dialog", (d) => d.accept());
  await carte.locator('button:has-text("Enregistrer")').click();
  await page.waitForSelector('#reglages [data-reglage="calmes_fin"].attention');
  const apres = await page.textContent('#reglages [data-reglage="calmes_fin"]');
  verifier(apres.includes("pas encore en vigueur") && apres.includes("06:00"), "redémarrage non annoncé : " + apres);
  verifier((await page.textContent("#reglages")).includes("redémarrage du programme est nécessaire"), "bandeau de redémarrage");
  if (captures) await page.screenshot({ path: captures + "/reglages.png", fullPage: true });
  page.once("dialog", (d) => d.accept());
  await page.locator('#reglages [data-reglage="calmes_fin"] button:has-text("Revenir")').click();
  await page.waitForFunction(() => !document.querySelector('#reglages [data-reglage="calmes_fin"].attention'));
  verifier((await page.locator('#reglages [data-reglage="calmes_fin"] input').inputValue()) === "06:00", "valeur d'avant pas remise");

  // ---- Un employé : pas d'onglet Réglages, mais le carnet pour écrire.
  const contexteAide = await navigateur.newContext({ viewport: { width: 420, height: 900 } });
  await connecter(contexteAide, aide);
  const pageAide = await contexteAide.newPage();
  await pageAide.goto(adresse + "/");
  await pageAide.waitForSelector("#appli:not([hidden])");
  verifier(await pageAide.locator("#onglet-reglages").isHidden(), "l'onglet Réglages doit être caché à l'employé");
  await pageAide.click('nav button[data-vue="carnet"]');
  await pageAide.waitForSelector("#carnet form textarea");
  await contexteAide.close();

  // ---- Appli installable : manifeste, service worker (127.0.0.1 est un contexte sûr).
  const lien = await page.getAttribute('link[rel="manifest"]', "href");
  verifier(lien === "/manifeste.webmanifest", "lien du manifeste");
  const inscrit = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    return { scope: reg.scope, actif: !!reg.active };
  });
  verifier(inscrit.actif && inscrit.scope === adresse + "/", "service worker pas actif : " + JSON.stringify(inscrit));
  // Un rechargement fait passer la page sous le contrôle du service worker.
  await page.reload();
  await page.waitForSelector("#appli:not([hidden])");
  await page.evaluate(() => navigator.serviceWorker.ready);
  const cache = await page.evaluate(async () => {
    const resultat = {};
    for (const nom of await caches.keys()) {
      resultat[nom] = (await (await caches.open(nom)).keys()).map((r) => new URL(r.url).pathname);
    }
    return resultat;
  });
  const noms = Object.keys(cache);
  verifier(noms.length === 1 && noms[0].startsWith("vidange-coquille-"), "un seul cache attendu : " + noms);
  const gardes = Object.values(cache).flat();
  verifier(gardes.includes("/"), "la page « / » n'est pas gardée : " + gardes);
  verifier(!gardes.some((c) => c.startsWith("/api/")), "une réponse de l'API est gardée : " + gardes);
  // Le Pi devient injoignable : la page s'ouvre (coquille), mais ne montre aucun état de la machine.
  await contexte.setOffline(true);
  await page.reload();
  await page.waitForSelector("#cle:not([hidden])");
  const horsLigne = await page.textContent("#cle");
  verifier(horsLigne.includes("Le Pi ne répond pas"), "message hors ligne manquant : " + horsLigne);
  verifier(await page.locator("#appli").isHidden(), "l'état de la machine ne doit jamais s'afficher hors ligne");
  await contexte.setOffline(false);
} catch (erreur) {
  erreurs.push(String(erreur));
} finally {
  await navigateur.close();
}
if (erreurs.length) { console.error(erreurs.join("\n")); process.exit(1); }
console.log("onglets : ok");
