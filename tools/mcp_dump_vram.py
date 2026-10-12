"""Snapshot the guest's graphics VRAM through the DOSBox-X debugger (MCP).

Ground truth for the display-list work: the PC-98 graphics planes are guest-visible
at segments A800 (B), B000 (R), B800 (G) and E000 (E), 400 rows x 80 bytes each, so
the debugger's MEMDUMPBIN can pull them straight out of the running game:

    BREAK                       freeze the frame
    EXEC MEMDUMPBIN A800:0000 8000 vram_B.bin     (and B000/B800/E000)
    EXEC PC98 DACPAL            the palette that goes with it
    EXEC RUN                    resume

Frames are de-duplicated by content, so a long play session produces one directory
per distinct screen, each with the four planes, a JASC `.pal` and (with Pillow) a
640x400 PNG preview.

    python tools\\mcp_dump_vram.py --listen 2999 --outdir out\\vram --interval 4
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dosbox_mcp_palette import McpServer, parse_analog, write_pal     # noqa: E402

PLANES = [("B", 0xA800), ("R", 0xB000), ("G", 0xB800), ("E", 0xE000)]
PLANE_BYTES = 0x8000            # 32 KB per plane (400 rows x 80 bytes used)
ROW = 80
ROWS = 400


def render_preview(planes: dict, pal, path: Path):
    """Compose a 640x400 indexed image from the four planes."""
    try:
        from PIL import Image
    except ImportError:
        return False
    img = Image.new("P", (640, ROWS))
    p = []
    for c in pal:
        r, g, b = c if c else (0, 0, 0)
        p += [r * 17, g * 17, b * 17]
    p += [0] * (768 - len(p))
    img.putpalette(p)
    data = bytearray(640 * ROWS)
    for y in range(ROWS):
        base = y * ROW
        for xb in range(ROW):
            idx = {}
            for name, _seg in PLANES:
                pl = planes.get(name)
                if pl is None or base + xb >= len(pl):
                    return False
                idx[name] = pl[base + xb]
            for bit in range(8):
                v = 0
                for k, (name, _seg) in enumerate(PLANES):
                    v |= ((idx[name] >> (7 - bit)) & 1) << k
                data[y * 640 + xb * 8 + bit] = v
    img.putdata(list(data))
    img.convert("RGB").save(path)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, default=2999)
    ap.add_argument("--outdir", type=Path, default=Path("out/vram"))
    ap.add_argument("--interval", type=float, default=4.0)
    ap.add_argument("--count", type=int, default=0, help="0 = until stopped")
    ap.add_argument("--label", default="frame")
    ap.add_argument("--wait", type=float, default=900.0)
    ap.add_argument("--extra-dir", action="append", type=Path, default=[],
                    help="also look for the dump files here (DOSBox-X writes them "
                         "relative to its own working directory)")
    ap.add_argument("--launch", type=Path, default=None,
                    help="start this executable (dosbox-x.exe) once the listener is up, "
                         "so the game cannot dial in before the dumper is ready")
    ap.add_argument("--conf", type=Path, default=None, help="config for --launch")
    ap.add_argument("--freeze", action="store_true",
                    help="BREAK/RUN around each dump (frame-accurate). Warning: a BREAK "
                         "sent while the guest is still early in its boot crashes "
                         "DOSBox-X, so leave it off unless you need frozen frames")
    ap.add_argument("--start-delay", type=float, default=10.0,
                    help="seconds to let the guest run before the first dump (a BREAK "
                         "or memory dump this early is unsafe)")
    a = ap.parse_args()

    a.outdir.mkdir(parents=True, exist_ok=True)
    srv = McpServer(a.listen)
    print(f"[mcp] listening on 127.0.0.1:{srv.port}")
    if a.launch:
        cmd = [str(a.launch)]
        if a.conf:
            cmd += ["-conf", str(a.conf)]
        print(f"[run] {' '.join(cmd)}")
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"[mcp] start DOSBox-X with `mcp_server = {srv.port}`, then play. "
              f"Ctrl+C here to stop.")
    seen_dirs = (Path.cwd(), HERE.parent, HERE.parent.parent, Path.home(),
                 Path(r"D:\Games\DOSBox-X")) + tuple(a.extra_dir)

    def collect(stem: str):
        """Find the files the emulator just wrote, wherever it put them."""
        out = {}
        for name, _seg in PLANES:
            for cand in seen_dirs:
                p = cand / f"{stem}_{name}.bin"
                if p.is_file():
                    out[name] = p.read_bytes()
                    break
        return out

    def cleanup(stem: str):
        for name, _seg in PLANES:
            for cand in seen_dirs:
                p = cand / f"{stem}_{name}.bin"
                if p.is_file():
                    p.unlink()

    try:
        if not srv.accept(a.wait):
            print("[mcp] timeout waiting for DOSBox-X", file=sys.stderr)
            return 2
        srv.drain(0.3)
        if a.start_delay > 0:
            print(f"[mcp] letting the guest run for {a.start_delay:.0f}s before the "
                  f"first dump")
            time.sleep(a.start_delay)
        req = 1
        saved, last = 0, None
        while True:
            stem = "vram_tmp"
            try:
                if a.freeze:
                    srv.send(f"REQ {req} BREAK"); req += 1; srv.drain(0.8)
                for name, seg in PLANES:
                    srv.send(f"REQ {req} EXEC MEMDUMPBIN {seg:04X}:0000 "
                             f"{PLANE_BYTES:X} {stem}_{name}.bin")
                    req += 1
                    srv.drain(1.0)
                srv.send(f"REQ {req} EXEC PC98 DACPAL"); req += 1
                pal_lines = srv.drain(1.5)
                if a.freeze:
                    srv.send(f"REQ {req} EXEC RUN"); req += 1; srv.drain(0.8)
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                print(f"\n[mcp] DOSBox-X dropped the connection ({e}). If the emulator "
                      f"window vanished, it crashed - restart with a longer "
                      f"--start-delay and without --freeze.")
                break

            found = collect(stem)
            pal = parse_analog(pal_lines)
            if len(found) != len(PLANES):
                print(f"[dump] {saved:03d}: plane file(s) not found (looked in "
                      f"{', '.join(str(d) for d in seen_dirs)})")
            else:
                digest = hashlib.sha256(b"".join(found[n] for n, _ in PLANES)).hexdigest()
                nonzero = {n: sum(1 for b in found[n][:32000] if b) for n, _ in PLANES}
                if not any(nonzero.values()):
                    print(f"[dump] {saved:03d}: all planes blank, skipped")
                elif digest == last:
                    print(f"[dump] {saved:03d}: screen unchanged, skipped")
                else:
                    last = digest
                    frame_dir = a.outdir / f"{a.label}_{saved:03d}_{datetime.now():%H%M%S}"
                    frame_dir.mkdir(parents=True, exist_ok=True)
                    for name, _seg in PLANES:
                        (frame_dir / f"{name}.bin").write_bytes(found[name])
                    if any(pal):
                        write_pal(frame_dir / "palette.pal", pal)
                    print(f"[dump] {frame_dir.name}: saved, non-zero bytes/plane {nonzero}")
                    if any(pal) and render_preview(found, pal, frame_dir / "preview.png"):
                        print(f"[dump]   -> {frame_dir / 'preview.png'}")
                    saved += 1
            cleanup(stem)
            if a.count and saved >= a.count:
                break
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\n[stop] interrupted")
    finally:
        srv.close()
    print(f"[done] {saved} distinct frame(s) in {a.outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
