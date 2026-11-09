// Onglets « Statistiques », « Réglages » et « Carnet » de la page web (tâche 28 bis).
//
// Aucun chiffre de la machine ici : tout vient de l'API du Pi (statistiques d'après le registre,
// réglages modifiables avec leurs bornes, notes du carnet). Les graphiques sont dessinés à la main
// en SVG (aucune bibliothèque : le Pi tourne sans Internet). Le texte venu du Pi passe toujours par
// textContent (jamais de HTML).
//
// La page donne les outils : { el, lire, api, dire, heure, Refus, droits }.

const SVG = "http://www.w3.org/2000/svg";

function svg(nom, attributs, ...enfants) {
  const e = document.createElementNS(SVG, nom);
  for (const [cle, valeur] of Object.entries(attributs || {})) {
    if (valeur !== null && valeur !== undefined) e.setAttribute(cle, valeur);
  }
  for (const enfant of enfants) if (enfant) e.append(enfant instanceof Node ? enfant : String(enfant));
  return e;
}

// ------------------------------------------------------------ statistiques

const COULEURS = ["var(--bleu)", "var(--orange)", "var(--rouge)", "var(--vert)", "var(--doux)"];

export function duree(secondes) {
  if (secondes === null || secondes === undefined) return "—";
  const s = Math.round(secondes);
  if (s < 90) return s + " s";
  const minutes = Math.round(s / 60);
  if (minutes < 90) return minutes + " min";
  const h = Math.floor(s / 3600);
  const m = Math.round((s - h * 3600) / 60);
  return h + " h " + String(m).padStart(2, "0");
}

export function etiquette(periode, echelle) {
  const d = new Date(periode.debut + "T12:00:00");
  if (echelle === "mois") return d.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
  const court = d.toLocaleDateString("fr-FR", { day: "numeric", month: "numeric" });
  return echelle === "jour" ? d.toLocaleDateString("fr-FR", { weekday: "short" }).slice(0, 3) + " " + court : court;
}

// Un « beau » maximum pour l'axe (1, 2, 5 × 10^n).
function maximumAxe(valeur) {
  if (!(valeur > 0)) return 1;
  const puissance = Math.pow(10, Math.floor(Math.log10(valeur)));
  for (const pas of [1, 2, 5, 10]) if (valeur <= pas * puissance) return pas * puissance;
  return 10 * puissance;
}

// Un graphique en barres, empilées si plusieurs séries. `series` : [{ libelle, couleur, valeur(p) }].
// `format` : comment écrire une valeur. Rend un élément SVG + sa légende, et un tableau des chiffres.
export function graphique({ el, titre, aide, periodes, echelle, series, format, unite }) {
  const L = 600, H = 210, gauche = 46, bas = 30, haut = 10, droite = 8;
  const totaux = periodes.map((p) => series.reduce((s, serie) => s + (serie.valeur(p) || 0), 0));
  const maximum = maximumAxe(Math.max(0, ...totaux));
  const largeur = (L - gauche - droite) / Math.max(periodes.length, 1);
  const echelleY = (v) => haut + (H - haut - bas) * (1 - v / maximum);
  const dessin = svg("svg", { viewBox: `0 0 ${L} ${H}`, role: "img", class: "graphique",
    "aria-label": titre, width: "100%" }, svg("title", {}, titre));
  for (const fraction of [0, 0.5, 1]) {
    const v = maximum * fraction;
    dessin.append(
      svg("line", { x1: gauche, x2: L - droite, y1: echelleY(v), y2: echelleY(v), class: "grille" }),
      svg("text", { x: gauche - 6, y: echelleY(v) + 4, "text-anchor": "end", class: "axe-texte" }, format(v)));
  }
  const pas = Math.ceil(periodes.length / 8);
  periodes.forEach((p, i) => {
    const x = gauche + i * largeur;
    let cumul = 0;
    series.forEach((serie) => {
      const valeur = serie.valeur(p) || 0;
      if (valeur <= 0) return;
      const barre = svg("rect", { x: x + largeur * 0.12, width: largeur * 0.76, y: echelleY(cumul + valeur),
        height: Math.max(echelleY(cumul) - echelleY(cumul + valeur), 1), fill: serie.couleur, class: "barre" },
        svg("title", {}, `${etiquette(p, echelle)} — ${serie.libelle} : ${format(valeur)}${unite ? " " + unite : ""}`));
      dessin.append(barre);
      cumul += valeur;
    });
    if (i % pas === 0 || i === periodes.length - 1) {
      dessin.append(svg("text", { x: x + largeur / 2, y: H - 10, "text-anchor": "middle", class: "axe-texte" },
        etiquette(p, echelle)));
    }
  });
  const legende = el("div", { classe: "doux" }, ...series.map((serie) => el("span", { classe: "legende" },
    (() => { const c = el("span", { classe: "pastille" }); c.style.background = serie.couleur; return c; })(),
    serie.libelle + " ")));
  const tableau = el("details", {}, el("summary", { classe: "doux" }, "Voir les chiffres"),
    el("table", {},
      el("tr", {}, el("th", {}, "Période"), ...series.map((s) => el("th", {}, s.libelle))),
      ...periodes.map((p) => el("tr", {}, el("td", {}, etiquette(p, echelle)),
        ...series.map((s) => el("td", {}, s.valeur(p) === null || s.valeur(p) === undefined ? "—" : format(s.valeur(p))))))));
  return el("div", { classe: "carte" }, el("strong", {}, titre), aide && el("div", { classe: "doux" }, aide),
    dessin, legende, tableau);
}

const entier = (v) => String(Math.round(v * 10) / 10);
const heures = (v) => (v / 3600).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " h";
const minutes = (v) => (v / 60).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " min";

let echelleStats = "jour";

export async function ouvrirStatistiques(conteneur, outils) {
  const { el, lire } = outils;
  const donnees = await lire("/api/statistiques?par=" + echelleStats);
  const p = donnees.periodes;
  const choix = el("div", { classe: "choix" }, ...[["jour", "Par jour"], ["semaine", "Par semaine"], ["mois", "Par mois"]]
    .map(([cle, texte]) => el("button", { classe: "petit" + (cle === echelleStats ? " actif" : ""), "data-echelle": cle,
      surclick: () => { echelleStats = cle; ouvrirStatistiques(conteneur, outils).catch(() => {}); } }, texte)));
  const modules = donnees.modules;
  const somme = (cle) => p.reduce((s, x) => s + x[cle], 0);
  const seauxTotal = somme("seaux");
  conteneur.replaceChildren(
    choix,
    el("p", { classe: "doux" }, "Calculé d'après le registre seulement, rien d'estimé. Les périodes commencent à minuit "
      + "(la semaine le lundi) ; la dernière est la période en cours. Total affiché : " + seauxTotal + " seaux, "
      + somme("cycles") + " cycles, " + somme("alarmes_total") + " alarmes."),
    graphique({ el, titre: "Seaux faits", periodes: p, echelle: donnees.echelle, format: entier,
      series: [{ libelle: "seaux", couleur: "var(--vert)", valeur: (x) => x.seaux }] }),
    graphique({ el, titre: "Durée moyenne par seau", periodes: p, echelle: donnees.echelle, format: minutes,
      aide: "Durée des cycles terminés qui ont rempli des seaux, divisée par leur nombre de seaux "
        + "(pauses comprises : le registre ne les note pas).",
      series: [{ libelle: "durée par seau", couleur: "var(--bleu)", valeur: (x) => x.duree_moyenne_seau_s }] }),
    graphique({ el, titre: "Cycles", periodes: p, echelle: donnees.echelle, format: entier,
      aide: "Cycles commencés pendant la période, selon leur issue.",
      series: [
        { libelle: "terminés", couleur: "var(--vert)", valeur: (x) => x.cycles_termines },
        { libelle: "abandonnés", couleur: "var(--rouge)", valeur: (x) => x.cycles_abandonnes },
        { libelle: "en cours ou ouverts", couleur: "var(--doux)", valeur: (x) => x.cycles_ouverts }] }),
    graphique({ el, titre: "Alarmes par module", periodes: p, echelle: donnees.echelle, format: entier,
      aide: modules.length ? null : "Aucune alarme sur ces périodes.",
      series: modules.map((m, i) => ({ libelle: m, couleur: COULEURS[i % COULEURS.length], valeur: (x) => x.alarmes[m] || 0 })) }),
    graphique({ el, titre: "Temps de marche et d'arrêt", periodes: p, echelle: donnees.echelle, format: heures,
      aide: "Marche : au moins un cycle tourne. Arrêt : le reste de la période écoulée.",
      series: [
        { libelle: "marche", couleur: "var(--vert)", valeur: (x) => x.marche_s },
        { libelle: "arrêt", couleur: "var(--doux)", valeur: (x) => x.arret_s }] }),
  );
}

// ------------------------------------------------------------ réglages

export async function ouvrirReglages(conteneur, outils) {
  const { el, lire, api, dire, heure, Refus } = outils;
  if (!outils.droits().includes("régler")) {
    conteneur.replaceChildren(el("p", { classe: "doux" }, "Réservé au rôle « régler » (karulium)."));
    return;
  }
  const [etat, historique] = await Promise.all([lire("/api/reglages-modifiables"), lire("/api/reglages-modifiables/historique")]);
  const recharger = () => ouvrirReglages(conteneur, outils).catch(() => {});

  async function envoyer(chemin, corps, texteOk) {
    try {
      const options = { method: "POST" };
      if (corps !== undefined) { options.headers = { "Content-Type": "application/json" }; options.body = JSON.stringify(corps); }
      const reponse = await (await api(chemin, options)).json();
      dire(texteOk + (reponse.redemarrage ? " Agit au prochain redémarrage du programme." : ""), "vert");
    } catch (erreur) {
      if (!(erreur instanceof Refus)) dire("Refusé : " + erreur.message, "rouge");
    }
    recharger();
  }

  const cartes = etat.reglages.map((r) => {
    const champ = r.genre === "heure"
      ? el("input", { type: "time", value: r.valeur, min: r.min, max: r.max, required: "" })
      : el("input", { type: "number", value: r.valeur, min: r.min, max: r.max, step: r.genre === "entier" ? "1" : "any", required: "" });
    champ.disabled = !!etat.occupe;
    const lire_champ = () => r.genre === "heure" ? champ.value : Number(champ.value);
    return el("div", { classe: "carte" + (r.redemarrage_necessaire ? " attention" : ""), "data-reglage": r.nom },
      el("strong", {}, r.libelle),
      el("div", { classe: "doux" }, r.aide),
      el("div", { classe: "champs" }, el("label", {}, "Valeur (" + r.unite + ")", champ)),
      el("div", { classe: "doux" }, "Permis : de " + r.min + " à " + r.max + " (" + r.unite + "). Fichier : "
        + r.fichier + " → " + r.chemin + "."),
      r.redemarrage_necessaire && el("div", { classe: "quoi" }, "Changé, pas encore en vigueur : le programme utilise encore "
        + r.en_vigueur + " jusqu'à son prochain redémarrage."),
      r.dernier_changement && el("div", { classe: "doux" }, "Dernier changement : " + heure(r.dernier_changement.quand)
        + " par " + r.dernier_changement.qui + " (" + r.dernier_changement.ancien + " → " + r.dernier_changement.nouveau + ")."),
      el("button", { classe: "petit", disabled: etat.occupe ? "" : null, surclick: () => {
        const valeur = lire_champ();
        if (confirm("Changer « " + r.libelle + " » de " + r.valeur + " à " + valeur + " " + r.unite + " ?"))
          envoyer("/api/reglages-modifiables/" + r.nom, { valeur }, "Réglage changé.");
      } }, "Enregistrer"),
      " ",
      r.peut_revenir && el("button", { classe: "petit", disabled: etat.occupe ? "" : null, surclick: () => {
        const d = r.dernier_changement;
        if (confirm("Revenir à " + d.ancien + " " + r.unite + " pour « " + r.libelle + " » ?"))
          envoyer("/api/reglages-modifiables/retour/" + d.numero, undefined, "Valeur d'avant remise.");
      } }, "Revenir à " + (r.dernier_changement ? r.dernier_changement.ancien : "")));
  });

  conteneur.replaceChildren(
    el("p", { classe: "doux" }, "Seuls ces réglages se changent d'ici, dans leurs bornes. Jamais les positions, courses, zones, "
      + "vitesses ni rien qui touche au mouvement de la machine. Chaque changement est vérifié (avec toutes les vérifications "
      + "du démarrage) avant d'être écrit, noté, et on peut revenir."),
    etat.exemple && el("p", { classe: "doux" }, "Les bornes sont des exemples, à ajuster à l'usage."),
    etat.occupe && el("div", { classe: "carte alarme" }, "Changements impossibles maintenant : " + etat.occupe + "."),
    etat.redemarrage_necessaire && el("div", { classe: "carte attention" },
      "Un redémarrage du programme est nécessaire pour que les changements agissent (jamais pendant un cycle : "
      + "voir la procédure, « sudo systemctl restart vidange »)."),
    ...cartes,
    ...(await blocVitesseEtEssai(outils, recharger)),
    el("h2", {}, "Historique des changements"),
    historique.length === 0 ? el("p", { classe: "doux" }, "Aucun changement fait depuis la page.")
      : el("table", {}, el("tr", {}, el("th", {}, "N°"), el("th", {}, "Quand"), el("th", {}, "Qui"),
          el("th", {}, "Réglage"), el("th", {}, "Avant"), el("th", {}, "Après")),
        ...historique.map((h) => el("tr", {}, el("td", {}, h.numero), el("td", {}, heure(h.quand)), el("td", {}, h.qui),
          el("td", {}, h.libelle + (h.raison.includes("retour") ? " (retour)" : "")), el("td", {}, String(h.ancien)),
          el("td", {}, String(h.nouveau))))));
}

// Montée en vitesse et essai d'un réglage dans le simulateur (tâche 30).
async function blocVitesseEtEssai(outils, recharger) {
  const { el, lire, api, dire, heure, Refus } = outils;
  const blocs = [];
  let vitesse = null;
  try { vitesse = await lire("/api/vitesse"); } catch (erreur) { /* pas de montée sur ce programme */ }
  if (vitesse && vitesse.present) {
    blocs.push(el("h2", {}, "Montée en vitesse"),
      el("div", { classe: "carte" + (vitesse.redemarrage_necessaire ? " attention" : "") },
        el("div", {}, vitesse.actif
          ? "Palier " + vitesse.palier + " sur " + vitesse.palier_max + " (vitesses à "
            + Math.round(vitesse.facteur * 100) + " % du départ) ; " + vitesse.cycles + " cycle(s) sur "
            + vitesse.cycles_par_palier + " sans alerte avant le palier suivant."
          : "Pas active (programme.yaml → montee_vitesse → actif)."),
        el("div", { classe: "doux" }, "Jamais au-dessus des plafonds fixés dans programme.yaml : "
          + Object.entries(vitesse.plafonds).map(([chemin, plafond]) => chemin + " ≤ " + plafond).join(" ; ")
          + ". Une alerte ou une alarme fait reculer. Aucun seuil, aucune zone, aucune règle de positions n'est touchée."),
        vitesse.redemarrage_necessaire && el("div", { classe: "quoi" }, "Palier voulu " + vitesse.palier
          + ", en vigueur " + vitesse.palier_en_vigueur + " : il agira au prochain démarrage du programme."),
        ...vitesse.changements.slice(0, 5).map((c) => el("div", { classe: "doux" }, heure(c.quand) + " : palier "
          + c.avant + " → " + c.apres + " (" + c.raison + ", " + c.qui + ")")),
        vitesse.peut_annuler && el("button", { classe: "petit", surclick: async () => {
          if (!confirm("Annuler le dernier changement de palier ?")) return;
          try { await api("/api/vitesse/annuler", { method: "POST" }); dire("Dernier changement annulé.", "vert"); }
          catch (erreur) { if (!(erreur instanceof Refus)) dire("Refusé : " + erreur.message, "rouge"); }
          recharger();
        } }, "Annuler le dernier changement")));
  }
  let essai = null;
  try { essai = await lire("/api/essai"); } catch (erreur) { /* pas d'essai sur ce programme */ }
  if (essai) {
    const zone = el("textarea", { rows: "3", placeholder: "machine.yaml=griffe.vitesses.pont_x=0.2" });
    const sortie = el("pre", { style: "white-space: pre-wrap; overflow-x: auto; font-size: 0.85em" }, essai.erreur ? "Impossible : " + essai.erreur
      : essai.en_cours ? "Essai en cours (une minute environ)..." : essai.resultat ? essai.resultat.texte : "");
    blocs.push(el("h2", {}, "Essai d'un réglage dans le simulateur"),
      el("div", { classe: "carte" },
        el("div", { classe: "doux" }, "Un réglage par ligne : fichier=chemin=valeur. Le lot simulé est rejoué avec le réglage changé "
          + "(sur une copie : aucun vrai fichier n'est touché) et comparé au lot normal : durée, alertes, refus. "
          + "Refusé pendant un lot."),
        zone,
        el("button", { classe: "petit", surclick: async () => {
          const changements = zone.value.split("\n").map((l) => l.trim()).filter(Boolean);
          try {
            await api("/api/essai", { method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ changements }) });
            dire("Essai lancé.", "vert");
          } catch (erreur) { if (!(erreur instanceof Refus)) dire("Refusé : " + erreur.message, "rouge"); }
          recharger();
        } }, "Lancer l'essai"),
        el("button", { classe: "petit", surclick: recharger }, "Voir où il en est"),
        sortie));
  }
  return blocs;
}

// ------------------------------------------------------------ carnet de bord

const etatCarnet = { recherche: "", barrees: true };

export async function ouvrirCarnet(conteneur, outils, avant = null, notes = []) {
  const { el, api, dire, heure, Refus } = outils;
  const peutEcrire = outils.droits().includes("produire");
  const parametres = new URLSearchParams();
  if (etatCarnet.recherche) parametres.set("recherche", etatCarnet.recherche);
  if (!etatCarnet.barrees) parametres.set("barrees", "false");
  if (avant) parametres.set("avant", avant);
  const reponse = await api("/api/carnet?" + parametres);
  const parPage = Number(reponse.headers.get("X-Notes-Par-Page")) || 0;
  const page = await reponse.json();
  const toutes = [...notes, ...page];
  const recharger = () => ouvrirCarnet(conteneur, outils).catch(() => {});

  const texte = el("textarea", { rows: "3", placeholder: "Une note libre : ce qui a été vu, fait, décidé…", required: "" });
  const lot = el("input", { type: "number", min: "1", placeholder: "n° de cycle (lot)" });
  const seau = el("input", { type: "text", placeholder: "code du seau (S1293)" });
  const alarme = el("input", { type: "number", min: "1", placeholder: "n° d'alarme" });
  const formulaire = el("form", { classe: "carte", sursubmit: async (ev) => {
    ev.preventDefault();
    const corps = { texte: texte.value };
    if (lot.value) corps.cycle = Number(lot.value);
    if (seau.value.trim()) corps.seau = seau.value.trim();
    if (alarme.value) corps.alarme = Number(alarme.value);
    try {
      await api("/api/carnet", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
      dire("Note écrite.", "vert");
      recharger();
    } catch (erreur) { if (!(erreur instanceof Refus)) dire("Refusé : " + erreur.message, "rouge"); }
  } },
    el("strong", {}, "Nouvelle note"),
    el("div", { classe: "champs" }, el("label", {}, "Texte", texte)),
    el("div", { classe: "champs" }, el("label", {}, "Lot", lot), el("label", {}, "Seau", seau), el("label", {}, "Alarme", alarme)),
    el("div", { classe: "doux" }, "Écrite au nom de votre compte, avec la date. Une note ne se supprime pas : on la barre."),
    el("button", { classe: "petit", type: "submit" }, "Écrire la note"));

  const recherche = el("input", { type: "search", value: etatCarnet.recherche, placeholder: "Chercher (texte ou auteur)" });
  const barrees = el("input", { type: "checkbox" });
  barrees.checked = etatCarnet.barrees;
  const filtre = el("form", { classe: "champs", sursubmit: (ev) => {
    ev.preventDefault();
    etatCarnet.recherche = recherche.value.trim();
    etatCarnet.barrees = barrees.checked;
    recharger();
  } }, el("label", {}, "Recherche", recherche),
    el("label", {}, "Notes barrées", el("span", {}, barrees, " les montrer")),
    el("button", { classe: "petit", type: "submit" }, "Chercher"));

  const carte = (n) => {
    const rattache = [n.cycle_id && "lot (cycle n° " + n.cycle_id + ")", n.seau && "seau " + n.seau,
      n.alarme_id && "alarme n° " + n.alarme_id].filter(Boolean).join(", ");
    const corps = el("div", { classe: n.barre_le ? "barree" : "" }, n.texte);
    return el("div", { classe: "carte note" + (n.barre_le ? " gris-barre" : ""), "data-note": n.id },
      el("div", { classe: "doux" }, "n° " + n.id + " · " + heure(n.quand) + " · " + n.auteur + (rattache ? " · " + rattache : "")),
      corps,
      n.barre_le && el("div", { classe: "doux" }, "Barrée par " + n.barre_par + " le " + heure(n.barre_le) + " : " + n.barre_raison),
      peutEcrire && !n.barre_le && el("button", { classe: "petit", surclick: async () => {
        const raison = prompt("Pourquoi barrer cette note ? (elle reste lisible)");
        if (!raison || !raison.trim()) return;
        try {
          await api("/api/carnet/" + n.id + "/barrer", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ raison }) });
          dire("Note barrée.", "vert");
          recharger();
        } catch (erreur) { if (!(erreur instanceof Refus)) dire("Refusé : " + erreur.message, "rouge"); }
      } }, "Barrer"));
  };

  const suite = parPage > 0 && page.length >= parPage ? el("button", { classe: "petit", surclick: () =>
    ouvrirCarnet(conteneur, outils, page[page.length - 1].id, toutes).catch(() => {}) }, "Plus ancien") : null;
  conteneur.replaceChildren(
    peutEcrire ? formulaire : el("p", { classe: "doux" }, "Pour écrire une note, il faut le rôle « produire » (employé)."),
    filtre,
    toutes.length === 0 ? el("p", { classe: "doux" }, "Aucune note.") : el("div", {}, ...toutes.map(carte)),
    suite);
}
