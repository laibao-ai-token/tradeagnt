try:
    from psycopg import sql as psycopg_sql
except Exception:
    psycopg_sql = None


def render_query_text(query):
    if psycopg_sql is not None:
        if isinstance(query, psycopg_sql.Composed):
            return "".join(render_query_text(part) for part in list(getattr(query, "_obj", [])))
        if isinstance(query, psycopg_sql.SQL):
            return getattr(query, "_obj", "")
        if isinstance(query, psycopg_sql.Identifier):
            return ".".join(['"{0}"'.format(part) for part in getattr(query, "_obj", ())])
        if isinstance(query, psycopg_sql.Literal):
            value = getattr(query, "_obj", None)
            if isinstance(value, str):
                return "'{0}'".format(value)
            return str(value)
    return str(query)


class FakeCursor(object):
    def __init__(
        self,
        fetchone_result=None,
        fetchall_result=None,
        rowcount=0,
        raise_on_execute=False,
        raise_on_executemany=False,
    ):
        self.execute_calls = []
        self.executemany_calls = []
        self.rowcount = rowcount
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result or []
        self._raise_on_execute = raise_on_execute
        self._raise_on_executemany = raise_on_executemany

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.execute_calls.append((render_query_text(query), params))
        if self._raise_on_execute:
            raise RuntimeError("execute boom")

    def executemany(self, query, values):
        rows = list(values)
        self.executemany_calls.append((render_query_text(query), rows))
        if self._raise_on_executemany:
            raise RuntimeError("executemany boom")

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return list(self._fetchall_result)


class FakeConnection(object):
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.commit_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):
        del row_factory
        return self.cursor_obj

    def commit(self):
        self.commit_calls += 1


class FakePool(object):
    created = []
    next_cursor = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        cursor = self.__class__.next_cursor or FakeCursor()
        self.connection_obj = FakeConnection(cursor)
        self.closed = False
        self.__class__.created.append(self)

    def connection(self):
        return self.connection_obj

    def close(self):
        self.closed = True

    @classmethod
    def reset(cls):
        cls.created = []
        cls.next_cursor = None
