"""Append-only, hash-linked run history with immutable branch checkpoints."""
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(previous, seq, kind, payload):
    return hashlib.sha256(canonical([previous, seq, kind, payload]).encode()).hexdigest()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, parent TEXT REFERENCES runs(id),
          fork_seq INTEGER, label TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(run_id TEXT REFERENCES runs(id), seq INTEGER,
          kind TEXT NOT NULL, payload TEXT NOT NULL, previous TEXT NOT NULL, hash TEXT NOT NULL,
          PRIMARY KEY(run_id, seq));
        CREATE TRIGGER IF NOT EXISTS events_no_update BEFORE UPDATE ON events
          BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS events_no_delete BEFORE DELETE ON events
          BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
        ''')

    def close(self):
        self.db.close()

    def create(self, label, config=None):
        run_id = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute('INSERT INTO runs VALUES(?,NULL,NULL,?)', (run_id, label))
            self._append(run_id, 'start', {'config': config or {}}, expected_seq=-1)
        return run_id

    def events(self, run_id):
        if not self.db.execute('SELECT 1 FROM runs WHERE id=?', (run_id,)).fetchone():
            raise ValueError('Unknown run')
        rows = self.db.execute('SELECT * FROM events WHERE run_id=? ORDER BY seq', (run_id,)).fetchall()
        previous = ''
        result = []
        for seq, row in enumerate(rows):
            payload = json.loads(row['payload'])
            if row['seq'] != seq or row['previous'] != previous or row['hash'] != digest(previous, seq, row['kind'], payload):
                raise ValueError('Event integrity check failed')
            previous = row['hash']
            result.append({**dict(row), 'payload': payload})
        return result

    def replay(self, run_id, through=None):
        events = self.events(run_id)
        if through is not None and (type(through) is not int or not 0 <= through < len(events)):
            raise ValueError('Checkpoint is out of range')
        state = {'config': {}, 'steps': {}, 'errors': []}
        for e in events if through is None else events[:through + 1]:
            p = e['payload']
            if e['kind'] in ('start', 'fork'):
                state['config'].update(p['config'])
            elif e['kind'] == 'result':
                state['steps'][p['name']] = p['output']
            elif e['kind'] == 'error':
                state['errors'].append(p)
        return state

    def _append(self, run_id, kind, payload, expected_seq):
        last = self.db.execute('SELECT seq,hash FROM events WHERE run_id=? ORDER BY seq DESC LIMIT 1', (run_id,)).fetchone()
        current = last['seq'] if last else -1
        if current != expected_seq:
            raise ValueError('Concurrent writer changed this run; fork or reload before continuing')
        seq, previous = current + 1, last['hash'] if last else ''
        value = canonical(payload)
        self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                        (run_id, seq, kind, value, previous, digest(previous, seq, kind, payload)))

    def append(self, run_id, kind, payload, expected_seq):
        if kind not in ('result', 'error'):
            raise ValueError('Use create/fork for configuration changes')
        self.events(run_id)
        with self.db:
            self._append(run_id, kind, payload, expected_seq)

    def fork(self, run_id, through, label, config=None):
        events = self.events(run_id)
        self.replay(run_id, through)  # Validate checkpoint, including bool rejection.
        child = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute('INSERT INTO runs VALUES(?,?,?,?)', (child, run_id, through, label))
            for e in events[:through + 1]:
                self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',
                                (child, e['seq'], e['kind'], canonical(e['payload']), e['previous'], e['hash']))
            self._append(child, 'fork', {'parent': run_id, 'through': through, 'config': config or {}}, through)
        return child

    def metadata(self, run_id):
        self.events(run_id)
        return dict(self.db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())


class Session:
    """Record JSON-returning operations. Existing successful steps are replayed, not called."""
    def __init__(self, store, run_id):
        self.store, self.run_id = store, run_id

    def step(self, name, operation):
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Step name is required')
        events = self.store.events(self.run_id)
        state = self.store.replay(self.run_id)
        if name in state['steps']:
            return state['steps'][name]
        expected = events[-1]['seq']
        try:
            output = operation(state)
            canonical(output)  # Fail before persisting non-JSON values.
        except Exception as exc:
            self.store.append(self.run_id, 'error', {'name': name, 'type': type(exc).__name__}, expected)
            raise
        self.store.append(self.run_id, 'result', {'name': name, 'output': output}, expected)
        return output
