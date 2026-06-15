# Mon Assistant IA

Assistant IA multi-agents spécialisé Shopify : Dev, Recherche, Marketing, Communication, Projet, Shopify Manager, Design.

## Fonctionnalités

- **Chat multi-agents** — routage automatique vers le bon expert
- **Design Studio** — analyse d'image → 3 maquettes HTML/CSS + workflow v0.dev → Liquid Shopify
- **Dashboard projets** — `/dashboard` avec stats et gestion de la mémoire
- **Générateur de devis PDF** — devis professionnels avec ReportLab
- **Intégrations** — GitHub, Notion, Gmail, Shopify Admin API

## Variables d'environnement

| Variable | Description |
|---|---|
| `GROQ_API_KEY` | Clé API Groq (LLM) |
| `TAVILY_API_KEY` | Clé API Tavily (recherche web) |
| `GITHUB_TOKEN` | Token GitHub Personal Access |
| `GITHUB_USERNAME` | Username GitHub |
| `NOTION_TOKEN` | Token d'intégration Notion |
| `NOTION_PAGE_ID` | ID de la page Notion principale |
| `SHOPIFY_STORE_URL` | URL boutique (ex : ma-boutique.myshopify.com) |
| `SHOPIFY_ACCESS_TOKEN` | Token Admin API Shopify |
| `GMAIL_ADDRESS` | Adresse Gmail expéditeur |
| `GMAIL_APP_PASSWORD` | Mot de passe d'application Gmail |

## Lancer en local

```bash
pip install -r requirements.txt
cp .env.example .env  # remplis les variables
python app.py
```

Accès : http://localhost:5000

## Déployer sur Render.com

1. Pousse le projet sur GitHub :
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/TON_USER/mon-assistant-ia.git
   git push -u origin main
   ```
2. Sur [render.com](https://render.com) → **New Web Service**
3. Connecte ton repo GitHub
4. Render détecte automatiquement `render.yaml`
5. Ajoute toutes les variables d'environnement dans l'onglet **Environment**
6. Clique **Deploy**

## Structure du projet

```
mon-assistant-ia/
├── app.py              # Backend Flask + tous les agents
├── index.html          # Interface chat
├── memoire.json        # Mémoire persistante (auto-généré)
├── devis/              # PDFs générés (auto-créé)
├── requirements.txt
├── Procfile
└── render.yaml
```
