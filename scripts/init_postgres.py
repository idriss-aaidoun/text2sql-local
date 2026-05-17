# -*- coding: utf-8 -*-
"""
scripts/init_postgres.py
Peuple la base PostgreSQL de demonstration.
Lancer : python scripts/init_postgres.py
"""

import psycopg2

# Connexion directe sans passer par .env ni SQLAlchemy
conn = psycopg2.connect(
    host="localhost",
    port=5432,
    dbname="demo_db",
    user="admin",
    password="admin123",
)
conn.autocommit = False
cur = conn.cursor()

print("Connexion PostgreSQL OK...")

# ── Tables ────────────────────────────────────────────────────────────────────

cur.execute("""
CREATE TABLE IF NOT EXISTS clients (
    id               SERIAL PRIMARY KEY,
    nom              VARCHAR(100) NOT NULL,
    email            VARCHAR(200) UNIQUE,
    ville            VARCHAR(100),
    date_inscription DATE DEFAULT CURRENT_DATE
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS produits (
    id        SERIAL PRIMARY KEY,
    nom       VARCHAR(200) NOT NULL,
    prix      DECIMAL(10,2) NOT NULL,
    stock     INTEGER DEFAULT 0,
    categorie VARCHAR(100)
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS commandes (
    id            SERIAL PRIMARY KEY,
    id_client     INTEGER REFERENCES clients(id),
    date_commande DATE DEFAULT CURRENT_DATE,
    montant_total DECIMAL(10,2),
    statut        VARCHAR(50) DEFAULT 'en_cours'
);
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS lignes_commande (
    id            SERIAL PRIMARY KEY,
    id_commande   INTEGER REFERENCES commandes(id),
    id_produit    INTEGER REFERENCES produits(id),
    quantite      INTEGER NOT NULL,
    prix_unitaire DECIMAL(10,2)
);
""")

print("Tables creees...")

# ── Clients ───────────────────────────────────────────────────────────────────

cur.execute("""
INSERT INTO clients (nom, email, ville, date_inscription) VALUES
    ('Alice Martin',  'alice@email.com',  'Paris',     '2023-01-15'),
    ('Bob Dupont',    'bob@email.com',    'Lyon',      '2023-03-22'),
    ('Clara Simon',   'clara@email.com',  'Paris',     '2023-05-10'),
    ('David Moreau',  'david@email.com',  'Bordeaux',  '2023-07-08'),
    ('Emma Leroy',    'emma@email.com',   'Paris',     '2023-09-01'),
    ('Franck Petit',  'franck@email.com', 'Toulouse',  '2023-11-14'),
    ('Grace Bernard', 'grace@email.com',  'Lyon',      '2024-01-20'),
    ('Hugo Roux',     'hugo@email.com',   'Paris',     '2024-02-28'),
    ('Iris Blanc',    'iris@email.com',   'Marseille', '2024-03-15'),
    ('Jules Noir',    'jules@email.com',  'Paris',     '2024-04-10')
ON CONFLICT (email) DO NOTHING;
""")

print("Clients inseres...")

# ── Produits ──────────────────────────────────────────────────────────────────

cur.execute("""
INSERT INTO produits (nom, prix, stock, categorie) VALUES
    ('Laptop Pro 15',      1299.99, 25,  'electronique'),
    ('Souris sans fil',      29.99, 150, 'electronique'),
    ('Clavier mecanique',    89.99, 80,  'electronique'),
    ('Ecran 27 pouces',     399.99, 40,  'electronique'),
    ('Chaise de bureau',    249.99, 30,  'mobilier'),
    ('Bureau standing',     599.99, 15,  'mobilier'),
    ('Webcam HD',            79.99, 60,  'electronique'),
    ('Casque audio',        149.99, 45,  'electronique'),
    ('Lampe de bureau',      49.99, 90,  'mobilier'),
    ('Tapis de souris XL',   19.99, 200, 'accessoire')
ON CONFLICT DO NOTHING;
""")

print("Produits inseres...")

# ── Commandes ─────────────────────────────────────────────────────────────────

cur.execute("""
INSERT INTO commandes (id_client, date_commande, montant_total, statut) VALUES
    (1,  '2024-01-05', 1329.98, 'livree'),
    (2,  '2024-01-12',   89.99, 'livree'),
    (3,  '2024-01-20',  449.98, 'livree'),
    (1,  '2024-02-03',  249.99, 'livree'),
    (4,  '2024-02-14',  679.98, 'livree'),
    (5,  '2024-02-28',   49.99, 'livree'),
    (2,  '2024-03-05',  429.98, 'en_cours'),
    (6,  '2024-03-18', 1299.99, 'en_cours'),
    (3,  '2024-03-25',  169.98, 'en_cours'),
    (7,  '2024-04-02',   99.98, 'en_cours'),
    (1,  '2024-04-10',  599.99, 'en_cours'),
    (8,  '2024-04-20',  229.98, 'annulee'),
    (9,  '2024-05-01',   79.99, 'livree'),
    (10, '2024-05-15',  349.98, 'livree'),
    (5,  '2024-05-22',  149.99, 'en_cours');
""")

print("Commandes inserees...")

# ── Lignes de commande ────────────────────────────────────────────────────────

cur.execute("""
INSERT INTO lignes_commande (id_commande, id_produit, quantite, prix_unitaire) VALUES
    (1,  1,  1, 1299.99),
    (1,  2,  1,   29.99),
    (2,  3,  1,   89.99),
    (3,  4,  1,  399.99),
    (3,  2,  2,   29.99),
    (4,  5,  1,  249.99),
    (5,  6,  1,  599.99),
    (5,  9,  1,   49.99),
    (6,  9,  1,   49.99),
    (7,  7,  1,   79.99),
    (7,  3,  1,   89.99),
    (8,  1,  1, 1299.99),
    (9,  8,  1,  149.99),
    (9,  2,  1,   29.99),
    (10, 10, 2,   19.99),
    (10, 2,  2,   29.99),
    (11, 6,  1,  599.99),
    (12, 4,  1,  399.99),
    (12, 7,  1,   79.99),
    (13, 7,  1,   79.99),
    (14, 4,  1,  399.99),
    (14, 9,  1,   49.99),
    (15, 8,  1,  149.99);
""")

print("Lignes de commande inserees...")

# ── Commit et fermeture ───────────────────────────────────────────────────────

conn.commit()
cur.close()
conn.close()

print("")
print("Base PostgreSQL peuplee avec succes !")
print("  10 clients | 10 produits | 15 commandes | 23 lignes de commande")