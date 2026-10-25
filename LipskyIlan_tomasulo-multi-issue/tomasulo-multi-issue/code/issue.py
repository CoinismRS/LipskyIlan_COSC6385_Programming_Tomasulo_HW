# ISSUE stage (includes fetch and decode).
#
# Original: fetched exactly one instruction per cycle and stopped fetching at
# every Bne until the branch resolved (no prediction).
# New:      issues up to `issue_width` (1-4) instructions per cycle, strictly in
#           program order, and predicts branches with the BTB so issue can
#           continue past them speculatively.
#
# In-order issue rules per cycle:
#   * stop at the first instruction that cannot get a ROB entry and an RS/LSQ entry
#     (structural hazard) -- younger instructions never bypass it;
#   * stop after a branch predicted taken (fetch is redirected to the target,
#     which is fetched next cycle);
#   * no issue at all while a misprediction is being recovered.

from init import ROBEntry, RSEntry, LSQEntry, RS_CLASS


def has_space(m, ins):
    if len(m.rob) >= m.cfg.rob_size:
        m.stats['stall_rob'] += 1
        return False
    cls = RS_CLASS[ins.kind]
    if cls == 'lsq':
        ok = sum(1 for l in m.lsq if l.state != 'retired') < m.cfg.lsq_size
    else:
        ok = len(m.rs[cls]) < m.rs_size[cls]
    if not ok:
        m.stats['stall_rs'] += 1
    return ok


def fill_operand(m, name, cycle):
    v, q, r = m.read_reg(name, cycle)
    return v, q, (r if r is not None else 0)


def issue_one(m, ins, cycle):
    """Allocate ROB + RS/LSQ entries for one instruction and rename its destination."""
    e = ROBEntry(m.seq, ins, m.seq % m.cfg.rob_size)
    m.seq += 1
    e.issue = cycle
    m.rob.append(e)
    cls = RS_CLASS[ins.kind]

    if cls == 'lsq':
        l = LSQEntry(e)
        l.base_v, l.base_q, l.base_r = fill_operand(m, ins.base, cycle)
        if ins.op == 'Sd':
            l.data_v, l.data_q, l.data_r = fill_operand(m, ins.data, cycle)
        e.lsq = l
        m.lsq.append(l)
    else:
        r = RSEntry(e)
        r.vj, r.qj, r.rj = fill_operand(m, ins.srcs[0], cycle)
        if len(ins.srcs) > 1:
            r.vk, r.qk, r.rk = fill_operand(m, ins.srcs[1], cycle)
        else:                                   # Addi: immediate operand
            r.vk, r.qk, r.rk = ins.imm, None, 0
        m.rs[cls].append(r)

    # rename the destination only after the sources were read (e.g. Addi R1, R1, 8)
    if e.dest:
        m.rat[e.dest] = e

    next_pc = ins.pc + 1
    if ins.kind == 'branch':
        e.pred_taken, e.pred_next = m.btb.predict(ins.pc)
        next_pc = e.pred_next
        m.stats['branches'] += 1
    m.stats['issued'] += 1
    m.trace('issue  %-22s -> %s%s' % (ins.text, e.tag,
            ('  (predict %s)' % ('T' if e.pred_taken else 'NT')) if ins.kind == 'branch' else ''))
    return e, next_pc


def issue(m, cycle):
    if cycle < m.fetch_resume:
        return 0
    n = 0
    while n < m.cfg.issue_width and 0 <= m.pc < len(m.program):
        ins = m.program[m.pc]
        if not has_space(m, ins):
            break
        e, m.pc = issue_one(m, ins, cycle)
        n += 1
        if ins.kind == 'branch' and e.pred_taken:
            break                               # taken branch ends the fetch group
    if n:
        m.stats['issue_per_cycle'][cycle] = n
    return n
