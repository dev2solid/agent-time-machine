import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import xml.etree.ElementTree as ET
from agent_time_machine.store import Store, Session
from agent_time_machine.compare import diff, export_svg
from agent_time_machine.demo import demo, execute


class TimeMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'history.db'
        self.store = Store(self.path)
        self.run = self.store.create('original', {'instruction': 'trust-result'})

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_replay_never_reexecutes_operation(self):
        calls = []
        session = Session(self.store, self.run)
        self.assertEqual(session.step('tool', lambda s: calls.append(1) or {'value': 7}), {'value': 7})
        self.assertEqual(session.step('tool', lambda s: self.fail('tool called during replay')), {'value': 7})
        self.assertEqual(len(calls), 1)

    def test_fork_preserves_parent_and_invalidates_only_suffix(self):
        execute(self.store, self.run)
        before = self.store.events(self.run)
        child = self.store.fork(self.run, 2, 'changed', {'instruction': 'verify-freshness'})
        state = execute(self.store, child)
        self.assertEqual(state['steps']['decide']['action'], 'request-fresh-metrics')
        self.assertEqual(self.store.events(self.run), before)
        self.assertEqual(self.store.events(child)[:3][2]['hash'], before[2]['hash'])
        self.assertEqual(self.store.replay(child)['steps']['retrieve'], self.store.replay(self.run)['steps']['retrieve'])

    def test_tool_change_requires_checkpoint_before_tool(self):
        execute(self.store, self.run)
        child = self.store.fork(self.run, 1, 'fresh', {'tool': 'fresh', 'instruction': 'verify-freshness'})
        self.assertEqual(execute(self.store, child)['steps']['retrieve']['age_minutes'], 3)

    def test_checkpoint_validation(self):
        for seq in [-1, 1, True, 0.5]:
            with self.assertRaises(ValueError):
                self.store.fork(self.run, seq, 'bad')
        with self.assertRaises(ValueError):
            self.store.replay('missing')

    def test_optimistic_concurrency_rejects_stale_append(self):
        self.store.append(self.run, 'result', {'name': 'one', 'output': 1}, 0)
        with self.assertRaises(ValueError):
            self.store.append(self.run, 'result', {'name': 'two', 'output': 2}, 0)
        self.assertNotIn('two', self.store.replay(self.run)['steps'])

    def test_events_are_immutable(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.db.execute('DELETE FROM events')
        self.store.db.rollback()

    def test_hash_detects_modified_event_if_trigger_is_removed(self):
        self.store.db.execute('DROP TRIGGER events_no_update')
        self.store.db.execute("UPDATE events SET payload='{}'")
        self.store.db.commit()
        with self.assertRaises(ValueError):
            self.store.events(self.run)

    def test_error_is_recorded_and_retry_can_succeed(self):
        session = Session(self.store, self.run)
        with self.assertRaises(ZeroDivisionError):
            session.step('tool', lambda s: 1 / 0)
        self.assertEqual(session.step('tool', lambda s: 4), 4)
        self.assertEqual(self.store.replay(self.run)['errors'][0]['type'], 'ZeroDivisionError')

    def test_restart_persists_and_diff_tracks_types(self):
        Session(self.store, self.run).step('value', lambda s: 1)
        other = Store(self.path)
        try:
            self.assertEqual(other.replay(self.run)['steps']['value'], 1)
        finally:
            other.close()
        self.assertEqual(diff({'x': True}, {'x': 1})[0]['path'], '$.x')
        self.assertEqual(diff({}, {'x': None})[0]['kind'], 'added')

    def test_svg_escapes_labels_and_demo_exports(self):
        malicious = self.store.create('<script>alert(1)</script>')
        path = Path(self.tmp.name) / 'timeline.svg'
        export_svg(self.store, [malicious], path)
        self.assertNotIn('<script>', path.read_text())
        ET.parse(path)
        result = demo(Path(self.tmp.name) / 'demo')
        self.assertEqual(len(result['runs']), 3)
        self.assertTrue(result['instruction_diff'])


if __name__ == '__main__':
    unittest.main()
