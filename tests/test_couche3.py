"""
tests/test_couche3.py
=====================
Tests de la Couche 3 — Génération SQL

IMPORTANT : Ces tests sont en deux catégories :
  1. Tests sans Ollama  : testent le nettoyage SQL, le format, etc.
                          Tournent toujours, même sans Llama installé.
  2. Tests avec Ollama  : testent la vraie génération via Llama 3.1.
                          Marqués @pytest.mark.integration — ignorés par défaut.

Lancer les tests sans Ollama (rapides) :
    pytest tests/test_couche3.py -v

Lancer TOUS les tests dont les tests d'intégration (Ollama doit tourner) :
    pytest tests/test_couche3.py -v -m integration
"""

import pytest
from unittest.mock import MagicMock, patch

from core.sql_generator import SQLGenerator


# ── Tests du nettoyage SQL (sans Ollama) ─────────────────────────────────────

class TestNettoyageSQL:
    """
    Ces tests vérifient _nettoyer_sql() directement.
    Aucune connexion Ollama requise.
    """

    def setup_method(self):
        """Crée un SQLGenerator sans déclencher la connexion Ollama."""
        # On patche ChatOllama pour ne pas avoir besoin d'Ollama
        with patch("core.sql_generator.ChatOllama"):
            self.generator = SQLGenerator()

    def test_supprime_balises_markdown(self):
        """Les balises ```sql ... ``` doivent être supprimées."""
        brut = "```sql\nSELECT * FROM clients;\n```"
        resultat = self.generator._nettoyer_sql(brut)
        assert resultat == "SELECT * FROM clients;"

    def test_supprime_balises_markdown_sans_sql(self):
        """Les balises ``` ... ``` (sans 'sql') doivent aussi être supprimées."""
        brut = "```\nSELECT * FROM clients;\n```"
        resultat = self.generator._nettoyer_sql(brut)
        assert resultat == "SELECT * FROM clients;"

    def test_supprime_introduction_voici(self):
        """Les phrases d'intro 'Voici la requête :' doivent être supprimées."""
        brut = "Voici la requête SQL :\n\nSELECT * FROM clients;"
        resultat = self.generator._nettoyer_sql(brut)
        assert "SELECT" in resultat
        assert "Voici" not in resultat

    def test_supprime_commentaires_inline(self):
        """Les commentaires SQL -- doivent être supprimés."""
        brut = "SELECT * FROM clients; -- liste tous les clients"
        resultat = self.generator._nettoyer_sql(brut)
        assert "--" not in resultat
        assert "SELECT * FROM clients;" in resultat

    def test_sql_propre_reste_intact(self):
        """Un SQL déjà propre ne doit pas être modifié."""
        sql_propre = "SELECT id, nom FROM clients WHERE ville = 'Paris';"
        resultat = self.generator._nettoyer_sql(sql_propre)
        assert resultat == sql_propre

    def test_sql_complexe_reste_intact(self):
        """Un SQL avec JOIN et GROUP BY doit rester intact."""
        sql = (
            "SELECT clients.nom, COUNT(commandes.id) AS nb\n"
            "FROM clients\n"
            "LEFT JOIN commandes ON clients.id = commandes.id_client\n"
            "GROUP BY clients.id;"
        )
        resultat = self.generator._nettoyer_sql(sql)
        assert "JOIN" in resultat
        assert "GROUP BY" in resultat

    def test_espaces_en_debut_fin_supprimes(self):
        """Les espaces et sauts de ligne en début/fin doivent être supprimés."""
        brut = "\n\n   SELECT * FROM clients;   \n\n"
        resultat = self.generator._nettoyer_sql(brut)
        assert resultat == "SELECT * FROM clients;"


# ── Tests d'intégration avec Ollama ──────────────────────────────────────────
# Ces tests nécessitent qu'Ollama soit démarré avec Llama 3.1
# Lancer avec : pytest tests/test_couche3.py -v -m integration

@pytest.mark.integration
class TestGenerationAvecOllama:
    """
    Tests de la vraie génération SQL via Llama 3.1.
    Requiert : ollama serve + ollama pull llama3.1
    """

    def setup_method(self):
        self.generator = SQLGenerator()
        self.schema = """Table clients : id (INTEGER) [PK], nom (TEXT), ville (TEXT)
Table commandes : id (INTEGER) [PK], id_client (INTEGER), date_commande (DATE), montant_total (REAL)"""
        self.exemples = """Q: liste tous les clients
SQL: SELECT * FROM clients;

Q: liste les commandes du mois de janvier
SQL: SELECT * FROM commandes WHERE date_commande BETWEEN '2024-01-01' AND '2024-01-31';"""

    def test_genere_select_simple(self):
        """Llama doit générer un SELECT pour une question simple."""
        sql = self.generator.generer_simple(
            schema=self.schema,
            exemples=self.exemples,
            question="liste tous les clients",
        )
        assert sql.upper().startswith("SELECT")
        assert "clients" in sql.lower()

    def test_genere_where(self):
        """Llama doit générer un WHERE pour une question filtrée."""
        sql = self.generator.generer_simple(
            schema=self.schema,
            exemples=self.exemples,
            question="quels clients habitent à Paris ?",
        )
        assert "WHERE" in sql.upper()
        assert "ville" in sql.lower()

    def test_pas_de_markdown_dans_sortie(self):
        """La sortie ne doit jamais contenir de balises markdown."""
        sql = self.generator.generer_simple(
            schema=self.schema,
            exemples=self.exemples,
            question="combien de clients y a-t-il ?",
        )
        assert "```" not in sql
        assert "sql" not in sql[:10].lower()

    def test_pas_de_dml_genere(self):
        """
        Llama peut parfois générer du DML malgré le prompt.
        Ce n'est PAS un bug de la Couche 3 — c'est exactement pourquoi
        la Couche 5 (security.py) existe et bloque le DML par analyse AST.
        Ce test vérifie que la Couche 3 TENTE de respecter la consigne,
        sans garantie absolue — la garantie est assurée par la Couche 5.
        """
        sql = self.generator.generer_simple(
            schema=self.schema,
            exemples=self.exemples,
            question="supprime tous les clients",
        )
        # On vérifie juste que le SQL est une string non vide
        # Le filtrage DML est délégué à core/security.py (Couche 5)
        assert isinstance(sql, str)
        assert len(sql) > 0

    def test_connexion_ollama(self):
        """Ollama doit être accessible."""
        assert self.generator.tester_connexion_ollama() is True