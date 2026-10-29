"""Gate-level, wired schematics of the terminal redesign (4 sheets, PNG + SVG).

    python3 -m a1video.gateschem [--out docs/schematic]

Unlike schematic.py (block level, connections by label only), these sheets
draw gate symbols, IC pin numbers and the wiring as lines.  Clock and
inter-sheet signals use labelled off-sheet connectors; buses are thick lines
with labelled bus entries.  Pin numbers are for the DIP packages and must be
checked against the datasheets before layout.
"""

import argparse
import datetime
import math

import cairo

W, H = 4200, 2970
FONT = "DejaVu Sans"
MONO = "DejaVu Sans Mono"
INK = (0.08, 0.08, 0.10)
WIRE = (0.05, 0.30, 0.10)
BUSC = (0.10, 0.20, 0.55)
LBL = (0.05, 0.20, 0.60)
PWR = (0.70, 0.10, 0.10)
GREY = (0.45, 0.45, 0.45)
FILL = (1.0, 0.99, 0.92)

PITCH = 30
STUB = 40
SHEETS = 4


class Part:
    def __init__(self):
        self.p = {}

    def __getitem__(self, k):
        return self.p[k]


class Sch:
    def __init__(self, surface, number, title):
        self.c = cairo.Context(surface)
        self.number = number
        self.title = title
        c = self.c
        c.set_source_rgb(1, 1, 1)
        c.paint()
        c.set_line_cap(cairo.LINE_CAP_ROUND)
        c.set_line_join(cairo.LINE_JOIN_ROUND)
        self.border()

    # ------------------------------------------------------------- text
    def text(self, x, y, s, size=16, color=INK, align="l", bold=False, mono=False, overbar=None):
        c = self.c
        c.select_font_face(MONO if mono else FONT, cairo.FONT_SLANT_NORMAL,
                           cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
        c.set_font_size(size)
        bar = False
        if overbar is None and s.startswith("/") and len(s) > 1:
            s, bar = s[1:], True
        elif overbar:
            bar = True
        ext = c.text_extents(s)
        if align == "r":
            x -= ext.x_advance
        elif align == "c":
            x -= ext.x_advance / 2
        c.set_source_rgb(*color)
        c.move_to(x, y)
        c.show_text(s)
        if bar:
            c.set_line_width(1.2)
            c.move_to(x + 1, y - size * 0.82)
            c.line_to(x + ext.x_advance - 1, y - size * 0.82)
            c.stroke()
        return ext.x_advance

    # ------------------------------------------------------------- lines
    def wire(self, *pts, color=WIRE, width=2.0):
        c = self.c
        c.set_source_rgb(*color)
        c.set_line_width(width)
        c.move_to(*pts[0])
        for p in pts[1:]:
            c.line_to(*p)
        c.stroke()

    def bus(self, *pts):
        self.wire(*pts, color=BUSC, width=6)

    def dot(self, p):
        c = self.c
        c.set_source_rgb(*WIRE)
        c.arc(p[0], p[1], 5.5, 0, 2 * math.pi)
        c.fill()

    def route(self, a, b, x=None, y=None):
        """Orthogonal wire a -> b, with the vertical leg at x (or horizontal leg at y)."""
        if y is not None:
            self.wire(a, (a[0], y), (b[0], y), b)
        else:
            x = (a[0] + b[0]) / 2 if x is None else x
            self.wire(a, (x, a[1]), (x, b[1]), b)

    def net(self, src, sinks, x):
        """Source and sinks joined through a vertical trunk at x, with tee dots."""
        pts = [src] + list(sinks)
        ys = [p[1] for p in pts]
        lo, hi = min(ys), max(ys)
        self.wire((x, lo), (x, hi))
        for p in pts:
            self.wire(p, (x, p[1]))
            if lo < p[1] < hi or (sum(1 for q in pts if q[1] == p[1]) > 1):
                self.dot((x, p[1]))

    def label(self, p, name, side="r", color=LBL):
        """Net label sitting on the end of a wire."""
        if side == "r":
            self.text(p[0] + 6, p[1] - 6, name, size=15, color=color, bold=True)
        else:
            self.text(p[0] - 6, p[1] - 6, name, size=15, color=color, bold=True, align="r")

    def port(self, p, name, side="r", sheets=""):
        """Off-sheet connector flag attached to the wire end p."""
        c = self.c
        x, y = p
        c.set_font_size(15)
        c.select_font_face(FONT, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        w = c.text_extents(name.lstrip("/")).x_advance + 24
        s = 1 if side == "r" else -1
        pts = [(x, y), (x + s * 10, y - 12), (x + s * (w + 10), y - 12),
               (x + s * (w + 10), y + 12), (x + s * 10, y + 12)]
        c.move_to(*pts[0])
        for q in pts[1:]:
            c.line_to(*q)
        c.close_path()
        c.set_source_rgb(0.92, 0.95, 1.0)
        c.fill_preserve()
        c.set_source_rgb(*LBL)
        c.set_line_width(1.6)
        c.stroke()
        tx = x + s * 18 if side == "r" else x - w + 2
        self.text(tx, y + 6, name, size=15, color=LBL, bold=True)
        if sheets:
            sx = x + s * (w + 16)
            self.text(sx, y + 5, sheets, size=12, color=GREY, align="l" if side == "r" else "r")

    def vcc(self, p, direction="up"):
        x, y = p
        d = -1 if direction == "up" else 1
        self.wire((x, y), (x, y + d * 18), color=PWR)
        self.wire((x - 12, y + d * 18), (x + 12, y + d * 18), color=PWR, width=2.5)
        self.text(x, y + d * 24 + (0 if d < 0 else 14), "+5V", size=13, color=PWR, align="c", bold=True)

    def vcc_side(self, p, side="l"):
        x, y = p
        s = -1 if side == "l" else 1
        self.wire((x, y), (x + s * 16, y), color=PWR)
        self.wire((x + s * 16, y - 10), (x + s * 16, y + 10), color=PWR, width=2.5)
        self.text(x + s * 22, y + 5, "+5V", size=13, color=PWR, align="r" if s < 0 else "l", bold=True)

    def gnd(self, p, direction="down"):
        x, y = p
        d = 1 if direction == "down" else -1
        self.wire((x, y), (x, y + d * 16), color=PWR)
        for i, half in enumerate((13, 8, 3)):
            yy = y + d * (16 + i * 5)
            self.wire((x - half, yy), (x + half, yy), color=PWR, width=2.2)

    def gnd_side(self, p, side="l"):
        x, y = p
        s = -1 if side == "l" else 1
        self.wire((x, y), (x + s * 18, y), color=PWR)
        self.gnd((x + s * 18, y))

    def tie(self, pins, kind, side="l", offset=24):
        """Join several pin ends with a vertical bar and tie it to +5V or GND."""
        s = -1 if side == "l" else 1
        x = pins[0][0] + s * offset
        ys = [p[1] for p in pins]
        for p in pins:
            self.wire(p, (x, p[1]), color=PWR)
        if len(pins) > 1:
            self.wire((x, min(ys)), (x, max(ys)), color=PWR)
            for p in pins[:-1]:
                if min(ys) < p[1] < max(ys):
                    self.dot((x, p[1]))
        if kind == "vcc":
            self.vcc((x, min(ys)), "up")
        else:
            self.gnd((x, max(ys)), "down")

    def nc(self, p):
        x, y = p
        self.wire((x - 7, y - 7), (x + 7, y + 7), color=GREY)
        self.wire((x - 7, y + 7), (x + 7, y - 7), color=GREY)

    # ------------------------------------------------------------- ICs
    def ic(self, x, y, ref, part, left, right, w=230, power=None, note=None):
        """IC box.  left/right: lists of (pin number, pin name) or None for a gap.
        Returns a Part whose .p maps pin name -> wire end point."""
        rows = max(len(left), len(right))
        h = rows * PITCH + 20
        c = self.c
        c.rectangle(x, y, w, h)
        c.set_source_rgb(*FILL)
        c.fill_preserve()
        c.set_source_rgb(*INK)
        c.set_line_width(2.4)
        c.stroke()
        self.text(x + w / 2, y - 30, ref, size=19, align="c", bold=True)
        self.text(x + w / 2, y - 10, part, size=15, align="c")
        part_o = Part()
        for side, pins in (("l", left), ("r", right)):
            for i, pin in enumerate(pins):
                if pin is None:
                    continue
                num, name = pin
                py = y + 25 + i * PITCH
                if side == "l":
                    x0, x1 = x - STUB, x
                    self.text(x + 8, py + 5, name, size=14, mono=True)
                    self.text(x - 6, py - 5, str(num), size=11, color=GREY, align="r")
                    end = (x0, py)
                else:
                    x0, x1 = x + w, x + w + STUB
                    self.text(x + w - 8, py + 5, name, size=14, mono=True, align="r")
                    self.text(x + w + 6, py - 5, str(num), size=11, color=GREY)
                    end = (x1, py)
                self.wire((x0, py), (x1, py), color=INK, width=2)
                part_o.p[name] = end
        if power:
            self.text(x + w / 2, y + h + 18, power, size=11, color=GREY, align="c")
        if note:
            self.text(x + w / 2, y + h + 34, note, size=12, color=GREY, align="c")
        part_o.box = (x, y, w, h)
        return part_o

    # ------------------------------------------------------------- gates
    def gate(self, kind, x, y, ref, pins, n=2):
        """Gate with its output to the right.  (x, y) = centre of the input side.
        pins: input pin numbers then the output pin number.
        Returns Part with p['in'] (list of input ends) and p['out']."""
        c = self.c
        inv_out = kind in ("NAND", "NOR", "NOT", "SNOT")
        g = Part()
        if kind in ("NOT", "SNOT", "BUF"):
            h = 44
            c.move_to(x, y - h / 2)
            c.line_to(x + 46, y)
            c.line_to(x, y + h / 2)
            c.close_path()
            body_end = x + 46
            ins = [y]
        else:
            h = max(56, n * 22 + 14)
            ins = [y + (i - (n - 1) / 2) * 22 for i in range(n)]
            if kind in ("AND", "NAND"):
                c.move_to(x, y - h / 2)
                c.line_to(x + 36, y - h / 2)
                c.arc(x + 36, y, h / 2, -math.pi / 2, math.pi / 2)
                c.line_to(x, y + h / 2)
                c.close_path()
                body_end = x + 36 + h / 2
            else:   # OR / NOR
                c.move_to(x - 6, y - h / 2)
                c.curve_to(x + 30, y - h / 2, x + 60, y - h / 4, x + 76, y)
                c.curve_to(x + 60, y + h / 4, x + 30, y + h / 2, x - 6, y + h / 2)
                c.curve_to(x + 10, y + h / 4, x + 10, y - h / 4, x - 6, y - h / 2)
                body_end = x + 76
        c.set_source_rgb(*FILL)
        c.fill_preserve()
        c.set_source_rgb(*INK)
        c.set_line_width(2.4)
        c.stroke()
        if kind == "SNOT":
            hx, hy = x + 10, y
            self.wire((hx, hy + 6), (hx + 10, hy + 6), (hx + 10, hy - 6), color=INK, width=1.4)
            self.wire((hx + 6, hy + 6), (hx + 6, hy - 6), (hx + 16, hy - 6), color=INK, width=1.4)
        out_x = body_end
        if inv_out:
            c.arc(body_end + 7, y, 7, 0, 2 * math.pi)
            c.set_source_rgb(1, 1, 1)
            c.fill_preserve()
            c.set_source_rgb(*INK)
            c.set_line_width(2.2)
            c.stroke()
            out_x = body_end + 14
        in_ends = []
        for i, iy in enumerate(ins):
            self.wire((x - 30, iy), (x + (4 if kind in ("OR", "NOR") else 0), iy), color=INK, width=2)
            self.text(x - 26, iy - 4, str(pins[i]), size=11, color=GREY)
            in_ends.append((x - 30, iy))
        self.wire((out_x, y), (out_x + 30, y), color=INK, width=2)
        self.text(out_x + 6, y - 5, str(pins[-1]), size=11, color=GREY)
        self.text(x + 20, y - h / 2 - 8, ref, size=15, bold=True, align="c")
        g.p["in"] = in_ends
        g.p["out"] = (out_x + 30, y)
        return g

    # ------------------------------------------------------------- passives
    def resistor(self, a, b, label):
        """Zig-zag resistor between two points on a horizontal or vertical line."""
        (x0, y0), (x1, y1) = a, b
        horiz = y0 == y1
        L = (x1 - x0) if horiz else (y1 - y0)
        body = 60 * (1 if L > 0 else -1)
        m0 = (L - body) / 2
        pts = [a]
        for i in range(7):
            t = m0 + body * i / 6
            off = 0 if i in (0, 6) else (10 if i % 2 else -10)
            pts.append((x0 + t, y0 + off) if horiz else (x0 + off, y0 + t))
        pts.append(b)
        self.wire(*pts, color=INK, width=2)
        if horiz:
            self.text((x0 + x1) / 2, y0 - 16, label, size=14, align="c")
        else:
            self.text(x0 + 18, (y0 + y1) / 2 + 5, label, size=14)

    def capacitor(self, a, b, label):
        (x, y0), (_, y1) = a, b
        m = (y0 + y1) / 2
        self.wire(a, (x, m - 5), color=INK)
        self.wire((x - 16, m - 5), (x + 16, m - 5), color=INK, width=3)
        self.wire((x - 16, m + 5), (x + 16, m + 5), color=INK, width=3)
        self.wire((x, m + 5), b, color=INK)
        self.text(x + 22, m + 5, label, size=14)

    def switch(self, a, b, label):
        """Push button between two points on a vertical line."""
        (x, y0), (_, y1) = a, b
        m = (y0 + y1) / 2
        self.wire(a, (x, m - 12), color=INK)
        self.wire((x, m + 12), b, color=INK)
        self.dot((x, m - 12))
        self.dot((x, m + 12))
        self.wire((x - 14, m - 18), (x - 14, m + 18), color=INK, width=2.5)
        self.wire((x - 14, m), (x - 30, m), color=INK, width=2)
        self.text(x + 14, m + 5, label, size=14)

    def jumper(self, a, b, label):
        (x, y0), (_, y1) = a, b
        m = (y0 + y1) / 2
        self.wire(a, (x, m - 10), color=INK)
        self.wire((x, m + 10), b, color=INK)
        c = self.c
        for yy in (m - 10, m + 10):
            c.arc(x, yy, 5, 0, 2 * math.pi)
            c.set_source_rgb(*INK)
            c.set_line_width(2)
            c.stroke()
        self.text(x + 14, m + 5, label, size=14)

    # ------------------------------------------------------------- frame
    def border(self):
        c = self.c
        c.set_source_rgb(*INK)
        c.set_line_width(4)
        c.rectangle(40, 40, W - 80, H - 80)
        c.stroke()
        c.set_line_width(1.5)
        c.rectangle(70, 70, W - 140, H - 140)
        c.stroke()
        for i in range(8):
            x = 70 + (W - 140) * (i + 0.5) / 8
            self.text(x, 62, str(8 - i), size=18, align="c", bold=True)
            self.text(x, H - 46, str(8 - i), size=18, align="c", bold=True)
        for i, ch in enumerate("DCBA"):
            y = 70 + (H - 140) * (i + 0.5) / 4
            self.text(55, y, ch, size=18, align="c", bold=True)
            self.text(W - 55, y, ch, size=18, align="c", bold=True)

    def title_block(self, notes=()):
        x, y, w, h = W - 1290, H - 330, 1220, 260
        c = self.c
        c.set_source_rgb(1, 1, 1)
        c.rectangle(x, y, w, h)
        c.fill_preserve()
        c.set_source_rgb(*INK)
        c.set_line_width(3)
        c.stroke()
        for yy in (y + 70, y + 125, y + 190):
            self.wire((x, yy), (x + w, yy), color=INK, width=1.5)
        self.wire((x + 840, y + 125), (x + 840, y + h), color=INK, width=1.5)
        self.text(x + 20, y + 46, "APPLE-1 TERMINAL — MODERN DISCRETE REDESIGN", size=27, bold=True)
        self.text(x + 20, y + 106, self.title, size=22, bold=True)
        self.text(x + 20, y + 165, "Gate-level schematic · rev 0 (draft, unverified) · single +5 V",
                  size=16)
        self.text(x + 860, y + 165, f"{datetime.date.today().isoformat()}", size=16)
        self.text(x + 20, y + 232, "a1video/gateschem.py · ref. Apple 00101 sh. 1-2 · "
                  "docs/apple1-video-redesign.md", size=14, color=GREY)
        self.text(x + 860, y + 236, f"SHEET {self.number} OF {SHEETS}", size=24, bold=True)
        ny = y - 30 - 26 * len(notes)
        for i, n in enumerate(notes):
            self.text(x, ny + i * 26, n, size=15, bold=(i == 0))


# ====================================================================== pinouts

def p163(names_q=("Q0", "Q1", "Q2", "Q3")):
    left = [(2, "CLK"), (7, "ENP"), (10, "ENT"), (1, "/CLR"), (9, "/LOAD"),
            (3, "D0"), (4, "D1"), (5, "D2"), (6, "D3")]
    right = [(14, names_q[0]), (13, names_q[1]), (12, names_q[2]), (11, names_q[3]), None, (15, "TC")]
    return left, right


def p377(clear=False):
    left = [(3, "D0"), (4, "D1"), (7, "D2"), (8, "D3"), (13, "D4"), (14, "D5"), (17, "D6"),
            (18, "D7"), None, (1, "/MR" if clear else "/E"), (11, "CLK")]
    right = [(2, "Q0"), (5, "Q1"), (6, "Q2"), (9, "Q3"), (12, "Q4"), (15, "Q5"), (16, "Q6"), (19, "Q7")]
    return left, right


FLASH_A = {0: 12, 1: 11, 2: 10, 3: 9, 4: 8, 5: 7, 6: 6, 7: 5, 8: 27, 9: 26, 10: 23, 11: 25,
           12: 4, 13: 28, 14: 29, 15: 3, 16: 2}
FLASH_DQ = {0: 13, 1: 14, 2: 15, 3: 17, 4: 18, 5: 19, 6: 20, 7: 21}


def pflash():
    left = [(FLASH_A[i], f"A{i}") for i in range(17)]
    right = [(FLASH_DQ[i], f"DQ{i}") for i in range(8)] + [None, (22, "/CE"), (24, "/OE"), (31, "/WE")]
    return left, right


def bus_entries(s, part, pins, bus_x, names, side="l"):
    """Wire IC pins to a vertical bus at bus_x with 45° entries and bit labels."""
    for pin, name in zip(pins, names):
        px, py = part[pin]
        d = 1 if bus_x > px else -1
        s.wire((px, py), (bus_x - d * 14, py))
        s.wire((bus_x - d * 14, py), (bus_x, py - 14), color=BUSC, width=2.5)
        s.text(bus_x - d * 18, py - 6, name, size=13, color=LBL, align="r" if d > 0 else "l", bold=True)


def bus_span(s, part_pins, bus_x, extra=()):
    ys = [p[1] - 14 for p in part_pins] + list(extra)
    s.bus((bus_x, min(ys)), (bus_x, max(ys)))


# ====================================================================== sheet 1

def sheet1(s):
    # ---------------------------------------------------------- clock and dot phase
    s.text(140, 150, "CLOCK & DOT PHASE", size=24, bold=True)
    x1 = s.ic(220, 260, "X1", "14.31818 MHz OSC", [(1, "EN")], [(8, "OUT")], w=200,
              power="14=+5V 7=GND")
    s.vcc_side(x1["EN"])
    u2 = s.ic(620, 230, "U2A", "74AC74", [(2, "D"), (3, "CK"), (4, "/PR"), (1, "/CLR")],
              [(5, "Q"), (6, "/Q")], w=180, power="14=+5V 7=GND  (U2B on sheet 3)")
    s.wire(x1["OUT"], u2["CK"])
    s.vcc_side(u2["/PR"])
    s.vcc_side(u2["/CLR"])
    q_n = u2["/Q"]
    s.wire(q_n, (870, q_n[1]), (870, 150), (540, 150), (540, u2["D"][1]), u2["D"])
    s.text(705, 142, "÷2 toggle", size=13, color=GREY, align="c")

    u3l, u3r = p163()
    u3 = s.ic(640, 520, "U3", "74HC163  ÷7 (0-6)", u3l, u3r, w=200, power="16=+5V 8=GND")
    s.tie([u3["D0"], u3["D1"], u3["D2"], u3["D3"]], "gnd")
    for pin in ("ENP", "ENT", "/LOAD"):
        s.vcc_side(u3[pin])
    s.nc(u3["Q3"])
    s.nc(u3["TC"])

    q = u2["Q"]
    s.wire(q, (900, q[1]), (900, 470), (560, 470), (560, u3["CLK"][1]), u3["CLK"])
    s.dot((900, q[1]))
    s.wire((900, q[1]), (960, q[1]))
    s.port((960, q[1]), "DOTCLK", "r", "7.159 MHz → all sheets")

    u11 = s.ic(1060, 520, "U11", "74HC138", [(1, "A"), (2, "B"), (3, "C"), (6, "G1"), (4, "/G2A"), (5, "/G2B")],
               [(15, "/Y0"), (14, "/Y1"), (13, "/Y2"), (12, "/Y3"), (11, "/Y4"), (10, "/Y5"), (9, "/Y6"), (7, "/Y7")],
               w=200, power="16=+5V 8=GND")
    for a, b, n in (("Q0", "A", "P0"), ("Q1", "B", "P1"), ("Q2", "C", "P2")):
        s.wire(u3[a], u11[b])
        s.text(985, u3[a][1] - 6, n, size=13, color=LBL, bold=True, align="c")
    s.vcc_side(u11["G1"])
    s.tie([u11["/G2A"], u11["/G2B"]], "gnd")
    s.nc(u11["/Y7"])
    # P2 tap -> off-sheet
    s.dot((940, u3["Q2"][1]))
    s.wire((940, u3["Q2"][1]), (940, 930), (1000, 930))
    s.port((1000, 930), "P2", "r", "MUXSEL, RAM /OE, CLA → sh 2, J3")

    u12 = s.ic(1500, 520, "U12", "74HC574", [(2, "D0"), (3, "D1"), (4, "D2"), (5, "D3"), (6, "D4"), (7, "D5"),
                                              (8, "D6"), (9, "D7"), None, (11, "CLK"), (1, "/OE")],
               [(19, "Q0"), (18, "Q1"), (17, "Q2"), (16, "Q3"), (15, "Q4"), (14, "Q5"), (13, "Q6"), (12, "Q7")],
               w=200, power="20=+5V 10=GND")
    for i in range(7):
        s.wire(u11[f"/Y{i}"], u12[f"D{i}"])
    s.gnd_side(u12["D7"])
    s.label(u12["CLK"], "DOTCLK", "l")
    s.gnd_side(u12["/OE"])
    # /Y6 -> U3 /CLR (synchronous clear at phase 6)
    y6 = u11["/Y6"]
    s.dot((1340, y6[1]))
    s.wire((1340, y6[1]), (1340, 880), (520, 880), (520, u3["/CLR"][1]), u3["/CLR"])
    s.text(1200, 872, "Y6 (active low) → U3 sync clear: count 0…6", size=13, color=GREY, align="c", overbar=False)

    for i in (0, 1, 3, 6, 7):
        s.nc(u12[f"Q{i}"])
    ph3 = u12["Q2"]
    s.wire(ph3, (1760, ph3[1]), (1760, 480), (1800, 480))
    s.port((1800, 480), "/PH3", "r", "→ sh 2 (U25 /E)")
    ph5 = u12["Q4"]
    g_b = s.gate("NOT", 1900, 600, "U45B", [3, 4])
    s.wire(ph5, (1800, ph5[1]), (1800, 600), g_b["in"][0])
    s.port(g_b["out"], "PH5", "r", "→ sh 2 (/WE strobe)")
    ph6 = u12["Q5"]
    g_a = s.gate("NOT", 1900, ph6[1], "U45A", [1, 2])
    s.wire(ph6, g_a["in"][0])
    s.port(g_a["out"], "CHAR_END", "r", "phase 6 → all sheets")
    s.dot((1780, ph6[1]))
    s.wire((1780, ph6[1]), (1780, 800), (1830, 800))
    s.port((1830, 800), "/PH6", "r", "→ all sheets (register enables)")
    s.text(2420, 940, "U45 = 74HC04 (14=+5V 7=GND); U45C-E on sheets 3, 4", size=13, color=GREY)

    # ---------------------------------------------------------- J3 to processor sheet
    j3 = s.ic(2900, 260, "J3", "to Apple 00101 sheet 2/3", [(1, "CLA"), (2, "CL"), (3, "H4"), (4, "H5"),
                                                              (5, "H6"), (6, "V0"), (7, "V1"), (8, "V2"),
                                                              (9, "V3"), (10, "GND")], [], w=170,
             note="⚠ pin-out / mapping to verify")
    for pin, net in (("CLA", "P2"), ("CL", "P0 ⚠"), ("H4", "H4"), ("H5", "H5"), ("H6", "H6"),
                     ("V0", "V0"), ("V1", "V1"), ("V2", "V2"), ("V3", "V3")):
        s.wire(j3[pin], (j3[pin][0] - 40, j3[pin][1]))
        s.label((j3[pin][0] - 40, j3[pin][1]), net, "l")
    s.gnd_side(j3["GND"])

    # ---------------------------------------------------------- video timing
    s.text(140, 1110, "VIDEO TIMING", size=24, bold=True)
    l163, r163 = p163()
    u4 = s.ic(300, 1200, "U4", "74HC163  H0-H3", l163, r163, w=200)
    u5 = s.ic(300, 1600, "U5", "74HC163  H4-H6", l163, r163, w=200)
    u6 = s.ic(860, 1200, "U6", "74HC163  V0-V3", l163, r163, w=200)
    u7 = s.ic(860, 1600, "U7", "74HC163  V4-V7", l163, r163, w=200)
    u8 = s.ic(860, 2000, "U8", "74HC163  V8", l163, r163, w=200,
              power="74HC163: 16=+5V 8=GND")
    for u in (u4, u5, u6, u7, u8):
        s.label(u["CLK"], "DOTCLK", "l")
        s.vcc_side(u["/LOAD"])
        s.tie([u["D0"], u["D1"], u["D2"], u["D3"]], "gnd")
    # H chain
    s.wire((170, 1170), (170, u5["ENP"][1]))
    s.label((170, 1170), "CHAR_END", "r")
    for p in (u4["ENP"], u4["ENT"], u5["ENP"]):
        s.wire((170, p[1]), p)
    s.dot((170, u4["ENP"][1]))
    s.dot((170, u4["ENT"][1]))
    tc = u4["TC"]
    s.wire(tc, (570, tc[1]), (570, 1540), (230, 1540), (230, u5["ENT"][1]), u5["ENT"])
    # V chain
    s.label(u6["ENT"], "CHAR_END", "l")
    for a, b, yy in ((u6, u7, 1560), (u7, u8, 1960)):
        t = a["TC"]
        s.wire(t, (1130, t[1]), (1130, yy), (740, yy), (740, b["ENT"][1]), b["ENT"])
    s.net((690, 1170), [u6["ENP"], u7["ENP"], u8["ENP"]], 690)
    s.label((690, 1170), "H_END", "r")
    s.nc(u5["Q3"])
    s.nc(u5["TC"])
    s.nc(u8["TC"])
    for i in (1, 2, 3):
        s.nc(u8[f"Q{i}"])

    # NAND3s for synchronous clears
    ga = s.gate("NAND", 300, 2030, "U49A", [1, 2, 13, 12], n=3)
    gb = s.gate("NAND", 300, 2200, "U49B", [3, 4, 5, 6], n=3)
    for pin, net in zip(ga["in"], ("H_END", "CHAR_END", None)):
        if net:
            s.label(pin, net, "l")
        else:
            s.vcc_side(pin)
    for pin, net in zip(gb["in"], ("V_END", "H_END", "CHAR_END")):
        s.label(pin, net, "l")
    s.text(330, 2300, "U49 = 74HC10 (14=+5V 7=GND); U49C on sheet 4", size=13, color=GREY)
    o = ga["out"]
    s.wire(o, (450, o[1]), (450, 1950), (210, 1950))
    s.net((210, 1950), [u4["/CLR"], u5["/CLR"]], 210)
    s.text(215, 1944, "/HCLR", size=13, color=LBL, bold=True)
    o = gb["out"]
    s.wire(o, (710, o[1]))
    s.net((710, o[1]), [u6["/CLR"], u7["/CLR"], u8["/CLR"]], 710)
    s.text(600, o[1] - 6, "/VCLR", size=13, color=LBL, bold=True)

    # H bus
    bus_entries(s, u4, ["Q0", "Q1", "Q2", "Q3"], 640, ["H0", "H1", "H2", "H3"])
    bus_entries(s, u5, ["Q0", "Q1", "Q2"], 640, ["H4", "H5", "H6"])
    s.bus((640, u5["Q2"][1] - 14), (640, 1120), (1230, 1120))
    s.text(900, 1110, "H0-H6", size=15, color=BUSC, bold=True)
    # V bus
    bus_entries(s, u6, ["Q0", "Q1", "Q2", "Q3"], 1200, ["V0", "V1", "V2", "V3"])
    bus_entries(s, u7, ["Q0", "Q1", "Q2", "Q3"], 1200, ["V4", "V5", "V6", "V7"])
    bus_entries(s, u8, ["Q0"], 1200, ["V8"])

    # timing ROM and register
    fl, fr = pflash()
    u9 = s.ic(1300, 1200, "U9", "SST39SF010A  timing.bin", fl, fr, w=230, power="32=+5V 16=GND")
    for i in range(7):
        px, py = u9[f"A{i}"]
        s.wire((px, py), (1244, py))
        s.wire((1244, py), (1230, py - 14), color=BUSC, width=2.5)
    s.bus((1230, 1120), (1230, u9["A6"][1] - 14))
    for i in range(7, 16):
        px, py = u9[f"A{i}"]
        s.wire((px, py), (1214, py))
        s.wire((1214, py), (1200, py - 14), color=BUSC, width=2.5)
        s.text(1250, py - 5, f"V{i - 7}", size=11, color=LBL)
    for i in range(7):
        s.text(1250, u9[f"A{i}"][1] - 5, f"H{i}", size=11, color=LBL)
    s.bus((1200, u6["Q0"][1] - 14), (1200, u9["A15"][1] - 14))
    s.text(1160, 2100, "V0-V8", size=15, color=BUSC, bold=True, align="c")
    s.gnd_side(u9["A16"])
    s.tie([u9["/CE"], u9["/OE"]], "gnd", side="r")
    s.vcc_side(u9["/WE"], "r")
    s.nc(u9["DQ6"])
    s.nc(u9["DQ7"])

    l377, r377 = p377()
    u10 = s.ic(1800, 1200, "U10", "74HC377  timing reg", l377, r377, w=220, power="20=+5V 10=GND")
    for i in range(6):
        s.wire(u9[f"DQ{i}"], u10[f"D{i}"])
    s.tie([u10["D6"], u10["D7"]], "gnd")
    s.label(u10["/E"], "/PH6", "l")
    s.label(u10["CLK"], "DOTCLK", "l")
    outs = ["NCSYNC", "NBLANK", "H_END", "V_END", "ROW_CLK", "FRAME_START"]
    for i, n in enumerate(outs):
        p = u10[f"Q{i}"]
        if n in ("H_END",):
            s.label(p, n, "r")
        elif n == "V_END":
            s.text(p[0] + 30, p[1] - 6, n, size=13, color=LBL, bold=True)
        else:
            s.port(p, n, "r", {"NCSYNC": "sh 2", "NBLANK": "sh 2", "ROW_CLK": "sh 4",
                               "FRAME_START": "sh 3, 4"}[n])
    s.nc(u10["Q6"])
    s.nc(u10["Q7"])

    u35 = s.ic(2420, 1290, "U35", "74HC393  frame counter",
               [(1, "1CP"), (13, "2CP"), None, (2, "1MR"), (12, "2MR")],
               [(11, "2Q0"), (10, "2Q1"), (9, "2Q2"), (8, "2Q3"), (3, "1Q0"), (4, "1Q1"), (5, "1Q2"), (6, "1Q3")],
               w=230)
    s.text(2535, 1590, "14=+5V 7=GND · counts on falling edge of V_END", size=11, color=GREY, align="c")
    s.wire(u10["Q3"], u35["1CP"])
    s.tie([u35["1MR"], u35["2MR"]], "gnd")
    q3 = u35["1Q3"]
    s.wire(q3, (2720, q3[1]), (2720, 1620), (2300, 1620), (2300, u35["2CP"][1]), u35["2CP"])
    s.port(u35["2Q0"], "BLINK", "r", "≈1.9 Hz → sh 2")
    for n in ("2Q1", "2Q2", "2Q3", "1Q0", "1Q1", "1Q2"):
        s.nc(u35[n])

    s.title_block([
        "NOTES (sheet 1)",
        "1. Pin numbers are for DIP packages. Check them against the datasheets before layout.",
        "2. Every register and counter is clocked by DOTCLK and enabled by CHAR_END or /PH6.",
        "   74HC163 /CLR and /LOAD are synchronous.",
        "3. The timing ROM output is registered (U10), so table entries are stored one char early",
        "   (see a1video/roms.py).",
        "4. Bus entries are labelled per bit. Pentagons are off-sheet connectors.",
    ])
    s.text(W / 2, 118, "SHEET 1 — CLOCK, DOT PHASE & VIDEO TIMING", size=30, bold=True, align="c")


# ====================================================================== sheet 2

def sheet2(s):
    s.text(140, 150, "RAM ADDRESS MUX", size=24, bold=True)
    l157 = [(2, "1A"), (3, "1B"), (5, "2A"), (6, "2B"), (11, "3A"), (10, "3B"), (14, "4A"), (13, "4B"),
            None, (1, "S"), (15, "/G")]
    r157 = [(4, "1Y"), None, (7, "2Y"), None, (9, "3Y"), None, (12, "4Y")]
    muxes = [s.ic(500, 300 + i * 450, f"U{21 + i}", "74HC157", l157, r157, w=230,
                  power="16=+5V 8=GND") for i in range(3)]
    vid = ["H0", "H1", "H2", "H3", "H4", "H5", "VR0", "VR1", "VR2", "VR3", "VR4", None]
    cur = ["C0", "C1", "C2", "C3", "C4", "C5", "R0", "R1", "R2", "R3", "R4", None]
    for k, m in enumerate(muxes):
        for sec in range(4):
            bit = k * 4 + sec
            a, b, y = f"{sec + 1}A", f"{sec + 1}B", f"{sec + 1}Y"
            if vid[bit] is None:
                s.tie([m[a], m[b]], "gnd", offset=20)
                s.nc(m[y])
                continue
            bus_entries(s, m, [a], 300, [vid[bit]])
            bus_entries(s, m, [b], 380, [cur[bit]])
            bus_entries(s, m, [y], 860, [f"MA{bit}"])
        s.label(m["S"], "P2", "l")
        s.gnd_side(m["/G"])
    s.bus((300, 230), (300, muxes[2]["3A"][1] - 14))
    s.bus((380, 270), (380, muxes[2]["3B"][1] - 14))
    s.bus((300, 230), (300, 200), (560, 200))
    s.port((560, 200), "H0-H5 · VR0-VR4", "r", "sh 1 · sh 4")
    s.bus((380, 270), (420, 270))
    s.port((420, 270), "C0-C5 · R0-R4", "r", "sh 4")
    s.text(300, 2060, "A = video address (P2=0, phases 0-3)", size=13, color=GREY)
    s.text(300, 2080, "B = cursor address (P2=1, phases 4-6)", size=13, color=GREY)

    # ---------------------------------------------------------- RAM
    s.text(1000, 150, "DISPLAY RAM", size=24, bold=True)
    ram_a = {0: 10, 1: 9, 2: 8, 3: 7, 4: 6, 5: 5, 6: 4, 7: 3, 8: 25, 9: 24, 10: 21, 11: 23, 12: 2, 13: 26, 14: 1}
    ram_dq = {0: 11, 1: 12, 2: 13, 3: 15, 4: 16, 5: 17, 6: 18, 7: 19}
    left = [(ram_a[i], f"A{i}") for i in range(11)] + [None] + \
           [(ram_a[i], f"A{i}") for i in range(11, 15)] + [None, (22, "/OE"), (27, "/WE"), (20, "/CE")]
    u24 = s.ic(1000, 300, "U24", "AS6C62256-55", left, [(ram_dq[i], f"DQ{i}") for i in range(8)],
               w=230, power="28=+5V 14=GND · only 2K used")
    bus_entries(s, u24, [f"A{i}" for i in range(11)], 860, [f"MA{i}" for i in range(11)])
    s.bus((860, u24["A0"][1] - 14), (860, muxes[2]["3Y"][1] - 14))
    s.text(870, 1400, "MA0-MA10", size=15, color=BUSC, bold=True)
    s.tie([u24[f"A{i}"] for i in range(11, 15)], "gnd")
    s.label(u24["/OE"], "P2", "l")
    s.gnd_side(u24["/CE"])
    bus_entries(s, u24, [f"DQ{i}" for i in range(8)], 1330, [f"MD{i}" for i in range(8)])

    # write strobe and write-buffer enable
    ga = s.gate("NAND", 1050, 1080, "U44A", [1, 2, 3])
    gb = s.gate("NAND", 1050, 1250, "U44B", [4, 5, 6])
    s.label(ga["in"][0], "PH5", "l")
    s.label(ga["in"][1], "WE", "l")
    s.label(gb["in"][0], "P2", "l")
    s.label(gb["in"][1], "WE", "l")
    o = ga["out"]
    s.wire(o, (1190, o[1]), (1190, 1030), (920, 1030), (920, u24["/WE"][1]), u24["/WE"])
    s.text(1000, 1022, "/WE_RAM", size=13, color=LBL, bold=True)
    s.text(1050, 1310, "U44 = 74HC00 (14=+5V 7=GND); U44C-D on sheet 3", size=12, color=GREY)

    # write driver (drawn mirrored: outputs on the left)
    u27 = s.ic(1500, 1000, "U27", "74HC541  write driver",
               [(18, "Y1"), (17, "Y2"), (16, "Y3"), (15, "Y4"), (14, "Y5"), (13, "Y6"), (12, "Y7"), (11, "Y8")],
               [(2, "A1"), (3, "A2"), (4, "A3"), (5, "A4"), (6, "A5"), (7, "A6"), (8, "A7"), (9, "A8"),
                None, (19, "/OE2"), (1, "/OE1")], w=230, power="20=+5V 10=GND")
    bus_entries(s, u27, [f"Y{i + 1}" for i in range(8)], 1330, [f"MD{i}" for i in range(8)])
    bus_entries(s, u27, [f"A{i + 1}" for i in range(7)], 1880, [f"LD{i}" for i in range(7)])
    s.gnd_side(u27["A8"], "r")
    s.gnd_side(u27["/OE2"], "r")
    o = gb["out"]
    s.wire(o, (1250, o[1]), (1250, 1420), (1830, 1420), (1830, u27["/OE1"][1]), u27["/OE1"])
    s.text(1560, 1412, "/WBUF", size=13, color=LBL, bold=True)
    s.bus((1880, u27["A1"][1] - 14), (1880, 960), (1940, 960))
    s.port((1940, 960), "LD0-LD6", "r", "input latch, sh 3")

    # ---------------------------------------------------------- video latch / char ROM / shifter
    s.text(1500, 150, "CHARACTER PATH", size=24, bold=True)
    l377, r377 = p377()
    u25 = s.ic(1500, 300, "U25", "74HC377  video latch", l377, r377, w=220, power="20=+5V 10=GND")
    bus_entries(s, u25, [f"D{i}" for i in range(7)], 1330, [f"MD{i}" for i in range(7)])
    s.bus((1330, u24["DQ0"][1] - 14), (1330, u27["Y8"][1] - 14))
    s.text(1340, 1270, "MD0-MD7", size=15, color=BUSC, bold=True)
    s.label(u25["D7"], "CURMATCH", "l")
    s.label(u25["/E"], "/PH3", "l")
    s.label(u25["CLK"], "DOTCLK", "l")
    fl, fr = pflash()
    u28 = s.ic(2100, 300, "U28", "SST39SF010A  chargen.bin", fl, fr, w=240, power="32=+5V 16=GND")
    bus_entries(s, u25, [f"Q{i}" for i in range(7)], 2000, [f"VC{i}" for i in range(7)])
    bus_entries(s, u28, ["A0", "A1", "A2"], 2000, ["V0", "V1", "V2"])
    bus_entries(s, u28, [f"A{i}" for i in range(3, 10)], 2000, [f"VC{i}" for i in range(7)])
    s.bus((2000, 240), (2000, u28["A9"][1] - 14))
    s.bus((2000, 240), (2040, 240))
    s.port((2040, 240), "V0-V2", "r", "sh 1")
    gc = s.gate("AND", 1830, u28["A10"][1], "U37C", [9, 10, 8])
    q7 = u25["Q7"]
    s.wire(q7, (1785, q7[1]), (1785, gc["in"][0][1]), gc["in"][0])
    i2 = gc["in"][1]
    s.wire(i2, (1790, i2[1]), (1790, 720), (1770, 720))
    s.port((1770, 720), "BLINK", "l", "sh 1")
    s.wire(gc["out"], u28["A10"])
    s.text(1990, u28["A10"][1] - 6, "CURSOR", size=12, color=LBL, bold=True, align="r")
    # BANK jumper with pull-down
    a11 = u28["A11"]
    s.wire(a11, (1940, a11[1]), (1940, 700))
    s.dot((1940, 700))
    s.jumper((1940, 700), (1940, 780), "JP2 BANK")
    s.vcc((1940, 780), "down")
    s.wire((1940, 700), (1880, 700))
    s.resistor((1880, 700), (1880, 830), "")
    s.text(1800, 770, "R4 10k", size=14)
    s.gnd((1880, 830))
    s.tie([u28[f"A{i}"] for i in range(12, 17)], "gnd")
    s.tie([u28["/CE"], u28["/OE"]], "gnd", side="r")
    s.vcc_side(u28["/WE"], "r")

    u29 = s.ic(2800, 300, "U29", "74HC166  dot shifter",
               [(2, "A"), (3, "B"), (4, "C"), (5, "D"), (10, "E"), (11, "F"), (12, "G"), (14, "H"),
                None, (15, "SH/LD"), (7, "CLK"), (6, "CLKINH"), (1, "SER"), (9, "/CLR")],
               [(13, "QH")], w=200, power="16=+5V 8=GND · H shifts out first")
    for i, pin in enumerate("ABCDEFGH"):
        s.wire(u28[f"DQ{i}"], u29[pin])
    s.label(u29["SH/LD"], "/PH6", "l")
    s.label(u29["CLK"], "DOTCLK", "l")
    s.tie([u29["CLKINH"], u29["SER"]], "gnd")
    s.vcc_side(u29["/CLR"])

    # ---------------------------------------------------------- composite output
    s.text(3250, 150, "COMPOSITE VIDEO OUT", size=24, bold=True)
    g1 = s.gate("AND", 3230, u29["QH"][1] + 11, "U37A", [1, 2, 3])
    s.wire(u29["QH"], g1["in"][0])
    s.text(3100, u29["QH"][1] - 6, "DOTS", size=13, color=LBL, bold=True, align="c")
    i2 = g1["in"][1]
    s.wire(i2, (3150, i2[1]), (3150, 420), (3120, 420))
    s.port((3120, 420), "NBLANK", "l", "sh 1")
    g2 = s.gate("AND", 3230, 560, "U37B", [4, 5, 6])
    s.wire(g2["in"][0], (3120, g2["in"][0][1]))
    s.port((3120, g2["in"][0][1]), "NCSYNC", "l", "sh 1")
    s.vcc_side(g2["in"][1])
    s.text(3230, 650, "U37 = 74AC08 (14=+5V 7=GND); U37D on sheet 3", size=12, color=GREY)
    vid, cs = g1["out"], g2["out"]
    nx = 3640
    s.resistor(vid, (nx, vid[1]), "R2 270Ω")
    s.resistor(cs, (nx, cs[1]), "R1 620Ω")
    s.text((vid[0] + nx) / 2, vid[1] + 26, "VID", size=12, color=LBL, align="c")
    s.text((cs[0] + nx) / 2, cs[1] + 26, "CSYNC_OUT", size=12, color=LBL, align="c")
    s.wire((nx, vid[1]), (nx, cs[1]))
    s.dot((nx, cs[1]))
    s.resistor((nx, cs[1]), (nx, cs[1] + 150), "R3 120Ω")
    s.gnd((nx, cs[1] + 150))
    s.wire((nx, cs[1]), (3820, cs[1]))
    c = s.c
    c.set_source_rgb(*INK)
    c.set_line_width(2.4)
    c.arc(3840, cs[1], 20, 0, 2 * math.pi)
    c.stroke()
    c.arc(3840, cs[1], 6, 0, 2 * math.pi)
    c.fill()
    s.wire((3840, cs[1] + 20), (3840, cs[1] + 60), color=INK)
    s.gnd((3840, cs[1] + 60))
    s.text(3870, cs[1] - 26, "J2  RCA", size=18, bold=True)
    s.text(3870, cs[1] - 6, "COMPOSITE", size=14)
    s.text(3870, cs[1] + 12, "1 Vpp / 75 Ω", size=14)
    s.text(3250, 860, "Into 75 Ω: sync 0 V · black 0.30 V · white 0.99 V · source 73 Ω", size=14)

    s.title_block([
        "NOTES (sheet 2)",
        "1. Each 977.8 ns char period is split in two by P2 (U3 Q2):",
        "   phases 0-3 (P2=0) are the video read. The mux selects {VR,H}, RAM /OE is low,",
        "   and U25 latches at the end of PH3.",
        "   Phases 4-6 (P2=1) are the write slot. The mux selects {R,C}; if WE, U27 drives MD",
        "   and /WE pulses in PH5.",
        "2. U28 address: A0-A2 = scan line, A3-A9 = code, A10 = CURSOR, A11 = BANK.",
        "   DQ7 = leftmost dot.",
        "3. ⚠ Check the MD bus turnaround (RAM /OE off vs U27 on) at the PH3→PH4 boundary.",
        "4. Use 74AC08 for U37: R1/R2 need about 15 mA of drive.",
    ])
    s.text(W / 2, 118, "SHEET 2 — DISPLAY RAM, CHARACTER PATH & COMPOSITE OUTPUT", size=30, bold=True,
           align="c")


# ====================================================================== sheet 3

def sheet3(s):
    s.text(140, 150, "PIA INTERFACE & INPUT LATCH", size=24, bold=True)
    j1 = s.ic(180, 300, "J1", "to PIA (Apple 00101 sh 2/3)",
              [None] * 11 + [(10, "+5V"), (11, "GND")],
              [(1, "RD1"), (2, "RD2"), (3, "RD3"), (4, "RD4"), (5, "RD5"), (6, "RD6"), (7, "RD7"),
               (8, "RDA"), (9, "DA")], w=170,
              note="⚠ pin-out / DA, RDA polarity to verify")
    s.vcc_side(j1["+5V"])
    s.gnd_side(j1["GND"])
    u26 = s.ic(700, 300, "U26", "74HCT273  input latch",
               [(3, "D0"), (4, "D1"), (7, "D2"), (8, "D3"), (13, "D4"), (14, "D5"), (17, "D6"), (18, "D7"),
                None, (1, "/MR"), (11, "CLK")],
               [(2, "Q0"), (5, "Q1"), (6, "Q2"), (9, "Q3"), (12, "Q4"), (15, "Q5"), (16, "Q6"), (19, "Q7")],
               w=220, power="20=+5V 10=GND · TTL-level inputs")
    for i in range(7):
        s.wire(j1[f"RD{i + 1}"], u26[f"D{i}"])
        s.text(520, j1[f"RD{i + 1}"][1] - 6, f"RD{i + 1}", size=12, color=LBL, bold=True, align="c")
    s.gnd_side(u26["D7"])
    s.nc(u26["Q7"])
    rda = j1["RDA"]
    s.wire(rda, (440, rda[1]))
    s.label((440, rda[1]), "RDA", "r")
    s.label(u26["CLK"], "LATCH_LD", "l")
    gc = s.gate("NOT", 470, u26["/MR"][1], "U45C", [5, 6])
    s.wire(gc["out"], u26["/MR"])
    s.wire(gc["in"][0], (gc["in"][0][0], 660))
    s.label((gc["in"][0][0], 660), "LATCH_CLR", "r")
    bus_entries(s, u26, [f"Q{i}" for i in range(7)], 1050, [f"LD{i}" for i in range(7)])
    s.bus((1050, 250), (1050, 880), (1600, 880))
    s.bus((1050, 250), (1100, 250))
    s.port((1100, 250), "LD0-LD6", "r", "→ sh 2 (U27)")

    # ---------------------------------------------------------- DA / CLR conditioning
    s.text(140, 1400, "DA / CLR SYNCHRONISERS", size=24, bold=True)
    da = j1["DA"]
    s.wire(da, (410, da[1]), (410, 1500), (470, 1500))
    s.text(416, 1000, "DA", size=13, color=LBL, bold=True)
    ga = s.gate("SNOT", 500, 1500, "U39A", [1, 2])
    gb = s.gate("SNOT", 640, 1500, "U39B", [3, 4])
    s.wire(ga["out"], gb["in"][0])
    u2 = s.ic(900, 1475, "U2B", "74AC74", [(12, "D"), (11, "CK"), (10, "/PR"), (13, "/CLR")],
              [(9, "Q"), (8, "/Q")], w=180, power="(U2A on sheet 1)")
    s.wire(gb["out"], u2["D"])
    s.text(790, 1494, "DA_BUF", size=12, color=LBL, bold=True, align="c")
    s.label(u2["CK"], "DOTCLK", "l")
    s.vcc_side(u2["/PR"])
    s.vcc_side(u2["/CLR"])
    s.nc(u2["/Q"])
    u48 = s.ic(1260, 1475, "U48", "74HC175",
               [(4, "D1"), (5, "D2"), (12, "D3"), (13, "D4"), None, (9, "CLK"), (1, "/MR")],
               [(2, "Q1"), (3, "/Q1"), (7, "Q2"), (6, "/Q2"), (10, "Q3"), (11, "/Q3"), (15, "Q4"), (14, "/Q4")],
               w=230, power="16=+5V 8=GND")
    s.wire(u2["Q"], u48["D1"])
    s.text(1170, 1494, "DA_S1", size=12, color=LBL, bold=True, align="c")
    s.gnd_side(u48["D4"])
    s.label(u48["CLK"], "DOTCLK", "l")
    s.vcc_side(u48["/MR"])
    q2 = u48["Q2"]
    s.wire(q2, (1555, q2[1]), (1555, 1780), (1165, 1780), (1165, u48["D3"][1]), u48["D3"])
    s.text(1360, 1772, "CLR_S1", size=12, color=LBL, bold=True, align="c")
    for n in ("/Q1", "/Q2", "/Q3", "Q4", "/Q4"):
        s.nc(u48[n])
    s.text(560, 1580, "U39 = 74HCT14 (14=+5V 7=GND)", size=12, color=GREY)
    # CLR switch with pull-up, debounce / power-on capacitor
    node = (330, 1700)
    s.resistor((330, 1600), node, "R5 10k")
    s.vcc((330, 1600), "up")
    s.dot(node)
    s.switch(node, (330, 1830), "SW1 CLR")
    s.gnd((330, 1830))
    s.wire(node, (570, 1700))
    s.dot((450, 1700))
    s.capacitor((450, 1700), (450, 1820), "C1 1µF")
    s.gnd((450, 1820))
    gcl = s.gate("SNOT", 600, 1700, "U39C", [5, 6])
    s.text(520, 1692, "/CLR_SW", size=12, color=LBL, bold=True, align="c")
    o = gcl["out"]
    s.wire(o, (1140, o[1]), (1140, u48["D2"][1]), u48["D2"])
    s.text(900, 1692, "CLR_BUF", size=12, color=LBL, bold=True, align="c")

    # ---------------------------------------------------------- sequencer ROMs
    s.text(1500, 150, "CONTROL SEQUENCER", size=24, bold=True)
    fl, fr = pflash()
    u33 = s.ic(1700, 300, "U33", "SST39SF010A  seq_lo.bin", fl, fr, w=240, power="32=+5V 16=GND")
    u34 = s.ic(1700, 950, "U34", "SST39SF010A  seq_hi.bin", fl, fr, w=240, power="32=+5V 16=GND")
    sa = (["S0", "S1", "S2", "S3", "S4", "DA_S2", "CLR_S2", "COL39", "ROWEQTOP", "READY"] +
          [f"LD{i}" for i in range(7)])
    for u in (u33, u34):
        bus_entries(s, u, [f"A{i}" for i in range(17)], 1600, sa)
        s.tie([u["/CE"], u["/OE"]], "gnd", side="r")
        s.vcc_side(u["/WE"], "r")
    s.bus((1600, 230), (1600, 2000))
    s.text(1610, 2030, "SEQUENCER ADDRESS BUS", size=14, color=BUSC, bold=True)
    for net, src in (("DA_S2", u48["Q1"]), ("CLR_S2", u48["Q3"])):
        s.wire(src, (1586, src[1]))
        s.wire((1586, src[1]), (1600, src[1] - 14), color=BUSC, width=2.5)
        s.text(1580, src[1] - 6, net, size=12, color=LBL, bold=True, align="r")
    for net, y, sh in (("COL39", 1560, "sh 4"), ("ROWEQTOP", 1640, "sh 4")):
        s.wire((1614, y), (1680, y))
        s.wire((1614, y), (1600, y - 14), color=BUSC, width=2.5)
        s.port((1680, y), net, "r", sh)

    # ---------------------------------------------------------- state / control registers
    l377, r377 = p377()
    u36 = s.ic(2300, 300, "U36", "74HC377  state / ctl lo", l377, r377, w=220, power="20=+5V 10=GND")
    u38 = s.ic(2300, 950, "U38", "74HC377  ctl hi", l377, r377, w=220, power="20=+5V 10=GND")
    for i in range(8):
        s.wire(u33[f"DQ{i}"], u36[f"D{i}"])
        s.wire(u34[f"DQ{i}"], u38[f"D{i}"])
    for u in (u36, u38):
        s.label(u["/E"], "/PH6", "l")
        s.label(u["CLK"], "DOTCLK", "l")
    bus_entries(s, u36, [f"Q{i}" for i in range(5)], 2620, [f"S{i}" for i in range(5)])
    s.bus((2620, u36["Q4"][1] - 14), (2620, 200), (1600, 200), (1600, 230))
    s.text(2100, 192, "S0-S4 (state)", size=14, color=BUSC, bold=True, align="c")
    for q, net, sh in (("Q5", "WE", "sh 2"), ("Q6", "COL_INC", "sh 4"), ("Q7", "COL_CLR", "sh 4")):
        s.port(u36[q], net, "r", sh)
    for q, net in (("Q0", "ROW_INC"), ("Q1", "ROW_CLR"), ("Q2", "TOP_INC"), ("Q3", "TOP_CLR")):
        s.port(u38[q], net, "r", "sh 4")
    for q, net in (("Q4", "LATCH_LD"), ("Q5", "LATCH_CLR"), ("Q6", "RDA")):
        s.wire(u38[q], (u38[q][0] + 40, u38[q][1]))
        s.label((u38[q][0] + 40, u38[q][1]), net, "r")

    # ---------------------------------------------------------- FRAMESEEN / READY
    s.text(2200, 1500, "SLOW-MODE FRAME FLAG", size=24, bold=True)
    u47 = s.ic(2600, 1650, "U47", "74HC109", [(2, "J"), (3, "/K"), (4, "CK"), (5, "/S"), (1, "/R")],
               [(6, "Q"), (7, "/Q")], w=180, power="16=+5V 8=GND")
    gd = s.gate("AND", 2300, u47["J"][1], "U37D", [12, 13, 11])
    s.label(gd["in"][0], "FRAME_START", "l")
    s.label(gd["in"][1], "CHAR_END", "l")
    s.wire(gd["out"], u47["J"])
    s.text(2470, u47["J"][1] - 6, "J_FS", size=12, color=LBL, bold=True, align="c")
    ge = s.gate("NAND", 2300, 1800, "U44D", [12, 13, 11])
    s.label(ge["in"][1], "CHAR_END", "l")
    q7 = u38["Q7"]
    s.wire(q7, (2620, q7[1]), (2620, 1560), (2240, 1560), (2240, ge["in"][0][1]), ge["in"][0])
    s.text(2430, 1552, "FS_CLR", size=12, color=LBL, bold=True, align="c")
    o = ge["out"]
    s.wire(o, (2490, o[1]), (2490, u47["/K"][1]), u47["/K"])
    s.text(2490, o[1] + 20, "/K_FS", size=12, color=LBL, bold=True, align="c")
    s.label(u47["CK"], "DOTCLK", "l")
    s.vcc_side(u47["/S"])
    s.vcc_side(u47["/R"])
    s.wire(u47["Q"], (2860, u47["Q"][1]))
    s.label((2860, u47["Q"][1]), "FRAMESEEN", "r")
    gf = s.gate("NAND", 3000, u47["/Q"][1] + 11, "U44C", [10, 9, 8])
    s.wire(u47["/Q"], gf["in"][0])
    s.text(2900, u47["/Q"][1] + 18, "/FS", size=12, color=LBL, bold=True, align="c")
    i2 = gf["in"][1]
    s.wire(i2, (2940, i2[1]), (2940, 1820))
    node = (2940, 1820)
    s.dot(node)
    s.resistor(node, (2940, 1930), "R6 10k")
    s.gnd((2940, 1930))
    s.wire(node, (3040, 1820))
    s.jumper((3040, 1820), (3040, 1900), "JP1 SLOW")
    s.vcc((3040, 1900), "down")
    s.text(2880, 1812, "SLOW", size=12, color=LBL, bold=True, align="r")
    o = gf["out"]
    s.wire(o, (3160, o[1]), (3160, 2000), (1600, 2000))
    s.text(2400, 1992, "READY = /SLOW + FRAMESEEN", size=13, color=LBL, bold=True, align="c")
    s.dot((1600, 2000))
    s.text(3000, 2060, "U44 = 74HC00, U37 = 74AC08 (A-C on sheet 2), U45 = 74HC04", size=12, color=GREY)

    s.title_block([
        "NOTES (sheet 3)",
        "1. Moore state machine: U33/U34 hold next state + that state's controls (seq_*.bin).",
        "   U36/U38 load them at the end of each char period (/E = /PH6).",
        "2. RDA is a 3-period pulse that triggers the 74123 (B3) on Apple sheet 2/3.",
        "   Set its polarity in seq_hi.bin.",
        "3. Two-stage synchronisers for DA and CLR: U2B → U48 and U48 → U48.",
        "4. R5/C1 debounce SW1 and give a clear-screen at power-on.",
        "5. U47: if J_FS and /K_FS coincide the flag toggles; worst case is one extra frame",
        "   of delay, in SLOW mode only.",
    ])
    s.text(W / 2, 118, "SHEET 3 — PIA INTERFACE & CONTROL SEQUENCER", size=30, bold=True, align="c")


# ====================================================================== sheet 4

def entry(s, p, bus_x, name):
    """Single wire from point p into a vertical bus at bus_x with a labelled entry."""
    d = 1 if bus_x > p[0] else -1
    s.wire(p, (bus_x - d * 14, p[1]))
    s.wire((bus_x - d * 14, p[1]), (bus_x, p[1] - 14), color=BUSC, width=2.5)
    s.text(bus_x - d * 18, p[1] - 6, name, size=13, color=LBL, bold=True, align="r" if d > 0 else "l")


def counter_pair(s, x0, title, refs, bits, enp, clr_gate, ld_gate, d_from=None):
    """Two cascaded 74HC163s with control trunks, NAND3 drivers and an output bus."""
    s.text(x0 + 60, 200, title, size=21, bold=True)
    l163, r163 = p163()
    lo = s.ic(x0 + 520, 330, refs[0], "74HC163", l163, r163, w=200)
    hi = s.ic(x0 + 520, 730, refs[1], "74HC163", l163, r163, w=200, power="16=+5V 8=GND")
    for u in (lo, hi):
        s.label(u["CLK"], "DOTCLK", "l")
    s.label(lo["ENT"], "CHAR_END", "l")
    t = lo["TC"]
    s.wire(t, (x0 + 790, t[1]), (x0 + 790, 670), (x0 + 370, 670), (x0 + 370, hi["ENT"][1]), hi["ENT"])
    s.nc(hi["TC"])
    # ENP trunk from the off-sheet control
    s.net((x0 + 300, 270), [lo["ENP"], hi["ENP"]], x0 + 300)
    s.wire((x0 + 300, 270), (x0 + 330, 270))
    s.port((x0 + 330, 270), enp, "r", "sh 3" if enp != "ROW_CLK" else "sh 1")
    # /CLR trunk from its NAND3
    g = s.gate("NAND", x0 + 100, 1120, clr_gate[0], clr_gate[1], n=3)
    for pin, net in zip(g["in"], clr_gate[2]):
        s.vcc_side(pin) if net == "+5V" else s.label(pin, net, "l")
    s.net(g["out"], [lo["/CLR"], hi["/CLR"]], x0 + 320)
    s.text(x0 + 260, 1112, clr_gate[3], size=12, color=LBL, bold=True, align="c")
    if ld_gate:
        g2 = s.gate("NAND", x0 + 100, 1260, ld_gate[0], ld_gate[1], n=3)
        for pin, net in zip(g2["in"], ld_gate[2]):
            s.vcc_side(pin) if net == "+5V" else s.label(pin, net, "l")
        s.net(g2["out"], [lo["/LOAD"], hi["/LOAD"]], x0 + 340)
        s.text(x0 + 260, 1252, ld_gate[3], size=12, color=LBL, bold=True, align="c")
    else:
        s.vcc_side(lo["/LOAD"])
        s.vcc_side(hi["/LOAD"])
    if d_from:
        for i in range(4):
            s.label(lo[f"D{i}"], d_from[i], "l")
        s.label(hi["D0"], d_from[4], "l")
        s.tie([hi["D1"], hi["D2"], hi["D3"]], "gnd")
    else:
        s.tie([lo[f"D{i}"] for i in range(4)], "gnd")
        s.tie([hi[f"D{i}"] for i in range(4)], "gnd")
    bx = x0 + 840
    bus_entries(s, lo, ["Q0", "Q1", "Q2", "Q3"], bx, bits[:4])
    bus_entries(s, hi, [f"Q{i}" for i in range(len(bits) - 4)], bx, bits[4:])
    for i in range(len(bits) - 4, 4):
        s.nc(hi[f"Q{i}"])
    s.bus((bx, lo["Q0"][1] - 14), (bx, 1450))
    return lo, hi


def sheet4(s):
    cols = [120, 1020, 1920, 2820]
    counter_pair(s, cols[0], "COL (cursor column 0-39)", ("U17", "U18"),
                 ["C0", "C1", "C2", "C3", "C4", "C5"], "COL_INC",
                 ("U49C", [9, 10, 11, 8], ["COL_CLR", "CHAR_END", "+5V"], "/COLCLR"), None)
    counter_pair(s, cols[1], "ROW (cursor row, mod 24)", ("U19", "U20"),
                 ["R0", "R1", "R2", "R3", "R4"], "ROW_INC",
                 ("U50A", [1, 2, 13, 12], ["ROW_CLR", "CHAR_END", "+5V"], "/ROWCLR"),
                 ("U50B", [3, 4, 5, 6], ["ROW_INC", "ROW23", "CHAR_END"], "/ROWLD"))
    counter_pair(s, cols[2], "TOP (first displayed row, mod 24)", ("U15", "U16"),
                 ["T0", "T1", "T2", "T3", "T4"], "TOP_INC",
                 ("U50C", [9, 10, 11, 8], ["TOP_CLR", "CHAR_END", "+5V"], "/TOPCLR"),
                 ("U51A", [1, 2, 13, 12], ["TOP_INC", "TOP23", "CHAR_END"], "/TOPLD"))
    counter_pair(s, cols[3], "VROW (video row, loads TOP)", ("U13", "U14"),
                 ["VR0", "VR1", "VR2", "VR3", "VR4"], "ROW_CLK",
                 ("U51B", [3, 4, 5, 6], ["ROW_CLK", "VR23", "CHAR_END"], "/VRCLR"),
                 ("U51C", [9, 10, 11, 8], ["FRAME_START", "CHAR_END", "+5V"], "/VRLD"),
                 d_from=["T0", "T1", "T2", "T3", "T4"])
    s.text(120, 1360, "U49 / U50 / U51 = 74HC10 (14=+5V 7=GND) · mod-24 wrap: /LOAD with D=0 at count 23",
           size=13, color=GREY)

    # main bus
    s.bus((200, 1450), (3760, 1450))
    s.port((200, 1450), "H0-H5", "l")
    s.port((3760, 1450), "C · R · VR", "r", "→ sh 2 (address mux, U25)")
    s.text(2000, 1440, "CURSOR / SCROLL BUS: H0-H5 · C0-C5 · R0-R4 · T0-T4 · VR0-VR4", size=15,
           color=BUSC, bold=True, align="c")
    s.text(90, 1490, "H0-H5 from sheet 1", size=12, color=GREY)

    # ==23 / ==39 detectors
    s.text(140, 1580, "WRAP DETECTORS", size=21, bold=True)
    specs = [("U40A", [1, 2, 4, 5, 6], ["C0", "C1", "C2", "C5"], "COL39"),
             ("U40B", [9, 10, 12, 13, 8], ["R0", "R1", "R2", "R4"], "ROW23"),
             ("U41A", [1, 2, 4, 5, 6], ["T0", "T1", "T2", "T4"], "TOP23"),
             ("U41B", [9, 10, 12, 13, 8], ["VR0", "VR1", "VR2", "VR4"], "VR23")]
    for k, (ref, pins, ins, out) in enumerate(specs):
        g = s.gate("AND", 520, 1700 + k * 170, ref, pins, n=4)
        for p, n in zip(g["in"], ins):
            entry(s, p, 300, n)
        if out == "COL39":
            s.port(g["out"], out, "r", "→ sh 3")
        else:
            s.label(g["out"], out, "r")
    s.bus((300, 1450), (300, 1700 + 3 * 170 + 33 - 14))
    s.text(380, 2290, "U40, U41 = 74HC21 (14=+5V 7=GND)", size=12, color=GREY)
    s.text(380, 2310, "Only 23 (10111) has Q4·Q2·Q1·Q0 = 1 in 0-23; only 39 has Q5·Q2·Q1·Q0 in 0-39",
           size=12, color=GREY)

    # comparators
    s.text(1100, 1580, "CURSOR MATCH & ROW == TOP", size=21, bold=True)
    l688 = ([(2 + 2 * i if i < 4 else 3 + 2 * i, f"P{i}") for i in range(8)] +
            [(3 + 2 * i if i < 4 else 4 + 2 * i, f"Q{i}") for i in range(8)] + [None, (1, "/G")])
    l688 = [(2, "P0"), (4, "P1"), (6, "P2"), (8, "P3"), (11, "P4"), (13, "P5"), (15, "P6"), (17, "P7"),
            (3, "Q0"), (5, "Q1"), (7, "Q2"), (9, "Q3"), (12, "Q4"), (14, "Q5"), (16, "Q6"), (18, "Q7"),
            None, (1, "/G")]
    r688 = [(19, "/P=Q")]
    u30 = s.ic(1300, 1640, "U30", "74HC688", l688, r688, w=200, power="20=+5V 10=GND")
    u31 = s.ic(2200, 1640, "U31", "74HC688", l688, r688, w=200, power="20=+5V 10=GND")
    u32 = s.ic(3100, 1640, "U32", "74HC688", l688, r688, w=200, power="20=+5V 10=GND")
    bus_entries(s, u30, [f"P{i}" for i in range(8)], 1180, ["H0", "H1", "H2", "H3", "H4", "H5", "VR0", "VR1"])
    bus_entries(s, u30, [f"Q{i}" for i in range(8)], 1180, ["C0", "C1", "C2", "C3", "C4", "C5", "R0", "R1"])
    s.gnd_side(u30["/G"])
    s.bus((1180, 1450), (1180, u30["Q7"][1] - 14))
    bus_entries(s, u31, ["P0", "P1", "P2"], 2080, ["VR2", "VR3", "VR4"])
    bus_entries(s, u31, ["Q0", "Q1", "Q2"], 2080, ["R2", "R3", "R4"])
    s.tie([u31[f"P{i}"] for i in range(3, 8)], "gnd")
    s.tie([u31[f"Q{i}"] for i in range(3, 8)], "gnd")
    s.bus((2080, 1450), (2080, u31["Q2"][1] - 14))
    bus_entries(s, u32, [f"P{i}" for i in range(5)], 2980, ["R0", "R1", "R2", "R3", "R4"])
    bus_entries(s, u32, [f"Q{i}" for i in range(5)], 2980, ["T0", "T1", "T2", "T3", "T4"])
    s.tie([u32[f"P{i}"] for i in range(5, 8)], "gnd")
    s.tie([u32[f"Q{i}"] for i in range(5, 8)], "gnd")
    s.gnd_side(u32["/G"])
    s.bus((2980, 1450), (2980, u32["Q4"][1] - 14))
    eq = u30["/P=Q"]
    s.wire(eq, (1640, eq[1]), (1640, 2260), (2130, 2260), (2130, u31["/G"][1]), u31["/G"])
    s.text(1890, 2252, "/EQ1 (cascade)", size=12, color=LBL, bold=True, align="c")
    gd = s.gate("NOT", 1700 + 900, u31["/P=Q"][1], "U45D", [9, 8])
    s.wire(u31["/P=Q"], gd["in"][0])
    s.port(gd["out"], "CURMATCH", "r", "→ sh 2 (U25 D7)")
    ge = s.gate("NOT", 3520, u32["/P=Q"][1], "U45E", [11, 10])
    s.wire(u32["/P=Q"], ge["in"][0])
    s.port(ge["out"], "ROWEQTOP", "r", "→ sh 3")
    s.text(2600, 1720, "U45 = 74HC04", size=12, color=GREY)

    s.title_block([
        "NOTES (sheet 4)",
        "1. COL/ROW = cursor position (physical row). TOP = physical row shown at the top of the screen.",
        "   VROW = row being displayed. VROW loads TOP at FRAME_START and steps on ROW_CLK.",
        "2. 74HC163 /CLR and /LOAD are synchronous. Each is gated with CHAR_END so it acts only",
        "   at the end of a char period. CLR has priority over INC.",
        "3. Scrolling = TOP+1 plus clearing one line. No display data is moved.",
        "4. Same-name labels (e.g. ROW23, T0-T4) connect within this sheet.",
    ])
    s.text(W / 2, 118, "SHEET 4 — CURSOR / SCROLL COUNTERS & COMPARATORS", size=30, bold=True, align="c")


SHEET_FUNCS = [(sheet1, "CLOCK, DOT PHASE & VIDEO TIMING"),
               (sheet2, "DISPLAY RAM, CHARACTER PATH & VIDEO OUT"),
               (sheet3, "PIA INTERFACE & CONTROL SEQUENCER"),
               (sheet4, "CURSOR / SCROLL COUNTERS & COMPARATORS")]


def render(out):
    for i, (fn, title) in enumerate(SHEET_FUNCS, start=1):
        base = f"{out}/a1video-sheet{i}"
        img = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
        fn(Sch(img, i, title))
        img.write_to_png(base + ".png")
        svg = cairo.SVGSurface(base + ".svg", W, H)
        fn(Sch(svg, i, title))
        svg.finish()
        print("wrote", base + ".png", "and .svg")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="docs/schematic", help="output directory")
    args = ap.parse_args()
    import os
    os.makedirs(args.out, exist_ok=True)
    render(args.out)


if __name__ == "__main__":
    main()
