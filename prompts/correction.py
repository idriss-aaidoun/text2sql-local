"""
prompts/correction.py
=====================
Template du prompt de self-correction pour Llama 3.1

Utilisé par la Couche 4 (LangGraph) quand le SQL généré
provoque une erreur à l'exécution.

On envoie à Llama :
  - Le SQL invalide
  - Le message d'erreur exact de la base de données
  - Le schéma pertinent
  - La question originale

Llama doit retourner UNIQUEMENT le SQL corrigé.
"""

from langchain_core.prompts import ChatPromptTemplate

PROMPT_CORRECTION = ChatPromptTemplate.from_messages([
    (
        "system",
        """Tu es un expert SQL. Une requête SQL a échoué avec une erreur.
Analyse l'erreur et corrige la requête.
Retourne UNIQUEMENT le SQL corrigé — aucune explication, aucun commentaire.""",
    ),
    (
        "human",
        """=== SCHÉMA ===
{schema}

=== QUESTION ORIGINALE ===
{question}

=== REQUÊTE INCORRECTE ===
{sql_invalide}

=== MESSAGE D'ERREUR ===
{message_erreur}

SQL corrigé :""",
    ),
])