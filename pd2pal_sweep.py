#!/usr/bin/env python3
"""Render one .PCK or .ASK file once for every .pal file in a directory.

Usage:
    python pd2pal_sweep.py FILE.PCK PALETTE_DIR OUTDIR
    python pd2pal_sweep.py FILE.ASK PALETTE_DIR OUTDIR [--raw-geom WxH]

Each palette gets its own subdirectory under OUTDIR, named after the palette
file. Palette files are searched recursively and may be JASC-PAL or another
format accepted by pd2extract.py --pal.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('file', type=Path, help='one .PCK archive or .ASK image')
    ap.add_argument('palette_dir', type=Path, help='directory containing .pal files')
    ap.add_argument('outdir', type=Path, help='output root; one subdirectory is made per palette')
    ap.add_argument('--scale', type=int, default=1, help='integer upscale passed to pd2extract.py')
    ap.add_argument('--raw-geom', metavar='WxH',
                    help='geometry for a raw-block .ASK; passed to pd2extract.py')
    args = ap.parse_args()

    source = args.file.resolve()
    palette_root = args.palette_dir.resolve()
    out_root = args.outdir.resolve()
    if not source.is_file():
        ap.error(f'input file not found: {source}')
    if source.suffix.upper() not in ('.PCK', '.ASK'):
        ap.error(f'input must be a .PCK or .ASK file: {source}')
    if not palette_root.is_dir():
        ap.error(f'palette directory not found: {palette_root}')
    if args.scale < 1:
        ap.error('--scale must be at least 1')

    palettes = sorted(
        (path for path in palette_root.rglob('*')
         if path.is_file() and path.suffix.lower() == '.pal'),
        key=lambda path: str(path).casefold())
    if not palettes:
        ap.error(f'no .pal files found under {palette_root}')

    extractor = Path(__file__).resolve().with_name('pd2extract.py')
    if not extractor.is_file():
        ap.error(f'pd2extract.py not found next to this script: {extractor}')

    mode = '--pck' if source.suffix.upper() == '.PCK' else '--ask'
    failures = 0
    print(f'{len(palettes)} palette(s); input: {source}')
    for index, palette in enumerate(palettes, 1):
        relative = palette.relative_to(palette_root).with_suffix('')
        palette_out = out_root / relative
        command = [
            sys.executable, str(extractor), mode, str(source), str(palette_out),
            '--pal', str(palette), '--scale', str(args.scale),
        ]
        if args.raw_geom:
            command.extend(['--raw-geom', args.raw_geom])

        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace')
        summary = next(
            (line.strip() for line in reversed(result.stdout.splitlines())
             if 'image(s) written to' in line),
            'no extraction summary',
        )
        status = 'ok' if result.returncode == 0 else 'FAILED'
        print(f'[{index}/{len(palettes)}] {palette.relative_to(palette_root)}: {summary} [{status}]')
        if result.returncode != 0:
            failures += 1
            if result.stdout:
                print(result.stdout.rstrip())
            if result.stderr:
                print(result.stderr.rstrip(), file=sys.stderr)

    print(f'Finished: {len(palettes) - failures}/{len(palettes)} palette run(s) succeeded; output: {out_root}')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
