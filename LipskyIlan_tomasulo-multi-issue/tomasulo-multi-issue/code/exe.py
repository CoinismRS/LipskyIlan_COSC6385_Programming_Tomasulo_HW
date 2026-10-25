# EX stage.
#
# 1. Dispatch: every free functional unit takes the OLDEST ready instruction
#    from its reservation stations (operands must have been broadcast in an
#    earlier cycle, and the instruction must have issued in an earlier cycle).
#    The dedicated address adder(s) take the oldest load/store whose base
#    register is ready.
# 2. Complete: ops whose last EX cycle is this cycle produce their result.
#    ALU results go to the CDB queue (written back from the next cycle on),
#    effective addresses go straight into the LSQ, and branches are resolved.
#    A mispredicted branch squashes all younger instructions; fetch from the
#    correct path restarts two cycles later (n -> recovery n+1 -> fetch n+2).
#
# Original: one instruction per RS group per cycle, FIFO functional units,
# "waiting instruction" special cases, Bne only, no prediction.
# New: multiple FUs per class, oldest-first select, pipelined/unpipelined FUs,
# Beq + Bne, BTB update and misprediction recovery.

from init import SimError


def operands_ready(r, cycle):
    return (r.rob.issue < cycle and r.qj is None and r.qk is None
            and r.rj < cycle and r.rk < cycle)


def compute(op, a, b):
    if op in ('Add', 'Addi', 'Add.d'):
        return a + b
    if op in ('Sub', 'Sub.d'):
        return a - b
    if op == 'Mult.d':
        return a * b
    raise SimError('cannot compute %s' % op)


def dispatch(m, cycle):
    # ALU reservation stations -> functional units
    for cls in ('int', 'fpadd', 'fpmul'):
        for fu in m.fus[cls]:
            if not fu.can_accept(cycle):
                continue
            ready = [r for r in m.rs[cls] if operands_ready(r, cycle)]
            if not ready:
                break
            r = min(ready, key=lambda x: x.rob.seq)
            m.rs[cls].remove(r)                  # RS entry freed when EX starts
            end = fu.start(r.rob, r, cycle)
            r.rob.ex = [cycle, end]
            m.trace('exec   %-22s on %s (cycles %d-%d)' % (r.rob.ins.text, fu.name, cycle, end))
    # load/store queue -> effective-address adder(s)
    for fu in m.fus['addr']:
        if not fu.can_accept(cycle):
            continue
        ready = [l for l in m.lsq if l.state == 'wait' and l.rob.issue < cycle
                 and l.base_q is None and l.base_r < cycle]
        if not ready:
            break
        l = ready[0]                             # LSQ is already in program order
        l.state = 'exe'
        end = fu.start(l.rob, l, cycle)
        l.rob.ex = [cycle, end]
        m.trace('addr   %-22s on %s (cycles %d-%d)' % (l.rob.ins.text, fu.name, cycle, end))


def resolve_branch(m, e, r, cycle):
    ins = e.ins
    eq = (r.vj == r.vk)
    taken = eq if ins.op == 'Beq' else not eq
    target = ins.pc + 1 + ins.imm               # PC + 4 + (offset << 2), in words
    e.taken = taken
    actual_next = target if taken else ins.pc + 1
    m.btb.update(ins.pc, taken, target)
    if actual_next != e.pred_next:
        e.mispredicted = True
        m.stats['mispredicts'] += 1
        m.trace('branch %-22s %s -> MISPREDICTED' % (ins.text, 'T' if taken else 'NT'))
        m.squash_after(e, cycle)
        m.pc = actual_next
        m.fetch_resume = cycle + 2
    else:
        m.trace('branch %-22s %s -> correct' % (ins.text, 'T' if taken else 'NT'))


def complete(m, cycle):
    done = []
    for cls, fus in m.fus.items():
        for fu in fus:
            for item in fu.inflight:
                if item[2] == cycle:
                    done.append((cls, fu, item))
    done.sort(key=lambda x: x[2][0].seq)        # program order (oldest branch first)
    for cls, fu, item in done:
        e, payload, _ = item
        if e.squashed:                          # removed by an older mispredicted branch
            continue
        fu.inflight.remove(item)
        if cls == 'addr':
            l = payload
            l.address = l.base_v + l.imm
            l.addr_cycle = cycle
            l.state = 'addr'
        elif e.ins.kind == 'branch':
            resolve_branch(m, e, payload, cycle)
        else:
            e.value = compute(e.ins.op, payload.vj, payload.vk)
            e.complete = cycle
            m.results.append(e)


def exe(m, cycle):
    dispatch(m, cycle)
    complete(m, cycle)
