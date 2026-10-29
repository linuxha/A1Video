"""Single source of truth for the redesigned Apple-1 terminal.

Every constant here mirrors a table in docs/apple1-video-redesign.md.  The ROM
builders (roms.py) and the hardware simulator (sim.py) both import from this
module, so a change here changes both consistently.
"""

# ---------------------------------------------------------------- clocks
OSC_HZ = 14_318_180                  # canned oscillator, 4 x NTSC colour burst
DOT_HZ = OSC_HZ / 2                  # 74AC74 divide-by-2
DOTS_PER_CHAR = 7                    # U3 74HC163 counts phases 0..6
CHAR_HZ = DOT_HZ / DOTS_PER_CHAR     # = CLA, 1.0227 MHz (Apple-1 CPU clock)
CHAR_NS = 1e9 / CHAR_HZ

# ---------------------------------------------------------------- display
COLS = 40
ROWS = 24
SCANS_PER_ROW = 8
ROW_STRIDE = 64                      # RAM address = row * 64 + col
RAM_ADDR_BITS = 11

# ---------------------------------------------------------------- horizontal (char periods)
H_TOTAL = 65                         # 65 * 7 = 455 dots = 63.556 us
H_VISIBLE = range(1, COLS + 1)       # dots appear one char after the fetch at H = col
H_SYNC = range(47, 52)               # 5 chars = 4.89 us

# ---------------------------------------------------------------- vertical (lines)
V_TOTAL = 262                        # progressive, 60.05 Hz
V_ACTIVE = ROWS * SCANS_PER_ROW      # 192
V_SYNC = range(216, 219)             # 3 lines

# ---------------------------------------------------------------- timing ROM (U9)
# Address: A0-A6 = H, A7-A15 = V, A16 = 0.  Output registered by U10 at CHAR_END,
# so the builder stores at (H, V) the value wanted during the *next* char period.
T_H_BITS = 7
T_NCSYNC = 1 << 0                    # 0 = sync tip
T_NBLANK = 1 << 1                    # 1 = visible (dots enabled)
T_H_END = 1 << 2                     # H counter clears at end of this period
T_V_END = 1 << 3                     # V counter clears (with H_END)
T_ROW_CLK = 1 << 4                   # VROW += 1
T_FRAME_START = 1 << 5               # VROW <- TOP, FRAMESEEN <- 1

# ---------------------------------------------------------------- char ROM (U28)
# Address: A0-A2 = scan line V[2:0], A3-A9 = code[6:0], A10 = CURSOR, A11 = BANK.
# Data: D7 is the first dot shifted out (74HC166 input H), D7..D3 = glyph columns
# left to right, D2..D1 = inter-character gap, D0 unused.
CG_CURSOR_BIT = 10
CG_BANK_BIT = 11
CURSOR_CODE = 0x40                   # '@', as on the original

# ---------------------------------------------------------------- sequencer ROMs (U33 lo, U34 hi)
# Address fields
S_STATE_BITS = 5                     # A0-A4
S_DA = 1 << 5                        # A5  DA (synchronised)
S_CLR = 1 << 6                       # A6  CLR switch (synchronised)
S_COL39 = 1 << 7                     # A7  COL == 39 (74HC21)
S_ROW_EQ_TOP = 1 << 8                # A8  ROW == TOP (74HC688)
S_READY = 1 << 9                     # A9  /SLOW + FRAMESEEN
S_CHAR_SHIFT = 10                    # A10-A16 latched char[6:0]
SEQ_ADDR_BITS = 17

# 16-bit output word (lo byte in U33, hi byte in U34); D0-D4 = next state.
C_WE = 1 << 5
C_COL_INC = 1 << 6
C_COL_CLR = 1 << 7
C_ROW_INC = 1 << 8
C_ROW_CLR = 1 << 9
C_TOP_INC = 1 << 10
C_TOP_CLR = 1 << 11
C_LATCH_LD = 1 << 12
C_LATCH_CLR = 1 << 13
C_RDA = 1 << 14
C_FRAMESEEN_CLR = 1 << 15

ROM_SIZE = 1 << 17                   # SST39SF010A, 128K x 8
