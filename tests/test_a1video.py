import os
import random
import shutil
import tempfile
import unittest

from a1video import spec as S
from a1video.font import UPPER, LOWER, glyph_rows
from a1video.roms import build_all, chargen_addr, CONTROLS, STATE_NAMES, IDLE, ACK1, ACK2, ACK3
from a1video.sim import (Terminal, Driver, ReferenceTerminal, measure_timing, render_frame,
                         LEVEL_SYNC, LEVEL_WHITE)

ROMS = None


def setUpModule():
    global ROMS
    ROMS = build_all()


def run(text, **kw):
    term = Terminal(ROMS, **{k: v for k, v in kw.items() if k in ("slow", "bank", "seed_ram")})
    drv = Driver(term, cpu_gap=kw.get("cpu_gap", 10))
    drv.press_clr()
    drv.send(text)
    drv.run_until_idle()
    return term, drv


def assert_matches_reference(tc, term, data):
    ref = ReferenceTerminal()
    ref.feed(data)
    tc.assertEqual(term.screen_lines(), ref.screen_lines())
    tc.assertEqual(term.cursor(), ref.cursor())


class TestTiming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = measure_timing(Terminal(ROMS))

    def test_line_and_frame_length(self):
        self.assertEqual(self.m["line_periods"], {65})
        self.assertEqual(self.m["lines_per_frame"], 262)
        self.assertEqual(self.m["frame_periods"], {65 * 262})
        self.assertAlmostEqual(self.m["line_us"], 63.556, places=3)
        self.assertAlmostEqual(S.CHAR_HZ / 65, 15734.26, places=1)
        self.assertAlmostEqual(self.m["frame_hz"], 60.054, places=2)

    def test_hsync(self):
        self.assertEqual(self.m["hsync_h"], list(range(47, 52)))
        width_us = len(self.m["hsync_h"]) * S.CHAR_NS / 1000
        self.assertTrue(4.5 <= width_us <= 5.1, width_us)

    def test_vsync_and_serrations(self):
        self.assertEqual(self.m["vsync_lines"], [216, 217, 218])
        t = Terminal(ROMS)
        while not (t.v == 217 and t.h == 0):
            t.step()
        high = []
        for _ in range(65):
            if t.treg & S.T_NCSYNC:
                high.append(t.h)
            t.step()
        self.assertEqual(high, list(range(47, 52)))

    def test_visible_window(self):
        self.assertEqual(self.m["visible_h"], list(range(1, 41)))
        self.assertEqual(self.m["visible_v"], (0, 191))

    def test_cla_is_apple1_cpu_clock(self):
        self.assertAlmostEqual(S.CHAR_HZ / 1e6, 1.0227, places=4)


class TestCharRom(unittest.TestCase):
    def rows(self, code, bank=0, cursor=0):
        return [ROMS["chargen.bin"][chargen_addr(code, s, cursor, bank)] >> 3 for s in range(8)]

    def test_datasheet_example_S(self):
        self.assertEqual(self.rows(ord("S")),
                         [0b00000, 0b01110, 0b10001, 0b10000, 0b01110, 0b00001, 0b10001, 0b01110])

    def test_font_tables_complete(self):
        self.assertEqual(sorted(ord(c) for c in UPPER), list(range(0x20, 0x60)))
        self.assertEqual(sorted(ord(c) for c in LOWER), list(range(0x60, 0x80)))
        for table in (UPPER, LOWER):
            for ch, g in table.items():
                self.assertEqual(len(g), 7, ch)
                self.assertTrue(all(len(r) == 5 and set(r) <= {".", "#"} for r in g), ch)

    def test_control_codes_blank(self):
        for code in range(0x20):
            self.assertEqual(self.rows(code), [0] * 8)

    def test_case_folding_and_bank1(self):
        self.assertEqual(self.rows(ord("a")), self.rows(ord("A")))
        self.assertEqual(self.rows(ord("a"), bank=1), glyph_rows(LOWER["a"]))

    def test_cursor_half_is_at_sign(self):
        at = self.rows(0x40)
        for code in (0x00, 0x20, 0x41, 0x7F):
            self.assertEqual(self.rows(code, cursor=1), at)

    def test_gap_columns_dark(self):
        self.assertTrue(all(b & 0b111 == 0 for b in ROMS["chargen.bin"][:1 << 12]))


class TestSequencerRom(unittest.TestCase):
    def words(self):
        lo, hi = ROMS["seq_lo.bin"], ROMS["seq_hi.bin"]
        return (lo[a] | hi[a] << 8 for a in range(1 << S.SEQ_ADDR_BITS))

    def test_unused_states_recover(self):
        lo, hi = ROMS["seq_lo.bin"], ROMS["seq_hi.bin"]
        for state in range(len(STATE_NAMES), 32):
            for inputs in (0, 0x3E0, 0x1FFE0):
                a = state | inputs
                self.assertEqual(lo[a] | hi[a] << 8, IDLE)

    def test_no_conflicting_controls(self):
        pairs = [(S.C_COL_INC, S.C_COL_CLR), (S.C_ROW_INC, S.C_ROW_CLR),
                 (S.C_TOP_INC, S.C_TOP_CLR), (S.C_LATCH_LD, S.C_LATCH_CLR)]
        for w in set(self.words()):
            for a, b in pairs:
                self.assertFalse(w & a and w & b, hex(w))

    def test_rda_only_in_ack_states(self):
        for state, c in CONTROLS.items():
            self.assertEqual(bool(c & S.C_RDA), state in (ACK1, ACK2, ACK3), STATE_NAMES[state])


class TestBehaviour(unittest.TestCase):
    def test_monitor_style_output(self):
        text = "\\\nFF00: D8 58 A0 7F\n0123456789 ABCDEF\n"
        term, _ = run(text)
        assert_matches_reference(self, term, text)

    def test_wrap_at_40_then_cr(self):
        text = "X" * 40 + "\nNEXT"
        term, _ = run(text)
        assert_matches_reference(self, term, text)
        self.assertEqual(term.screen_lines()[1].strip(), "")      # wrap + CR = blank line

    def test_scrolling(self):
        text = "".join(f"LINE {i:02d}\n" for i in range(60))
        term, _ = run(text)
        assert_matches_reference(self, term, text)
        self.assertEqual(term.screen_lines()[22].strip(), "LINE 59")
        self.assertNotEqual(term.top, 0)

    def test_control_codes_ignored(self):
        data = bytes([0x41, 0x07, 0x08, 0x0A, 0x1B, 0x42, 0x0D, 0x43])
        term, drv = run(data)
        assert_matches_reference(self, term, data)
        self.assertEqual(len(drv.latencies), len(data))           # every byte acknowledged

    def test_random_stream(self):
        rng = random.Random(1976)
        data = bytes(rng.choice([0x0D] * 3 + list(range(0x00, 0x80))) for _ in range(3000))
        term, _ = run(data)
        assert_matches_reference(self, term, data)

    def test_clr_mid_stream(self):
        term, drv = run("".join(f"{i}\n" for i in range(30)))
        drv.press_clr()
        self.assertEqual(term.screen_lines(), [" " * 40] * 24)
        self.assertEqual((term.cursor(), term.top), ((0, 0), 0))
        drv.send("AFTER CLEAR\n")
        drv.run_until_idle()
        assert_matches_reference(self, term, "AFTER CLEAR\n")

    def test_power_up_garbage(self):
        rng = random.Random(6502)
        term = Terminal(ROMS, seed_ram=bytes(rng.randrange(256) for _ in range(2048)))
        term.col, term.row, term.top, term.vrow = 51, 30, 27, 29
        term.seqreg = rng.randrange(1 << 16)
        drv = Driver(term)
        drv.press_clr()
        self.assertEqual(term.screen_lines(), [" " * 40] * 24)
        drv.send("OK\n")
        drv.run_until_idle()
        assert_matches_reference(self, term, "OK\n")

    def test_latency(self):
        text = "ABCDEFGHIJ\n" * 30
        _, drv = run(text)
        us = S.CHAR_NS / 1000
        printable = [p * us for ch, p in drv.latencies if ch != 0x0D]
        cr = [p * us for ch, p in drv.latencies if ch == 0x0D]
        self.assertLess(max(printable), 6.0)
        self.assertLess(max(cr), 50.0)

    def test_clear_time(self):
        term = Terminal(ROMS)
        term.clr = True
        n = 0
        while term.state != 18:                        # WAITCLR
            term.step()
            n += 1
        self.assertLess(n * S.CHAR_NS / 1e6, 1.1)        # under 1.1 ms

    def test_rda_pulse_width(self):
        term = Terminal(ROMS)
        drv = Driver(term)
        drv.press_clr()
        drv.send("A")
        width = 0
        while drv.busy or term.state != IDLE:
            drv.tick()
            width += term.rda
        self.assertEqual(width, 3)

    def test_slow_mode_one_char_per_frame(self):
        text = "SLOWMODE"
        term, drv = run(text, slow=True)
        assert_matches_reference(self, term, text)
        frame = 65 * 262
        self.assertGreaterEqual(max(p for _, p in drv.latencies), frame // 2)
        clr_periods = int(0.020 * S.CHAR_HZ) + 8
        self.assertGreaterEqual(term.periods - clr_periods, (len(text) - 1) * frame)


class TestRender(unittest.TestCase):
    def test_glyph_pixels_and_cursor(self):
        term, drv = run("S")
        for blink in (0, 1):
            term.framecnt = blink << 4
            img = render_frame(term, drv)
            for scan in range(8):
                line = img[scan]
                s = [int(lv == LEVEL_WHITE) for lv in line[7:14]]       # column 0 at H=1
                cur = [int(lv == LEVEL_WHITE) for lv in line[14:21]]    # cursor at column 1
                expect_s = [(glyph_rows(UPPER["S"])[scan] >> (4 - i)) & 1 for i in range(5)]
                self.assertEqual(s, expect_s + [0, 0])
                expect_c = [(glyph_rows(UPPER["@"])[scan] >> (4 - i)) & 1 for i in range(5)]
                self.assertEqual(cur, (expect_c if blink else [0] * 5) + [0, 0])

    def test_sync_level(self):
        term = Terminal(ROMS)
        img = render_frame(term)
        self.assertTrue(all(lv == LEVEL_SYNC for lv in img[10][47 * 7:52 * 7]))
        self.assertTrue(all(lv == LEVEL_SYNC for lv in img[217][:47 * 7]))


class TestKicad(unittest.TestCase):
    def test_netlist_resolves(self):
        from a1video import kicad
        kicad.define()
        kicad.resolve()
        nets = kicad.expected_nets()
        self.assertEqual(nets["CHAR_END"] >= {("U45", "2"), ("U4", "7"), ("U37", "13")}, True)
        self.assertTrue(all(len(n) > 1 for name, n in nets.items()), "single-pin net")

    @unittest.skipUnless(shutil.which("kicad-cli") and os.path.isdir(
        os.environ.get("KICAD9_SYMBOL_DIR", "/usr/share/kicad/symbols")), "KiCad 9 not installed")
    def test_kicad_netlist_and_erc(self):
        from a1video import kicad
        with tempfile.TemporaryDirectory() as td:
            kicad.write_project(td)
            self.assertEqual(kicad.compare(td), [])
            self.assertEqual(kicad.run_erc(td), [])


if __name__ == "__main__":
    unittest.main()
