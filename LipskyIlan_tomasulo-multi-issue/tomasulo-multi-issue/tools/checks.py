# Correctness checks applied to every simulation run:
#   1. final registers + memory equal the sequential golden model
#   2. the committed instruction stream equals the golden model's dynamic trace
#   3. pipeline timing invariants (in-order issue/commit, width limits, stage order,
#      producer -> consumer timing, one CDB broadcast per CDB per cycle, ...)

import math
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'code'))

from reference import run_reference  # noqa: E402


def same(a, b):
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def check_run(m, cfg_orig, program):
    errs = []
    R, F, M, trace = run_reference(cfg_orig, program)
    for i in range(32):
        if not same(R[i], m.reg_int[i]):
            errs.append('R%d: sim=%r ref=%r' % (i, m.reg_int[i], R[i]))
        if not same(float(F[i]), float(m.reg_fp[i])):
            errs.append('F%d: sim=%r ref=%r' % (i, m.reg_fp[i], F[i]))
    for a in range(len(M)):
        if not same(M[a], m.memory[a]):
            errs.append('Mem[%d]: sim=%r ref=%r' % (a, m.memory[a], M[a]))
    pcs = [e.ins.pc for e in m.committed]
    if pcs != trace:
        errs.append('committed stream differs from sequential trace')
    errs.extend(check_timing(m))
    return errs


def check_timing(m):
    c = m.cfg
    errs = []
    E = m.committed
    issue_cnt = Counter(e.issue for e in E)
    commit_cnt = Counter(e.commit for e in E)
    wb_cnt = Counter(e.wb for e in E if e.wb is not None)
    if any(v > c.issue_width for v in m.stats['issue_per_cycle'].values()):
        errs.append('more than issue_width instructions issued in a cycle')
    if any(v > c.issue_width for v in issue_cnt.values()):
        errs.append('issue width exceeded (committed stream)')
    if any(v > c.commit_width for v in commit_cnt.values()):
        errs.append('commit width exceeded')
    if any(v > c.cdb_width for v in wb_cnt.values()):
        errs.append('CDB width exceeded')
    mem_busy = Counter()
    last_writer = {}
    for i, e in enumerate(E):
        k = e.ins.kind
        if i and (e.issue < E[i - 1].issue or e.commit < E[i - 1].commit):
            errs.append('%s: out-of-order issue/commit' % e.ins.text)
        if not e.ex or e.ex[0] <= e.issue:
            errs.append('%s: EX must start after ISSUE' % e.ins.text)
        if k in ('int', 'fpadd', 'fpmul'):
            lat = {'int': c.int_ex, 'fpadd': c.fpa_ex, 'fpmul': c.fpm_ex}[k]
            if e.ex[1] - e.ex[0] + 1 != lat:
                errs.append('%s: wrong EX latency' % e.ins.text)
            if not (e.ex[1] < e.wb < e.commit):
                errs.append('%s: stage order EX<WB<COMMIT violated' % e.ins.text)
        elif k == 'load':
            if not (e.ex[1] < e.mem[0] <= e.mem[1] < e.wb < e.commit):
                errs.append('%s: stage order EX<MEM<WB<COMMIT violated' % e.ins.text)
            n = e.mem[1] - e.mem[0] + 1
            if n != (1 if e.forwarded else c.ls_mem):
                errs.append('%s: bad MEM length' % e.ins.text)
            if not e.forwarded:
                for t in range(e.mem[0], e.mem[1] + 1):
                    mem_busy[t] += 1
        elif k == 'store':
            if not (e.ex[1] < e.commit == e.mem[0]):
                errs.append('%s: store must write memory at commit' % e.ins.text)
            for t in range(e.mem[0], e.mem[1] + 1):
                mem_busy[t] += 1
        elif k == 'branch':
            if not (e.ex[1] < e.commit):
                errs.append('%s: branch committed before resolving' % e.ins.text)
        # producer -> consumer: operands must be broadcast before EX starts
        srcs = list(e.ins.srcs) + ([e.ins.base] if e.ins.base else [])
        for s in srcs:
            p = last_writer.get(s)
            if p is not None and s != 'R0' and not (p.wb < e.ex[0]):
                errs.append('%s: started EX before producer %s broadcast' % (e.ins.text, p.ins.text))
        if k == 'store':
            p = last_writer.get(e.ins.data)
            if p is not None and e.ins.data != 'R0' and not (p.wb < e.commit):
                errs.append('%s: committed before data was available' % e.ins.text)
        if e.dest:
            last_writer[e.dest] = e
    # single memory port (only committed accesses are visible here; squashed
    # wrong-path loads can only add, never remove, conflicts)
    if any(v > 1 for v in mem_busy.values()):
        errs.append('memory port used by two accesses in one cycle')
    return errs
