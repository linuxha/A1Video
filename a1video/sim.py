"""Character-period-accurate simulator of the redesigned terminal.

The model treats the four ROMs as opaque images (it never calls the Python
transition function), so a passing simulation validates the ROM contents.
It models the hardware of docs/apple1-video-redesign.md §3:

* one step() = one 977.8 ns character period (7 dots)
* registered outputs (timing ROM -> U10, sequencer -> U36/U38) and all counters
  change together at CHAR_END (end of the period)
* the RAM is read for video in PH0-3 and written in the PH4-6 write slot
* the 74HC166 shows during period n the glyph row fetched in period n-1
"""

import struct
import zlib

from . import spec as S
from .roms import build_all, chargen_addr

LEVEL_SYNC, LEVEL_BLACK, LEVEL_WHITE = 0.0, 0.3, 1.0


def _mod24_inc(x):
    """74HC163 pair with synchronous clear when Q4.Q2.Q1.Q0 (== 23)."""
    return 0 if (x & 0b10111) == 0b10111 else (x + 1) & 0x1F


class Terminal:
    def __init__(self, roms=None, slow=False, bank=0, seed_ram=None):
        roms = roms or build_all()
        self.timing = roms["timing.bin"]
        self.chargen = roms["chargen.bin"]
        self.seq_lo = roms["seq_lo.bin"]
        self.seq_hi = roms["seq_hi.bin"]
        self.slow = slow
        self.bank = bank
        # power-up state: registers 0, RAM may hold garbage
        self.ram = bytearray(seed_ram) if seed_ram else bytearray(1 << S.RAM_ADDR_BITS)
        self.h = self.v = 0
        self.treg = 0
        self.seqreg = 0
        self.col = self.row = self.top = self.vrow = 0
        self.latch = 0
        self.shifter = 0
        self.framecnt = 0
        self.frameseen = False
        self.da_sync = self.clr_sync = False
        # inputs from the PIA / switch
        self.rd = 0
        self.da = False
        self.clr = False
        self.periods = 0

    # ---------------------------------------------------------------- outputs
    @property
    def state(self):
        return self.seqreg & ((1 << S.S_STATE_BITS) - 1)

    @property
    def rda(self):
        return bool(self.seqreg & S.C_RDA)

    def dots(self):
        """Composite level for each of the 7 dots of the current period."""
        if not self.treg & S.T_NCSYNC:
            return [LEVEL_SYNC] * S.DOTS_PER_CHAR
        if not self.treg & S.T_NBLANK:
            return [LEVEL_BLACK] * S.DOTS_PER_CHAR
        sh = self.shifter
        return [LEVEL_WHITE if (sh >> (7 - i)) & 1 else LEVEL_BLACK
                for i in range(S.DOTS_PER_CHAR)]

    # ---------------------------------------------------------------- one char period
    def step(self):
        c = self.seqreg

        # LATCH_LD rises at the start of the period; LATCH_CLR is asynchronous.
        if c & S.C_LATCH_CLR:
            self.latch = 0
        elif c & S.C_LATCH_LD:
            self.latch = self.rd & 0x7F

        # PH0-3: video read; U25 latches code + cursor match; char ROM lookup.
        hcol = self.h & 0x3F
        code = self.ram[self.vrow * S.ROW_STRIDE + hcol] & 0x7F
        curmatch = self.vrow == self.row and hcol == self.col
        blink = (self.framecnt >> 4) & 1
        next_shifter = self.chargen[chargen_addr(code, self.v & 7,
                                                 int(curmatch and blink), self.bank)]

        # PH4-6: write slot.
        if c & S.C_WE:
            self.ram[self.row * S.ROW_STRIDE + self.col] = self.latch

        # ---- CHAR_END: everything below updates on the same edge.
        ready = (not self.slow) or self.frameseen
        saddr = (self.state
                 | (S.S_DA if self.da_sync else 0)
                 | (S.S_CLR if self.clr_sync else 0)
                 | (S.S_COL39 if (self.col & 0b100111) == 0b100111 else 0)
                 | (S.S_ROW_EQ_TOP if self.row == self.top else 0)
                 | (S.S_READY if ready else 0)
                 | (self.latch << S.S_CHAR_SHIFT))
        t = self.treg

        new_seqreg = self.seq_lo[saddr] | (self.seq_hi[saddr] << 8)
        new_treg = self.timing[(self.v << S.T_H_BITS) | self.h]

        if t & S.T_H_END:
            self.h = 0
            self.v = 0 if t & S.T_V_END else (self.v + 1) & 0x1FF
        else:
            self.h = (self.h + 1) & 0x7F

        old_top = self.top
        if c & S.C_COL_CLR:
            self.col = 0
        elif c & S.C_COL_INC:
            self.col = (self.col + 1) & 0x3F
        if c & S.C_ROW_CLR:
            self.row = 0
        elif c & S.C_ROW_INC:
            self.row = _mod24_inc(self.row)
        if c & S.C_TOP_CLR:
            self.top = 0
        elif c & S.C_TOP_INC:
            self.top = _mod24_inc(self.top)

        if t & S.T_FRAME_START:
            self.vrow = old_top
        elif t & S.T_ROW_CLK:
            self.vrow = _mod24_inc(self.vrow)

        if t & S.T_V_END:
            self.framecnt = (self.framecnt + 1) & 0xFF
        if t & S.T_FRAME_START:
            self.frameseen = True
        elif c & S.C_FRAMESEEN_CLR:
            self.frameseen = False

        self.da_sync, self.clr_sync = self.da, self.clr
        self.seqreg = new_seqreg
        self.treg = new_treg
        self.shifter = next_shifter
        self.periods += 1

    # ---------------------------------------------------------------- inspection
    def screen_lines(self):
        """The 24 text lines as the viewer sees them (top line first)."""
        lines = []
        for i in range(S.ROWS):
            phys = (self.top + i) % S.ROWS
            base = phys * S.ROW_STRIDE
            lines.append("".join(chr(b) if b >= 0x20 else " "
                                 for b in self.ram[base:base + S.COLS]))
        return lines

    def cursor(self):
        """(line, col) of the cursor in viewer coordinates."""
        return ((self.row - self.top) % S.ROWS, self.col)


# ====================================================================== PIA / CPU driver

class Driver:
    """Models the 6820 port-B handshake and a CPU sending characters.

    The CPU writes a char (DA asserts) once DA is low and `cpu_gap` periods
    have passed.  The rising edge of RDA fires the 74123 one-shot (B3), whose
    edge on CB1 releases CB2, so DA drops one period later.
    """

    def __init__(self, term, cpu_gap=10):
        self.t = term
        self.cpu_gap = cpu_gap
        self.pending = []
        self.gap = 0
        self.prev_rda = False
        self.release_in = None
        self.sent_at = None
        self.latencies = []          # (char, periods from DA assert to RDA rise)

    def send(self, data):
        if isinstance(data, str):
            data = data.replace("\n", "\r").encode("latin-1")
        self.pending.extend(b & 0x7F for b in data)

    @property
    def busy(self):
        return bool(self.pending) or self.t.da

    def tick(self):
        t = self.t
        if self.release_in is not None:
            self.release_in -= 1
            if self.release_in == 0:
                t.da = False
                self.release_in = None
                self.gap = self.cpu_gap
        elif not t.da and self.pending:
            if self.gap > 0:
                self.gap -= 1
            else:
                t.rd = self.pending.pop(0)
                t.da = True
                self.sent_at = t.periods
        t.step()
        if t.rda and not self.prev_rda and t.da:
            self.latencies.append((t.rd, t.periods - self.sent_at))
            self.release_in = 1
        self.prev_rda = t.rda

    def run_until_idle(self, limit=10_000_000):
        n = 0
        while self.busy:
            self.tick()
            n += 1
            if n > limit:
                raise TimeoutError("terminal did not accept all characters")
        # let the sequencer return to IDLE
        for _ in range(8):
            self.tick()

    def press_clr(self, periods=None):
        """Hold CLR for `periods` (default about 20 ms), then release."""
        periods = periods or int(0.020 * S.CHAR_HZ)
        self.t.clr = True
        for _ in range(periods):
            self.tick()
        self.t.clr = False
        for _ in range(8):
            self.tick()


# ====================================================================== reference model

class ReferenceTerminal:
    """Behavioural Apple-1 terminal used to check the hardware simulation."""

    def __init__(self):
        self.lines = [[" "] * S.COLS for _ in range(S.ROWS)]
        self.r = self.c = 0

    def _newline(self):
        self.c = 0
        if self.r == S.ROWS - 1:
            self.lines.pop(0)
            self.lines.append([" "] * S.COLS)
        else:
            self.r += 1
            self.lines[self.r] = [" "] * S.COLS

    def put(self, b):
        b &= 0x7F
        if b == 0x0D:
            self._newline()
        elif b >= 0x20:
            self.lines[self.r][self.c] = chr(b)
            self.c += 1
            if self.c == S.COLS:
                self._newline()

    def feed(self, data):
        if isinstance(data, str):
            data = data.replace("\n", "\r").encode("latin-1")
        for b in data:
            self.put(b)

    def screen_lines(self):
        return ["".join(l) for l in self.lines]

    def cursor(self):
        return (self.r, self.c)


# ====================================================================== timing measurement

def measure_timing(term, frames=2):
    """Run free for `frames` frames and measure the generated video timing."""
    rec = []
    for _ in range(frames * S.H_TOTAL * S.V_TOTAL + S.H_TOTAL):
        rec.append((term.h, term.v, term.treg))
        term.step()
    line_starts = [i for i, (h, v, t) in enumerate(rec) if h == 0]
    line_len = {line_starts[i + 1] - line_starts[i] for i in range(len(line_starts) - 1)}
    frame_starts = [i for i, (h, v, t) in enumerate(rec) if h == 0 and v == 0]
    frame_len = {frame_starts[i + 1] - frame_starts[i] for i in range(len(frame_starts) - 1)}
    # analyse the last complete frame
    f0 = frame_starts[-2]
    frame = rec[f0:frame_starts[-1]]
    lines = [frame[i:i + S.H_TOTAL] for i in range(0, len(frame), S.H_TOTAL)]
    hsync = [h for h, v, t in lines[10] if not t & S.T_NCSYNC]
    vsync_lines = [i for i, l in enumerate(lines)
                   if sum(1 for _, _, t in l if not t & S.T_NCSYNC) > S.H_TOTAL // 2]
    vis_h = [h for h, v, t in lines[10] if t & S.T_NBLANK]
    vis_v = [i for i, l in enumerate(lines) if any(t & S.T_NBLANK for _, _, t in l)]
    return {
        "line_periods": line_len,
        "frame_periods": frame_len,
        "lines_per_frame": len(lines),
        "hsync_h": hsync,
        "vsync_lines": vsync_lines,
        "visible_h": vis_h,
        "visible_v": (vis_v[0], vis_v[-1]) if vis_v else None,
        "line_us": S.H_TOTAL / S.CHAR_HZ * 1e6,
        "frame_hz": S.CHAR_HZ / (S.H_TOTAL * S.V_TOTAL),
    }


# ====================================================================== frame render

def render_frame(term, driver=None):
    """Run one full frame (aligned to V=0, H=0) and return 262 x 455 levels."""
    tick = driver.tick if driver else term.step
    while not (term.h == 0 and term.v == 0):
        tick()
    img = []
    line = []
    for _ in range(S.H_TOTAL * S.V_TOTAL):
        line.extend(term.dots())
        tick()
        if term.h == 0:
            img.append(line)
            line = []
    return img


def tv_view(img):
    """Rotate a raw frame so it starts after VSYNC/HSYNC, as a monitor shows it."""
    x0 = S.H_SYNC[-1] + 1
    y0 = S.V_SYNC[-1] + 1
    rows = img[y0:] + img[:y0]
    return [r[x0 * S.DOTS_PER_CHAR:] + r[:x0 * S.DOTS_PER_CHAR] for r in rows]


def write_png(path, img, yscale=2):
    """Write composite levels as an 8-bit greyscale PNG (sync shown as black)."""
    h, w = len(img), len(img[0])
    raw = bytearray()
    for row in img:
        px = bytes(min(255, int(max(0.0, lv - LEVEL_BLACK) / (LEVEL_WHITE - LEVEL_BLACK) * 255))
                   for lv in row)
        for _ in range(yscale):
            raw.append(0)
            raw.extend(px)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h * yscale, 8, 0, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(chunk(b"IEND", b""))
