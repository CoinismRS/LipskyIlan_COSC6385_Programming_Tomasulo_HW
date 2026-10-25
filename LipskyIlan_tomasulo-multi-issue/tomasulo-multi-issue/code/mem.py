# MEM stage for loads (stores access memory when they commit -- see commit.py).
#
# For each load whose effective address is known, in program order:
#   * if any OLDER store in the LSQ still has an unknown address, wait
#     (conservative memory disambiguation, as in the original code);
#   * otherwise look for the nearest older store to the same address:
#       - match with data ready  -> store-to-load forwarding, takes 1 cycle,
#                                   no memory access;
#       - match, data not ready  -> wait for the store data;
#       - no match               -> access memory (single port, non-pipelined,
#                                   `ls_mem` cycles).  Oldest eligible load first.
# A load's LSQ entry is cleared as soon as it has its value.

from init import MEM_BYTES


def read_memory(m, e, address):
    if not isinstance(address, int) or not 0 <= address < MEM_BYTES:
        e.fault = 'load from invalid address %s' % address
        return 0
    return m.memory[address]


def to_dest_type(e, v):
    if e.dest and e.dest[0] == 'F':
        return float(v)
    return v


def mem(m, cycle):
    # 1. loads finishing their memory access this cycle
    for l in [l for l in m.lsq if l.op == 'Ld' and l.state == 'mem' and l.rob.mem[1] == cycle]:
        e = l.rob
        e.value = to_dest_type(e, read_memory(m, e, l.address))
        e.complete = cycle
        l.state = 'done'
        m.lsq.remove(l)
        m.results.append(e)

    # 2. start forwarding / memory accesses
    port_free = m.mem_busy_until < cycle
    for i, l in enumerate(list(m.lsq)):
        if l.op != 'Ld' or l.state != 'addr' or not l.addr_known(cycle):
            continue
        idx = m.lsq.index(l)
        older_stores = [s for s in m.lsq[:idx] if s.op == 'Sd']
        if any(not s.addr_known(cycle) for s in older_stores):
            continue
        match = None
        for s in reversed(older_stores):
            if s.address == l.address:
                match = s
                break
        e = l.rob
        if match is not None:
            if match.data_known(cycle):
                e.value = to_dest_type(e, match.data_v)
                e.mem = [cycle, cycle]
                e.forwarded = True
                e.complete = cycle
                l.state = 'done'
                m.lsq.remove(l)
                m.results.append(e)
                m.trace('fwd    %-22s <- store %s (addr %d)' % (e.ins.text, match.rob.tag, l.address))
            continue
        if port_free:
            end = cycle + m.cfg.ls_mem - 1
            e.mem = [cycle, end]
            m.mem_busy_until = end
            l.state = 'mem'
            port_free = False
            m.trace('mem    %-22s addr %d (cycles %d-%d)' % (e.ins.text, l.address, cycle, end))
            if end == cycle:                    # 1-cycle memory
                e.value = to_dest_type(e, read_memory(m, e, l.address))
                e.complete = cycle
                l.state = 'done'
                m.lsq.remove(l)
                m.results.append(e)
