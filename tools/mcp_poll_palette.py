"""Poll the running DOSBox-X palette over MCP and save a .pal whenever it changes.

Why this instead of an in-guest dumper: on this HDI the DOS shell is GO.EXE
(`SHELL = GO.EXE` in both config.sys files), and a test that put a marker-writer
into the image's AUTOEXEC.BAT showed the marker never appears - AUTOEXEC.BAT is
not executed on this boot path. Patching the game's own launcher is possible but
invasive; driving the emulator from outside needs no guest modification at all
and works no matter how the game was started (including through the boot menu).

Typical use: start DOSBox-X with `mcp_server = <port>`, run this, and play. Stop
at the screen you care about, wait one interval, and the newest file in the
output directory is that screen's palette.

    python tools\\mcp_poll_palette.py --listen 2999 --outdir out\\pal --interval 5
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dosbox_mcp_palette import McpServer, parse_analog, write_pal, write_preview  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, default=2999)
    ap.add_argument("--outdir", type=Path, default=Path("out/pal"))
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--count", type=int, default=0, help="0 = until stopped")
    ap.add_argument("--tag", default="live")
    ap.add_argument("--wait", type=float, default=600.0)
    a = ap.parse_args()

    a.outdir.mkdir(parents=True, exist_ok=True)
    srv = McpServer(a.listen)
    print(f"[mcp] listening on 127.0.0.1:{srv.port}; start DOSBox-X with "
          f"`mcp_server = {srv.port}`, then play")
    preview_ok = True
    try:
        if not srv.accept(a.wait):
            print("[mcp] timeout waiting for DOSBox-X", file=sys.stderr)
            return 2
        srv.drain(0.3)
        req = 1
        last = None
        saved = 0
        while True:
            srv.send(f"REQ {req} EXEC PC98 DACPAL")
            req += 1
            lines = srv.drain(1.2)
            pal = parse_analog(lines)
            if any(pal):
                key = tuple(pal)
                if key != last:
                    last = key
                    name = f"{a.tag}_{saved:03d}.pal"
                    write_pal(a.outdir / name, pal)
                    # the preview needs Pillow; without it the palette itself is
                    # still saved, so keep polling instead of dying here
                    try:
                        write_preview(a.outdir / (Path(name).stem + ".png"), pal)
                    except ImportError:
                        if preview_ok:
                            preview_ok = False
                            print("[warn] Pillow is not installed - skipping .png previews",
                                  file=sys.stderr)
                    # raw 4-bit triples, exactly as the debugger reported them:
                    # the palette search tools read this form, not the x17 .pal
                    raw = a.outdir / (Path(name).stem + "_analog.rgb")
                    raw.write_bytes(bytes(v for c in pal for v in (c or (0, 0, 0))))
                    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    with open(a.outdir / "screens.log", "a", encoding="utf-8") as log:
                        log.write(f"{stamp}  {name}  " +
                                  " ".join("--" if c is None else "%x%x%x" % c for c in pal) +
                                  "\n")
                    print("   " + " ".join("--" if c is None else "%x%x%x" % c for c in pal))
                    print(f"   -> {name} / {raw.name} / preview .png")
                    saved += 1
                    if a.count and saved >= a.count:
                        break
            if a.count and req > a.count * 60:
                break
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\n[stop] interrupted")
    finally:
        srv.close()
    print(f"[done] {saved} distinct palettes written to {a.outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
