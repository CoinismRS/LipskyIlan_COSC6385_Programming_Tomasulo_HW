# Multi-issue Tomasulo simulator (ROB, RAT, LSQ, BTB, speculative execution).
#
# usage: python3 main.py [input_file] [-w WIDTH] [--cdb N] [--commit N] [-v] [--btb]
#
# The input file holds the hardware configuration, the issue width, initial
# register / memory values and the assembly program (see README.md).
# Command-line options override the values given in the file.
#
# Each simulated cycle runs the stages in the order
#     COMMIT -> WB (CDB) -> MEM -> EX -> ISSUE
# and every hand-off between stages is time-stamped, so an instruction can
# never pass through two dependent stages in the same cycle
# (e.g. a value broadcast in cycle n can be used by EX in cycle n+1).

import argparse
import sys

from init import Machine, parse_input, SimError
from issue import issue
from exe import exe
from mem import mem
from wb import wb
from commit import commit
from print_status import report


def finished(m):
    return not m.rob and not (0 <= m.pc < len(m.program))


def run(m):
    cycle = 0
    while True:
        cycle += 1
        m.cycle = cycle
        if cycle > m.cfg.max_cycles:
            raise SimError('simulation exceeded %d cycles (infinite loop?)' % m.cfg.max_cycles)
        commit(m, cycle)
        wb(m, cycle)
        mem(m, cycle)
        exe(m, cycle)
        issue(m, cycle)
        m.lsq = [l for l in m.lsq if l.state != 'retired']   # stores dequeued at commit
        if finished(m):
            break
    return m


def simulate(path, issue_width=None, cdb_width=None, commit_width=None, verbose=False):
    cfg, program = parse_input(path)
    if issue_width is not None:
        cfg.issue_width = issue_width
        if commit_width is None:
            cfg.commit_width = None          # follow the new issue width
    if cdb_width is not None:
        cfg.cdb_width = cdb_width
    if commit_width is not None:
        cfg.commit_width = commit_width
    return run(Machine(cfg, program, verbose))


def main(argv=None):
    ap = argparse.ArgumentParser(description='Multi-issue Tomasulo simulator')
    ap.add_argument('input', nargs='?', default='code.in', help='test-bench file (default: code.in)')
    ap.add_argument('-w', '--width', type=int, help='issue width 1-4 (overrides the file)')
    ap.add_argument('--cdb', type=int, help='number of CDBs / broadcasts per cycle (default 1)')
    ap.add_argument('--commit', type=int, help='commit width (default = issue width)')
    ap.add_argument('-v', '--verbose', action='store_true', help='print a cycle-by-cycle trace')
    ap.add_argument('--btb', action='store_true', help='print the final BTB contents')
    a = ap.parse_args(argv)
    try:
        m = simulate(a.input, a.width, a.cdb, a.commit, a.verbose)
    except (SimError, OSError) as ex:
        print('error: %s' % ex, file=sys.stderr)
        return 1
    if a.verbose:
        print('CYCLE-BY-CYCLE TRACE')
        print('\n'.join(m.log))
        print()
    print('\n'.join(report(m, a.btb)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
