"""Power Dolls 1 / 2 (PC-98) — brute-force palette sweep.

Takes a whole data tree, unpacks **every** picture it can find, collects **every**
palette it can find, and renders each picture once per palette so the right
combination can be picked by eye.

What counts as a picture
------------------------
* `.GCP` — display lists ([`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.md))
* `.PCK` — raster entries *and* display-list entries (both kinds are accepted)
* `.ASK` — raster pictures and "raw block" pictures (`S_ROLL.ASK`)
* a disk image passed with `--image` is unpacked first with
  `tools/img_extract.py`, so a bare `.HDI`/`.FDI`/`.fdd` can be swept directly
* an `.IDX` + `.BND` bundle (`pd2bnd.py`) — Advanced PD2 ships its whole data
  set that way, so `--image APD2.hdi` has to split it to see anything; with
  `--data DIR` add `--split-bundles`

Where the palettes come from
----------------------------
* the 32-byte packed table at `+0xB` of `.GCP` files and display-list `.PCK`
  entries (deduplicated);
* the 48-byte tables inside the game's `EXE`/`COM`/`BIN` files
  (`tools/pal_tables.py`), in the engine's `(B, R, G)` channel order;
  `--orders all` adds the five other permutations of each table;
* every `.pal` under `--palette-dir`;
* the packed `.GCP` ramp: `pd2pal.DEFAULT_PALETTE`, plus the `PC-98` default ramp
  `pd2extract.py` falls back to.

Output
------
    OUTDIR/palettes/<NNN>_<id>.pal     every distinct palette, JASC, 8-bit
    OUTDIR/palettes/index.txt          id -> source, hex string, .pal file
    OUTDIR/sheets/<image>.png          contact sheet: one cell per palette
    OUTDIR/full/<image>/<NNN>_<id>.png one PNG per palette (`--mode full|both`)

A contact sheet is the point of the exercise: rendering 400 images x 60 palettes
as loose files is hundreds of thousands of PNGs, while a sheet is one file per
image and lets you pick the palette with one glance. Each cell is labelled with
the palette number used in `index.txt`; the palette a block carries itself is
marked `*`.

Usage
-----
    python pd2sweep.py --data hdi/PD2D -o out/sweep
    python pd2sweep.py --image "PD2S.HDI" -o out/sweep --orders all
    python pd2sweep.py --data hdi/PD2D -o out/sweep --mode full --max-palettes 8
    python pd2sweep.py --data hdi/PD2D -o out/sweep --images "CHARA*" --list
"""
import argparse
import fnmatch
import os
import re
import shutil
import sys
from pathlib import Path

from pd2extract import PC98
from pd2img import (indices_from_planes, is_image_entry, is_raw_block, parse_archive,
                    parse_entry, planes_from_stream, raw_geometry)
from pd2gcp import DisplayListError, indices as dl_indices, is_display_list, parse_header
from pd2pal import DEFAULT_PALETTE, palette_from_packed, read_pal, write_pal

try:
    import pal_tables
except ImportError:                                   # tools/ ships with the repo
    pal_tables = None

DISK_SUFFIXES = (".HDI", ".FDI", ".FDD", ".IMG", ".D88", ".HDM")
CODE_SUFFIXES = (".EXE", ".COM", ".BIN", ".SYS", ".OVL", ".DRV", ".386")
CODE_MAX = 8_000_000
ORDER_NAMES = ("B,R,G", "R,G,B", "G,R,B", "B,G,R", "R,B,G", "G,B,R")
ORDER_PERMS = ((1, 2, 0), (0, 1, 2), (1, 0, 2), (2, 1, 0), (0, 2, 1), (2, 0, 1))


def slug(text):
    """A filesystem-safe, still readable id."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "x"


class Palette:
    __slots__ = ("id", "source", "rgb", "key", "aliases", "number")

    def __init__(self, pid, source, rgb):
        self.id = pid
        self.source = source
        self.rgb = list(rgb)               # 16 (R,G,B) with 4-bit components
        self.key = tuple(self.rgb)
        self.aliases = []

    @property
    def hex(self):
        return " ".join("%x%x%x" % c for c in self.rgb)

    def file_stem(self):
        return f"{self.number:03d}_{slug(self.id)}"


class Picture:
    __slots__ = ("id", "source", "w", "h", "data", "own")

    def __init__(self, pid, source, w, h, indices, own=None):
        self.id = pid
        self.source = source
        self.w = w
        self.h = h
        self.data = bytes(indices)            # one 0..15 per pixel
        self.own = own                        # the block's own palette, if any


# ------------------------------------------------------------------ unpacking
def unpack_image(path, outdir):
    """Extract a disk image with tools/img_extract.py. -> (root, message)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
    import img_extract
    target = Path(outdir) / slug(Path(path).stem)
    info, err = img_extract.extract(Path(path), target, verbose=False)
    if err:
        return None, err
    return target, f"extracted to {target}"


def split_bundles(root, dest_root=None):
    """Unpack every `.IDX` + `.BND` pair the tree contains.

    Advanced PD2 ships one bundle instead of the game's data files, so a sweep
    that stops at the image's own `.PCK`/`.GCP` files sees almost nothing.  With
    `dest_root` the members go there, otherwise they are carved next to the pair.
    -> list of directories that now hold members.
    """
    try:
        from pd2bnd import BundleError, find_bundles, split
    except ImportError:
        return []
    made = []
    for idx, bnd in find_bundles(root):
        dest = Path(dest_root) / Path(bnd).stem if dest_root \
            else Path(idx).parent / Path(bnd).stem
        if dest.exists():
            made.append(dest)
            continue
        try:
            members, report = split(idx.read_bytes(), bnd.read_bytes(),
                                    dest, verbose=False)
        except (BundleError, OSError) as e:
            print(f"  bundle {idx.name}: {e}", file=sys.stderr)
            continue
        print(f"  bundle {idx.name} + {bnd.name}: {len(members)} member(s) -> {dest}")
        made.append(dest)
    return made


# ------------------------------------------------------------- picture sources
def pictures_from_raster(blob):
    """-> (w, h, indices) for a `.ASK`/`.PCK` raster entry, or None."""
    if not is_image_entry(blob):
        return None
    r = parse_entry(blob)
    planes = planes_from_stream(r["stream_bytes"], r["w"], r["h"])
    return r["w"], r["h"], indices_from_planes(planes, r["w"], r["h"])


def pictures_from_raw(blob):
    """-> (w, h, indices) for a `u32 size` + LZSS "raw block", or None."""
    out = is_raw_block(blob)
    if out is None:
        return None
    geom = raw_geometry(len(out))
    if geom is None:
        return None
    w, h = geom
    planes = planes_from_stream(out, w, h)
    return w, h, indices_from_planes(planes, w, h)


def pictures_from_displaylist(blob):
    if not is_display_list(blob):
        return None
    w, h, data = dl_indices(blob)
    return w, h, data


def collect_pictures(root, want=None, entry_only=None):
    """Walk a directory tree -> [Picture].  `want` is matched on the picture id."""
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in sorted(files):
            path = os.path.join(dirpath, fn)
            up = fn.upper()
            try:
                if up.endswith(".PCK"):
                    for i, blob in parse_archive(path):
                        name = f"{os.path.splitext(fn)[0]}_{i:03d}"
                        if want and not _matches(want, name):
                            continue
                        pic = _one_picture(blob, name, path, raster_ok=True)
                        if pic:
                            out.append(pic)
                elif up.endswith((".ASK", ".GCP")):
                    name = os.path.splitext(fn)[0]
                    if want and not _matches(want, name):
                        continue
                    with open(path, "rb") as f:
                        blob = f.read()
                    pic = _one_picture(blob, name, path, raster_ok=up.endswith(".ASK"))
                    if pic:
                        out.append(pic)
            except Exception as e:                     # a broken file must not stop a sweep
                print(f"  skipped {fn}: {e}", file=sys.stderr)
    return out


def _matches(patterns, name):
    return any(fnmatch.fnmatch(name.casefold(), p.casefold()) for p in patterns)


def _one_picture(blob, name, path, raster_ok):
    """Raster first when the container says so, then display list, then raw block."""
    if raster_ok:
        got = pictures_from_raster(blob)
        if got:
            return Picture(name, path, got[0], got[1], got[2])
    got = pictures_from_displaylist(blob)
    if got:
        own = parse_header(blob)["palette"]
        return Picture(name, path, got[0], got[1], got[2], own)
    if raster_ok:
        got = pictures_from_raw(blob)
        if got:
            return Picture(name, path, got[0], got[1], got[2])
    return None


# ------------------------------------------------------------- palette sources
def collect_palettes(roots, args, seen, out):
    """Append every palette found under `roots` to `out`, deduplicated by value."""

    def add(pid, source, rgb):
        rgb = [tuple(int(c) & 0xF for c in t) for t in rgb]
        key = tuple(rgb)
        if key in seen:
            seen[key].aliases.append(source)
            return
        pal = Palette(pid, source, rgb)
        seen[key] = pal
        out.append(pal)

    # 1. the ramps the extractors fall back to (identical values, one entry)
    add("pc98-default", "PC-98 / .GCP ramp", DEFAULT_PALETTE)

    # 2. packed 32-byte tables carried by .GCP / display-list .PCK entries
    files = []
    for root in roots:
        files += sorted(Path(root).rglob("*")) if os.path.isdir(root) else [Path(root)]
    for p in files:
        if not p.is_file():
            continue
        if p.suffix.upper() == ".GCP":
            try:
                blob = p.read_bytes()
            except OSError:
                continue
            pal = palette_from_packed(blob)
            if pal:
                add(f"packed/{p.stem}", f"{p.name} +0xB", pal)
        elif p.suffix.upper() == ".PCK":
            try:
                for i, blob in parse_archive(str(p)):
                    if is_display_list(blob):
                        pal = palette_from_packed(blob)
                        if pal:
                            add(f"packed/{p.stem}_{i:03d}", f"{p.name}#{i} +0xB", pal)
            except Exception:
                continue

    # 3. every 48-byte table inside the executables
    if pal_tables is not None:
        orders = range(len(ORDER_NAMES)) if args.orders == "all" else (0,)
        for p in files:
            if not p.is_file() or p.suffix.upper() not in CODE_SUFFIXES:
                continue
            try:
                if p.stat().st_size > CODE_MAX:
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            for oi in orders:
                for off, tri in pal_tables.tables_in(data, ORDER_PERMS[oi]):
                    tag = f"{ORDER_NAMES[oi]}" if args.orders != "all" else f"order {ORDER_NAMES[oi]}"
                    add(f"{p.stem}@{off:06x}" + (f"/{ORDER_NAMES[oi]}" if args.orders == "all" else ""),
                        f"{p.name} +{off:#x} ({tag})", tri)

    # 4. loose .pal files
    for extra in args.palette_dir or []:
        for p in sorted(Path(extra).rglob("*.pal")):
            try:
                add(f"pal/{p.stem}", str(p), read_pal(str(p)))
            except Exception as e:
                print(f"  palette {p}: {e}", file=sys.stderr)
    return out


# --------------------------------------------------------------------- output
def write_palettes(pals, outdir):
    root = Path(outdir) / "palettes"
    root.mkdir(parents=True, exist_ok=True)
    lines = ["#  #  id                              source                              RGB (B,R,G order of the game)",
             "#     (* = the palette the block itself carries)"]
    for n, pal in enumerate(pals):
        pal.number = n
        write_pal(str(root / (pal.file_stem() + ".pal")), pal.rgb, "jasc")
        lines.append(f"{n:3d}    {pal.id:<31s} {pal.source:<35s} {pal.hex}")
        if pal.aliases:
            lines.append(f"       {'':31s} aliases: {', '.join(pal.aliases[:6])}"
                         + (" ..." if len(pal.aliases) > 6 else ""))
    with open(root / "index.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return root


def _font(size=11):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                                  # Pillow < 10.1
        return ImageFont.load_default()


def _p_image(pic, pal):
    """The index buffer under one palette, as an RGB-capable `P` image."""
    from PIL import Image
    im = Image.frombytes("P", (pic.w, pic.h), pic.data)
    im.putpalette([c * 17 for rgb in pal.rgb for c in rgb] + [0] * (768 - 48))
    return im


def contact_sheet(pic, pals, cell=160, cols=None, label=True, own_marked=True):
    """One cell per palette -> a PIL image."""
    from PIL import Image, ImageDraw
    cols = cols or max(1, min(len(pals), 1200 // (cell + 8)))
    rows = (len(pals) + cols - 1) // cols
    font = _font(11)
    pad = 4
    lab = 13 if label else 0
    cw, ch = cell + 2 * pad, cell + 2 * pad + lab
    sheet = Image.new("RGB", (cols * cw, rows * ch), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    scale = min(cell / pic.w, cell / pic.h)
    w = max(1, int(round(pic.w * scale)))
    h = max(1, int(round(pic.h * scale)))
    for n, pal in enumerate(pals):
        thumb = _p_image(pic, pal).convert("RGB").resize((w, h), Image.NEAREST)
        x = (n % cols) * cw + pad + (cell - w) // 2
        y = (n // cols) * ch + pad + lab + (cell - h) // 2
        sheet.paste(thumb, (x, y))
        if label:
            mark = "*" if (own_marked and pic.own and pal.rgb == pic.own) else " "
            text = f"{mark}{n} {pal.id}"
            room = max(8, (cw - 2) // 6)
            if len(text) > room:
                text = text[:room - 1] + "\u2026"
            draw.text(((n % cols) * cw + pad, (n // cols) * ch + pad), text,
                      fill=(200, 200, 200), font=font)
    return sheet


def save_full(pic, pals, outdir, scale):
    from PIL import Image
    root = Path(outdir) / "full" / slug(pic.id)
    root.mkdir(parents=True, exist_ok=True)
    for pal in pals:
        im = _p_image(pic, pal).convert("RGB")
        if scale > 1:
            im = im.resize((pic.w * scale, pic.h * scale), Image.NEAREST)
        im.save(root / f"{pal.file_stem()}.png")


# ------------------------------------------------------------------------ CLI
def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", metavar="DIR", help="extracted game data directory")
    src.add_argument("--image", metavar="FILE", help="disk image to unpack first")
    ap.add_argument("-o", "--out", required=True, metavar="DIR")
    ap.add_argument("--mode", choices=("sheets", "full", "both"), default="sheets")
    ap.add_argument("--cell", type=int, default=160, help="contact-sheet cell size in px")
    ap.add_argument("--cols", type=int, help="cells per sheet row")
    ap.add_argument("--scale", type=int, default=1, help="upscale for --mode full")
    ap.add_argument("--orders", choices=("engine", "all"), default="engine",
                    help="channel orders tried for the 48-byte EXE tables")
    ap.add_argument("--palette-dir", action="append", metavar="DIR",
                    help="also sweep every .pal under DIR (repeatable)")
    ap.add_argument("--images", action="append", metavar="GLOB",
                    help="only these picture ids (repeatable)")
    ap.add_argument("--palettes", action="append", metavar="GLOB",
                    help="only these palette ids (repeatable)")
    ap.add_argument("--max-palettes", type=int, default=0,
                    help="cap the palettes per image (0 = all)")
    ap.add_argument("--keep-unpacked", action="store_true",
                    help="with --image, keep the extracted tree and say where")
    ap.add_argument("--split-bundles", action="store_true",
                    help="also unpack every .IDX/.BND pair found under --data "
                         "(into OUTDIR/_bundles); with --image this is automatic")
    ap.add_argument("--list", action="store_true", help="only report what was found")
    a = ap.parse_args()

    out = Path(a.out)
    root = Path(a.data) if a.data else None
    temp = None
    if a.image:
        temp = out / "_unpacked"
        if temp.exists():
            shutil.rmtree(temp)
        root, message = unpack_image(a.image, temp)
        if root is None:
            sys.exit(f"{a.image}: {message}")
        print(f"{message}")

    if not os.path.isdir(root):
        sys.exit(f"not a directory: {root}")

    print(f"scanning {root} ...")
    roots = [root]
    if a.image or a.split_bundles:
        # Advanced PD2 keeps the game inside one bundle; unpack it before looking
        made = split_bundles(root, None if a.image else out / "_bundles")
        if not a.image:                # with --image the members land inside root
            roots += made

    pictures = []
    for r in roots:
        pictures += collect_pictures(r, a.images)
    seen, pals = {}, []
    collect_palettes(roots, a, seen, pals)
    seen2, kept = {}, []
    for p in pals:                                 # keep the collection order, drop empties
        if p.key not in seen2:
            seen2[p.key] = p
            kept.append(p)
    pals = kept
    if a.palettes:
        pals = [p for p in pals if _matches(a.palettes, p.id)]
    if a.orders == "all" and a.palettes is None and a.max_palettes == 0:
        print("note: --orders all multiplies the 48-byte tables by six; "
              "consider --max-palettes or --palettes to keep the sheets readable")

    print(f"{len(pictures)} picture(s), {len(pals)} distinct palette(s)")
    if a.mode in ("full", "both"):
        total = sum(len(pals) for _ in pictures)
        print(f"note: --mode {a.mode} writes about {total} PNG file(s)")
    if a.list:
        for i, p in enumerate(pictures):
            print(f"  {p.id:28s} {p.w:4d}x{p.h:<4d} {'own palette' if p.own else '':11s} {p.source}")
        print(f"\n{len(pals)} palettes:")
        for i, p in enumerate(pals):
            print(f"  {i:3d}  {p.id:32s} {p.source:38s} {p.hex}")
        if temp and not a.keep_unpacked and temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        return

    pal_dir = write_palettes(pals, out)
    print(f"palettes -> {pal_dir}  (index.txt lists every one)")
    sheet_dir = out / "sheets"
    sheet_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    for pic in pictures:
        order = list(pals)
        if pic.own:                                # the block's own palette first
            order.sort(key=lambda p: 0 if p.rgb == pic.own else 1)
        if a.max_palettes:
            order = order[:a.max_palettes]
        if a.mode in ("sheets", "both"):
            sheet = contact_sheet(pic, order, cell=a.cell, cols=a.cols)
            sheet.save(sheet_dir / f"{slug(pic.id)}.png")
        if a.mode in ("full", "both"):
            save_full(pic, order, out, a.scale)
        made += 1
        if made % 25 == 0 or made == len(pictures):
            print(f"  [{made}/{len(pictures)}] {pic.id}")
    if temp and not a.keep_unpacked:
        shutil.rmtree(temp, ignore_errors=True)
    print(f"{made} picture(s) swept with up to {len(pals)} palettes -> {out}")
    if a.mode == "sheets":
        print("open one sheet per picture; the palette the block itself carries is "
              "marked with * and the numbers match palettes/index.txt")


if __name__ == "__main__":
    main()
