# Multi-issue Tomasulo Simulator

A Python simulator of Tomasulo's algorithm with a reorder buffer, register renaming (RAT),
a load/store queue, a BTB-based branch predictor and speculative execution. It extends the
provided single-issue simulator to **issue 1–4 instructions per cycle, in program order**.

Requires **Python 3.6+** and nothing else. The test tools also use only the standard library.
Rebuilding the report needs `pdflatex` and `matplotlib`.

## Quick start

```bash
cd code
python3 main.py                                   # runs code.in (the handout example)
python3 main.py ../tests/test1_loop.txt           # issue width taken from the file
python3 main.py ../tests/test1_loop.txt -w 4      # override the issue width (1-4)
python3 main.py ../tests/test2_independent.txt -w 4 --cdb 4   # 4 CDBs
python3 main.py ../tests/test5_branches.txt -w 2 -v --btb     # cycle trace + final BTB
```

| Option | Meaning |
|---|---|
| `-w N`, `--width N` | issue width, 1–4 (overrides `Issue width =` in the file) |
| `--cdb N` | number of CDBs, i.e. results broadcast per cycle (default 1) |
| `--commit N` | commit width (default: equal to the issue width) |
| `-v` | print a cycle-by-cycle trace (issue, exec, mem, wb, commit, squash) |
| `--btb` | print the final BTB contents |

## Input format

The input file is case-insensitive, and commas between operands are optional. Lines starting
with `//` or `#` are comments.

```
                 # of rs   Cycles in EX   Cycles in Mem   # of FUs
Integer adder      2          1                              1
FP adder           3          3                              1
FP multiplier      2          20                             1
Load/store unit    3          1               4              1

ROB entries = 128
Issue width = 2            // 1-4, default 1
CDB width = 1              // optional, default 1
Commit width = 2           // optional, default = issue width
R1=10, R2=20, F2=30.1
Mem[4]=1, Mem[8]=2, Mem[12]=3.4

Add.d F1, F2, F3
Ld F4, 8(R1)
Addi R2, R2, -10
Bne R2, R3, -4
```

* **Supported instructions:** `Ld`, `Sd`, `Beq`, `Bne`, `Add`, `Addi`, `Sub`, `Add.d`,
  `Sub.d` and `Mult.d`.
* **Branch offsets** are in instructions (words): the target is `PC + 4 + (offset << 2)`.
  In the example above, `-4` jumps back to the first line.
* **Registers:** R0–R31 (R0 is always 0) and F0–F31. All registers start at 0 unless
  initialized in the file.
* **Memory:** 256 bytes, using byte addresses 0–255. Use word-aligned addresses.

## Output

The simulator prints the instruction status table (ISSUE, EX, MEM, WB and COMMIT cycles for
every committed instruction), the values of all registers, the non-zero memory values, and a
summary: total cycles, IPC, mispredictions and squashed instructions.

```
                    ISSUE   EX        MEM       WB      COMMIT
Ld F2, 0(R1)        1       2-2       3-7       8       9
Mult.d F4, F2, F20  1       9-23      -         24      25
...
REGISTER VALUES
        R0        R1        R2   ...
value:  0         0         20   ...
NON-ZERO MEMORY VALUES
Addresses   Values
4           3.0
...
```

## Processor model in brief

* **ISSUE:** up to W instructions per cycle, in order. Issue stops at the first instruction
  that cannot get a ROB entry and an RS/LSQ entry. A branch predicted taken ends the issue
  group for that cycle.
* **Branches:** an 8-entry BTB (indexed by PC word address & 7) with a 1-bit predictor per
  entry; prediction happens at ISSUE and the branch resolves at the end of EX. On a
  misprediction detected in cycle n, the simulator squashes younger instructions and recovers
  the RAT, and correct-path fetch starts in cycle n+2.
* **Functional units:** the integer adder is unpipelined, while the FP adder and FP multiplier
  are pipelined. Each unit type can have several FUs, and each FU takes the oldest ready
  instruction.
* **Loads and stores:** the load/store queue uses a dedicated address adder. A load waits for
  all older store addresses to be known. It then gets its value by store-to-load forwarding
  (1 cycle) or from memory (single-ported, non-pipelined). Stores write memory at commit.
* **WB:** CDB-width results per cycle, oldest first. **COMMIT:** commit-width instructions
  per cycle, in order.

## Repository layout

```
code/      simulator: main.py, init.py, issue.py, exe.py, mem.py, wb.py, commit.py,
           predictor.py, print_status.py, code.in
tests/     test benches test0 ... test8 (see the header comment in each file)
tools/     reference.py (sequential golden model), checks.py, run_tests.py, fuzz.py
results/   full simulator output of every test at W=1..4 (CDB=1 and CDB=W)
report/    report.pdf, report.tex, build_report.py (regenerates all tables and figures)
```

## Testing

```bash
python3 tools/run_tests.py                     # 9 tests x W=1..4 x {1 CDB, W CDBs}
python3 tools/run_tests.py --tables results    # also regenerate results/
python3 tools/fuzz.py 2000                     # random programs/configs vs. golden model
python3 report/build_report.py                 # rebuild report.pdf from fresh simulations
```

Every run is compared with a sequential interpreter, which must produce the same registers,
the same memory and the same committed instruction stream. The tests also check the timing
rules: in-order issue and commit, the width limits, stage ordering and producer→consumer
timing. All 72 directed runs and 20,000 random runs pass.

## Known limitations

* Loads do not speculate past stores whose addresses are still unknown (conservative memory
  disambiguation, as in the original code).
* Each memory address holds one value, as in the original simulator, so unaligned or
  overlapping word accesses are not modeled.
* The output table lists committed instructions only. Use `-v` to see the squashed
  wrong-path instructions.
