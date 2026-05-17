# Interface Streamlit — Orchestration des 5 Couches NL2SQL

## 📊 Vue d'ensemble de l'architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    INTERFACE STREAMLIT                          │
│  (affichage utilisateur, formulaires, visualisations)           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
         ┌──────────────────────────────────────┐
         │    PIPELINE NL2SQL (core/pipeline.py)│
         │  Orchestrateur des 5 couches         │
         └──────────────────────────────────────┘
                      │        │
        ┌─────────────┼────────┼──────────┬──────────────┐
        │             │        │          │              │
        ▼             ▼        ▼          ▼              ▼
    ┌──────┐    ┌──────┐  ┌──────┐  ┌──────┐       ┌──────┐
    │  C1  │    │  C2  │  │  C3  │  │  C5  │       │  C4  │
    │  S.R │    │ F.S. │  │  SQL │  │ SEC. │       │ AUTO │
    │      │    │      │  │ GEN. │  │ VAL. │       │ CORR │
    └──────┘    └──────┘  └──────┘  └──────┘       └──────┘
        │           │          │        │              │
        └───────────┴──────────┴────────┴──────────────┘
                            │
                            ▼
            ┌─────────────────────────────┐
            │  BASE DE DONNÉES (READ-ONLY)│
            │  + Mémoire conversationnelle│
            └─────────────────────────────┘
```

---

## 🔄 Les 5 Couches Expliquées

### **Couche 1 : SchemaRetriever (Récupération de schéma)**
**Fichier** : `core/schema_retriever.py`  
**Rôle** : Indexer le schéma SQL et retrouver les tables pertinentes par similarité sémantique.

```
Question utilisateur
    ↓ Embedding (all-MiniLM-L6-v2)
Vecteur de 384 dimensions
    ↓ ChromaDB similarity_search
Tables les plus proches (cosine similarity)
    ↓
Texte des tables injecté dans le prompt
```

**Exemple** :
- Question : "quels clients habitent à Paris ?"
- ChromaDB retourne les tables `clients` et `villes`
- Llama reçoit : `"Table clients : id INT, nom VARCHAR, ville VARCHAR..."`

---

### **Couche 2 : FewShotSelector (Sélection dynamique d'exemples)**
**Fichier** : `core/few_shot_selector.py`  
**Rôle** : Sélectionner les exemples NL→SQL les plus pertinents pour "montrer l'exemple" à Llama.

```
Question utilisateur
    ↓ Embedding
Vecteur question
    ↓ ChromaDB similarity_search (collection "few_shot_examples")
3 questions + SQL les plus proches
    ↓
Formatés en texte pour le prompt Llama
```

**Exemple** :
- Si la question porte sur un `GROUP BY`, les exemples avec `GROUP BY` seront sélectionnés
- Llama "voit" immédiatement le patron SQL attendu

---

### **Couche 3 : SQLGenerator (Génération SQL)**
**Fichier** : `core/sql_generator.py`  
**Rôle** : Assembler le prompt, l'envoyer à Llama 3.1 via Ollama, et retourner le SQL brut nettoyé.

```
Inputs :
  - Schéma pertinent (C1)
  - Exemples few-shot (C2)
  - Historique conversationnel
  - Question utilisateur
    ↓
PROMPT_GENERATION (template structuré)
    ↓
Llama 3.1 (via Ollama local)
    ↓
StrOutputParser
    ↓
SQL brut nettoyé (sans markdown ni commentaires)
```

**Configuration** :
- `temperature = 0.0` (déterministe : toujours le même SQL pour la même question)
- `num_ctx = 4096` tokens (fenêtre de contexte)
- `num_thread = 4` (parallélisme CPU)

---

### **Couche 5 : Sécurité et Explication (Double validation)**

#### **Couche 5A : SQLSecurityValidator (Validation sécurité)**
**Fichier** : `core/security.py`  
**Rôle** : Analyser l'AST (Abstract Syntax Tree) et bloquer les opérations non-SELECT.

```
SQL généré par Llama
    ↓ sqlparse.parse()
AST (tokens avec types)
    ↓ Analyse : recherche les mots-clés DDL/DML
    ├─ SELECT ✅ Autorisé
    ├─ INSERT ❌ Bloqué
    ├─ DELETE ❌ Bloqué
    ├─ DROP   ❌ Bloqué
    └─ ALTER  ❌ Bloqué
    ↓
ResultatValidation { valide, sql, raison, type_requete }
```

**Trois niveaux de vérification** :
1. Requête unique (pas de `;` suivi d'un autre SQL)
2. Opération principale (SELECT pur)
3. Pas de sous-requêtes avec DML

#### **Couche 5B : SQLExplainer (Explication pédagogique)**
**Fichier** : `core/explainer.py`  
**Rôle** : Générer une explication en français simple du SQL validé.

```
SQL valide + Question originale
    ↓
PROMPT_EXPLICATION
    ↓
Llama 3.1 (temperature=0.3, plus naturel)
    ↓
Explication en 2-3 phrases compréhensibles
```

**Exemple** :
```
SQL  : SELECT c.nom, COUNT(cmd.id) AS nb FROM clients c 
       LEFT JOIN commandes cmd ON c.id = cmd.id_client 
       GROUP BY c.id HAVING COUNT(cmd.id) > 3;

Explication : "Cette requête affiche tous les clients qui ont passé 
              plus de 3 commandes, avec le nombre de commandes 
              pour chacun."
```

---

### **Couche 4 : SelfCorrectionPipeline (Auto-correction avec LangGraph)**
**Fichier** : `core/sql_validator.py`  
**Rôle** : Exécuter le SQL et le corriger automatiquement s'il échoue.

```
SQL généré (ou corrigé)
    ↓
[Noeud EXECUTER]
    ├─ Succès ✅ → END (retourner les résultats)
    └─ Échec  ❌ → [Noeud CORRIGER]
                      ↓ Llama : "corrige ce SQL" + message d'erreur
                      ↓ SQL corrigé
                      ↓ Retour à EXECUTER (tentative suivante)
                      ↓ Max 3 tentatives
```

**État du graphe** :
```python
class EtatCorrection(TypedDict):
    question: str           # Question originale
    schema: str             # Schéma pertinent
    sql: str                # SQL courant
    erreur: str             # Dernier message d'erreur
    tentatives: int         # Nombre de corrections
    resultat: Optional[str] # DataFrame sérialisé en JSON
    abandon: bool           # True si >= 3 tentatives
```

---

## 📦 Modèle de résultat retourné par le pipeline

```python
class RésultatPipeline(BaseModel):
    """Résultat complet retourné par le pipeline à l'interface Streamlit."""
    succes: bool                    # True si succès, False sinon
    question: str                   # Question originale
    sql: str                        # SQL final (original ou corrigé)
    donnees: Optional[pd.DataFrame] # Résultats si succes=True
    explication: str                # Explication pédagogique
    nb_resultats: int = 0           # Nombre de lignes retournées
    nb_corrections: int = 0         # Nombre de corrections effectuées
    erreur: Optional[str] = None    # Message d'erreur si succes=False
    bloque_securite: bool = False   # True si bloqué par Couche 5A
```

---

## 🎨 Interface Streamlit — Structure recommandée

### **Layout global**

```
┌──────────────────────────────────────────────────────────────┐
│                  NL2SQL INTERFACE                             │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  🏠 Accueil  |  💬 Chat  |  📊 Historique  |  ⚙️ Paramètres  │
│                                                                │
├──────────────────────────────────────────────────────────────┤
│                                                                │
│  CONTENU DYNAMIQUE (selon l'onglet actif)                    │
│                                                                │
└──────────────────────────────────────────────────────────────┘
```

### **Onglet "Chat" (Principal)**

```
┌─────────────────────────────────────────────────────────────┐
│  💬 Interface de Chat                                        │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ HISTORIQUE DE CONVERSATION                             │  │
│  │                                                         │  │
│  │ T1 : "Quels sont les 5 clients VIP ?"                 │  │
│  │      ✅ Succès | SQL exécuté | 5 résultats            │  │
│  │                                                         │  │
│  │ T2 : "Leurs commandes en 2024"                        │  │
│  │      ✅ Succès | 1 correction | 42 résultats          │  │
│  │                                                         │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  Nouvelle question :                                  │  │
│  │                                                       │  │
│  │  ┌─────────────────────────────────────────────────┐ │  │
│  │  │ [Posez votre question ici...]                 │ │  │
│  │  └─────────────────────────────────────────────────┘ │  │
│  │                                                       │  │
│  │  [🔄 Exécuter]  [🔄 Nouvelle session]  [⌛ Loading...] │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### **Onglet "Résultats" (Après exécution)**

```
┌─────────────────────────────────────────────────────────────┐
│  📊 Résultats de la Requête                                  │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  QUESTION POSÉE                                             │
│  ► "Quels clients ont dépensé plus de 1000€ en 2024 ?"    │
│                                                               │
│  ─────────────────────────────────────────────────────────  │
│                                                               │
│  SQL GÉNÉRÉ                                                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ SELECT c.id, c.nom, SUM(cmd.montant) as total      │   │
│  │ FROM clients c                                     │   │
│  │ JOIN commandes cmd ON c.id = cmd.id_client        │   │
│  │ WHERE YEAR(cmd.date) = 2024                       │   │
│  │ GROUP BY c.id                                     │   │
│  │ HAVING SUM(cmd.montant) > 1000;                  │   │
│  └─────────────────────────────────────────────────────┘   │
│  ✅ Sécurité : SELECT pur (3 tables pertinentes)           │
│                                                               │
│  ─────────────────────────────────────────────────────────  │
│                                                               │
│  EXPLICATION PÉDAGOGIQUE                                   │
│  Cette requête affiche tous les clients qui ont dépensé    │
│  plus de 1000€ en 2024, avec le montant total de leurs    │
│  commandes triées par client.                              │
│                                                               │
│  ─────────────────────────────────────────────────────────  │
│                                                               │
│  RÉSULTATS (15 lignes trouvées)                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ id │ nom                  │ total   │                 │  │
│  ├────┼──────────────────────┼─────────┤                 │  │
│  │ 5  │ Jean Dupont          │ 2540€   │                 │  │
│  │ 12 │ Marie Martin         │ 1850€   │                 │  │
│  │ 8  │ Pierre Bernard       │ 1200€   │                 │  │
│  │ ... (12 lignes de plus)                               │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                               │
│  📊 Visualisation : [Graphique Plotly]                      │
│  [Histogramme des dépenses]                                 │
│                                                               │
│  ─────────────────────────────────────────────────────────  │
│  📈 Statistiques de la requête                              │
│  • Temps d'exécution : 0.42s                                │
│  • Corrections appliquées : 0                                │
│  • Tables utilisées : clients, commandes                    │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

### **Onglet "Historique"**

```
┌─────────────────────────────────────────────────────────────┐
│  📚 Historique de Session                                    │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  [Filtrer par : ✅ Succès | ❌ Erreurs | 🔧 Corrections]   │
│                                                               │
│  Tour 1 | 14:23:45 | ✅ SUCCÈS                             │
│  ├─ Question : "Clients à Paris"                           │
│  ├─ SQL : SELECT * FROM clients WHERE ville = 'Paris';   │
│  ├─ Résultats : 42 lignes                                 │
│  └─ Corrections : 0                                        │
│                                                               │
│  Tour 2 | 14:24:12 | ✅ SUCCÈS (1 correction)             │
│  ├─ Question : "Commandes de janvier"                     │
│  ├─ SQL : SELECT * FROM commandes ...                    │
│  ├─ Résultats : 256 lignes                                │
│  └─ Corrections : 1 (erreur de syntaxe → rechapé)        │
│                                                               │
│  Tour 3 | 14:25:03 | ❌ ERREUR                             │
│  ├─ Question : "Les produits les plus commandés"         │
│  ├─ Erreur : Colonne 'commandes_count' inexistante        │
│  ├─ Raison : 3 tentatives échouées                        │
│  └─ [💡 Conseil : Reformulez votre question]              │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 🔧 Code de base de l'interface Streamlit

Voici le code recommandé pour `app/main.py` :

```python
"""
app/main.py
===========
Interface Streamlit pour le pipeline NL2SQL.

Lancer l'application :
    streamlit run app/main.py

Navigateur :
    http://localhost:8501
"""

import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.graph_objects as go

# Configuration Streamlit
st.set_page_config(
    page_title="NL2SQL Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

# CSS personnalisé
st.markdown("""
<style>
    .main {
        padding-top: 2rem;
    }
    .stTabs [data-baseweb="tab-list"] button {
        font-size: 16px;
        padding: 10px 20px;
    }
    .success-box {
        background-color: #d4edda;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-top: 1rem;
    }
    .error-box {
        background-color: #f8d7da;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-top: 1rem;
    }
    .info-box {
        background-color: #d1ecf1;
        padding: 1rem;
        border-radius: 0.5rem;
        margin-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────────────────────
# INITIALISATION DE SESSION
# ──────────────────────────────────────────────────────────────────────────────

@st.cache_resource
def initialiser_pipeline():
    """Charge le pipeline NL2SQL une seule fois."""
    from core.pipeline import NL2SQLPipeline
    pipeline = NL2SQLPipeline()
    pipeline.initialiser()
    return pipeline

if "pipeline" not in st.session_state:
    with st.spinner("🚀 Chargement du pipeline NL2SQL..."):
        st.session_state.pipeline = initialiser_pipeline()

if "historique" not in st.session_state:
    st.session_state.historique = []

if "dernier_resultat" not in st.session_state:
    st.session_state.dernier_resultat = None

# ──────────────────────────────────────────────────────────────────────────────
# HEADER
# ──────────────────────────────────────────────────────────────────────────────

col1, col2 = st.columns([4, 1])
with col1:
    st.title("🤖 NL2SQL Chat")
    st.markdown("Converser avec vos données en français — alimenté par Llama 3.1 local")
with col2:
    if st.button("🔄 Nouvelle session", help="Réinitialiser la mémoire conversationnelle"):
        st.session_state.pipeline.nouvelle_session()
        st.session_state.historique = []
        st.session_state.dernier_resultat = None
        st.success("✅ Nouvelle session démarrée")

st.divider()

# ──────────────────────────────────────────────────────────────────────────────
# ONGLETS PRINCIPAUX
# ──────────────────────────────────────────────────────────────────────────────

tab_chat, tab_resultats, tab_historique, tab_parametres = st.tabs(
    ["💬 Chat", "📊 Résultats", "📚 Historique", "⚙️ Paramètres"]
)

# ──────────────────────────────────────────────────────────────────────────────
# ONGLET 1 : CHAT
# ──────────────────────────────────────────────────────────────────────────────

with tab_chat:
    st.subheader("💬 Posez votre question")
    
    # Affichage de l'historique conversationnel
    if st.session_state.historique:
        st.markdown("### Historique de cette session")
        for i, tour in enumerate(st.session_state.historique, 1):
            with st.expander(
                f"Tour {i} | {tour['timestamp']} | "
                f"{'✅ Succès' if tour['succes'] else '❌ Erreur'} "
                f"({tour.get('nb_resultats', 0)} résultats)"
            ):
                st.markdown(f"**Question** : {tour['question']}")
                st.markdown("**SQL généré** :")
                st.code(tour['sql'], language='sql')
                if tour['succes']:
                    st.info(f"✅ Exécuté avec succès ({tour['nb_resultats']} lignes)")
                    if tour['nb_corrections'] > 0:
                        st.warning(f"⚠️ {tour['nb_corrections']} correction(s) appliquée(s)")
                else:
                    st.error(f"❌ Erreur : {tour.get('erreur', 'Inconnu')}")
    
    st.divider()
    
    # Formulaire de saisie
    st.markdown("### Nouvelle question")
    col_input, col_btn = st.columns([4, 1])
    
    with col_input:
        question = st.text_input(
            "Votre question en français :",
            placeholder="Ex: Quels clients habitent à Paris ?",
            label_visibility="collapsed"
        )
    
    with col_btn:
        executer = st.button("🔄 Exécuter", use_container_width=True, type="primary")
    
    # Traitement de la question
    if executer and question:
        st.session_state.en_cours = True
        
        with st.spinner("⏳ Traitement de votre question..."):
            resultat = st.session_state.pipeline.executer(question)
        
        st.session_state.dernier_resultat = resultat
        
        # Enregistrer dans l'historique
        st.session_state.historique.append({
            "question": question,
            "sql": resultat.sql,
            "succes": resultat.succes,
            "nb_resultats": resultat.nb_resultats,
            "nb_corrections": resultat.nb_corrections,
            "erreur": resultat.erreur,
            "bloque_securite": resultat.bloque_securite,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        })
        
        # Affichage du résultat
        st.divider()
        st.markdown("### 📋 Résultats")
        
        if resultat.bloque_securite:
            st.error(f"🛑 Requête bloquée par la sécurité : {resultat.erreur}")
        elif resultat.succes:
            st.success(f"✅ Exécuté avec succès ({resultat.nb_resultats} résultats)")
            
            # Afficher l'explication
            with st.expander("📖 Explication pédagogique", expanded=True):
                st.info(resultat.explication)
            
            # Afficher le SQL
            with st.expander("🔍 SQL généré", expanded=False):
                st.code(resultat.sql, language='sql')
                if resultat.nb_corrections > 0:
                    st.info(f"💡 {resultat.nb_corrections} correction(s) appliquée(s) automatiquement")
            
            # Afficher les résultats en tableau
            st.markdown("#### 📊 Tableau de résultats")
            st.dataframe(resultat.donnees, use_container_width=True)
            
            # Visualisation Plotly si applicable
            if len(resultat.donnees) > 0 and len(resultat.donnees.columns) >= 2:
                try:
                    first_col = resultat.donnees.columns[0]
                    second_col = resultat.donnees.columns[1]
                    
                    if pd.api.types.is_numeric_dtype(resultat.donnees[second_col]):
                        fig = go.Figure(data=[
                            go.Bar(
                                x=resultat.donnees[first_col],
                                y=resultat.donnees[second_col],
                                name=second_col
                            )
                        ])
                        fig.update_layout(
                            title=f"{second_col} par {first_col}",
                            xaxis_title=first_col,
                            yaxis_title=second_col,
                            height=400
                        )
                        st.plotly_chart(fig, use_container_width=True)
                except:
                    pass  # Pas de visualisation si les colonnes ne conviennent pas
        
        else:
            st.error(f"❌ Erreur lors de l'exécution : {resultat.erreur}")
            st.code(resultat.sql, language='sql')

# ──────────────────────────────────────────────────────────────────────────────
# ONGLET 2 : RÉSULTATS
# ──────────────────────────────────────────────────────────────────────────────

with tab_resultats:
    st.subheader("📊 Résultats détaillés")
    
    if st.session_state.dernier_resultat is None:
        st.info("💡 Posez d'abord une question dans l'onglet Chat")
    else:
        resultat = st.session_state.dernier_resultat
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Question posée")
            st.write(resultat.question)
            
            st.markdown("### Statut")
            if resultat.succes:
                st.success(f"✅ Succès")
            else:
                st.error(f"❌ Erreur")
        
        with col2:
            st.markdown("### Statistiques")
            st.metric("Résultats", resultat.nb_resultats)
            st.metric("Corrections", resultat.nb_corrections)
        
        st.divider()
        
        st.markdown("### SQL généré")
        st.code(resultat.sql, language='sql')
        
        st.markdown("### Explication")
        st.info(resultat.explication)
        
        if resultat.succes and resultat.donnees is not None:
            st.markdown("### Données")
            st.dataframe(resultat.donnees, use_container_width=True)

# ──────────────────────────────────────────────────────────────────────────────
# ONGLET 3 : HISTORIQUE
# ──────────────────────────────────────────────────────────────────────────────

with tab_historique:
    st.subheader("📚 Historique complet")
    
    if not st.session_state.historique:
        st.info("💡 Aucune question posée pour le moment")
    else:
        # Filtres
        col1, col2, col3 = st.columns(3)
        with col1:
            filtre_succes = st.checkbox("✅ Succès", value=True)
        with col2:
            filtre_erreurs = st.checkbox("❌ Erreurs", value=True)
        with col3:
            filtre_corrections = st.checkbox("🔧 Corrections", value=False)
        
        # Affichage filtré
        historique_filtre = []
        for tour in st.session_state.historique:
            if filtre_succes and tour['succes']:
                historique_filtre.append(tour)
            elif filtre_erreurs and not tour['succes']:
                historique_filtre.append(tour)
            elif filtre_corrections and tour['nb_corrections'] > 0:
                historique_filtre.append(tour)
        
        for i, tour in enumerate(historique_filtre, 1):
            with st.expander(
                f"Tour {i} | {tour['timestamp']} | "
                f"{'✅' if tour['succes'] else '❌'} | "
                f"{tour['nb_resultats']} résultats"
            ):
                st.markdown(f"**Question** : {tour['question']}")
                st.code(tour['sql'], language='sql')
                
                if tour['succes']:
                    st.success(f"✅ {tour['nb_resultats']} résultats")
                    if tour['nb_corrections'] > 0:
                        st.warning(f"⚠️ {tour['nb_corrections']} correction(s)")
                else:
                    st.error(f"❌ {tour['erreur']}")

# ──────────────────────────────────────────────────────────────────────────────
# ONGLET 4 : PARAMÈTRES
# ──────────────────────────────────────────────────────────────────────────────

with tab_parametres:
    st.subheader("⚙️ Paramètres de l'application")
    
    st.markdown("### Configuration du pipeline")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.metric("Modèle LLM", "Llama 3.1")
        st.metric("Embeddings", "all-MiniLM-L6-v2")
    
    with col2:
        st.metric("Vector Store", "ChromaDB")
        st.metric("Mode", "Read-Only")
    
    st.markdown("### À propos")
    st.markdown("""
    **NL2SQL Local** — Convertir du français en SQL 100% local
    
    - **Architecture** : 5 couches orchestrées par LangGraph
    - **LLM** : Llama 3.1 via Ollama (aucune clé API requise)
    - **Sécurité** : Validation AST, exécution read-only
    - **Explications** : Pédagogiques en français
    - **Mémoire** : Conversationnelle (5 tours)
    
    ### Couches intégrées
    1. **SchemaRetriever** : Récupération de schéma par RAG
    2. **FewShotSelector** : Exemples dynamiques
    3. **SQLGenerator** : Génération avec Llama
    4. **SelfCorrectionPipeline** : Auto-correction avec LangGraph
    5. **Security + Explainer** : Validation et explication
    
    **Temps typique** : 2-10 secondes par question
    """)

# ──────────────────────────────────────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────────────────────────────────────

st.divider()
st.markdown("""
<div style='text-align: center; color: gray; font-size: 0.8rem;'>
    © 2024 NL2SQL Local | Interface Streamlit
</div>
""", unsafe_allow_html=True)
```

---

## 🚀 Lancement de l'application

```bash
# 1. S'assurer qu'Ollama tourne
ollama serve

# 2. Dans un autre terminal, lancer Streamlit
streamlit run app/main.py

# 3. Ouvrir le navigateur
# http://localhost:8501
```

---

## 📊 Flux de données complet (Exemple pas à pas)

### Entrée : Question utilisateur
```
"Quels clients à Paris ont dépensé plus de 500€ en 2024 ?"
```

### Couche 1 : SchemaRetriever
```
Question → Embedding → ChromaDB
Résultat : "Table clients (id, nom, ville), Table commandes (id, montant, date)"
```

### Couche 2 : FewShotSelector
```
Question → Embedding → ChromaDB (collection few_shot_examples)
Résultat : 
  "Q: clients de Paris ? → SELECT * FROM clients WHERE ville = 'Paris'"
  "Q: dépenses > 500 ? → SELECT * FROM commandes WHERE montant > 500"
```

### Couche 3 : SQLGenerator
```
Prompt = "Schéma : [tables] | Exemples : [few-shot] | Historique : [] | Question : [...]"
Llama génère →
SQL : "SELECT c.id, c.nom, SUM(cmd.montant) FROM clients c 
       JOIN commandes cmd ON c.id = cmd.id_client 
       WHERE c.ville = 'Paris' AND YEAR(cmd.date) = 2024 
       GROUP BY c.id HAVING SUM(cmd.montant) > 500;"
```

### Couche 5A : SQLSecurityValidator
```
Analyse AST → SELECT (✅ autorisé)
Résultat : valide=True, type_requete="SELECT"
```

### Couche 4 : SelfCorrectionPipeline
```
Exécution sur BD → 12 résultats trouvés ✅
Pas de correction nécessaire
```

### Couche 5B : SQLExplainer
```
SQL + Question → Llama (temperature=0.3)
Explication : "Cette requête affiche tous les clients parisiens 
              qui ont dépensé plus de 500€ en 2024, triés par client."
```

### Retour à l'interface
```
RésultatPipeline {
  succes: True,
  question: "Quels clients à Paris...",
  sql: "SELECT c.id, c.nom, SUM(...)",
  donnees: DataFrame(12 lignes, 3 colonnes),
  explication: "Cette requête affiche...",
  nb_resultats: 12,
  nb_corrections: 0,
  bloque_securite: False
}

Streamlit affiche :
  ✅ Exécuté avec succès (12 résultats)
  📖 Explication pédagogique
  🔍 SQL généré
  📊 Tableau + Graphique
```

---

## 📋 Checklist pour tester l'interface

- [ ] Ollama tourne avec Llama 3.1
- [ ] ChromaDB est accessible
- [ ] Streamlit est installé (`pip install streamlit`)
- [ ] `app/main.py` contient le code fourni ci-dessus
- [ ] Lancer `streamlit run app/main.py`
- [ ] Tester une question simple
- [ ] Vérifier l'explication pédagogique
- [ ] Vérifier l'historique conversationnel
- [ ] Tester une correction automatique (question qui cause une erreur)
- [ ] Tester la sécurité (essayer "DELETE FROM clients")

---

## 🎯 Résumé

L'interface Streamlit :
1. **Affiche un chat** pour poser des questions en français
2. **Appelle le pipeline** qui orchestr les 5 couches
3. **Affiche les résultats** : SQL, explication, tableau, graphique
4. **Gère l'historique** et la mémoire conversationnelle
5. **Visualise les statistiques** de chaque requête

Les 5 couches :
- **C1** : Récupère les tables pertinentes (RAG)
- **C2** : Sélectionne les exemples SQL (Few-shot dynamique)
- **C3** : Génère le SQL (Llama)
- **C5A** : Valide la sécurité (AST)
- **C5B** : Explique le SQL (Llama)
- **C4** : Corrige le SQL (LangGraph)
- **Mémoire** : Historique conversationnel
