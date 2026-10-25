# COMMIT stage.
#
# Original: committed at most one instruction per cycle (plus a special case
# for a store followed by another instruction), branches committed silently.
# New:      commits up to `commit_width` instructions per cycle (defaults to the
#           issue width), strictly in order from the ROB head.
#
#   * ALU / load : result must have been broadcast in an earlier cycle.
#   * branch     : must have resolved (EX finished) in an earlier cycle.
#   * store      : address and data must be known; the store writes memory now,
#                  occupying the single memory port for `ls_mem` cycles (shown
#                  as its MEM stage), and is dequeued from the LSQ.  A second store in the
#                  same cycle therefore has to wait for the port.

from init import MEM_BYTES, SimError


def write_arch(m, e):
    if not e.dest:
        return
    idx = int(e.dest[1:])
    if e.dest[0] == 'R':
        m.reg_int[idx] = e.value
    else:
        m.reg_fp[idx] = e.value
    if m.rat.get(e.dest) is e:
        del m.rat[e.dest]          # no younger writer: architectural reg is now current


def commit(m, cycle):
    n = 0
    while n < m.cfg.commit_width and m.rob:
        e = m.rob[0]
        kind = e.ins.kind
        if kind == 'store':
            l = e.lsq
            if not (l.addr_known(cycle) and l.data_known(cycle)):
                break
            if m.mem_busy_until >= cycle:
                break
            if not isinstance(l.address, int) or not 0 <= l.address < MEM_BYTES:
                raise SimError('cycle %d: %s stores to invalid address %s'
                               % (cycle, e.ins.text, l.address))
            m.memory[l.address] = l.data_v
            e.mem = [cycle, cycle + m.cfg.ls_mem - 1]
            m.mem_busy_until = e.mem[1]
            # Dequeued at commit.  Commit and the MEM-stage forwarding check work
            # in parallel, so the entry stays visible to younger loads until the
            # end of this cycle (main.py removes 'retired' entries).
            l.state = 'retired'
        elif kind == 'branch':
            if not (e.ex and e.ex[1] < cycle):
                break
        else:
            if e.wb is None or e.wb >= cycle:
                break
            if e.fault:
                raise SimError('cycle %d: %s: %s' % (cycle, e.ins.text, e.fault))
            write_arch(m, e)
        e.commit = cycle
        m.rob.popleft()
        m.committed.append(e)
        m.trace('commit %-22s %s' % (e.ins.text, e.tag))
        n += 1
    return n
