"""One-shot MCP probe: run an arbitrary list of debugger commands against a
DOSBox-X instance that is ALREADY RUNNING (started by something else).

Unlike dosbox_mcp_palette.py this does not launch the emulator; it only listens,
waits for the connection, sends the commands and prints every reply line. Use it
to inspect a guest that you drove by hand (e.g. you pressed the key at the
PC-98 boot menu yourself).

    python tools\\mcp_probe.py --listen 2999 --command "PC98 DACPAL" --command "MEMDUMPBIN A000:0000 4000 vram.bin"

Notes:
  * DOSBox-X dials 127.0.0.1:<port> itself, so the listener must be up first.
  * MEMDUMPBIN writes on the HOST, relative to DOSBox-X's -working-dir.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from dosbox_mcp_palette import McpServer, parse_analog, write_pal, write_preview  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, default=2999)
    ap.add_argument("--command", action="append", default=[],
                    help="debugger command to EXEC (repeatable)")
    ap.add_argument("--wait", type=float, default=300.0)
    ap.add_argument("--settle", type=float, default=0.5)
    ap.add_argument("--save", type=Path)
    ap.add_argument("--preview", type=Path)
    a = ap.parse_args()

    srv = McpServer(a.listen)
    print(f"[mcp] listening on 127.0.0.1:{srv.port} - start DOSBox-X with "
          f"`mcp_server = {srv.port}`")
    try:
        if not srv.accept(a.wait):
            print("[mcp] timeout waiting for DOSBox-X", file=sys.stderr)
            return 2
        time.sleep(a.settle)
        srv.drain(0.3)
        srv.send("REQ 1 PING")
        srv.drain(0.4)
        collected: list[str] = []
        for i, cmd in enumerate(a.command, start=2):
            srv.send(f"REQ {i} EXEC {cmd}")
            collected += srv.drain(1.5)
        pal = parse_analog(collected)
        if any(pal):
            print("[pal] PC-98 analog palette:")
            for i, c in enumerate(pal):
                print(f"   [{i:2d}] {'--' if c is None else '%x%x%x' % c}")
            if a.save:
                write_pal(a.save, pal)
                if a.preview:
                    write_preview(a.preview, pal)
        return 0
    finally:
        srv.close()


if __name__ == "__main__":
    sys.exit(main())
