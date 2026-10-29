"""Builders for the four SST39SF010A images: timing, chargen, seq_lo, seq_hi.

Each builder returns a bytes object of spec.ROM_SIZE.  Unused locations are
filled so that a counter or state register that powers up out of range
recovers on its own.
"""

from . import spec as S
from .font import UPPER, LOWER, glyph_rows

# ====================================================================== timing ROM

def _wanted_timing(h, v):
    """Register value wanted *during* char period (h, v)."""
    hs = h in S.H_SYNC
    vs = v in S.V_SYNC
    out = 0
    if not (hs ^ vs):                                  # serrated composite sync
        out |= S.T_NCSYNC
    if h in S.H_VISIBLE and v < S.V_ACTIVE:
        out |= S.T_NBLANK
    if h == S.H_TOTAL - 1:
        out |= S.T_H_END
        if v == S.V_TOTAL - 1:
            out |= S.T_V_END | S.T_FRAME_START
        if v < S.V_ACTIVE and v % S.SCANS_PER_ROW == S.SCANS_PER_ROW - 1:
            out |= S.T_ROW_CLK
    return out


def timing_addr(h, v):
    return (v << S.T_H_BITS) | h


def build_timing():
    rom = bytearray(S.ROM_SIZE)
    for addr in range(1 << 16):
        h = addr & ((1 << S.T_H_BITS) - 1)
        v = addr >> S.T_H_BITS
        if h < S.H_TOTAL and v < S.V_TOTAL:
            # The output register adds one char of delay, so store the value
            # wanted in the following period.
            nh, nv = h + 1, v
            if nh == S.H_TOTAL:
                nh, nv = 0, (v + 1) % S.V_TOTAL
            rom[addr] = _wanted_timing(nh, nv)
        else:
            # Out of range (power-up only): blank, no sync, force the counters home.
            rom[addr] = S.T_NCSYNC | S.T_H_END | (S.T_V_END if v >= S.V_TOTAL - 1 else 0)
    return bytes(rom)

# ====================================================================== char ROM

def _glyph_for(code, bank):
    """5-bit-wide glyph (8 scan lines) for a stored 7-bit code, or None = blank."""
    if code < 0x20:
        return None                                    # $00 is the clear value
    if code >= 0x60:
        if bank == 1:
            return LOWER[chr(code)]
        code -= 0x20                                   # fold to upper case (verify vs. original)
    return UPPER[chr(code)]


def chargen_addr(code, scan, cursor=0, bank=0):
    return (bank << S.CG_BANK_BIT) | (cursor << S.CG_CURSOR_BIT) | (code << 3) | scan


def build_chargen():
    rom = bytearray(S.ROM_SIZE)
    cursor_rows = glyph_rows(UPPER[chr(S.CURSOR_CODE)])
    for bank in (0, 1):
        for code in range(128):
            g = _glyph_for(code, bank)
            rows = glyph_rows(g) if g else [0] * 8
            for scan in range(8):
                rom[chargen_addr(code, scan, 0, bank)] = rows[scan] << 3
                rom[chargen_addr(code, scan, 1, bank)] = cursor_rows[scan] << 3
    return bytes(rom)

# ====================================================================== sequencer ROMs
# Moore machine: the ROM output is next_state plus that state's controls, so
# the controls are held during the period the register shows that state.
# Counter changes happen at the end of that period.

IDLE, LOAD, DECODE, PRINT, NL, SCRCHK, SCROLL, CLRL_A, CLRL_A_END, ACKW, \
    ACK1, ACK2, ACK3, WAITDA, CLRALL, CLRL_B, NEXTROW, CLRCHK, WAITCLR = range(19)

STATE_NAMES = ["IDLE", "LOAD", "DECODE", "PRINT", "NL", "SCRCHK", "SCROLL",
               "CLRL_A", "CLRL_A_END", "ACKW", "ACK1", "ACK2", "ACK3", "WAITDA",
               "CLRALL", "CLRL_B", "NEXTROW", "CLRCHK", "WAITCLR"]

CONTROLS = {
    IDLE: 0,
    LOAD: S.C_LATCH_LD | S.C_FRAMESEEN_CLR,
    DECODE: 0,
    PRINT: S.C_WE | S.C_COL_INC,
    NL: S.C_COL_CLR | S.C_ROW_INC | S.C_LATCH_CLR,
    SCRCHK: 0,
    SCROLL: S.C_TOP_INC,
    CLRL_A: S.C_WE | S.C_COL_INC,
    CLRL_A_END: S.C_COL_CLR,
    ACKW: 0,
    ACK1: S.C_RDA,
    ACK2: S.C_RDA,
    ACK3: S.C_RDA,
    WAITDA: 0,
    CLRALL: S.C_TOP_CLR | S.C_ROW_CLR | S.C_COL_CLR | S.C_LATCH_CLR,
    CLRL_B: S.C_WE | S.C_COL_INC,
    NEXTROW: S.C_COL_CLR | S.C_ROW_INC,
    CLRCHK: 0,
    WAITCLR: 0,
}


def next_state(state, da, clr, col39, row_eq_top, ready, char):
    """Transition taken at the end of a period spent in `state`.

    The inputs show counter values *before* that period's controls are
    applied (e.g. in PRINT, col39 means column 39 was just written).
    """
    ack = ACK1 if ready else ACKW
    if state == IDLE:
        if clr:
            return CLRALL
        return LOAD if da else IDLE
    if state == LOAD:
        return DECODE
    if state == DECODE:
        if char == 0x0D:
            return NL
        if char >= 0x20:                               # RD6 or RD7 set
            return PRINT
        return ack                                     # other control codes ignored
    if state == PRINT:
        return NL if col39 else ack
    if state == NL:
        return SCRCHK
    if state == SCRCHK:                                # ROW now holds the new row
        return SCROLL if row_eq_top else CLRL_A
    if state == SCROLL:
        return CLRL_A
    if state == CLRL_A:
        return CLRL_A_END if col39 else CLRL_A
    if state == CLRL_A_END:
        return ack
    if state == ACKW:
        return ACK1 if ready else ACKW
    if state == ACK1:
        return ACK2
    if state == ACK2:
        return ACK3
    if state == ACK3:
        return WAITDA
    if state == WAITDA:
        return WAITDA if da else IDLE
    if state == CLRALL:
        return CLRL_B
    if state == CLRL_B:
        return NEXTROW if col39 else CLRL_B
    if state == NEXTROW:
        return CLRCHK
    if state == CLRCHK:                                # ROW wrapped back to TOP = 0
        return WAITCLR if row_eq_top else CLRL_B
    if state == WAITCLR:
        return WAITCLR if clr else IDLE
    return IDLE                                        # unused codes recover


def seq_word(addr):
    state = addr & ((1 << S.S_STATE_BITS) - 1)
    ns = next_state(state,
                    bool(addr & S.S_DA), bool(addr & S.S_CLR),
                    bool(addr & S.S_COL39), bool(addr & S.S_ROW_EQ_TOP),
                    bool(addr & S.S_READY), addr >> S.S_CHAR_SHIFT)
    return ns | CONTROLS[ns]


def build_sequencer():
    """Return (lo, hi) images: U33 holds D0-D7, U34 holds D8-D15."""
    lo = bytearray(S.ROM_SIZE)
    hi = bytearray(S.ROM_SIZE)
    for addr in range(1 << S.SEQ_ADDR_BITS):
        w = seq_word(addr)
        lo[addr] = w & 0xFF
        hi[addr] = w >> 8
    return bytes(lo), bytes(hi)


def build_all():
    lo, hi = build_sequencer()
    return {
        "timing.bin": build_timing(),
        "chargen.bin": build_chargen(),
        "seq_lo.bin": lo,
        "seq_hi.bin": hi,
    }
