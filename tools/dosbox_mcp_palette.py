"""Talk to DOSBox-X's external debugger control server ("MCP") and pull the
PC-98 palette out of it.

How it works
------------
DOSBox-X can act as a *TCP client*: with `mcp_server = <port>` in the config it
dials 127.0.0.1:<port> (see src/debug/debug_mcp.cpp). The protocol is one line
per request:

    REQ <id> PING                  -> RES <id> OK PONG
    REQ <id> BREAK                 -> pauses the guest (opens the debugger)
    REQ <id> EXEC <command...>     -> runs ANY debugger command

`EXEC` is the useful one: the debugger has undocumented palette commands

    PC98 DACPAL      prints the current analog palette (pc98_pal_analog[16],
                     pc98_pal_vga[256], pc98_pal_digital[8])
    VGA DACPAL       prints the VGA DAC palette

which is precisely the "dump the palette" function DOSBox-X seems to be missing
from its menus - it is just not documented in the debugger's HELP.

Usage
-----
    # 1. start the listener (it prints the port it picked)
    python tools\\dosbox_mcp_palette.py --listen 2999 --save out\\live.pal

    # 2. in another shell, start the game with it enabled, e.g.
    #    dosbox-x -conf tools\\pdz_mcp.conf -c "config -set mcp_server=2999"

    # or one-shot: launch DOSBox-X yourself and drive it
    python tools\\dosbox_mcp_palette.py --listen 2999 --launch "D:\\Games\\DOSBox-X\\dosbox-x.exe" ^
        --conf tools\\pdz_mcp.conf --save out\\live.pal
"""
from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

PC98_DEFAULT = [(0, 0, 0), (0, 0, 15), (0, 15, 0), (0, 15, 15),
                (15, 0, 0), (15, 0, 15), (15, 15, 0), (15, 15, 15),
                (7, 7, 7), (0, 0, 10), (0, 10, 0), (0, 10, 10),
                (10, 0, 0), (10, 0, 10), (10, 10, 0), (10, 10, 10)]


class McpServer:
    """Minimal server: accept DOSBox-X's connection and send requests."""

    def __init__(self, port: int, host: str = "127.0.0.1"):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.conn: socket.socket | None = None
        self.buf = b""
        self.lines: list[str] = []
        self.lock = threading.Lock()
        self._stop = False

    def accept(self, timeout: float) -> bool:
        self.sock.settimeout(timeout)
        try:
            self.conn, addr = self.sock.accept()
        except socket.timeout:
            return False
        print(f"[mcp] dosbox-x connected from {addr[0]}:{addr[1]}")
        self.conn.settimeout(0.25)
        threading.Thread(target=self._reader, daemon=True).start()
        return True

    def _reader(self) -> None:
        assert self.conn
        while not self._stop:
            try:
                data = self.conn.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            self.buf += data
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                text = line.decode("latin1", "replace").strip()
                if text:
                    with self.lock:
                        self.lines.append(text)
                    print(f"[mcp] <- {text}")

    def send(self, request: str) -> None:
        assert self.conn
        print(f"[mcp] -> {request}")
        self.conn.sendall((request + "\n").encode("latin1"))

    def drain(self, seconds: float = 1.0) -> list[str]:
        end = time.time() + seconds
        while time.time() < end:
            time.sleep(0.05)
        with self.lock:
            out = self.lines[:]
            self.lines.clear()
        return out

    def close(self) -> None:
        self._stop = True
        for s in (self.conn, self.sock):
            try:
                if s:
                    s.close()
            except OSError:
                pass


TRIPLE_RE = re.compile(r"\b([0-9A-Fa-f]{3})\b")


def parse_analog(lines: list[str]):
    """Parse the `PC98 DACPAL` reply.

    Layout (as printed by the debugger):

        Analog 16-color DAC palette (RGB):
        00: 000 00a 0a0 0aa-a00 a0a aa0 aaa
        08: 555 55f 5f5 5ff-f55 f5f ff5 fff
        VGA DAC palette (RGB):

    Eight entries per line, the ninth is preceded by '-' (the 8. colour), and
    the offset column restarts at 00/08. Colours are 4-bit hex, one digit per
    channel.
    """
    pal: list[tuple[int, int, int] | None] = [None] * 16
    inside = False
    for ln in lines:
        if "Analog 16-color" in ln:
            inside = True
            continue
        if inside and ("VGA DAC palette" in ln or "Digital" in ln):
            break
        if not inside:
            continue
        body = ln.split(":", 1)[1] if ":" in ln else ln
        for tok in re.split(r"[-\s]+", body.strip()):
            if len(tok) == 3 and all(c in "0123456789abcdefABCDEF" for c in tok):
                i = next((k for k in range(16) if pal[k] is None), None)
                if i is None:
                    break
                pal[i] = (int(tok[0], 16), int(tok[1], 16), int(tok[2], 16))
    return pal


def write_pal(path: Path, pal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="\n") as f:
        f.write("JASC-PAL\n0100\n16\n")
        for c in pal:
            r, g, b = c if c else (0, 0, 0)
            f.write(f"{r * 17} {g * 17} {b * 17}\n")
    print(f"[pal] wrote {path} (JASC-PAL, 16 entries)")


def write_preview(path: Path, pal, cell: int = 64) -> None:
    from PIL import Image
    im = Image.new("RGB", (cell * 8, cell * 2), (0, 0, 0))
    for i in range(16):
        c = pal[i] or (0, 0, 0)
        im.paste(Image.new("RGB", (cell - 2, cell - 2),
                           tuple(v * 17 for v in c)), ((i % 8) * cell + 1, (i // 8) * cell + 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    print(f"[pal] wrote {path} (preview)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", type=int, default=0,
                    help="TCP port to listen on (0 = pick a free one)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--launch", help="executable to start (dosbox-x.exe)")
    ap.add_argument("--conf", help="config file for --launch")
    ap.add_argument("--extra", nargs="*", default=[], help="extra args for --launch")
    ap.add_argument("--command", default="PC98 DACPAL",
                    help="debugger command to run through EXEC")
    ap.add_argument("--save", type=Path, help="write the parsed palette here")
    ap.add_argument("--preview", type=Path, help="write a 16-swatch PNG preview")
    ap.add_argument("--wait", type=float, default=120.0,
                    help="seconds to wait for DOSBox-X to connect")
    ap.add_argument("--settle", type=float, default=1.0)
    ap.add_argument("--pause", type=float, default=0.0,
                    help="seconds to let the guest run before asking for the palette "
                         "(e.g. 45 to let the game boot)")
    ap.add_argument("--exit-after", action="store_true",
                    help="send DOSBox-X's own EXIT command when done")
    ap.add_argument("extra_passthrough", nargs=argparse.REMAINDER,
                    help="everything after -- is passed to the emulator")
    a, unknown = ap.parse_known_args()
    extra = list(a.extra) + list(a.extra_passthrough) + list(unknown)
    extra = [x for x in extra if x != "--"]

    srv = McpServer(a.listen, a.host)
    print(f"[mcp] listening on {a.host}:{srv.port} (set `mcp_server = {srv.port}`)")
    if not (a.launch or a.conf):
        print("[mcp] pass --launch/--conf, or start DOSBox-X yourself with "
              f"`-c \"config -set mcp_server={srv.port}\"`", file=sys.stderr)

    proc = None
    if a.launch:
        cmd = [a.launch]
        if a.conf:
            cmd += ["-conf", a.conf]
        cmd += extra
        print(f"[run] {' '.join(cmd)}")
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not srv.accept(a.wait):
            print("[mcp] timed out waiting for DOSBox-X to connect", file=sys.stderr)
            return 2
        time.sleep(a.settle)
        srv.drain(0.5)
        srv.send("REQ 1 PING")
        srv.drain(0.5)
        if a.pause > 0:
            print(f"[mcp] letting the guest run for {a.pause:.0f}s ...")
            time.sleep(a.pause)
        srv.send(f"REQ 2 EXEC {a.command}")
        out = srv.drain(2.0)
        pal = parse_analog(out)
        if any(pal):
            print("[pal] live PC-98 palette from the debugger:")
            for i, c in enumerate(pal):
                print(f"   [{i:2d}] {'--' if c is None else '%x%x%x' % c}")
            missing = [i for i, c in enumerate(pal) if c is None]
            if missing:
                print(f"[pal] indices not initialised by the BIOS/program: {missing}"
                      " (the screenshot route cannot recover those at all)")
            if a.save:
                write_pal(a.save, pal)
                if a.preview:
                    write_preview(a.preview, pal)
        else:
            print("[pal] could not parse a palette out of the reply; raw reply kept above")
            if a.exit_after:
                srv.send("REQ 3 EXEC EXIT")
                srv.drain(1.0)
            return 3
        if a.exit_after:
            print("[mcp] asking DOSBox-X to exit")
            srv.send("REQ 3 EXEC EXIT")
            srv.drain(1.5)
    finally:
        srv.close()
        if proc:
            time.sleep(1.0)
            proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
