"""Atomic per-question checkpoints, isolated by source/data/config fingerprints."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Checkpoints:
    def __init__(self, path, run_key):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.key = run_key
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('CREATE TABLE IF NOT EXISTS results (run_key TEXT, qid TEXT, payload TEXT NOT NULL, PRIMARY KEY(run_key,qid))')

    def get(self, qid):
        row = self.conn.execute('SELECT payload FROM results WHERE run_key=? AND qid=?', (self.key, qid)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, qid, payload):
        with self.conn:
            self.conn.execute('INSERT OR REPLACE INTO results VALUES(?,?,?)', (self.key, qid, json.dumps(payload, ensure_ascii=False)))

    def close(self):
        self.conn.close()
