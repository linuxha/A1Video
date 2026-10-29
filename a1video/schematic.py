"""Draw the block-level schematic of the terminal redesign (PNG + SVG).

    python3 -m a1video.schematic [--out docs/a1video-schematic]

Connections are by net name: every pin stub labelled with the same net is
connected.  Thick stubs are buses.  Pin numbers are left to the PCB phase.
"""

import argparse
import datetime

import cairo

W, H = 5010, 2190
PITCH = 24
STUB = 26
BOX_W = 210
COL_W = 610
HEAD = 58

INK = (0.10, 0.10, 0.12)
NET = (0.05, 0.25, 0.65)
PWR = (0.65, 0.10, 0.10)
NC = (0.55, 0.55, 0.55)
ZONE = (0.35, 0.45, 0.35)
BOXFILL = (1.0, 0.99, 0.93)
FONT = "DejaVu Sans Mono"


def bus(name, net):
    return (name, net, True)


# --------------------------------------------------------------------- parts
# (ref, part, description, left pins, right pins)
# pin = (pin name, net) or bus(pin name, net)

CLOCK = [
    ("X1", "OSC 14.31818 MHz", "5 V canned oscillator", [], [("OUT", "OSC14M")]),
    ("U2", "74AC74", "÷2 dot clock / DA sync 1",
     [("1D", "/DOTCLK"), ("1CK", "OSC14M"), ("2D", "DA_BUF"), ("2CK", "DOTCLK")],
     [("1Q", "DOTCLK"), ("1/Q", "/DOTCLK"), ("2Q", "DA_S1"), ("/PR,/CLR", "+5V")]),
    ("U3", "74HC163", "dot phase ÷7 (0-6)",
     [("CLK", "DOTCLK"), ("/CLR", "/Y6"), ("ENP,ENT", "+5V"), ("/LOAD", "+5V"), bus("D0-D3", "GND")],
     [("Q0", "P0"), ("Q1", "P1"), ("Q2", "P2"), ("Q3", "nc")]),
    ("U11", "74HC138", "phase decode",
     [("A", "P0"), ("B", "P1"), ("C", "P2"), ("G1", "+5V"), ("/G2A,/G2B", "GND")],
     [bus("/Y0-/Y6", "/Y0-/Y6"), ("/Y7", "nc")]),
    ("U12", "74HC574", "glitch-free phase strobes",
     [bus("D0-D6", "/Y0-/Y6"), ("CLK", "DOTCLK"), ("/OE", "GND")],
     [("Q0", "/PH1"), ("Q1", "/PH2"), ("Q2", "/PH3"), ("Q3", "/PH4"),
      ("Q4", "/PH5"), ("Q5", "/PH6"), ("Q6", "/PH0")]),
]

PIA = [
    ("J1", "CONN", "to PIA, sheet 2/3",
     [], [bus("RD1-RD7", "RD1-RD7"), ("DA", "DA"), ("RDA", "RDA"), ("+5V", "+5V"), ("GND", "GND")]),
    ("SW1", "CLR switch", "10k pull-up, 1µF RC",
     [], [("debounce + power-on", "/CLR_SW")]),
    ("U39", "74HCT14", "TTL-level Schmitt inputs",
     [("1A", "DA"), ("2A", "/DA_BUF"), ("3A", "/CLR_SW")],
     [("1Y", "/DA_BUF"), ("2Y", "DA_BUF"), ("3Y", "CLR_BUF")]),
    ("U48", "74HC175", "DA / CLR synchronisers",
     [("D1", "DA_S1"), ("D2", "CLR_BUF"), ("D3", "CLR_S1"), ("CLK", "DOTCLK"), ("/MR", "+5V")],
     [("Q1", "DA_S2"), ("Q2", "CLR_S1"), ("Q3", "CLR_S2")]),
    ("U26", "74HCT273", "input char latch",
     [bus("D0-D6", "RD1-RD7"), ("D7", "GND"), ("CLK", "LATCH_LD"), ("/MR", "/LATCH_CLR")],
     [bus("Q0-Q6", "LD0-LD6")]),
]

TIMING = [
    ("U4-U5", "2×74HC163", "H counter 0-64",
     [("CLK", "DOTCLK"), ("ENP,ENT", "CHAR_END"), ("/CLR", "/HCLR"), ("/LOAD", "+5V")],
     [bus("Q0-Q6", "H0-H6")]),
    ("U6-U8", "3×74HC163", "V counter 0-261",
     [("CLK", "DOTCLK"), ("ENP", "H_END"), ("ENT", "CHAR_END"), ("/CLR", "/VCLR"), ("/LOAD", "+5V")],
     [bus("Q0-Q8", "V0-V8")]),
    ("U35", "74HC393", "frame counter / blink",
     [("1CP", "V_END"), ("2CP", "FC3"), ("1MR,2MR", "GND")],
     [("1Q3", "FC3"), ("2Q0", "BLINK")]),
]

TIMING2 = [
    ("U9", "SST39SF010A", "TIMING ROM  timing.bin",
     [bus("A0-A6", "H0-H6"), bus("A7-A15", "V0-V8"), ("A16", "GND"), ("/CE,/OE", "GND"), ("/WE", "+5V")],
     [bus("DQ0-DQ5", "TD0-TD5"), ("DQ6-DQ7", "nc")]),
    ("U10", "74HC377", "timing register",
     [bus("D0-D5", "TD0-TD5"), ("/E", "/PH6"), ("CLK", "DOTCLK")],
     [("Q0", "NCSYNC"), ("Q1", "NBLANK"), ("Q2", "H_END"), ("Q3", "V_END"),
      ("Q4", "ROW_CLK"), ("Q5", "FRAME_START")]),
]

RAM = [
    ("U21-U23", "3×74HC157", "RAM address mux",
     [bus("A[10:0]", "VR4-0,H5-0"), bus("B[10:0]", "R4-0,C5-0"), ("S", "P2"), ("/G", "GND")],
     [bus("Y[10:0]", "MA0-MA10")]),
    ("U24", "AS6C62256-55", "display RAM (2K used)",
     [bus("A0-A10", "MA0-MA10"), bus("A11-A14", "GND"), ("/CE", "GND"), ("/OE", "P2"), ("/WE", "/WE_RAM")],
     [bus("DQ0-DQ7", "MD0-MD7")]),
    ("U27", "74HC541", "RAM write driver",
     [bus("A1-A7", "LD0-LD6"), ("A8", "GND"), ("/OE1", "/WBUF"), ("/OE2", "GND")],
     [bus("Y1-Y8", "MD0-MD7")]),
]

VIDEO = [
    ("U25", "74HC377", "video char latch",
     [bus("D0-D6", "MD0-MD6"), ("D7", "CURMATCH"), ("/E", "/PH3"), ("CLK", "DOTCLK")],
     [bus("Q0-Q6", "VC0-VC6"), ("Q7", "CURM_L")]),
    ("U28", "SST39SF010A", "CHAR ROM  chargen.bin",
     [bus("A0-A2", "V0-V2"), bus("A3-A9", "VC0-VC6"), ("A10", "CURSOR"), ("A11", "BANK"),
      bus("A12-A16", "GND"), ("/CE,/OE", "GND"), ("/WE", "+5V")],
     [bus("DQ0-DQ7", "G0-G7")]),
    ("U29", "74HC166", "dot shifter (DQ7 first)",
     [bus("A-H", "G0-G7"), ("SH,/LD", "/PH6"), ("CLK", "DOTCLK"), ("CLK INH", "GND"),
      ("SER", "GND"), ("/CLR", "+5V")],
     [("QH", "DOTS")]),
]

OUTPUT = [
    ("U37", "74AC08", "video gating / drive",
     [("1A,1B", "DOTS,NBLANK"), ("2A,2B", "NCSYNC,+5V"), ("3A,3B", "CURM_L,BLINK"),
      ("4A,4B", "FRAME_START,CHAR_END")],
     [("1Y", "VID"), ("2Y", "CSYNC_OUT"), ("3Y", "CURSOR"), ("4Y", "J_FS")]),
    ("JP2", "BANK", "char ROM bank", [], [("1=lower case", "BANK")]),
    ("J3", "CONN", "to sheet 2/3 (⚠ verify)",
     [("CLA", "P2"), ("H4,H5,H6", "H4,H5,H6"), bus("V0-V3", "V0-V3"), ("CL", "P0 ⚠")], []),
]

SEQ1 = [
    ("U33", "SST39SF010A", "SEQ ROM lo  seq_lo.bin",
     [bus("A0-A4", "S0-S4"), ("A5", "DA_S2"), ("A6", "CLR_S2"), ("A7", "COL39"), ("A8", "ROWEQTOP"),
      ("A9", "READY"), bus("A10-A16", "LD0-LD6"), ("/CE,/OE", "GND")],
     [bus("DQ0-DQ7", "SL0-SL7")]),
    ("U34", "SST39SF010A", "SEQ ROM hi  seq_hi.bin",
     [bus("A0-A16", "same as U33"), ("/CE,/OE", "GND")],
     [bus("DQ0-DQ7", "SH0-SH7")]),
]

SEQ2 = [
    ("U36", "74HC377", "state / control reg lo",
     [bus("D0-D7", "SL0-SL7"), ("/E", "/PH6"), ("CLK", "DOTCLK")],
     [bus("Q0-Q4", "S0-S4"), ("Q5", "WE"), ("Q6", "COL_INC"), ("Q7", "COL_CLR")]),
    ("U38", "74HC377", "control reg hi",
     [bus("D0-D7", "SH0-SH7"), ("/E", "/PH6"), ("CLK", "DOTCLK")],
     [("Q0", "ROW_INC"), ("Q1", "ROW_CLR"), ("Q2", "TOP_INC"), ("Q3", "TOP_CLR"),
      ("Q4", "LATCH_LD"), ("Q5", "LATCH_CLR"), ("Q6", "RDA"), ("Q7", "FS_CLR")]),
    ("U47", "74HC109", "FRAMESEEN flag",
     [("J", "J_FS"), ("/K", "/K_FS"), ("CLK", "DOTCLK"), ("/S,/R", "+5V")],
     [("Q", "FRAMESEEN"), ("/Q", "/FS")]),
    ("JP1", "SLOW", "authentic speed", [], [("1=slow", "SLOW")]),
]

COUNT1 = [
    ("U17-U18", "2×74HC163", "COL cursor 0-39",
     [("CLK", "DOTCLK"), ("ENP", "COL_INC"), ("ENT", "CHAR_END"), ("/CLR", "/COLCLR"), ("/LOAD", "+5V")],
     [bus("Q0-Q5", "C0-C5")]),
    ("U19-U20", "2×74HC163", "ROW cursor mod 24",
     [("CLK", "DOTCLK"), ("ENP", "ROW_INC"), ("ENT", "CHAR_END"), ("/CLR", "/ROWCLR"),
      ("/LOAD", "/ROWLD"), bus("D0-D4", "GND")],
     [bus("Q0-Q4", "R0-R4")]),
    ("U40", "74HC21", "==39 / ==23 detect",
     [bus("1A-1D", "C0,C1,C2,C5"), bus("2A-2D", "R0,R1,R2,R4")],
     [("1Y", "COL39"), ("2Y", "ROW23")]),
]

COUNT2 = [
    ("U15-U16", "2×74HC163", "TOP row mod 24",
     [("CLK", "DOTCLK"), ("ENP", "TOP_INC"), ("ENT", "CHAR_END"), ("/CLR", "/TOPCLR"),
      ("/LOAD", "/TOPLD"), bus("D0-D4", "GND")],
     [bus("Q0-Q4", "T0-T4")]),
    ("U13-U14", "2×74HC163", "VROW video row",
     [("CLK", "DOTCLK"), ("ENP", "ROW_CLK"), ("ENT", "CHAR_END"), ("/CLR", "/VRCLR"),
      ("/LOAD", "/VRLD"), bus("D0-D4", "T0-T4")],
     [bus("Q0-Q4", "VR0-VR4")]),
    ("U41", "74HC21", "==23 detect",
     [bus("1A-1D", "T0,T1,T2,T4"), bus("2A-2D", "VR0,VR1,VR2,VR4")],
     [("1Y", "TOP23"), ("2Y", "VR23")]),
]

COMPARE = [
    ("U30", "74HC688", "cursor compare lo",
     [bus("P0-P5", "H0-H5"), bus("Q0-Q5", "C0-C5"), bus("P6-P7", "VR0-VR1"), bus("Q6-Q7", "R0-R1"),
      ("/G", "GND")],
     [("/P=Q", "/EQ1")]),
    ("U31", "74HC688", "cursor compare hi",
     [bus("P0-P2", "VR2-VR4"), bus("Q0-Q2", "R2-R4"), bus("P3-7,Q3-7", "GND"), ("/G", "/EQ1")],
     [("/P=Q", "/CURMATCH")]),
    ("U32", "74HC688", "ROW == TOP",
     [bus("P0-P4", "R0-R4"), bus("Q0-Q4", "T0-T4"), bus("P5-7,Q5-7", "GND"), ("/G", "GND")],
     [("/P=Q", "/ROWEQTOP")]),
]

GLUE1 = [
    ("U44", "74HC00", "write strobes / READY",
     [("1A,1B", "PH5,WE"), ("2A,2B", "P2,WE"), ("3A,3B", "SLOW,/FS"), ("4A,4B", "FS_CLR,CHAR_END")],
     [("1Y", "/WE_RAM"), ("2Y", "/WBUF"), ("3Y", "READY"), ("4Y", "/K_FS")]),
    ("U45", "74HC04", "inverters",
     [("1A", "/PH6"), ("2A", "/PH5"), ("3A", "LATCH_CLR"), ("4A", "/CURMATCH"), ("5A", "/ROWEQTOP")],
     [("1Y", "CHAR_END"), ("2Y", "PH5"), ("3Y", "/LATCH_CLR"), ("4Y", "CURMATCH"), ("5Y", "ROWEQTOP")]),
]

GLUE2 = [
    ("U49", "74HC10", "sync clear / load",
     [("1A-1C", "H_END,CHAR_END,+5V"), ("2A-2C", "V_END,H_END,CHAR_END"), ("3A-3C", "COL_CLR,CHAR_END,+5V")],
     [("1Y", "/HCLR"), ("2Y", "/VCLR"), ("3Y", "/COLCLR")]),
    ("U50", "74HC10", "sync clear / load",
     [("1A-1C", "ROW_CLR,CHAR_END,+5V"), ("2A-2C", "ROW_INC,ROW23,CHAR_END"),
      ("3A-3C", "TOP_CLR,CHAR_END,+5V")],
     [("1Y", "/ROWCLR"), ("2Y", "/ROWLD"), ("3Y", "/TOPCLR")]),
    ("U51", "74HC10", "sync clear / load",
     [("1A-1C", "TOP_INC,TOP23,CHAR_END"), ("2A-2C", "ROW_CLK,VR23,CHAR_END"),
      ("3A-3C", "FRAME_START,CHAR_END,+5V")],
     [("1Y", "/TOPLD"), ("2Y", "/VRCLR"), ("3Y", "/VRLD")]),
]

NOTES = [
    "NOTES",
    "1. Block-level schematic. Pins with the same net label are connected;",
    "   thick stubs are buses. Pin numbers per datasheet (PCB phase).",
    "2. All ICs +5 V / GND with 100 nF each; 10 µF bulk. Single +5 V supply.",
    "3. Fully synchronous: every counter / register is clocked by DOTCLK and",
    "   enabled by CHAR_END (phase 6) or a phase strobe. No gated clocks.",
    "   Counters are cascaded TC -> ENT. /CLR and /LOAD of 74HC163 are",
    "   synchronous; mod-24 wrap uses /LOAD with D=0.",
    "4. P2 (U3 Q2) = 0 in phases 0-3: video read (RAM /OE low, mux = video).",
    "   P2 = 1 in phases 4-6: write slot (mux = cursor, /WE in phase 5).",
    "5. ROM images from  python3 -m a1video.gen_roms :",
    "   U9 timing.bin  U28 chargen.bin  U33 seq_lo.bin  U34 seq_hi.bin",
    "6. RDA polarity is set in seq_hi.bin (D6). DA polarity at J1 ⚠ verify.",
    "7. J3 (CPU clock, DRAM refresh) mapping ⚠ verify against Apple 00101",
    "   sheet 2/3 B7/B8 wiring and the original CL / H6 / H10 signals.",
    "8. ⚠ Check MD bus turnaround at the phase 3 -> 4 boundary.",
    "9. U47: if J_FS and /K_FS coincide the flag toggles; worst case is one",
    "   extra frame of delay in SLOW mode only.",
]

# --------------------------------------------------------------------- drawing


class Sheet:
    def __init__(self, surface):
        self.c = cairo.Context(surface)
        self.c.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        self.boxes = {}

    def text(self, x, y, s, size=15, color=INK, align="l", bold=False):
        c = self.c
        c.select_font_face(FONT, cairo.FONT_SLANT_NORMAL,
                           cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size)
        ext = c.text_extents(s)
        if align == "r":
            x -= ext.x_advance
        elif align == "c":
            x -= ext.x_advance / 2
        c.set_source_rgb(*color)
        c.move_to(x, y)
        c.show_text(s)

    def line(self, x0, y0, x1, y1, width=1.6, color=INK, dash=None):
        c = self.c
        c.set_source_rgb(*color)
        c.set_line_width(width)
        c.set_dash(dash or [])
        c.move_to(x0, y0)
        c.line_to(x1, y1)
        c.stroke()
        c.set_dash([])

    def net_color(self, net):
        if net in ("+5V", "GND"):
            return PWR
        if net == "nc":
            return NC
        return NET

    def pin(self, x, y, name, net, is_bus, side):
        sgn = -1 if side == "l" else 1
        x_end = x + sgn * STUB
        self.line(x, y, x_end, y, width=4.5 if is_bus else 1.6)
        if is_bus:
            mx = x + sgn * STUB / 2
            self.line(mx - 5, y + 6, mx + 5, y - 6, width=1.4)
        if net == "nc":
            self.line(x_end - 5, y - 5, x_end + 5, y + 5, color=NC)
            self.line(x_end - 5, y + 5, x_end + 5, y - 5, color=NC)
        self.text(x_end + sgn * 6, y + 5, net, size=15, color=self.net_color(net),
                  align="r" if side == "l" else "l")
        self.text(x - sgn * 7, y + 5, name, size=13, align="l" if side == "l" else "r")

    def chip(self, x, y, ref, part, desc, left, right):
        rows = max(len(left), len(right), 1)
        h = HEAD + rows * PITCH + 8
        c = self.c
        c.rectangle(x, y, BOX_W, h)
        c.set_source_rgb(*BOXFILL)
        c.fill_preserve()
        c.set_source_rgb(*INK)
        c.set_line_width(2.2)
        c.stroke()
        self.text(x + BOX_W / 2, y + 19, ref, size=17, align="c", bold=True)
        self.text(x + BOX_W / 2, y + 37, part, size=14, align="c")
        self.text(x + BOX_W / 2, y + 53, desc, size=11.5, color=(0.35, 0.35, 0.35), align="c")
        self.line(x, y + HEAD - 2, x + BOX_W, y + HEAD - 2, width=0.8)
        for side, pins, px in (("l", left, x), ("r", right, x + BOX_W)):
            for i, p in enumerate(pins):
                name, net = p[0], p[1]
                is_bus = len(p) > 2 and p[2]
                self.pin(px, y + HEAD + 4 + i * PITCH + PITCH / 2, name, net, is_bus, side)
        self.boxes[ref] = (x, y, BOX_W, h)
        return h

    def stack(self, col, y, parts, gap=46):
        x = 30 + col * COL_W + 222
        top = y
        for p in parts:
            y += self.chip(x, y, *p) + gap
        return (col, top, y - gap)

    def zone(self, cols, top, bottom, title):
        x0 = 30 + cols[0] * COL_W + 8
        x1 = 30 + (cols[1] + 1) * COL_W - 8
        y0, y1 = top - 52, bottom + 22
        c = self.c
        c.rectangle(x0, y0, x1 - x0, y1 - y0)
        c.set_source_rgb(*ZONE)
        c.set_line_width(2)
        c.set_dash([14, 8])
        c.stroke()
        c.set_dash([])
        self.text(x0 + 14, y0 + 30, title, size=21, color=ZONE, bold=True)

    def resistor(self, x, y, horizontal, label):
        """Zig-zag resistor 60 px long starting at (x, y)."""
        pts = []
        for i in range(7):
            off = 0 if i in (0, 6) else (9 if i % 2 else -9)
            t = i * 10
            pts.append((x + t, y + off) if horizontal else (x + off, y + t))
        c = self.c
        c.set_source_rgb(*INK)
        c.set_line_width(2)
        c.move_to(*pts[0])
        for p in pts[1:]:
            c.line_to(*p)
        c.stroke()
        if horizontal:
            self.text(x + 30, y - 16, label, size=15, align="c")
        else:
            self.text(x + 18, y + 36, label, size=15)


def dac(sh, x, y):
    """Composite DAC: CSYNC_OUT-620, VID-270, 120 to GND, out to RCA."""
    node_x = x + 230
    for i, (net, r) in enumerate((("CSYNC_OUT", "R1 620Ω"), ("VID", "R2 270Ω"))):
        yy = y + i * 70
        sh.text(x, yy + 5, net, color=NET)
        sh.line(x + 110, yy, x + 130, yy)
        sh.resistor(x + 130, yy, True, r)
        sh.line(x + 190, yy, node_x, yy)
    sh.line(node_x, y, node_x, y + 70)
    sh.c.arc(node_x, y + 70, 5, 0, 6.3)
    sh.c.fill()
    sh.line(node_x, y + 70, node_x, y + 100)
    sh.resistor(node_x, y + 100, False, "R3 120Ω")
    sh.line(node_x, y + 160, node_x, y + 180)
    sh.line(node_x - 16, y + 180, node_x + 16, y + 180, width=2.4)
    sh.line(node_x - 10, y + 187, node_x + 10, y + 187, width=2)
    sh.line(node_x - 4, y + 194, node_x + 4, y + 194, width=2)
    sh.line(node_x, y + 70, node_x + 110, y + 70)
    sh.c.arc(node_x + 122, y + 70, 12, 0, 6.3)
    sh.c.set_line_width(2.2)
    sh.c.stroke()
    sh.c.arc(node_x + 122, y + 70, 4, 0, 6.3)
    sh.c.fill()
    sh.text(node_x + 142, y + 66, "J2 RCA", size=16, bold=True)
    sh.text(node_x + 142, y + 86, "COMPOSITE", size=14)
    sh.text(node_x + 142, y + 104, "1 Vpp / 75 Ω", size=14)
    sh.text(x, y + 230, "sync 0 V · black 0.30 V · white 0.99 V", size=13)
    sh.text(x, y + 250, "source impedance 73 Ω (into 75 Ω load)", size=13)
    return y + 260


def title_block(sh, x, y, w, h):
    c = sh.c
    c.rectangle(x, y, w, h)
    c.set_source_rgb(*INK)
    c.set_line_width(3)
    c.stroke()
    rows = [(0, 70), (70, 120), (120, 170), (170, h)]
    for r0, _ in rows[1:]:
        sh.line(x, y + r0, x + w, y + r0, width=1.5)
    sh.line(x + w / 2, y + 120, x + w / 2, y + h, width=1.5)
    sh.text(x + 20, y + 45, "APPLE-1 TERMINAL SECTION — MODERN DISCRETE REDESIGN", size=24, bold=True)
    sh.text(x + 20, y + 103, "Block-level schematic · NTSC composite · single +5 V · 74HC/HCT/AC + SRAM + flash",
            size=16)
    sh.text(x + 20, y + 153, "Ref: Apple 00101 sheets 1/3, 2/3 · docs/apple1-video-redesign.md", size=14)
    sh.text(x + w / 2 + 20, y + 153, f"Generated {datetime.date.today().isoformat()} · a1video/schematic.py",
            size=14)
    sh.text(x + 20, y + 205, "REV 0 (draft)", size=17, bold=True)
    sh.text(x + w / 2 + 20, y + 205, "SHEET 1 / 1", size=17, bold=True)


def draw(surface):
    sh = Sheet(surface)
    c = sh.c
    c.set_source_rgb(1, 1, 1)
    c.paint()

    # ---- row 1
    y1 = 120
    zones = []
    zones.append((sh.stack(0, y1, CLOCK), "A  CLOCK & DOT PHASE"))
    zones.append((sh.stack(1, y1, PIA), "B  PIA INTERFACE & INPUT"))
    tb = sh.stack(2, y1, TIMING)
    tb2 = sh.stack(3, y1, TIMING2)
    zones.append(((2, 3, tb[1], max(tb[2], tb2[2])), "C  VIDEO TIMING"))
    ram = sh.stack(4, y1, RAM)
    vid = sh.stack(5, y1, VIDEO)
    zones.append(((4, 5, y1, max(ram[2], vid[2])), "D  DISPLAY RAM & CHARACTER PATH"))
    out = sh.stack(6, y1, OUTPUT)
    dac_end = dac(sh, 30 + 6 * COL_W + 60, out[2] + 70)
    zones.append(((6, 6, y1, dac_end), "E  VIDEO OUT & SHEET 2"))
    row1_bottom = max(z[0][-1] for z in zones) + 110

    # ---- row 2
    y2 = row1_bottom
    s1 = sh.stack(0, y2, SEQ1)
    s2 = sh.stack(1, y2, SEQ2)
    zones.append(((0, 1, y2, max(s1[2], s2[2])), "F  CONTROL SEQUENCER (ROM STATE MACHINE)"))
    k1 = sh.stack(2, y2, COUNT1)
    k2 = sh.stack(3, y2, COUNT2)
    k3 = sh.stack(4, y2, COMPARE)
    zones.append(((2, 4, y2, max(k1[2], k2[2], k3[2])), "G  CURSOR / SCROLL COUNTERS & COMPARE"))
    g1 = sh.stack(5, y2, GLUE1)
    g2 = sh.stack(6, y2, GLUE2)
    zones.append(((5, 6, y2, max(g1[2], g2[2])), "H  GLUE LOGIC"))

    for z, title in zones:
        if len(z) == 3:
            col, top, bottom = z
            sh.zone((col, col), top, bottom, title)
        else:
            sh.zone((z[0], z[1]), z[2], z[3], title)

    # ---- notes and title block (column 7)
    nx = 30 + 7 * COL_W + 10
    for i, line in enumerate(NOTES):
        sh.text(nx, y1 + i * 26, line, size=15 if i else 19, bold=(i == 0))
    tx = 30 + 5 * COL_W + 8
    title_block(sh, tx, max(g1[2], g2[2]) + 90, W - tx - 30, 230)
    sh.text(W / 2, 60, "APPLE-1 TERMINAL SECTION — MODERN DISCRETE REDESIGN — BLOCK SCHEMATIC",
            size=30, align="c", bold=True)
    return sh


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="docs/a1video-schematic", help="output path without extension")
    args = ap.parse_args()
    img = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    draw(img)
    img.write_to_png(args.out + ".png")
    svg = cairo.SVGSurface(args.out + ".svg", W, H)
    draw(svg)
    svg.finish()
    print("wrote", args.out + ".png", "and", args.out + ".svg")


if __name__ == "__main__":
    main()
