# Tomasulo Simulator with Multi-Issue

This project extends the provided Python simulator of Tomasulo's algorithm, which has a reorder
buffer, a RAT and a load/store queue, so that it **issues 1–4 instructions per cycle, in program
order**. It also adds the BTB branch predictor from the handout, with speculative issue and
misprediction recovery.

The original code structure is kept: the same files, stage functions and data structures. The
changes are marked with comments in the code. The provided code is in `original_code/` for
comparison.

**Repository:** https://github.com/CoinismRS/LipskyIlan_COSC6385_Programming_Tomasulo_HW

Requires **Python 3** only. Rebuilding the report also needs `pdflatex` and `matplotlib`.

## Quick start

```bash
git clone https://github.com/CoinismRS/LipskyIlan_COSC6385_Programming_Tomasulo_HW.git
cd LipskyIlan_COSC6385_Programming_Tomasulo_HW
cd code
python3 main.py                                   # runs code.in (the handout example)
python3 main.py ../tests/test1_loop.txt           # issue width taken from the file
python3 main.py ../tests/test1_loop.txt -w 4      # override the issue width (1-4)
python3 main.py ../tests/test2_independent.txt -w 4 --cdb 4   # 4 CDBs
```

| Option | Meaning |
|---|---|
| `-w N`, `--width N` | issue width, 1–4 (overrides `Issue width =` in the file) |
| `--cdb N` | number of CDBs, i.e. results broadcast per cycle (default 1) |
| `--commit N` | commit width (default: same as the issue width) |

## Input format

The input file is case-insensitive, and commas between operands are optional. Text after `//`
is a comment.

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

* **Instructions:** `Ld`, `Sd`, `Beq`, `Bne`, `Add`, `Addi`, `Sub`, `Add.d`, `Sub.d` and
  `Mult.d`.
* **Branch offsets:** given in instructions (words). The target is `PC + 4 + (offset << 2)`,
  so in the example `-4` jumps back to the first line.
* **Registers:** R0–R31 and F0–F31. R0 is always 0, and every register starts at 0 unless the
  file sets it.
* **Memory:** 256 bytes, with byte addresses 0–255.
* **"# of FUs" for the load/store unit:** this is the number of address adders. Memory itself
  is single-ported.

## Output

The output has four parts, in the same style as the original simulator:

* the instruction status table, with the ISSUE, EXE, MEM, WB and COMMIT cycles of every
  committed instruction;
* all register values;
* the non-zero memory values;
* a summary line: total cycles, IPC, mispredictions and squashed instructions.

```
                              ISSUE          EXE            MEM            WB             COMMIT
Ld F2 0(R1)                   [1]            [2, 2]         [3, 7]         [9]            [10]
Mult.d F4 F2 F20              [2]            [10, 24]       []             [25]           [26]
...
REGISTER VALUES
        R0        R1        R2   ...
value:  0         0         20   ...
NON-ZERO MEMORY VALUES
Addresses      Values
4              3.0
...
```

## What was changed

* **`issue.py`:** issues up to W instructions per cycle, in order. It stops at the first
  instruction that cannot get a ROB entry and an RS or load/store-queue entry, and after a
  branch predicted taken.
* **`branch.py` (new):**
  * an 8-entry BTB (index = PC word address & 7) with a 1-bit predictor per entry;
  * misprediction recovery: it recovers the RAT, clears the wrong-path RS entries and their
    tags, removes wrong-path work from the FUs, the load/store queue and the CDB, and clears
    the ROB entries after the branch;
  * fetch restarts at cycle n+2.
* **`exe.py`:**
  * several FUs per type;
  * oldest-ready-first selection;
  * pipelined FP units and an unpipelined integer adder;
  * branches report their outcome to `branch.py`.
* **`wb.py`:** several CDBs. The RAT update no longer overwrites a younger rename.
* **`commit.py`:** up to the commit width per cycle; branches get a commit cycle.
* **`mem.py`:** stores go to memory only as the ROB head, plus forwarding fixes.
* **`init.py` / `main.py`:** read the configuration from the input file (it was hard-coded)
  and print the final registers and memory.

The report (`report/report.pdf`) shows the original and modified code side by side and lists
the bugs that were fixed in the provided code.

## Testing

```bash
python3 tools/run_tests.py                     # 9 tests x W=1..4 x {1 CDB, W CDBs}
python3 tools/run_tests.py --tables results    # also regenerate results/
python3 tools/fuzz.py 2000                     # random programs/configs vs. reference
python3 report/build_report.py                 # rebuild report.pdf from fresh simulations
```

Every run is compared against a sequential interpreter, which must produce the same
registers, the same memory and the same committed instruction sequence. Each run is also
checked for:

* in-order issue and commit;
* the issue, commit and CDB width limits;
* stage order;
* operand-ready timing;
* use of the single memory port.

## Known limitations

* A load never passes a store whose address is still unknown, as in the original code.
* A store is sent to memory only when it is the oldest instruction in the ROB.
* Each memory address holds one value, as in the original code, so overlapping word accesses
  are not modelled.
* The table lists committed instructions only. Squashed instructions are counted in the
  summary line.
