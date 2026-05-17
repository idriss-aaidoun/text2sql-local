"""
tests/test_couche5.py
=====================
Tests de la Couche 5 — Sécurité & Explication

Les tests de sécurité ne nécessitent pas Ollama.
Les tests d'explication sont marqués @pytest.mark.integration.

Lancer :
    pytest tests/test_couche5.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from core.security import (
    SQLSecurityValidator,
    valider_sql,
    est_select_valide,
    ResultatValidation,
)
from core.memory import ConversationMemory, Tour


# ── Tests SQLSecurityValidator ────────────────────────────────────────────────

class TestSecurityValidator:

    def setup_method(self):
        self.validator = SQLSecurityValidator()

    # -- SELECT valides -------------------------------------------------------

    def test_select_simple_valide(self):
        """Un SELECT simple doit être autorisé."""
        r = self.validator.valider("SELECT * FROM clients;")
        assert r.valide is True
        assert r.type_requete == "SELECT"

    def test_select_avec_where_valide(self):
        """SELECT avec WHERE doit être autorisé."""
        r = self.validator.valider(
            "SELECT * FROM clients WHERE ville = 'Paris';"
        )
        assert r.valide is True

    def test_select_avec_join_valide(self):
        """SELECT avec JOIN doit être autorisé."""
        r = self.validator.valider(
            "SELECT c.nom, cmd.montant_total "
            "FROM clients c JOIN commandes cmd ON c.id = cmd.id_client;"
        )
        assert r.valide is True

    def test_select_avec_group_by_valide(self):
        """SELECT avec GROUP BY et COUNT doit être autorisé."""
        r = self.validator.valider(
            "SELECT ville, COUNT(*) as nb FROM clients GROUP BY ville;"
        )
        assert r.valide is True

    def test_select_avec_subquery_valide(self):
        """SELECT avec sous-requête doit être autorisé."""
        r = self.validator.valider(
            "SELECT * FROM clients WHERE id IN "
            "(SELECT id_client FROM commandes WHERE montant_total > 100);"
        )
        assert r.valide is True

    # -- DML bloqués ----------------------------------------------------------

    def test_delete_bloque(self):
        """DELETE doit être bloqué."""
        r = self.validator.valider("DELETE FROM clients;")
        assert r.valide is False
        assert "DELETE" in r.raison

    def test_insert_bloque(self):
        """INSERT doit être bloqué."""
        r = self.validator.valider(
            "INSERT INTO clients (nom) VALUES ('Hacker');"
        )
        assert r.valide is False
        assert "INSERT" in r.raison

    def test_update_bloque(self):
        """UPDATE doit être bloqué."""
        r = self.validator.valider(
            "UPDATE clients SET nom = 'Hacker' WHERE id = 1;"
        )
        assert r.valide is False
        assert "UPDATE" in r.raison

    def test_truncate_bloque(self):
        """TRUNCATE doit être bloqué."""
        r = self.validator.valider("TRUNCATE TABLE clients;")
        assert r.valide is False

    # -- DDL bloqués ----------------------------------------------------------

    def test_drop_bloque(self):
        """DROP TABLE doit être bloqué."""
        r = self.validator.valider("DROP TABLE clients;")
        assert r.valide is False
        assert "DROP" in r.raison

    def test_create_bloque(self):
        """CREATE TABLE doit être bloqué."""
        r = self.validator.valider(
            "CREATE TABLE hack (id INTEGER);"
        )
        assert r.valide is False

    def test_alter_bloque(self):
        """ALTER TABLE doit être bloqué."""
        r = self.validator.valider(
            "ALTER TABLE clients ADD COLUMN hack TEXT;"
        )
        assert r.valide is False

    # -- Injections bloquées --------------------------------------------------

    def test_injection_multiple_requetes(self):
        """Deux requêtes séparées par ; doivent être bloquées."""
        r = self.validator.valider(
            "SELECT * FROM clients; DROP TABLE clients;"
        )
        assert r.valide is False
        assert "multiples" in r.raison.lower() or "plusieurs" in r.raison.lower()

    def test_sql_vide_bloque(self):
        """Un SQL vide doit être bloqué."""
        r = self.validator.valider("")
        assert r.valide is False

    def test_sql_whitespace_bloque(self):
        """Un SQL avec seulement des espaces doit être bloqué."""
        r = self.validator.valider("   ")
        assert r.valide is False

    # -- Fonctions utilitaires ------------------------------------------------

    def test_valider_sql_fonction(self):
        """La fonction utilitaire valider_sql doit fonctionner."""
        r = valider_sql("SELECT * FROM clients;")
        assert isinstance(r, ResultatValidation)
        assert r.valide is True

    def test_est_select_valide_true(self):
        """est_select_valide doit retourner True pour un SELECT."""
        assert est_select_valide("SELECT * FROM clients;") is True

    def test_est_select_valide_false(self):
        """est_select_valide doit retourner False pour un DELETE."""
        assert est_select_valide("DELETE FROM clients;") is False


# ── Tests ConversationMemory ──────────────────────────────────────────────────

class TestConversationMemory:

    def test_memoire_vide_au_debut(self):
        """La mémoire doit être vide à l'initialisation."""
        memory = ConversationMemory()
        assert memory.est_vide is True
        assert memory.nb_tours == 0

    def test_ajouter_un_tour(self):
        """Après ajout, la mémoire ne doit plus être vide."""
        memory = ConversationMemory()
        memory.ajouter(
            question="liste les clients",
            sql="SELECT * FROM clients;",
            succes=True,
            nb_resultats=10,
        )
        assert memory.est_vide is False
        assert memory.nb_tours == 1

    def test_historique_contient_question(self):
        """L'historique formaté doit contenir la question posée."""
        memory = ConversationMemory()
        memory.ajouter("liste les clients", "SELECT * FROM clients;", True, 10)
        historique = memory.get_historique()
        assert "liste les clients" in historique

    def test_historique_contient_sql(self):
        """L'historique formaté doit contenir le SQL exécuté."""
        memory = ConversationMemory()
        memory.ajouter("liste les clients", "SELECT * FROM clients;", True, 10)
        historique = memory.get_historique()
        assert "SELECT * FROM clients;" in historique

    def test_limite_max_tours(self):
        """La mémoire ne doit pas dépasser max_tours."""
        memory = ConversationMemory(max_tours=3)
        for i in range(5):
            memory.ajouter(f"question {i}", f"SELECT {i};", True, i)
        assert memory.nb_tours == 3

    def test_fifo_garde_les_derniers(self):
        """Les tours les plus récents doivent être conservés."""
        memory = ConversationMemory(max_tours=2)
        memory.ajouter("question 1", "SELECT 1;", True, 1)
        memory.ajouter("question 2", "SELECT 2;", True, 2)
        memory.ajouter("question 3", "SELECT 3;", True, 3)

        historique = memory.get_historique()
        assert "question 1" not in historique
        assert "question 2" in historique
        assert "question 3" in historique

    def test_get_dernier_sql_succes(self):
        """get_dernier_sql doit retourner le dernier SQL réussi."""
        memory = ConversationMemory()
        memory.ajouter("q1", "SELECT * FROM clients;", True, 5)
        memory.ajouter("q2", "SELECT * FROM mauvaise;", False, 0)
        assert memory.get_dernier_sql() == "SELECT * FROM clients;"

    def test_reinitialiser_vide_la_memoire(self):
        """reinitialiser() doit vider complètement l'historique."""
        memory = ConversationMemory()
        memory.ajouter("question", "SELECT 1;", True, 1)
        memory.reinitialiser()
        assert memory.est_vide is True

    def test_historique_vide_message_explicite(self):
        """Sans historique, get_historique doit retourner un message clair."""
        memory = ConversationMemory()
        historique = memory.get_historique()
        assert "première" in historique.lower() or "aucun" in historique.lower()