# WB stage: broadcast finished results on the CDB(s).
#
# Original: a single CDB latch, results taken FIFO from the results buffer.
# New:      up to `cdb_width` results per cycle (default 1, i.e. one CDB as in
#           the assignment), oldest instruction first.  A result can be written
#           back the cycle after its EX (or MEM, for loads) stage ends.
#
# A broadcast writes the value into the ROB and wakes up every reservation
# station / LSQ entry waiting for that tag.  Waiting instructions may start
# executing in the following cycle.


def broadcast(m, e, cycle):
    e.wb = cycle
    for rss in m.rs.values():
        for r in rss:
            if r.qj is e:
                r.vj, r.qj, r.rj = e.value, None, cycle
            if r.qk is e:
                r.vk, r.qk, r.rk = e.value, None, cycle
    for l in m.lsq:
        if l.base_q is e:
            l.base_v, l.base_q, l.base_r = e.value, None, cycle
        if l.data_q is e:
            l.data_v, l.data_q, l.data_r = e.value, None, cycle
    m.trace('wb     %-22s %s = %s' % (e.ins.text, e.tag, e.value))


def wb(m, cycle):
    ready = sorted((e for e in m.results if e.complete < cycle), key=lambda e: e.seq)
    for e in ready[:m.cfg.cdb_width]:
        m.results.remove(e)
        broadcast(m, e, cycle)
