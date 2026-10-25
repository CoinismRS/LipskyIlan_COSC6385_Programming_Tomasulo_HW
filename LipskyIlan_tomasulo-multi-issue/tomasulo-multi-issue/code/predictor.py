# Branch predictor: 8-entry branch target buffer with a 1-bit predictor per entry.
#
# * Indexed by the least-significant 3 bits of the word address of the PC
#   (byte PC >> 2) & 7  ==  instruction index & 7.
# * Each entry holds a tag (the branch PC), the target and a 1-bit
#   taken / not-taken history.  A miss predicts not-taken (fall through).
# * Prediction happens in the ISSUE stage; the entry is written when the
#   branch resolves at the end of its EX stage.


class BTBEntry:
    def __init__(self):
        self.valid = False
        self.tag = None
        self.target = None
        self.taken = False


class BTB:
    def __init__(self, size=8):
        self.size = size
        self.entries = [BTBEntry() for _ in range(size)]
        self.lookups = 0
        self.hits = 0

    def index(self, pc):
        """pc is the instruction (word) index, i.e. byte address >> 2."""
        return pc % self.size

    def predict(self, pc):
        """Return (predict_taken, next_pc) for the branch at word index pc."""
        self.lookups += 1
        e = self.entries[self.index(pc)]
        if e.valid and e.tag == pc:
            self.hits += 1
            if e.taken:
                return True, e.target
        return False, pc + 1

    def update(self, pc, taken, target):
        e = self.entries[self.index(pc)]
        e.valid = True
        e.tag = pc
        e.target = target
        e.taken = taken

    def dump(self):
        rows = []
        for i, e in enumerate(self.entries):
            if e.valid:
                rows.append('  BTB[%d]: PC=%d target=%d bit=%s' %
                            (i, e.tag * 4, e.target * 4, 'T' if e.taken else 'NT'))
        return rows
