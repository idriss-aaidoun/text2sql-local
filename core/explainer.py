"""
core/explainer.py
=================
Couche 5 — Partie B : Explication pédagogique

Rôle : Prendre le SQL validé et généré, et produire une explication
en français simple compréhensible par un utilisateur non-technique.

Pourquoi cette couche est importante ?
  L'objectif du projet est de démocratiser l'accès aux données.
  Si on affiche juste le SQL à l'utilisateur métier, on n'a résolu
  qu'à moitié le problème — il ne comprend toujours pas ce qui se passe.

  L'explication pédagogique ferme la boucle :
    Utilisateur : "quels clients ont commandé plus de 3 fois ?"
    SQL généré  : SELECT c.nom, COUNT(cmd.id) as nb ...
    Explication : "Cette requête affiche les clients qui ont passé
                   plus de 3 commandes, avec leur nombre de commandes."

Température 0.3 (vs 0.0 pour la génération SQL) :
  Pour le SQL on veut 0.0 — déterministe, pas de créativité.
  Pour l'explication on peut se permettre 0.3 — légèrement plus
  naturel et varié dans les formulations.
"""

import os
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser

from prompts.explanation import PROMPT_EXPLICATION


class SQLExplainer:
    """
    Génère des explications pédagogiques en français pour les requêtes SQL.

    Utilise Llama 3.1 avec une température légèrement supérieure à 0
    pour produire des explications naturelles et variées.

    Utilisation :
        explainer = SQLExplainer()
        explication = explainer.expliquer(
            "SELECT * FROM clients WHERE ville = 'Paris';"
        )
        # → "Cette requête récupère tous les clients qui habitent à Paris."
    """

    def __init__(
        self,
        model: str = "llama3.1",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.3,
        num_ctx: int = 2048,
    ) -> None:
        """
        Args:
            model       : modèle Ollama (même que Couche 3)
            base_url    : adresse du serveur Ollama
            temperature : 0.3 = légèrement créatif pour les explications
            num_ctx     : 2048 suffisent pour l'explication (prompt court)
        """
        self.llm = ChatOllama(
            model=model,
            temperature=temperature,
            base_url=base_url,
            num_ctx=num_ctx,
        )
        self.parser = StrOutputParser()
        self.chain = PROMPT_EXPLICATION | self.llm | self.parser

    def expliquer(self, sql: str) -> str:
        """
        Génère une explication en français simple du SQL fourni.

        Args:
            sql : requête SQL validée à expliquer

        Returns:
            Explication en 2-3 phrases compréhensibles par un non-technicien.
            En cas d'erreur Ollama, retourne un message de fallback.
        """
        try:
            explication = self.chain.invoke({"sql": sql})
            return explication.strip()
        except Exception as e:
            # Fallback : ne pas bloquer l'interface si l'explication échoue
            return (
                f"La requête a été exécutée avec succès. "
                f"(Explication indisponible : {type(e).__name__})"
            )

    def expliquer_avec_contexte(self, sql: str, question: str) -> str:
        """
        Version enrichie : prend aussi la question originale en compte
        pour une explication encore plus pertinente.

        Utilise un prompt légèrement différent qui relie la question
        utilisateur au SQL généré.

        Args:
            sql      : requête SQL à expliquer
            question : question originale de l'utilisateur

        Returns:
            Explication contextualisée en français simple
        """
        from langchain_core.prompts import ChatPromptTemplate

        prompt_contextuel = ChatPromptTemplate.from_messages([
            (
                "system",
                """Tu es un assistant pédagogique. Un utilisateur a posé une question
en langage naturel et une requête SQL a été générée automatiquement.
Explique en 2-3 phrases simples ce que fait cette requête et comment
elle répond à la question. Évite le jargon SQL.""",
            ),
            (
                "human",
                """Question de l'utilisateur : {question}

Requête SQL générée :
{sql}

Explication simple :""",
            ),
        ])

        chain_contextuelle = prompt_contextuel | self.llm | self.parser

        try:
            return chain_contextuelle.invoke({
                "question": question,
                "sql": sql,
            }).strip()
        except Exception as e:
            return (
                f"La requête a été exécutée avec succès. "
                f"(Explication indisponible : {type(e).__name__})"
            )