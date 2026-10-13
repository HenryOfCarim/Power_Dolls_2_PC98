> 🌐 **English** · [Українська](PALETTE_TABLES.uk.md)

> This file supplements [`PALETTE.md`](PALETTE.md); parts of its conclusions are
> **corrected** below.
>
> **Just want the in-game colours?** The "read first" section of
> [`PALETTE.md`](PALETTE.md) is the short version: the extractor's default palette
> is **not** the game's, and `--pal-exe FILE.EXE:0xOFFSET` is the fix. This file
> explains where those tables come from.

# Where the screens' palettes really are: the tables inside the EXEs

## 1. In short

The earlier conclusion ("the palettes of the artwork screens are not in the
files, capture them from the emulator") is **wrong**. The palettes are in the
files — inside the **EXEs**, as banks of 48-byte tables (stride `0x60`/`0xC0`) —
and the code hands the right table to the palette writer (`BRIEFING.EXE` image
`0x10A59`).

Verified against live emulator dumps: the palette that was on screen matches a
stored table **16/16**.

## 2. Why it was not found before — two reasons

| cause | how it shows up |
|---|---|
| **Channel order.** In Power Dolls 2 the tables are stored as **(B, R, G)**: an entry is `(byte[3i+1], byte[3i+2], byte[3i+0])`. Earlier searches only tried `rgb`/`grb`/`bgr` — plain component swaps, which never produce a cyclic rotation | read as `rgb` a table scores 6/16, read as `gbr` it scores **16/16** |
| **A reference palette with permuted indices.** The "16 colours measured from a screenshot of the equip screen" hold the same colour *set* as the real palette but attach them to **different entry numbers** | identical multisets, index map `1→7 2→8 3→9 …`; element-wise comparison could never match |

> **Power Dolls 1 is the other way round.** Its `PREMIUM.EXE` / `STARTUP.EXE`
> store the same kind of table as **(G, R, B)** — `(byte[3i+1], byte[3i+0],
> byte[3i+2])` — which the frames dumped from the running game prove (11 of 20
> match a PD1 table under `G,R,B` and none under `B,R,G`; `PREMIUM.EXE 0xEDF1`
> and PD2's `STARTUP.EXE 0x9311` are the same 16 colours with the first and third
> bytes exchanged). Pass the order explicitly to the tools:
> `--pal-exe "PREMIUM.EXE:0xEDF1:G,R,B"`, `pd2pal.py --exe "...:G,R,B"`. See
> [`PALETTE.md`](PALETTE.md) §1.

A third factor is the **fade ladder**: the game dims palettes at run time
(`scale = k/16`), so a base table must be searched for across that ladder,
otherwise a screen caught mid-fade "is not found".

## 3. The tool

```
python tools\pal_tables.py --list  [--data DIR ...] [--out tables.txt]
python tools\pal_tables.py --dump  OUTDIR [--data DIR ...]
python tools\pal_tables.py --find  DUMP_analog.rgb [--tol 1]
python tools\pal_tables.py --self-test
```

* `--list` — inventory: **127 tables in 22 files (59 distinct palettes)** across
  the shipped HDI+FDI data;
* `--dump` — every table as a JASC `.pal` (`<EXE>_<offset>.pal`);
* `--find` — locate the source of a given palette; prints `file + offset +
  scale`, and falls back to a loose pass when the strict filter finds nothing;
* `--self-test` — a control proving the search can fire at all (a negative
  result is worthless without one).

Table criterion: 48 bytes, all `<= 0x0F`, first entry black, a white entry
present, at least 10 distinct colours. The **last** entry is not necessarily
white — in `TACTICS.EXE 0x1ECA4` white sits at index 7 and the last entry is
`fdb`.

## 4. Result of the capture run (live dumps from DOSBox-X)

Snapshots: `out/pal/equip/*_analog.rgb`; full report: `out/pal/equip/FOUND.md`.

| snapshot | source in the files | scale |
|---|---|---|
| `equip_002` | `STARTUP.EXE` @ `0x9311` (+ copies in `USERDISK.EXE`, `INST.EXE`, FDI images) | 15/16 |
| `equip_003` | `PD2SHELL.EXE` @ `0x9826` | 13/16 (dimmed) |
| `equip_006` | `PD2SHELL.EXE` @ `0x98E6` (shell/menu palette) | 15/16 |
| `equip_008` | `BRIEFING.EXE` @ `0x234C6` — also in `CONVERT.EXE`, `OPENING.EXE` @ `0xCF0E`, `REPORT.EXE` @ `0x13E5C` and `0x169A2`, `TACTICS.EXE` @ `0x2290E` | 15/16 |
| `equip_009` | `TACTICS.EXE` @ `0x1ECA4` (gameplay/tactics palette) | 15/16 |

`equip_008` is the equip screen's palette: its 16 colours are exactly the set of
the old `equip_obs` reference (see §2).

Not found, and why that is expected:

* `equip_000` — the BIOS default PC-98 palette (the boot menu, before the game);
* `equip_001` — a bootleg/cracktro logo screen (not a game screen). Checked as a
  48-byte table in 4-, 6- and 8-bit form, and also inside the MAKI02/MAG files
  (`DOS\\X68GP.MAG`, `DOS\\MAG.EXE`) — no table; that palette is produced by code;
* `equip_004`, `equip_005`, `equip_007` — a fade to black and a colour-cycle
  animation (`577 9bb cee` repeating), i.e. no table exists.

## 5. Visual check

With the right palette the extracted artwork has the right colours:

```powershell
python pd2extract.py --pck "..\power dolls 2 HDI\_unpacked\PD2D\FACE.PCK" `
    out\equip_face --pal out\pal\tables\BRIEFING.EXE_0234c6.pal
```

The `FACE_000…` portraits come out with natural skin and hair tones (see
`out/equip_face/FACE/FACE_000.png`); the same pixels through the extractor's
default ramp are a green-and-blue mess. Three palettes side by side:
[`PALETTE.md`](PALETTE.md) → "read first" (`img/palette_default_vs_screen.png`).

The palette is chosen **per screen**, not per archive: `BRIEFING.EXE 0x234C6` is
the equip/artwork screen's table (confirmed by a live capture, `equip_008`), and
`TACTICS.EXE 0x1ECA4` is gameplay. `GAMEOVER.ASK` renders with any of them and
none has been confirmed by a capture of that screen — treat it as unmapped until
one is (see §6).

## 6. Still open

* systematically map **all** 59 distinct tables (127 positions) to screens —
  needs a dump per screen or a trace of the callers of the `0x10A59` routine.
  **Until that is done, four screens have a known palette** (the table in §4) and
  everything else needs a capture: `pd2extract.py --pal capture\game.pal`, or
  `tools/pal_tables.py --find capture\game_analog.rgb` to identify the shipped
  table and then `--pal-exe`. See also [`PALETTE.md`](PALETTE.md), "read first";
* `equip_001` — the one screen of the run whose palette is not in the files
  (a bootleg logo, so not a game screen);
* the 32-byte packed palettes in `.GCP` — separate, see [`PALETTE.md`](PALETTE.md) §2.
