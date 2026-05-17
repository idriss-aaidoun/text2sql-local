"""
core/memory.py
==============
Mémoire conversationnelle multi-tours

Rôle : Stocker l'historique des échanges pour que l'utilisateur puisse
faire référence aux résultats précédents dans ses questions.

Exemple de conversation multi-tours :
  Tour 1 : "liste les 5 clients qui ont dépensé le plus"
           → SQL généré et exécuté → résultats affichés

  Tour 2 : "maintenant montre-moi leurs commandes"
           ← La mémoire injecte le contexte du Tour 1
           → Llama comprend que "leurs" = les 5 clients du tour précédent

Sans mémoire, chaque question est traitée de façon isolée.
Avec mémoire, le système supporte des analyses en plusieurs étapes.

Implémentation volontairement simple :
  On stocke les N derniers échanges en mémoire (pas de base de données).
  La mémoire est réinitialisée à chaque redémarrage de l'app.
  Pour une V2, on pourrait persister dans PostgreSQL ou SQLite.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Tour:
    """Représente un échange question/SQL/résultat."""
    question: str
    sql: str
    succes: bool
    nb_resultats: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now().strftime("%H:%M:%S")
    )


class ConversationMemory:
    """
    Gère l'historique des échanges de la session courante.

    Stocke les N derniers tours et les formate en texte
    pour injection dans le prompt de génération SQL.

    Utilisation :
        memory = ConversationMemory(max_tours=5)

        # Après chaque génération réussie :
        memory.ajouter(
            question="liste les clients",
            sql="SELECT * FROM clients;",
            succes=True,
            nb_resultats=42,
        )

        # Dans le prompt de la question suivante :
        historique = memory.get_historique()
    """

    def __init__(self, max_tours: int = 5) -> None:
        """
        Args:
            max_tours : nombre maximum de tours conservés en mémoire.
                        5 = bon compromis entre contexte et taille du prompt.
                        Au-delà de 5, le prompt devient trop long pour Llama 3.1.
        """
        self.max_tours = max_tours
        self._historique: list[Tour] = []

    def ajouter(
        self,
        question: str,
        sql: str,
        succes: bool,
        nb_resultats: int = 0,
    ) -> None:
        """
        Ajoute un tour à l'historique.

        Si l'historique dépasse max_tours, supprime le plus ancien
        (stratégie FIFO — First In, First Out).

        Args:
            question     : question posée par l'utilisateur
            sql          : SQL généré (et éventuellement corrigé)
            succes       : True si le SQL a été exécuté avec succès
            nb_resultats : nombre de lignes retournées
        """
        tour = Tour(
            question=question,
            sql=sql,
            succes=succes,
            nb_resultats=nb_resultats,
        )
        self._historique.append(tour)

        # Garder seulement les max_tours derniers tours
        if len(self._historique) > self.max_tours:
            self._historique = self._historique[-self.max_tours:]

    def get_historique(self) -> str:
        """
        Formate l'historique en texte pour injection dans le prompt Llama.

        Format optimisé pour Llama 3.1 : court, structuré, informatif.

        Exemple de sortie :
            [10:23:15] Q: liste les clients
            SQL: SELECT * FROM clients; (42 résultats)

            [10:25:01] Q: quels clients habitent à Paris ?
            SQL: SELECT * FROM clients WHERE ville = 'Paris'; (8 résultats)

        Returns:
            Texte formaté de l'historique, ou message vide si aucun historique
        """
        if not self._historique:
            return "Aucun historique — première question de la session."

        lignes = []
        for tour in self._historique:
            statut = f"{tour.nb_resultats} résultats" if tour.succes else "échec"
            lignes.append(f"[{tour.timestamp}] Q: {tour.question}")
            lignes.append(f"SQL: {tour.sql} ({statut})")
            lignes.append("")

        return "\n".join(lignes).strip()

    def get_dernier_sql(self) -> str | None:
        """
        Retourne le dernier SQL exécuté avec succès.

        Utile pour des questions de type "modifie la requête précédente".
        """
        for tour in reversed(self._historique):
            if tour.succes:
                return tour.sql
        return None

    def reinitialiser(self) -> None:
        """Vide l'historique — appelé quand l'utilisateur clique 'Nouvelle session'."""
        self._historique = []

    @property
    def nb_tours(self) -> int:
        """Nombre de tours dans l'historique courant."""
        return len(self._historique)

    @property
    def est_vide(self) -> bool:
        """True si aucun échange n'a encore eu lieu."""
        return len(self._historique) == 0