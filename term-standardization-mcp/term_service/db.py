import hashlib
from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector
from .config import DATABASE_URL

@contextmanager
def connect():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5) as conn:
        register_vector(conn)
        conn.execute("SET statement_timeout = '15s'")
        yield conn

def initialize():
    with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
        conn.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

def catalog_fingerprint(conn):
    rows = conn.execute("SELECT id,updated_at FROM standard_terms ORDER BY id").fetchall()
    domains = conn.execute("SELECT code,description FROM domains ORDER BY code").fetchall()
    return hashlib.sha256(str((rows, domains)).encode()).hexdigest()

def word_catalog_fingerprint(conn):
    rows = conn.execute("SELECT id,updated_at FROM standard_words ORDER BY id").fetchall()
    return hashlib.sha256(str(rows).encode()).hexdigest()
