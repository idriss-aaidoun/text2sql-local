"""
app/utils.py
============
Fonctions utilitaires pour l'interface Streamlit.

Rôle : Tout ce qui touche à l'affichage et la mise en forme
des résultats — séparé de main.py pour garder le code lisible.
"""

import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# ── Affichage des résultats ───────────────────────────────────────────────────

def afficher_sql(sql: str, nb_corrections: int = 0) -> None:
    """Affiche le SQL généré avec un badge corrections si applicable."""
    label = "SQL généré"
    if nb_corrections > 0:
        label += f" — ✏️ {nb_corrections} correction(s) automatique(s)"
    st.code(sql, language="sql")
    if nb_corrections > 0:
        st.caption(
            f"⚠️ Le SQL initial était invalide. "
            f"Llama l'a corrigé automatiquement en {nb_corrections} tentative(s)."
        )


def afficher_resultats(df: pd.DataFrame) -> None:
    """
    Affiche le DataFrame avec des métriques et le tableau de données.
    """
    nb_lignes, nb_cols = df.shape
    col1, col2 = st.columns(2)
    col1.metric("Lignes retournées", nb_lignes)
    col2.metric("Colonnes", nb_cols)
    st.dataframe(df, use_container_width=True)


def afficher_explication(explication: str) -> None:
    """Affiche l'explication pédagogique dans une info-box."""
    if explication:
        st.info(f"💡 **Explication** : {explication}")


def afficher_erreur(erreur: str, bloque_securite: bool = False) -> None:
    """Affiche un message d'erreur formaté selon son type."""
    if bloque_securite:
        st.error(
            f"🛑 **Requête bloquée par sécurité**\n\n"
            f"{erreur}\n\n"
            f"Seules les requêtes SELECT sont autorisées."
        )
    else:
        st.error(f"❌ **Erreur d'exécution**\n\n{erreur}")


# ── Visualisation automatique Plotly ─────────────────────────────────────────

def detecter_type_visualisation(df: pd.DataFrame) -> str:
    """
    Détecte automatiquement le type de graphe le plus adapté au DataFrame.

    Logique de décision :
      - 1 colonne numérique + 1 colonne catégorielle  → bar chart
      - 1 colonne date + 1 colonne numérique          → line chart
      - 2 colonnes numériques                         → scatter
      - 1 seule colonne numérique                     → métrique
      - sinon                                         → tableau seulement

    Returns:
        "bar" | "line" | "scatter" | "metric" | "table"
    """
    if df.empty or len(df.columns) < 1:
        return "table"

    cols_num = df.select_dtypes(include=["number"]).columns.tolist()
    cols_cat = df.select_dtypes(include=["object", "category"]).columns.tolist()
    cols_date = [
        c for c in df.columns
        if "date" in c.lower() or "mois" in c.lower() or "month" in c.lower()
    ]

    if len(cols_date) >= 1 and len(cols_num) >= 1:
        return "line"
    if len(cols_cat) >= 1 and len(cols_num) >= 1:
        return "bar"
    if len(cols_num) >= 2:
        return "scatter"
    if len(cols_num) == 1 and len(df) == 1:
        return "metric"

    return "table"


def afficher_visualisation(df: pd.DataFrame) -> None:
    """
    Génère et affiche automatiquement la visualisation Plotly
    la plus adaptée aux données.
    """
    if df.empty:
        return

    type_viz = detecter_type_visualisation(df)
    cols_num = df.select_dtypes(include=["number"]).columns.tolist()
    cols_cat = df.select_dtypes(include=["object", "category"]).columns.tolist()
    cols_date = [
        c for c in df.columns
        if "date" in c.lower() or "mois" in c.lower() or "month" in c.lower()
    ]

    st.subheader("📊 Visualisation automatique")

    if type_viz == "bar" and cols_cat and cols_num:
        fig = px.bar(
            df,
            x=cols_cat[0],
            y=cols_num[0],
            title=f"{cols_num[0]} par {cols_cat[0]}",
            color=cols_cat[0],
        )
        st.plotly_chart(fig, use_container_width=True)

    elif type_viz == "line" and cols_date and cols_num:
        fig = px.line(
            df,
            x=cols_date[0],
            y=cols_num[0],
            title=f"Évolution de {cols_num[0]}",
            markers=True,
        )
        st.plotly_chart(fig, use_container_width=True)

    elif type_viz == "scatter" and len(cols_num) >= 2:
        fig = px.scatter(
            df,
            x=cols_num[0],
            y=cols_num[1],
            title=f"{cols_num[1]} vs {cols_num[0]}",
        )
        st.plotly_chart(fig, use_container_width=True)

    elif type_viz == "metric" and cols_num:
        valeur = df[cols_num[0]].iloc[0]
        st.metric(label=cols_num[0], value=f"{valeur:,.2f}")

    else:
        st.caption("Visualisation non disponible pour ce format de données.")


# ── Export ────────────────────────────────────────────────────────────────────

def bouton_export_csv(df: pd.DataFrame, nom_fichier: str = "resultats.csv") -> None:
    """Bouton de téléchargement CSV des résultats."""
    csv = df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="⬇️ Télécharger CSV",
        data=csv,
        file_name=nom_fichier,
        mime="text/csv",
    )


# ── Historique ────────────────────────────────────────────────────────────────

def afficher_historique_sidebar(historique_session: list[dict]) -> None:
    """
    Affiche l'historique des questions de la session dans la sidebar.

    Args:
        historique_session : liste de dicts {"question": ..., "succes": ...}
    """
    if not historique_session:
        st.sidebar.caption("Aucune question posée dans cette session.")
        return

    for i, item in enumerate(reversed(historique_session), 1):
        icone = "✅" if item["succes"] else "❌"
        st.sidebar.markdown(f"{icone} `{item['question'][:40]}...`"
                            if len(item["question"]) > 40
                            else f"{icone} `{item['question']}`")