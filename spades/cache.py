"""Local embedding reuse, keyed by exact text and immutable model digest."""

import hashlib
import json
import math
from pathlib import Path
import sqlite3
from contextlib import contextmanager


def valid_vector(vector):
    return (isinstance(vector, list) and bool(vector)
            and all(type(value) in (float, int) and math.isfinite(value) for value in vector))


class EmbeddingCache:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("CREATE TABLE IF NOT EXISTS embeddings (cache_key TEXT PRIMARY KEY, vector TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def key(model_digest, text):
        return hashlib.sha256((model_digest + "\0" + text).encode("utf-8")).hexdigest()

    def get_many(self, model_digest, texts):
        result = []
        with self.connect() as connection:
            for text in texts:
                row = connection.execute("SELECT vector FROM embeddings WHERE cache_key = ?",
                                         (self.key(model_digest, text),)).fetchone()
                try:
                    vector = json.loads(row[0]) if row else None
                except (ValueError, TypeError):
                    vector = None
                result.append(vector if valid_vector(vector) else None)
        return result

    def put_many(self, model_digest, texts, vectors):
        if len(texts) != len(vectors) or not all(valid_vector(vector) for vector in vectors):
            raise ValueError("Embedding provider returned invalid vectors")
        with self.connect() as connection:
            connection.executemany("INSERT OR REPLACE INTO embeddings(cache_key, vector) VALUES (?, ?)",
                                   [(self.key(model_digest, text), json.dumps(vector)) for text, vector in zip(texts, vectors)])
