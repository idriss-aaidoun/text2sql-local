"""
database/schema_extractor.py
============================
Couche 1 — Partie A : Extraction du schéma SQL

Rôle : Se connecter à la base de données et extraire toutes les
métadonnées (tables, colonnes, types, clés étrangères).

Principe : SQLAlchemy fournit un objet "inspect" qui lit le schéma
directement depuis la base sans écrire une seule requête SQL à la main.

Ce module ne sait rien du RAG ni des embeddings — il fait UNE seule
chose : lire le schéma. C'est le principe de séparation des responsabilités.
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel
from typing import Optional


# ── Modèles de données ───────────────────────────────────────────────────────
# On utilise Pydantic pour typer strictement les données extraites.
# Avantage : validation automatique + documentation auto-générée.

class ColumnInfo(BaseModel):
    """Représente une colonne d'une table SQL."""
    name: str
    type: str                        # ex: "VARCHAR", "INTEGER", "TIMESTAMP"
    nullable: bool = True
    primary_key: bool = False
    comment: Optional[str] = None


class ForeignKeyInfo(BaseModel):
    """Représente une clé étrangère (lien entre deux tables)."""
    column: str                      # colonne locale
    referred_table: str              # table distante
    referred_column: str             # colonne distante


class TableInfo(BaseModel):
    """Représente une table complète avec ses colonnes et relations."""
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKeyInfo]
    comment: Optional[str] = None


class DatabaseSchema(BaseModel):
    """Le schéma complet de la base de données."""
    tables: dict[str, TableInfo]     # nom_table -> TableInfo
    database_url: str


# ── Extracteur principal ──────────────────────────────────────────────────────

class SchemaExtractor:
    """
    Extrait le schéma complet d'une base de données relationnelle.

    Supporte PostgreSQL et SQLite (les deux bases du cahier des charges).
    Utilise SQLAlchemy Inspector pour une abstraction complète du dialecte SQL.

    Utilisation :
        extractor = SchemaExtractor(db_url="postgresql://admin:admin123@localhost/demo_db")
        schema = extractor.extraire()
        print(schema.tables["commandes"].columns)
    """

    def __init__(self, db_url: str) -> None:
        """
        Args:
            db_url: URL de connexion SQLAlchemy
                    Ex: "postgresql://user:pass@localhost:5432/ma_base"
                    Ex: "sqlite:///./ma_base.db"
        """
        self.db_url = db_url
        # create_engine crée une "fabrique" de connexions — pas encore connecté
        # pool_pre_ping vérifie que la connexion est vivante avant de l'utiliser
        self.engine = create_engine(db_url, pool_pre_ping=True)

    def extraire(self) -> DatabaseSchema:
        """
        Extrait le schéma complet et retourne un objet structuré.

        Returns:
            DatabaseSchema avec toutes les tables, colonnes et relations

        Raises:
            SQLAlchemyError: si la connexion ou l'inspection échoue
        """
        try:
            # inspect() est l'outil SQLAlchemy pour lire les métadonnées
            inspecteur = inspect(self.engine)
            tables: dict[str, TableInfo] = {}

            for nom_table in inspecteur.get_table_names():
                tables[nom_table] = self._extraire_table(inspecteur, nom_table)

            return DatabaseSchema(tables=tables, database_url=self.db_url)

        except SQLAlchemyError as e:
            raise SQLAlchemyError(f"Impossible d'extraire le schéma : {e}") from e

    def _extraire_table(self, inspecteur, nom_table: str) -> TableInfo:
        """Extrait les métadonnées d'une table spécifique."""

        # 1. Récupérer les clés primaires (pour annoter les colonnes PK)
        pks = set(inspecteur.get_pk_constraint(nom_table).get("constrained_columns", []))

        # 2. Extraire chaque colonne
        colonnes = []
        for col in inspecteur.get_columns(nom_table):
            colonnes.append(ColumnInfo(
                name=col["name"],
                # str(col["type"]) donne "VARCHAR(255)", "INTEGER", etc.
                type=str(col["type"]),
                nullable=col.get("nullable", True),
                primary_key=col["name"] in pks,
                comment=col.get("comment"),
            ))

        # 3. Extraire les clés étrangères (relations entre tables)
        cles_etrangeres = []
        for fk in inspecteur.get_foreign_keys(nom_table):
            if fk["constrained_columns"] and fk["referred_columns"]:
                cles_etrangeres.append(ForeignKeyInfo(
                    column=fk["constrained_columns"][0],
                    referred_table=fk["referred_table"],
                    referred_column=fk["referred_columns"][0],
                ))

        # 4. Commentaire de table (optionnel, souvent absent)
        try:
            commentaire = inspecteur.get_table_comment(nom_table).get("text")
        except Exception:
            commentaire = None

        return TableInfo(
            name=nom_table,
            columns=colonnes,
            foreign_keys=cles_etrangeres,
            comment=commentaire,
        )

    def tester_connexion(self) -> bool:
        """Vérifie que la connexion à la base fonctionne."""
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except SQLAlchemyError:
            return False

    def vers_texte(self, schema: DatabaseSchema) -> str:
        """
        Convertit le schéma en texte lisible pour les logs ou le debug.

        Exemple de sortie :
            Table clients :
              - id (INTEGER) [PK]
              - nom (VARCHAR(100))
              - email (VARCHAR(200))
              FK: id_ville -> villes.id
        """
        lignes = []
        for nom, table in schema.tables.items():
            lignes.append(f"\nTable {nom} :")
            for col in table.columns:
                pk_tag = " [PK]" if col.primary_key else ""
                lignes.append(f"  - {col.name} ({col.type}){pk_tag}")
            for fk in table.foreign_keys:
                lignes.append(f"  FK: {fk.column} -> {fk.referred_table}.{fk.referred_column}")
        return "\n".join(lignes)