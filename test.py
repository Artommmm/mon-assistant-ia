from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq()

# Définition des agents
AGENTS = {
    "dev": {
        "nom": "Dev",
        "prompt": "Tu es un expert en développement logiciel. Tu aides à écrire du code, concevoir des architectures, déboguer des problèmes. Tu donnes des exemples de code concrets. Tu réponds toujours en français."
    },
    "communication": {
        "nom": "Communication",
        "prompt": "Tu es un expert en communication professionnelle. Tu rédiges des emails, messages, et réponses clairs et efficaces. Tu adaptes le ton selon le contexte (formel, décontracté). Tu réponds toujours en français."
    },
    "marketing": {
        "nom": "Marketing",
        "prompt": "Tu es un expert en marketing et création de contenu. Tu aides à définir des stratégies, rédiger des posts, des slogans, des descriptions de produits. Tu réponds toujours en français."
    },
    "recherche": {
        "nom": "Recherche",
        "prompt": "Tu es un expert en analyse et synthèse d'informations. Tu structures les idées clairement, compares les options, et fournis des résumés utiles. Tu réponds toujours en français."
    },
    "projet": {
        "nom": "Projet",
        "prompt": "Tu es un expert en gestion de projet. Tu aides à organiser les tâches, créer des roadmaps, prioriser les actions et suivre l'avancement. Tu réponds toujours en français."
    }
}

def appeler_agent(agent_id, message):
    agent = AGENTS[agent_id]
    reponse = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": agent["prompt"]},
            {"role": "user", "content": message}
        ]
    )
    return reponse.choices[0].message.content

# Test des agents
print("=== TEST DES AGENTS ===\n")

print(">>> Agent DEV :")
print(appeler_agent("dev", "Comment créer une fonction Python qui calcule la moyenne d'une liste ?"))
print()

print(">>> Agent COMMUNICATION :")
print(appeler_agent("communication", "Rédige un email pour demander un délai supplémentaire à un client."))
print()

print(">>> Agent MARKETING :")
print(appeler_agent("marketing", "Donne-moi 3 slogans pour une app de gestion de tâches."))
print()