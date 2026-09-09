"""A deterministic incident-triage fixture, not an LLM benchmark."""
import json
from pathlib import Path
from .store import Store, Session
from .compare import diff, export_svg


def execute(store, run_id):
    session = Session(store, run_id)
    session.step('plan', lambda s: {'task': 'Triage checkout latency', 'service': 'checkout'})
    session.step('retrieve', lambda s: {'p95_ms': 1900, 'age_minutes': 3 if s['config'].get('tool') == 'fresh' else 180,
                                      'source': 'metrics-api'})
    def decide(s):
        metrics = s['steps']['retrieve']
        if s['config'].get('instruction') == 'verify-freshness' and metrics['age_minutes'] > 10:
            return {'action': 'request-fresh-metrics', 'reason': 'Evidence is older than 10 minutes'}
        return {'action': 'investigate-latency' if metrics['p95_ms'] > 1000 else 'observe',
                'reason': 'p95 compared to 1000ms threshold'}
    session.step('decide', decide)
    return store.replay(run_id)


def demo(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    store = Store(out / 'history.db')
    try:
        original = store.create('Original · trusts stale metrics', {'instruction': 'trust-result', 'tool': 'stale'})
        execute(store, original)
        # Checkpoint 2 contains retrieval: change only the decision instruction.
        prompt = store.fork(original, 2, 'Instruction branch · freshness check', {'instruction': 'verify-freshness'})
        execute(store, prompt)
        # Checkpoint 1 is before retrieval: change the tool and decision instruction.
        tool = store.fork(original, 1, 'Tool branch · fresh evidence', {'instruction': 'verify-freshness', 'tool': 'fresh'})
        execute(store, tool)
        result = {'mode': 'deterministic fixture, no model calls', 'runs': [original, prompt, tool],
                  'instruction_diff': diff(store.replay(original), store.replay(prompt)),
                  'tool_diff': diff(store.replay(original), store.replay(tool))}
        (out / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
        for run_id in result['runs']:
            (out / f'{run_id}.json').write_text(json.dumps(store.events(run_id), indent=2) + '\n')
        export_svg(store, result['runs'], out / 'timeline.svg')
        return result
    finally:
        store.close()
