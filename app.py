from flask import Flask, request, jsonify, send_from_directory, send_file
from groq import Groq
from tavily import TavilyClient
from dotenv import load_dotenv
import json, os, datetime, subprocess, tempfile, base64, urllib.parse, re, io
from concurrent.futures import ThreadPoolExecutor
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from github import Github, GithubException
from notion_client import Client as NotionClient
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import shopify

load_dotenv()

# ── Base de connaissances Shopify partagée ────────────────
CONTEXTE_SHOPIFY = """
CONTEXTE TECHNIQUE SHOPIFY (2025-2026) :

STACK RECOMMANDE :
- Framework : Remix + Node.js (standard Shopify CLI)
- UI : Polaris (composants officiels Shopify)
- Auth : OAuth 2.0 via @shopify/shopify-api
- DB : Prisma + SQLite (dev) / PostgreSQL (prod)
- Hosting : Fly.io ou Render (gratuit pour démarrer)

API SHOPIFY :
- REST Admin API : /admin/api/2024-01/
- GraphQL Admin API : /admin/api/2024-01/graphql.json
- Scopes courants : read_products, write_products, read_orders, write_orders, read_customers

APP STORE :
- Revenu moyen app : 5$ à 50$/mois par marchand
- Catégories les plus rentables : Marketing, SEO, Inventory, Customer loyalty
- Délai de review Shopify : 2 à 6 semaines
- Modèle freemium recommandé pour démarrer

OUTILS CLI :
- npm init @shopify/app (créer une app)
- shopify app dev (lancer en local)
- shopify app deploy (déployer)

OPPORTUNITES 2026 :
- Apps IA pour personnalisation produits
- Automatisation du service client
- Gestion multi-boutiques
- Apps pour marchés de niche (B2B, abonnements)
"""

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
client = Groq()
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

from github import Auth
github_auth = Auth.Token(os.getenv("GITHUB_TOKEN"))
github_client = Github(auth=github_auth)
github_username = os.getenv("GITHUB_USERNAME")

notion = NotionClient(auth=os.getenv("NOTION_TOKEN"))
notion_page_id = os.getenv("NOTION_PAGE_ID")

# ── Mémoire ───────────────────────────────────────────────
MEMOIRE_FILE = "memoire.json"

def charger_memoire():
    if os.path.exists(MEMOIRE_FILE):
        with open(MEMOIRE_FILE, "r") as f:
            return json.load(f)
    return {"projets": [], "decisions": [], "historique": []}

def sauvegarder_memoire(memoire):
    with open(MEMOIRE_FILE, "w") as f:
        json.dump(memoire, f, ensure_ascii=False, indent=2)

# ── Devis ─────────────────────────────────────────────────
DEVIS_FILE = "devis_counter.json"
DEVIS_DIR  = "devis"
os.makedirs(DEVIS_DIR, exist_ok=True)

def get_next_devis_numero():
    if os.path.exists(DEVIS_FILE):
        with open(DEVIS_FILE) as f:
            data = json.load(f)
    else:
        data = {"numero": 0}
    data["numero"] += 1
    with open(DEVIS_FILE, "w") as f:
        json.dump(data, f)
    return data["numero"]

def generer_pdf_devis(client_nom, projet, prestations, prix_total, delai, numero):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)

    def S(name, **kw):
        return ParagraphStyle(name, **kw)

    s_big = S("big", fontName="Helvetica-Bold", fontSize=22, leading=28)
    s_sub = S("sub", fontName="Helvetica", fontSize=10,
               textColor=colors.HexColor("#888888"), leading=14)
    s_sec = S("sec", fontName="Helvetica-Bold", fontSize=12,
               leading=16, spaceBefore=14, spaceAfter=8)
    s_bd  = S("bd",  fontName="Helvetica-Bold", fontSize=10, leading=16)
    s_b   = S("b",   fontName="Helvetica",      fontSize=10, leading=16)
    s_bdr = S("bdr", fontName="Helvetica-Bold", fontSize=11, leading=16, alignment=TA_RIGHT)

    date_str = datetime.datetime.now().strftime("%d/%m/%Y")
    story = []

    story.append(Paragraph("Antoine Dev", s_big))
    story.append(Paragraph("Développement Shopify &amp; Applications Web", s_sub))
    story.append(Spacer(1, 0.4*cm))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#111111")))
    story.append(Spacer(1, 0.6*cm))

    info = [
        [Paragraph(f"<b>DEVIS N° {numero:04d}</b>", s_bd), Paragraph(f"<b>Client :</b> {client_nom}", s_bd)],
        [Paragraph(f"Date : {date_str}", s_b),              Paragraph(f"<b>Projet :</b> {projet}", s_bd)],
        [Paragraph(f"Délai estimé : {delai}", s_b),         Paragraph("", s_b)],
    ]
    t_info = Table(info, colWidths=[9*cm, 8*cm])
    t_info.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6)
    ]))
    story.append(t_info)
    story.append(Spacer(1, 0.8*cm))

    story.append(Paragraph("Détail des prestations", s_sec))
    rows = [["Description", "Montant HT"]]
    for p in prestations:
        if isinstance(p, dict):
            desc = p.get("description", "")
            prix = f"{p.get('prix', '')} €"
        else:
            parts = str(p).rsplit("-", 1)
            desc = parts[0].strip()
            prix = parts[1].strip() if len(parts) == 2 else ""
            if prix and "€" not in prix:
                prix += " €"
        rows.append([desc, prix])
    rows.append(["", ""])
    rows.append([Paragraph("<b>TOTAL HT</b>", s_bd), Paragraph(f"<b>{prix_total} €</b>", s_bdr)])

    t_p = Table(rows, colWidths=[13*cm, 4*cm])
    t_p.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),  (-1,0),  colors.HexColor("#111111")),
        ("TEXTCOLOR",     (0,0),  (-1,0),  colors.white),
        ("FONTNAME",      (0,0),  (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),  (-1,0),  10),
        ("TOPPADDING",    (0,0),  (-1,0),  8),
        ("BOTTOMPADDING", (0,0),  (-1,0),  8),
        ("LEFTPADDING",   (0,0),  (-1,-1), 8),
        ("RIGHTPADDING",  (0,0),  (-1,-1), 8),
        ("ALIGN",         (1,0),  (1,-1),  "RIGHT"),
        ("FONTNAME",      (0,1),  (-1,-3), "Helvetica"),
        ("FONTSIZE",      (0,1),  (-1,-3), 10),
        ("TOPPADDING",    (0,1),  (-1,-3), 7),
        ("BOTTOMPADDING", (0,1),  (-1,-3), 7),
        ("ROWBACKGROUNDS",(0,1),  (-1,-3), [colors.white, colors.HexColor("#f8f8f8")]),
        ("LINEBELOW",     (0,0),  (-1,-4), 0.5, colors.HexColor("#eeeeee")),
        ("LINEABOVE",     (0,-1), (-1,-1), 1.5, colors.HexColor("#111111")),
        ("BACKGROUND",    (0,-1), (-1,-1), colors.HexColor("#f0f0f0")),
        ("TOPPADDING",    (0,-1), (-1,-1), 8),
        ("BOTTOMPADDING", (0,-1), (-1,-1), 8),
    ]))
    story.append(t_p)
    story.append(Spacer(1, 0.8*cm))

    story.append(Paragraph("Conditions de paiement", s_sec))
    for c in [
        "• Acompte de 50 % à la commande",
        "• Solde de 50 % à la livraison",
        "• Règlement par virement bancaire",
        "• Devis valable 30 jours à compter de la date d'émission",
        "• TVA non applicable — Art. 293 B du CGI",
    ]:
        story.append(Paragraph(c, s_b))
    story.append(Spacer(1, 1.2*cm))

    sig = [
        [Paragraph("<b>Bon pour accord — Client</b>", s_bd), Paragraph("<b>Le prestataire</b>", s_bd)],
        [Paragraph(f"\n\n\n{client_nom}\nDate :", s_b),
         Paragraph(f"\n\n\nAntoine Dev\nDate : {date_str}", s_b)],
    ]
    t_sig = Table(sig, colWidths=[8.5*cm, 8.5*cm])
    t_sig.setStyle(TableStyle([
        ("BOX",           (0,0), (0,-1),  0.5, colors.HexColor("#cccccc")),
        ("BOX",           (1,0), (1,-1),  0.5, colors.HexColor("#cccccc")),
        ("BACKGROUND",    (0,0), (-1,0),  colors.HexColor("#f8f8f8")),
        ("LINEBELOW",     (0,0), (-1,0),  0.5, colors.HexColor("#eeeeee")),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
    ]))
    story.append(t_sig)

    doc.build(story)
    buf.seek(0)
    return buf

# ── Outils réels ──────────────────────────────────────────
def recherche_web(query):
    """Cherche sur Internet et retourne un résumé des résultats."""
    try:
        resultats = tavily.search(query=query, max_results=5, search_depth="basic")
        texte = f"Résultats de recherche pour : '{query}'\n\n"
        for i, r in enumerate(resultats.get("results", []), 1):
            texte += f"{i}. {r['title']}\n{r['content'][:300]}...\n\n"
        return texte
    except Exception as e:
        return f"Erreur de recherche : {e}"

def executer_code(code):
    """Exécute du code Python et retourne le résultat."""
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            tmp_path = f.name
        result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True, text=True, timeout=10
        )
        os.unlink(tmp_path)
        if result.returncode == 0:
            return f"✅ Résultat :\n{result.stdout}"
        else:
            return f"❌ Erreur :\n{result.stderr}"
    except subprocess.TimeoutExpired:
        return "❌ Timeout : le code a pris trop de temps."
    except Exception as e:
        return f"❌ Erreur : {e}"

def creer_fichier(nom_fichier, contenu):
    """Crée un fichier dans le dossier du projet."""
    try:
        chemin = os.path.join(os.path.expanduser("~/Desktop"), nom_fichier)
        with open(chemin, "w") as f:
            f.write(contenu)
        return f"✅ Fichier créé sur ton Bureau : {nom_fichier}"
    except Exception as e:
        return f"❌ Erreur : {e}"
    
def github_creer_repo(nom, description="", prive=False):
    """Crée un nouveau repo GitHub."""
    try:
        user = github_client.get_user()
        repo = user.create_repo(
            name=nom,
            description=description,
            private=prive,
            auto_init=True
        )
        return f"✅ Repo créé : {repo.html_url}"
    except GithubException as e:
        return f"❌ Erreur GitHub : {e.data.get('message', str(e))}"

def github_pousser_fichier(repo_nom, chemin_fichier, contenu, message_commit="Ajout via assistant IA"):
    """Pousse un fichier dans un repo GitHub existant."""
    try:
        user = github_client.get_user()
        repo = user.get_repo(repo_nom)
        try:
            # Fichier existant → on le met à jour
            fichier = repo.get_contents(chemin_fichier)
            repo.update_file(chemin_fichier, message_commit, contenu, fichier.sha)
            return f"✅ Fichier mis à jour dans {repo_nom}/{chemin_fichier}"
        except GithubException:
            # Fichier nouveau → on le crée
            repo.create_file(chemin_fichier, message_commit, contenu)
            return f"✅ Fichier créé dans {repo_nom}/{chemin_fichier}"
    except GithubException as e:
        return f"❌ Erreur GitHub : {e.data.get('message', str(e))}"

def github_lister_repos():
    """Liste les repos GitHub de l'utilisateur."""
    try:
        user = github_client.get_user()
        repos = list(user.get_repos())[:10]
        liste = "\n".join([f"• {r.name} — {r.html_url}" for r in repos])
        return f"✅ Tes repos GitHub :\n{liste}"
    except GithubException as e:
        return f"❌ Erreur GitHub : {e.data.get('message', str(e))}"

def github_creer_issue(repo_nom, titre, corps=""):
    """Crée une issue dans un repo GitHub."""
    try:
        user = github_client.get_user()
        repo = user.get_repo(repo_nom)
        issue = repo.create_issue(title=titre, body=corps)
        return f"✅ Issue créée : {issue.html_url}"
    except GithubException as e:
        return f"❌ Erreur GitHub : {e.data.get('message', str(e))}"


def notion_creer_page(titre, contenu):
    """Crée une nouvelle page Notion en découpant le contenu si nécessaire."""
    try:
        # Découpe le contenu en blocs de 1800 caractères max
        blocs_texte = [contenu[i:i+1800] for i in range(0, len(contenu), 1800)]
        
        children = []
        for bloc in blocs_texte:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": bloc}}]
                }
            })

        nouvelle_page = notion.pages.create(
            parent={"page_id": notion_page_id},
            properties={
                "title": {
                    "title": [{"type": "text", "text": {"content": titre}}]
                }
            },
            children=children
        )
        url = nouvelle_page.get("url", "")
        return f"✅ Page Notion créée : {url}"
    except Exception as e:
        return f"❌ Erreur Notion : {str(e)}"

def notion_ajouter_contenu(titre, contenu):
    """Ajoute du contenu dans la page principale Notion."""
    try:
        blocs_texte = [contenu[i:i+1800] for i in range(0, len(contenu), 1800)]
        
        children = [
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": titre}}]
                }
            }
        ]
        for bloc in blocs_texte:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": bloc}}]
                }
            })
        children.append({"object": "block", "type": "divider", "divider": {}})

        notion.blocks.children.append(notion_page_id, children=children)
        return f"✅ Contenu ajouté dans ta page Notion"
    except Exception as e:
        return f"❌ Erreur Notion : {str(e)}"

def notion_ajouter_contenu(titre, contenu):
    """Ajoute un bloc de contenu dans la page principale Notion."""
    try:
        notion.blocks.children.append(
            notion_page_id,
            children=[
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": titre}}]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": contenu[:2000]}}]
                    }
                },
                {
                    "object": "block",
                    "type": "divider",
                    "divider": {}
                }
            ]
        )
        return f"✅ Contenu ajouté dans ta page Notion"
    except Exception as e:
        return f"❌ Erreur Notion : {str(e)}"
    
def gmail_envoyer(destinataire, sujet, corps):
    """Envoie un vrai email via Gmail."""
    try:
        expediteur = os.getenv("GMAIL_ADDRESS")
        mot_de_passe = os.getenv("GMAIL_APP_PASSWORD")

        msg = MIMEMultipart()
        msg["From"] = expediteur
        msg["To"] = destinataire
        msg["Subject"] = sujet
        msg.attach(MIMEText(corps, "plain"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as serveur:
            serveur.login(expediteur, mot_de_passe)
            serveur.sendmail(expediteur, destinataire, msg.as_string())

        return f"✅ Email envoyé à {destinataire} — Sujet : {sujet}"
    except Exception as e:
        return f"❌ Erreur Gmail : {str(e)}"
    

def shopify_init():
    """Initialise la connexion Shopify."""
    shop_url = os.getenv("SHOPIFY_STORE_URL")
    token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    api_version = "2024-01"
    session = shopify.Session(shop_url, api_version, token)
    shopify.ShopifyResource.activate_session(session)

def shopify_lister_produits():
    """Liste les produits de la boutique."""
    try:
        shopify_init()
        produits = shopify.Product.find(limit=10)
        if not produits:
            return "Aucun produit trouvé dans la boutique."
        liste = ""
        for p in produits:
            liste += f"• {p.title} — {p.status} — {p.variants[0].price}$\n"
        return f"✅ Produits de ta boutique :\n{liste}"
    except Exception as e:
        return f"❌ Erreur Shopify : {str(e)}"

def shopify_lister_commandes():
    """Liste les dernières commandes."""
    try:
        shopify_init()
        commandes = shopify.Order.find(limit=10, status="any")
        if not commandes:
            return "Aucune commande trouvée."
        liste = ""
        for c in commandes:
            liste += f"• Commande #{c.order_number} — {c.financial_status} — {c.total_price}$\n"
        return f"✅ Dernières commandes :\n{liste}"
    except Exception as e:
        return f"❌ Erreur Shopify : {str(e)}"

def shopify_stats():
    """Retourne les statistiques générales de la boutique."""
    try:
        shopify_init()
        shop = shopify.Shop.current()
        produits = shopify.Product.find(limit=250)
        commandes = shopify.Order.find(limit=250, status="any")

        total_ventes = sum(float(c.total_price) for c in commandes)
        nb_commandes = len(commandes)
        nb_produits = len(produits)

        return (
            f"✅ Statistiques de {shop.name} :\n"
            f"• Produits : {nb_produits}\n"
            f"• Commandes totales : {nb_commandes}\n"
            f"• Chiffre d'affaires total : {total_ventes:.2f}$\n"
            f"• Devise : {shop.currency}\n"
            f"• Email : {shop.email}"
        )
    except Exception as e:
        return f"❌ Erreur Shopify : {str(e)}"

def shopify_creer_produit(titre, description, prix):
    """Crée un nouveau produit dans la boutique."""
    try:
        shopify_init()
        nouveau_produit = shopify.Product()
        nouveau_produit.title = titre
        nouveau_produit.body_html = description
        nouveau_produit.variants = [{"price": str(prix)}]
        nouveau_produit.save()
        return f"✅ Produit créé : {titre} à {prix}$"
    except Exception as e:
        return f"❌ Erreur Shopify : {str(e)}"

def shopify_lister_clients():
    """Liste les clients de la boutique."""
    try:
        shopify_init()
        clients = shopify.Customer.find(limit=10)
        if not clients:
            return "Aucun client trouvé."
        liste = ""
        for c in clients:
            liste += f"• {c.first_name} {c.last_name} — {c.email} — {c.orders_count} commande(s)\n"
        return f"✅ Clients de ta boutique :\n{liste}"
    except Exception as e:
        return f"❌ Erreur Shopify : {str(e)}"

# ── Agents ────────────────────────────────────────────────
AGENTS = {
    "dev": {
        "nom": "Dev",
        "prompt": """Tu es un expert en développement logiciel avec une spécialisation Shopify.

COMPETENCES GENERALES :
- Code Python, JavaScript, Node.js propre et fonctionnel
- Architecture logicielle, APIs REST et GraphQL
- Debugging et optimisation de code
- Quand tu génères du code à exécuter localement, mets-le entre <CODE> et </CODE>

COMPETENCES SHOPIFY :
- Apps Shopify modernes : Remix + Node.js + Polaris UI
- API Admin Shopify (REST + GraphQL) : produits, commandes, clients, inventaire
- Authentification OAuth pour apps Shopify
- Shopify CLI : création, déploiement, test d'apps
- App Extensions et Theme App Extensions
- Shopify Functions (personnalisation checkout)
- Webhooks Shopify pour automatisations
- Liquid pour les thèmes

REGLES ABSOLUES POUR LE CODE LIQUID ET LES THEMES SHOPIFY :

1. JAMAIS de valeurs en dur pour les couleurs, polices ou espacements.
   Tu utilises TOUJOURS les variables de thème Shopify :
   - Couleurs    : {{ settings.color_primary }}, {{ settings.color_secondary }},
                   {{ settings.color_background_1 }}, {{ settings.color_background_2 }},
                   {{ settings.color_text }}, {{ settings.color_accent }}
   - Polices     : {{ settings.type_header_font.family }}, {{ settings.type_body_font.family }},
                   {{ settings.type_header_font | font_url }}, {{ settings.type_body_font | font_url }}
   - Taille h.   : {{ settings.type_header_font_size }}px
   - Params sect.: {{ section.settings.NOM_DU_PARAMETRE }} pour tout réglage propre à une section

2. TU GÉNÈRES TOUJOURS settings_schema.json (ou le bloc {% schema %} de section) quand tu produis du Liquid :
   - Pour une section : bloc {% schema %} en fin de fichier avec tous les settings utilisés (type, id, label, default)
   - Pour des settings globaux de thème : fichier config/settings_schema.json complet avec les groupes appropriés
   Exemple de bloc section :
   {% schema %}
   {
     "name": "Nom Section",
     "settings": [
       { "type": "color", "id": "color_primary", "label": "Couleur principale", "default": "#000000" },
       { "type": "font_picker", "id": "type_header_font", "label": "Police des titres", "default": "helvetica_n4" }
     ]
   }
   {% endschema %}

3. Pour les variables CSS dans les thèmes, utilise des custom properties alimentées par les settings :
   :root {
     --color-primary: {{ settings.color_primary }};
     --font-heading: {{ settings.type_header_font.family }}, {{ settings.type_header_font.fallback_families }};
   }

QUAND tu génères du code Shopify, tu fournis toujours :
1. La structure de fichiers complète
2. Le code Liquid avec les variables settings.* (jamais de hex en dur)
3. Le fichier settings_schema.json OU le bloc {% schema %} de la section
4. Les commandes d'installation
5. Les variables d'environnement nécessaires

OUTILS GITHUB DISPONIBLES :
Tu peux déclencher ces actions en utilisant ces balises dans ta réponse :
- Créer un repo : <GITHUB_CREATE_REPO nom="nom-du-repo" description="description" prive="false"/>
- Pousser un fichier : <GITHUB_PUSH_FILE repo="nom-repo" chemin="src/index.js" contenu="le code ici" commit="message"/>
- Créer une issue : <GITHUB_CREATE_ISSUE repo="nom-repo" titre="Bug: ..." corps="description"/>
- Lister les repos : <GITHUB_LIST_REPOS/>
Utilise ces balises quand l'utilisateur demande une action GitHub.


Tu réponds toujours en français."""
    },
    "recherche": {
        "nom": "Recherche",
        "prompt": """Tu es un expert en analyse de marché et veille concurrentielle avec une spécialisation Shopify.

COMPETENCES GENERALES :
- Synthèse de résultats web en insights actionnables
- Analyse comparative de solutions
- Identification de tendances et opportunités
- Les résultats de recherche web réels te sont fournis : utilise-les

COMPETENCES SHOPIFY :
- Analyse du Shopify App Store : catégories, concurrents, avis
- Identification de niches peu couvertes et rentables
- Lecture des avis négatifs pour détecter les opportunités
- Connaissance des apps populaires par catégorie
- Compréhension des besoins des marchands Shopify

QUAND tu analyses une opportunité Shopify, tu structures ainsi :
## Opportunite identifiee
## Marche actuel (concurrents, lacunes, avis)
## Differentiation possible
## Modele de revenus recommande (Freemium / Abonnement / Usage-based)
## Complexite technique (Faible / Moyenne / Elevee)
## Prochaine etape concrete cette semaine

Tu réponds toujours en français."""
    },
    "marketing": {
        "nom": "Marketing",
        "prompt": """Tu es un expert en marketing digital et création de contenu avec une spécialisation Shopify.

COMPETENCES GENERALES :
- Stratégie de contenu et branding
- Rédaction de posts réseaux sociaux, slogans, descriptions
- Copywriting persuasif et pages de vente
- Email marketing et séquences automatisées

COMPETENCES SHOPIFY :
- Rédaction de fiches App Store optimisées (titre, description courte, description longue)
- Stratégies d'acquisition pour apps Shopify
- Pages de vente pour apps et services Shopify
- Emails de prospection vers des marchands Shopify
- Arguments de vente spécifiques aux marchands e-commerce
- Optimisation ASO (App Store Optimization)

QUAND tu crées une fiche App Store, tu fournis :
## Nom de l'app + tagline accrocheuse
## Description courte (160 caractères max)
## Description longue structurée avec bénéfices
## 5 arguments de vente principaux
## Suggestions de screenshots et leur légende

Tu réponds toujours en français."""
    },
    "communication": {
        "nom": "Communication",
        "prompt": """Tu es un expert en communication professionnelle avec une spécialisation Shopify.

COMPETENCES GENERALES :
- Emails professionnels clairs et efficaces
- Messages adaptés au contexte (formel, décontracté)
- Réponses à des situations délicates
- Rédaction de documentation utilisateur

COMPETENCES SHOPIFY :
- Emails de prospection vers des marchands Shopify
- Réponses aux avis App Store (positifs et négatifs)
- Emails d'onboarding pour nouveaux utilisateurs d'une app
- Messages de support technique pour marchands
- Propositions commerciales pour développement d'apps custom
- Communication de mise à jour / changelog d'app

OUTIL GMAIL DISPONIBLE :
Quand l'utilisateur demande d'envoyer un email, tu DOIS inclure cette balise dans ta réponse :
<GMAIL_SEND destinataire="email@exemple.com" sujet="Sujet ici" corps="Corps complet de l'email ici"/>

IMPORTANT :
- Inclus TOUJOURS la balise quand on demande d'envoyer un email
- Le corps doit contenir le vrai texte de l'email, professionnel et complet
- Si l'utilisateur ne donne pas d'adresse email destinataire, demande-la avant d'envoyer

Exemple :
<GMAIL_SEND destinataire="contact@boutique.fr" sujet="Proposition de développement app Shopify" corps="Bonjour, Je me permets de vous contacter car je développe des applications Shopify sur mesure..."/>

OUTIL DEVIS DISPONIBLE :
Quand l'utilisateur demande la génération d'un devis, tu DOIS inclure cette balise :
<DEVIS client="Nom du client" projet="Description du projet" prestations="Prestation 1 - 800€|Prestation 2 - 500€|Prestation 3 - 200€" prix="1500" delai="3 semaines"/>

IMPORTANT devis :
- N'inclus la balise QUE si on demande explicitement un devis
- Estime des tarifs réalistes pour du dev Shopify (75-150€/h)
- Sépare les prestations avec le caractère |
- Le prix total doit être la somme des prestations individuelles
- Si tu manques d'informations (client, projet), demande-les avant de générer

Tu réponds toujours en français."""
    },
    "projet": {
        "nom": "Projet",
        "prompt": """Tu es un expert en gestion de projet avec une spécialisation Shopify.

COMPETENCES GENERALES :
- Création de roadmaps et plannings réalistes
- Découpage en tâches actionnables et priorisées
- Suivi d'avancement et gestion des risques
- Quand tu crées un fichier local, mets le contenu entre <FICHIER nom='fichier.md'> et </FICHIER>

COMPETENCES SHOPIFY :
- Structure d'un projet de développement d'app Shopify
- Phases types : specs → dev → review Shopify → publication
- Checklist de soumission App Store
- Gestion des versions et mises à jour d'apps
- Planification d'un portfolio d'apps
- Estimation réaliste des délais pour apps Shopify

OUTILS NOTION DISPONIBLES :
Quand l'utilisateur demande de sauvegarder, créer une page ou mettre dans Notion, tu DOIS obligatoirement inclure une de ces balises dans ta réponse :
- Créer une page : <NOTION_CREATE_PAGE titre="Titre ici" contenu="Contenu complet ici"/>
- Ajouter dans page principale : <NOTION_ADD_CONTENT titre="Titre section" contenu="Contenu ici"/>

IMPORTANT : Tu dois TOUJOURS inclure la balise Notion quand on te demande de sauvegarder ou créer dans Notion. La balise doit contenir le vrai contenu, pas un placeholder.

Exemple de réponse correcte quand on demande une page Notion pour un projet :
<NOTION_CREATE_PAGE titre="Roadmap shopify-upsell-app" contenu="Phase 1 : Specs (2 semaines) - Définir les fonctionnalités - Créer les wireframes Phase 2 : Dev (6 semaines) - Développer le MVP - Intégrer API Shopify Phase 3 : Tests (2 semaines) Phase 4 : Publication App Store (1 semaine)"/>

Tu réponds toujours en français."""
    
    },
    "shopify": {
        "nom": "Shopify Manager",
        "prompt": """Tu es le gestionnaire Shopify de l'utilisateur. Tu as accès direct à sa boutique.

OUTILS SHOPIFY DISPONIBLES :
Utilise ces balises pour interagir avec la boutique :
- Lister les produits : <SHOPIFY_LIST_PRODUCTS/>
- Lister les commandes : <SHOPIFY_LIST_ORDERS/>
- Voir les statistiques : <SHOPIFY_STATS/>
- Lister les clients : <SHOPIFY_LIST_CUSTOMERS/>
- Créer un produit : <SHOPIFY_CREATE_PRODUCT titre="Nom" description="Description" prix="29.99"/>

IMPORTANT : Quand l'utilisateur demande des infos sur sa boutique, tu DOIS inclure la balise correspondante dans ta réponse.

Exemples :
- "montre mes produits" → inclus <SHOPIFY_LIST_PRODUCTS/>
- "stats de ma boutique" → inclus <SHOPIFY_STATS/>
- "mes commandes" → inclus <SHOPIFY_LIST_ORDERS/>
- "mes clients" → inclus <SHOPIFY_LIST_CUSTOMERS/>

Tu réponds toujours en français."""
    },
    "design": {
        "nom": "Design",
        "prompt": """Tu es un expert UI/UX designer et développeur front-end spécialisé Shopify.

Tu crées des maquettes HTML/CSS de composants web en respectant fidèlement un style graphique analysé.

REGLES STRICTES :
1. Génère EXACTEMENT 3 maquettes distinctes enveloppées dans ces balises :
   <MAQUETTE_1>...</MAQUETTE_1>
   <MAQUETTE_2>...</MAQUETTE_2>
   <MAQUETTE_3>...</MAQUETTE_3>
2. Chaque maquette est un document HTML COMPLET et AUTONOME :
   - Commence par <!DOCTYPE html><html><head><meta charset="UTF-8">
   - Tout le CSS est dans une balise <style> (AUCUN fichier externe)
   - PAS d'images externes (utilise des divs colorés ou emojis comme placeholders)
   - PAS de JavaScript
   - Fonctionne en isolation complète dans un iframe
3. Les 3 maquettes proposent des variations stylistiques :
   - Maquette 1 : sobre et minimaliste
   - Maquette 2 : moderne et détaillée
   - Maquette 3 : créative et distinctive
4. Respecte EXACTEMENT les couleurs, typographie et style de l'analyse fournie
5. Le composant doit être réaliste, complet et prêt à montrer à un client

Tu réponds toujours en français. Les balises MAQUETTE contiennent UNIQUEMENT le code HTML."""
    }
}

# ── Fonctions Design ──────────────────────────────────────
def analyser_image_design(image_data, image_mime, composant):
    """Analyse les couleurs, typographie et style d'une image via vision."""
    try:
        reponse = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{image_mime};base64,{image_data}"}
                    },
                    {
                        "type": "text",
                        "text": f"""Analyse cette capture d'écran de site web et extrais avec précision :
1. Palette de couleurs (hex approximatifs) : couleur de fond, texte principal, texte secondaire, couleur d'accent/CTA, couleur des bordures
2. Typographie : serif ou sans-serif, style (moderne/classique/tech/élégant), graisse apparente
3. Style général : minimaliste / luxe / coloré / corporate / moderne / tech / etc.
4. Espacement : compact ou très aéré
5. Effets visuels : ombres portées, border-radius, gradients, séparateurs

Ces informations serviront à créer un composant "{composant}" dans ce style exact. Sois technique et précis."""
                    }
                ]
            }],
            max_tokens=600
        )
        return reponse.choices[0].message.content
    except Exception as e:
        return f"Style moderne sans-serif, fond blanc (#ffffff), texte sombre (#111111), accent bleu (#0066ff), espacement aéré, border-radius léger. (Analyse image non disponible : {e})"


def generer_maquettes(analyse_style, composant):
    """Génère 3 maquettes HTML/CSS basées sur l'analyse de style."""
    import re
    agent = AGENTS["design"]
    prompt = f"""Voici l'analyse du style visuel du site de référence :

{analyse_style}

Crée maintenant 3 maquettes HTML/CSS différentes du composant : **{composant}**

Chaque maquette doit :
- Utiliser les couleurs et polices extraites de l'analyse
- Être fonctionnelle et réaliste (données d'exemple cohérentes)
- Être prête à montrer à un client comme proposition de design"""

    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": agent["prompt"]},
            {"role": "user", "content": prompt}
        ],
        max_tokens=4000
    )

    texte = reponse.choices[0].message.content
    maquettes = []
    for i in range(1, 4):
        match = re.search(rf'<MAQUETTE_{i}>(.*?)</MAQUETTE_{i}>', texte, re.DOTALL)
        if match:
            maquettes.append(match.group(1).strip())
        else:
            maquettes.append(
                f"<!DOCTYPE html><html><body style='font-family:sans-serif;padding:20px;color:#888'>"
                f"<p>Maquette {i} non générée. Réessaie avec une description plus précise.</p>"
                f"</body></html>"
            )
    return maquettes


def extraire_design_tokens(url_site):
    """Fetche le contenu du site client et en extrait les design tokens via LLM."""
    contenu_brut = ""

    # 1. Extraction directe du HTML/contenu via Tavily extract
    try:
        result = tavily.extract(
            urls=[url_site],
            extract_depth="advanced",
            format="markdown"
        )
        if result.get("results"):
            contenu_brut = result["results"][0].get("raw_content", "")[:3500]
    except Exception:
        pass

    # 2. Fallback : recherche si l'extraction est trop pauvre
    if len(contenu_brut) < 300:
        try:
            resultats = tavily.search(
                query=f"{url_site} brand colors design typography CSS",
                max_results=3,
                search_depth="basic"
            )
            for r in resultats.get("results", []):
                contenu_brut += "\n" + r.get("content", "")[:600]
                if len(contenu_brut) > 2500:
                    break
        except Exception:
            pass

    if len(contenu_brut) < 50:
        return None

    # 3. Extraction des tokens via LLM
    # On lui passe le contenu brut et on lui demande un JSON strict
    prompt_extraction = f"""You are a CSS/design expert. Analyze this website content and extract design tokens.

Search carefully for:
- Hex color codes (#abc or #aabbcc anywhere in the text)
- CSS custom properties (--color-primary, --bg-*, etc.)
- Tailwind color classes (bg-gray-900, text-blue-500, bg-[#hex], border-zinc-200, etc.)
- Font family names (Inter, Montserrat, Playfair, etc.)
- Border-radius clues (rounded-full, rounded-xl, rounded-sm, rounded-[8px], etc.)
- Overall aesthetic clues in text (luxury, minimal, sport, tech, organic, etc.)

Website URL: {url_site}

Website content:
---
{contenu_brut[:2800]}
---

Respond ONLY with a valid JSON object. No markdown fences, no explanation. Use your best judgment for defaults if a value is not found:
{{
  "colors": {{
    "background": "#ffffff",
    "text_primary": "#111111",
    "text_secondary": "#6b7280",
    "accent": "#3b82f6",
    "button_bg": "#111111",
    "button_text": "#ffffff",
    "surface": "#f9fafb",
    "border": "#e5e7eb"
  }},
  "typography": {{
    "font_primary": "Inter, sans-serif",
    "font_headings": "Inter, sans-serif",
    "heading_weight": "700",
    "body_weight": "400"
  }},
  "shape": {{
    "radius_button": "6px",
    "radius_card": "12px"
  }},
  "style_label": "modern minimal",
  "spacing": "airy",
  "shadows": "subtle",
  "confidence": "medium"
}}"""

    try:
        reponse = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You extract design tokens from website content. Respond with valid JSON only. No markdown, no explanation."
                },
                {"role": "user", "content": prompt_extraction}
            ],
            max_tokens=500
        )
        texte = reponse.choices[0].message.content.strip()
        # Nettoyer les éventuels blocs markdown ```json ... ```
        texte = re.sub(r'^```[a-z]*\s*', '', texte)
        texte = re.sub(r'\s*```$', '', texte)
        match = re.search(r'\{.*\}', texte, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass

    return None


def generer_prompt_v0(description, url_site=""):
    """Génère un prompt v0 précis avec les vrais design tokens extraits du site client."""

    tokens = None
    if url_site:
        tokens = extraire_design_tokens(url_site)

    # Construire le contexte tokens pour le LLM
    if tokens:
        c = tokens.get("colors", {})
        t = tokens.get("typography", {})
        s = tokens.get("shape", {})
        tokens_context = f"""REAL DESIGN TOKENS extracted from {url_site}:

Colors (use these exact hex values via Tailwind arbitrary syntax or inline styles):
  background:      {c.get('background', '#ffffff')}
  text primary:    {c.get('text_primary', '#111111')}
  text secondary:  {c.get('text_secondary', '#6b7280')}
  accent:          {c.get('accent', '#3b82f6')}
  button bg:       {c.get('button_bg', '#111111')}
  button text:     {c.get('button_text', '#ffffff')}
  card/surface bg: {c.get('surface', '#f9fafb')}
  border:          {c.get('border', '#e5e7eb')}

Typography:
  body font:       {t.get('font_primary', 'Inter, sans-serif')}
  heading font:    {t.get('font_headings', 'Inter, sans-serif')}
  heading weight:  {t.get('heading_weight', '700')}
  body weight:     {t.get('body_weight', '400')}

Shape:
  button radius:   {s.get('radius_button', '6px')}
  card radius:     {s.get('radius_card', '12px')}

Visual style: {tokens.get('style_label', 'modern')}
Spacing feel: {tokens.get('spacing', 'airy')}
Shadows:      {tokens.get('shadows', 'subtle')}"""
    else:
        tokens_context = (
            f"No design tokens could be reliably extracted from {url_site}. "
            "Use clean, modern defaults (white bg, dark text, neutral grays, Inter font)."
            if url_site else
            "No site URL provided. Use clean, modern defaults."
        )

    # Détecter le contexte e-commerce pour ajouter des instructions spécifiques
    ecommerce_keywords = ["product", "produit", "shop", "store", "cart", "panier",
                          "price", "prix", "buy", "acheter", "checkout", "shopify",
                          "comparison", "comparaison", "feature", "plan"]
    is_ecommerce = any(k in description.lower() for k in ecommerce_keywords)

    ecommerce_block = ""
    if is_ecommerce:
        ecommerce_block = """
SHOPIFY / E-COMMERCE REQUIREMENTS:
- Use realistic product names, prices (format: €49.90 or $49.90), and feature lists
- "Add to cart" CTA button with hover state (darken by 10%)
- Show a "Best value" or "Most popular" badge on one option
- Strikethrough original price in text-secondary + sale price in accent color
- Star ratings (★★★★☆) where relevant
- Fully responsive: single column on mobile, grid on desktop"""

    user_content = f"""Component to build: {description}

{tokens_context}
{ecommerce_block}

CRITICAL: This component will be embedded on the client's website. It MUST look native — as if it was always part of the site.
Use the exact extracted colors via Tailwind arbitrary values (bg-[#hex], text-[#hex], border-[#hex]).
Import the exact font via a <style>@import url('https://fonts.googleapis.com/...')</style> tag if it's a Google Font."""

    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """You are a senior prompt engineer for v0.dev by Vercel.
v0 generates production-ready React + Tailwind CSS components.

Write a v0 prompt that will produce a pixel-perfect component matching the client's site.

Structure the prompt as follows:
1. Component name + purpose (1 sentence)
2. Exact layout description (columns, flex/grid, hierarchy)
3. Design tokens: paste the exact hex colors with their semantic role
4. Typography: font name, sizes, weights
5. Realistic sample data (names, prices, descriptions, features)
6. Hover/focus states and micro-interactions
7. Responsive behavior (mobile breakpoints)
8. End with: "Make it match exactly the existing site style. Use the exact hex colors provided via Tailwind arbitrary values. Pixel-perfect fidelity to the design tokens is mandatory."

OUTPUT RULES:
- Write ONLY the v0 prompt
- English only
- 250-450 words
- No preamble, no "Here is your prompt:", no markdown headers
- Ready to paste directly into v0.dev chat"""
            },
            {"role": "user", "content": user_content}
        ],
        max_tokens=800
    )

    return reponse.choices[0].message.content.strip()


# ── Orchestrateur ─────────────────────────────────────────
def choisir_agent(message):
    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Tu es un routeur d'agents IA.
Réponds avec UN SEUL MOT parmi : dev, recherche, marketing, communication, projet, shopify, design, tous.

- shopify : TOUT ce qui concerne une boutique existante : produits, commandes, clients, stats, inventaire, créer un produit, voir les ventes, statistiques de MA boutique
- dev : code, programmation, architecture, générer une app, bug, Remix, Node.js
- design : maquette, design, UI, UX, composant visuel, style, couleurs, typographie, wireframe
- recherche : analyser le marché, trouver des idées d'apps, concurrents, opportunités
- marketing : fiche App Store, page de vente, slogan, contenu, prospection
- communication : email, message, proposition commerciale, support
- projet : roadmap, planning, tâches, organisation, checklist
- tous : demande qui nécessite plusieurs expertises en même temps

IMPORTANT : Si l'utilisateur parle de SA boutique (mes produits, mes commandes, mes stats, ma boutique) → réponds TOUJOURS "shopify".

Réponds UNIQUEMENT avec le mot clé, rien d'autre."""
            },
            {"role": "user", "content": message}
        ]
    )
    agent_id = reponse.choices[0].message.content.strip().lower()
    return agent_id if agent_id in list(AGENTS.keys()) + ["tous"] else "recherche"


def appeler_agent(agent_id, message, contexte_memoire=""):
    agent = AGENTS[agent_id]
    system = agent["prompt"]
    # Injection automatique des connaissances Shopify
    system += f"\n\n{CONTEXTE_SHOPIFY}"
    if contexte_memoire:
        system += f"\n\nContexte projet actuel : {contexte_memoire}"

    # 🔍 Agent Recherche → cherche vraiment sur le web
    if agent_id == "recherche":
        resultats_web = recherche_web(message)
        message_enrichi = f"{message}\n\nVoici les résultats de recherche réels :\n{resultats_web}"
        contenu_user = message_enrichi
    else:
        contenu_user = message

    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": contenu_user}
        ]
    )
    texte = reponse.choices[0].message.content
    actions = []

    # 💻 Agent Dev → exécute le code
    if agent_id == "dev" and "<CODE>" in texte:
        debut = texte.find("<CODE>") + 6
        fin = texte.find("</CODE>")
        code = texte[debut:fin].strip()
        resultat = executer_code(code)
        texte = texte.replace(
            f"<CODE>{code}</CODE>",
            f"\n```python\n{code}\n```\n\n{resultat}"
        )
        actions.append("code_execute")

    # 🐙 Agent Dev → actions GitHub
    if agent_id == "dev":
        import re
        match = re.search(r'<GITHUB_CREATE_REPO nom="([^"]+)" description="([^"]*)" prive="([^"]+)"/>', texte)
        if match:
            resultat = github_creer_repo(match.group(1), match.group(2), match.group(3) == "true")
            texte = texte.replace(match.group(0), f"\n{resultat}\n")
            actions.append("github_repo_cree")

        match = re.search(r'<GITHUB_PUSH_FILE repo="([^"]+)" chemin="([^"]+)" contenu="([^"]*)" commit="([^"]*)"/>', texte, re.DOTALL)
        if match:
            resultat = github_pousser_fichier(match.group(1), match.group(2), match.group(3), match.group(4))
            texte = texte.replace(match.group(0), f"\n{resultat}\n")
            actions.append("github_fichier_pousse")

        match = re.search(r'<GITHUB_CREATE_ISSUE repo="([^"]+)" titre="([^"]+)" corps="([^"]*)"/>', texte)
        if match:
            resultat = github_creer_issue(match.group(1), match.group(2), match.group(3))
            texte = texte.replace(match.group(0), f"\n{resultat}\n")
            actions.append("github_issue_creee")

        if "<GITHUB_LIST_REPOS/>" in texte:
            resultat = github_lister_repos()
            texte = texte.replace("<GITHUB_LIST_REPOS/>", f"\n{resultat}\n")
            actions.append("github_liste")

    # 📁 Agent Projet → crée fichier local
    if agent_id == "projet" and "<FICHIER" in texte:
        import re
        match = re.search(r"<FICHIER nom='([^']+)'>(.*?)</FICHIER>", texte, re.DOTALL)
        if match:
            nom_fichier = match.group(1)
            contenu_fichier = match.group(2).strip()
            resultat = creer_fichier(nom_fichier, contenu_fichier)
            texte = texte.replace(match.group(0), f"\n{resultat}\n\n```\n{contenu_fichier}\n```")
            actions.append("fichier_cree")

    # 📝 Agent Projet → actions Notion
    if agent_id == "projet":
        import re
        match = re.search(r'<NOTION_CREATE_PAGE titre="([^"]+)" contenu="([^"]+)"/>', texte, re.DOTALL)
        if match:
            resultat = notion_creer_page(match.group(1), match.group(2))
            texte = texte.replace(match.group(0), f"\n{resultat}\n")
            actions.append("notion_page_creee")

        match = re.search(r'<NOTION_ADD_CONTENT titre="([^"]+)" contenu="([^"]+)"/>', texte, re.DOTALL)
        if match:
            resultat = notion_ajouter_contenu(match.group(1), match.group(2))
            texte = texte.replace(match.group(0), f"\n{resultat}\n")
            actions.append("notion_contenu_ajoute")

    # 📧 Agent Communication → envoi Gmail
    if agent_id == "communication":
        import re
        match = re.search(r'<GMAIL_SEND destinataire="([^"]+)" sujet="([^"]+)" corps="([^"]+)"/>', texte, re.DOTALL)
        if match:
            resultat = gmail_envoyer(match.group(1), match.group(2), match.group(3))
            texte = texte.replace(match.group(0), f"\n{resultat}\n")
            actions.append("gmail_envoye")

        # 📄 Agent Communication → génère un devis PDF
        match = re.search(r'<DEVIS([^/]+)/>', texte)
        if match:
            def _attr(name, s):
                m = re.search(rf'{name}="([^"]*)"', s)
                return m.group(1) if m else ""
            attrs        = match.group(1)
            client_d     = _attr("client", attrs)
            projet_d     = _attr("projet", attrs)
            presta_str   = _attr("prestations", attrs)
            prix_d       = _attr("prix", attrs)
            delai_d      = _attr("delai", attrs)
            prestations_d = [p.strip() for p in presta_str.split("|") if p.strip()]
            try:
                numero   = get_next_devis_numero()
                buf      = generer_pdf_devis(client_d, projet_d, prestations_d, prix_d, delai_d, numero)
                filename = f"devis_{numero:04d}_{client_d.replace(' ','_')}.pdf"
                with open(os.path.join(DEVIS_DIR, filename), "wb") as fh:
                    fh.write(buf.read())
                lien = (
                    f'<a href="/devis/download/{filename}" download '
                    f'style="display:inline-block;margin:10px 0;padding:10px 18px;'
                    f'background:#111;color:white;border-radius:8px;text-decoration:none;font-size:13px;">'
                    f'📄 Télécharger Devis N°{numero:04d} — {client_d}</a>'
                )
                texte = texte.replace(match.group(0), f"\n{lien}\n")
                actions.append("devis_genere")
            except Exception as e_devis:
                texte = texte.replace(match.group(0), f"\n❌ Erreur génération devis : {e_devis}\n")

    # 🛍️ Agent Shopify → actions boutique
    if agent_id == "shopify":
        import re

        if "<SHOPIFY_LIST_PRODUCTS/>" in texte:
            resultat = shopify_lister_produits()
            texte = texte.replace("<SHOPIFY_LIST_PRODUCTS/>", f"\n{resultat}\n")
            actions.append("shopify_produits")

        if "<SHOPIFY_LIST_ORDERS/>" in texte:
            resultat = shopify_lister_commandes()
            texte = texte.replace("<SHOPIFY_LIST_ORDERS/>", f"\n{resultat}\n")
            actions.append("shopify_commandes")

        if "<SHOPIFY_STATS/>" in texte:
            resultat = shopify_stats()
            texte = texte.replace("<SHOPIFY_STATS/>", f"\n{resultat}\n")
            actions.append("shopify_stats")

        if "<SHOPIFY_LIST_CUSTOMERS/>" in texte:
            resultat = shopify_lister_clients()
            texte = texte.replace("<SHOPIFY_LIST_CUSTOMERS/>", f"\n{resultat}\n")
            actions.append("shopify_clients")

        match = re.search(
            r'<SHOPIFY_CREATE_PRODUCT titre="([^"]+)" description="([^"]+)" prix="([^"]+)"/>',
            texte
        )
        if match:
            resultat = shopify_creer_produit(match.group(1), match.group(2), match.group(3))
            texte = texte.replace(match.group(0), f"\n{resultat}\n")
            actions.append("shopify_produit_cree")

    return texte, actions


def appeler_tous_les_agents(message, contexte_memoire=""):
    # L'orchestrateur décide quels agents sont vraiment nécessaires
    decision = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Tu es un orchestrateur qui choisit les agents nécessaires.
Réponds UNIQUEMENT avec une liste JSON d'agents parmi : dev, recherche, marketing, communication, projet, shopify.
Exemples :
- "crée une app et prépare le lancement" -> ["dev", "marketing", "projet"]
- "analyse le marché et rédige une proposition client" -> ["recherche", "communication"]
- "génère le code et la roadmap" -> ["dev", "projet"]
- "tout analyser et préparer" -> ["dev", "recherche", "marketing", "projet"]
Réponds UNIQUEMENT avec le JSON, rien d'autre."""
            },
            {"role": "user", "content": message}
        ]
    )

    try:
        texte = decision.choices[0].message.content.strip()
        agents_a_consulter = json.loads(texte)
        agents_valides = ["dev", "recherche", "marketing", "communication", "projet", "shopify", "design"]
        agents_a_consulter = [a for a in agents_a_consulter if a in agents_valides]
        if not agents_a_consulter:
            agents_a_consulter = ["recherche", "marketing", "projet"]
    except:
        agents_a_consulter = ["recherche", "marketing", "projet"]

    # Appel de chaque agent sélectionné
    resultats = {}
    for agent_id in agents_a_consulter:
        prompt_specialise = (
            f"{message}\n\n"
            "Reponds uniquement depuis ton angle d'expertise. "
            "Sois concis (5-6 points max) mais précis et actionnable."
        )
        texte, _ = appeler_agent(agent_id, prompt_specialise, contexte_memoire)
        resultats[agent_id] = texte

    # Construction de la synthèse
    parties = []
    noms = {
        "dev": "Expert Dev",
        "recherche": "Expert Recherche",
        "marketing": "Expert Marketing",
        "communication": "Expert Communication",
        "projet": "Expert Projet",
        "shopify": "Shopify Manager",
        "design": "Expert Design"
    }
    for agent_id, contenu in resultats.items():
        parties.append(f"{noms[agent_id]} :\n{contenu}")

    synthese_prompt = (
        f"Voici les analyses de {len(agents_a_consulter)} experts sur : \"{message}\"\n\n"
        + "\n\n".join(parties)
        + "\n\nFais une synthese complete, structuree et actionnable en francais. "
        "Organise par sections claires. Garde les meilleurs insights de chaque expert."
    )

    synthese = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un orchestrateur expert. Tu synthetises les analyses "
                    "de plusieurs experts en une reponse claire et actionnable. "
                    "Tu reponds en francais."
                )
            },
            {"role": "user", "content": synthese_prompt}
        ]
    )

    agents_utilises = ", ".join([noms[a] for a in agents_a_consulter])
    resultat_final = (
        f"*Agents consultés : {agents_utilises}*\n\n"
        + synthese.choices[0].message.content
    )
    return resultat_final

def construire_contexte_memoire(memoire):
    if not memoire["projets"] and not memoire["decisions"]:
        return ""
    contexte = ""
    if memoire["projets"]:
        contexte += "Projets actifs : " + ", ".join(memoire["projets"][-3:]) + "\n"
    if memoire["decisions"]:
        contexte += "Dernières décisions : " + " | ".join(memoire["decisions"][-3:])
    return contexte

def extraire_infos_memoire(message, reponse, memoire):
    try:
        detection = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": 'Réponds UNIQUEMENT en JSON : {"projet": "nom si mentionné sinon null", "decision": "décision importante sinon null"}'
                },
                {"role": "user", "content": f"Message: {message}\nRéponse: {reponse[:200]}"}
            ]
        )
        texte = detection.choices[0].message.content.strip()
        infos = json.loads(texte)
        if infos.get("projet") and infos["projet"] not in memoire["projets"]:
            memoire["projets"].append(infos["projet"])
        if infos.get("decision"):
            memoire["decisions"].append(infos["decision"])
    except:
        pass
    return memoire

# ── Routes Flask ──────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message", "")

    memoire = charger_memoire()
    contexte = construire_contexte_memoire(memoire)
    agent_id = choisir_agent(message)

    if agent_id == "tous":
        reponse = appeler_tous_les_agents(message, contexte)
        agent_nom = "Synthèse multi-agents"
        actions = []
    else:
        reponse, actions = appeler_agent(agent_id, message, contexte)
        agent_nom = AGENTS[agent_id]["nom"]

    memoire = extraire_infos_memoire(message, reponse, memoire)
    memoire["historique"].append({
        "date": datetime.datetime.now().isoformat(),
        "message": message,
        "agent": agent_nom
    })
    sauvegarder_memoire(memoire)

    return jsonify({
        "reponse": reponse,
        "agent": agent_nom,
        "projets": memoire["projets"],
        "actions": actions
    })

@app.route("/memoire", methods=["GET"])
def voir_memoire():
    return jsonify(charger_memoire())

@app.route("/design/analyser", methods=["POST"])
def design_analyser():
    image = request.files.get("image")
    composant = request.form.get("composant", "tableau de comparaison produits")

    if not image:
        return jsonify({"erreur": "Aucune image fournie"}), 400
    if not image.content_type.startswith("image/"):
        return jsonify({"erreur": "Le fichier doit être une image"}), 400

    image_data = base64.b64encode(image.read()).decode("utf-8")
    image_mime = image.content_type or "image/jpeg"

    analyse = analyser_image_design(image_data, image_mime, composant)
    maquettes = generer_maquettes(analyse, composant)

    return jsonify({
        "analyse": analyse,
        "maquettes": maquettes,
        "composant": composant
    })

@app.route("/design/valider", methods=["POST"])
def design_valider():
    data = request.json
    maquette_html = data.get("maquette", "")
    composant = data.get("composant", "composant")

    message = f"""Convertis cette maquette HTML/CSS en code Liquid Shopify complet et fonctionnel.

Composant cible : {composant}

Maquette HTML/CSS de référence :
```html
{maquette_html}
```

Génère :
1. Le fichier Liquid (.liquid) avec les bonnes variables Shopify (product, collection, settings…)
2. Le CSS correspondant dans une balise <style> ou fichier assets/
3. Les instructions d'intégration dans un thème Shopify (où placer le fichier, comment l'inclure)"""

    reponse, actions = appeler_agent("dev", message)
    return jsonify({"code_liquid": reponse, "agent": "Dev", "actions": actions})

@app.route("/design/v0/prompt", methods=["POST"])
def design_v0_prompt():
    data = request.json
    description = data.get("description", "").strip()
    url_site = data.get("url_site", "").strip()

    if not description:
        return jsonify({"erreur": "Description du composant requise"}), 400

    # Extraction des tokens séparément pour les exposer au frontend
    tokens = None
    if url_site:
        tokens = extraire_design_tokens(url_site)

    prompt = generer_prompt_v0(description, url_site)
    url_v0 = "https://v0.dev/chat?q=" + urllib.parse.quote(prompt, safe="")

    return jsonify({
        "prompt_v0": prompt,
        "url_v0": url_v0,
        "description": description,
        "tokens": tokens
    })

@app.route("/design/v0/convertir", methods=["POST"])
def design_v0_convertir():
    data = request.json
    code_v0 = data.get("code_v0", "").strip()
    composant = data.get("composant", "composant")

    if not code_v0:
        return jsonify({"erreur": "Code v0 requis"}), 400

    message = f"""Convertis ce composant React/Tailwind (généré par v0.dev) en code Liquid Shopify complet et fonctionnel.

Composant : {composant}

Code React/Tailwind de référence :
```jsx
{code_v0}
```

Génère :
1. Le fichier .liquid complet avec les variables Shopify appropriées (product, collection, section.settings…)
2. Le CSS correspondant adapté aux thèmes Shopify (dans <style> ou assets/)
3. Le schéma de section Shopify ({{% schema %}}) avec les paramètres configurables
4. Les instructions d'intégration dans un thème Dawn ou similaire"""

    reponse, actions = appeler_agent("dev", message)
    return jsonify({"code_liquid": reponse, "agent": "Dev", "actions": actions})

# ── Analyse de conversation client ───────────────────────
@app.route("/analyser-conversation", methods=["POST"])
def analyser_conversation():
    data         = request.json
    conversation = data.get("conversation", "").strip()
    source       = data.get("source", "whatsapp")

    if not conversation:
        return jsonify({"erreur": "Conversation vide"}), 400

    system_prompt = (
        "Tu es un expert en gestion de projet pour développeur d'extensions Shopify.\n"
        "Analyse cette conversation client et extrais de façon structurée :\n"
        "- Besoin principal (en une phrase claire)\n"
        "- Type d'extension demandée\n"
        "- Fonctionnalités mentionnées (liste)\n"
        "- Contraintes (délai, budget mentionné, contraintes techniques)\n"
        "- Style visuel souhaité (si mentionné)\n"
        "- Questions à clarifier avant de commencer\n"
        "- Ton recommandé pour répondre au client\n"
        "Retourne UNIQUEMENT un JSON valide avec ces clés :\n"
        "besoin, type_extension, fonctionnalites[], contraintes{}, style, questions[], ton"
    )

    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Source : {source}\n\nConversation :\n{conversation}"}
        ],
        max_tokens=1200
    )

    texte = reponse.choices[0].message.content.strip()
    texte = re.sub(r'^```[a-z]*\s*', '', texte)
    texte = re.sub(r'\s*```$', '', texte)
    m = re.search(r'\{.*\}', texte, re.DOTALL)

    analyse = {}
    if m:
        try:
            analyse = json.loads(m.group(0))
        except Exception:
            analyse = {"erreur": "JSON invalide", "brut": texte}
    else:
        analyse = {"erreur": "Pas de JSON", "brut": texte}

    def li(items):
        return "\n".join(f"• {i}" for i in (items or []))

    contraintes = analyse.get("contraintes") or {}
    contra_str  = "\n".join(f"• {k} : {v}" for k, v in contraintes.items()) or "Aucune identifiée"

    compte_rendu = (
        f"📋 COMPTE-RENDU — {source.upper()}\n\n"
        f"🎯 BESOIN PRINCIPAL\n{analyse.get('besoin','Non identifié')}\n\n"
        f"🔧 TYPE D'EXTENSION\n{analyse.get('type_extension','Non précisé')}\n\n"
        f"⚙️ FONCTIONNALITÉS\n{li(analyse.get('fonctionnalites',[]))}\n\n"
        f"⚠️ CONTRAINTES\n{contra_str}\n\n"
        f"🎨 STYLE VISUEL\n{analyse.get('style','Non précisé')}\n\n"
        f"❓ QUESTIONS À CLARIFIER\n{li(analyse.get('questions',[]))}\n\n"
        f"💬 TON RECOMMANDÉ\n{analyse.get('ton','Professionnel et bienveillant')}"
    )

    return jsonify({"analyse": analyse, "compte_rendu": compte_rendu})


@app.route("/valider-conversation", methods=["POST"])
def valider_conversation():
    data    = request.json
    analyse = data.get("analyse", {})

    if not analyse:
        return jsonify({"erreur": "Analyse manquante"}), 400

    besoin = analyse.get("besoin", "")
    contexte = (
        f"BRIEF CLIENT VALIDÉ :\n"
        f"Besoin : {besoin}\n"
        f"Type extension : {analyse.get('type_extension','')}\n"
        f"Fonctionnalités : {', '.join(analyse.get('fonctionnalites',[]))}\n"
        f"Contraintes : {json.dumps(analyse.get('contraintes',{}), ensure_ascii=False)}\n"
        f"Style : {analyse.get('style','')}\n"
        f"Ton : {analyse.get('ton','')}"
    )

    tasks = {
        "projet": (
            f"Sur la base de ce brief client validé, génère une roadmap complète pour ce projet Shopify.\n\n"
            f"{contexte}\n\n"
            "Structure en phases (Specs / Dev / Tests / Publication) avec durées, tâches et priorités. "
            "Sois précis et actionnable."
        ),
        "dev": (
            f"Sur la base de ce brief client validé, génère les specs techniques complètes.\n\n"
            f"{contexte}\n\n"
            "Inclus : architecture, stack recommandé, API Shopify nécessaires, structure de fichiers, "
            "points techniques complexes à anticiper."
        ),
        "marketing": (
            f"Sur la base de ce brief client validé, génère le brief design et la fiche App Store.\n\n"
            f"{contexte}\n\n"
            "Inclus : positionnement, nom d'app suggéré, tagline, description courte (160 car.), "
            "description longue, 5 arguments clés, style visuel recommandé."
        ),
        "communication": (
            f"Sur la base de ce brief client validé, rédige l'email de confirmation professionnel au client.\n\n"
            f"{contexte}\n\n"
            f"L'email doit confirmer la compréhension du besoin, résumer les fonctionnalités retenues, "
            f"proposer les prochaines étapes concrètes, et utiliser ce ton : {analyse.get('ton','professionnel')}."
        ),
    }

    resultats = {}

    def _appeler(agent_id, message):
        texte, _ = appeler_agent(agent_id, message)
        return agent_id, texte

    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(_appeler, aid, msg): aid for aid, msg in tasks.items()}
        for fut in futures:
            try:
                aid, texte = fut.result(timeout=90)
                resultats[aid] = texte
            except Exception as e:
                resultats[futures[fut]] = f"❌ Erreur : {e}"

    nom_projet = besoin[:60] if besoin else "Projet client"
    memoire    = charger_memoire()
    if nom_projet not in memoire["projets"]:
        memoire["projets"].append(nom_projet)
    memoire["decisions"].append(f"Brief validé : {nom_projet}")
    memoire["historique"].append({
        "date":    datetime.datetime.now().isoformat(),
        "message": f"Analyse conversation → {nom_projet}",
        "agent":   "Analyse Client"
    })
    sauvegarder_memoire(memoire)

    return jsonify({
        "roadmap":         resultats.get("projet", ""),
        "specs":           resultats.get("dev", ""),
        "brief_marketing": resultats.get("marketing", ""),
        "email_client":    resultats.get("communication", ""),
        "projet":          nom_projet
    })


# ── Dashboard ─────────────────────────────────────────────
@app.route("/dashboard")
def dashboard():
    memoire     = charger_memoire()
    historique  = memoire.get("historique", [])
    projets     = memoire.get("projets", [])
    decisions   = memoire.get("decisions", [])

    total_messages  = len(historique)
    total_projets   = len(projets)
    total_decisions = len(decisions)
    last_date = historique[-1]["date"][:10] if historique else "—"

    agent_counts = {}
    for h in historique:
        a = h.get("agent", "Inconnu")
        agent_counts[a] = agent_counts.get(a, 0) + 1
    max_count  = max(agent_counts.values()) if agent_counts else 1
    top_agents = sorted(agent_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    agents_html = "".join(
        f'<div class="agent-bar">'
        f'<span class="agent-name">{n}</span>'
        f'<div class="bar-track"><div class="bar-fill" style="width:{int(c/max_count*100)}%"></div></div>'
        f'<span class="agent-count">{c}</span></div>'
        for n, c in top_agents
    ) if top_agents else '<div class="empty-state">Aucune conversation encore.</div>'

    projets_html = "".join(
        f'<div class="projet-card">'
        f'<span class="projet-name">📁 {p}</span>'
        f'<button class="btn-del" data-nom="{p.replace(chr(34), "&quot;")}" '
        f'onclick="supprimerProjet(this.dataset.nom)">Supprimer</button>'
        f'</div>'
        for p in projets
    ) if projets else '<div class="empty-state">Aucun projet mémorisé.</div>'

    decisions_html = "".join(
        f'<div class="dec-item">{d}</div>' for d in decisions[-8:][::-1]
    ) if decisions else '<div class="empty-state">Aucune décision enregistrée.</div>'

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Dashboard — Mon Assistant IA</title>
  <style>
    *{{margin:0;padding:0;box-sizing:border-box}}
    body{{font-family:system-ui,sans-serif;background:#f5f5f5;min-height:100vh;padding:32px 16px}}
    .wrap{{max-width:900px;margin:0 auto}}
    .dash-head{{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:28px}}
    .dash-head h1{{font-size:22px;font-weight:700;color:#111}}
    .sub{{font-size:12px;color:#aaa;margin-top:3px}}
    .dash-head a{{font-size:13px;color:#555;text-decoration:none;padding:8px 16px;border:1px solid #ddd;border-radius:8px;background:white}}
    .dash-head a:hover{{background:#f0f0f0}}
    .stats{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px}}
    .stat{{background:white;border-radius:12px;padding:20px 24px;box-shadow:0 2px 8px rgba(0,0,0,.06)}}
    .stat-v{{font-size:36px;font-weight:700;color:#111}}
    .stat-l{{font-size:12px;color:#888;margin-top:4px}}
    .card{{background:white;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.06);margin-bottom:20px}}
    .card h2{{font-size:11px;font-weight:700;color:#888;text-transform:uppercase;letter-spacing:.06em;margin-bottom:16px}}
    .agent-bar{{display:flex;align-items:center;gap:10px;margin-bottom:10px}}
    .agent-name{{font-size:13px;color:#444;width:180px;flex-shrink:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .bar-track{{flex:1;background:#f0f0f0;border-radius:4px;height:6px}}
    .bar-fill{{background:#111;border-radius:4px;height:6px}}
    .agent-count{{font-size:12px;color:#888;width:24px;text-align:right}}
    .projet-card{{display:flex;align-items:center;justify-content:space-between;padding:12px 0;border-bottom:1px solid #f0f0f0}}
    .projet-card:last-child{{border-bottom:none}}
    .projet-name{{font-size:14px;color:#111}}
    .btn-del{{padding:5px 12px;background:#fee2e2;color:#991b1b;border:none;border-radius:6px;font-size:12px;cursor:pointer}}
    .btn-del:hover{{background:#fecaca}}
    .dec-item{{font-size:13px;color:#555;padding:8px 0 8px 12px;border-left:2px solid #e0e0e0;margin-bottom:6px;line-height:1.5}}
    .empty-state{{font-size:13px;color:#bbb;text-align:center;padding:24px}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="dash-head">
      <div><h1>📊 Dashboard</h1><div class="sub">Dernière activité : {last_date}</div></div>
      <a href="/">← Retour au chat</a>
    </div>
    <div class="stats">
      <div class="stat"><div class="stat-v">{total_messages}</div><div class="stat-l">Messages échangés</div></div>
      <div class="stat"><div class="stat-v">{total_projets}</div><div class="stat-l">Projets mémorisés</div></div>
      <div class="stat"><div class="stat-v">{total_decisions}</div><div class="stat-l">Décisions enregistrées</div></div>
    </div>
    <div class="card"><h2>Agents les plus utilisés</h2>{agents_html}</div>
    <div class="card"><h2>Projets mémorisés</h2><div id="list">{projets_html}</div></div>
    <div class="card"><h2>Dernières décisions</h2>{decisions_html}</div>
  </div>
  <script>
    async function supprimerProjet(nom) {{
      if (!confirm('Supprimer "' + nom + '" de la mémoire ?')) return;
      const r = await fetch('/projet/supprimer', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{nom}})
      }});
      if (r.ok) location.reload();
    }}
  </script>
</body></html>"""


@app.route("/projet/supprimer", methods=["POST"])
def supprimer_projet():
    nom = request.json.get("nom", "")
    memoire = charger_memoire()
    memoire["projets"] = [p for p in memoire["projets"] if p != nom]
    sauvegarder_memoire(memoire)
    return jsonify({"ok": True})


@app.route("/devis", methods=["POST"])
def route_devis():
    data        = request.json
    client_nom  = data.get("client", "Client")
    projet      = data.get("projet", "")
    prestations = data.get("prestations", [])
    prix_total  = data.get("prix_total", "0")
    delai       = data.get("delai", "")
    numero      = get_next_devis_numero()
    buf         = generer_pdf_devis(client_nom, projet, prestations, prix_total, delai, numero)
    filename    = f"devis_{numero:04d}_{client_nom.replace(' ', '_')}.pdf"
    return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.route("/devis/download/<filename>")
def telecharger_devis(filename):
    filename = os.path.basename(filename)
    path = os.path.join(DEVIS_DIR, filename)
    if not os.path.exists(path):
        return "Fichier introuvable", 404
    return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
