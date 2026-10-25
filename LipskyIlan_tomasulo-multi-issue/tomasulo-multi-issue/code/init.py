# Tomasulo simulator -- data structures, configuration and program parsing.
#
# Based on the single-issue Python simulator by Qing (May 2017).  The original
# used namedtuple *classes* as mutable records and hard-coded the machine
# configuration in main.py.  This version replaces them with small explicit
# classes and reads the whole configuration (including the new issue width)
# from the input file.

import re
from collections import deque

from predictor import BTB

# --------------------------------------------------------------------------
# Instruction set
# --------------------------------------------------------------------------
# kind -> which reservation station / functional-unit class the op uses
OPCODES = {
    'add':    'int',
    'addi':   'int',
    'sub':    'int',
    'beq':    'branch',   # branches use the integer adder RS / FU
    'bne':    'branch',
    'add.d':  'fpadd',
    'sub.d':  'fpadd',
    'mult.d': 'fpmul',
    'mul.d':  'fpmul',    # accepted alias
    'ld':     'load',
    'sd':     'store',
}
CANON = {'add': 'Add', 'addi': 'Addi', 'sub': 'Sub', 'beq': 'Beq', 'bne': 'Bne',
         'add.d': 'Add.d', 'sub.d': 'Sub.d', 'mult.d': 'Mult.d', 'mul.d': 'Mult.d',
         'ld': 'Ld', 'sd': 'Sd'}

# reservation-station class for each instruction kind
RS_CLASS = {'int': 'int', 'branch': 'int', 'fpadd': 'fpadd', 'fpmul': 'fpmul',
            'load': 'lsq', 'store': 'lsq'}

MEM_BYTES = 256            # 256-byte data memory, addressed by byte address.
# As in the original simulator, every byte address 0..255 names one memory cell
# that holds a whole value; test benches normally use word-aligned addresses.


class SimError(Exception):
    pass


class Instr:
    """A decoded (static) instruction."""

    def __init__(self, pc, text, op, dest=None, srcs=(), imm=0, base=None, data=None):
        self.pc = pc            # word index into the program (byte address = 4*pc)
        self.text = text        # normalised assembly text used in the output table
        self.op = op            # canonical opcode, e.g. 'Add.d'
        self.kind = OPCODES[op.lower()]
        self.dest = dest        # destination register name ('R3', 'F2') or None
        self.srcs = list(srcs)  # source registers for ALU / branch ops
        self.imm = imm          # immediate / offset
        self.base = base        # base register for Ld/Sd
        self.data = data        # data register for Sd

    def __repr__(self):
        return self.text


# --------------------------------------------------------------------------
# Dynamic (in-flight) structures
# --------------------------------------------------------------------------
class ROBEntry:
    def __init__(self, seq, ins, slot):
        self.seq = seq            # global program-order sequence number (unique)
        self.slot = slot          # ROB slot number (seq mod ROB size) -- the "tag"
        self.ins = ins
        self.dest = ins.dest if ins.dest != 'R0' else None   # R0 is hard-wired
        self.value = None
        self.fault = None         # memory fault on a (possibly speculative) load
        self.complete = None      # cycle the result became available (EX/MEM end)
        # timing (cycle numbers) shown in the final table
        self.issue = None
        self.ex = []              # [start, end]
        self.mem = []             # [start, end]
        self.wb = None
        self.commit = None
        # branch bookkeeping
        self.pred_taken = False
        self.pred_next = None
        self.taken = None
        self.mispredicted = False
        # load/store bookkeeping
        self.lsq = None
        self.forwarded = False    # load got its value from an older store
        self.squashed = False

    @property
    def tag(self):
        return 'ROB%d' % self.slot


class RSEntry:
    """Reservation-station entry (integer adder, FP adder, FP multiplier)."""

    def __init__(self, rob):
        self.rob = rob
        self.op = rob.ins.op
        self.vj = self.vk = None
        self.qj = self.qk = None          # producing ROB entry, or None if value valid
        self.rj = self.rk = 0             # cycle in which the value became valid


class LSQEntry:
    """Load/store queue entry (acts as the reservation station of the memory unit)."""

    def __init__(self, rob):
        self.rob = rob
        self.op = rob.ins.op
        self.imm = rob.ins.imm
        self.base_v = None
        self.base_q = None
        self.base_r = 0
        self.data_v = None                # store data (Sd only)
        self.data_q = None
        self.data_r = 0
        self.address = None
        self.addr_cycle = None            # cycle the effective address was computed
        self.state = 'wait'               # wait -> exe -> addr -> mem/done (Ld) | retired (Sd)

    def addr_known(self, cycle):
        return self.addr_cycle is not None and self.addr_cycle < cycle

    def data_known(self, cycle):
        return self.data_q is None and self.data_r < cycle


class FU:
    """One functional unit.  Pipelined units accept one new op per cycle;
    unpipelined units accept a new op only when the previous one has left."""

    def __init__(self, name, latency, pipelined):
        self.name = name
        self.latency = latency
        self.pipelined = pipelined
        self.inflight = []                # list of (rob_entry, payload, end_cycle)
        self.last_accept = 0

    def can_accept(self, cycle):
        if self.pipelined:
            return self.last_accept != cycle
        return not self.inflight

    def start(self, rob, payload, cycle):
        end = cycle + self.latency - 1
        self.inflight.append((rob, payload, end))
        self.last_accept = cycle
        return end


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
class Config:
    def __init__(self):
        # name: [num_rs, ex_cycles, mem_cycles, num_fus]
        self.int_rs, self.int_ex, self.int_fu = 2, 1, 1
        self.fpa_rs, self.fpa_ex, self.fpa_fu = 3, 3, 1
        self.fpm_rs, self.fpm_ex, self.fpm_fu = 2, 20, 1
        self.lsq_size, self.ls_ex, self.ls_mem, self.ls_fu = 3, 1, 4, 1
        self.rob_size = 128
        self.issue_width = 1
        self.commit_width = None   # default: equal to issue width
        self.cdb_width = 1         # one CDB, as in the assignment
        self.btb_size = 8
        self.max_cycles = 100000
        self.reg_int = [0] * 32
        self.reg_fp = [0.0] * 32
        self.memory = [0] * MEM_BYTES

    def finalize(self):
        if not 1 <= self.issue_width <= 4:
            raise SimError('issue width must be between 1 and 4 (got %d)' % self.issue_width)
        if self.commit_width is None:
            self.commit_width = self.issue_width
        for name in ('int_rs', 'int_ex', 'int_fu', 'fpa_rs', 'fpa_ex', 'fpa_fu', 'fpm_rs',
                     'fpm_ex', 'fpm_fu', 'lsq_size', 'ls_ex', 'ls_mem', 'ls_fu', 'rob_size',
                     'commit_width', 'cdb_width'):
            if getattr(self, name) < 1:
                raise SimError('configuration value %s must be >= 1' % name)
        self.reg_int[0] = 0


def _num(s):
    s = s.strip()
    try:
        return int(s)
    except ValueError:
        return float(s)


REG_RE = re.compile(r'^([RF])(\d+)$', re.I)
MEMOP_RE = re.compile(r'^(-?\d+)\(\s*(R\d+)\s*\)$', re.I)
UNIT_RE = re.compile(r'^(integer\s+adder|fp\s+adder|fp\s+multiplier|load\s*/\s*store\s+unit)\s+(.*)$', re.I)


def _reg(tok, kinds, lineno):
    m = REG_RE.match(tok)
    if not m or m.group(1).upper() not in kinds or int(m.group(2)) > 31:
        raise SimError('line %d: bad register "%s"' % (lineno, tok))
    return m.group(1).upper() + str(int(m.group(2)))


def parse_instruction(line, pc, lineno):
    toks = [t for t in re.split(r'[\s,]+', line.strip()) if t]
    opl = toks[0].lower()
    if opl not in OPCODES:
        raise SimError('line %d: unknown instruction "%s"' % (lineno, line.strip()))
    op = CANON[opl]
    args = toks[1:]

    def need(n):
        if len(args) != n:
            raise SimError('line %d: %s expects %d operands' % (lineno, op, n))

    if op in ('Add', 'Sub'):
        need(3)
        d, s, t = (_reg(a, 'R', lineno) for a in args)
        return Instr(pc, '%s %s, %s, %s' % (op, d, s, t), op, dest=d, srcs=[s, t])
    if op == 'Addi':
        need(3)
        d, s = _reg(args[0], 'R', lineno), _reg(args[1], 'R', lineno)
        imm = int(args[2])
        return Instr(pc, '%s %s, %s, %d' % (op, d, s, imm), op, dest=d, srcs=[s], imm=imm)
    if op in ('Add.d', 'Sub.d', 'Mult.d'):
        need(3)
        d, s, t = (_reg(a, 'F', lineno) for a in args)
        return Instr(pc, '%s %s, %s, %s' % (op, d, s, t), op, dest=d, srcs=[s, t])
    if op in ('Beq', 'Bne'):
        need(3)
        s, t = _reg(args[0], 'R', lineno), _reg(args[1], 'R', lineno)
        off = int(args[2])
        return Instr(pc, '%s %s, %s, %d' % (op, s, t, off), op, srcs=[s, t], imm=off)
    if op in ('Ld', 'Sd'):
        if len(args) == 3:                      # tolerate "Ld F1, 8 (R1)"
            args = [args[0], args[1] + args[2]]
        need(2)
        r = _reg(args[0], 'RF', lineno)
        m = MEMOP_RE.match(args[1])
        if not m:
            raise SimError('line %d: bad memory operand "%s"' % (lineno, args[1]))
        off, base = int(m.group(1)), _reg(m.group(2), 'R', lineno)
        text = '%s %s, %d(%s)' % (op, r, off, base)
        if op == 'Ld':
            return Instr(pc, text, op, dest=r, imm=off, base=base)
        return Instr(pc, text, op, imm=off, base=base, data=r)
    raise SimError('line %d: unsupported instruction' % lineno)


def parse_input(path):
    """Parse a test-bench file: hardware table, parameters, initial values, program."""
    cfg = Config()
    program = []
    with open(path) as f:
        lines = f.read().splitlines()
    for lineno, raw in enumerate(lines, 1):
        line = re.split(r'//|;', raw)[0].strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith('#') or 'cycles in ex' in low:
            continue                                    # table header / comment
        m = UNIT_RE.match(line)
        if m:
            unit = re.sub(r'\s+', ' ', m.group(1).lower()).replace(' / ', '/').replace('/ ', '/').replace(' /', '/')
            nums = [int(x) for x in m.group(2).split()]
            if unit == 'load/store unit':
                if len(nums) == 3:
                    nums.append(1)
                if len(nums) != 4:
                    raise SimError('line %d: load/store unit needs: #rs ex_cycles mem_cycles [#fus]' % lineno)
                cfg.lsq_size, cfg.ls_ex, cfg.ls_mem, cfg.ls_fu = nums
            else:
                if len(nums) == 2:
                    nums.append(1)
                if len(nums) != 3:
                    raise SimError('line %d: %s needs: #rs ex_cycles [#fus]' % (lineno, unit))
                if unit == 'integer adder':
                    cfg.int_rs, cfg.int_ex, cfg.int_fu = nums
                elif unit == 'fp adder':
                    cfg.fpa_rs, cfg.fpa_ex, cfg.fpa_fu = nums
                else:
                    cfg.fpm_rs, cfg.fpm_ex, cfg.fpm_fu = nums
            continue
        if '=' in line:
            for item in line.split(','):
                item = item.strip()
                if not item:
                    continue
                if '=' not in item:
                    raise SimError('line %d: cannot parse "%s"' % (lineno, item))
                key, val = [x.strip() for x in item.split('=', 1)]
                k = re.sub(r'\s+', ' ', key.lower())
                if k in ('rob entries', 'rob size', '# of rob entries'):
                    cfg.rob_size = int(val)
                elif k in ('issue width', 'issue_width'):
                    cfg.issue_width = int(val)
                elif k in ('commit width', 'commit_width'):
                    cfg.commit_width = int(val)
                elif k in ('cdb width', 'cdb_width', '# of cdbs', 'cdbs', 'cdb count'):
                    cfg.cdb_width = int(val)
                elif REG_RE.match(key):
                    r = REG_RE.match(key)
                    idx = int(r.group(2))
                    if idx > 31:
                        raise SimError('line %d: bad register %s' % (lineno, key))
                    if r.group(1).upper() == 'R':
                        if idx == 0:
                            raise SimError('line %d: R0 is hard-wired to 0' % lineno)
                        cfg.reg_int[idx] = int(_num(val))
                    else:
                        cfg.reg_fp[idx] = float(_num(val))
                elif re.match(r'^mem\s*\[\s*\d+\s*\]$', key, re.I):
                    addr = int(re.search(r'\d+', key).group())
                    if addr >= MEM_BYTES:
                        raise SimError('line %d: memory address %d must be < %d'
                                       % (lineno, addr, MEM_BYTES))
                    cfg.memory[addr] = _num(val)
                else:
                    raise SimError('line %d: unknown parameter "%s"' % (lineno, key))
            continue
        program.append(parse_instruction(line, len(program), lineno))
    if not program:
        raise SimError('no instructions found in %s' % path)
    return cfg, program


# --------------------------------------------------------------------------
# Whole-machine state
# --------------------------------------------------------------------------
class Machine:
    def __init__(self, cfg, program, verbose=False):
        cfg.finalize()
        self.cfg = cfg
        self.program = program
        self.reg_int = list(cfg.reg_int)
        self.reg_fp = list(cfg.reg_fp)
        self.memory = list(cfg.memory)
        self.rat = {}                         # register name -> ROBEntry (absent = arch reg)
        self.rob = deque()
        self.rs = {'int': [], 'fpadd': [], 'fpmul': []}
        self.rs_size = {'int': cfg.int_rs, 'fpadd': cfg.fpa_rs, 'fpmul': cfg.fpm_rs}
        self.fus = {
            'int':   [FU('IntAdd%d' % i, cfg.int_ex, False) for i in range(cfg.int_fu)],
            'fpadd': [FU('FPAdd%d' % i, cfg.fpa_ex, True) for i in range(cfg.fpa_fu)],
            'fpmul': [FU('FPMul%d' % i, cfg.fpm_ex, True) for i in range(cfg.fpm_fu)],
            'addr':  [FU('AddrAdd%d' % i, cfg.ls_ex, False) for i in range(cfg.ls_fu)],
        }
        self.lsq = []                         # program order
        self.results = []                     # finished ops waiting for a CDB
        self.mem_busy_until = 0               # single-ported, non-pipelined memory
        self.btb = BTB(cfg.btb_size)
        self.pc = 0                           # word index of next instruction to fetch
        self.fetch_resume = 1                 # first cycle fetch/issue may proceed
        self.seq = 0
        self.committed = []
        self.cycle = 0
        self.verbose = verbose
        self.log = []
        self.stats = {'issued': 0, 'squashed': 0, 'branches': 0, 'mispredicts': 0,
                      'issue_per_cycle': {}, 'stall_rob': 0, 'stall_rs': 0}

    def trace(self, msg):
        if self.verbose:
            self.log.append('  [%4d] %s' % (self.cycle, msg))

    # ---- register read through the RAT (used by issue) ----
    def read_reg(self, name, cycle):
        """Return (value, producer, ready_cycle).  producer is None if value is valid."""
        if name == 'R0':
            return 0, None, 0
        e = self.rat.get(name)
        if e is None:
            idx = int(name[1:])
            return (self.reg_int[idx] if name[0] == 'R' else self.reg_fp[idx]), None, 0
        if e.wb is not None:                  # broadcast already -> value is in the ROB
            return e.value, None, e.wb
        return None, e, None

    # ---- misprediction recovery ----
    def squash_after(self, br, cycle):
        """Squash every instruction younger than branch `br` (one recovery cycle)."""
        dead = set()
        while self.rob and self.rob[-1].seq > br.seq:
            e = self.rob.pop()
            e.squashed = True
            dead.add(e.seq)
        self.stats['squashed'] += len(dead)
        # clear reservation stations (and their wait-for tags), LSQ, FUs, CDB queue
        for k in self.rs:
            self.rs[k] = [r for r in self.rs[k] if r.rob.seq not in dead]
        self.lsq = [l for l in self.lsq if l.rob.seq not in dead]
        for fus in self.fus.values():
            for fu in fus:
                fu.inflight = [x for x in fu.inflight if x[0].seq not in dead]
        self.results = [e for e in self.results if e.seq not in dead]
        # recover the RAT from the surviving (older) ROB entries
        self.rat = {}
        for e in self.rob:
            if e.dest:
                self.rat[e.dest] = e
        self.trace('squash %d younger instruction(s); RAT recovered; fetch resumes at cycle %d'
                   % (len(dead), cycle + 2))
