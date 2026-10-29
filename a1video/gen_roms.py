"""Write the four ROM images for an SST39SF010A programmer.

    python3 -m a1video.gen_roms [--out roms]
"""

import argparse
import hashlib
import os

from .roms import build_all
from .sim import Terminal, measure_timing
from . import spec as S


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="roms", help="output directory (default: roms)")
    args = ap.parse_args()

    roms = build_all()

    # Sanity check: the images must generate the specified video timing.
    m = measure_timing(Terminal(roms))
    assert m["line_periods"] == {S.H_TOTAL}, m["line_periods"]
    assert m["lines_per_frame"] == S.V_TOTAL, m["lines_per_frame"]
    assert m["hsync_h"] == list(S.H_SYNC), m["hsync_h"]

    os.makedirs(args.out, exist_ok=True)
    for name, data in roms.items():
        path = os.path.join(args.out, name)
        with open(path, "wb") as f:
            f.write(data)
        print(f"{path:24s} {len(data):7d} bytes  sha1 {hashlib.sha1(data).hexdigest()[:12]}")
    print(f"timing: {m['line_us']:.3f} us/line, {m['frame_hz']:.2f} Hz, "
          f"{m['lines_per_frame']} lines, hsync H={m['hsync_h'][0]}-{m['hsync_h'][-1]}, "
          f"vsync lines {m['vsync_lines']}")


if __name__ == "__main__":
    main()
