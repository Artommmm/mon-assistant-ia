from flask import Flask, request, jsonify, send_from_directory, send_file
from groq import Groq
from tavily import TavilyClient
from dotenv import load_dotenv
import json, os, datetime, subprocess, tempfile, base64, urllib.parse, re, io, threading, uuid
from apscheduler.schedulers.background import BackgroundScheduler
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

def formater_notion_id(page_id):
    """Assure que l'ID Notion est au format UUID avec tirets (xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)."""
    if not page_id:
        return page_id
    raw = page_id.strip().replace("-", "").replace(" ", "")
    if len(raw) != 32:
        return page_id  # Longueur inattendue, on retourne tel quel pour garder l'erreur explicite
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"

notion = NotionClient(auth=os.getenv("NOTION_TOKEN"))
notion_page_id = formater_notion_id(os.getenv("NOTION_PAGE_ID"))

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

# ── Notion Sync Intelligente ─────────────────────────────

SECTIONS_PROJET = {
    "brief":      "📋 Brief client",
    "specs":      "⚙️ Specs techniques",
    "roadmap":    "🗺️ Roadmap détaillée",
    "email":      "💬 Communications",
    "devis":      "💰 Devis",
    "historique": "📝 Historique",
}

# Inverse map: Notion heading → content key
_HEADING_TO_KEY = {v: k for k, v in SECTIONS_PROJET.items()}


def _extraire_contenu_notion_page(page_id):
    """Lit tous les blocs d'une page Notion et retourne un dict {key: text} par section."""
    all_blocks = _list_all_blocks(page_id)
    HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}
    sections = {}
    current_heading = None
    for block in all_blocks:
        btype = block["type"]
        if btype in HEADING_TYPES:
            rt = block.get(btype, {}).get("rich_text", [])
            current_heading = "".join(
                t.get("text", {}).get("content", "") for t in rt
            ).strip()
            sections.setdefault(current_heading, [])
        elif current_heading and btype == "paragraph":
            rt = block.get("paragraph", {}).get("rich_text", [])
            text = "".join(t.get("text", {}).get("content", "") for t in rt).strip()
            if text:
                sections[current_heading].append(text)
    content = {}
    for heading, paragraphs in sections.items():
        key = _HEADING_TO_KEY.get(heading)
        if key and paragraphs:
            content[key] = "\n\n".join(paragraphs)
    return content


def _backfill_content_from_notion(nom_projet):
    """Cherche la page Notion du projet, extrait son contenu et le sauvegarde dans memoire."""
    if not notion:
        return {}
    try:
        page_id = _trouver_page_enfant(nom_projet)
        if not page_id:
            return {}
        content = _extraire_contenu_notion_page(page_id)
        if content:
            memoire = charger_memoire()
            memoire.setdefault("projets_content", {})[nom_projet] = content
            sauvegarder_memoire(memoire)
        return content
    except Exception:
        return {}


def _nt(content):
    return {"type": "text", "text": {"content": content}}


def _make_paragraph(text):
    return {
        "object": "block", "type": "paragraph",
        "paragraph": {"rich_text": [_nt(text)] if text and text.strip() else []}
    }


def _make_heading(text, level=2):
    h = f"heading_{level}"
    return {"object": "block", "type": h, h: {"rich_text": [_nt(text)]}}


def _make_todo(text, checked=False):
    return {
        "object": "block", "type": "to_do",
        "to_do": {"rich_text": [_nt(text)], "checked": checked}
    }


def _make_callout(text, emoji="🟢", color="green_background"):
    return {
        "object": "block", "type": "callout",
        "callout": {
            "rich_text": [_nt(text)],
            "icon": {"type": "emoji", "emoji": emoji},
            "color": color
        }
    }


def _paragraphs_from_text(text, max_chars=1900):
    if not text or not text.strip():
        return [_make_paragraph(" ")]
    return [_make_paragraph(text[i:i+max_chars]) for i in range(0, len(text), max_chars)]


def _trouver_page_enfant(titre_cible):
    """Cherche une page enfant par titre (insensible à la casse, ignore emoji préfixe)."""
    def _norm(t):
        t = t.strip()
        while t and not t[0].isalnum():
            t = t[1:].strip()
        return t.lower()

    cible_norm = _norm(titre_cible)
    cursor = None
    while True:
        params = {"block_id": notion_page_id}
        if cursor:
            params["start_cursor"] = cursor
        blocks = notion.blocks.children.list(**params)
        for block in blocks.get("results", []):
            if block["type"] == "child_page":
                titre_bloc = block.get("child_page", {}).get("title", "")
                if _norm(titre_bloc) == cible_norm:
                    return block["id"]
        if not blocks.get("has_more"):
            break
        cursor = blocks.get("next_cursor")
    return None


def _list_all_blocks(block_id):
    """Récupère tous les blocs enfants d'un bloc (paginé)."""
    all_blocks = []
    cursor = None
    while True:
        params = {"block_id": block_id}
        if cursor:
            params["start_cursor"] = cursor
        resp = notion.blocks.children.list(**params)
        all_blocks.extend(resp.get("results", []))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return all_blocks


def _trouver_section_blocks(page_id, heading_text):
    """Retourne (heading_block_id, last_block_id_in_section)."""
    HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}
    all_blocks = _list_all_blocks(page_id)

    heading_id = None
    last_block_id = None
    in_section = False

    for block in all_blocks:
        btype = block["type"]
        if btype in HEADING_TYPES:
            rich_text = block.get(btype, {}).get("rich_text", [])
            text = "".join(rt.get("text", {}).get("content", "") for rt in rich_text)
            if text.strip() == heading_text.strip():
                heading_id = block["id"]
                last_block_id = block["id"]
                in_section = True
            elif in_section:
                break
        elif in_section:
            last_block_id = block["id"]

    return heading_id, last_block_id


def _mettre_a_jour_section_notion(page_id, section_titre, contenu, timestamp=None):
    """Insère du contenu dans la bonne section de la page (après le dernier bloc de la section)."""
    _, last_block_id = _trouver_section_blocks(page_id, section_titre)

    new_blocks = []
    if timestamp:
        new_blocks.append(_make_paragraph(f"— {timestamp} —"))
    new_blocks += _paragraphs_from_text(contenu)

    try:
        if last_block_id:
            notion.blocks.children.append(page_id, children=new_blocks, after=last_block_id)
        else:
            notion.blocks.children.append(page_id, children=new_blocks)
    except Exception:
        notion.blocks.children.append(page_id, children=new_blocks)


def _mettre_a_jour_progression(page_id):
    """Recalcule le % depuis les to_do et met à jour le bloc barre de progression."""
    HEADING_TYPES = {"heading_1", "heading_2", "heading_3"}
    all_blocks = _list_all_blocks(page_id)

    total_todo = 0
    checked_todo = 0
    progression_para_id = None
    in_progression = False

    for block in all_blocks:
        btype = block["type"]
        if btype in HEADING_TYPES:
            text = "".join(
                rt.get("text", {}).get("content", "")
                for rt in block.get(btype, {}).get("rich_text", [])
            )
            in_progression = "📊 Progression" in text
        elif btype == "paragraph" and in_progression and not progression_para_id:
            progression_para_id = block["id"]
            in_progression = False
        elif btype == "to_do":
            total_todo += 1
            if block.get("to_do", {}).get("checked", False):
                checked_todo += 1

    if total_todo == 0 or not progression_para_id:
        return

    pct = int(checked_todo / total_todo * 100)
    filled = min(pct // 10, 10)
    barre = "▓" * filled + "░" * (10 - filled)
    if pct < 25:
        phase = "Phase 1 : Specs en cours"
    elif pct < 50:
        phase = "Phase 2 : Développement"
    elif pct < 75:
        phase = "Phase 3 : Tests"
    else:
        phase = "Phase 4 : Publication"

    try:
        notion.blocks.update(
            progression_para_id,
            paragraph={"rich_text": [_nt(f"{barre} {pct}% — {phase}")]}
        )
    except Exception:
        pass


def _creer_page_projet_structuree(nom_projet, contenu, type_action, meta, date_courte):
    """Crée une page Notion entièrement structurée et visuelle."""
    client_nom     = meta.get("client", "—")
    budget         = meta.get("budget", "—")
    delai          = meta.get("delai", "—")
    type_extension = meta.get("type_extension", "—")
    date_livraison = meta.get("date_livraison", "—")

    by_section = {k: " " for k in SECTIONS_PROJET}
    section_key = type_action if type_action in SECTIONS_PROJET else "historique"
    by_section[section_key] = (contenu or " ")[:1900]

    callout_text = (
        f"🟢 En cours · Client : {client_nom} · Budget : {budget} · "
        f"Délai : {delai} · Livraison estimée : {date_livraison}"
    )
    hist_first = (
        (contenu or "")[:1900]
        if type_action == "historique"
        else f"{date_courte} — Projet créé depuis conversation client"
    )

    children = [
        _make_callout(callout_text),
        _make_heading("📊 Progression"),
        _make_paragraph("▓▓░░░░░░░░ 15% — Phase 1 : Specs en cours"),
        _make_heading("🗺️ Phases du projet"),
        _make_todo("Phase 1 — Specs & Design (15/06 → 22/06)"),
        _make_todo("Phase 2 — Développement (22/06 → 03/07)"),
        _make_todo("Phase 3 — Tests (03/07 → 06/07)"),
        _make_todo("Phase 4 — Publication App Store"),
        _make_heading("✅ Tâches immédiates"),
        _make_todo("Brief client analysé", True),
        _make_todo("Roadmap générée", True),
        _make_todo("Specs techniques rédigées", True),
        _make_todo("Wireframes validés par client"),
        _make_todo("Design tokens extraits"),
        _make_todo("Devis envoyé et signé"),
        _make_heading("📋 Brief client"),
        _make_paragraph(by_section["brief"]),
        _make_heading("⚙️ Specs techniques"),
        _make_paragraph(by_section["specs"]),
        _make_heading("🗺️ Roadmap détaillée"),
        _make_paragraph(by_section["roadmap"]),
        _make_heading("💬 Communications"),
        _make_paragraph(by_section["email"]),
        _make_heading("💰 Devis"),
        _make_paragraph(by_section["devis"]),
        _make_heading("📝 Historique"),
        _make_paragraph(hist_first),
    ]

    new_page = notion.pages.create(
        parent={"page_id": notion_page_id},
        properties={
            "title": {"title": [{"type": "text", "text": {"content": f"🛍️ {nom_projet}"}}]}
        },
        children=children
    )
    return new_page["id"]


def _mettre_a_jour_index_notion(nom_projet, page_projet_id, meta=None):
    """Crée ou met à jour la page INDEX avec une ligne riche par projet."""
    if meta is None:
        meta = {}
    if not any(v and v not in ("—", "") for v in meta.values()):
        try:
            m = charger_memoire()
            meta = m.get("projets_meta", {}).get(nom_projet, meta)
        except Exception:
            pass

    INDEX_TITRE = "🗂️ Index Projets"
    index_id = _trouver_page_enfant(INDEX_TITRE)
    date_str = datetime.datetime.now().strftime("%d/%m/%Y")
    page_url = f"https://www.notion.so/{page_projet_id.replace('-', '')}"

    client_nom = meta.get("client", "—")
    budget     = meta.get("budget", "—")
    delai      = meta.get("delai", "—")
    type_ext   = meta.get("type_extension", "—")

    ligne = (
        f"🟢 {nom_projet} | {type_ext} | Client : {client_nom} | "
        f"Budget : {budget} | Délai : {delai} | Créé le {date_str} | {page_url}"
    )

    if not index_id:
        notion.pages.create(
            parent={"page_id": notion_page_id},
            properties={"title": {"title": [{"type": "text", "text": {"content": INDEX_TITRE}}]}},
            children=[
                _make_heading(INDEX_TITRE, level=1),
                _make_paragraph("Statut | Projet | Type | Client | Budget | Délai | Date"),
                {"object": "block", "type": "divider", "divider": {}},
                _make_paragraph(ligne),
            ]
        )
        return

    all_blocks = _list_all_blocks(index_id)
    existing_id = None
    for block in all_blocks:
        if block["type"] == "paragraph":
            text = "".join(
                rt.get("text", {}).get("content", "")
                for rt in block.get("paragraph", {}).get("rich_text", [])
            )
            if nom_projet in text:
                existing_id = block["id"]
                break

    if existing_id:
        try:
            notion.blocks.update(existing_id, paragraph={"rich_text": [_nt(ligne)]})
        except Exception:
            pass
    else:
        notion.blocks.children.append(index_id, children=[_make_paragraph(ligne)])


def notion_sync_projet(nom_projet, type_action, contenu, meta=None):
    """Sync structurée d'un projet vers Notion avec page visuelle complète."""
    if not notion_page_id or not os.getenv("NOTION_TOKEN"):
        return "⚠️ Notion non configuré"

    if meta is None:
        meta = {}

    section_titre = SECTIONS_PROJET.get(type_action, "📝 Historique")
    date_str    = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    date_courte = datetime.datetime.now().strftime("%d/%m/%Y")

    try:
        notion.pages.retrieve(notion_page_id)
    except Exception as e:
        return f"❌ Notion connexion échouée (ID={notion_page_id}) : {e}"

    # Cherche d'abord par ID mémorisé (évite un scan de liste à chaque appel)
    try:
        mem_ids = charger_memoire()
        stored_id = mem_ids.get("projets_meta", {}).get(nom_projet, {}).get("_notion_page_id")
        if stored_id:
            try:
                notion.pages.retrieve(stored_id)
                page_id = stored_id
            except Exception:
                page_id = None
                stored_id = None
        else:
            page_id = None
        if not page_id:
            page_id = _trouver_page_enfant(nom_projet)
    except Exception as e:
        return f"❌ Notion recherche page échouée : {e}"

    if not page_id:
        try:
            m = charger_memoire()
            if meta:
                m.setdefault("projets_meta", {})[nom_projet] = meta
            page_id = _creer_page_projet_structuree(
                nom_projet, contenu, type_action, meta, date_courte
            )
            m.setdefault("projets_meta", {}).setdefault(nom_projet, {})["_notion_page_id"] = page_id
            sauvegarder_memoire(m)
        except Exception as e:
            return f"❌ Notion création page '{nom_projet}' échouée : {e}"
        try:
            _mettre_a_jour_index_notion(nom_projet, page_id, meta)
        except Exception as e:
            print(f"[Notion index] Erreur non bloquante : {e}")
        return f"✅ Notion → Page structurée créée pour '{nom_projet}'"

    # Mémorise l'ID si pas encore fait
    if not stored_id:
        try:
            m2 = charger_memoire()
            m2.setdefault("projets_meta", {}).setdefault(nom_projet, {})["_notion_page_id"] = page_id
            sauvegarder_memoire(m2)
        except Exception:
            pass

    # Page existante → mise à jour intelligente de la section cible
    try:
        _mettre_a_jour_section_notion(page_id, section_titre, contenu or " ", date_str)
    except Exception as e:
        return f"❌ Notion update '{section_titre}' échoué : {e}"

    if type_action != "historique":
        try:
            _mettre_a_jour_section_notion(
                page_id, "📝 Historique",
                f"{date_courte} — Mise à jour [{section_titre}]", None
            )
        except Exception:
            pass

    try:
        _mettre_a_jour_progression(page_id)
    except Exception:
        pass

    try:
        _mettre_a_jour_index_notion(nom_projet, page_id, meta)
    except Exception as e:
        print(f"[Notion index] Erreur non bloquante : {e}")

    return f"✅ Notion sync → '{nom_projet}' [{section_titre}]"


# ── Agent Autonome 24/7 ───────────────────────────────────

AGENT_TASKS_META = {
    "veille_app_store":      {"nom": "Veille App Store",           "frequence": "Lundi 08h00"},
    "rapport_boutiques":     {"nom": "Rapport boutiques clients",  "frequence": "Lundi 09h00"},
    "alerte_stock":          {"nom": "Alerte stock critique",      "frequence": "Toutes les 6h"},
    "analyse_avis_negatifs": {"nom": "Analyse avis négatifs",      "frequence": "Mercredi 08h00"},
}


def _log_agent_execution(task_name, statut):
    try:
        memoire = charger_memoire()
        memoire.setdefault("agent_executions", []).append({
            "task": task_name,
            "date": datetime.datetime.now().isoformat(),
            "statut": statut
        })
        memoire["agent_executions"] = memoire["agent_executions"][-50:]
        sauvegarder_memoire(memoire)
    except Exception:
        pass


def veille_app_store():
    """Tâche 1 : Veille App Store — lundi 8h."""
    try:
        semaine = datetime.datetime.now().isocalendar()[1]
        r1 = tavily.search(query="new shopify apps 2025 trending", max_results=5, search_depth="basic")
        r2 = tavily.search(query="shopify app store gaps opportunities 2025", max_results=5, search_depth="basic")
        brut = ""
        for r in r1.get("results", []) + r2.get("results", []):
            brut += f"\n• {r['title']}\n{r['content'][:300]}\n"
        reponse_llm = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": AGENTS["recherche"]["prompt"] + "\n" + CONTEXTE_SHOPIFY},
                {"role": "user", "content": f"Identifie 3 opportunités d'apps Shopify depuis ces résultats:\n{brut}"}
            ],
            max_tokens=1500
        )
        analyse = reponse_llm.choices[0].message.content
        memoire = charger_memoire()
        memoire.setdefault("veille_hebdo", []).append(
            {"date": datetime.datetime.now().isoformat(), "semaine": f"Semaine {semaine}", "analyse": analyse}
        )
        memoire["veille_hebdo"] = memoire["veille_hebdo"][-10:]
        sauvegarder_memoire(memoire)
        dest = os.getenv("GMAIL_ADDRESS", "")
        if dest:
            gmail_envoyer(dest, f"🔍 Veille App Store - Semaine {semaine}", analyse)
        notion_sync_projet("Veille hebdomadaire", "historique", f"Semaine {semaine}\n\n{analyse}")
        _log_agent_execution("veille_app_store", f"✅ Semaine {semaine}")
    except Exception as e:
        _log_agent_execution("veille_app_store", f"❌ {str(e)[:120]}")


def rapport_boutiques():
    """Tâche 2 : Rapport boutiques — lundi 9h."""
    try:
        shopify_init()
        shop = shopify.Shop.current()
        date_debut = (datetime.datetime.now() - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
        commandes = shopify.Order.find(limit=250, status="any", created_at_min=date_debut)
        ca_semaine = sum(float(c.total_price) for c in commandes)
        produits = shopify.Product.find(limit=250)
        ruptures = []
        for p in produits:
            for v in p.variants:
                stock = getattr(v, "inventory_quantity", None)
                if stock is not None and stock <= 0:
                    ruptures.append(f"{p.title} — {v.title}")
        rapport = (
            f"📊 RAPPORT HEBDOMADAIRE — {shop.name}\n"
            f"Période : 7 derniers jours\n\n"
            f"• Commandes : {len(commandes)}\n"
            f"• CA : {ca_semaine:.2f} {shop.currency}\n"
            f"• Produits en rupture : {len(ruptures)}\n"
            + ("\nRuptures :\n" + "\n".join(f"  - {r}" for r in ruptures[:10]) if ruptures else "")
        )
        dest = os.getenv("GMAIL_ADDRESS", "")
        if dest:
            gmail_envoyer(dest, f"📊 Rapport hebdo - {shop.name}", rapport)
        notion_sync_projet(f"Rapport {shop.name}", "historique", rapport)
        _log_agent_execution("rapport_boutiques", f"✅ {len(commandes)} cmds / {ca_semaine:.0f}{shop.currency}")
    except Exception as e:
        _log_agent_execution("rapport_boutiques", f"❌ {str(e)[:120]}")


def alerte_stock():
    """Tâche 3 : Alerte stock critique — toutes les 6h."""
    try:
        shopify_init()
        produits = shopify.Product.find(limit=250)
        memoire = charger_memoire()
        alertes = memoire.get("alertes_stock_envoyees", {})
        now = datetime.datetime.now()
        # Nettoyer les alertes > 24h
        alertes = {k: v for k, v in alertes.items()
                   if (now - datetime.datetime.fromisoformat(v)).total_seconds() < 86400}
        nouvelles = 0
        for p in produits:
            for v in p.variants:
                stock = getattr(v, "inventory_quantity", None)
                if stock is not None and 0 < stock < 5:
                    cle = f"{p.id}_{v.id}"
                    if cle not in alertes:
                        dest = os.getenv("GMAIL_ADDRESS", "")
                        if dest:
                            gmail_envoyer(dest,
                                f"⚠️ Stock critique : {p.title}",
                                f"Produit : {p.title}\nVariante : {v.title}\nStock : {stock} unité(s)\n\nRéapprovisionner rapidement.")
                        alertes[cle] = now.isoformat()
                        nouvelles += 1
        memoire["alertes_stock_envoyees"] = alertes
        sauvegarder_memoire(memoire)
        _log_agent_execution("alerte_stock", f"✅ {nouvelles} alerte(s) envoyée(s)")
    except Exception as e:
        _log_agent_execution("alerte_stock", f"❌ {str(e)[:120]}")


def analyse_avis_negatifs():
    """Tâche 4 : Analyse avis négatifs App Store — mercredi 8h."""
    try:
        brut = ""
        for cat in ["loyalty", "upsell", "inventory", "SEO"]:
            r = tavily.search(query=f"shopify app store negative reviews 1 star {cat}",
                              max_results=3, search_depth="basic")
            for res in r.get("results", []):
                brut += f"\n[{cat}] {res['title']}: {res['content'][:250]}\n"
        reponse_llm = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": AGENTS["recherche"]["prompt"] + "\n" + CONTEXTE_SHOPIFY},
                {"role": "user", "content": f"Identifie les frustrations récurrentes et les opportunités d'apps depuis ces avis négatifs:\n{brut}"}
            ],
            max_tokens=1500
        )
        analyse = reponse_llm.choices[0].message.content
        memoire = charger_memoire()
        memoire.setdefault("opportunites_detectees", []).append(
            {"date": datetime.datetime.now().isoformat(), "analyse": analyse}
        )
        memoire["opportunites_detectees"] = memoire["opportunites_detectees"][-10:]
        sauvegarder_memoire(memoire)
        dest = os.getenv("GMAIL_ADDRESS", "")
        if dest:
            gmail_envoyer(dest, "💡 Opportunités détectées cette semaine", analyse)
        notion_sync_projet("Analyse avis négatifs", "historique", analyse)
        _log_agent_execution("analyse_avis_negatifs", "✅ Analyse complète")
    except Exception as e:
        _log_agent_execution("analyse_avis_negatifs", f"❌ {str(e)[:120]}")


# Initialisation du scheduler (une seule instance grâce à --workers 1)
scheduler = BackgroundScheduler(timezone="Europe/Paris")
scheduler.add_job(veille_app_store,      "cron", day_of_week="mon", hour=8,  minute=0, id="veille_app_store")
scheduler.add_job(rapport_boutiques,     "cron", day_of_week="mon", hour=9,  minute=0, id="rapport_boutiques")
scheduler.add_job(alerte_stock,          "interval", hours=6,                          id="alerte_stock")
scheduler.add_job(analyse_avis_negatifs, "cron", day_of_week="wed", hour=8,  minute=0, id="analyse_avis_negatifs")
scheduler.start()


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

FORMAT DE SORTIE POUR LES EMAILS :
Quand tu rédiges un email (que l'utilisateur demande d'en envoyer un ou qu'il faut confirmer un projet), structure TOUJOURS ta réponse ainsi :

SUJET : [sujet de l'email ici]

[corps complet de l'email, professionnel et complet, sans autre balise]

IMPORTANT :
- N'envoie JAMAIS l'email toi-même — rédige uniquement le texte
- La première ligne doit toujours commencer par "SUJET : "
- Le corps commence à la ligne suivant la ligne vide après le sujet
- Si tu n'as pas l'adresse email du destinataire, mets un placeholder [email du client]

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

OUTIL NOTION DISPONIBLE :
Quand l'utilisateur demande d'ajouter ou sauvegarder du contenu dans Notion, utilise cette balise pour l'injecter dans la page du projet actif :
<NOTION_ADD_CONTENT titre="Titre de la section" contenu="Contenu complet ici"/>

IMPORTANT : N'utilise JAMAIS <NOTION_CREATE_PAGE> — toute sauvegarde doit aller dans la page existante du projet via <NOTION_ADD_CONTENT>.

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


def appeler_agent(agent_id, message, contexte_memoire="", nom_projet_ctx=None, max_tokens=1500):
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
        ],
        max_tokens=max_tokens,
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
            if nom_projet_ctx:
                # Dans le contexte d'un projet : injecte dans la page existante au lieu de créer une orpheline
                contenu_tag = match.group(2)
                threading.Thread(
                    target=notion_sync_projet,
                    args=(nom_projet_ctx, "historique", contenu_tag),
                    daemon=True,
                ).start()
                texte = texte.replace(match.group(0), "\n✅ Contenu ajouté dans le projet Notion\n")
                actions.append("notion_sync_projet")
            else:
                resultat = notion_creer_page(match.group(1), match.group(2))
                texte = texte.replace(match.group(0), f"\n{resultat}\n")
                actions.append("notion_page_creee")

        match = re.search(r'<NOTION_ADD_CONTENT titre="([^"]+)" contenu="([^"]+)"/>', texte, re.DOTALL)
        if match:
            if nom_projet_ctx:
                contenu_tag = match.group(2)
                threading.Thread(
                    target=notion_sync_projet,
                    args=(nom_projet_ctx, "historique", contenu_tag),
                    daemon=True,
                ).start()
                texte = texte.replace(match.group(0), "\n✅ Contenu ajouté dans le projet Notion\n")
                actions.append("notion_sync_projet")
            else:
                resultat = notion_ajouter_contenu(match.group(1), match.group(2))
                texte = texte.replace(match.group(0), f"\n{resultat}\n")
                actions.append("notion_contenu_ajoute")

    # 📧 Agent Communication → extrait <GMAIL_SEND> si présent mais NE l'envoie PAS
    # L'envoi nécessite une validation humaine explicite via /envoyer-email-valide
    if agent_id == "communication":
        import re
        match = re.search(r'<GMAIL_SEND destinataire="([^"]+)" sujet="([^"]+)" corps="([^"]+)"/>', texte, re.DOTALL)
        if match:
            dest_tag  = match.group(1)
            sujet_tag = match.group(2)
            corps_tag = match.group(3)
            # Remplace la balise par le texte structuré lisible (pas d'envoi)
            texte = texte.replace(
                match.group(0),
                f"\nSUJET : {sujet_tag}\n\n{corps_tag}\n"
            )
            actions.append("email_redige")
            # Sync dans Notion si contexte projet connu
            try:
                projet_cible = nom_projet_ctx
                if not projet_cible:
                    memoire_tmp = charger_memoire()
                    if memoire_tmp.get("projets"):
                        projet_cible = memoire_tmp["projets"][-1]
                if projet_cible:
                    contenu_email = f"Sujet : {sujet_tag}\nDestinataire : {dest_tag}\n\n{corps_tag}"
                    threading.Thread(target=notion_sync_projet,
                                     args=(projet_cible, "email", contenu_email), daemon=True).start()
            except Exception:
                pass

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
    return send_from_directory(".", "projets.html")

@app.route("/chat-libre")
def chat_libre():
    return send_from_directory(".", "index.html")

@app.route("/nouveau-projet")
def nouveau_projet_page():
    return send_from_directory(".", "nouveau-projet.html")

@app.route("/projet/<path:nom_projet>")
def projet_detail_page(nom_projet):
    return send_from_directory(".", "projet.html")

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

    # Sync historique Notion si un projet est actif et la réponse est substantielle
    if memoire.get("projets") and len(reponse) > 300:
        projet_actif = memoire["projets"][-1]
        contenu_hist = f"Question : {message}\n\nRéponse ({agent_nom}) :\n{reponse[:2000]}"
        threading.Thread(target=notion_sync_projet,
                         args=(projet_actif, "historique", contenu_hist), daemon=True).start()

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
        "- client_nom : prénom (et nom si mentionné) de la personne qui passe la commande. "
        "Cherche les formules de politesse, les signatures, ou la façon dont la personne se présente.\n"
        "- nom_projet : titre COURT du projet, max 35 caractères, "
        "format '[Prénom] — [fonctionnalité courte]', ex: 'Sophie — Badge stock faible'\n"
        "- besoin : besoin principal en une phrase claire\n"
        "- type_extension : type d'extension demandée\n"
        "- fonctionnalites : liste des fonctionnalités mentionnées\n"
        "- contraintes : objet avec les clés 'delai' (délai exact mentionné) et 'budget' (budget mentionné)\n"
        "- style : style visuel souhaité (si mentionné)\n"
        "- questions : questions à clarifier avant de commencer\n"
        "- ton : ton recommandé pour répondre au client\n"
        "Retourne UNIQUEMENT un JSON valide avec ces clés :\n"
        "client_nom, nom_projet, besoin, type_extension, fonctionnalites[], "
        "contraintes{delai, budget}, style, questions[], ton"
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
        f"👤 CLIENT\n{analyse.get('client_nom','Non identifié')}\n\n"
        f"📁 NOM PROJET\n{analyse.get('nom_projet','Non défini')}\n\n"
        f"🎯 BESOIN PRINCIPAL\n{analyse.get('besoin','Non identifié')}\n\n"
        f"🔧 TYPE D'EXTENSION\n{analyse.get('type_extension','Non précisé')}\n\n"
        f"⚙️ FONCTIONNALITÉS\n{li(analyse.get('fonctionnalites',[]))}\n\n"
        f"⚠️ CONTRAINTES\n{contra_str}\n\n"
        f"🎨 STYLE VISUEL\n{analyse.get('style','Non précisé')}\n\n"
        f"❓ QUESTIONS À CLARIFIER\n{li(analyse.get('questions',[]))}\n\n"
        f"💬 TON RECOMMANDÉ\n{analyse.get('ton','Professionnel et bienveillant')}"
    )

    return jsonify({"analyse": analyse, "compte_rendu": compte_rendu})


def parser_delai_en_jours(texte):
    """Convertit un délai textuel en nombre de jours. Retourne None si non parsable."""
    if not texte or texte.strip() in ("—", ""):
        return None
    texte = texte.lower().strip()
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(semaines?|jours?|mois)', texte)
    if not m:
        return None
    val = float(m.group(1).replace(",", "."))
    unite = m.group(2)
    if "semaine" in unite:
        return int(val * 7)
    elif "mois" in unite:
        return int(val * 30)
    else:
        return int(val)


# ── Helpers partagés validation ───────────────────────────

def _construire_contexte_brief(analyse):
    besoin = analyse.get("besoin", "")
    return besoin, (
        f"BRIEF CLIENT VALIDÉ :\n"
        f"Besoin : {besoin}\n"
        f"Type extension : {analyse.get('type_extension','')}\n"
        f"Fonctionnalités : {', '.join(analyse.get('fonctionnalites',[]))}\n"
        f"Contraintes : {json.dumps(analyse.get('contraintes',{}), ensure_ascii=False)}\n"
        f"Style : {analyse.get('style','')}\n"
        f"Ton : {analyse.get('ton','')}"
    )

def _construire_tasks(analyse, contexte):
    ton = analyse.get("ton", "professionnel")
    return {
        "projet": (
            f"Sur la base de ce brief client validé, génère une roadmap complète pour ce projet Shopify.\n\n"
            f"{contexte}\n\n"
            "Structure en phases (Specs / Dev / Tests / Publication) avec durées, tâches et priorités. "
            "Sois précis et actionnable. Limite ta réponse à l'essentiel."
        ),
        "dev": (
            f"Sur la base de ce brief client validé, génère les specs techniques complètes.\n\n"
            f"{contexte}\n\n"
            "Inclus : architecture, stack recommandé, API Shopify nécessaires, structure de fichiers, "
            "points techniques complexes à anticiper. Sois concis."
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
            f"proposer les prochaines étapes concrètes. Ton : {ton}."
        ),
    }

def _calculer_meta_projet(analyse, besoin):
    client_nom  = (analyse.get("client_nom") or "").strip()
    type_ext    = (analyse.get("type_extension") or "").strip()
    contraintes = analyse.get("contraintes") or {}
    delai = (
        contraintes.get("delai") or contraintes.get("délai")
        or contraintes.get("deadline") or ""
    )
    delai  = (delai or "—").strip() or "—"
    budget = (contraintes.get("budget") or contraintes.get("Budget") or "—")
    budget = (budget or "—").strip() or "—"
    jours  = parser_delai_en_jours(delai)
    date_livraison = (
        (datetime.datetime.now() + datetime.timedelta(days=jours)).strftime("%d/%m/%Y")
        if jours else "—"
    )
    nom_projet_llm = (analyse.get("nom_projet") or "").strip()
    if nom_projet_llm:
        nom_projet = nom_projet_llm[:50]
    elif client_nom and type_ext:
        label = type_ext if len(type_ext) <= 28 else type_ext[:25].rsplit(" ", 1)[0]
        nom_projet = f"{client_nom} — {label}"
    elif client_nom:
        nom_projet = client_nom
    else:
        nom_projet = (besoin[:50] if besoin else "Projet client")
    return {
        "nom_projet":     nom_projet,
        "client_nom":     client_nom,
        "type_ext":       type_ext,
        "budget":         budget,
        "delai":          delai,
        "date_livraison": date_livraison,
    }

def _sauvegarder_resultats_validation(analyse, resultats, nom_projet, meta):
    besoin  = analyse.get("besoin", "")
    memoire = charger_memoire()
    if nom_projet not in memoire["projets"]:
        memoire["projets"].append(nom_projet)
    memoire["decisions"].append(f"Brief validé : {nom_projet}")
    memoire["historique"].append({
        "date":    datetime.datetime.now().isoformat(),
        "message": f"Analyse conversation → {nom_projet}",
        "agent":   "Analyse Client"
    })
    memoire.setdefault("projets_content", {})[nom_projet] = {
        "brief":     besoin,
        "roadmap":   resultats.get("projet", ""),
        "specs":     resultats.get("dev", ""),
        "marketing": resultats.get("marketing", ""),
        "email":     resultats.get("communication", ""),
    }
    sauvegarder_memoire(memoire)

    meta_projet = {
        "client":         meta["client_nom"] or "—",
        "budget":         meta["budget"],
        "delai":          meta["delai"],
        "type_extension": meta["type_ext"] or "—",
        "date_livraison": meta["date_livraison"],
    }

    def _sync_notion():
        try:
            notion_sync_projet(nom_projet, "brief", besoin, meta_projet)
            notion_sync_projet(nom_projet, "roadmap", resultats.get("projet", ""), meta_projet)
            notion_sync_projet(nom_projet, "specs",   resultats.get("dev", ""),    meta_projet)
        except Exception:
            pass
    threading.Thread(target=_sync_notion, daemon=True).start()


# ── Route 1 : initialise une validation (calcul nom_projet + tasks) ──

@app.route("/valider-conversation/init", methods=["POST"])
def valider_conversation_init():
    data    = request.json or {}
    analyse = data.get("analyse", {})
    if not analyse:
        return jsonify({"erreur": "Analyse manquante"}), 400
    besoin, contexte = _construire_contexte_brief(analyse)
    tasks            = _construire_tasks(analyse, contexte)
    meta             = _calculer_meta_projet(analyse, besoin)
    return jsonify({"nom_projet": meta["nom_projet"], "tasks": tasks})


# ── Helpers email ────────────────────────────────────────

def _parser_email_agent(texte):
    """Extrait sujet et corps d'une réponse texte de l'agent Communication."""
    import re
    sujet = ""
    corps = texte.strip()
    m = re.search(r'^(?:SUJET|Sujet|Objet|Subject)\s*:\s*(.+)$', texte, re.MULTILINE)
    if m:
        sujet = m.group(1).strip()
        idx   = texte.find(m.group(0))
        rest  = texte[idx + len(m.group(0)):].strip()
        rest  = re.sub(r'^(?:CORPS|Corps|Body)\s*:\s*', '', rest, flags=re.IGNORECASE).strip()
        corps = rest
    return sujet, corps


# ── Route 2 : exécute un seul agent (appelé 4 fois par le frontend) ──

@app.route("/valider-conversation/run-agent", methods=["POST"])
def valider_conversation_run_agent():
    data     = request.json or {}
    agent_id = data.get("agent_id", "")
    message  = data.get("message", "")
    if agent_id not in AGENTS or not message:
        return jsonify({"erreur": "agent_id ou message manquant"}), 400
    try:
        texte, _ = appeler_agent(agent_id, message, max_tokens=1200)
    except Exception as e:
        texte = f"❌ Erreur agent {agent_id} : {e}"

    reponse = {"agent_id": agent_id, "texte": texte}
    if agent_id == "communication":
        sujet, corps = _parser_email_agent(texte)
        reponse["email_sujet"] = sujet
        reponse["email_corps"] = corps
    return jsonify(reponse)


# ── Route : envoi email avec validation humaine explicite ──

@app.route("/envoyer-email-valide", methods=["POST"])
def envoyer_email_valide():
    import re as _re
    data         = request.json or {}
    destinataire = (data.get("destinataire") or "").strip()
    sujet        = (data.get("sujet") or "").strip()
    corps        = (data.get("corps") or "").strip()

    if not destinataire or not sujet or not corps:
        return jsonify({"ok": False, "erreur": "Destinataire, sujet et corps sont requis"}), 400

    if not _re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', destinataire):
        return jsonify({"ok": False, "erreur": f"Adresse email invalide : {destinataire}"}), 400

    try:
        resultat = gmail_envoyer(destinataire, sujet, corps)
        ok = resultat.startswith("✅")
        return jsonify({"ok": ok, "message": resultat})
    except Exception as e:
        return jsonify({"ok": False, "erreur": f"Erreur lors de l'envoi : {e}"}), 500


# ── Route 3 : sauvegarde les 4 résultats dans memoire + Notion ──

@app.route("/valider-conversation/save", methods=["POST"])
def valider_conversation_save():
    data       = request.json or {}
    analyse    = data.get("analyse", {})
    resultats  = data.get("resultats", {})
    nom_projet = data.get("nom_projet", "")
    if not analyse or not nom_projet:
        return jsonify({"erreur": "Données manquantes"}), 400
    besoin = analyse.get("besoin", "")
    meta   = _calculer_meta_projet(analyse, besoin)
    meta["nom_projet"] = nom_projet
    _sauvegarder_resultats_validation(analyse, resultats, nom_projet, meta)
    return jsonify({"projet": nom_projet, "ok": True})


# ── Route legacy : conservée pour compatibilité, appels séquentiels ──

@app.route("/valider-conversation", methods=["POST"])
def valider_conversation():
    data    = request.json or {}
    analyse = data.get("analyse", {})
    if not analyse:
        return jsonify({"erreur": "Analyse manquante"}), 400

    besoin, contexte = _construire_contexte_brief(analyse)
    tasks            = _construire_tasks(analyse, contexte)

    # Appels séquentiels — 1 thread, 1 appel API à la fois
    resultats = {}
    for agent_id, message in tasks.items():
        try:
            texte, _ = appeler_agent(agent_id, message, max_tokens=1200)
            resultats[agent_id] = texte
        except Exception as e:
            resultats[agent_id] = f"❌ Erreur : {e}"

    meta = _calculer_meta_projet(analyse, besoin)
    _sauvegarder_resultats_validation(analyse, resultats, meta["nom_projet"], meta)

    return jsonify({
        "roadmap":         resultats.get("projet", ""),
        "specs":           resultats.get("dev", ""),
        "brief_marketing": resultats.get("marketing", ""),
        "email_client":    resultats.get("communication", ""),
        "projet":          meta["nom_projet"],
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
    # Sync devis dans Notion en arrière-plan
    contenu_devis = (
        f"Client : {client_nom}\nProjet : {projet}\nDélai : {delai}\n"
        f"Prix total : {prix_total} €\n\nPrestations :\n"
        + "\n".join(
            f"• {p.get('description','')}: {p.get('prix','')} €"
            if isinstance(p, dict) else f"• {p}"
            for p in prestations
        )
    )
    threading.Thread(target=notion_sync_projet,
                     args=(client_nom or "Client", "devis", contenu_devis), daemon=True).start()
    buf_copy = io.BytesIO(buf.getvalue())
    return send_file(buf_copy, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.route("/devis/download/<filename>")
def telecharger_devis(filename):
    filename = os.path.basename(filename)
    path = os.path.join(DEVIS_DIR, filename)
    if not os.path.exists(path):
        return "Fichier introuvable", 404
    return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.route("/agent/status", methods=["GET"])
def agent_status():
    memoire = charger_memoire()
    executions = memoire.get("agent_executions", [])

    jobs_info = []
    for job in scheduler.get_jobs():
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        meta = AGENT_TASKS_META.get(job.id, {})
        # Trouver la dernière exécution
        derniere = next((e for e in reversed(executions) if e["task"] == job.id), None)
        jobs_info.append({
            "id": job.id,
            "nom": meta.get("nom", job.id),
            "frequence": meta.get("frequence", ""),
            "prochaine_exec": next_run,
            "derniere_exec": derniere.get("date") if derniere else None,
            "dernier_statut": derniere.get("statut") if derniere else "jamais exécuté",
        })

    return jsonify({
        "scheduler_actif": scheduler.running,
        "taches": jobs_info,
        "historique_recent": list(reversed(executions[-10:])),
    })


@app.route("/agent/run/<task_name>", methods=["POST"])
def agent_run(task_name):
    taches_map = {
        "veille_app_store":      veille_app_store,
        "rapport_boutiques":     rapport_boutiques,
        "alerte_stock":          alerte_stock,
        "analyse_avis_negatifs": analyse_avis_negatifs,
    }
    if task_name not in taches_map:
        return jsonify({"erreur": f"Tâche inconnue : {task_name}"}), 404
    try:
        taches_map[task_name]()
        memoire = charger_memoire()
        executions = memoire.get("agent_executions", [])
        derniere = next((e for e in reversed(executions) if e["task"] == task_name), None)
        return jsonify({"ok": True, "statut": derniere.get("statut", "exécuté") if derniere else "exécuté"})
    except Exception as e:
        return jsonify({"erreur": str(e)}), 500


# ── API Projets ───────────────────────────────────────────

@app.route("/projets-data")
def projets_data():
    memoire    = charger_memoire()
    meta_dict  = memoire.get("projets_meta", {})
    phases_dict = memoire.get("phases", {})

    seen, projets = set(), []
    for p in reversed(memoire.get("projets", [])):
        if not p or p == "null" or len(p.strip()) < 3:
            continue
        key = p.strip().lower()
        if key not in seen:
            seen.add(key)
            projets.append(p.strip())
    projets.reverse()

    _phase_labels = ["Specs & Design", "Développement", "Tests", "Publication"]
    result = []
    for nom in projets:
        meta    = meta_dict.get(nom, {})
        phases  = phases_dict.get(nom, {})
        checked = sum(1 for k in ["phase_1","phase_2","phase_3","phase_4"] if phases.get(k))
        pct     = int(checked / 4 * 100)
        phase_actuelle = f"Phase {checked+1} — {_phase_labels[checked]}" if checked < 4 else "Terminé"
        result.append({
            "nom": nom,
            "client":         meta.get("client", "—"),
            "budget":         meta.get("budget", "—"),
            "delai":          meta.get("delai", "—"),
            "type_extension": meta.get("type_extension", "—"),
            "date_livraison": meta.get("date_livraison", "—"),
            "phases":         phases,
            "progression":    pct,
            "phase_actuelle": phase_actuelle,
            "has_meta":       bool(meta),
        })
    return jsonify(result)


@app.route("/projet-data/<path:nom_projet>")
def projet_data(nom_projet):
    nom     = urllib.parse.unquote(nom_projet)
    memoire = charger_memoire()
    meta    = memoire.get("projets_meta", {}).get(nom, {})
    content = memoire.get("projets_content", {}).get(nom, {})
    if not content and notion:
        content = _backfill_content_from_notion(nom)
    phases  = memoire.get("phases", {}).get(nom, {})

    _labels = [
        "Phase 1 — Specs & Design",
        "Phase 2 — Développement",
        "Phase 3 — Tests",
        "Phase 4 — Publication App Store",
    ]
    checked = sum(1 for k in ["phase_1","phase_2","phase_3","phase_4"] if phases.get(k))
    pct     = int(checked / 4 * 100)
    phase_actuelle = _labels[checked] if checked < 4 else "Projet terminé"

    date_creation = None
    for h in memoire.get("historique", []):
        if nom in h.get("message", ""):
            date_creation = h.get("date", "")[:10]
            break

    return jsonify({
        "nom":           nom,
        "meta":          meta,
        "content":       content,
        "phases":        phases,
        "phase_labels":  _labels,
        "progression":   pct,
        "phase_actuelle": phase_actuelle,
        "date_creation": date_creation,
    })


@app.route("/projet/<path:nom_projet>/phase", methods=["POST"])
def toggle_projet_phase(nom_projet):
    nom       = urllib.parse.unquote(nom_projet)
    data      = request.json
    phase_key = data.get("phase")
    checked   = data.get("checked", False)
    if not phase_key:
        return jsonify({"erreur": "phase manquante"}), 400
    memoire = charger_memoire()
    memoire.setdefault("phases", {}).setdefault(nom, {})[phase_key] = checked
    sauvegarder_memoire(memoire)
    return jsonify({"ok": True})


@app.route("/projet/<path:nom_projet>/chat", methods=["POST"])
def projet_chat(nom_projet):
    nom     = urllib.parse.unquote(nom_projet)
    data    = request.json
    message = data.get("message", "")
    if not message:
        return jsonify({"erreur": "message vide"}), 400

    memoire = charger_memoire()
    meta    = memoire.get("projets_meta", {}).get(nom, {})
    content = memoire.get("projets_content", {}).get(nom, {})

    contexte = (
        f"CONTEXTE PROJET ACTIF : {nom}\n"
        f"Client : {meta.get('client','—')}\n"
        f"Type : {meta.get('type_extension','—')}\n"
        f"Budget : {meta.get('budget','—')} · Délai : {meta.get('delai','—')}\n"
    )
    if content.get("brief"):
        contexte += f"\nBrief : {content['brief'][:600]}"
    if content.get("roadmap"):
        contexte += f"\nRoadmap : {content['roadmap'][:400]}"

    agent_id = choisir_agent(message)
    if agent_id == "tous":
        reponse   = appeler_tous_les_agents(message, contexte)
        agent_nom = "Synthèse multi-agents"
        actions   = []
    else:
        reponse, actions = appeler_agent(agent_id, message, contexte, nom_projet_ctx=nom)
        agent_nom = AGENTS[agent_id]["nom"]

    # Sauvegarde dans projets_content[nom]["historique"]
    entree_hist = f"[{datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}] Q: {message}\nR ({agent_nom}): {reponse[:2000]}"
    try:
        mem = charger_memoire()
        pc  = mem.setdefault("projets_content", {}).setdefault(nom, {})
        ancien = pc.get("historique", "")
        pc["historique"] = (ancien + "\n\n" + entree_hist).strip()
        sauvegarder_memoire(mem)
    except Exception:
        pass

    threading.Thread(
        target=notion_sync_projet,
        args=(nom, "historique", f"Q: {message}\nR ({agent_nom}): {reponse[:1500]}"),
        daemon=True
    ).start()

    return jsonify({"reponse": reponse, "agent": agent_nom, "actions": actions})


@app.route("/projet/<path:nom_projet>/notion-sync", methods=["POST"])
def projet_notion_sync(nom_projet):
    nom     = urllib.parse.unquote(nom_projet)
    memoire = charger_memoire()
    meta    = memoire.get("projets_meta", {}).get(nom, {})
    content = memoire.get("projets_content", {}).get(nom, {})

    resultats_sync = []
    if content.get("brief"):
        resultats_sync.append(notion_sync_projet(nom, "brief", content["brief"], meta))
    if content.get("roadmap"):
        resultats_sync.append(notion_sync_projet(nom, "roadmap", content["roadmap"], meta))
    if content.get("specs"):
        resultats_sync.append(notion_sync_projet(nom, "specs", content["specs"], meta))
    if not resultats_sync:
        resultats_sync.append(notion_sync_projet(nom, "historique", "Sync manuel", meta))

    return jsonify({"ok": True, "resultats": resultats_sync})


# ── Mini boîte mail projet ────────────────────────────────

def _charger_emails_projet(nom):
    """Charge la liste emails d'un projet, avec migration auto depuis l'ancien format texte."""
    memoire = charger_memoire()
    content = memoire.get("projets_content", {}).get(nom, {})
    if "email" in content and "emails" not in content:
        old_email = content.pop("email", "")
        content["emails"] = [{
            "id":           str(uuid.uuid4()),
            "sujet":        "Email de confirmation",
            "corps":        old_email,
            "destinataire": "",
            "date":         datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "statut":       "envoye",
        }] if old_email else []
        memoire.setdefault("projets_content", {})[nom] = content
        sauvegarder_memoire(memoire)
    return content.get("emails", [])


def _sauvegarder_email_projet(nom, email_item):
    """Ajoute un email dans la liste du projet (avec migration auto si nécessaire)."""
    memoire = charger_memoire()
    pc = memoire.setdefault("projets_content", {}).setdefault(nom, {})
    if "email" in pc and "emails" not in pc:
        old = pc.pop("email", "")
        pc["emails"] = [{
            "id": str(uuid.uuid4()), "sujet": "Email de confirmation",
            "corps": old, "destinataire": "",
            "date": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "statut": "envoye",
        }] if old else []
    pc.setdefault("emails", []).append(email_item)
    sauvegarder_memoire(memoire)


@app.route("/projet/<path:nom_projet>/emails", methods=["GET"])
def projet_emails_liste(nom_projet):
    nom = urllib.parse.unquote(nom_projet)
    emails = _charger_emails_projet(nom)
    return jsonify(emails)


@app.route("/projet/<path:nom_projet>/emails/envoyer", methods=["POST"])
def projet_emails_envoyer(nom_projet):
    nom  = urllib.parse.unquote(nom_projet)
    data = request.json or {}
    dest  = (data.get("destinataire") or "").strip()
    sujet = (data.get("sujet") or "").strip()
    corps = (data.get("corps") or "").strip()

    if not dest or not sujet or not corps:
        return jsonify({"succes": False, "message": "Destinataire, sujet et corps sont requis"}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', dest):
        return jsonify({"succes": False, "message": f"Adresse email invalide : {dest}"}), 400

    try:
        resultat = gmail_envoyer(dest, sujet, corps)
    except Exception as e:
        return jsonify({"succes": False, "message": f"Erreur Gmail : {e}"}), 500

    if not resultat.startswith("✅"):
        return jsonify({"succes": False, "message": resultat}), 500

    email_item = {
        "id":           str(uuid.uuid4()),
        "sujet":        sujet,
        "corps":        corps,
        "destinataire": dest,
        "date":         datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "statut":       "envoye",
    }
    _sauvegarder_email_projet(nom, email_item)
    contenu_notion = f"📧 Envoyé à {dest}\nSujet : {sujet}\n\n{corps}"
    threading.Thread(
        target=notion_sync_projet,
        args=(nom, "email", contenu_notion),
        daemon=True
    ).start()
    return jsonify({"succes": True, "message": resultat})


@app.route("/projet/<path:nom_projet>/emails/brouillon", methods=["POST"])
def projet_emails_brouillon(nom_projet):
    nom  = urllib.parse.unquote(nom_projet)
    data = request.json or {}
    email_item = {
        "id":           str(uuid.uuid4()),
        "sujet":        (data.get("sujet") or "(sans sujet)").strip(),
        "corps":        (data.get("corps") or "").strip(),
        "destinataire": (data.get("destinataire") or "").strip(),
        "date":         datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "statut":       "brouillon",
    }
    _sauvegarder_email_projet(nom, email_item)
    return jsonify({"succes": True, "id_brouillon": email_item["id"]})


@app.route("/projet/<path:nom_projet>/emails/recu", methods=["POST"])
def projet_emails_recu(nom_projet):
    nom  = urllib.parse.unquote(nom_projet)
    data = request.json or {}
    email_item = {
        "id":           str(uuid.uuid4()),
        "sujet":        (data.get("sujet") or "(sans sujet)").strip(),
        "corps":        (data.get("corps") or "").strip(),
        "destinataire": (data.get("expediteur") or "").strip(),
        "date":         (data.get("date") or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")).strip(),
        "statut":       "recu",
    }
    _sauvegarder_email_projet(nom, email_item)
    return jsonify({"succes": True})


@app.route("/projet/<path:nom_projet>/emails/rediger-ia", methods=["POST"])
def projet_emails_rediger_ia(nom_projet):
    nom  = urllib.parse.unquote(nom_projet)
    data = request.json or {}
    contexte_utilisateur = (data.get("contexte") or "").strip()
    if not contexte_utilisateur:
        return jsonify({"erreur": "contexte manquant"}), 400

    memoire = charger_memoire()
    meta    = memoire.get("projets_meta", {}).get(nom, {})
    content = memoire.get("projets_content", {}).get(nom, {})
    contexte_projet = (
        f"CONTEXTE PROJET : {nom}\n"
        f"Client : {meta.get('client','—')}\n"
        f"Type : {meta.get('type_extension','—')}\n"
        f"Budget : {meta.get('budget','—')} · Délai : {meta.get('delai','—')}\n"
    )
    if content.get("brief"):
        contexte_projet += f"\nBrief : {content['brief'][:600]}"

    message = f"{contexte_projet}\n\nDemande : {contexte_utilisateur}"
    try:
        texte, _ = appeler_agent("communication", message, max_tokens=1200)
    except Exception as e:
        return jsonify({"erreur": f"Erreur agent : {e}"}), 500

    sujet, corps = _parser_email_agent(texte)
    return jsonify({"sujet": sujet, "corps": corps})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
