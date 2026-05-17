"""
core/sql_validator.py
=====================
Couche 4 — Self-Correction avec LangGraph

Rôle : Modéliser la boucle de correction comme un graphe d'états.
       Si le SQL échoue, on le renvoie à Llama avec le message d'erreur,
       et on retente jusqu'à MAX_TENTATIVES fois.

Concept LangGraph — Graphe d'états :
  Un graphe d'états = des NOEUDS (fonctions) reliés par des ARÊTES
  (transitions). Chaque noeud reçoit l'état courant, le modifie,
  et retourne le nouvel état. Les arêtes conditionnelles permettent
  de router vers différents noeuds selon l'état.

  État (EtatCorrection) :
    question    : question originale de l'utilisateur
    schema      : schéma pertinent (Couche 1)
    sql         : SQL courant (modifié à chaque correction)
    erreur      : dernière erreur SQL (vide si succès)
    tentatives  : compteur de corrections (0 au départ)
    resultat    : DataFrame résultat (None si pas encore de succès)

  Noeuds :
    executer    : tente d'exécuter le SQL sur la base
    corriger    : demande à Llama de corriger le SQL

  Arêtes conditionnelles depuis "executer" :
    succes      → END          (SQL valide, résultats obtenus)
    corriger    → "corriger"   (SQL invalide, tentatives < MAX)
    abandon     → END          (SQL invalide, tentatives >= MAX)

  Arête fixe :
    "corriger"  → "executer"   (toujours, pour réessayer)

Flux complet :
  START
    ↓
  [executer] ──erreur──→ [corriger] ──→ [executer] ──erreur──→ [corriger]...
      ↓ succès                                ↓ abandon (3 essais)
     END                                     END
"""

import os
from typing import TypedDict, Optional

import pandas as pd
from langgraph.graph import StateGraph, END
from langchain_ollama import ChatOllama
from langchain_core.output_parsers import StrOutputParser

from prompts.correction import PROMPT_CORRECTION
from database.executor import SQLExecutor, ResultatExecution


# ── État du graphe ────────────────────────────────────────────────────────────
# TypedDict définit la structure de l'état partagé entre tous les noeuds.
# Chaque noeud reçoit l'état complet et retourne un dict avec les clés modifiées.

class EtatCorrection(TypedDict):
    """
    État partagé entre les noeuds du graphe LangGraph.

    Toutes les clés sont optionnelles sauf question, schema et sql
    qui doivent être présentes dès le début.
    """
    question: str           # question originale (ne change jamais)
    schema: str             # schéma pertinent (ne change jamais)
    sql: str                # SQL courant (modifié à chaque correction)
    erreur: str             # dernière erreur SQL ("" si succès)
    tentatives: int         # nombre de corrections effectuées
    resultat: Optional[str] # résultat sérialisé ("" si pas encore de succès)
    abandon: bool           # True si toutes les tentatives ont échoué


# ── Constante ─────────────────────────────────────────────────────────────────
MAX_TENTATIVES = int(os.getenv("MAX_CORRECTION_ATTEMPTS", "3"))


# ── Noeuds du graphe ─────────────────────────────────────────────────────────

def noeud_executer(etat: EtatCorrection, executor: SQLExecutor) -> dict:
    """
    Noeud 1 : tente d'exécuter le SQL sur la base de données.

    Reçoit l'état courant, exécute etat["sql"], et retourne
    les clés modifiées de l'état (pas l'état complet).

    LangGraph fusionne automatiquement les clés retournées
    avec l'état existant — on ne retourne que ce qui change.
    """
    resultat: ResultatExecution = executor.executer(etat["sql"])

    if resultat.succes:
        # Succès : sérialiser le DataFrame en JSON pour le stocker dans l'état
        # (TypedDict ne supporte pas les types arbitraires comme DataFrame)
        df_json = resultat.donnees.to_json(orient="records", force_ascii=False)
        return {
            "erreur": "",
            "resultat": df_json,
            "abandon": False,
        }
    else:
        # Échec : enregistrer l'erreur pour le noeud de correction
        return {
            "erreur": resultat.erreur,
            "resultat": "",
            "abandon": False,
        }


def noeud_corriger(etat: EtatCorrection, llm: ChatOllama) -> dict:
    """
    Noeud 2 : demande à Llama de corriger le SQL invalide.

    Envoie à Llama :
      - Le SQL qui a échoué
      - Le message d'erreur exact de la base
      - Le schéma pertinent
      - La question originale

    Llama retourne le SQL corrigé.
    On incrémente le compteur de tentatives.
    """
    chain = PROMPT_CORRECTION | llm | StrOutputParser()

    sql_corrige = chain.invoke({
        "schema": etat["schema"],
        "question": etat["question"],
        "sql_invalide": etat["sql"],
        "message_erreur": etat["erreur"],
    })

    # Nettoyer les éventuelles balises markdown (même logique que Couche 3)
    import re
    sql_corrige = re.sub(r"```sql\s*", "", sql_corrige, flags=re.IGNORECASE)
    sql_corrige = re.sub(r"```\s*", "", sql_corrige)
    sql_corrige = sql_corrige.strip()

    print(
        f"  🔄 Tentative {etat['tentatives'] + 1}/{MAX_TENTATIVES} — "
        f"SQL corrigé : {sql_corrige[:80]}..."
    )

    return {
        "sql": sql_corrige,
        "tentatives": etat["tentatives"] + 1,
    }


def decision_apres_execution(etat: EtatCorrection) -> str:
    """
    Arête conditionnelle : décide quoi faire après "executer".

    Retourne une string qui correspond à une clé dans le dict
    conditional_edges de LangGraph.

    Logique :
      - resultat non vide → "succes"  → END
      - tentatives >= MAX → "abandon" → END
      - sinon            → "corriger" → noeud corriger
    """
    if etat["resultat"]:
        return "succes"
    if etat["tentatives"] >= MAX_TENTATIVES:
        print(f"  ❌ Abandon après {MAX_TENTATIVES} tentatives.")
        return "abandon"
    return "corriger"


# ── Construction du graphe ────────────────────────────────────────────────────

def construire_graphe(executor: SQLExecutor, llm: ChatOllama) -> any:
    """
    Construit et compile le graphe LangGraph de self-correction.

    On utilise des lambdas pour injecter executor et llm dans les noeuds
    sans les mettre dans l'état (ils ne changent pas pendant l'exécution).

    Structure du graphe :
        START → executer → (succes → END)
                         → (corriger → corriger → executer → ...)
                         → (abandon → END)

    Args:
        executor : SQLExecutor pour exécuter les requêtes
        llm      : ChatOllama pour corriger les requêtes invalides

    Returns:
        Graphe compilé prêt à être invoqué avec .invoke(etat_initial)
    """
    graphe = StateGraph(EtatCorrection)

    # Ajouter les noeuds
    # Les lambdas capturent executor et llm par closure
    graphe.add_node(
        "executer",
        lambda etat: noeud_executer(etat, executor)
    )
    graphe.add_node(
        "corriger",
        lambda etat: noeud_corriger(etat, llm)
    )

    # Point d'entrée : on commence toujours par exécuter
    graphe.set_entry_point("executer")

    # Arêtes conditionnelles depuis "executer"
    graphe.add_conditional_edges(
        "executer",           # noeud source
        decision_apres_execution,  # fonction de décision
        {
            "succes":   END,        # → terminer
            "corriger": "corriger", # → noeud corriger
            "abandon":  END,        # → terminer (avec erreur)
        }
    )

    # Arête fixe : après correction, toujours réessayer l'exécution
    graphe.add_edge("corriger", "executer")

    return graphe.compile()


# ── Interface principale ──────────────────────────────────────────────────────

class SelfCorrectionPipeline:
    """
    Interface de haut niveau pour la Couche 4.

    Encapsule la construction du graphe et expose une méthode simple
    corriger() que le pipeline principal (core/pipeline.py) appelle.

    Utilisation :
        pipeline = SelfCorrectionPipeline(executor, llm)
        resultat = pipeline.corriger(
            sql="SELECT * FROM clientss;",  # faute de frappe
            schema="Table clients : id, nom...",
            question="liste les clients"
        )
        if resultat["succes"]:
            df = pd.read_json(resultat["resultat"])
        else:
            print(resultat["erreur"])
    """

    def __init__(self, executor: SQLExecutor, llm: ChatOllama) -> None:
        self.executor = executor
        self.llm = llm
        self.graphe = construire_graphe(executor, llm)

    def corriger(
        self,
        sql: str,
        schema: str,
        question: str,
    ) -> dict:
        """
        Lance le pipeline de self-correction sur un SQL potentiellement invalide.

        Args:
            sql      : SQL généré par la Couche 3 (peut être invalide)
            schema   : schéma pertinent (pour la correction par Llama)
            question : question originale (contexte pour Llama)

        Returns:
            dict avec les clés :
              succes   (bool)  : True si le SQL a pu être exécuté
              sql      (str)   : SQL final (original ou corrigé)
              resultat (str)   : JSON du DataFrame si succes=True
              erreur   (str)   : message d'erreur si succes=False
              tentatives (int) : nombre de corrections effectuées
        """
        # État initial du graphe
        etat_initial: EtatCorrection = {
            "question": question,
            "schema": schema,
            "sql": sql,
            "erreur": "",
            "tentatives": 0,
            "resultat": "",
            "abandon": False,
        }

        # Invoquer le graphe — LangGraph gère toute la boucle
        etat_final = self.graphe.invoke(etat_initial)

        return {
            "succes": bool(etat_final["resultat"]),
            "sql": etat_final["sql"],
            "resultat": etat_final["resultat"],
            "erreur": etat_final["erreur"],
            "tentatives": etat_final["tentatives"],
        }