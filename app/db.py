import os
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

_pool = None

def pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=5, open=True,
                               kwargs={"row_factory": dict_row, "autocommit": True})
    return _pool

def init():
    sql = open(os.path.join(os.path.dirname(__file__), "schema.sql")).read()
    with pool().connection() as c:
        c.execute(sql)

def q(sql, params=(), one=False):
    with pool().connection() as c:
        cur = c.execute(sql, params)
        if cur.description is None:
            return None
        return cur.fetchone() if one else cur.fetchall()

def tx():
    """Transaction context: `with db.tx() as c:` (commits on success, rolls back on error)."""
    from contextlib import contextmanager
    @contextmanager
    def _t():
        with pool().connection() as c:
            c.autocommit = False
            try:
                yield c
                c.commit()
            except Exception:
                c.rollback(); raise
            finally:
                c.autocommit = True
    return _t()
