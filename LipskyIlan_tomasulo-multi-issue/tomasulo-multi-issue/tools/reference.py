# Golden model: a plain sequential (one-instruction-at-a-time) interpreter of
# the same ISA.  The Tomasulo simulator must end with exactly the same
# registers and memory for every program, configuration and issue width.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'code'))
from init import MEM_BYTES, SimError  # noqa: E402


def run_reference(cfg, program, max_steps=200000):
    R = list(cfg.reg_int)
    F = list(cfg.reg_fp)
    M = list(cfg.memory)
    pc = 0
    steps = 0
    trace = []

    def rd(name):
        if name == 'R0':
            return 0
        return R[int(name[1:])] if name[0] == 'R' else F[int(name[1:])]

    def wr(name, v):
        if name == 'R0':
            return
        if name[0] == 'R':
            R[int(name[1:])] = v
        else:
            F[int(name[1:])] = float(v)

    while 0 <= pc < len(program):
        steps += 1
        if steps > max_steps:
            raise SimError('reference model: too many steps')
        ins = program[pc]
        trace.append(pc)
        op = ins.op
        nxt = pc + 1
        if op in ('Add', 'Add.d'):
            wr(ins.dest, rd(ins.srcs[0]) + rd(ins.srcs[1]))
        elif op in ('Sub', 'Sub.d'):
            wr(ins.dest, rd(ins.srcs[0]) - rd(ins.srcs[1]))
        elif op == 'Addi':
            wr(ins.dest, rd(ins.srcs[0]) + ins.imm)
        elif op == 'Mult.d':
            wr(ins.dest, rd(ins.srcs[0]) * rd(ins.srcs[1]))
        elif op == 'Ld':
            a = rd(ins.base) + ins.imm
            if not 0 <= a < MEM_BYTES:
                raise SimError('reference: bad load address %s' % a)
            wr(ins.dest, M[a])
        elif op == 'Sd':
            a = rd(ins.base) + ins.imm
            if not 0 <= a < MEM_BYTES:
                raise SimError('reference: bad store address %s' % a)
            M[a] = rd(ins.data)
        elif op in ('Beq', 'Bne'):
            eq = rd(ins.srcs[0]) == rd(ins.srcs[1])
            if eq == (op == 'Beq'):
                nxt = pc + 1 + ins.imm
        pc = nxt
    return R, F, M, trace
