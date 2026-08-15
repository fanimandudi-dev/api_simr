"""
db.py — Accès base de données centralisé avec POOL DE CONNEXIONS
=================================================================
Pourquoi un pool ?
  Créer/fermer une connexion TCP (poignée de main + authentification PostgreSQL)
  à CHAQUE requête HTTP détruit les performances. Le pool ouvre un nombre
  limité de connexions UNE FOIS au démarrage, puis les réutilise pour toutes
  les requêtes. Sous charge, le gain est énorme (plus de connexions TIME_WAIT
  qui s'accumulent, plus de latence d'authentification par requête).

Pourquoi ThreadedConnectionPool ?
  FastAPI exécute les routes `def` dans un threadpool (40 threads par défaut).
  Chaque thread doit avoir SA connexion : ce pool est thread-safe.
"""
import os
from contextlib import contextmanager

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

# ⚠️ load_dotenv() DOIT précéder os.getenv()
#    (bug corrigé : l'ancienne version lisait DATABASE_URL avant de charger le .env)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "Variable DATABASE_URL manquante : créez un fichier .env à la racine "
        "(copiez .env.example et renseignez l'URL PostgreSQL)."
    )

# Taille du pool — ajustable via .env sans toucher au code.
# Règle : DB_POOL_MAX ≈ concurrence moyenne de l'API, et jamais au-delà
# du max_connections de PostgreSQL (au-delà de ~50 connexions simultanées,
# placez PgBouncer devant la base).
POOL_MIN = int(os.getenv("DB_POOL_MIN", "2"))
POOL_MAX = int(os.getenv("DB_POOL_MAX", "10"))

_pool = ThreadedConnectionPool(POOL_MIN, POOL_MAX, DATABASE_URL)


def get_conn():
    """Récupère une connexion SAINE du pool (répare les connexions mortes)."""
    conn = _pool.getconn()
    try:
        # Annule la transaction précédente ET vérifie que la connexion vit encore
        # (résilience après un redémarrage de PostgreSQL ou une coupure réseau).
        if hasattr(conn, "reset"):      # psycopg2 >= 2.9
            conn.reset()
        else:
            conn.rollback()
        return conn
    except Exception:
        # Connexion morte → on la jette (close=True) et on en demande une autre
        _pool.putconn(conn, close=True)
        return _pool.getconn()


def put_conn(conn):
    """Rend la connexion au pool (NE PAS appeler conn.close() !)."""
    _pool.putconn(conn)


def close_pool():
    """Ferme proprement toutes les connexions (appelée à l'arrêt de l'API)."""
    _pool.closeall()


@contextmanager
def db_cursor(commit: bool = False):
    """
    Contexte de requête : connexion prise au pool, curseur RealDictCursor,
    commit/rollback automatique, et connexion TOUJOURS rendue au pool
    (même en cas d'exception → zéro fuite de connexion).

    Usage :
        with db_cursor() as cur:              # LECTURE (rollback auto à la sortie)
            cur.execute("SELECT ...")
            rows = cur.fetchall()

        with db_cursor(commit=True) as cur:   # ÉCRITURE (commit auto à la sortie)
            cur.execute("INSERT ...")
    """
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        if commit:
            conn.commit()
        else:
            conn.rollback()  # referme la transaction de lecture
    except Exception:
        conn.rollback()      # ne laisse jamais une transaction ouverte derrière soi
        raise
    finally:
        put_conn(conn)


def bulk_insert(sql: str, rows: list):
    """
    Insertion en masse : N lignes en 1 SEUL aller-retour réseau (executemany).
    ~10 à 100× plus rapide qu'une boucle d'INSERT unitaires.
    Idéal pour le seeding (zones/aires/centres) ou l'import de logs.

    Exemple :
        from db import bulk_insert
        bulk_insert(
            "INSERT INTO zone_sante (nom, code, province, population) VALUES (%s, %s, %s, %s)",
            [("Zone A", "Z-A", "Kinshasa", 50000),
             ("Zone B", "Z-B", "Kongo-Central", 32000)],
        )
    """
    with db_cursor(commit=True) as cur:
        cur.executemany(sql, rows)
