"""
database/executor.py
====================
Exécution sécurisée des requêtes SQL générées par Llama.

Rôle : Prendre le SQL validé par la Couche 5, l'exécuter sur la base,
et retourner les résultats sous forme de DataFrame pandas.

Ce module est appelé par la Couche 4 (LangGraph) dans le noeud "executer".
Il capture les erreurs SQL et les retourne proprement pour que
LangGraph puisse décider de corriger ou d'abandonner.
"""

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel
from typing import Optional


class ResultatExecution(BaseModel):
    """
    Résultat structuré d'une exécution SQL.

    Utilise model_config pour autoriser les types arbitraires (DataFrame).
    """
    model_config = {"arbitrary_types_allowed": True}

    succes: bool
    sql: str
    donnees: Optional[pd.DataFrame] = None   # résultats si succès
    erreur: Optional[str] = None             # message d'erreur si échec
    nb_lignes: int = 0


class SQLExecutor:
    """
    Exécute les requêtes SQL de façon sécurisée et retourne les résultats.

    Utilisation :
        executor = SQLExecutor(engine)
        resultat = executor.executer("SELECT * FROM clients LIMIT 10;")
        if resultat.succes:
            print(resultat.donnees)   # DataFrame pandas
        else:
            print(resultat.erreur)    # message d'erreur pour correction
    """

    def __init__(self, engine: Engine, limite_lignes: int = 1000) -> None:
        """
        Args:
            engine       : engine SQLAlchemy (read-only de préférence)
            limite_lignes: nombre max de lignes retournées (protection mémoire)
        """
        self.engine = engine
        self.limite_lignes = limite_lignes

    def executer(self, sql: str) -> ResultatExecution:
        """
        Exécute le SQL et retourne un ResultatExecution structuré.

        En cas d'erreur, le message d'erreur est formaté pour être
        directement injecté dans le prompt de correction de la Couche 4.

        Args:
            sql : requête SQL à exécuter (doit être un SELECT)

        Returns:
            ResultatExecution avec succes=True et donnees=DataFrame
            ou succes=False et erreur=message_erreur
        """
        sql_propre = self._preparer_sql(sql)

        try:
            with self.engine.connect() as conn:
                # pandas.read_sql exécute et convertit directement en DataFrame
                df = pd.read_sql(text(sql_propre), conn)

                # Limiter le nombre de lignes pour protéger la mémoire
                if len(df) > self.limite_lignes:
                    df = df.head(self.limite_lignes)

                return ResultatExecution(
                    succes=True,
                    sql=sql_propre,
                    donnees=df,
                    nb_lignes=len(df),
                )

        except SQLAlchemyError as e:
            # Formater l'erreur de façon utile pour la correction Llama
            return ResultatExecution(
                succes=False,
                sql=sql_propre,
                erreur=self._formater_erreur(str(e)),
            )
        except PermissionError as e:
            return ResultatExecution(
                succes=False,
                sql=sql_propre,
                erreur=f"Opération non autorisée : {e}",
            )
        except Exception as e:
            return ResultatExecution(
                succes=False,
                sql=sql_propre,
                erreur=f"Erreur inattendue : {type(e).__name__} : {e}",
            )

    def _preparer_sql(self, sql: str) -> str:
        """
        Prépare le SQL avant exécution :
        - Supprime les points-virgules multiples
        - S'assure qu'il n'y a qu'une seule requête
        - Ajoute LIMIT si absent (protection contre les full scans)
        """
        sql = sql.strip().rstrip(";")

        # Bloquer les requêtes multiples (séparées par ;)
        if ";" in sql:
            # Garder seulement la première requête
            sql = sql.split(";")[0].strip()

        # Ajouter LIMIT si la requête n'en a pas (protection mémoire)
        sql_upper = sql.upper()
        if (
            "SELECT" in sql_upper
            and "LIMIT" not in sql_upper
            and "COUNT" not in sql_upper
            and "SUM" not in sql_upper
            and "AVG" not in sql_upper
        ):
            sql = f"{sql} LIMIT {self.limite_lignes}"

        return sql + ";"

    def _formater_erreur(self, erreur_brute: str) -> str:
        """
        Formate le message d'erreur SQLAlchemy pour qu'il soit
        compréhensible par Llama dans le prompt de correction.

        SQLAlchemy produit des messages verbeux avec des stack traces.
        On extrait juste la partie utile.
        """
        # Extraire la ligne la plus informative de l'erreur
        lignes = erreur_brute.split("\n")
        for ligne in lignes:
            ligne = ligne.strip()
            # Les erreurs SQL utiles commencent souvent par ces patterns
            if any(
                pattern in ligne.lower()
                for pattern in [
                    "column", "table", "syntax", "relation",
                    "colonne", "tableau", "erreur", "error",
                    "does not exist", "n'existe pas"
                ]
            ):
                return ligne

        # Si on n'a pas trouvé de ligne spécifique, retourner les 200 premiers chars
        return erreur_brute[:200]