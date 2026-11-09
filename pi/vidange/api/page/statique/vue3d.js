// Vue 3D de la machine (en direct) et rejeu d'incident : tâche 28.
//
// Aucun chiffre de la machine ici : la scène (boîtes, zones, couleurs, vitesses) vient de
// /api/vue3d/scene (vue3d.yaml et machine.yaml), les positions de /api/vue3d/positions (en direct)
// ou d'un fichier de rejeu (/api/vue3d/rejeux/N). La bibliothèque three.js est dans le dépôt
// (statique/three/) : pas d'Internet nécessaire.
//
// Repère : celui de la machine, z vers le haut (la caméra a z pour « haut », on ne convertit rien).
import * as THREE from "three";
import { OrbitControls } from "three/addons/OrbitControls.js";

const etat = {
  ouvert: false,
  mode: "direct", // « direct » ou « rejeu »
  scene: null,
  rendu: null, // { renderer, camera, controles, decor, boites: Map, zones: Map }
  positions: {}, // dernières positions connues, par axe
  minuterie: null,
  image: null,
  rejeu: null, // { numero, axes, temps, valeurs, lecture, t, vitesse }
  lire: null,
};

// Pour les essais automatiques : ce que la scène contient et reçoit.
window.__vue3d = { pret: false, boites: 0, zones: 0, recues: 0, mode: "direct", indice: 0, erreur: null };
const lien = window.__vue3d;
// Position (x, y, z) dessinée d'une boîte, pour vérifier qu'elle bouge.
lien.position = (nom) => {
  const b = etat.rendu && etat.rendu.boites.get(nom);
  return b ? b.maille.position.toArray() : null;
};

function el(balise, attributs, ...enfants) {
  const e = document.createElement(balise);
  for (const [nom, valeur] of Object.entries(attributs || {})) {
    if (valeur === null || valeur === undefined) continue;
    if (nom === "classe") e.className = valeur;
    else if (nom.startsWith("sur")) e.addEventListener(nom.slice(3), valeur);
    else e.setAttribute(nom, valeur);
  }
  for (const enfant of enfants) {
    if (enfant === null || enfant === undefined || enfant === false) continue;
    e.append(enfant instanceof Node ? enfant : String(enfant));
  }
  return e;
}

const virgule = (n, d = 1) => n.toFixed(d).replace(".", ",");

// ------------------------------------------------------------ la scène

function construire(scene, conteneur) {
  const c = scene.couleurs;
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(new THREE.Color(c.fond));
  conteneur.replaceChildren(renderer.domElement);
  renderer.domElement.style.cssText = "width:100%;height:100%;display:block;touch-action:none";

  const decor = new THREE.Scene();
  const [x0, x1] = scene.etendue.x, [y0, y1] = scene.etendue.y, [z0, z1] = scene.etendue.z;
  const centre = new THREE.Vector3((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2);

  decor.add(new THREE.AmbientLight(0xffffff, 0.7));
  const soleil = new THREE.DirectionalLight(0xffffff, 1.4);
  soleil.position.set(x1, y0 - 2, z1 + 3);
  decor.add(soleil);

  // Le sol : un rectangle de la taille du volume dessiné, et une grille.
  const sol = new THREE.Mesh(
    new THREE.PlaneGeometry(x1 - x0, y1 - y0),
    new THREE.MeshBasicMaterial({ color: new THREE.Color(c.sol), side: THREE.DoubleSide }));
  sol.position.set((x0 + x1) / 2, (y0 + y1) / 2, z0);
  decor.add(sol);
  const cadre = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(x1 - x0, y1 - y0, z1 - z0)),
    new THREE.LineBasicMaterial({ color: 0x55605a, transparent: true, opacity: 0.35 }));
  cadre.position.copy(centre);
  decor.add(cadre);

  const camera = new THREE.PerspectiveCamera(40, 1, 0.05, 100);
  camera.up.set(0, 0, 1);
  const controles = new OrbitControls(camera, renderer.domElement);
  controles.target.copy(centre);
  controles.update();

  const boites = new Map();
  for (const b of scene.boites) {
    const maille = new THREE.Mesh(
      new THREE.BoxGeometry(...b.taille),
      new THREE.MeshStandardMaterial({ color: new THREE.Color(b.couleur), roughness: 0.6 }));
    maille.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(maille.geometry), new THREE.LineBasicMaterial({ color: 0x101412 })));
    maille.position.set(b.x.decalage, b.y.decalage, b.z.decalage);
    maille.name = b.nom;
    decor.add(maille);
    boites.set(b.nom, { def: b, maille });
  }

  const zones = new Map();
  for (const z of scene.zones) {
    const dim = [z.x[1] - z.x[0], z.y[1] - z.y[0], z.z[1] - z.z[0]];
    const matiere = new THREE.MeshBasicMaterial({
      color: new THREE.Color(c.zone_libre), transparent: true, opacity: 0.12, depthWrite: false });
    const maille = new THREE.Mesh(new THREE.BoxGeometry(...dim), matiere);
    const aretes = new THREE.LineBasicMaterial({ color: new THREE.Color(c.zone_libre) });
    maille.add(new THREE.LineSegments(new THREE.EdgesGeometry(maille.geometry), aretes));
    maille.position.set((z.x[0] + z.x[1]) / 2, (z.y[0] + z.y[1]) / 2, (z.z[0] + z.z[1]) / 2);
    maille.name = "zone " + z.nom;
    decor.add(maille);
    zones.set(z.nom, { matiere, aretes, maille });
  }
  return { renderer, camera, controles, decor, boites, zones, centre, diagonale: Math.hypot(x1 - x0, y1 - y0, z1 - z0) };
}

function dimensionner() {
  const r = etat.rendu;
  const conteneur = r.renderer.domElement.parentElement;
  const l = Math.max(conteneur.clientWidth, 1), h = Math.max(conteneur.clientHeight, 1);
  r.renderer.setSize(l, h, false);
  r.camera.aspect = l / h;
  r.camera.updateProjectionMatrix();
}

// Place la caméra de loin, de face et un peu au-dessus, pour voir tout le volume (plus loin si
// l'écran est étroit, comme un téléphone debout).
function cadrer() {
  const r = etat.rendu;
  const recul = r.diagonale * 0.95 * Math.max(1, 1.3 / r.camera.aspect);
  r.camera.position.set(r.centre.x + recul * 0.15, r.centre.y - recul * 0.85, r.centre.z + recul * 0.45);
  r.controles.target.copy(r.centre);
  r.controles.update();
}

function appliquer(positions, zonesTenues) {
  const r = etat.rendu;
  if (!r) return;
  for (const { def, maille } of r.boites.values()) {
    for (const [sens, champ] of [["x", def.x], ["y", def.y], ["z", def.z]]) {
      const valeur = champ.axe === null ? 0 : positions[champ.axe];
      if (valeur === null || valeur === undefined) continue; // position pas encore connue : on garde
      maille.position[sens] = valeur + champ.decalage;
    }
    if (def.tourne !== null) {
      const angle = positions[def.tourne];
      if (angle !== null && angle !== undefined) maille.rotation.z = THREE.MathUtils.degToRad(angle);
    }
  }
  const c = etat.scene.couleurs;
  for (const [nom, zone] of r.zones.entries()) {
    const tenue = zonesTenues && Object.prototype.hasOwnProperty.call(zonesTenues, nom);
    const couleur = new THREE.Color(tenue ? c.zone_tenue : c.zone_libre);
    zone.matiere.color.copy(couleur);
    zone.aretes.color.copy(couleur);
    zone.matiere.opacity = tenue ? 0.3 : 0.12;
  }
}

function boucle() {
  if (!etat.ouvert) return;
  etat.image = requestAnimationFrame(boucle);
  if (etat.mode === "rejeu" && etat.rejeu) avancerRejeu();
  etat.rendu.controles.update();
  etat.rendu.renderer.render(etat.rendu.decor, etat.rendu.camera);
}

// ------------------------------------------------------------ en direct

async function sonder() {
  clearTimeout(etat.minuterie);
  if (!etat.ouvert || etat.mode !== "direct") return;
  try {
    const p = await etat.lire("/api/vue3d/positions");
    etat.positions = p.axes;
    lien.recues += 1;
    appliquer(p.axes, p.zones_tenues);
    majInfo(p);
  } catch (erreur) {
    if (erreur && erreur.constructor.name !== "Refus") majInfo(null, erreur.message);
  }
  if (etat.ouvert && etat.mode === "direct") {
    etat.minuterie = setTimeout(sonder, etat.scene.rafraichir_s * 1000);
  }
}

function majInfo(p, erreur) {
  const info = document.getElementById("vue3d-info");
  if (!info) return;
  if (erreur) { info.textContent = "Positions illisibles : " + erreur; return; }
  const tenues = Object.entries(p.zones_tenues || {}).map(([z, m]) => z + " (" + m + ")");
  info.textContent = (p.en_alarme ? "UN MODULE EST EN ALARME. " : "")
    + (tenues.length ? "Zones tenues : " + tenues.join(", ") + "." : "Aucune zone tenue.");
}

// ------------------------------------------------------------ rejeu d'incident

async function rejouer(numero) {
  const d = await etat.lire("/api/vue3d/rejeux/" + numero);
  const temps = d.echantillons.map((l) => l[0]);
  const valeurs = d.echantillons.map((l) => {
    const v = {};
    d.axes.forEach((axe, i) => { v[axe] = l[i + 1]; });
    return v;
  });
  etat.mode = "rejeu";
  lien.mode = "rejeu";
  clearTimeout(etat.minuterie);
  etat.rejeu = {
    numero, donnees: d, temps, valeurs, lecture: false, t: temps[0], vitesse: 1, dernier: null, indice: 0,
  };
  const curseur = document.getElementById("vue3d-curseur");
  curseur.min = temps[0]; curseur.max = temps[temps.length - 1]; curseur.step = "any"; curseur.value = temps[0];
  document.getElementById("vue3d-rejeu").hidden = false;
  document.getElementById("vue3d-titre-rejeu").textContent =
    "Alarme n° " + numero + " (" + d.module + ") : " + d.message;
  poserRejeu(temps[0]);
}

function direct() {
  etat.mode = "direct";
  lien.mode = "direct";
  etat.rejeu = null;
  document.getElementById("vue3d-rejeu").hidden = true;
  sonder();
}

// Position à l'instant t du rejeu : moyenne entre les deux relevés voisins (un axe sans valeur
// garde la dernière connue).
function poserRejeu(t) {
  const r = etat.rejeu;
  const { temps, valeurs } = r;
  t = Math.min(Math.max(t, temps[0]), temps[temps.length - 1]);
  r.t = t;
  let i = 0;
  while (i < temps.length - 2 && temps[i + 1] <= t) i++;
  const a = valeurs[i], b = valeurs[Math.min(i + 1, valeurs.length - 1)];
  const ecart = temps[Math.min(i + 1, temps.length - 1)] - temps[i];
  const f = ecart > 0 ? Math.min(Math.max((t - temps[i]) / ecart, 0), 1) : 0;
  const p = {};
  for (const axe of Object.keys(a)) {
    const va = a[axe], vb = b[axe];
    p[axe] = va === null ? vb : (vb === null ? va : va + (vb - va) * f);
  }
  r.indice = i;
  lien.indice = i;
  appliquer(p, r.donnees.zones_tenues);
  document.getElementById("vue3d-curseur").value = t;
  const dt = t - 0;
  document.getElementById("vue3d-heure").textContent = Math.abs(dt) < 0.05
    ? "à l'alarme" : (dt < 0 ? virgule(-dt) + " s avant l'alarme" : virgule(dt) + " s après l'alarme");
}

function avancerRejeu() {
  const r = etat.rejeu;
  const maintenant = performance.now();
  if (r.lecture && r.dernier !== null) {
    r.t += ((maintenant - r.dernier) / 1000) * r.vitesse;
    if (r.t >= r.temps[r.temps.length - 1]) {
      r.t = r.temps[r.temps.length - 1];
      r.lecture = false;
      majBoutonLecture();
    }
    poserRejeu(r.t);
  }
  r.dernier = maintenant;
}

function majBoutonLecture() {
  const b = document.getElementById("vue3d-lecture");
  if (b && etat.rejeu) b.textContent = etat.rejeu.lecture ? "Pause" : "Lecture";
}

// ------------------------------------------------------------ la page

async function chargerAlarmes() {
  const liste = document.getElementById("vue3d-alarmes");
  try {
    const alarmes = await etat.lire("/api/vue3d/rejeux");
    liste.replaceChildren(...(alarmes.length
      ? alarmes.map((a) => el("button", { classe: "petit", surclick: () => rejouer(a.id).catch(montrerErreur) },
          "N° " + a.id + " · " + a.module + " · " + new Date(a.quand).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })))
      : [el("span", { classe: "doux" }, "Aucune alarme n'a encore de rejeu (il est écrit une minute après chaque alarme).")]));
  } catch (erreur) { montrerErreur(erreur); }
}

function montrerErreur(erreur) {
  if (erreur && erreur.constructor.name === "Refus") return;
  lien.erreur = String(erreur && erreur.message || erreur);
  const info = document.getElementById("vue3d-info");
  if (info) info.textContent = "Erreur : " + lien.erreur;
}

function legende(scene) {
  const vus = new Map();
  for (const b of scene.boites) if (!vus.has(b.couleur)) vus.set(b.couleur, []);
  for (const b of scene.boites) vus.get(b.couleur).push(b.libelle);
  const pastille = (couleur) => el("span", { style: "display:inline-block;width:.9em;height:.9em;border-radius:2px;margin-right:.35em;background:" + couleur });
  return [
    ...[...vus.entries()].map(([couleur, noms]) => el("span", { style: "margin-right:1em;white-space:nowrap" }, pastille(couleur), noms.join(", "))),
    el("span", { style: "margin-right:1em;white-space:nowrap" }, pastille(scene.couleurs.zone_libre), "zone libre"),
    el("span", { style: "white-space:nowrap" }, pastille(scene.couleurs.zone_tenue), "zone tenue"),
  ];
}

// Deux ouvertures en même temps (onglet et bouton « Rejouer ») : la seconde attend la première.
let ouverture = null;
export function ouvrir(racine, lire) {
  if (!ouverture) ouverture = ouvrirVraiment(racine, lire).finally(() => { ouverture = null; });
  return ouverture;
}

async function ouvrirVraiment(racine, lire) {
  etat.lire = lire;
  etat.ouvert = true;
  if (!etat.rendu) {
    racine.replaceChildren(
      el("div", { id: "vue3d-info", classe: "doux" }, "Chargement de la scène…"),
      el("div", { id: "vue3d-scene", style: "width:100%;height:min(65vh,640px);min-height:300px;border-radius:8px;overflow:hidden;background:#141816" }),
      el("div", { id: "vue3d-legende", classe: "doux", style: "margin:.5em 0" }),
      el("div", { classe: "choix" },
        el("button", { id: "vue3d-bouton-direct", classe: "petit", surclick: direct }, "En direct")),
      el("h2", {}, "Rejeu d'une alarme"),
      el("p", { classe: "doux" }, "Les positions des axes pendant la minute avant et la minute après l'alarme."),
      el("div", { id: "vue3d-alarmes", classe: "choix" }),
      el("div", { id: "vue3d-rejeu", classe: "carte", hidden: "hidden" },
        el("div", { id: "vue3d-titre-rejeu" }),
        el("input", { id: "vue3d-curseur", type: "range", style: "width:100%",
          surinput: (ev) => { if (etat.rejeu) { etat.rejeu.lecture = false; majBoutonLecture(); poserRejeu(parseFloat(ev.target.value)); } } }),
        el("div", { id: "vue3d-heure", classe: "doux" }),
        el("div", { classe: "choix" },
          el("button", { id: "vue3d-lecture", classe: "petit", surclick: () => {
            const r = etat.rejeu; if (!r) return;
            if (!r.lecture && r.t >= r.temps[r.temps.length - 1]) r.t = r.temps[0];
            r.lecture = !r.lecture; r.dernier = null; majBoutonLecture();
          } }, "Lecture"),
          el("select", { id: "vue3d-vitesse", "aria-label": "Vitesse de lecture", surchange: (ev) => { if (etat.rejeu) etat.rejeu.vitesse = parseFloat(ev.target.value); } }))));
    try {
      etat.scene = await lire("/api/vue3d/scene");
    } catch (erreur) { montrerErreur(erreur); etat.ouvert = false; return; }
    const select = document.getElementById("vue3d-vitesse");
    select.replaceChildren(...etat.scene.rejeu.vitesses.map((v) =>
      el("option", { value: v, selected: v === 1 ? "selected" : null }, "×" + String(v).replace(".", ","))));
    document.getElementById("vue3d-legende").replaceChildren(...legende(etat.scene));
    try {
      etat.rendu = construire(etat.scene, document.getElementById("vue3d-scene"));
    } catch (erreur) {
      lien.erreur = "WebGL : " + erreur.message;
      document.getElementById("vue3d-info").textContent = "Ce navigateur ne sait pas dessiner en 3D (WebGL absent).";
      etat.ouvert = false;
      return;
    }
    dimensionner();
    cadrer();
    new ResizeObserver(dimensionner).observe(document.getElementById("vue3d-scene"));
    lien.boites = etat.rendu.boites.size;
    lien.zones = etat.rendu.zones.size;
  }
  document.getElementById("vue3d-info").textContent = "";
  dimensionner();
  lien.pret = true;
  chargerAlarmes();
  if (etat.mode === "direct") sonder();
  cancelAnimationFrame(etat.image);
  boucle();
}

export function fermer() {
  etat.ouvert = false;
  clearTimeout(etat.minuterie);
  cancelAnimationFrame(etat.image);
  if (etat.rejeu) { etat.rejeu.lecture = false; majBoutonLecture(); }
}

export { rejouer };
