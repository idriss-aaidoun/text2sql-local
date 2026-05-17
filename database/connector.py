"""
database/connector.py
=====================
Connexion sécurisée à la base de données en mode READ-ONLY.

Principe de sécurité fondamental :
  Le pipeline NL2SQL ne doit JAMAIS pouvoir modifier les données.
  On crée un utilisateur PostgreSQL avec uniquement le droit SELECT.
  Même si Llama génère un DELETE, la base refusera l'exécution
  au niveau du driver — indépendamment de la Couche 5.

  C'est ce qu'on appelle la "défense en profondeur" :
  plusieurs couches de sécurité indépendantes.

  Couche 5 (security.py)  -> bloque au niveau applicatif (AST)
  connector.py            -> bloque au niveau base de données (droits)
  Les deux ensemble       -> sécurité production-ready
"""

import os
from sqlalchemy import create_engine, text, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from dotenv import load_dotenv

load_dotenv()


def creer_engine_readonly(db_url: str | None = None) -> Engine:
    """
    Crée un engine SQLAlchemy configuré pour la lecture seule.

    Pour PostgreSQL : utilise un rôle dédié avec GRANT SELECT uniquement.
    Pour SQLite     : ouvre la base en mode URI read-only.

    Args:
        db_url : URL de connexion. Si None, lit DATABASE_URL depuis .env

    Returns:
        Engine SQLAlchemy configuré en read-only
    """
    url = db_url or os.getenv("DATABASE_URL", "sqlite:///./demo.db")

    if url.startswith("sqlite"):
        # SQLite : mode read-only via URI
        # On remplace sqlite:/// par sqlite+pysqlite:///file:...?mode=ro
        chemin = url.replace("sqlite:///", "")
        url_readonly = f"sqlite+pysqlite:///file:{chemin}?mode=ro&uri=true"
        engine = create_engine(url_readonly)
    else:
        # PostgreSQL : connexion standard
        # La restriction read-only est assurée par les droits du rôle PostgreSQL
        # Voir le README pour créer le rôle : CREATE ROLE nl2sql_reader...
        engine = create_engine(
            url,
            pool_pre_ping=True,    # vérifie la connexion avant utilisation
            pool_size=5,           # pool de 5 connexions simultanées
            max_overflow=10,       # jusqu'à 10 connexions supplémentaires
        )

        # Intercepteur SQLAlchemy : bloque tout ce qui n'est pas SELECT
        # au niveau du driver, avant même d'envoyer à la base
        @event.listens_for(engine, "before_cursor_execute")
        def bloquer_non_select(conn, cursor, statement, parameters, context, executemany):
            stmt_upper = statement.strip().upper()
            mots_interdits = {
                "INSERT", "UPDATE", "DELETE", "DROP",
                "TRUNCATE", "ALTER", "CREATE", "GRANT", "REVOKE"
            }
            premier_mot = stmt_upper.split()[0] if stmt_upper.split() else ""
            if premier_mot in mots_interdits:
                raise PermissionError(
                    f"Opération interdite : {premier_mot}. "
                    "Ce pipeline est configuré en lecture seule."
                )

    return engine


def tester_connexion(engine: Engine) -> tuple[bool, str]:
    """
    Teste la connexion à la base de données.

    Returns:
        (True, "OK") si la connexion fonctionne
        (False, message_erreur) sinon
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "Connexion OK"
    except SQLAlchemyError as e:
        return False, str(e)