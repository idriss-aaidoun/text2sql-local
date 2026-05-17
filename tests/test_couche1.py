"""
tests/test_couche1.py
=====================
Tests de la Couche 1 — Schema Retrieval

On teste avec SQLite (inclus dans Python standard) pour ne pas avoir
besoin de PostgreSQL ni d'Ollama pendant le développement.

Lancer les tests :
    pytest tests/test_couche1.py -v
"""

import sqlite3
import pytest

from database.schema_extractor import SchemaExtractor
from core.schema_retriever import SchemaRetriever


# ── Fixtures ──────────────────────────────────────────────────────────────────
# Une "fixture" pytest = données ou ressources préparées avant chaque test.
# tmp_path est fourni automatiquement par pytest — dossier temporaire propre.

@pytest.fixture
def base_demo(tmp_path):
    """
    Crée une base SQLite temporaire avec un schéma e-commerce simple.
    Elle est détruite automatiquement après chaque test.
    """
    db_path = tmp_path / "demo.db"
    db_url = f"sqlite:///{db_path}"

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE clients (
            id          INTEGER PRIMARY KEY,
            nom         TEXT    NOT NULL,
            email       TEXT    UNIQUE,
            ville       TEXT,
            date_inscription DATE
        );

        CREATE TABLE produits (
            id          INTEGER PRIMARY KEY,
            nom         TEXT    NOT NULL,
            prix        REAL    NOT NULL,
            stock       INTEGER DEFAULT 0,
            categorie   TEXT
        );

        CREATE TABLE commandes (
            id              INTEGER PRIMARY KEY,
            id_client       INTEGER REFERENCES clients(id),
            date_commande   DATE    NOT NULL,
            montant_total   REAL,
            statut          TEXT    DEFAULT 'en_cours'
        );

        CREATE TABLE lignes_commande (
            id              INTEGER PRIMARY KEY,
            id_commande     INTEGER REFERENCES commandes(id),
            id_produit      INTEGER REFERENCES produits(id),
            quantite        INTEGER NOT NULL,
            prix_unitaire   REAL
        );
    """)
    conn.close()
    return db_url


@pytest.fixture
def chroma_temp(tmp_path):
    """
    Dossier temporaire isolé pour ChromaDB.
    Chaque test a son propre index vide — pas d'interférence entre tests.
    """
    return str(tmp_path / "chroma")


# ── Tests SchemaExtractor ─────────────────────────────────────────────────────

class TestSchemaExtractor:

    def test_connexion_ok(self, base_demo):
        """L'extracteur doit se connecter sans erreur."""
        extractor = SchemaExtractor(base_demo)
        assert extractor.tester_connexion() is True

    def test_nombre_tables(self, base_demo):
        """Doit trouver exactement les 4 tables créées."""
        extractor = SchemaExtractor(base_demo)
        schema = extractor.extraire()
        assert len(schema.tables) == 4

    def test_noms_tables_presents(self, base_demo):
        """Les 4 noms de tables attendus doivent être dans le schéma."""
        extractor = SchemaExtractor(base_demo)
        schema = extractor.extraire()
        assert "clients"         in schema.tables
        assert "produits"        in schema.tables
        assert "commandes"       in schema.tables
        assert "lignes_commande" in schema.tables

    def test_colonnes_clients(self, base_demo):
        """La table clients doit avoir ses 5 colonnes."""
        extractor = SchemaExtractor(base_demo)
        schema = extractor.extraire()
        noms = [c.name for c in schema.tables["clients"].columns]
        assert "id"               in noms
        assert "nom"              in noms
        assert "email"            in noms
        assert "ville"            in noms
        assert "date_inscription" in noms

    def test_cle_primaire_clients(self, base_demo):
        """La colonne 'id' de clients doit être marquée primary_key=True."""
        extractor = SchemaExtractor(base_demo)
        schema = extractor.extraire()
        id_col = next(c for c in schema.tables["clients"].columns if c.name == "id")
        assert id_col.primary_key is True

    def test_texte_lisible(self, base_demo):
        """vers_texte() doit produire un texte contenant les noms de tables."""
        extractor = SchemaExtractor(base_demo)
        schema = extractor.extraire()
        texte = extractor.vers_texte(schema)
        assert "clients"   in texte
        assert "commandes" in texte
        assert len(texte)  > 100


# ── Tests SchemaRetriever (RAG) ───────────────────────────────────────────────

class TestSchemaRetriever:

    def test_indexation_sans_erreur(self, base_demo, chroma_temp):
        """L'indexation complète ne doit lever aucune exception."""
        extractor = SchemaExtractor(base_demo)
        schema    = extractor.extraire()

        retriever = SchemaRetriever(persist_dir=chroma_temp)
        retriever.indexer_schema(schema)

        assert retriever._indexe_charge is True

    def test_recupere_table_commandes(self, base_demo, chroma_temp):
        """Une question sur les commandes doit retourner la table 'commandes'."""
        extractor = SchemaExtractor(base_demo)
        schema    = extractor.extraire()
        retriever = SchemaRetriever(persist_dir=chroma_temp)
        retriever.indexer_schema(schema)

        result = retriever.recuperer("liste toutes les commandes du mois de janvier", k=2)
        assert "commandes" in result.lower()

    def test_recupere_table_produits(self, base_demo, chroma_temp):
        """Une question sur les prix doit retourner la table 'produits'."""
        extractor = SchemaExtractor(base_demo)
        schema    = extractor.extraire()
        retriever = SchemaRetriever(persist_dir=chroma_temp)
        retriever.indexer_schema(schema)

        result = retriever.recuperer("quel est le prix des articles en stock ?", k=2)
        assert "produits" in result.lower()

    def test_recupere_table_clients(self, base_demo, chroma_temp):
        """Une question sur les utilisateurs doit retourner la table 'clients'."""
        extractor = SchemaExtractor(base_demo)
        schema    = extractor.extraire()
        retriever = SchemaRetriever(persist_dir=chroma_temp)
        retriever.indexer_schema(schema)

        result = retriever.recuperer("combien d'utilisateurs habitent à Paris ?", k=2)
        assert "clients" in result.lower()

    def test_scores_sont_des_floats(self, base_demo, chroma_temp):
        """recuperer_avec_scores() doit retourner des tuples (str, float)."""
        extractor = SchemaExtractor(base_demo)
        schema    = extractor.extraire()
        retriever = SchemaRetriever(persist_dir=chroma_temp)
        retriever.indexer_schema(schema)

        results = retriever.recuperer_avec_scores("commandes clients", k=2)
        assert len(results) == 2
        assert isinstance(results[0][0], str)    # texte de la table
        assert isinstance(results[0][1], float)  # score de similarité

    def test_k_controle_le_nombre_de_resultats(self, base_demo, chroma_temp):
        """Le paramètre k doit contrôler exactement le nombre de tables retournées."""
        extractor = SchemaExtractor(base_demo)
        schema    = extractor.extraire()
        retriever = SchemaRetriever(persist_dir=chroma_temp)
        retriever.indexer_schema(schema)

        results = retriever.recuperer_avec_scores("données", k=3)
        assert len(results) == 3