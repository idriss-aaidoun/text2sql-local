"""
core/schema_retriever.py
========================
Couche 1 — Partie B : RAG sur le schéma SQL

Rôle : Indexer le schéma SQL dans ChromaDB et retrouver les tables
pertinentes par similarité sémantique avec la question utilisateur.

Concept RAG (Retrieval-Augmented Generation) :
  1. INDEXATION : on transforme chaque table en texte et on calcule
     son "embedding" (vecteur numérique qui capture le sens).
  2. RETRIEVAL : pour une question, on calcule son embedding et on
     cherche les tables dont l'embedding est le plus proche.
  3. GÉNÉRATION : on injecte uniquement ces tables dans le prompt Llama.

Pourquoi ça marche ?
  "Montre-moi les commandes de janvier" → proche de "Table commandes : id, date, montant"
  → ChromaDB retourne la table "commandes" et pas "produits" ni "fournisseurs"
  → Llama génère un SQL correct sans halluciner de colonnes inexistantes
"""

import os
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

from database.schema_extractor import DatabaseSchema, TableInfo


class SchemaRetriever:
    """
    Indexe le schéma SQL dans ChromaDB et retrouve les tables pertinentes
    par recherche sémantique (cosine similarity sur les embeddings).

    Architecture interne :
        Question utilisateur
            ↓ HuggingFaceEmbeddings (all-MiniLM-L6-v2)
        Vecteur question [384 dimensions]
            ↓ ChromaDB similarity_search
        Vecteurs tables les plus proches
            ↓
        Texte des tables pertinentes → injecté dans le prompt Llama

    Utilisation :
        retriever = SchemaRetriever()
        retriever.indexer_schema(schema)  # une seule fois au démarrage
        tables = retriever.recuperer("quelles commandes de janvier ?", k=3)
        # → retourne le texte des 3 tables les plus pertinentes
    """

    def __init__(self, persist_dir: str = "./chroma_db") -> None:
        """
        Args:
            persist_dir: dossier où ChromaDB stocke ses données sur disque.
                         ChromaDB est persistant : si on relance l'app,
                         l'index est déjà là, pas besoin de réindexer.
        """
        # ── Modèle d'embeddings ───────────────────────────────────────────
        # all-MiniLM-L6-v2 : modèle léger (90 Mo) optimisé pour la similarité
        # de phrases. "L6" = 6 couches Transformer. Très rapide sur CPU.
        # Il transforme n'importe quel texte en vecteur de 384 dimensions.
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},  # cosine similarity
        )

        # ── Vector Store ChromaDB ─────────────────────────────────────────
        # collection_name : comme un "namespace" — sépare nos tables
        # des exemples few-shot qui seront dans une autre collection
        self.vectorstore = Chroma(
            collection_name="schema_index",
            embedding_function=self.embeddings,
            persist_directory=persist_dir,
        )

        self._indexe_charge = False

    def indexer_schema(self, schema: DatabaseSchema, forcer: bool = False) -> None:
        """
        Transforme chaque table en document texte et l'indexe dans ChromaDB.

        Appelé UNE SEULE FOIS au démarrage (ou quand le schéma change).
        ChromaDB étant persistant, les données survivent aux redémarrages.

        Args:
            schema: le schéma extrait par SchemaExtractor
            forcer: si True, réindexe même si l'index existe déjà
        """
        # Vérifier si l'index existe déjà (évite de réindexer à chaque démarrage)
        if not forcer and self._index_existe():
            print("Index schéma déjà chargé — skip réindexation")
            self._indexe_charge = True
            return

        documents = []
        for nom_table, table_info in schema.tables.items():
            # Convertir la table en texte structuré
            # Ce texte EST ce qui va être vectorisé — sa qualité est cruciale
            texte = self._table_vers_texte(table_info)

            # Un Document LangChain = texte + métadonnées
            # Les métadonnées permettent de récupérer le nom original de la table
            documents.append(Document(
                page_content=texte,
                metadata={"table_name": nom_table}
            ))

        # Vider l'ancienne collection si on force la réindexation
        if forcer:
            self.vectorstore.delete_collection()
            self.vectorstore = Chroma(
                collection_name="schema_index",
                embedding_function=self.embeddings,
                persist_directory=self.vectorstore._persist_directory,
            )

        # add_documents calcule les embeddings ET les stocke dans ChromaDB
        self.vectorstore.add_documents(documents)
        self._indexe_charge = True
        print(f"✅ {len(documents)} tables indexées dans ChromaDB")

    def recuperer(self, question: str, k: int = 3) -> str:
        """
        Recherche les k tables les plus pertinentes pour la question.

        Le résultat est formaté en texte prêt à être injecté dans le prompt Llama.

        Args:
            question: la question en langage naturel de l'utilisateur
            k: nombre de tables à récupérer (défaut: 3, configurable en .env)

        Returns:
            Texte formaté des tables pertinentes, ex:
                Table commandes : id (INTEGER) [PK], date (DATE), montant (FLOAT)
                  FK: id_client -> clients.id
                Table clients : id (INTEGER) [PK], nom (VARCHAR), email (VARCHAR)

        Raises:
            RuntimeError: si le schéma n'a pas été indexé d'abord
        """
        if not self._indexe_charge and not self._index_existe():
            raise RuntimeError(
                "Le schéma n'est pas indexé. Appeler indexer_schema() d'abord."
            )

        # similarity_search calcule l'embedding de la question et cherche
        # les documents dont le vecteur est le plus proche (cosine similarity)
        docs = self.vectorstore.similarity_search(question, k=k)

        # Assembler les résultats en un texte structuré
        return "\n\n".join(doc.page_content for doc in docs)

    def recuperer_avec_scores(self, question: str, k: int = 3) -> list[tuple[str, float]]:
        """
        Version debug : retourne les tables avec leur score de similarité.

        Utile pour diagnostiquer pourquoi le RAG récupère telle ou telle table.
        Score entre 0 et 1 — plus proche de 1 = plus pertinent.
        """
        results = self.vectorstore.similarity_search_with_score(question, k=k)
        return [(doc.page_content, score) for doc, score in results]

    def _table_vers_texte(self, table: TableInfo) -> str:
        """
        Convertit une TableInfo en texte dense que l'embedding va vectoriser.

        Format optimisé pour que le modèle all-MiniLM-L6-v2 capte bien
        le sens métier de la table (pas juste les noms techniques).

        Exemple de sortie :
            Table commandes : colonnes : id (INTEGER), date_commande (DATE),
            montant_total (FLOAT), statut (VARCHAR). Relations : id_client -> clients.id
        """
        # Formater les colonnes
        cols_parts = []
        for col in table.columns:
            tag = " [PK]" if col.primary_key else ""
            cols_parts.append(f"{col.name} ({col.type}){tag}")
        cols_text = ", ".join(cols_parts)

        # Formater les clés étrangères
        fks_text = ""
        if table.foreign_keys:
            fk_parts = [
                f"{fk.column} -> {fk.referred_table}.{fk.referred_column}"
                for fk in table.foreign_keys
            ]
            fks_text = f". Relations : {', '.join(fk_parts)}"

        # Commentaire de table (si présent, très utile pour la vectorisation)
        comment_text = f". Description : {table.comment}" if table.comment else ""

        return (
            f"Table {table.name} : colonnes : {cols_text}{fks_text}{comment_text}"
        )

    def _index_existe(self) -> bool:
        """Vérifie si la collection ChromaDB contient déjà des données."""
        try:
            count = self.vectorstore._collection.count()
            return count > 0
        except Exception:
            return False