"""KiCad 9 project for the gate-level design (root + 5 hierarchical sheets).

    python3 -m a1video.kicad [--out kicad] [--check]

The design is entered here as a netlist (every IC pin -> net), transcribed from
the gate-level drawings in gateschem.py.  The generator places the real KiCad
library symbols (embedded in each sheet) and connects every pin with a short
stub and a net label: local labels for nets that stay on one sheet, global
labels for nets that cross sheets, power symbols for +5V/GND and no-connect
flags on unused outputs.  --check exports the netlist with kicad-cli, compares
it pin-for-pin with the table below and runs ERC.

Symbols come from the stock KiCad libraries (KICAD9_SYMBOL_DIR, default
/usr/share/kicad/symbols).  Where the library has no HC/AC variant the LS or
HCT symbol with the identical DIP pin-out is used and Value names the real part.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

SYMDIR = os.environ.get("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")
PROJECT = "a1video"
NS = uuid.UUID("6f1d2c3a-5b7e-4e0a-9c1d-a1a1a1a1a1a1")
G = 2.54

DIP14, DIP16, DIP20 = (f"Package_DIP:DIP-{n}_W7.62mm" for n in (14, 16, 20))
DIP28W, DIP32W = "Package_DIP:DIP-28_W15.24mm", "Package_DIP:DIP-32_W15.24mm"
R_FP = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"
C_FP = "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm"
CP_FP = "Capacitor_THT:CP_Radial_D5.0mm_P2.00mm"
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x{:02d}_P2.54mm_Vertical"

KINDS = {   # value -> (library symbol with the same DIP pin-out, footprint)
    "74HC163": ("74xx:74LS163", DIP16), "74AC74": ("74xx:74HC74", DIP14),
    "74HC138": ("74xx:74HC138", DIP16), "74HC574": ("74xx:74HCT574", DIP20),
    "74HC377": ("74xx:74LS377", DIP20), "74HC157": ("74xx:74LS157", DIP16),
    "74HC541": ("74xx:74HCT541", DIP20), "74HC166": ("74xx:74LS166", DIP16),
    "74HC688": ("74xx:74HC688", DIP20), "74HC04": ("74xx:74HC04", DIP14),
    "74HC00": ("74xx:74HC00", DIP14), "74HC10": ("74xx:74LS10", DIP14),
    "74AC08": ("74xx:74LS08", DIP14), "74HCT14": ("74xx:74HC14", DIP14),
    "74HC21": ("74xx:74LS21", DIP14), "74HC175": ("74xx:74LS175", DIP16),
    "74HC109": ("74xx:74LS109", DIP16), "74HC393": ("74xx:74LS393", DIP14),
    "74HCT273": ("74xx:74HCT273", DIP20),
    "AS6C62256-55": ("Memory_RAM:HM62256BLP", DIP28W),
    "SST39SF010A": ("Memory_Flash:SST39SF010", DIP32W),
    "14.31818MHz": ("Oscillator:ACO-xxxMHz-A", "Oscillator:Oscillator_DIP-14"),
}

SHEETS = [  # (file, sheet name, title)
    ("timing.kicad_sch", "Timing", "Clock, dot phase & video timing"),
    ("video.kicad_sch", "Video", "Display RAM, character path & composite output"),
    ("sequencer.kicad_sch", "Sequencer", "PIA interface & control sequencer"),
    ("counters.kicad_sch", "Counters", "Cursor / scroll counters & comparators"),
    ("power.kicad_sch", "Power", "Power & decoupling"),
]

NOTES = {
    1: ["Pin numbers are DIP. Where KiCad has no HC/AC symbol the LS/HCT symbol with the",
        "same pin-out is used; Value is the part to fit.",
        "Every register/counter is clocked by DOTCLK and enabled by CHAR_END or /PH6;",
        "74HC163 /CLR and /LOAD are synchronous.",
        "Timing ROM output is registered (U10): table entries are one char early (roms.py).",
        "J3 pin-out and refresh mapping (CL, H4-H6, V0-V3) must be verified on sheet 2/3."],
    2: ["P2 (U3 Q2) splits each 977.8 ns char period: phases 0-3 video read (mux A,",
        "RAM /OE low, U25 latches at end of PH3); phases 4-6 write slot (mux B, U27 drives",
        "MD when WE, /WE pulses in PH5).",
        "U28: A0-A2 scan line, A3-A9 code, A10 CURSOR, A11 BANK.  DQ7 = leftmost dot.",
        "Check MD bus turnaround (RAM /OE off vs U27 on) at PH3->PH4.",
        "U37 must be 74AC08: R1/R2 need ~15 mA.  J2: choose an RCA jack footprint."],
    3: ["Moore machine: U33/U34 hold next state + controls (seq_lo/hi.bin); U36/U38 load",
        "them at the end of each char period (/E = /PH6).",
        "RDA is a 3-period pulse for the 74123 (B3) on Apple sheet 2/3; polarity in seq_hi.bin.",
        "Two-stage synchronisers: DA via U2B -> U48, CLR via U48 -> U48.",
        "R5/C1 debounce SW1 and clear the screen at power-on.",
        "J1 pin-out and DA/RDA polarity must be verified."],
    4: ["COL/ROW = cursor (physical row).  TOP = physical row shown first.  VROW = row being",
        "displayed: loads TOP at FRAME_START, steps on ROW_CLK.",
        "/CLR and /LOAD are synchronous and gated with CHAR_END; CLR has priority over INC.",
        "Mod-24 wrap: /LOAD with D=0 at count 23.  Scrolling = TOP+1 and clear one line."],
    5: ["One 100 nF ceramic per IC, placed at its VCC pin (see table).  C100 bulk at J1."],
}


# ====================================================================== netlist

PARTS = {}      # ref -> {"value", "lib", "fp", "pins": {num: net}, "unit_sheet": {}, "sheet"}
ORDER = {s: [] for s in range(1, 6)}    # sheet -> [("section", title) | (ref, unit or None)]


def section(sheet, title):
    ORDER[sheet].append(("section", title))


def part(sheet, ref, value, pins, lib=None, fp=None):
    """Add pins of `ref` drawn on `sheet` (several calls per ref may split units)."""
    if lib is None:
        lib, fp2 = KINDS[value]
        fp = fp if fp is not None else fp2
    p = PARTS.setdefault(ref, {"value": value, "lib": lib, "fp": fp, "pins": {}, "pin_sheet": {},
                               "sheet": sheet})
    for num, net in pins.items():
        assert num not in p["pins"], (ref, num)
        p["pins"][num] = net
        p["pin_sheet"][num] = sheet
    ORDER[sheet].append((ref, tuple(sorted(pins))))


def nbar(n):
    return "~{" + n + "}"


def c163(clk, enp, ent, clr, load, d, q, tc):
    p = {1: clr, 2: clk, 7: enp, 9: load, 10: ent, 15: tc}
    p.update(zip((3, 4, 5, 6), d))
    p.update(zip((14, 13, 12, 11), q))
    return p


def c377(d, q, en, clk, first=1):
    p = {first: en, 11: clk}
    p.update(zip((3, 4, 7, 8, 13, 14, 17, 18), d))
    p.update(zip((2, 5, 6, 9, 12, 15, 16, 19), q))
    return p


FLASH_A = {0: 12, 1: 11, 2: 10, 3: 9, 4: 8, 5: 7, 6: 6, 7: 5, 8: 27, 9: 26, 10: 23, 11: 25,
           12: 4, 13: 28, 14: 29, 15: 3, 16: 2}
FLASH_DQ = {0: 13, 1: 14, 2: 15, 3: 17, 4: 18, 5: 19, 6: 20, 7: 21}
RAM_A = {0: 10, 1: 9, 2: 8, 3: 7, 4: 6, 5: 5, 6: 4, 7: 3, 8: 25, 9: 24, 10: 21, 11: 23, 12: 2,
         13: 26, 14: 1}
RAM_DQ = {0: 11, 1: 12, 2: 13, 3: 15, 4: 16, 5: 17, 6: 18, 7: 19}


def cflash(a, dq):
    p = {FLASH_A[i]: n for i, n in enumerate(a)}
    p.update({FLASH_DQ[i]: n for i, n in enumerate(dq)})
    p.update({22: "GND", 24: "GND", 31: "+5V", 1: None, 30: None})   # /CE /OE /WE, NC
    return p


def bits(prefix, n, start=0):
    return [f"{prefix}{i}" for i in range(start, start + n)]


GND4 = ["GND"] * 4
NC = None


def define():
    PARTS.clear()
    for v in ORDER.values():
        v.clear()
    y = [nbar(f"Y{i}") for i in range(7)]

    # ------------------------------------------------------------------ sheet 1
    section(1, "CLOCK & DOT PHASE")
    part(1, "X1", "14.31818MHz", {1: "+5V", 8: "OSC14M"})
    part(1, "U2", "74AC74", {2: nbar("DOTCLK"), 3: "OSC14M", 4: "+5V", 1: "+5V",
                             5: "DOTCLK", 6: nbar("DOTCLK")})
    part(1, "U3", "74HC163", c163("DOTCLK", "+5V", "+5V", y[6], "+5V", GND4,
                                  ["P0", "P1", "P2", NC], NC))
    part(1, "U11", "74HC138", {1: "P0", 2: "P1", 3: "P2", 6: "+5V", 4: "GND", 5: "GND",
                               15: y[0], 14: y[1], 13: y[2], 12: y[3], 11: y[4], 10: y[5],
                               9: y[6], 7: NC})
    u12 = {1: "GND", 11: "DOTCLK", 9: "GND"}
    u12.update(zip(range(2, 9), y))
    u12.update(zip(range(19, 11, -1), [NC, NC, nbar("PH3"), NC, nbar("PH5"), nbar("PH6"), NC, NC]))
    part(1, "U12", "74HC574", u12)
    part(1, "U45", "74HC04", {1: nbar("PH6"), 2: "CHAR_END"})
    part(1, "U45", "74HC04", {3: nbar("PH5"), 4: "PH5"})
    part(1, "J3", "Conn_01x10", {1: "P2", 2: "P0", 3: "H4", 4: "H5", 5: "H6", 6: "V0", 7: "V1",
                                 8: "V2", 9: "V3", 10: "GND"},
         lib="Connector_Generic:Conn_01x10", fp=HDR.format(10))

    section(1, "VIDEO TIMING")
    hclr, vclr = nbar("HCLR"), nbar("VCLR")
    part(1, "U4", "74HC163", c163("DOTCLK", "CHAR_END", "CHAR_END", hclr, "+5V", GND4,
                                  bits("H", 4), "H_TC"))
    part(1, "U5", "74HC163", c163("DOTCLK", "CHAR_END", "H_TC", hclr, "+5V", GND4,
                                  ["H4", "H5", "H6", NC], NC))
    part(1, "U6", "74HC163", c163("DOTCLK", "H_END", "CHAR_END", vclr, "+5V", GND4,
                                  bits("V", 4), "V_TC1"))
    part(1, "U7", "74HC163", c163("DOTCLK", "H_END", "V_TC1", vclr, "+5V", GND4,
                                  bits("V", 4, 4), "V_TC2"))
    part(1, "U8", "74HC163", c163("DOTCLK", "H_END", "V_TC2", vclr, "+5V", GND4,
                                  ["V8", NC, NC, NC], NC))
    part(1, "U49", "74HC10", {1: "H_END", 2: "CHAR_END", 13: "+5V", 12: hclr})
    part(1, "U49", "74HC10", {3: "V_END", 4: "H_END", 5: "CHAR_END", 6: vclr})
    tq = bits("TROM_D", 6)
    part(1, "U9", "SST39SF010A", cflash(bits("H", 7) + bits("V", 9) + ["GND"], tq + [NC, NC]))
    part(1, "U10", "74HC377", c377(tq + ["GND", "GND"],
                                   [nbar("CSYNC"), nbar("BLANK"), "H_END", "V_END", "ROW_CLK",
                                    "FRAME_START", NC, NC], nbar("PH6"), "DOTCLK"))
    part(1, "U35", "74HC393", {1: "V_END", 2: "GND", 3: NC, 4: NC, 5: NC, 6: "FRM_Q3"})
    part(1, "U35", "74HC393", {13: "FRM_Q3", 12: "GND", 11: "BLINK", 10: NC, 9: NC, 8: NC})

    # ------------------------------------------------------------------ sheet 2
    section(2, "RAM ADDRESS MUX")
    vid = ["H0", "H1", "H2", "H3", "H4", "H5", "VR0", "VR1", "VR2", "VR3", "VR4", "GND"]
    cur = ["C0", "C1", "C2", "C3", "C4", "C5", "R0", "R1", "R2", "R3", "R4", "GND"]
    ma = bits("MA", 11) + [NC]
    for k in range(3):
        p = {1: "P2", 15: "GND"}
        for sec, (a, b, yy) in enumerate(((2, 3, 4), (5, 6, 7), (11, 10, 9), (14, 13, 12))):
            i = k * 4 + sec
            p.update({a: vid[i], b: cur[i], yy: ma[i]})
        part(2, f"U{21 + k}", "74HC157", p)

    section(2, "DISPLAY RAM & WRITE PATH")
    md = bits("MD", 8)
    ram = {RAM_A[i]: n for i, n in enumerate(bits("MA", 11) + GND4)}
    ram.update({RAM_DQ[i]: n for i, n in enumerate(md)})
    ram.update({22: "P2", 27: nbar("WE_RAM"), 20: "GND"})
    part(2, "U24", "AS6C62256-55", ram)
    part(2, "U44", "74HC00", {1: "PH5", 2: "WE", 3: nbar("WE_RAM")})
    part(2, "U44", "74HC00", {4: "P2", 5: "WE", 6: nbar("WBUF")})
    u27 = {1: nbar("WBUF"), 19: "GND"}
    u27.update(zip(range(2, 10), bits("LD", 7) + ["GND"]))
    u27.update(zip(range(18, 10, -1), md))
    part(2, "U27", "74HC541", u27)

    section(2, "CHARACTER PATH")
    vc = bits("VC", 7)
    part(2, "U25", "74HC377", c377(md[:7] + ["CURMATCH"], vc + ["CURQ"], nbar("PH3"), "DOTCLK"))
    part(2, "U37", "74AC08", {9: "CURQ", 10: "BLINK", 8: "CURSOR"})
    cg = bits("CG_D", 8)
    part(2, "U28", "SST39SF010A", cflash(["V0", "V1", "V2"] + vc + ["CURSOR", "BANK"] + ["GND"] * 5, cg))
    part(2, "JP2", "BANK", {1: "BANK", 2: "+5V"}, lib="Jumper:Jumper_2_Open", fp=HDR.format(2))
    part(2, "R4", "10k", {1: "BANK", 2: "GND"}, lib="Device:R", fp=R_FP)
    u29 = {15: nbar("PH6"), 7: "DOTCLK", 6: "GND", 1: "GND", 9: "+5V", 13: "DOTS"}
    u29.update(zip((2, 3, 4, 5, 10, 11, 12, 14), cg))
    part(2, "U29", "74HC166", u29)

    section(2, "COMPOSITE VIDEO OUT")
    part(2, "U37", "74AC08", {1: "DOTS", 2: nbar("BLANK"), 3: "VID"})
    part(2, "U37", "74AC08", {4: nbar("CSYNC"), 5: "+5V", 6: "CSYNC_OUT"})
    part(2, "R2", "270", {1: "VID", 2: "COMPOSITE"}, lib="Device:R", fp=R_FP)
    part(2, "R1", "620", {1: "CSYNC_OUT", 2: "COMPOSITE"}, lib="Device:R", fp=R_FP)
    part(2, "R3", "120", {1: "COMPOSITE", 2: "GND"}, lib="Device:R", fp=R_FP)
    part(2, "J2", "RCA composite", {1: "COMPOSITE", 2: "GND"}, lib="Connector:Conn_Coaxial", fp="")

    # ------------------------------------------------------------------ sheet 3
    section(3, "PIA INTERFACE & INPUT LATCH")
    rd = bits("RD", 7, 1)
    j1 = dict(zip(range(1, 8), rd))
    j1.update({8: "RDA", 9: "DA", 10: "+5V", 11: "GND"})
    part(3, "J1", "Conn_01x11", j1, lib="Connector_Generic:Conn_01x11", fp=HDR.format(11))
    part(3, "U26", "74HCT273", c377(rd + ["GND"], bits("LD", 7) + [NC], nbar("LATCH_CLR"), "LATCH_LD"))
    part(3, "U45", "74HC04", {5: "LATCH_CLR", 6: nbar("LATCH_CLR")})

    section(3, "DA / CLR SYNCHRONISERS")
    part(3, "U39", "74HCT14", {1: "DA", 2: nbar("DA")})
    part(3, "U39", "74HCT14", {3: nbar("DA"), 4: "DA_BUF"})
    part(3, "U2", "74AC74", {12: "DA_BUF", 11: "DOTCLK", 10: "+5V", 13: "+5V", 9: "DA_S1", 8: NC})
    part(3, "U39", "74HCT14", {5: nbar("CLR_SW"), 6: "CLR_BUF"})
    part(3, "SW1", "CLR", {1: nbar("CLR_SW"), 2: "GND"}, lib="Switch:SW_Push",
         fp="Button_Switch_THT:SW_PUSH_6mm")
    part(3, "R5", "10k", {1: "+5V", 2: nbar("CLR_SW")}, lib="Device:R", fp=R_FP)
    part(3, "C1", "1uF", {1: nbar("CLR_SW"), 2: "GND"}, lib="Device:C", fp=C_FP)
    part(3, "U48", "74HC175", {4: "DA_S1", 5: "CLR_BUF", 12: "CLR_S1", 13: "GND", 9: "DOTCLK",
                               1: "+5V", 2: "DA_S2", 7: "CLR_S1", 10: "CLR_S2",
                               3: NC, 6: NC, 11: NC, 15: NC, 14: NC})
    part(3, "U39", "74HCT14", {9: "GND", 8: NC})
    part(3, "U39", "74HCT14", {11: "GND", 10: NC})
    part(3, "U39", "74HCT14", {13: "GND", 12: NC})

    section(3, "CONTROL SEQUENCER")
    sa = (bits("S", 5) + ["DA_S2", "CLR_S2", "COL39", "ROWEQTOP", "READY"] + bits("LD", 7))
    lo, hi = bits("SEQ_LO", 8), bits("SEQ_HI", 8)
    part(3, "U33", "SST39SF010A", cflash(sa, lo))
    part(3, "U34", "SST39SF010A", cflash(sa, hi))
    part(3, "U36", "74HC377", c377(lo, bits("S", 5) + ["WE", "COL_INC", "COL_CLR"],
                                   nbar("PH6"), "DOTCLK"))
    part(3, "U38", "74HC377", c377(hi, ["ROW_INC", "ROW_CLR", "TOP_INC", "TOP_CLR", "LATCH_LD",
                                        "LATCH_CLR", "RDA", "FS_CLR"], nbar("PH6"), "DOTCLK"))

    section(3, "SLOW-MODE FRAME FLAG")
    part(3, "U37", "74AC08", {12: "FRAME_START", 13: "CHAR_END", 11: "J_FS"})
    part(3, "U44", "74HC00", {12: "FS_CLR", 13: "CHAR_END", 11: nbar("K_FS")})
    part(3, "U47", "74HC109", {2: "J_FS", 3: nbar("K_FS"), 4: "DOTCLK", 5: "+5V", 1: "+5V",
                               6: NC, 7: nbar("FS")})
    part(3, "U47", "74HC109", {14: "GND", 13: "GND", 12: "GND", 11: "+5V", 15: "+5V", 10: NC, 9: NC})
    part(3, "U44", "74HC00", {10: nbar("FS"), 9: "SLOW", 8: "READY"})
    part(3, "R6", "10k", {1: "SLOW", 2: "GND"}, lib="Device:R", fp=R_FP)
    part(3, "JP1", "SLOW", {1: "SLOW", 2: "+5V"}, lib="Jumper:Jumper_2_Open", fp=HDR.format(2))

    # ------------------------------------------------------------------ sheet 4
    pairs = [("COL (cursor column 0-39)", "U17", "U18", bits("C", 6), "COL_INC",
              ("U49", {9: "COL_CLR", 10: "CHAR_END", 11: "+5V", 8: nbar("COLCLR")}), None, None),
             ("ROW (cursor row, mod 24)", "U19", "U20", bits("R", 5), "ROW_INC",
              ("U50", {1: "ROW_CLR", 2: "CHAR_END", 13: "+5V", 12: nbar("ROWCLR")}),
              ("U50", {3: "ROW_INC", 4: "ROW23", 5: "CHAR_END", 6: nbar("ROWLD")}), None),
             ("TOP (first displayed row, mod 24)", "U15", "U16", bits("T", 5), "TOP_INC",
              ("U50", {9: "TOP_CLR", 10: "CHAR_END", 11: "+5V", 8: nbar("TOPCLR")}),
              ("U51", {1: "TOP_INC", 2: "TOP23", 13: "CHAR_END", 12: nbar("TOPLD")}), None),
             ("VROW (video row, loads TOP)", "U13", "U14", bits("VR", 5), "ROW_CLK",
              ("U51", {3: "ROW_CLK", 4: "VR23", 5: "CHAR_END", 6: nbar("VRCLR")}),
              ("U51", {9: "FRAME_START", 10: "CHAR_END", 11: "+5V", 8: nbar("VRLD")}), bits("T", 5))]
    section(4, "COL (cursor column 0-39) · ROW (cursor row) · TOP (first displayed row) · "
               "VROW (video row, loads TOP)")
    for title, rlo, rhi, q, enp, clr, ld, d in pairs:
        clrn = [v for k, v in clr[1].items() if k in (8, 12, 6)][0]
        ldn = [v for k, v in ld[1].items() if k in (8, 12, 6)][0] if ld else "+5V"
        dlo, dhi = (d[:4], [d[4], "GND", "GND", "GND"]) if d else (GND4, GND4)
        qhi = (q[4:] + [NC] * 4)[:4]
        tc = f"{q[0][:-1]}_TC"
        part(4, rlo, "74HC163", c163("DOTCLK", enp, "CHAR_END", clrn, ldn, dlo, q[:4], tc))
        part(4, rhi, "74HC163", c163("DOTCLK", enp, tc, clrn, ldn, dhi, qhi, NC))
        part(4, clr[0], "74HC10", clr[1])
        if ld:
            part(4, ld[0], "74HC10", ld[1])

    section(4, "WRAP DETECTORS")
    for ref, pins, ins, out in (("U40", (1, 2, 4, 5, 6), ["C0", "C1", "C2", "C5"], "COL39"),
                                ("U40", (9, 10, 12, 13, 8), ["R0", "R1", "R2", "R4"], "ROW23"),
                                ("U41", (1, 2, 4, 5, 6), ["T0", "T1", "T2", "T4"], "TOP23"),
                                ("U41", (9, 10, 12, 13, 8), ["VR0", "VR1", "VR2", "VR4"], "VR23")):
        part(4, ref, "74HC21", dict(zip(pins, ins + [out])))

    section(4, "CURSOR MATCH & ROW == TOP")
    P688, Q688 = (2, 4, 6, 8, 11, 13, 15, 17), (3, 5, 7, 9, 12, 14, 16, 18)

    def c688(p, q, g, out):
        d = {1: g, 19: out}
        d.update(zip(P688, (p + ["GND"] * 8)[:8]))
        d.update(zip(Q688, (q + ["GND"] * 8)[:8]))
        return d
    part(4, "U30", "74HC688", c688(bits("H", 6) + ["VR0", "VR1"], bits("C", 6) + ["R0", "R1"],
                                   "GND", nbar("EQ1")))
    part(4, "U31", "74HC688", c688(["VR2", "VR3", "VR4"], ["R2", "R3", "R4"], nbar("EQ1"),
                                   nbar("CURMATCH")))
    part(4, "U45", "74HC04", {9: nbar("CURMATCH"), 8: "CURMATCH"})
    part(4, "U32", "74HC688", c688(bits("R", 5), bits("T", 5), "GND", nbar("ROWEQTOP")))
    part(4, "U45", "74HC04", {11: nbar("ROWEQTOP"), 10: "ROWEQTOP"})
    part(4, "U45", "74HC04", {13: "GND", 12: NC})

    # ------------------------------------------------------------------ sheet 5
    section(5, "BULK & DECOUPLING")
    part(5, "C100", "10uF", {1: "+5V", 2: "GND"}, lib="Device:C_Polarized", fp=CP_FP)
    ics = sorted((r for r in PARTS if r[0] in "UX"), key=lambda r: (r[0], int(r[1:])))
    for i, ref in enumerate(ics):
        part(5, f"C{101 + i}", "100nF", {1: "+5V", 2: "GND"}, lib="Device:C", fp=C_FP)
        PARTS[f"C{101 + i}"]["decouples"] = ref


# ====================================================================== s-expressions

TOK = re.compile(r'"(?:[^"\\]|\\.)*"|[()]|[^\s()"]+')


def parse(text):
    stack = [[]]
    for t in TOK.findall(text):
        if t == "(":
            stack.append([])
        elif t == ")":
            x = stack.pop()
            stack[-1].append(x)
        else:
            stack[-1].append(t)
    return stack[0]


def q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def unq(t):
    return t[1:-1].replace('\\"', '"').replace("\\\\", "\\") if t.startswith('"') else t


def dump(node, ind=0):
    if not isinstance(node, list):
        return node
    if all(not isinstance(x, list) for x in node):
        return "(" + " ".join(node) + ")"
    pad = "\t" * (ind + 1)
    head = [x for x in node if not isinstance(x, list)]
    out = "(" + " ".join(head)
    for x in node:
        if isinstance(x, list):
            out += "\n" + pad + dump(x, ind + 1)
    return out + "\n" + "\t" * ind + ")"


def find(node, key):
    return [x for x in node if isinstance(x, list) and x and x[0] == key]


def first(node, key):
    r = find(node, key)
    return r[0] if r else None


def fmt(v):
    v = round(v, 4)
    return str(int(v)) if v == int(v) else f"{v:.4f}".rstrip("0")


# ====================================================================== library

_libs = {}


def lib_symbol(lib_id):
    """Flattened library symbol node renamed to lib_id (as embedded in a schematic)."""
    lib, name = lib_id.split(":")
    if lib not in _libs:
        tree = parse(open(os.path.join(SYMDIR, lib + ".kicad_sym")).read())[0]
        _libs[lib] = {unq(e[1]): e for e in find(tree, "symbol")}
    syms = _libs[lib]
    sym = syms[name]
    ext = first(sym, "extends")
    if not ext:
        node = [x for x in sym]
    else:
        parent = syms[unq(ext[1])]
        pname = unq(ext[1])
        own = {unq(x[1]): x for x in find(sym, "property")}
        props = [own.pop(unq(x[1]), x) for x in find(parent, "property")] + list(own.values())
        node = []
        for x in parent:
            if isinstance(x, list) and x[0] == "property":
                continue
            if isinstance(x, list) and x[0] == "symbol":
                x = [x[0], q(unq(x[1]).replace(pname, name, 1))] + x[2:]
            node.append(x)
        idx = next(i for i, x in enumerate(node) if isinstance(x, list) and x[0] == "symbol")
        node[idx:idx] = props
    node = [node[0], q(lib_id)] + node[2:]
    return node


class Geo:
    """Pins and bounding box of one unit of a library symbol (library coords, y up)."""

    def __init__(self, sym, unit):
        self.pins = {}
        xs, ys = [], []
        for sub in find(sym, "symbol"):
            m = re.match(r".*_(\d+)_(\d+)$", unq(sub[1]))
            u, style = int(m.group(1)), int(m.group(2))
            if u not in (0, unit) or style not in (0, 1):
                continue
            for g in sub[2:]:
                if not isinstance(g, list):
                    continue
                if g[0] == "pin":
                    at = first(g, "at")
                    x, y, a = float(at[1]), float(at[2]), int(float(at[3]))
                    num = unq(first(g, "number")[1])
                    self.pins[num] = (x, y, a, g[1], unq(first(g, "name")[1]))
                    ln = float(first(g, "length")[1])
                    dx, dy = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[a]
                    xs += [x, x + dx * ln]
                    ys += [y, y + dy * ln]
                elif g[0] in ("rectangle", "arc", "polyline", "circle", "bezier"):
                    for k in ("start", "end", "mid", "center"):
                        p = first(g, k)
                        if p:
                            xs.append(float(p[1]))
                            ys.append(float(p[2]))
                    pts = first(g, "pts")
                    for p in (pts[1:] if pts else []):
                        xs.append(float(p[1]))
                        ys.append(float(p[2]))
                    c, r = first(g, "center"), first(g, "radius")
                    if c and r:
                        xs += [float(c[1]) - float(r[1]), float(c[1]) + float(r[1])]
                        ys += [float(c[2]) - float(r[1]), float(c[2]) + float(r[1])]
        self.box = (min(xs), min(ys), max(xs), max(ys))


def units_of(sym):
    """{pin number: unit} for body style 1 (unit 0 = common to all)."""
    out = {}
    for sub in find(sym, "symbol"):
        m = re.match(r".*_(\d+)_(\d+)$", unq(sub[1]))
        if int(m.group(2)) not in (0, 1):
            continue
        for g in find(sub, "pin"):
            out[unq(first(g, "number")[1])] = int(m.group(1))
    return out


# ====================================================================== netlist resolution

def resolve():
    """Fill power pins, assign every pin to a (unit, sheet) and return placed units."""
    placed = {}     # (ref, unit) -> sheet
    for ref, p in PARTS.items():
        sym = lib_symbol(p["lib"])
        p["sym"] = sym
        umap = units_of(sym)
        p["umap"] = umap
        nunits = max(umap.values())
        types = {}
        for u in set(umap.values()) | {1}:
            types.update({n: (v[3], v[4]) for n, v in Geo(sym, max(u, 1)).pins.items()})
        p["types"] = types
        given = {str(k): v for k, v in p["pins"].items()}
        sheets = {str(k): v for k, v in p["pin_sheet"].items()}
        for num, u in umap.items():
            if num in given:
                continue
            typ, name = types[num]
            if typ == "power_in":
                given[num] = "GND" if name.upper() == "GND" else "+5V"
                same = [n for n, uu in umap.items() if uu == u and n in sheets]
                sheets[num] = sheets[same[0]] if same else p["sheet"]
            elif typ in ("output", "tri_state") or name == "NC":
                raise ValueError(f"{ref} pin {num} ({name}) unspecified: use None for no-connect")
            else:
                raise ValueError(f"{ref} pin {num} ({name}, {typ}) left floating")
        extra = set(given) - set(umap)
        assert not extra, (ref, extra)
        p["net"] = given
        p["sheet_of"] = sheets
        for num, u in umap.items():
            uu = u if u else 1
            s = sheets[num]
            if placed.setdefault((ref, uu), s) != s:
                raise ValueError(f"{ref} unit {uu} split across sheets")
        for u in range(1, nunits + 1):
            if (ref, u) not in placed:
                raise ValueError(f"{ref} unit {u} not placed")
    return placed


def net_sheets():
    out = {}
    for ref, p in PARTS.items():
        for num, net in p["net"].items():
            if net:
                out.setdefault(net, set()).add(p["sheet_of"][num])
    return out


def expected_nets():
    nets = {}
    for ref, p in PARTS.items():
        for num, net in p["net"].items():
            if net:
                nets.setdefault(net, set()).add((ref, num))
    return nets


# ====================================================================== schematic writer

def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(x) for x in parts)))


def eff(size=1.27, justify=None, hide=False, bold=False):
    f = ["font", ["size", fmt(size), fmt(size)]]
    if bold:
        f.append(["bold", "yes"])
    e = ["effects", f]
    if justify:
        e.append(["justify"] + justify.split())
    if hide:
        e.append(["hide", "yes"])
    return e


def text_len(s, size=1.27):
    return len(re.sub(r"[~{}]", "", s)) * size * 0.95


PAPERS = [("A3", 420, 297), ("A2", 594, 420), ("A1", 841, 594), ("A0", 1189, 841)]
OUT_DIR = {0: (1, 0), 90: (0, -1), 180: (-1, 0), 270: (0, 1)}    # schematic dx, dy (y down)


class Sheet:
    def __init__(self, number, root_uuid, sheet_uuid):
        self.n = number
        self.file, self.name, self.title = SHEETS[number - 1]
        self.uuid = uid("sheetfile", number)
        self.path = f"/{root_uuid}/{sheet_uuid}"
        self.items = []
        self.lib_ids = set()
        self.pwr = 0

    def add(self, node):
        self.items.append(node)

    def wire(self, a, b):
        self.add(["wire", ["pts", ["xy", fmt(a[0]), fmt(a[1])], ["xy", fmt(b[0]), fmt(b[1])]],
                  ["stroke", ["width", "0"], ["type", "default"]], ["uuid", q(uid(self.n, "w", a, b))]])

    def text(self, x, y, s, size=1.27, bold=False):
        self.add(["text", q(s), ["exclude_from_sim", "no"], ["at", fmt(x), fmt(y), "0"],
                  eff(size, "left bottom", bold=bold), ["uuid", q(uid(self.n, "t", x, y, s))]])

    def label(self, p, name, ang, glob, shape="input"):
        just = "left" if ang in (0, 90) else "right"
        if glob:
            self.add(["global_label", q(name), ["shape", shape],
                      ["at", fmt(p[0]), fmt(p[1]), str(ang)], ["fields_autoplaced", "yes"],
                      eff(1.27, just), ["uuid", q(uid(self.n, "gl", p, name))],
                      ["property", q("Intersheetrefs"), q("${INTERSHEET_REFS}"),
                       ["at", fmt(p[0]), fmt(p[1]), "0"], eff(1.27, just, hide=True)]])
        else:
            self.add(["label", q(name), ["at", fmt(p[0]), fmt(p[1]), str(ang)],
                      ["fields_autoplaced", "yes"], eff(1.27, just + " bottom"),
                      ["uuid", q(uid(self.n, "l", p, name))]])

    def junction(self, p):
        self.add(["junction", ["at", fmt(p[0]), fmt(p[1])], ["diameter", "0"],
                  ["color", "0", "0", "0", "0"], ["uuid", q(uid(self.n, "j", p))]])

    def noconn(self, p):
        self.add(["no_connect", ["at", fmt(p[0]), fmt(p[1])], ["uuid", q(uid(self.n, "nc", p))]])

    def power(self, p, net, outward, project):
        """+5V / GND symbol whose pin sits at p, body pointing `outward`."""
        self.pwr += 1
        lib_id = "power:" + net
        self.lib_ids.add(lib_id)
        rot = {"+5V": {(0, -1): 0, (-1, 0): 90, (0, 1): 180, (1, 0): 270},
               "GND": {(0, 1): 0, (1, 0): 90, (0, -1): 180, (-1, 0): 270},
               "PWR_FLAG": {(0, -1): 0, (-1, 0): 90, (0, 1): 180, (1, 0): 270}}[net][outward]
        ref = f"#{'FLG' if net == 'PWR_FLAG' else 'PWR'}{self.n}{self.pwr:03d}"
        dx, dy = outward
        vp = (p[0] + dx * 5, p[1] + dy * 5)
        self.add(["symbol", ["lib_id", q(lib_id)], ["at", fmt(p[0]), fmt(p[1]), str(rot)],
                  ["unit", "1"], ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
                  ["dnp", "no"], ["uuid", q(uid(self.n, "pwr", ref))],
                  ["property", q("Reference"), q(ref), ["at", fmt(p[0]), fmt(p[1]), "0"],
                   eff(hide=True)],
                  ["property", q("Value"), q(net), ["at", fmt(vp[0]), fmt(vp[1]), "0"],
                   eff(1.0, hide=net == "PWR_FLAG")],
                  ["property", q("Footprint"), q(""), ["at", fmt(p[0]), fmt(p[1]), "0"], eff(hide=True)],
                  ["property", q("Datasheet"), q(""), ["at", fmt(p[0]), fmt(p[1]), "0"], eff(hide=True)],
                  ["pin", q("1"), ["uuid", q(uid(self.n, "pwrpin", ref))]],
                  ["instances", ["project", q(project), ["path", q(self.path), ["reference", q(ref)],
                                                         ["unit", "1"]]]]])

    def body(self, ref, unit, p, x, y, project):
        lib_id = p["lib"]
        self.lib_ids.add(lib_id)
        sym = p["sym"]
        node = ["symbol", ["lib_id", q(lib_id)], ["at", fmt(x), fmt(y), "0"], ["unit", str(unit)],
                ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
                ["uuid", q(uid("sym", ref, unit))]]
        vals = {"Reference": ref, "Value": p["value"], "Footprint": p["fp"], "Datasheet": "",
                "Description": f"Decoupling for {p['decouples']}" if "decouples" in p else ""}
        for prop in find(sym, "property"):
            key = unq(prop[1])
            if key not in vals:
                continue
            at = first(prop, "at")
            e = first(prop, "effects")
            hide = any(isinstance(h, list) and h[0] == "hide" and h[1] == "yes" for h in e) or \
                "hide" in e
            node.append(["property", q(key), q(vals[key]),
                         ["at", fmt(x + float(at[1])), fmt(y - float(at[2])), at[3] if len(at) > 3 else "0"],
                         eff(1.27, None, hide=hide or key in ("Footprint", "Datasheet", "Description"))])
        for num, u in p["umap"].items():
            if u in (0, unit):
                node.append(["pin", q(num), ["uuid", q(uid("pin", ref, num))]])
        node.append(["instances", ["project", q(project),
                                   ["path", q(self.path), ["reference", q(ref)], ["unit", str(unit)]]]])
        self.add(node)

    def write(self, outdir, paper, project):
        libs = [lib_symbol(l) for l in sorted(self.lib_ids)]
        tree = ["kicad_sch", ["version", "20250114"], ["generator", q("eeschema")],
                ["generator_version", q("9.0")], ["uuid", q(self.uuid)], ["paper", q(paper)],
                title_block(self.title),
                ["lib_symbols"] + libs] + self.items + [["embedded_fonts", "no"]]
        with open(os.path.join(outdir, self.file), "w") as f:
            f.write(dump(tree) + "\n")


def title_block(title):
    return ["title_block", ["title", q(title)], ["date", q("2026-10-29")], ["rev", q("0.1")],
            ["company", q("Apple-1 terminal redesign (a1video)")],
            ["comment", "1", q("Generated by python3 -m a1video.kicad -- edit the netlist there")],
            ["comment", "2", q("Pin numbers DIP; verify against datasheets before layout")]]


def unit_extents(p, unit, nets_glob):
    """Box (x0, y0, x1, y1) in schematic coords relative to the symbol origin, labels included."""
    g = Geo(p["sym"], unit)
    x0, y0, x1, y1 = g.box[0], -g.box[3], g.box[2], -g.box[1]
    for num, (px, py, a, typ, _) in g.pins.items():
        if p["umap"].get(num) not in (0, unit):
            continue
        net = p["net"][num]
        dx, dy = OUT_DIR[(a + 180) % 360]
        sx, sy = px, -py
        if net is None:
            reach = 1
        elif net in ("+5V", "GND"):
            reach = 2 * G + 6
        else:
            reach = G + text_len(net) + (4 if nets_glob.get(net) else 1)
        ex, ey = sx + dx * reach, sy + dy * reach
        x0, x1, y0, y1 = min(x0, ex), max(x1, ex), min(y0, ey - 1.5), max(y1, ey + 1.5)
    return x0 - 2, y0 - 4, x1 + 2, y1 + 4


def layout(sheet_no, placed, nets_glob):
    """Shelf-pack the sheet's units in ORDER; returns (paper, [(ref, unit, x, y)], headings)."""
    seq = []
    seen = set()
    for item in ORDER[sheet_no]:
        if item[0] == "section":
            seq.append(item)
            continue
        ref, pins = item
        p = PARTS[ref]
        units = sorted({p["umap"][str(n)] or 1 for n in pins})
        for u in units:
            if (ref, u) not in seen:
                seen.add((ref, u))
                seq.append((ref, u))
    # power units (and any remaining unit) of parts that start on this sheet
    for (ref, u), s in sorted(placed.items(), key=lambda k: (k[0][0][0], int(re.sub(r"\D", "", k[0][0])), k[0][1])):
        if s == sheet_no and (ref, u) not in seen:
            seq.append((ref, u))
            seen.add((ref, u))
    ext = {k: unit_extents(PARTS[k[0]], k[1], nets_glob) for k in seq if k[0] != "section"}
    notes = NOTES.get(sheet_no, [])
    for paper, pw, ph in PAPERS:
        for inline in (False, True):    # inline: sections share rows, each row has a heading band
            r = pack(seq, ext, notes, pw, ph, inline)
            if r:
                return (paper,) + r
    raise RuntimeError(f"sheet {sheet_no} does not fit on A0")


def pack(seq, ext, notes, pw, ph, inline):
    left, top = 20.32, 30.48 + 3.2 * len(notes)
    right, bottom = pw - 15, ph - 15
    band = 8 if inline else 0
    x, y, row_h = left, top, 0
    out, heads, pending = [], [], None
    for k in seq:
        if k[0] == "section":
            if inline:
                pending = k[1]
                if x > left:
                    x += 10
            else:
                if x > left:
                    y += row_h + 8
                heads.append((left, y + 4, k[1]))
                x, row_h = left, 0
                y += 8
            continue
        bx0, by0, bx1, by1 = ext[k]
        w, h = bx1 - bx0, by1 - by0
        lim = right if y + band + h < ph - 42 else pw - 125     # keep clear of the title block
        if x + w > lim and x > left:
            x, y, row_h = left, y + row_h + band + 4, 0
        if pending:
            heads.append((x, y + 5, pending))
            pending = None
        ox = round((x - bx0) / G) * G
        oy = round((y + band - by0) / G) * G
        out.append((k[0], k[1], ox, oy))
        x += w + 5
        row_h = max(row_h, h + G)
    if y + band + row_h <= bottom:
        return out, heads
    return None


def draw_unit(sh, ref, unit, x, y, nets_glob, project):
    p = PARTS[ref]
    sh.body(ref, unit, p, x, y, project)
    g = Geo(p["sym"], unit)
    pins = [(num, v) for num, v in g.pins.items() if p["umap"].get(num) in (0, unit)]
    # side pins tied to the same rail at adjacent positions share one trunk and one symbol
    rail_runs = {}
    for num, (px, py, a, typ, _) in pins:
        net = p["net"][num]
        if net in ("+5V", "GND") and a in (0, 180):
            rail_runs.setdefault((a, px), []).append((-py, num, net))
    lead = {}
    for (a, px), run in rail_runs.items():
        run.sort()
        group = [run[0]]
        for item in run[1:] + [None]:
            if item and item[2] == group[-1][2] and abs(item[0] - group[-1][0] - G) < 0.01:
                group.append(item)
                continue
            for _, num, _ in group:
                lead[num] = group[0][1]
            if len(group) > 1:
                xs = x + px + (G if a == 180 else -G)
                for (ya, _, _), (yb, _, _) in zip(group, group[1:]):
                    sh.wire((xs, y + ya), (xs, y + yb))
                for yy, _, _ in group[1:-1]:
                    sh.junction((xs, y + yy))
            group = [item]
    for num, (px, py, a, typ, _) in pins:
        net = p["net"][num]
        cp = (x + px, y - py)
        out = OUT_DIR[(a + 180) % 360]
        if net is None:
            sh.noconn(cp)
            continue
        end = (cp[0] + out[0] * G, cp[1] + out[1] * G)
        sh.wire(cp, end)
        if net in ("+5V", "GND"):
            if lead.get(num, num) != num:
                continue
            if num in lead:
                far = (end[0] + out[0] * G, end[1])
                sh.wire(end, far)
                end = far
            sh.power(end, net, out, project)
        else:
            ang = {(1, 0): 0, (-1, 0): 180, (0, -1): 90, (0, 1): 270}[out]
            shape = "output" if typ in ("output", "tri_state", "power_out") else \
                "passive" if typ == "passive" else "input"
            sh.label(end, net, ang, nets_glob.get(net, False), shape)


def write_project(outdir):
    define()
    placed = resolve()
    ns = net_sheets()
    nets_glob = {n: len(s) > 1 for n, s in ns.items()}
    os.makedirs(outdir, exist_ok=True)
    root_uuid = uid("root")
    sheet_uuids = [uid("sheetsym", i) for i in range(1, 6)]
    papers = {}
    for i in range(1, 6):
        sh = Sheet(i, root_uuid, sheet_uuids[i - 1])
        paper, pos, heads = layout(i, placed, nets_glob)
        papers[i] = paper
        sh.text(20.32, 22, SHEETS[i - 1][2].upper(), size=3.5, bold=True)
        for k, line in enumerate(NOTES.get(i, [])):
            sh.text(20.32, 30.48 + 3.2 * k, line, size=1.6)
        for hx, hy, title in heads:
            sh.text(hx, hy, title, size=2.5, bold=True)
        for ref, unit, x, y in pos:
            draw_unit(sh, ref, unit, x, y, nets_glob, PROJECT)
        if i == 5:
            add_power_flags(sh, PROJECT)
            add_decoupling_table(sh)
        sh.write(outdir, paper, PROJECT)
    write_root(outdir, root_uuid, sheet_uuids)
    write_pro(outdir)
    write_lib_tables(outdir)
    return papers


def add_power_flags(sh, project):
    x, y = 30.48, 60.96
    for k, net in enumerate(("+5V", "GND")):
        p = (x + k * 20.32, y)
        sh.power(p, net, (0, -1) if net == "+5V" else (0, 1), project)
        sh.power(p, "PWR_FLAG", (0, 1) if net == "+5V" else (0, -1), project)
    sh.text(x - 10, y - 14, "PWR_FLAG: +5V and GND enter on J1", size=1.27)


def add_decoupling_table(sh):
    caps = sorted((r for r in PARTS if "decouples" in PARTS[r]), key=lambda r: int(r[1:]))
    cols = 6
    y0 = 300.0
    for k, r in enumerate(caps):
        sh.text(20.32 + (k % cols) * 30, y0 + (k // cols) * 3.2, f"{r} -> {PARTS[r]['decouples']}", 1.4)


def write_root(outdir, root_uuid, sheet_uuids):
    items = []
    for i, (fname, name, title) in enumerate(SHEETS):
        x, y, w, h = 30.48 + (i % 3) * 88.9, 50.8 + (i // 3) * 63.5, 66.04, 38.1
        items.append(["sheet", ["at", fmt(x), fmt(y)], ["size", fmt(w), fmt(h)],
                      ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
                      ["fields_autoplaced", "yes"],
                      ["stroke", ["width", "0.1524"], ["type", "solid"]],
                      ["fill", ["color", "0", "0", "0", "0.0000"]], ["uuid", q(sheet_uuids[i])],
                      ["property", q("Sheetname"), q(name), ["at", fmt(x), fmt(y - 0.7), "0"],
                       eff(1.524, "left bottom")],
                      ["property", q("Sheetfile"), q(fname), ["at", fmt(x), fmt(y + h + 0.6), "0"],
                       eff(1.27, "left top")],
                      ["instances", ["project", q(PROJECT),
                                     ["path", q("/" + root_uuid), ["page", q(str(i + 2))]]]]])
        items.append(["text", q(title), ["exclude_from_sim", "no"],
                      ["at", fmt(x + 2), fmt(y + h / 2), "0"], eff(1.6, "left bottom"),
                      ["uuid", q(uid("roottext", i))]])
    notes = ["APPLE-1 TERMINAL SECTION REDESIGN - NTSC composite, discrete modern logic, single +5V",
             "Replaces Apple 00101 sheet 1/3.  Design: docs/apple1-video-redesign.md.",
             "ROM images: python3 -m a1video.gen_roms (timing.bin -> U9, chargen.bin -> U28,",
             "seq_lo.bin -> U33, seq_hi.bin -> U34).",
             "Generated from a1video/kicad.py: regenerate rather than hand-editing connectivity."]
    for k, line in enumerate(notes):
        items.append(["text", q(line), ["exclude_from_sim", "no"], ["at", "30.48", fmt(25.4 + 4 * k), "0"],
                      eff(2.0 if k == 0 else 1.6, "left bottom", bold=k == 0),
                      ["uuid", q(uid("rootnote", k))]])
    tree = ["kicad_sch", ["version", "20250114"], ["generator", q("eeschema")],
            ["generator_version", q("9.0")], ["uuid", q(root_uuid)], ["paper", q("A4")],
            title_block("Apple-1 terminal redesign"), ["lib_symbols"]] + items + \
        [["sheet_instances", ["path", q("/"), ["page", q("1")]]], ["embedded_fonts", "no"]]
    with open(os.path.join(outdir, PROJECT + ".kicad_sch"), "w") as f:
        f.write(dump(tree) + "\n")


def write_lib_tables(outdir):
    libs = sorted({PARTS[r]["lib"].split(":")[0] for r in PARTS} | {"power"})
    rows = "".join(f'  (lib (name "{n}")(type "KiCad")(uri "${{KICAD9_SYMBOL_DIR}}/{n}.kicad_sym")'
                   f'(options "")(descr ""))\n' for n in libs)
    with open(os.path.join(outdir, "sym-lib-table"), "w") as f:
        f.write("(sym_lib_table\n  (version 7)\n" + rows + ")\n")


def write_pro(outdir):
    pro = {"meta": {"filename": PROJECT + ".kicad_pro", "version": 3},
           "sheets": [[uid("root"), "Root"]] + [[uid("sheetsym", i + 1), s[1]] for i, s in enumerate(SHEETS)],
           "text_variables": {}}
    with open(os.path.join(outdir, PROJECT + ".kicad_pro"), "w") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")


# ====================================================================== verification

def kicad_netlist(outdir):
    with tempfile.TemporaryDirectory() as td:
        xmlf = os.path.join(td, "net.xml")
        subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format", "kicadxml", "-o", xmlf,
                        os.path.join(outdir, PROJECT + ".kicad_sch")],
                       check=True, capture_output=True)
        root = ET.parse(xmlf).getroot()
    nets = {}
    for n in root.iter("net"):
        name = n.get("name")
        nets[name] = {(node.get("ref"), node.get("pin")) for node in n.iter("node")}
    return nets


def compare(outdir):
    """List of differences between the KiCad netlist and the table in define()."""
    if not PARTS:
        define()
        resolve()
    want = expected_nets()
    got = kicad_netlist(outdir)
    errs = []
    by_pin = {}
    for name, nodes in got.items():
        short = name.rsplit("/", 1)[-1] if name.startswith("/") else name
        for node in nodes:
            by_pin[node] = short
    for net, nodes in want.items():
        names = {by_pin.get(n) for n in nodes}
        if len(names) != 1:
            errs.append(f"{net}: split into {sorted(map(str, names))}")
            continue
        name = names.pop()
        if name != net:
            errs.append(f"{net}: named {name} in KiCad")
        full = [k for k in got if (k.rsplit('/', 1)[-1] if k.startswith('/') else k) == name]
        kn = set().union(*(got[k] for k in full))
        if kn != nodes:
            errs.append(f"{net}: KiCad has extra {sorted(kn - nodes)}")
    for ref, p in PARTS.items():
        for num, net in p["net"].items():
            if net is None and (ref, num) in by_pin and not by_pin[(ref, num)].startswith("unconnected"):
                errs.append(f"{ref}.{num}: expected no-connect, got {by_pin[(ref, num)]}")
    return errs


def run_erc(outdir):
    with tempfile.TemporaryDirectory() as td:
        rpt = os.path.join(td, "erc.json")
        subprocess.run(["kicad-cli", "sch", "erc", "--format", "json", "-o", rpt,
                        os.path.join(outdir, PROJECT + ".kicad_sch")], check=True, capture_output=True)
        data = json.load(open(rpt))
    out = []
    for sh in data.get("sheets", []):
        for v in sh.get("violations", []):
            out.append((v["severity"], v["type"], v["description"],
                        "; ".join(i["description"] for i in v.get("items", []))))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="kicad")
    ap.add_argument("--check", action="store_true", help="netlist compare + ERC via kicad-cli")
    a = ap.parse_args()
    papers = write_project(a.out)
    n_parts = len(PARTS)
    n_nets = len(expected_nets())
    print(f"wrote {a.out}/{PROJECT}.kicad_pro, root + {len(SHEETS)} sheets "
          f"({', '.join(f'{SHEETS[i - 1][1]} {p}' for i, p in papers.items())}): "
          f"{n_parts} parts, {n_nets} nets")
    if a.check:
        if not shutil.which("kicad-cli"):
            sys.exit("kicad-cli not found")
        errs = compare(a.out)
        print(f"netlist compare: {'OK' if not errs else f'{len(errs)} differences'}")
        for e in errs:
            print("  ", e)
        erc = run_erc(a.out)
        counts = {}
        for sev, typ, *_ in erc:
            counts[(sev, typ)] = counts.get((sev, typ), 0) + 1
        print(f"ERC: {len(erc)} violations")
        for (sev, typ), n in sorted(counts.items()):
            print(f"   {sev:8s} {typ:30s} {n}")
        if errs:
            sys.exit(1)


if __name__ == "__main__":
    main()
