# Regenerates every number, table and figure used in report.tex directly from
# the simulator, then runs pdflatex.  usage: python3 report/build_report.py

import copy
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, os.path.join(ROOT, 'code'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))

from init import Machine, parse_input  # noqa: E402
from main import run  # noqa: E402
from checks import check_run  # noqa: E402
from print_status import fmt_val  # noqa: E402

GEN = os.path.join(HERE, 'generated')
TESTS = ['test0_handout_example', 'test1_loop', 'test2_independent', 'test3_dependency_chain',
         'test4_memory', 'test5_branches', 'test6_structural', 'test7_sample_report_tc1',
         'test8_sample_report_tc2']


def sim(name, w, cdb):
    cfg, prog = parse_input(os.path.join(ROOT, 'tests', name + '.txt'))
    orig = copy.deepcopy(cfg)
    cfg.issue_width, cfg.commit_width, cfg.cdb_width = w, None, cdb
    m = run(Machine(cfg, prog))
    errs = check_run(m, orig, prog)
    assert not errs, (name, w, cdb, errs)
    return m


def tt(s):
    return '\\texttt{%s}' % s.replace('_', '\\_')


def rng(r):
    return '--' if not r else '%d--%d' % (r[0], r[1])


def write(name, text):
    with open(os.path.join(GEN, name), 'w') as f:
        f.write(text)


def status_table(m, caption=None):
    rows = []
    for e in m.committed:
        rows.append('%s & %d & %s & %s & %s & %d \\\\' % (
            tt(e.ins.text), e.issue, rng(e.ex), rng(e.mem),
            e.wb if e.wb is not None else '--', e.commit))
    s = ('\\begin{tabular}{@{}lrrrrr@{}}\\toprule\n'
         'Instruction & ISSUE & EX & MEM & WB & COMMIT\\\\\\midrule\n%s\n\\bottomrule\\end{tabular}'
         % '\n'.join(rows))
    return s


def issue_commit_table(ms):
    """One row per instruction, ISSUE/COMMIT cycle for W = 1..4."""
    base = ms[0].committed
    rows = []
    for i, e in enumerate(base):
        cells = []
        for m in ms:
            x = m.committed[i]
            cells.append('%d & %d' % (x.issue, x.commit))
        rows.append('%s & %s \\\\' % (tt(e.ins.text), ' & '.join(cells)))
    tot = ' & '.join('\\multicolumn{2}{c}{%d cycles}' % m.cycle for m in ms)
    head = ' & '.join('\\multicolumn{2}{c}{W=%d}' % m.cfg.issue_width for m in ms)
    cm = ''.join('\\cmidrule(lr){%d-%d}' % (2 + 2 * k, 3 + 2 * k) for k in range(len(ms)))
    sub = ' & '.join(['I & C'] * len(ms))
    return ('\\begin{tabular}{@{}l%s@{}}\\toprule\n & %s\\\\%s\n & %s\\\\\\midrule\n%s\n\\midrule Total & %s\\\\'
            '\\bottomrule\\end{tabular}' % ('>{\\hspace{10pt}}rr' * len(ms), head, cm, sub, '\n'.join(rows), tot))


def regs_mem(m):
    nz_r = ['R%d=%s' % (i, fmt_val(v)) for i, v in enumerate(m.reg_int) if v != 0]
    nz_f = ['F%d=%s' % (i, fmt_val(v)) for i, v in enumerate(m.reg_fp) if v != 0]
    nz_m = ['Mem[%d]=%s' % (a, fmt_val(v)) for a, v in enumerate(m.memory) if v != 0]
    return ', '.join(nz_r), ', '.join(nz_f), ', '.join(nz_m)


def main():
    os.makedirs(GEN, exist_ok=True)
    data = {}
    for t in TESTS:
        for w in (1, 2, 3, 4):
            for mode in ('1', 'W'):
                data[(t, w, mode)] = sim(t, w, 1 if mode == '1' else w)

    # ---- summary tables: cycles and IPC ----
    rows = []
    for t in TESTS:
        n = len(data[(t, 1, '1')].committed)
        c1 = [data[(t, w, '1')].cycle for w in (1, 2, 3, 4)]
        cw = [data[(t, w, 'W')].cycle for w in (1, 2, 3, 4)]
        best = c1[0] / min(cw)
        rows.append('%s & %d & %s & %s & %.2f$\\times$\\\\' % (
            tt(t.split('_', 1)[0]), n, ' & '.join(map(str, c1)), ' & '.join(map(str, cw[1:])), best))
    write('summary_cycles.tex',
          '\\begin{tabular}{@{}lr rrrr rrr r@{}}\\toprule\n'
          '& & \\multicolumn{4}{c}{CDB width = 1} & \\multicolumn{3}{c}{CDB width = W} & Best\\\\'
          '\\cmidrule(lr){3-6}\\cmidrule(lr){7-9}\n'
          'Test & Instr. & W=1 & W=2 & W=3 & W=4 & W=2 & W=3 & W=4 & speedup\\\\\\midrule\n'
          + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}\n')
    rows = []
    for t in TESTS:
        ipc1 = ['%.2f' % (len(data[(t, w, '1')].committed) / data[(t, w, '1')].cycle) for w in (1, 2, 3, 4)]
        ipcw = ['%.2f' % (len(data[(t, w, 'W')].committed) / data[(t, w, 'W')].cycle) for w in (2, 3, 4)]
        m = data[(t, 1, '1')]
        rows.append('%s & %s & %s & %d / %d\\\\' % (tt(t.split('_', 1)[0]), ' & '.join(ipc1),
                                                   ' & '.join(ipcw), m.stats['mispredicts'],
                                                   m.stats['squashed']))
    write('summary_ipc.tex',
          '\\begin{tabular}{@{}l rrrr rrr r@{}}\\toprule\n'
          '& \\multicolumn{4}{c}{CDB width = 1} & \\multicolumn{3}{c}{CDB width = W} & Mispred. /\\\\'
          '\\cmidrule(lr){2-5}\\cmidrule(lr){6-8}\n'
          'Test & W=1 & W=2 & W=3 & W=4 & W=2 & W=3 & W=4 & squashed (W=1)\\\\\\midrule\n'
          + '\n'.join(rows) + '\n\\bottomrule\\end{tabular}\n')

    # ---- detailed tables ----
    for w in (1, 2, 3, 4):
        write('t0_w%d.tex' % w, status_table(data[('test0_handout_example', w, '1')]))
    write('t2_ic.tex', issue_commit_table([data[('test2_independent', w, 'W')] for w in (1, 2, 3, 4)]))
    write('t2_ic_cdb1.tex', issue_commit_table([data[('test2_independent', w, '1')] for w in (1, 2, 3, 4)]))
    write('t2_w4.tex', status_table(data[('test2_independent', 4, 'W')]))
    write('t1_w1.tex', status_table(data[('test1_loop', 1, '1')]))
    write('t1_w4.tex', status_table(data[('test1_loop', 4, '1')]))
    write('t3_ic.tex', issue_commit_table([data[('test3_dependency_chain', w, 'W')] for w in (1, 2, 3, 4)]))
    write('t4_w1.tex', status_table(data[('test4_memory', 1, '1')]))
    write('t4_w2.tex', status_table(data[('test4_memory', 2, '1')]))
    write('t5_w2.tex', status_table(data[('test5_branches', 2, '1')]))
    write('t6_ic.tex', issue_commit_table([data[('test6_structural', w, '1')] for w in (1, 2, 3, 4)]))
    write('t7_ic.tex', issue_commit_table([data[('test7_sample_report_tc1', w, 'W')] for w in (1, 2, 3, 4)]))

    # final state lines for each test (identical for every width: checked by check_run)
    lines = []
    for t in TESTS:
        r, f, mm = regs_mem(data[(t, 1, '1')])
        def brk(x):
            return ', '.join(tt(v) for v in x.split(', ')) if x else 'none'
        lines.append('\\item %s. Registers: %s, %s. Memory: %s.' % (
            tt(t), brk(r), brk(f), brk(mm)))
    write('final_state.tex', '{\\raggedright\\begin{itemize}\\small\n' + '\n'.join(lines)
          + '\n\\end{itemize}}\n')

    # plain-text full output for the loop test (shows the required output format)
    from print_status import report
    write('t1_full_w2.txt', '\n'.join(report(data[('test1_loop', 2, '1')])) + '\n')

    # ---- numbers used in the prose ----
    def cyc(t, w, mode='1'):
        return data[(t, w, mode)].cycle
    macros = {
        'tTwoWoneCycles': cyc('test2_independent', 1),
        'tTwoWfourCycles': cyc('test2_independent', 4, 'W'),
        'tTwoWfourCdbOne': cyc('test2_independent', 4, '1'),
        'tOneWone': cyc('test1_loop', 1), 'tOneWfour': cyc('test1_loop', 4),
        'tThreeWone': cyc('test3_dependency_chain', 1), 'tThreeWfour': cyc('test3_dependency_chain', 4, 'W'),
        'tSevenWone': cyc('test7_sample_report_tc1', 1),
        'tSevenWtwo': cyc('test7_sample_report_tc1', 2, 'W'),
        'tEightWone': cyc('test8_sample_report_tc2', 1),
        'tEightWtwo': cyc('test8_sample_report_tc2', 2, 'W'),
        'tSixAll': cyc('test6_structural', 1),
        'tFiveWtwoSquashed': data[('test5_branches', 2, '1')].stats['squashed'],
    }
    write('numbers.tex', ''.join('\\newcommand{\\%s}{%s}\n' % kv for kv in macros.items()))

    make_figure(data)
    for _ in range(2):
        subprocess.run(['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 'report.tex'],
                       cwd=HERE, check=True, stdout=subprocess.DEVNULL)
    print('report/report.pdf written')


def make_figure(data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    # validated categorical palette (slots 1-4), distinct markers as secondary encoding
    series = [('test2_independent', 'independent ops', '#2a78d6', 'o'),
              ('test5_branches', 'branches / loops', '#eb6834', 's'),
              ('test4_memory', 'memory / LSQ', '#1baf7a', '^'),
              ('test3_dependency_chain', 'dependence chain', '#eda100', 'D')]
    ink, muted, grid = '#1f1f1e', '#6b6a63', '#e4e3dd'
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9})
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.9), sharey=True)
    for ax, mode, title in ((axes[0], '1', 'CDB width = 1 (one CDB)'),
                            (axes[1], 'W', 'CDB width = issue width')):
        ends = []
        for t, label, col, mk in series:
            base = data[(t, 1, mode)].cycle
            ys = [base / data[(t, w, mode)].cycle for w in (1, 2, 3, 4)]
            ax.plot([1, 2, 3, 4], ys, color=col, lw=2, marker=mk, ms=6,
                    markeredgecolor='white', markeredgewidth=1.2, label=label, zorder=3)
            ends.append([ys[-1], ys[-1]])
        # end-of-line value labels, nudged apart so they never overlap
        order = sorted(range(len(ends)), key=lambda i: ends[i][0])
        gap = 0.075
        for a, b in zip(order, order[1:]):
            if ends[b][1] - ends[a][1] < gap:
                ends[b][1] = ends[a][1] + gap
        for (y, ly) in ends:
            ax.annotate('%.2f' % y, (4, y), xytext=(4.18, ly), textcoords='data',
                        va='center', fontsize=8, color=ink)
        ax.set_title(title, fontsize=9, color=ink, loc='left')
        ax.set_xticks([1, 2, 3, 4])
        ax.set_xlim(0.8, 4.6)
        ax.set_xlabel('issue width W', color=muted)
        ax.grid(axis='y', color=grid, lw=0.8)
        ax.set_axisbelow(True)
        for s in ('top', 'right'):
            ax.spines[s].set_visible(False)
        for s in ('left', 'bottom'):
            ax.spines[s].set_color(grid)
        ax.tick_params(colors=muted, length=0)
    axes[0].set_ylabel('speedup over W=1', color=muted)
    axes[0].set_ylim(0.9, 2.4)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc='lower center', ncol=4, frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, -0.01))
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    fig.savefig(os.path.join(GEN, 'speedup.pdf'))
    fig.savefig(os.path.join(GEN, 'speedup.png'), dpi=160)


if __name__ == '__main__':
    main()
