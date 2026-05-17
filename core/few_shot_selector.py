"""
core/few_shot_selector.py
=========================
Couche 2 — Few-Shot Dynamique

Rôle : Sélectionner les exemples NL->SQL les plus proches sémantiquement
de la question posée, pour les injecter dans le prompt Llama.

Pourquoi le few-shot est crucial pour les LLM ?
  Un LLM génère du texte en prédisant le prochain token.
  Si on lui montre des exemples du format attendu JUSTE AVANT sa réponse,
  il "comprend" le patron et l'imite. C'est le principe du few-shot learning.

Pourquoi dynamique et pas statique ?
  Avec des exemples statiques (toujours les mêmes 3 exemples), Llama reçoit
  des exemples peut-être sans rapport avec la question. Par exemple, si la
  question porte sur un GROUP BY complexe mais que les exemples statiques
  sont tous des SELECT simples, Llama n'a pas de modèle à imiter.

  Avec le few-shot DYNAMIQUE, on sélectionne les 3 exemples dont la question
  est sémantiquement la plus proche -> Llama voit exactement le bon patron SQL.

Architecture :
  Question utilisateur
      ↓ embedding (all-MiniLM-L6-v2)
  Vecteur question
      ↓ ChromaDB similarity_search sur la collection "few_shot_examples"
  3 questions les plus proches + leur SQL de référence
      ↓
  Texte formaté injecté dans le prompt Llama
"""

import json
import os
from pathlib import Path

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document


class FewShotSelector:
    """
    Indexe les exemples NL->SQL dans ChromaDB et sélectionne dynamiquement
    les plus pertinents pour chaque question utilisateur.

    Les exemples sont stockés dans data/few_shot_examples.json.
    Chaque exemple = {"question": "...", "sql": "SELECT ..."}

    Utilisation :
        selector = FewShotSelector()
        selector.charger_exemples()
        exemples = selector.selectionner("commandes de janvier", k=3)
        # -> texte formaté avec les 3 exemples les plus proches
    """

    def __init__(
        self,
        examples_path: str = "./data/few_shot_examples.json",
        persist_dir: str = "./chroma_db",
    ) -> None:
        """
        Args:
            examples_path : chemin vers le fichier JSON des exemples
            persist_dir   : dossier ChromaDB (même base que la couche 1,
                            mais collection différente)
        """
        self.examples_path = Path(examples_path)
        self.persist_dir = persist_dir

        # Même modèle d'embeddings que la Couche 1 — cohérence sémantique
        # et économie mémoire (le modèle est chargé une seule fois en pratique)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )

        # Collection SÉPARÉE de la Couche 1 dans le MÊME ChromaDB
        # "schema_index"     -> tables SQL       (Couche 1)
        # "few_shot_examples" -> exemples NL->SQL (Couche 2)
        self.vectorstore = Chroma(
            collection_name="few_shot_examples",
            embedding_function=self.embeddings,
            persist_directory=persist_dir,
        )

        self._exemples_charges = False

    def charger_exemples(self, forcer: bool = False) -> None:
        """
        Lit le fichier JSON et indexe chaque exemple dans ChromaDB.

        Le texte vectorisé = la QUESTION (pas le SQL).
        Le SQL est stocké dans les métadonnées du document.

        Pourquoi vectoriser la question et pas le SQL ?
        -> On veut trouver les exemples dont la QUESTION ressemble
           à celle de l'utilisateur, pas ceux dont le SQL se ressemble.

        Args:
            forcer : réindexe même si la collection existe déjà
        """
        if not forcer and self._index_existe():
            print("Index few-shot déjà chargé — skip réindexation")
            self._exemples_charges = True
            return

        if not self.examples_path.exists():
            raise FileNotFoundError(
                f"Fichier d'exemples introuvable : {self.examples_path}\n"
                "Créer data/few_shot_examples.json avec des exemples NL->SQL."
            )

        with open(self.examples_path, encoding="utf-8") as f:
            exemples = json.load(f)

        if not exemples:
            raise ValueError("Le fichier few_shot_examples.json est vide.")

        # Construire les documents LangChain
        # page_content = question (ce qui est vectorisé et comparé)
        # metadata.sql  = SQL de référence (récupéré après la recherche)
        documents = []
        for exemple in exemples:
            documents.append(Document(
                page_content=exemple["question"],
                metadata={"sql": exemple["sql"]},
            ))

        # Vider et réindexer si forcer=True
        if forcer and self._index_existe():
            self.vectorstore.delete_collection()
            self.vectorstore = Chroma(
                collection_name="few_shot_examples",
                embedding_function=self.embeddings,
                persist_directory=self.persist_dir,
            )

        self.vectorstore.add_documents(documents)
        self._exemples_charges = True
        print(f"✅ {len(documents)} exemples few-shot indexés dans ChromaDB")

    def selectionner(self, question: str, k: int = 3) -> str:
        """
        Retourne les k exemples les plus proches en texte formaté,
        prêt à être injecté dans le prompt Llama.

        Format de sortie :
            Q: quels clients habitent à Paris ?
            SQL: SELECT * FROM clients WHERE ville = 'Paris';

            Q: liste les commandes du mois de janvier 2024
            SQL: SELECT * FROM commandes WHERE date_commande BETWEEN ...

            Q: ...
            SQL: ...

        Args:
            question : question de l'utilisateur en langage naturel
            k        : nombre d'exemples à sélectionner

        Returns:
            Texte formaté des exemples les plus pertinents

        Raises:
            RuntimeError : si charger_exemples() n'a pas été appelé
        """
        if not self._exemples_charges and not self._index_existe():
            raise RuntimeError(
                "Les exemples ne sont pas chargés. "
                "Appeler charger_exemples() d'abord."
            )

        docs = self.vectorstore.similarity_search(question, k=k)

        lignes = []
        for doc in docs:
            lignes.append(f"Q: {doc.page_content}")
            lignes.append(f"SQL: {doc.metadata['sql']}")
            lignes.append("")  # ligne vide entre les exemples

        return "\n".join(lignes).strip()

    def selectionner_avec_scores(
        self, question: str, k: int = 3
    ) -> list[dict]:
        """
        Version debug : retourne les exemples avec leur score de similarité.

        Utile pour vérifier que les bons exemples sont sélectionnés.

        Returns:
            Liste de dicts : [{"question": ..., "sql": ..., "score": ...}]
        """
        results = self.vectorstore.similarity_search_with_score(question, k=k)
        return [
            {
                "question": doc.page_content,
                "sql": doc.metadata["sql"],
                "score": round(score, 4),
            }
            for doc, score in results
        ]

    def ajouter_exemple(self, question: str, sql: str) -> None:
        """
        Ajoute un nouvel exemple à la volée sans réindexer tout.

        Utile pour enrichir la base d'exemples depuis l'interface Streamlit
        quand l'utilisateur valide un SQL généré.

        Args:
            question : nouvelle question NL
            sql      : SQL correspondant validé
        """
        doc = Document(
            page_content=question,
            metadata={"sql": sql},
        )
        self.vectorstore.add_documents([doc])

        # Sauvegarder aussi dans le fichier JSON pour persistance
        self._sauvegarder_exemple(question, sql)
        print(f"✅ Exemple ajouté : '{question}'")

    def _sauvegarder_exemple(self, question: str, sql: str) -> None:
        """Ajoute un exemple au fichier JSON source pour persistance."""
        if self.examples_path.exists():
            with open(self.examples_path, encoding="utf-8") as f:
                exemples = json.load(f)
        else:
            exemples = []

        exemples.append({"question": question, "sql": sql})

        with open(self.examples_path, "w", encoding="utf-8") as f:
            json.dump(exemples, f, ensure_ascii=False, indent=2)

    def _index_existe(self) -> bool:
        """Vérifie si la collection few-shot contient déjà des données."""
        try:
            return self.vectorstore._collection.count() > 0
        except Exception:
            return False