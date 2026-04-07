import os
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector


def _connect():
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = False
    return conn


def get_conn(autocommit: bool = False):
    conn = _connect()
    if autocommit:
        conn.autocommit = True
    # Teach psycopg2 how to serialise/deserialise pgvector's vector type.
    # After this, you can pass numpy arrays directly as query parameters
    # and get them back as numpy arrays in results.
    # Requires the vector extension to already be installed (run migrate first).
    register_vector(conn)
    return conn


def migrate():
    # Use a plain connection — vector extension doesn't exist yet
    conn = _connect()
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    sql_path = os.path.join(migrations_dir, "001_init.sql")
    with open(sql_path) as f:
        sql = f.read()
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    conn.close()
    print("Migration applied.")


def dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
