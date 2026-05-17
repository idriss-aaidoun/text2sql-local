"""
core/security.py
================
Couche 5 — Partie A : Sécurité par analyse AST

Rôle : Analyser la structure syntaxique du SQL généré par Llama
et bloquer toute opération non autorisée AVANT l'exécution.

Pourquoi l'AST et pas juste une recherche de mots-clés ?
  Une recherche naïve de "DELETE" dans le texte serait contournée par :
    - "select * from clients -- DELETE"  (commentaire)
    - "select 'DELETE' as action"        (string SQL)
    - "select delete_date from commandes" (nom de colonne)

  L'analyse AST parse la requête comme le ferait la base de données
  et inspecte les TOKENS réels — pas le texte brut.
  sqlparse identifie chaque token avec son type (DDL, DML, Keyword...)
  donc "DELETE" dans un commentaire n'est pas un token DML.

Défense en profondeur :
  Cette couche est le 3ème rempart (après le prompt et le rôle BDD read-only).
  Les trois ensemble garantissent qu'aucune opération destructive
  ne peut atteindre la base, quelle que soit la sortie de Llama.
"""

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DDL, DML
from pydantic import BaseModel


# ── Modèles ───────────────────────────────────────────────────────────────────

class ResultatValidation(BaseModel):
    """Résultat structuré de la validation de sécurité."""
    valide: bool
    sql: str
    raison: str = ""          # message d'erreur si invalide
    type_requete: str = ""    # "SELECT", "INSERT", etc. (pour les logs)


# ── Constantes ────────────────────────────────────────────────────────────────

# Tous les mots-clés SQL qui peuvent modifier ou détruire des données
OPERATIONS_INTERDITES = {
    # DML — Data Manipulation Language (modification de données)
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
    # DDL — Data Definition Language (modification de structure)
    "DROP", "CREATE", "ALTER", "TRUNCATE", "RENAME",
    # DCL — Data Control Language (gestion des droits)
    "GRANT", "REVOKE",
    # TCL — Transaction Control Language
    "COMMIT", "ROLLBACK", "SAVEPOINT",
}

# Seule opération autorisée dans ce pipeline
OPERATIONS_AUTORISEES = {"SELECT"}


# ── Validateur principal ──────────────────────────────────────────────────────

class SQLSecurityValidator:
    """
    Valide la sécurité d'une requête SQL par analyse AST.

    Analyse trois niveaux de sécurité :
      1. Opération principale (SELECT vs DML/DDL)
      2. Sous-requêtes (pas de DELETE dans un WITH ou subquery)
      3. Requêtes multiples (pas de "SELECT 1; DROP TABLE clients;")

    Utilisation :
        validator = SQLSecurityValidator()
        resultat = validator.valider("SELECT * FROM clients;")
        if not resultat.valide:
            print(resultat.raison)  # "Opération interdite : DELETE"
    """

    def valider(self, sql: str) -> ResultatValidation:
        """
        Valide complètement la sécurité d'une requête SQL.

        Args:
            sql : requête SQL à valider (générée par Llama)

        Returns:
            ResultatValidation avec valide=True si SELECT pur,
            ou valide=False avec la raison du refus
        """
        if not sql or not sql.strip():
            return ResultatValidation(
                valide=False,
                sql=sql,
                raison="La requête SQL est vide.",
            )

        sql_propre = sql.strip()

        # Niveau 1 : vérifier les requêtes multiples (injection via ;)
        ok, raison = self._verifier_requete_unique(sql_propre)
        if not ok:
            return ResultatValidation(valide=False, sql=sql_propre, raison=raison)

        # Niveau 2 : parser et analyser les tokens AST
        try:
            statements = sqlparse.parse(sql_propre)
        except Exception as e:
            return ResultatValidation(
                valide=False,
                sql=sql_propre,
                raison=f"Impossible de parser le SQL : {e}",
            )

        if not statements:
            return ResultatValidation(
                valide=False,
                sql=sql_propre,
                raison="Aucune requête SQL détectée.",
            )

        statement = statements[0]

        # Niveau 3 : analyser le type de l'opération principale
        ok, raison, type_requete = self._verifier_operation(statement)
        if not ok:
            return ResultatValidation(
                valide=False,
                sql=sql_propre,
                raison=raison,
                type_requete=type_requete,
            )

        # Niveau 4 : vérifier les tokens cachés dans les sous-requêtes
        ok, raison = self._verifier_tokens_interdits(statement)
        if not ok:
            return ResultatValidation(
                valide=False,
                sql=sql_propre,
                raison=raison,
                type_requete=type_requete,
            )

        return ResultatValidation(
            valide=True,
            sql=sql_propre,
            type_requete=type_requete,
        )

    def _verifier_requete_unique(self, sql: str) -> tuple[bool, str]:
        """
        Vérifie qu'il n'y a qu'une seule requête SQL.

        Technique d'injection courante :
            "SELECT * FROM clients; DROP TABLE clients;"
        sqlparse.split() sépare les requêtes sur les ;
        """
        # Supprimer le point-virgule final avant de splitter
        sql_sans_fin = sql.rstrip(";").strip()

        if ";" in sql_sans_fin:
            return False, (
                "Requêtes multiples détectées (plusieurs ';'). "
                "Une seule requête SELECT est autorisée."
            )
        return True, ""

    def _verifier_operation(
        self, statement: Statement
    ) -> tuple[bool, str, str]:
        """
        Analyse les tokens AST pour identifier l'opération principale.

        sqlparse parse le SQL en tokens typés :
          Token(DDL, 'DROP')    → type DDL
          Token(DML, 'SELECT')  → type DML
          Token(DML, 'INSERT')  → type DML

        On parcourt les tokens et on cherche le premier token
        de type DDL ou DML — c'est l'opération principale.
        """
        for token in statement.tokens:
            # Ignorer les espaces et commentaires
            if token.is_whitespace or token.ttype is sqlparse.tokens.Comment.Single:
                continue

            # Token DDL trouvé (CREATE, DROP, ALTER, TRUNCATE...)
            if token.ttype is DDL:
                valeur = token.normalized.upper()
                return (
                    False,
                    f"Opération DDL interdite : {valeur}. "
                    f"Seules les requêtes SELECT sont autorisées.",
                    valeur,
                )

            # Token DML trouvé (SELECT, INSERT, UPDATE, DELETE...)
            if token.ttype is DML:
                valeur = token.normalized.upper()
                if valeur in OPERATIONS_AUTORISEES:
                    return True, "", valeur
                else:
                    return (
                        False,
                        f"Opération DML interdite : {valeur}. "
                        f"Seules les requêtes SELECT sont autorisées.",
                        valeur,
                    )

        # Si aucun token DML/DDL trouvé, c'est suspect
        return False, "Type de requête non reconnu — requête refusée par sécurité.", ""

    def _verifier_tokens_interdits(
        self, statement: Statement
    ) -> tuple[bool, str]:
        """
        Parcourt TOUS les tokens (y compris dans les sous-requêtes)
        et détecte les mots-clés interdits cachés.

        flatten() aplatit l'arbre AST — retourne tous les tokens
        feuilles, même ceux profondément imbriqués dans des
        sous-requêtes ou des expressions WITH.
        """
        for token in statement.flatten():
            if token.ttype in (DDL, DML):
                valeur = token.normalized.upper()
                if valeur in OPERATIONS_INTERDITES:
                    return (
                        False,
                        f"Opération interdite détectée dans la requête : {valeur}",
                    )
        return True, ""


# ── Fonctions utilitaires ─────────────────────────────────────────────────────

# Instance globale réutilisable (pattern Singleton léger)
_validator = SQLSecurityValidator()


def valider_sql(sql: str) -> ResultatValidation:
    """
    Fonction utilitaire — point d'entrée principal de la Couche 5.

    Utilisation depuis le pipeline :
        from core.security import valider_sql
        resultat = valider_sql(sql_genere)
        if not resultat.valide:
            return {"erreur": resultat.raison}
    """
    return _validator.valider(sql)


def est_select_valide(sql: str) -> bool:
    """Version booléenne simplifiée pour les vérifications rapides."""
    return _validator.valider(sql).valide