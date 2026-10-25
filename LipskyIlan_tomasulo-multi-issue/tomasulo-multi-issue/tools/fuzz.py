# Random differential testing: generate random programs (straight-line code,
# forward branches, counted loops, aliasing loads/stores) and random hardware
# configurations, run them through the Tomasulo simulator with issue width
# 1..4, and compare against the sequential golden model + timing invariants.
#
# usage: python3 tools/fuzz.py [N] [seed]

import copy
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'code'))

from init import Config, Machine, parse_instruction  # noqa: E402
from main import run  # noqa: E402
from checks import check_run  # noqa: E402

INT_REGS = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6']
FP_REGS = ['F%d' % i for i in range(8)]


def rand_op(rng):
    k = rng.random()
    if k < 0.25:
        op = rng.choice(['Add', 'Sub'])
        return '%s %s, %s, %s' % (op, rng.choice(INT_REGS), rng.choice(INT_REGS + ['R0']),
                                  rng.choice(INT_REGS + ['R0']))
    if k < 0.35:
        return 'Addi %s, %s, %d' % (rng.choice(INT_REGS), rng.choice(INT_REGS + ['R0']),
                                    rng.randint(-5, 5))
    if k < 0.55:
        return '%s %s, %s, %s' % (rng.choice(['Add.d', 'Sub.d']), rng.choice(FP_REGS),
                                  rng.choice(FP_REGS), rng.choice(FP_REGS))
    if k < 0.65:
        return 'Mult.d %s, %s, %s' % (rng.choice(FP_REGS), rng.choice(FP_REGS), rng.choice(FP_REGS))
    base, lo = rng.choice([('R0', 0), ('R10', 0), ('R11', 64)])
    off = rng.choice([0, 4, 8, 12, 16, 20]) + (64 if base == 'R0' and rng.random() < .5 else 0)
    if k < 0.83:
        return 'Ld %s, %d(%s)' % (rng.choice(FP_REGS), off, base)
    return 'Sd %s, %d(%s)' % (rng.choice(FP_REGS), off, base)


def store_load_pair(rng):
    """Store whose data is still being computed, then a load from the same address."""
    f = rng.choice(FP_REGS)
    base, off = rng.choice([('R0', 8), ('R10', 12), ('R11', 4)])
    return ['Mult.d %s, %s, %s' % (f, rng.choice(FP_REGS), rng.choice(FP_REGS)),
            'Sd %s, %d(%s)' % (f, off, base),
            'Ld %s, %d(%s)' % (rng.choice(FP_REGS), off, base)]


def straight(rng, n):
    """n instructions; may contain short forward branches that stay inside the block."""
    body = [rand_op(rng) for _ in range(n)]
    if rng.random() < 0.3:
        pos = rng.randint(0, len(body))
        body[pos:pos] = store_load_pair(rng)
    out = []
    i = 0
    while i < len(body):
        if rng.random() < 0.2 and i < len(body) - 1:
            skip = rng.randint(0, min(3, len(body) - i - 1))
            out.append('%s %s, %s, %d' % (rng.choice(['Beq', 'Bne']), rng.choice(INT_REGS + ['R0']),
                                          rng.choice(INT_REGS + ['R0']), skip))
            # the `skip` following instructions belong to this block
        out.append(body[i])
        i += 1
    return out


def gen_program(rng):
    prog = []
    counters = ['R20', 'R21', 'R22']
    for _ in range(rng.randint(1, 4)):
        if rng.random() < 0.5 and counters:
            c = counters.pop()
            body = straight(rng, rng.randint(1, 7))
            prog.append('Addi %s, R0, %d' % (c, rng.randint(1, 4)))
            prog.extend(body)
            prog.append('Addi %s, %s, -1' % (c, c))
            prog.append('Bne %s, R0, %d' % (c, -(len(body) + 2)))
        else:
            prog.extend(straight(rng, rng.randint(1, 8)))
    return prog


def gen_config(rng):
    c = Config()
    c.int_rs, c.int_ex, c.int_fu = rng.randint(1, 4), rng.randint(1, 3), rng.randint(1, 2)
    c.fpa_rs, c.fpa_ex, c.fpa_fu = rng.randint(1, 4), rng.randint(1, 5), rng.randint(1, 2)
    c.fpm_rs, c.fpm_ex, c.fpm_fu = rng.randint(1, 4), rng.randint(1, 8), rng.randint(1, 2)
    c.lsq_size, c.ls_ex, c.ls_mem, c.ls_fu = (rng.randint(1, 6), rng.randint(1, 2),
                                              rng.randint(1, 5), rng.randint(1, 2))
    c.rob_size = rng.choice([2, 3, 4, 6, 8, 16, 64])
    c.cdb_width = rng.randint(1, 4)
    c.commit_width = rng.choice([None, 1, 2, 4])
    for r in INT_REGS:
        c.reg_int[int(r[1:])] = rng.randint(-3, 3)
    c.reg_int[11] = 64
    for f in FP_REGS:
        c.reg_fp[int(f[1:])] = float(rng.choice([0.0, 0.5, 1.0, 1.5, 2.0, -1.0, 3.25]))
    for a in range(0, 160, 4):
        if rng.random() < 0.5:
            c.memory[a] = float(rng.randint(-9, 9))
    return c


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 12345
    rng = random.Random(seed)
    fails = 0
    runs = 0
    stats = {'squashed': 0, 'mispredicts': 0, 'forwarded': 0}
    for it in range(n):
        lines = gen_program(rng)
        program = [parse_instruction(l, i, i + 1) for i, l in enumerate(lines)]
        base = gen_config(rng)
        for w in (1, 2, 3, 4):
            cfg = copy.deepcopy(base)
            cfg.issue_width = w
            orig = copy.deepcopy(cfg)
            try:
                m = run(Machine(cfg, program))
                errs = check_run(m, orig, program)
            except Exception as ex:          # noqa: BLE001
                errs = ['exception: %r' % ex]
            runs += 1
            if errs:
                fails += 1
                if fails <= 5:
                    print('FAIL iteration %d width %d' % (it, w))
                    print('\n'.join('    ' + l for l in lines))
                    print('\n'.join('  ! ' + e for e in errs[:8]))
            else:
                stats['squashed'] += m.stats['squashed']
                stats['mispredicts'] += m.stats['mispredicts']
                stats['forwarded'] += sum(1 for e in m.committed if e.forwarded)
    print('%d random runs (%d programs x 4 issue widths): %d failures' % (runs, n, fails))
    print('  exercised: %d mispredictions, %d squashed instructions, %d store->load forwards'
          % (stats['mispredicts'], stats['squashed'], stats['forwarded']))
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
