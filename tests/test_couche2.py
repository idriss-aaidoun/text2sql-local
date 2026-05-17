"""
tests/test_couche2.py
=====================
Tests de la Couche 2 — Few-Shot Dynamique

Lancer les tests :
    pytest tests/test_couche2.py -v
"""

import json
import pytest

from core.few_shot_selector import FewShotSelector


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def exemples_json(tmp_path):
    """
    Crée un fichier few_shot_examples.json temporaire avec 6 exemples.
    Couvre : SELECT simple, WHERE, JOIN, GROUP BY, ORDER BY, agrégation.
    """
    exemples = [
        {
            "question": "liste tous les clients",
            "sql": "SELECT * FROM clients;"
        },
        {
            "question": "combien de clients y a-t-il ?",
            "sql": "SELECT COUNT(*) FROM clients;"
        },
        {
            "question": "liste les commandes du mois de janvier",
            "sql": "SELECT * FROM commandes WHERE date_commande BETWEEN '2024-01-01' AND '2024-01-31';"
        },
        {
            "question": "quel est le produit le plus cher ?",
            "sql": "SELECT * FROM produits ORDER BY prix DESC LIMIT 1;"
        },
        {
            "question": "combien de commandes a passé chaque client ?",
            "sql": "SELECT clients.nom, COUNT(commandes.id) AS nb FROM clients LEFT JOIN commandes ON clients.id = commandes.id_client GROUP BY clients.id;"
        },
        {
            "question": "quels produits coûtent moins de 50 euros ?",
            "sql": "SELECT * FROM produits WHERE prix < 50;"
        },
    ]
    path = tmp_path / "few_shot_examples.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(exemples, f, ensure_ascii=False, indent=2)
    return str(path)


@pytest.fixture
def selector(exemples_json, tmp_path):
    """Crée un FewShotSelector chargé et prêt pour les tests."""
    chroma_dir = str(tmp_path / "chroma")
    sel = FewShotSelector(
        examples_path=exemples_json,
        persist_dir=chroma_dir,
    )
    sel.charger_exemples()
    return sel


# ── Tests chargement ──────────────────────────────────────────────────────────

class TestChargement:

    def test_chargement_sans_erreur(self, exemples_json, tmp_path):
        """charger_exemples() ne doit lever aucune exception."""
        sel = FewShotSelector(
            examples_path=exemples_json,
            persist_dir=str(tmp_path / "chroma"),
        )
        sel.charger_exemples()
        assert sel._exemples_charges is True

    def test_fichier_manquant(self, tmp_path):
        """Doit lever FileNotFoundError si le fichier JSON n'existe pas."""
        sel = FewShotSelector(
            examples_path=str(tmp_path / "inexistant.json"),
            persist_dir=str(tmp_path / "chroma"),
        )
        with pytest.raises(FileNotFoundError):
            sel.charger_exemples()

    def test_index_existe_apres_chargement(self, selector):
        """_index_existe() doit retourner True après chargement."""
        assert selector._index_existe() is True


# ── Tests sélection ───────────────────────────────────────────────────────────

class TestSelection:

    def test_retourne_texte_non_vide(self, selector):
        """selectionner() doit retourner un texte non vide."""
        result = selector.selectionner("liste les clients", k=2)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_q_sql(self, selector):
        """Le texte retourné doit contenir les marqueurs 'Q:' et 'SQL:'."""
        result = selector.selectionner("liste les clients", k=2)
        assert "Q:" in result
        assert "SQL:" in result

    def test_question_clients_retourne_select_clients(self, selector):
        """Une question sur les clients doit retourner un SQL avec 'clients'."""
        result = selector.selectionner("affiche tous les clients", k=1)
        assert "clients" in result.lower()

    def test_question_commandes_retourne_sql_commandes(self, selector):
        """Une question sur les commandes doit retourner un SQL avec 'commandes'."""
        result = selector.selectionner("commandes passées en janvier", k=1)
        assert "commandes" in result.lower()

    def test_question_prix_retourne_sql_produits(self, selector):
        """Une question sur les prix doit retourner un SQL sur produits."""
        result = selector.selectionner("produits qui coûtent moins de 100 euros", k=1)
        assert "produits" in result.lower()

    def test_k_controle_nombre_exemples(self, selector):
        """Le paramètre k doit contrôler le nombre d'exemples retournés."""
        result_k1 = selector.selectionner("données", k=1)
        result_k3 = selector.selectionner("données", k=3)
        # k=3 doit contenir plus de blocs Q:/SQL: que k=1
        assert result_k3.count("Q:") == 3
        assert result_k1.count("Q:") == 1

    def test_scores_sont_floats(self, selector):
        """selectionner_avec_scores() doit retourner des floats."""
        results = selector.selectionner_avec_scores("commandes", k=2)
        assert len(results) == 2
        assert all(isinstance(r["score"], float) for r in results)
        assert all("question" in r and "sql" in r for r in results)


# ── Tests ajout dynamique ─────────────────────────────────────────────────────

class TestAjoutDynamique:

    def test_ajouter_exemple(self, selector, exemples_json):
        """ajouter_exemple() doit enrichir l'index sans erreur."""
        selector.ajouter_exemple(
            question="liste les fournisseurs actifs",
            sql="SELECT * FROM fournisseurs WHERE actif = TRUE;",
        )
        # Le nouvel exemple doit maintenant apparaître dans une recherche ciblée
        result = selector.selectionner("fournisseurs actifs", k=1)
        assert "fournisseurs" in result.lower()

    def test_ajouter_exemple_persiste_dans_json(self, selector, exemples_json):
        """L'exemple ajouté doit être sauvegardé dans le fichier JSON."""
        selector.ajouter_exemple(
            question="total des ventes par région",
            sql="SELECT region, SUM(montant) FROM ventes GROUP BY region;",
        )
        with open(exemples_json, encoding="utf-8") as f:
            data = json.load(f)
        questions = [e["question"] for e in data]
        assert "total des ventes par région" in questions