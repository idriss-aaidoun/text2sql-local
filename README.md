# NL2SQL-Local 🗄️

Interface langage naturel → SQL avec Llama 3.1 8B (Ollama) + LangChain + ChromaDB.
Stack 100% locale, 0 €/mois, fonctionne sans GPU.

## Installation

```bash
# 1. Cloner le projet
git clone https://github.com/idriss-aaidoun/text2sql-local.git
cd text2sql-local

# 2. Installer les dépendances Python
pip install -r requirements.txt
pip install -U langchain-huggingface

# 3. Installer Ollama et télécharger Llama 3.1
# https://ollama.com/download
ollama pull llama3.1

# 4. Copier et configurer les variables d'environnement
cp .env.example .env

# 5. Lancer PostgreSQL + Langfuse (optionnel)
docker compose up -d

# 6. Lancer l'application
streamlit run app/main.py
```

## Architecture — 5 couches

| Couche | Fichier | Rôle |
|--------|---------|------|
| 1 | `core/schema_retriever.py` | RAG sur le schéma SQL |
| 2 | `core/few_shot_selector.py` | Few-Shot dynamique |
| 3 | `core/sql_generator.py` | Génération SQL Llama 3.1 |
| 4 | `core/sql_validator.py` | Self-correction LangGraph |
| 5 | `core/security.py` + `core/explainer.py` | Sécurité + Explication |

## Lancer les tests

```bash
pytest tests/ -v
```

## Stack technique

- **LLM** : Llama 3.1 8B via Ollama (CPU, 0 €)
- **Orchestration** : LangChain 0.3 + LangGraph 0.2
- **Embeddings** : sentence-transformers/all-MiniLM-L6-v2
- **Vector Store** : ChromaDB (persistant local)
- **Base de données** : PostgreSQL 16 / SQLite
- **Interface** : Streamlit 1.38 + Plotly
- **Monitoring** : Langfuse self-hosted