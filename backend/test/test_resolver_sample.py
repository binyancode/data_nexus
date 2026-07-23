import os
import sys
import unittest

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from nexus.client import NexusClient
from nexus.resolvers.sql import SqlResolver


class _Db:
    def __init__(self):
        self.calls = []

    def execute_query(self, sql, params=None):
        self.calls.append((sql, params))
        return [{"id": 1, "name": "sample"}]


class _SampleResolver:
    provides_concepts = True

    def sample(self, target, limit):
        return [{"a": 1}, {"b": 2, "a": 3}]

    def describe(self):
        return {"dbo.items": [{"column": "a"}, {"column": "b"}]}


class _Registry:
    def __init__(self, resolver):
        self._resolver = resolver

    def resolver(self, name):
        return self._resolver if name == "source" else None


class ResolverSampleTests(unittest.TestCase):
    def test_sql_sample_quotes_each_identifier_and_clamps_limit(self):
        resolver = object.__new__(SqlResolver)
        resolver._db = _Db()

        rows = resolver.sample("sales.order]items", 500)

        self.assertEqual(rows, [{"id": 1, "name": "sample"}])
        self.assertEqual(
            resolver._db.calls,
            [("SELECT TOP (100) * FROM [sales].[order]]items]", None)],
        )

    def test_sql_sample_rejects_invalid_multipart_identifier(self):
        resolver = object.__new__(SqlResolver)
        resolver._db = _Db()
        for target in (".dbo.items", "db..items", "a.b.c.d.e"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                resolver.sample(target, 20)

    def test_nexus_sample_returns_stable_column_union(self):
        client = object.__new__(NexusClient)
        client.registry = _Registry(_SampleResolver())

        result = client.resolver_sample("source", "dbo.items", 20)

        self.assertEqual(result["columns"], ["a", "b"])
        self.assertEqual(result["rows"], [{"a": 1}, {"b": 2, "a": 3}])

    def test_nexus_sample_rejects_non_concept_resolver(self):
        resolver = _SampleResolver()
        resolver.provides_concepts = False
        client = object.__new__(NexusClient)
        client.registry = _Registry(resolver)

        self.assertIsNone(client.resolver_sample("source", "dbo.items", 20))


if __name__ == "__main__":
    unittest.main()
