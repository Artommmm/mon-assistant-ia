# Déploiement sur Render.com — Guide complet

## Étape 1 — Créer un compte Render

1. Va sur [render.com](https://render.com)
2. Clique **Get Started for Free**
3. Inscris-toi avec ton compte GitHub (recommandé)

---

## Étape 2 — Préparer le repo GitHub

Si ce n'est pas déjà fait :

```bash
cd /Users/jeuxa/mon-assistant-ia
git init
git add .
git commit -m "Initial commit — Mon Assistant IA"
git branch -M main
git remote add origin https://github.com/TON_USERNAME/mon-assistant-ia.git
git push -u origin main
```

> **Important :** ne committe jamais le fichier `.env` — il doit rester en local.

---

## Étape 3 — Créer le service sur Render

1. Dans le dashboard Render → **New +** → **Web Service**
2. Connecte ton repo GitHub → sélectionne `mon-assistant-ia`
3. Render détecte automatiquement `render.yaml` et pré-remplit les champs :
   - **Name :** `mon-assistant-ia`
   - **Runtime :** Python
   - **Build Command :** `pip install -r requirements.txt`
   - **Start Command :** `gunicorn app:app --workers 2 --timeout 120`
4. Sélectionne le plan **Free** (0$/mois)

---

## Étape 4 — Configurer les variables d'environnement

Dans l'onglet **Environment** du service, ajoute ces variables une par une :

| Variable | Où la trouver |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) → API Keys |
| `TAVILY_API_KEY` | [tavily.com](https://tavily.com) → Dashboard |
| `GITHUB_TOKEN` | GitHub → Settings → Developer settings → Personal access tokens |
| `GITHUB_USERNAME` | Ton username GitHub |
| `NOTION_TOKEN` | Notion → Settings → Connections → Develop integrations |
| `NOTION_PAGE_ID` | ID de la page (dans l'URL Notion après `notion.so/`) |
| `SHOPIFY_STORE_URL` | Ex : `ma-boutique.myshopify.com` |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin → Apps → Develop apps → API credentials |
| `GMAIL_ADDRESS` | Ton adresse Gmail |
| `GMAIL_APP_PASSWORD` | Gmail → Compte Google → Sécurité → Mots de passe d'application |

> **Note :** `anthropic` et `google-genai` ne sont PAS utilisés dans ce projet.

---

## Étape 5 — Déployer

1. Clique **Create Web Service**
2. Render build et démarre l'app (2-3 minutes)
3. Ton URL finale : `https://mon-assistant-ia.onrender.com`

---

## Notes importantes

### Plan gratuit Render
- L'app **se met en veille** après 15 min d'inactivité
- Premier chargement après veille : 30-60 secondes (cold start)
- Pour éviter ça : upgrade vers le plan Starter (7$/mois)

### Persistance des données
Le plan gratuit n'a pas de disque persistant. Les fichiers `memoire.json` et `devis/` sont **perdus à chaque redéploiement**. Solutions :
- **Court terme :** exporte régulièrement via `/memoire`
- **Long terme :** migrer vers PostgreSQL + S3 pour les PDFs

### Fichiers générés localement
- `memoire.json` — mémoire de l'assistant
- `devis_counter.json` — compteur des devis
- `devis/` — PDFs générés par l'agent Communication

---

## Lancer en local (rappel)

```bash
pip install -r requirements.txt
cp .env.example .env  # remplis les variables
python app.py
# → http://localhost:5000
```
