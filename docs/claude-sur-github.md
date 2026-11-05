# Claude sur GitHub (avec les crédits de l'API)

Une autre façon de faire une tâche de `docs/taches.md` : au lieu d'ouvrir une session sur claude.ai/code,
on écrit un message dans GitHub et Claude travaille directement sur GitHub. C'est payé avec les crédits de
l'API d'Anthropic (console.anthropic.com), pas avec l'abonnement.

## À faire une seule fois

1. Sur https://console.anthropic.com, menu **API Keys** → **Create Key**. Copier la clé (elle commence par
   `sk-ant-`). **Ne jamais la coller dans une conversation ni dans un fichier.**
2. Sur GitHub, dépôt `vidange-auto` → **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**. Nom : `ANTHROPIC_API_KEY`. Valeur : la clé. **Add secret**.

## Pour faire une tâche

1. Dépôt `vidange-auto` → **Issues** → **New issue**.
2. Titre : le numéro de la tâche (par exemple « Tâche 18 ter »).
3. Texte : la phrase donnée dans le fil, précédée de `@claude`, par exemple :
   « @claude Sonnet. Lis CLAUDE.md, puis fais la tâche 18 ter de docs/taches.md, et seulement celle-là.
   Ouvre une PR à la fin. »
   - Le mot **Sonnet** dans le message choisit Sonnet (moins cher). Sans lui, c'est Opus.
4. **Submit**. Claude répond dans l'issue et coche ses étapes au fur et à mesure (onglet **Actions** pour
   voir qu'il tourne). À la fin, il laisse une branche et un lien **Create PR** : cliquer dessus, puis
   **Create pull request**.
5. Écrire « fait » dans le fil logiciel, comme d'habitude : la relecture ne change pas.

Pour corriger une PR, écrire un commentaire dans la PR qui commence par `@claude`.

## Bon à savoir

- Seul le propriétaire du dépôt peut lancer Claude (`.github/workflows/claude.yml`).
- Une tâche s'arrête d'elle-même au bout de 2 h.
- Coût : payé au volume. Une tâche moyenne coûte de quelques dollars à une vingtaine (estimation) ; Sonnet
  coûte bien moins qu'Opus. Le détail est sur console.anthropic.com → **Usage**.
- Quand les crédits sont finis, Claude répond par une erreur : on revient aux sessions claude.ai/code.
