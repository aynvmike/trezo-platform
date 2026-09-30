"""Offline seams for the day-trade income contract suites."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

NOW = datetime(2026, 9, 21, 18, tzinfo=timezone.utc)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@contextmanager
def patched(module, **attrs):
    old = {key: getattr(module, key) for key in attrs}
    try:
        for key, value in attrs.items():
            setattr(module, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(module, key, value)


async def none(*a, **k):
    return None


class Query:
    def __init__(self, rows):
        self.rows = list(rows)

    def select(self, *a): return self
    def eq(self, key, value):
        self.rows = [r for r in self.rows if r.get(key) == value]
        return self
    def neq(self, key, value):
        self.rows = [r for r in self.rows if r.get(key) != value]
        return self
    def in_(self, key, values):
        self.rows = [r for r in self.rows if r.get(key) in values]
        return self
    def like(self, key, value):
        self.rows = [r for r in self.rows if str(r.get(key, '')).startswith(value.rstrip('%'))]
        return self
    def gte(self, key, value):
        self.rows = [r for r in self.rows if str(r.get(key, '')) >= value]
        return self
    def order(self, key, desc=False):
        self.rows.sort(key=lambda r: r.get(key, ''), reverse=desc)
        return self
    def limit(self, count):
        self.rows = self.rows[:count]
        return self
    def range(self, start, end):
        self.rows = self.rows[start:end+1]
        return self
    def execute(self): return SimpleNamespace(data=self.rows)


class Client:
    def __init__(self, **tables): self.tables = tables
    def table(self, name): return Query(self.tables.get(name, []))
