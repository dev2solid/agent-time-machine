"""Structural state diffs and a data-driven SVG timeline (no browser required)."""
from html import escape
import json
from pathlib import Path


def diff(left, right, path='$'):
    if isinstance(left, dict) and isinstance(right, dict):
        changes = []
        for key in sorted(left.keys() | right.keys()):
            p = path + '.' + key
            if key not in left:
                changes.append({'path': p, 'kind': 'added', 'after': right[key]})
            elif key not in right:
                changes.append({'path': p, 'kind': 'removed', 'before': left[key]})
            else:
                changes.extend(diff(left[key], right[key], p))
        return changes
    if type(left) is not type(right) or left != right:
        return [{'path': path, 'kind': 'changed', 'before': left, 'after': right}]
    return []


def export_svg(store, runs, path):
    width, height = 1080, 120 + len(runs) * 160
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
             '<title id="title">Agent Time Machine: recorded branches</title>',
             '<desc id="desc">Each row shows an actual recorded run, event sequence, and final decision.</desc>',
             f'<rect width="{width}" height="{height}" fill="#101827"/>',
             '<g font-family="monospace" fill="#e5edf7">',
             '<text x="32" y="45" font-size="25">AGENT TIME MACHINE</text>',
             '<text x="32" y="76" font-size="14" fill="#9eb0c9">Record → fork a checkpoint → change one variable → compare</text>']
    for row, run_id in enumerate(runs):
        metadata = store.metadata(run_id)
        events = store.events(run_id)
        y = 128 + row * 160
        parts.append(f'<text x="32" y="{y}" font-size="17">{escape(metadata["label"][:55])}</text>')
        for col, e in enumerate(events):
            x = 42 + col * min(142, 930 / max(1, len(events) - 1))
            color = '#60dfb3' if e['kind'] == 'fork' else '#72a7ff'
            name = e['payload'].get('name', e['kind'])
            if col:
                parts.append(f'<path d="M {prev_x} {y+34} H {x}" stroke="#425570" stroke-width="2"/>')
            parts.append(f'<circle cx="{x}" cy="{y+34}" r="7" fill="{color}"/>')
            parts.append(f'<text x="{x-8}" y="{y+62}" font-size="13">{e["seq"]}: {escape(name[:16])}</text>')
            prev_x = x
        decision = store.replay(run_id)['steps'].get('decide', {})
        text = json.dumps(decision, ensure_ascii=False)
        parts.append(f'<text x="32" y="{y+100}" font-size="14" fill="#b8c8df">{escape(text[:118])}</text>')
    parts.append('</g></svg>')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(''.join(parts))
