# Output formatting: instruction status table, register file, non-zero memory.


def fmt_val(v):
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return '%.1f' % v
        return '%.6g' % v
    return str(v)


def fmt_range(r):
    if not r:
        return '-'
    return '%d-%d' % (r[0], r[1])


def status_table(m):
    w = max([len(e.ins.text) for e in m.committed] + [12]) + 2
    lines = ['%-*s%-8s%-10s%-10s%-8s%-8s' % (w, '', 'ISSUE', 'EX', 'MEM', 'WB', 'COMMIT')]
    for e in m.committed:
        lines.append('%-*s%-8s%-10s%-10s%-8s%-8s' % (
            w, e.ins.text, e.issue, fmt_range(e.ex), fmt_range(e.mem),
            e.wb if e.wb is not None else '-', e.commit))
    return lines


def reg_block(prefix, values, per_row=8):
    lines = []
    for start in range(0, 32, per_row):
        names = ''.join('%-10s' % ('%s%d' % (prefix, i)) for i in range(start, start + per_row))
        vals = ''.join('%-10s' % fmt_val(values[i]) for i in range(start, start + per_row))
        lines.append('        ' + names.rstrip())
        lines.append('value:  ' + vals.rstrip())
    return lines


def report(m, show_btb=False):
    c = m.cfg
    out = []
    out.append('Configuration: issue width=%d, commit width=%d, CDB width=%d, ROB=%d'
               % (c.issue_width, c.commit_width, c.cdb_width, c.rob_size))
    out.append('')
    out.extend(status_table(m))
    out.append('')
    out.append('REGISTER VALUES')
    out.extend(reg_block('R', m.reg_int))
    out.extend(reg_block('F', m.reg_fp))
    out.append('')
    out.append('NON-ZERO MEMORY VALUES')
    out.append('%-12s%s' % ('Addresses', 'Values'))
    for i, v in enumerate(m.memory):
        if v != 0:
            out.append('%-12d%s' % (i, fmt_val(v)))
    out.append('')
    s = m.stats
    n = len(m.committed)
    out.append('SUMMARY')
    out.append('  total cycles            : %d' % m.cycle)
    out.append('  instructions committed  : %d' % n)
    out.append('  IPC                     : %.3f' % (n / m.cycle if m.cycle else 0))
    out.append('  instructions issued     : %d (squashed %d)' % (s['issued'], s['squashed']))
    out.append('  branches issued         : %d, mispredicted %d' % (s['branches'], s['mispredicts']))
    if show_btb:
        out.append('  final BTB contents:')
        out.extend(m.btb.dump() or ['  (empty)'])
    return out
