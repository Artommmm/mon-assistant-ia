from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq()

# ── Agents ────────────────────────────────────────────────
AGENTS = {
    "dev": {
        "nom": "Dev",
        "prompt": "Tu es un expert en développement logiciel. Tu aides à écrire du code, concevoir des architectures, déboguer des problèmes. Tu donnes des exemples de code concrets. Tu réponds toujours en français."
    },
    "communication": {
        "nom": "Communication",
        "prompt": "Tu es un expert en communication professionnelle. Tu rédiges des emails, messages, et réponses clairs et efficaces. Tu adaptes le ton selon le contexte. Tu réponds toujours en français."
    },
    "marketing": {
        "nom": "Marketing",
        "prompt": "Tu es un expert en marketing et création de contenu. Tu aides à définir des stratégies, rédiger des posts, slogans, descriptions. Tu réponds toujours en français."
    },
    "recherche": {
        "nom": "Recherche",
        "prompt": "Tu es un expert en analyse et synthèse d'informations. Tu structures les idées, compares les options, fournis des résumés utiles. Tu réponds toujours en français."
    },
    "projet": {
        "nom": "Projet",
        "prompt": "Tu es un expert en gestion de projet. Tu aides à organiser les tâches, créer des roadmaps, prioriser les actions. Tu réponds toujours en français."
    }
}

# ── Orchestrateur ─────────────────────────────────────────
def choisir_agent(message_utilisateur):
    """Demande à l'IA quel agent est le plus adapté."""
    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """Tu es un routeur d'agents IA. 
Ton seul rôle est de lire le message de l'utilisateur et de répondre avec UN SEUL MOT parmi : dev, communication, marketing, recherche, projet.

Règles :
- dev → code, programmation, bug, architecture, base de données
- communication → email, message, lettre, réponse, rédaction
- marketing → slogan, contenu, réseaux sociaux, branding, stratégie
- recherche → comparaison, analyse, résumé, information, qu'est-ce que
- projet → tâche, planning, roadmap, organisation, priorité

Réponds UNIQUEMENT avec le mot clé, rien d'autre."""
            },
            {
                "role": "user",
                "content": message_utilisateur
            }
        ]
    )
    agent_id = reponse.choices[0].message.content.strip().lower()

    # Sécurité : si la réponse n'est pas valide, on utilise "recherche" par défaut
    if agent_id not in AGENTS:
        agent_id = "recherche"

    return agent_id

def appeler_agent(agent_id, message, historique):
    """Appelle l'agent choisi avec l'historique de conversation."""
    agent = AGENTS[agent_id]

    messages = [{"role": "system", "content": agent["prompt"]}] + historique + [{"role": "user", "content": message}]

    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages
    )
    return reponse.choices[0].message.content

# ── Boucle principale ─────────────────────────────────────
historique = []

print("╔════════════════════════════════╗")
print("║     Ton assistant IA personnel  ║")
print("║     Tape 'quitter' pour stop    ║")
print("╚════════════════════════════════╝\n")

while True:
    user_input = input("Toi : ").strip()

    if not user_input:
        continue

    if user_input.lower() == "quitter":
        print("Au revoir !")
        break

    # 1. L'orchestrateur choisit l'agent
    agent_id = choisir_agent(user_input)
    agent_nom = AGENTS[agent_id]["nom"]

    print(f"\n[→ Agent {agent_nom} activé]\n")

    # 2. L'agent répond
    reponse = appeler_agent(agent_id, user_input, historique)

    # 3. On met à jour l'historique
    historique.append({"role": "user", "content": user_input})
    historique.append({"role": "assistant", "content": reponse})

    print(f"Assistant ({agent_nom}) : {reponse}\n")