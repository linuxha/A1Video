"""Run the terminal simulator on some text and report what it does.

    python3 -m a1video.simulate [--file TEXT] [--slow] [--bank 1] [--png frame.png]
"""

import argparse

from . import spec as S
from .sim import Terminal, Driver, ReferenceTerminal, render_frame, tv_view, write_png

DEMO = (
    "\\\n"
    "FF00: D8 58 A0 7F 8C 12 D0 A9\n"
    "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG 0123456789\n"
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_\n"
    "lower case shows as upper in bank 0\n"
)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="text file to send (LF becomes CR)")
    ap.add_argument("--slow", action="store_true", help="fit the authentic-speed jumper")
    ap.add_argument("--bank", type=int, default=0, choices=(0, 1), help="char ROM bank jumper")
    ap.add_argument("--cpu-gap", type=int, default=10, help="CPU periods between characters")
    ap.add_argument("--png", help="render one frame to this PNG file")
    args = ap.parse_args()

    text = open(args.file, encoding="latin-1").read() if args.file else DEMO

    term = Terminal(slow=args.slow, bank=args.bank)
    drv = Driver(term, cpu_gap=args.cpu_gap)
    drv.press_clr()
    drv.send(text)
    drv.run_until_idle()

    ref = ReferenceTerminal()
    ref.feed(text)

    print("+" + "-" * S.COLS + "+")
    for line in term.screen_lines():
        print("|" + line + "|")
    print("+" + "-" * S.COLS + "+")

    ok = term.screen_lines() == ref.screen_lines() and term.cursor() == ref.cursor()
    lat = [p for _, p in drv.latencies]
    cr = [p for ch, p in drv.latencies if ch == 0x0D]
    us = 1e6 / S.CHAR_HZ
    print(f"chars sent: {len(lat)}   simulated time: {term.periods * us / 1000:.2f} ms")
    if lat:
        print(f"DA->RDA latency: min {min(lat) * us:.1f} us, max {max(lat) * us:.1f} us"
              + (f", CR max {max(cr) * us:.1f} us" if cr else ""))
    print(f"cursor: line {term.cursor()[0]}, col {term.cursor()[1]}   TOP={term.top}")
    print("matches reference model:", "YES" if ok else "NO")

    if args.png:
        write_png(args.png, tv_view(render_frame(term, drv)))
        print("frame written to", args.png)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
