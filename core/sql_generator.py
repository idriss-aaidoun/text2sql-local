"""
core/sql_generator.py
=====================
Couche 3 — Génération SQL avec Llama 3.1

Rôle : Assembler les sorties des Couches 1 et 2 dans un prompt structuré,
l'envoyer à Llama 3.1 via Ollama, et retourner le SQL brut nettoyé.

Flux de données :
  SchemaRetriever.recuperer()    -> schema (str)   [Couche 1]
  FewShotSelector.selectionner() -> exemples (str) [Couche 2]
  Memory.get_historique()        -> historique (str)
        ↓ assemblage dans PROMPT_GENERATION
  Llama 3.1 (via Ollama local)
        ↓ StrOutputParser
  SQL brut nettoyé (sans markdown, sans commentaires)

Concept LCEL (LangChain Expression Language) :
  LangChain permet de chaîner les composants avec l'opérateur |
  comme des pipes Unix :
      prompt | llm | parser
  Chaque composant reçoit la sortie du précédent.
  C'est simple, lisible, et facilement testable composant par composant.
"""

import re
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser

from prompts.generation import PROMPT_GENERATION, PROMPT_GENERATION_SIMPLE


class SQLGenerator:
    """
    Génère du SQL à partir d'une question en langage naturel en utilisant
    Llama 3.1 via Ollama (100% local, 0 € de coût d'inférence).

    Utilisation :
        generator = SQLGenerator()
        sql = generator.generer(
            schema="Table clients : id (INTEGER), nom (TEXT)...",
            exemples="Q: liste les clients\\nSQL: SELECT * FROM clients;",
            historique="",
            question="quels clients habitent à Paris ?"
        )
        # -> "SELECT * FROM clients WHERE ville = 'Paris';"
    """

    def __init__(
        self,
        model: str = "llama3.1",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.0,
        num_ctx: int = 4096,
        num_thread: int = 4,
    ) -> None:
        """
        Args:
            model       : modèle Ollama à utiliser
                          "llama3.1" = llama3.1:8b (défaut)
                          "llama3.1:8b-instruct-q4_0" = version quantifiée 4-bit
                                                        (plus rapide sur CPU)
            base_url    : adresse du serveur Ollama (localhost par défaut)
            temperature : 0.0 = déterministe (toujours le même SQL pour la même question)
                          > 0 = plus créatif mais moins prévisible
                          Pour SQL on veut TOUJOURS 0.0
            num_ctx     : taille de la fenêtre de contexte en tokens
                          4096 = compromis qualité/vitesse sur CPU
                          2048 = plus rapide si la machine est lente
            num_thread  : nombre de threads CPU pour l'inférence
                          Mettre le nombre de cœurs physiques de la machine
        """
        # ChatOllama = connecteur LangChain -> serveur Ollama local
        # Il envoie des requêtes HTTP à http://localhost:11434
        self.llm = ChatOllama(
            model=model,
            temperature=temperature,
            base_url=base_url,
            num_ctx=num_ctx,
            num_thread=num_thread,
        )

        # StrOutputParser extrait le texte brut de la réponse du LLM
        # Sans lui, on recevrait un objet AIMessage avec des métadonnées
        self.parser = StrOutputParser()

        # La chaîne LCEL : prompt -> llm -> parser
        # L'opérateur | est surchargé par LangChain pour créer des pipelines
        self.chain = PROMPT_GENERATION | self.llm | self.parser
        self.chain_simple = PROMPT_GENERATION_SIMPLE | self.llm | self.parser

    def generer(
        self,
        schema: str,
        exemples: str,
        question: str,
        historique: str = "",
    ) -> str:
        """
        Génère une requête SQL à partir des inputs des couches 1 et 2.

        Args:
            schema     : tables pertinentes (sortie Couche 1)
            exemples   : exemples few-shot (sortie Couche 2)
            question   : question de l'utilisateur
            historique : résumé des échanges précédents (pour multi-tours)

        Returns:
            SQL brut nettoyé, prêt pour validation et exécution

        Raises:
            ConnectionError : si Ollama n'est pas démarré
            Exception       : si Llama retourne une réponse vide
        """
        brut = self.chain.invoke({
            "schema": schema,
            "exemples": exemples,
            "historique": historique if historique else "Aucun historique.",
            "question": question,
        })

        return self._nettoyer_sql(brut)

    def generer_simple(self, schema: str, exemples: str, question: str) -> str:
        """
        Version simplifiée sans historique — utilisée pour les tests
        et les scénarios single-turn.
        """
        brut = self.chain_simple.invoke({
            "schema": schema,
            "exemples": exemples,
            "question": question,
        })
        return self._nettoyer_sql(brut)

    def _nettoyer_sql(self, texte_brut: str) -> str:
        """
        Nettoie la sortie brute de Llama pour extraire le SQL pur.

        Llama 3.1 a tendance à envelopper sa réponse dans des balises
        markdown (```sql ... ```) ou à ajouter des commentaires.
        Cette méthode les supprime systématiquement.

        Exemples de sortie brute typique de Llama :
            "```sql\nSELECT * FROM clients;\n```"
            "Voici la requête :\n\nSELECT * FROM clients;"
            "SELECT * FROM clients; -- liste tous les clients"

        Args:
            texte_brut : sortie directe du LLM

        Returns:
            SQL brut propre, ex: "SELECT * FROM clients;"
        """
        sql = texte_brut.strip()

        # Supprimer les blocs markdown ```sql ... ``` ou ``` ... ```
        sql = re.sub(r"```sql\s*", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"```\s*", "", sql)

        # Supprimer les phrases d'introduction que Llama ajoute parfois
        # ex: "Voici la requête SQL :\n\nSELECT..."
        patterns_intro = [
            r"^[Vv]oici\s+(?:la\s+)?requête\s*(?:SQL)?\s*:\s*",
            r"^[Hh]ere\s+is\s+the\s+SQL\s*:\s*",
            r"^SQL\s*:\s*",
            r"^Requête\s*:\s*",
        ]
        for pattern in patterns_intro:
            sql = re.sub(pattern, "", sql, flags=re.MULTILINE)

        # Supprimer les commentaires SQL inline (-- commentaire)
        # ATTENTION : ne pas supprimer les -- dans les strings SQL
        sql = re.sub(r"--[^\n]*", "", sql)

        # Nettoyer les lignes vides multiples
        sql = re.sub(r"\n\s*\n", "\n", sql)

        return sql.strip()

    def tester_connexion_ollama(self) -> bool:
        """
        Vérifie qu'Ollama est démarré et accessible.

        Returns:
            True si Ollama répond, False sinon
        """
        try:
            # Envoyer un prompt minimal pour tester la connexion
            test_chain = PROMPT_GENERATION_SIMPLE | self.llm | self.parser
            test_chain.invoke({
                "schema": "Table test : id INTEGER",
                "exemples": "",
                "question": "SELECT 1",
            })
            return True
        except Exception:
            return False