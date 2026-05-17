"""
prompts/explanation.py
======================
Template du prompt d'explication pédagogique

Utilisé par la Couche 5 pour expliquer en français simple
ce que fait le SQL généré — pour les utilisateurs non-techniques.
"""

from langchain_core.prompts import ChatPromptTemplate

PROMPT_EXPLICATION = ChatPromptTemplate.from_messages([
    (
        "system",
        """Tu es un assistant pédagogique. Explique en français simple
ce que fait une requête SQL, en 2-3 phrases maximum.
Ton explication doit être compréhensible par quelqu'un qui ne connaît pas SQL.
Ne mentionne pas les termes techniques SQL (JOIN, WHERE, GROUP BY...)
sauf si tu les expliques immédiatement.""",
    ),
    (
        "human",
        """Requête SQL :
{sql}

Explication simple :""",
    ),
])