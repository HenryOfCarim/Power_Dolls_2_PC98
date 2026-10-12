> 🌐 **English** · [Українська](ADVANCED_PD2.uk.md)

# Advanced Power Dolls 2 (1996) — the `.fdd` images

## 1. What this release is

Advanced PD2 is **not a standalone game but a patch/expansion over the base
Power Dolls 2**. Evidence from the disks themselves (disk 2 carries a text
makefile next to the installer fragments):

```
.SILENT
.SUFFIXES : .idx .bnd .org .chg
pd2dt.idx : MES2.PCK WMES2.PCK INIT2.PCK NPC2.PCK SMAP1.PCK \
            DATAU.PCK MUNIT.PCK TUNIT.PCK WEAPON.PCK MMAP1.PCK \
            CHARA.PCK FACE.PCK DFACE.PCK EVKAO.PCK MAP_CHG.PCK \
            MISSONSD.PCK MISSONMD.PCK MISSONHD.PCK MISSONPD.PCK MISSONCD.PCK \
            EVENT.PCK ARMS.PCK SCORE_N.PCK \
```

The installer **assembles** new files from an existing PD2 installation using
`.org`/`.chg`/`.idx`/`.bnd` rules. Files on the disks carry the base game's names
(`PD2SHELL.EXE`, `TACTICS1.EXE`, …) but their content is patch/fragment data, not
finished executables (only `GO.EXE`, `BRIEF2.EXE`, `BRIEF3.EXE` start with `MZ`).

## 2. The `.fdd` layout (no BPB — recovered from the data)

| item | value |
|---|---|
| directory | `0xD7FC`, 192 entries of 32 bytes |
| first cluster | `+0x1A` (u16), size | `+0x1C` (u32) |
| data area | `0xEFFC`, cluster **1024** bytes, `spc=1` |
| contiguity | every file is contiguous: `cluster[k+1] = cluster[k] + ceil(size/1024)` (17/17 pairs verified on disk 1) |
| quirk | the image **lacks the disk's first 4 bytes** (the real boot sector would start at `-4`); on disks 4–8 a copy of it sits at `0xC3FC` |
| sizes | 1,092,604 / 763,900 / 765,948 / 1,311,740 ×5 / 1,038,332 bytes |

There is no BPB at all (the first sector is `VFD1.00` plus zeros), so
`tools/img_extract.py` gained a "FAT without a BPB" detector: it finds the
directory, then picks the entry count (16…256) and cluster size from the
**contiguity of the files**, from `.EXE` entries really starting with `MZ`, and
from the data filling the image to its end.

Control checks: `GO.EXE` (disk 1) = `MZ`, `BRIEF2.EXE` (disk 2) = `MZ`,
`PD2DT.000…005` = `BI` ("BIGFILE") — all consistent.

## 3. What is on the disks

| disk | contents |
|---|---|
| 1 | installer and first modules: `INST.EXE`, `HD_INST.SCR`, `GO.EXE` (a real EXE), `PD2SHELL.EXE`, `CONVERT.EXE`, `BRIEFING.EXE`, `TACTICS1.EXE`, `STARTUP.EXE`, `CONTROL.EXE`, `MAKEINIT.EXE`, `REPORT.EXE`, `KABE3.GCP`, `FONT_ANK.DAT`, `EMI/NARU/SARI/CDP.COM` |
| 2 | `BRIEF2.EXE` (MZ), `TACTICS2.EXE`, `REPORT2.EXE`, `PD2DT.IDX`, `OPENING.EXE` |
| 3 | `BRIEF3.EXE` (MZ), `TACTICS3.EXE`, `REPORT3.EXE`, `UNINST.EXE`, `DFACE2.PCK`, `COMMENT.TXT` |
| 4–8 | one container volume each: `PD2DT.000` … `PD2DT.004` (1,250,304 bytes each) |
| 9 | `PD2DT.005` (976,796 bytes) |

`PD2DT.000…005` are six parts of **one logical container** `BIGFILE`
(7,228,316 bytes) holding the bundle `PD2DT.BND`.

## 4. What has been found inside the container

* the header `BIGFILE\0` plus member names (`PD2DT   BND`, `PD2DT.BND`);
* the payload is **partly uncompressed**: the 32-byte packed PC-98 palette occurs
  four times at `+0xB` from a `.GCP` start, i.e. real display lists live there
  (four groups carved, e.g. `gcp_002917bb.GCP`, 18,836 bytes with a valid header
  and the default palette);
* the makefile and text file lists mentioned above;
* the rest is high-entropy (compressed), so "MZ" hits inside it are coincidences:
  the 1.4 MB and 0.57 MB "EXEs" carved by MZ anchors turned out to be noise.

Even without unpacking the container, the palettes already pay off: 61 tables /
19 distinct palettes, 11 of them shared with the HDI build of PD2, including
`artwork/equip`, `gameplay` and `startup` (see `out/versions/palette_matrix.md`).

## 5. Open items

1. The `BIGFILE`/`BND` member table (decoder and offsets) — the next step; the
   most reliable route is to disassemble `INST.EXE`/`UNINST.EXE` (the project
   already has `capstone` in `_pylibs`) or to run the installer in DOSBox-X over a
   base PD2 installation and capture the result.
2. The file fragments (`PD2SHELL.EXE` and friends) are patch data; recovering the
   whole "richest version" needs the semantics of `.org`/`.chg`/`.idx`.
