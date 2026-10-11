"""Does the disk's AUTOEXEC.BAT actually run on this HDI?

The image is configured with `SHELL = GO.EXE` in the ROOT config.sys (and
`SHELL = GO.EXE` again in PD2D\\config.sys), i.e. the DOS shell is the game
loader, not COMMAND.COM. Whether AUTOEXEC.BAT is executed before that shell
takes over decides the whole in-guest dumper plan, so this test answers it
directly instead of assuming.

It injects a minimal AUTOEXEC.BAT that writes one marker file to C: and one to
Z: (DOSBox-X's host-backed drive), boots the image, and afterwards reports which
markers exist. Run it on a *copy* of the image.

    python tools\\test_autoexec_runs.py _hdi_test\\pd2s_probe.hdi --timeout 40
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hdi98 import open_fs                       # noqa: E402
from inject_paldump import put_file, del_file   # noqa: E402

BATCH = (
    "@ECHO OFF\r\n"
    "ECHO AUTOEXEC-RAN > C:\\AERAN.TXT\r\n"
    "ECHO AUTOEXEC-RAN > Z:\\AERAN.Z\r\n"
    "START.COM\r\n"
).encode("ascii")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--exe", default=r"D:\Games\DOSBox-X\dosbox-x.exe")
    ap.add_argument("--conf", default=str(HERE / "run_inject_probe.conf"))
    ap.add_argument("--timeout", type=float, default=40.0)
    ap.add_argument("--workdir", default=str(HERE.parent.parent))
    a = ap.parse_args()

    disk, fs = open_fs(a.image)
    for name in ("AERAN.TXT", "AERAN.BAK"):
        try:
            del_file(fs, name)
        except SystemExit:
            pass
    if not any(e.display_name == "AUTOEXEC.ORI" for _, e in fs.walk('/')):
        print(put_file(fs, "AUTOEXEC.ORI", fs.read_file(fs.resolve_path("/AUTOEXEC.BAT"))))
    print(put_file(fs, "AUTOEXEC.BAT", BATCH))
    disk.save()

    zmark = Path(a.workdir) / "AERAN.Z"
    if zmark.exists():
        zmark.unlink()

    print(f"[run] booting {a.image} for {a.timeout:.0f}s ...")
    proc = subprocess.Popen([a.exe, "-conf", a.conf, "-working-dir", a.workdir],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    time.sleep(a.timeout)
    proc.terminate()
    time.sleep(2.0)

    print("\n=== result ===")
    print(f"Z:\\AERAN.Z on host        : {'YES' if zmark.exists() else 'no'}")
    disk2, fs2 = open_fs(a.image)
    e = fs2.resolve_path("/AERAN.TXT")
    print(f"C:\\AERAN.TXT on the image : {'YES' if e else 'no'}")
    if e:
        print("   content:", fs2.read_file(e))
    if zmark.exists():
        print("   Z content:", zmark.read_bytes())
    print("\nAUTOEXEC.BAT does not run -> the dumper must be hooked after the "
          "shell starts (patch GO.EXE / BATCPTMP.BAT instead)." if not (e or zmark.exists())
          else "\nAUTOEXEC.BAT runs -> the in-guest dumper will fire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
