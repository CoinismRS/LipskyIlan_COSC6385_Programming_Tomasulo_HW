# Run every test bench in ../tests with issue width 1..4 (CDB width 1 and
# CDB width = issue width), verify each run against the golden model and the
# timing invariants, and print a cycle/IPC summary table.
#
# usage: python3 tools/run_tests.py [--tables DIR]
#   --tables DIR   also write the full simulator output of every run to DIR

import argparse
import copy
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'code'))

from init import Machine, parse_input  # noqa: E402
from main import run  # noqa: E402
from print_status import report  # noqa: E402
from checks import check_run  # noqa: E402


def simulate(path, width, cdb):
    cfg, prog = parse_input(path)
    orig = copy.deepcopy(cfg)
    cfg.issue_width = width
    cfg.commit_width = None
    cfg.cdb_width = cdb
    m = run(Machine(cfg, prog))
    return m, orig, prog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tables', help='directory to write full outputs to')
    a = ap.parse_args()
    tests = sorted(glob.glob(os.path.join(HERE, '..', 'tests', '*.txt')))
    failures = 0
    rows = []
    for t in tests:
        name = os.path.basename(t)[:-4]
        row = [name]
        for cdb_mode in ('1', 'W'):
            for w in (1, 2, 3, 4):
                cdb = 1 if cdb_mode == '1' else w
                m, orig, prog = simulate(t, w, cdb)
                errs = check_run(m, orig, prog)
                if errs:
                    failures += 1
                    print('FAIL %s width=%d cdb=%d' % (name, w, cdb))
                    for x in errs[:10]:
                        print('    ' + x)
                row.append(m.cycle)
                if a.tables:
                    os.makedirs(a.tables, exist_ok=True)
                    fn = os.path.join(a.tables, '%s_w%d_cdb%d.out' % (name, w, cdb))
                    with open(fn, 'w') as f:
                        f.write('\n'.join(report(m, True)) + '\n')
        rows.append(row)
    print()
    print('Total cycles (all runs verified against the sequential golden model)')
    print('%-28s | %-27s | %s' % ('', 'CDB width = 1', 'CDB width = issue width'))
    print('%-28s | %-6s%-6s%-6s%-9s| %-6s%-6s%-6s%-6s' % ('test', 'W=1', 'W=2', 'W=3', 'W=4',
                                                          'W=1', 'W=2', 'W=3', 'W=4'))
    for r in rows:
        print('%-28s | %-6d%-6d%-6d%-9d| %-6d%-6d%-6d%-6d' % tuple(r))
    print()
    print('%d test runs, %d failures' % (len(tests) * 8, failures))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
