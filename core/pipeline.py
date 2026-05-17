"""
core/pipeline.py
================
Assemblage des 5 couches — Pipeline principal NL2SQL

Rôle : Orchestrer les 5 couches dans le bon ordre et exposer
une interface simple pour l'application Streamlit.

Flux complet d'une question :

  Question utilisateur
      │
      ▼
  [Couche 1] SchemaRetriever.recuperer()
      │  → tables pertinentes (str)
      ▼
  [Couche 2] FewShotSelector.selectionner()
      │  → exemples NL->SQL pertinents (str)
      ▼
  [Couche 3] SQLGenerator.generer()
      │  → SQL brut nettoyé (str)
      ▼
  [Couche 5A] SQLSecurityValidator.valider()
      │  → bloqué si DML/DDL
      ▼
  [Couche 4] SelfCorrectionPipeline.corriger()
      │  → SQL validé + résultats (DataFrame JSON)
      ▼
  [Couche 5B] SQLExplainer.expliquer()
      │  → explication pédagogique (str)
      ▼
  [Mémoire] ConversationMemory.ajouter()
      │  → historique mis à jour
      ▼
  RésultatPipeline → Interface Streamlit
"""

import os
import json
import pandas as pd
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

from langchain_ollama import ChatOllama

from database.schema_extractor import SchemaExtractor
from database.connector import creer_engine_readonly
from database.executor import SQLExecutor
from core.schema_retriever import SchemaRetriever
from core.few_shot_selector import FewShotSelector
from core.sql_generator import SQLGenerator
from core.sql_validator import SelfCorrectionPipeline
from core.security import valider_sql
from core.explainer import SQLExplainer
from core.memory import ConversationMemory

load_dotenv()


# ── Modèle de résultat ────────────────────────────────────────────────────────

class RésultatPipeline(BaseModel):
    """Résultat complet retourné par le pipeline à l'interface Streamlit."""
    model_config = {"arbitrary_types_allowed": True}

    succes: bool
    question: str
    sql: str                          # SQL final (original ou corrigé)
    donnees: Optional[pd.DataFrame]   # résultats si succes=True
    explication: str                  # explication pédagogique
    nb_resultats: int = 0
    nb_corrections: int = 0           # nombre de corrections LangGraph
    erreur: Optional[str] = None      # message si succes=False
    bloque_securite: bool = False     # True si bloqué par la Couche 5A


# ── Pipeline principal ────────────────────────────────────────────────────────

class NL2SQLPipeline:
    """
    Pipeline complet NL2SQL — orchestration des 5 couches.

    Instancié une seule fois au démarrage de l'app Streamlit
    (les modèles d'embeddings et Llama sont lourds à charger).

    Utilisation :
        pipeline = NL2SQLPipeline()
        pipeline.initialiser()   # charge les modèles et indexe le schéma

        resultat = pipeline.executer("quels clients habitent à Paris ?")
        if resultat.succes:
            st.dataframe(resultat.donnees)
            st.write(resultat.explication)
    """

    def __init__(self) -> None:
        self._initialise = False

        # Variables d'environnement
        self.db_url = os.getenv("DATABASE_URL", "sqlite:///./demo.db")
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1")
        self.chroma_dir = os.getenv("CHROMA_PERSIST_DIR", "./chroma_db")
        self.schema_k = int(os.getenv("SCHEMA_TOP_K", "3"))
        self.fewshot_k = int(os.getenv("FEW_SHOT_TOP_K", "3"))

    def initialiser(self) -> None:
        """
        Initialise tous les composants du pipeline.

        Appelé une seule fois au démarrage — peut prendre
        30-60 secondes sur CPU (chargement des modèles).

        Ordre d'initialisation :
          1. Base de données + extraction schéma
          2. Modèles LLM et embeddings
          3. Couche 1 : indexation schéma
          4. Couche 2 : chargement exemples few-shot
          5. Mémoire conversationnelle
        """
        if self._initialise:
            return

        print("🚀 Initialisation du pipeline NL2SQL...")

        # ── 1. Base de données ────────────────────────────────────────────
        print("  📦 Connexion à la base de données...")
        self.engine = creer_engine_readonly(self.db_url)
        self.executor = SQLExecutor(self.engine)

        extractor = SchemaExtractor(self.db_url)
        self.schema_complet = extractor.extraire()
        print(f"  ✅ Schéma extrait : {len(self.schema_complet.tables)} tables")

        # ── 2. LLM Llama 3.1 ──────────────────────────────────────────────
        print(f"  🤖 Chargement de {self.ollama_model} via Ollama...")
        llm_generation = ChatOllama(
            model=self.ollama_model,
            temperature=0.0,
            base_url=self.ollama_url,
            num_ctx=4096,
            num_thread=4,
        )
        llm_correction = ChatOllama(
            model=self.ollama_model,
            temperature=0.0,
            base_url=self.ollama_url,
            num_ctx=4096,
            num_thread=4,
        )

        # ── 3. Couche 1 : Schema Retriever ────────────────────────────────
        print("  🔍 Indexation du schéma dans ChromaDB...")
        self.schema_retriever = SchemaRetriever(persist_dir=self.chroma_dir)
        self.schema_retriever.indexer_schema(self.schema_complet)

        # ── 4. Couche 2 : Few-Shot Selector ───────────────────────────────
        print("  📚 Chargement des exemples few-shot...")
        self.few_shot_selector = FewShotSelector(
            examples_path="./data/few_shot_examples.json",
            persist_dir=self.chroma_dir,
        )
        self.few_shot_selector.charger_exemples()

        # ── 5. Couches 3, 4, 5 ────────────────────────────────────────────
        self.sql_generator = SQLGenerator(
            model=self.ollama_model,
            base_url=self.ollama_url,
        )
        self.correction_pipeline = SelfCorrectionPipeline(
            executor=self.executor,
            llm=llm_correction,
        )
        self.explainer = SQLExplainer(
            model=self.ollama_model,
            base_url=self.ollama_url,
        )

        # ── 6. Mémoire conversationnelle ──────────────────────────────────
        self.memory = ConversationMemory(max_tours=5)

        self._initialise = True
        print("✅ Pipeline prêt !")

    def executer(self, question: str) -> RésultatPipeline:
        """
        Traite une question en langage naturel de bout en bout.

        Args:
            question : question de l'utilisateur en français ou anglais

        Returns:
            RésultatPipeline avec toutes les informations pour l'affichage
        """
        if not self._initialise:
            raise RuntimeError(
                "Pipeline non initialisé. Appeler initialiser() d'abord."
            )

        print(f"\n📝 Question : {question}")

        # ── Couche 1 : récupérer les tables pertinentes ───────────────────
        schema_pertinent = self.schema_retriever.recuperer(
            question, k=self.schema_k
        )
        print(f"  C1 ✅ Schéma récupéré ({self.schema_k} tables)")

        # ── Couche 2 : sélectionner les exemples few-shot ─────────────────
        exemples = self.few_shot_selector.selectionner(
            question, k=self.fewshot_k
        )
        print(f"  C2 ✅ {self.fewshot_k} exemples sélectionnés")

        # ── Couche 3 : générer le SQL ──────────────────────────────────────
        historique = self.memory.get_historique()
        sql_genere = self.sql_generator.generer(
            schema=schema_pertinent,
            exemples=exemples,
            question=question,
            historique=historique,
        )
        print(f"  C3 ✅ SQL généré : {sql_genere[:60]}...")

        # ── Couche 5A : validation sécurité ───────────────────────────────
        validation = valider_sql(sql_genere)
        if not validation.valide:
            print(f"  C5 🛑 Bloqué : {validation.raison}")
            return RésultatPipeline(
                succes=False,
                question=question,
                sql=sql_genere,
                donnees=None,
                explication="",
                erreur=validation.raison,
                bloque_securite=True,
            )

        print(f"  C5 ✅ Sécurité validée ({validation.type_requete})")

        # ── Couche 4 : exécution + self-correction ────────────────────────
        resultat_correction = self.correction_pipeline.corriger(
            sql=sql_genere,
            schema=schema_pertinent,
            question=question,
        )

        if not resultat_correction["succes"]:
            print(f"  C4 ❌ Échec après corrections : {resultat_correction['erreur']}")
            self.memory.ajouter(
                question=question,
                sql=resultat_correction["sql"],
                succes=False,
            )
            return RésultatPipeline(
                succes=False,
                question=question,
                sql=resultat_correction["sql"],
                donnees=None,
                explication="",
                erreur=resultat_correction["erreur"],
                nb_corrections=resultat_correction["tentatives"],
            )

        sql_final = resultat_correction["sql"]
        nb_corrections = resultat_correction["tentatives"]
        donnees = pd.read_json(resultat_correction["resultat"])

        print(
            f"  C4 ✅ Exécuté ({len(donnees)} lignes, "
            f"{nb_corrections} correction(s))"
        )

        # ── Couche 5B : explication pédagogique ───────────────────────────
        explication = self.explainer.expliquer_avec_contexte(
            sql=sql_final,
            question=question,
        )
        print(f"  C5 ✅ Explication générée")

        # ── Mémoire : enregistrer l'échange ───────────────────────────────
        self.memory.ajouter(
            question=question,
            sql=sql_final,
            succes=True,
            nb_resultats=len(donnees),
        )

        return RésultatPipeline(
            succes=True,
            question=question,
            sql=sql_final,
            donnees=donnees,
            explication=explication,
            nb_resultats=len(donnees),
            nb_corrections=nb_corrections,
        )

    def nouvelle_session(self) -> None:
        """Réinitialise la mémoire conversationnelle."""
        self.memory.reinitialiser()
        print("🔄 Nouvelle session démarrée")