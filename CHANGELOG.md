# CHANGELOG — Mon Assistant IA

## v2.0 — 2026-06-15

### Fonctionnalité 1 — Sync Notion Intelligente
- Nouvelle fonction `notion_sync_projet(nom_projet, type_action, contenu)` :
  - Cherche si une page Notion existe déjà pour le projet parmi les enfants de la page principale
  - Crée la page structurée avec 6 sections si elle n'existe pas (Brief, Specs, Roadmap, Communications, Devis, Historique)
  - Ajoute le contenu horodaté dans la bonne section selon `type_action`
  - Met à jour automatiquement la page INDEX "🗂️ Index Projets" avec une ligne par projet
- Sync automatique déclenché après :
  - `/valider-conversation` → brief + roadmap + specs en parallèle (3 threads)
  - `/devis` → section Devis du projet client
  - Réponse de l'agent Communication avec envoi email → section Communications
  - Réponse importante dans `/chat` (>300 chars) si un projet est actif → section Historique

### Fonctionnalité 2 — Agent Autonome 24/7 (APScheduler)
- Scheduler APScheduler en arrière-plan, lancé au démarrage de l'app (1 seul worker)
- **Tâche 1 — Veille App Store** (lundi 8h) :
  - Recherche Tavily "trending shopify apps" + "shopify gaps opportunities"
  - Analyse LLM → 3 opportunités concrètes
  - Sauvegarde dans `memoire.json["veille_hebdo"]`
  - Email récap + sync Notion "Veille hebdomadaire"
- **Tâche 2 — Rapport boutiques clients** (lundi 9h) :
  - Stats Shopify : commandes semaine, CA semaine, produits en rupture
  - Email rapport + sync Notion
- **Tâche 3 — Alerte stock critique** (toutes les 6h) :
  - Détecte les variantes avec stock < 5
  - Email d'alerte par produit, anti-doublon 24h via `memoire.json["alertes_stock_envoyees"]`
- **Tâche 4 — Analyse avis négatifs App Store** (mercredi 8h) :
  - Tavily cherche les avis 1 étoile pour loyalty, upsell, inventory, SEO
  - LLM extrait frustrations → opportunités
  - Sauvegarde dans `memoire.json["opportunites_detectees"]`
  - Email récap + sync Notion
- Route `GET /agent/status` : état du scheduler, liste des tâches avec prochaine/dernière exécution
- Route `POST /agent/run/<task_name>` : déclenche manuellement une tâche
- Panneau UI "🤖 Agent Auto" dans le header :
  - Tableau des 4 tâches avec fréquence, dates d'exécution, statut, bouton ▶ Lancer
  - Badge vert/rouge indiquant si le scheduler tourne
  - Log des 5 dernières actions automatiques

---

## v1.0 — 2026-06-03

### Lancement initial
- Interface chat IA multi-agents avec routing automatique
- **Agent Dev** : code Python/JS, intégration Shopify CLI, actions GitHub (créer repo, pousser fichier, créer issue)
- **Agent Recherche** : recherche web via Tavily, analyse de marché Shopify
- **Agent Marketing** : fiches App Store, pages de vente, copywriting Shopify
- **Agent Communication** : emails professionnels via Gmail, propositions commerciales
- **Agent Projet** : roadmaps, plannings, checklists, création fichiers locaux
- **Agent Shopify Manager** : accès direct boutique (produits, commandes, clients, stats, création produit)
- **Agent Design** : analyse d'image via vision LLM, génération de 3 maquettes HTML/CSS, workflow v0.dev
- **Mémoire persistante** : `memoire.json` (projets, décisions, historique), dashboard `/dashboard`
- **Génération de devis PDF** : ReportLab, numérotation auto, téléchargement direct
- **Analyse de conversation client** : extraction structurée (besoin, fonctionnalités, contraintes, ton)
- **Validation multi-agents** : 4 agents en parallèle sur `/valider-conversation` (roadmap + specs + marketing + email)
- **Intégration Notion** : création de pages, ajout de contenu dans la page principale
- **Workflow Design v0** : extraction de design tokens CSS depuis URL, génération prompt v0.dev, conversion en Liquid Shopify
- **Base de connaissances Shopify 2025-2026** injectée dans tous les agents
- Déploiement Render avec Gunicorn
