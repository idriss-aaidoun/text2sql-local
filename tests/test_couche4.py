"""
tests/test_couche4.py
=====================
Tests de la Couche 4 — Self-Correction LangGraph

Stratégie de test :
  On mocke SQLExecutor et ChatOllama pour contrôler précisément
  les scénarios (succès immédiat, échec puis succès, abandon).
  Pas besoin d'Ollama ni de PostgreSQL pour ces tests.

Lancer :
    pytest tests/test_couche4.py -v
"""

import json
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from database.executor import ResultatExecution
from core.sql_validator import (
    EtatCorrection,
    SelfCorrectionPipeline,
    decision_apres_execution,
    noeud_executer,
    noeud_corriger,
    MAX_TENTATIVES,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_etat(
    sql="SELECT * FROM clients;",
    erreur="",
    tentatives=0,
    resultat="",
    abandon=False,
) -> EtatCorrection:
    """Crée un état de test avec des valeurs par défaut."""
    return EtatCorrection(
        question="liste les clients",
        schema="Table clients : id INTEGER, nom TEXT",
        sql=sql,
        erreur=erreur,
        tentatives=tentatives,
        resultat=resultat,
        abandon=abandon,
    )


def make_executor_succes() -> MagicMock:
    """Mock executor qui retourne toujours un succès."""
    executor = MagicMock()
    df = pd.DataFrame([{"id": 1, "nom": "Alice"}, {"id": 2, "nom": "Bob"}])
    executor.executer.return_value = ResultatExecution(
        succes=True, sql="SELECT * FROM clients;", donnees=df, nb_lignes=2
    )
    return executor


def make_executor_echec(message: str = "colonne 'clientss' inexistante") -> MagicMock:
    """Mock executor qui retourne toujours un échec."""
    executor = MagicMock()
    executor.executer.return_value = ResultatExecution(
        succes=False, sql="SELECT * FROM clientss;", erreur=message
    )
    return executor


def make_executor_echec_puis_succes() -> MagicMock:
    """Mock executor qui échoue au 1er appel puis réussit au 2ème."""
    executor = MagicMock()
    df = pd.DataFrame([{"id": 1, "nom": "Alice"}])
    executor.executer.side_effect = [
        ResultatExecution(
            succes=False,
            sql="SELECT * FROM clientss;",
            erreur="relation 'clientss' does not exist",
        ),
        ResultatExecution(
            succes=True,
            sql="SELECT * FROM clients;",
            donnees=df,
            nb_lignes=1,
        ),
    ]
    return executor


def make_llm_correction(sql_corrige: str = "SELECT * FROM clients;") -> MagicMock:
    """Mock LLM qui retourne un SQL corrigé."""
    llm = MagicMock()
    response = MagicMock()
    response.content = sql_corrige
    llm.invoke.return_value = response

    # Simuler le comportement de la chaîne LCEL (prompt | llm | parser)
    # quand on appelle chain.invoke(...)
    mock_chain = MagicMock()
    mock_chain.invoke.return_value = sql_corrige
    llm.__or__ = MagicMock(return_value=mock_chain)
    return llm


# ── Tests de la fonction de décision ─────────────────────────────────────────

class TestDecision:
    """Tests de la logique de routage du graphe."""

    def test_succes_si_resultat_present(self):
        """Doit retourner 'succes' si l'état a un résultat."""
        etat = make_etat(resultat='[{"id": 1}]')
        assert decision_apres_execution(etat) == "succes"

    def test_abandon_si_max_tentatives(self):
        """Doit retourner 'abandon' si tentatives >= MAX_TENTATIVES."""
        etat = make_etat(erreur="erreur SQL", tentatives=MAX_TENTATIVES)
        assert decision_apres_execution(etat) == "abandon"

    def test_corriger_si_erreur_et_tentatives_restantes(self):
        """Doit retourner 'corriger' si erreur et tentatives < MAX."""
        etat = make_etat(erreur="erreur SQL", tentatives=0)
        assert decision_apres_execution(etat) == "corriger"

    def test_corriger_avant_derniere_tentative(self):
        """Doit encore corriger à tentatives = MAX - 1."""
        etat = make_etat(erreur="erreur SQL", tentatives=MAX_TENTATIVES - 1)
        assert decision_apres_execution(etat) == "corriger"


# ── Tests du noeud executer ───────────────────────────────────────────────────

class TestNoeudExecuter:
    """Tests du noeud d'exécution SQL."""

    def test_succes_retourne_resultat_json(self):
        """En cas de succès, retourne un JSON non vide."""
        executor = make_executor_succes()
        etat = make_etat()
        sortie = noeud_executer(etat, executor)

        assert sortie["erreur"] == ""
        assert sortie["resultat"] != ""
        # Vérifier que c'est du JSON valide
        data = json.loads(sortie["resultat"])
        assert len(data) == 2
        assert data[0]["nom"] == "Alice"

    def test_echec_retourne_erreur(self):
        """En cas d'échec, retourne le message d'erreur."""
        executor = make_executor_echec("colonne inexistante")
        etat = make_etat()
        sortie = noeud_executer(etat, executor)

        assert sortie["resultat"] == ""
        assert "colonne" in sortie["erreur"].lower()

    def test_executor_est_appele_avec_bon_sql(self):
        """Le noeud doit appeler executor.executer avec le SQL de l'état."""
        executor = make_executor_succes()
        etat = make_etat(sql="SELECT id FROM clients;")
        noeud_executer(etat, executor)

        executor.executer.assert_called_once_with("SELECT id FROM clients;")


# ── Tests du pipeline complet ─────────────────────────────────────────────────

class TestSelfCorrectionPipeline:
    """Tests du pipeline de self-correction complet via LangGraph."""

    def test_succes_immediat(self):
        """Un SQL valide dès le 1er essai doit réussir sans correction."""
        executor = make_executor_succes()
        llm = MagicMock()

        pipeline = SelfCorrectionPipeline(executor, llm)
        resultat = pipeline.corriger(
            sql="SELECT * FROM clients;",
            schema="Table clients : id INTEGER, nom TEXT",
            question="liste les clients",
        )

        assert resultat["succes"] is True
        assert resultat["tentatives"] == 0
        assert resultat["erreur"] == ""
        assert resultat["resultat"] != ""

    def test_echec_total_apres_max_tentatives(self):
        """Un SQL toujours invalide doit abandonner après MAX_TENTATIVES."""
        executor = make_executor_echec("table inexistante")
        llm = MagicMock()

        # On mocke noeud_corriger directement — il retourne toujours
        # un état avec le même SQL invalide, sans toucher au LLM
        with patch("core.sql_validator.noeud_corriger") as mock_corriger:
            mock_corriger.side_effect = lambda etat, llm: {
                **etat,
                "sql": "SELECT * FROM mauvaise_table;",
                "tentatives": etat["tentatives"] + 1,
            }

            pipeline = SelfCorrectionPipeline(executor, llm)
            resultat = pipeline.corriger(
                sql="SELECT * FROM mauvaise_table;",
                schema="Table clients : id INTEGER",
                question="liste les clients",
            )

        assert resultat["succes"] is False
        assert resultat["tentatives"] >= MAX_TENTATIVES

    def test_resultat_est_json_valide(self):
        """Le résultat retourné doit être du JSON parseable."""
        executor = make_executor_succes()
        llm = MagicMock()

        pipeline = SelfCorrectionPipeline(executor, llm)
        resultat = pipeline.corriger(
            sql="SELECT * FROM clients;",
            schema="Table clients : id INTEGER, nom TEXT",
            question="liste les clients",
        )

        assert resultat["succes"] is True
        data = json.loads(resultat["resultat"])
        assert isinstance(data, list)

    def test_sql_final_est_retourne(self):
        """Le SQL final (original ou corrigé) doit toujours être retourné."""
        executor = make_executor_succes()
        llm = MagicMock()

        pipeline = SelfCorrectionPipeline(executor, llm)
        resultat = pipeline.corriger(
            sql="SELECT * FROM clients;",
            schema="Table clients : id INTEGER, nom TEXT",
            question="liste les clients",
        )

        assert "sql" in resultat
        assert len(resultat["sql"]) > 0


# ── Tests SQLExecutor ─────────────────────────────────────────────────────────

class TestSQLExecutor:
    """Tests de l'exécuteur SQL avec une base SQLite de test."""

    @pytest.fixture
    def executor_sqlite(self, tmp_path):
        """Crée un executor avec une base SQLite temporaire."""
        import sqlite3
        from database.connector import creer_engine_readonly
        from database.executor import SQLExecutor

        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE clients (id INTEGER PRIMARY KEY, nom TEXT, ville TEXT);
            INSERT INTO clients VALUES (1, 'Alice', 'Paris');
            INSERT INTO clients VALUES (2, 'Bob', 'Lyon');
        """)
        conn.close()

        # SQLite en mode normal pour les tests (pas read-only URI)
        from sqlalchemy import create_engine
        engine = create_engine(f"sqlite:///{db_path}")
        return SQLExecutor(engine)

    def test_select_simple_retourne_dataframe(self, executor_sqlite):
        """Un SELECT valide doit retourner un DataFrame."""
        resultat = executor_sqlite.executer("SELECT * FROM clients;")
        assert resultat.succes is True
        assert resultat.donnees is not None
        assert len(resultat.donnees) == 2

    def test_table_inexistante_retourne_erreur(self, executor_sqlite):
        """Un SELECT sur une table inexistante doit retourner succes=False."""
        resultat = executor_sqlite.executer("SELECT * FROM inexistante;")
        assert resultat.succes is False
        assert resultat.erreur is not None
        assert len(resultat.erreur) > 0

    def test_colonnes_correctes(self, executor_sqlite):
        """Le DataFrame doit avoir les colonnes de la table."""
        resultat = executor_sqlite.executer("SELECT id, nom FROM clients;")
        assert resultat.succes is True
        assert "id" in resultat.donnees.columns
        assert "nom" in resultat.donnees.columns

    def test_where_filtre_correctement(self, executor_sqlite):
        """Un WHERE doit filtrer les résultats."""
        resultat = executor_sqlite.executer(
            "SELECT * FROM clients WHERE ville = 'Paris';"
        )
        assert resultat.succes is True
        assert len(resultat.donnees) == 1
        assert resultat.donnees.iloc[0]["nom"] == "Alice"