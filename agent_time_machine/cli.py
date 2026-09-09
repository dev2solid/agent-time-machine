import argparse
import json
from pathlib import Path
import sys
from .demo import demo, execute
from .store import Store
from .compare import diff, export_svg


def main(argv=None):
    p = argparse.ArgumentParser(description='Record, rewind, and fork agent workflows.')
    commands = p.add_subparsers(dest='command', required=True)
    d = commands.add_parser('demo')
    d.add_argument('--out', type=Path, default=Path('runs/demo'))
    for name in ('replay', 'fork', 'compare', 'export'):
        c = commands.add_parser(name)
        c.add_argument('--db', type=Path, required=True)
        if name in ('replay', 'fork'):
            c.add_argument('run')
            c.add_argument('--through', type=int, required=name == 'fork')
        if name == 'fork':
            c.add_argument('--label', default='Counterfactual branch')
            c.add_argument('--instruction', choices=['trust-result', 'verify-freshness'])
            c.add_argument('--tool', choices=['stale', 'fresh'])
            c.add_argument('--execute-demo', action='store_true')
        if name in ('compare', 'export'):
            c.add_argument('runs', nargs=2 if name == 'compare' else '+')
        if name == 'export':
            c.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    store = None
    try:
        if args.command == 'demo':
            print(json.dumps(demo(args.out), indent=2))
            print(f'Timeline: {args.out / "timeline.svg"}')
            return 0
        store = Store(args.db)
        if args.command == 'replay':
            result = store.replay(args.run, args.through)
        elif args.command == 'fork':
            config = {k: getattr(args, k) for k in ('instruction', 'tool') if getattr(args, k) is not None}
            child = store.fork(args.run, args.through, args.label, config)
            result = {'run': child, 'state': execute(store, child) if args.execute_demo else store.replay(child)}
        elif args.command == 'compare':
            result = diff(*(store.replay(r) for r in args.runs))
        else:
            export_svg(store, args.runs, args.out)
            result = {'path': str(args.out)}
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    finally:
        if store:
            store.close()
