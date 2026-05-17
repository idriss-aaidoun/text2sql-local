"""
prompts/generation.py
=====================
Template du prompt de génération SQL pour Llama 3.1

Rôle : Définir EXACTEMENT le texte envoyé à Llama pour générer le SQL.

Pourquoi c'est un fichier séparé ?
  Le prompt est le "cerveau" du système — une modification ici impacte
  toute la qualité des requêtes générées. Le séparer du code permet de
  l'itérer indépendamment sans toucher à la logique Python.

Spécificités Llama 3.1 vs GPT-4o (cf. cahier des charges section 7.1) :
  - Garder le prompt <= 2048 tokens
  - Utiliser des séparateurs === explicites
  - Insister sur "SQL brut uniquement" — Llama a tendance à commenter
  - 2-3 exemples max pour ne pas saturer la fenêtre de contexte
  - Rester cohérent sur la langue (on choisit le français)
"""

from langchain_core.prompts import ChatPromptTemplate

# ── Template principal de génération ─────────────────────────────────────────
# ChatPromptTemplate.from_messages prend une liste de tuples (rôle, contenu).
# "system" = instructions permanentes du comportement du LLM
# "human"  = le message de l'utilisateur (avec les variables injectées)

PROMPT_GENERATION = ChatPromptTemplate.from_messages([
    (
        "system",
        """Tu es un expert SQL spécialisé dans la génération de requêtes SELECT.

RÈGLES ABSOLUES :
1. Retourne UNIQUEMENT le SQL brut — aucun markdown, aucune explication, aucun commentaire
2. Génère EXCLUSIVEMENT des requêtes SELECT — jamais de INSERT, UPDATE, DELETE, DROP
3. Utilise UNIQUEMENT les tables et colonnes listées dans le schéma fourni
4. Si la question est ambiguë, génère la requête la plus probable
5. Termine toujours la requête par un point-virgule""",
    ),
    (
        "human",
        """=== SCHÉMA DES TABLES PERTINENTES ===
{schema}

=== EXEMPLES DE RÉFÉRENCE ===
{exemples}

=== HISTORIQUE DE LA CONVERSATION ===
{historique}

=== QUESTION ===
{question}

SQL :""",
    ),
])


# ── Template simplifié (sans historique, pour les tests) ─────────────────────

PROMPT_GENERATION_SIMPLE = ChatPromptTemplate.from_messages([
    (
        "system",
        """Tu es un expert SQL. Génère uniquement des requêtes SELECT.
Retourne UNIQUEMENT le SQL brut sans markdown ni explication.
Utilise exclusivement les tables et colonnes du schéma fourni.""",
    ),
    (
        "human",
        """=== SCHÉMA ===
{schema}

=== EXEMPLES ===
{exemples}

=== QUESTION ===
{question}

SQL :""",
    ),
])