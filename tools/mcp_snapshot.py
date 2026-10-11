"""Snapshot the PC-98 palette out of a RUNNING DOSBox-X through its debugger.

Method (no guest code, no image edits):

    REQ n BREAK                  -> pause the guest (freeze the frame)
    REQ n EXEC PC98 DACPAL       -> print pc98_pal_analog[16] + pc98_pal_vga[256]
    REQ n EXEC VGA DACPAL        -> print the VGA DAC palette
    REQ n EXEC MEMDUMPBIN ...    -> optional: dump the guest's text VRAM
    REQ n EXEC RUN               -> resume

Freezing first is what makes the result trustworthy: the palette and the screen
are read at the same instant, so a saved .pal always matches the saved frame.

    # DOSBox-X must be running with `mcp_server = <port>`
    python tools\\mcp_snapshot.py --listen 2999 --outdir out\\pal\\snap --label briefing
    python tools\\mcp_snapshot.py --listen 2999 --outdir out\\pal\\snap --no-freeze --vram
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dosbox_mcp_palette import (McpServer, parse_analog, write_pal,   # noqa: E402
                                write_preview)

DIGITAL_RE = re.compile(r"Digital 8-color DAC palette[^:]*:\s*([0-9A-Fa-f]{8})")
VGA_PAL_RE = re.compile(r"^\s*([0-9a-fA-F]{2}):\s*((?:[0-9a-fA-F]{6}[-\s]*)+)")


def parse_vga_dac(lines: list[str]):
    """Collect the 256-entry VGA DAC palette printed as 'xx: rrgGBB rrgGBB ...'."""
    out: list[tuple[int, int, int] | None] = [None] * 256
    inside = False
    for ln in lines:
        if "VGA DAC palette" in ln:
            inside = True
            continue
        if inside and ("palette" in ln.lower() and ":" not in ln):
            break
        if not inside:
            continue
        m = VGA_PAL_RE.match(ln.strip())
        if not m:
            continue
        start = int(m.group(1), 16)
        toks = [t for t in re.split(r"[-\s]+", m.group(2)) if len(t) == 6]
        for i, t in enumerate(toks):
            idx = start + i
            if idx < 256:
                out[idx] = (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
    return out


def parse_digital(lines: list[str]):
    for ln in lines:
        m = DIGITAL_RE.search(ln)
        if m:
            return [int(c, 16) for c in m.group(1)]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, default=2999)
    ap.add_argument("--outdir", type=Path, default=Path("out/pal/snap"))
    ap.add_argument("--label", default="snap")
    ap.add_argument("--wait", type=float, default=300.0)
    ap.add_argument("--no-freeze", action="store_true",
                    help="do not BREAK/RUN (palette may lag the frame slightly)")
    ap.add_argument("--vram", action="store_true",
                    help="also MEMDUMPBIN the guest's text VRAM (A000:0000 4000)")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--interval", type=float, default=5.0)
    a = ap.parse_args()

    a.outdir.mkdir(parents=True, exist_ok=True)
    srv = McpServer(a.listen)
    print(f"[mcp] listening on 127.0.0.1:{srv.port}; start DOSBox-X with "
          f"`mcp_server = {srv.port}`")
    try:
        if not srv.accept(a.wait):
            print("[mcp] timeout", file=sys.stderr)
            return 2
        srv.drain(0.3)
        req = 1

        def box(cmd: str, settle: float = 1.5) -> list[str]:
            nonlocal req
            srv.send(f"REQ {req} {cmd}")
            req += 1
            return srv.drain(settle)

        box("PING", 0.4)
        for i in range(a.count):
            stamp = datetime.now().strftime("%H%M%S")
            stem = f"{a.label}_{stamp}"
            vram_file = f"{stem}_vram.bin"
            print(f"\n--- snapshot {i + 1}: {stem}")
            if not a.no_freeze:
                box("BREAK", 1.0)
            pal_lines = box("EXEC PC98 DACPAL", 2.0)
            vga_lines = box("EXEC VGA DACPAL", 2.0)
            vram_lines = box(f"EXEC MEMDUMPBIN A000:0000 4000 {vram_file}", 1.5) if a.vram else []
            if not a.no_freeze:
                box("EXEC RUN", 1.0)

            pal = parse_analog(pal_lines)
            digital = parse_digital(pal_lines)
            vga_dac = parse_vga_dac(vga_lines)
            if digital:
                print(f"    digital 8-colour : {''.join('%x' % c for c in digital)}")
            if any(pal):
                print("    analog 16-colour : " +
                      " ".join("--" if c is None else "%x%x%x" % c for c in pal))
                write_pal(a.outdir / f"{stem}.pal", pal)
                write_preview(a.outdir / f"{stem}_preview.png", pal)
                raw = a.outdir / f"{stem}_analog.rgb"
                raw.write_bytes(bytes(v for c in pal for v in (c or (0, 0, 0))))
                print(f"    -> {stem}.pal / {stem}_preview.png / {stem}_analog.rgb")
            else:
                print("    !! no palette parsed; raw reply:")
                for ln in pal_lines:
                    print("      ", ln)
            if any(vga_dac):
                (a.outdir / f"{stem}_vga.dac").write_bytes(
                    bytes(v for c in vga_dac for v in (c or (0, 0, 0))))
                print(f"    -> {stem}_vga.dac (256 entries)")
            if a.vram and any("Memory dump" in ln for ln in vram_lines):
                print(f"    -> {vram_file}")
            if i + 1 < a.count:
                time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\n[stop] interrupted")
    finally:
        srv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
