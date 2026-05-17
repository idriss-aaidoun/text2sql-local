"""
app/main.py
===========
Interface Streamlit — Point d'entrée de l'application NL2SQL-Local

Lancer l'application :
    streamlit run app/main.py

Architecture de l'interface :
  ┌─────────────────────────────────────────────┐
  │  Sidebar                                    │
  │  - Connexion BDD + statut                   │
  │  - Historique session                       │
  │  - Bouton nouvelle session                  │
  ├─────────────────────────────────────────────┤
  │  Zone principale                            │
  │  - Titre + description                      │
  │  - Zone de saisie question                  │
  │  - Résultats :                              │
  │      SQL généré (avec corrections)          │
  │      Explication pédagogique                │
  │      Tableau de données                     │
  │      Visualisation Plotly automatique       │
  │      Bouton export CSV                      │
  └─────────────────────────────────────────────┘

Gestion du state Streamlit :
  Streamlit re-exécute tout le script à chaque interaction.
  st.session_state permet de conserver les données entre les runs :
    - pipeline        : instance NL2SQLPipeline (évite de recharger Llama)
    - historique      : liste des questions de la session
    - dernier_resultat: dernier RésultatPipeline affiché
"""

import sys
import os

# Ajouter la racine du projet au PATH Python
# Nécessaire pour que "from core.xxx import" fonctionne
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import pandas as pd

from core.pipeline import NL2SQLPipeline
from app.utils import (
    afficher_sql,
    afficher_resultats,
    afficher_explication,
    afficher_erreur,
    afficher_visualisation,
    bouton_export_csv,
    afficher_historique_sidebar,
)


# ── Configuration Streamlit ───────────────────────────────────────────────────

st.set_page_config(
    page_title="NL2SQL Local",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── Initialisation du pipeline (une seule fois) ───────────────────────────────

@st.cache_resource(show_spinner="Chargement du pipeline NL2SQL (30-60s sur CPU)...")
def charger_pipeline() -> NL2SQLPipeline:
    """
    Charge et initialise le pipeline NL2SQL.

    @st.cache_resource : Streamlit garde cette ressource en cache
    entre les reruns — le pipeline n'est créé qu'une seule fois.
    Sans ça, Llama serait rechargé à chaque question (inacceptable).
    """
    pipeline = NL2SQLPipeline()
    pipeline.initialiser()
    return pipeline


# ── Session state ─────────────────────────────────────────────────────────────

if "historique_session" not in st.session_state:
    st.session_state.historique_session = []

if "dernier_resultat" not in st.session_state:
    st.session_state.dernier_resultat = None


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🗄️ NL2SQL Local")
    st.caption("Stack 100% locale • 0 €/mois")
    st.divider()

    # Statut de connexion
    st.subheader("⚙️ Configuration")
    db_url = os.getenv("DATABASE_URL", "sqlite:///./demo.db")
    st.code(db_url, language="text")

    ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1")
    st.caption(f"🤖 Modèle : `{ollama_model}`")
    st.divider()

    # Historique de la session
    st.subheader("📋 Historique")
    afficher_historique_sidebar(st.session_state.historique_session)
    st.divider()

    # Bouton nouvelle session
    if st.button("🔄 Nouvelle session", use_container_width=True):
        try:
            pipeline = charger_pipeline()
            pipeline.nouvelle_session()
        except Exception:
            pass
        st.session_state.historique_session = []
        st.session_state.dernier_resultat = None
        st.rerun()

    # Informations architecture
    st.divider()
    st.subheader("🏗️ Architecture")
    st.markdown("""
    **Couche 1** — Schema RAG  
    **Couche 2** — Few-Shot  
    **Couche 3** — Llama 3.1  
    **Couche 4** — LangGraph  
    **Couche 5** — Sécurité  
    """)


# ── Zone principale ───────────────────────────────────────────────────────────

st.title("💬 Interrogez votre base en langage naturel")
st.caption(
    "Posez votre question en français ou en anglais. "
    "Le système génère et exécute automatiquement la requête SQL."
)

# ── Exemples cliquables ───────────────────────────────────────────────────────

st.subheader("💡 Exemples de questions")
exemples = [
    "Combien de clients y a-t-il ?",
    "Liste les 5 produits les plus chers",
    "Quels clients ont passé plus de 3 commandes ?",
    "Quel est le chiffre d'affaires total par mois ?",
    "Quels produits n'ont jamais été commandés ?",
]

cols = st.columns(len(exemples))
question_exemple = None
for i, (col, exemple) in enumerate(zip(cols, exemples)):
    if col.button(exemple, key=f"ex_{i}", use_container_width=True):
        question_exemple = exemple


# ── Formulaire de saisie ──────────────────────────────────────────────────────

st.subheader("✍️ Votre question")

with st.form("formulaire_question", clear_on_submit=False):
    question = st.text_input(
        label="Question",
        value=question_exemple or "",
        placeholder="Ex : Quels clients habitent à Paris et ont commandé en janvier ?",
        label_visibility="collapsed",
    )
    col_submit, col_info = st.columns([1, 4])
    soumettre = col_submit.form_submit_button(
        "🚀 Générer SQL",
        use_container_width=True,
        type="primary",
    )
    col_info.caption(
        "⏱️ Première requête : 30-60s (chargement Llama). "
        "Les suivantes sont plus rapides."
    )


# ── Traitement de la question ─────────────────────────────────────────────────

if soumettre and question.strip():

    with st.spinner("⚙️ Traitement en cours... (Couches 1→2→3→5→4→5)"):
        try:
            pipeline = charger_pipeline()
            resultat = pipeline.executer(question.strip())

            # Sauvegarder dans le session state
            st.session_state.dernier_resultat = resultat
            st.session_state.historique_session.append({
                "question": question.strip(),
                "succes": resultat.succes,
            })

        except ConnectionError:
            st.error(
                "❌ **Impossible de se connecter à Ollama.**\n\n"
                "Vérifiez que Ollama est démarré : `ollama serve`\n"
                "Et que Llama 3.1 est installé : `ollama pull llama3.1`"
            )
            st.stop()

        except Exception as e:
            st.error(f"❌ **Erreur inattendue :** {e}")
            st.stop()

elif soumettre and not question.strip():
    st.warning("⚠️ Veuillez saisir une question avant de soumettre.")


# ── Affichage des résultats ───────────────────────────────────────────────────

if st.session_state.dernier_resultat is not None:
    resultat = st.session_state.dernier_resultat

    st.divider()
    st.subheader("📊 Résultats")

    if not resultat.succes:
        # Cas d'erreur
        afficher_erreur(
            erreur=resultat.erreur,
            bloque_securite=resultat.bloque_securite,
        )
        st.subheader("🔍 SQL généré (refusé)")
        afficher_sql(resultat.sql, nb_corrections=resultat.nb_corrections)

    else:
        # Cas de succès — affichage en onglets
        tab_resultats, tab_sql, tab_viz = st.tabs([
            "📋 Données",
            "🔍 SQL",
            "📈 Visualisation",
        ])

        with tab_resultats:
            afficher_explication(resultat.explication)
            afficher_resultats(resultat.donnees)
            bouton_export_csv(resultat.donnees)

        with tab_sql:
            afficher_sql(resultat.sql, nb_corrections=resultat.nb_corrections)

            # Métriques de la requête
            col1, col2, col3 = st.columns(3)
            col1.metric("Lignes retournées", resultat.nb_resultats)
            col2.metric("Corrections LangGraph", resultat.nb_corrections)
            col3.metric(
                "Statut sécurité",
                "✅ SELECT" if not resultat.bloque_securite else "🛑 Bloqué"
            )

        with tab_viz:
            if resultat.donnees is not None and not resultat.donnees.empty:
                afficher_visualisation(resultat.donnees)
            else:
                st.info("Aucune donnée à visualiser.")


# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
st.caption(
    "NL2SQL-Local v1.0 • Stack 100% locale • "
    "Llama 3.1 8B + LangChain + ChromaDB + LangGraph • "
    "0 €/mois • Données confidentielles"
)