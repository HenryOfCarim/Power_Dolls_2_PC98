> 🌐 **English** · [Українська](LOAD_ORDER.uk.md)

# HDI boot/load order, and where the decoder lives

## 1. The boot chain

Recovered from `AUTOEXEC.BAT`, `START.COM`, `GO.EXE` and `PD2SHELL.EXE` (all at
the root of the HDI image; `hdi/` in this workspace is that image already
unpacked).

```
BIOS
 └─ IO.SYS / MSDOS.SYS                 (MS-DOS)
     └─ CONFIG.SYS                    FILES=10, BUFFERS=20,
        │                             DEVICE=A:\DOS\HIMEM.SYS, DOS=HIGH,UMB
        └─ COMMAND.COM
            └─ AUTOEXEC.BAT           -> START.COM
                └─ START.COM          resident INT 21h interceptor
                   │  INSIDE START.COM (COM address 0x0B7B) sits a ready-made
                   │  batch template which it writes to BATCPTMP.BAT:
                   │
                   │      @ECHO OFF
                   │      \DOS\MAG -t -K \DOS\X68GP.MAG
                   │      CD PD2D
                   │      GO.EXE
                   │
                   └─ COMMAND.COM /C BATCPTMP.BAT
                       ├─ \DOS\MAG.EXE -t -K \DOS\X68GP.MAG
                       │     "MAKIchan Graphic Loader/Saver for PC-98"
                       │     (draws its own picture, initialises the mode)
                       └─ GO.EXE
                           ├─ checks $force.id / BOOTDISK.ID / USERDISK.ID
                           │   (creates BOOTDISK.ID when missing; verifies the
                           │    drive letter via INT 21h AH=19h)
                           └─ one of the following (INT 21h AH=4Bh):
                                USERDISK.EXE   image 0x01E9
                                STARTUP.EXE    images 0x0220, 0x02BC
                                CONVERT.EXE    image 0x030A
                                PD2SHELL.EXE   images 0x0335, 0x038F
```

`PD2SHELL.EXE` is the menu/shell: it loads `.GCP` screens (`normal.gcp`,
`easy.gcp`, `kogado.gcp`, `usagi.gcp`, `detach.gcp`, `pd2title.gcp`) and spawns
`CONVERT.EXE` / `MAKEINIT.EXE` and the scenario programs through a Borland
wrapper (`lcall 0x676, 0x2D5`).

The scenario programs are separate EXEs, each drawing its own assets:

| program | assets |
|---|---|
| `STARTUP.EXE` | `kabe4.gcp`, `.gcp`/`.pck` |
| `CHOICE.EXE` | `.gcp`/`.pck` |
| `OPENING.EXE` | `names.pck`, `moji.pck`, `op_wai_*.pck`, `op_as.pck`, `yaoupd1.pck`, `kabe0/3.gcp` |
| `BRIEFING.EXE` | `INIT.PCK`, **`FACE.PCK`**, `chara.gcp`, `plan_g*.gcp`, `hensei_g.gcp`, `busou_*.gcp` |
| `TACTICS.EXE` | `MES.PCK`, `WMES.PCK`, `ANIME.PCK`, `nUNIT.PCK`, `MISSON?D.PCK`, `map_chg.pck`, `HEX_G.GCP`, `ido_g*.gcp` |
| `REPORT.EXE` | `score_g.gcp`, `chara.gcp`, `kabe0.gcp` |

> ⚠️ **The floppy release and the HDI release are different builds.** Do not
> mount them together: the game starts the wrong one and stalls. `FACE.PCK`
> differs between them (36 entries versus 38).

---

## 2. The prime suspect

**`CONVERT.EXE`, function at image `0x54E6`** (`lcall 0x539, 0x156`) is the
decoder. Why this one:

* it is the converter/packer: it owns both the `.pck`/`.gcp` extensions and
  carries the strings `rb`/`wb`, `File is not found <%s>`, `..\pd2`,
  `PD2RECnn.BIN`;
* it is **not** EXEPACK-compressed and has a full relocation table
  (`nreloc = 416`), so its image can be read directly.

---

## 3. Decoder locations in every binary

The decoder body is 539 bytes (`CONVERT.EXE` image `0x54E6 … 0x5701`).

Signatures to search for (relocation-free, so they match verbatim):

```
SIG_NIB  (CONVERT image 0x566B)
  c4 5e 06 26 8b 47 02 25 f0 00 c1 e0 04 26 09 07 26 8b 47 02
  25 0f 00 05 02 00 26 89 47 02 26 c7 47 08 00 00

SIG_BIT  (CONVERT image 0x5514)
  26 d1 6f 0a 26 8b 47 0a a9 00 01 75
```

The body offset = signature offset − `0x185`.

There are **two prologue forms**, so the "anchor" (computed from the signature)
and the "entry" (the real start of the function) can differ by 2 bytes:

```
enter 6,0                        c8 06 00 00          entry == anchor
push bp / mov bp,sp / sub sp,6   55 8b ec 83 ec 06     entry == anchor - 2
```

| file | bytes | hdr | image | **entry (image)** | anchor | file offset | signatures |
|---|---:|---:|---:|---:|---:|---:|---|
| `hdi/PD2D/CONVERT.EXE` | 81744 | 2560 | 79184 | **0x0054E6** | 0x0054E6 | 0x005EE6 | NIB+BIT |
| `hdi/PD2D/TACTICS.EXE` | 398192 | 5632 | 147472 | **0x0046BE** | 0x0046BE | 0x005CBE | NIB+BIT |
| `hdi/PD2D/BRIEFING.EXE` | 156783 | 1216 | 155567 | **0x00E915** | 0x00E917 | 0x00EDD5 | NIB+BIT |
| `hdi/PD2D/STARTUP.EXE` | 41489 | 1088 | 40401 | **0x0055A8** | 0x0055A8 | 0x0059E8 | NIB+BIT |
| `hdi/PD2D/CHOICE.EXE` | 79267 | 640 | 78627 | **0x00459C** | 0x00459E | 0x00481C | NIB+BIT |
| `hdi/PD2D/OPENING.EXE` | 59179 | 880 | 58299 | **0x005809** | 0x00580B | 0x005B79 | BIT * |
| `hdi/PD2D/REPORT.EXE` | 96389 | 1008 | 95381 | **0x00597D** | 0x00597F | 0x005D6D | BIT * |
| `disk 1/USERDISK.EXE` | 42357 | 912 | 41445 | **0x0056FC** | 0x0056FC | 0x005A8C | NIB+BIT |
| `disk 5/INST.EXE` | 70288 | 4096 | 66192 | **0x0074B7** | 0x0074B7 | 0x0084B7 | NIB+BIT |
| `disk 5/CONVERT.EXE` | 62368 | 2560 | 59808 | **0x005ECA** | 0x005ECA | 0x0068CA | NIB+BIT |
| `disc 2/BRIEFING.EXE` | 138559 | 1056 | 137503 | **0x00C4A1** | 0x00C4A3 | 0x00C8C1 | NIB+BIT |
| `disc 2/CHOICE.EXE` | 76779 | 656 | 76123 | **0x00448A** | 0x00448C | 0x00471A | NIB+BIT |
| `disc 2/STARTUP.EXE` | 40525 | 608 | 39917 | **0x005418** | 0x005418 | 0x005678 | NIB+BIT |
| `disk 3/TACTICS.EXE` | 313904 | 5632 | 139136 | **0x00464E** | 0x00464E | 0x005C4E | NIB+BIT |
| `disk 4/REPORT.EXE` | 95095 | 944 | 94151 | **0x005742** | 0x005744 | 0x005AF2 | NIB+BIT |

**No decoder:** `GO.EXE`, `PD2SHELL.EXE`, `MAKEINIT.EXE`, `EMI/NARU/SARI.COM`,
`MAG.EXE` (checked against six distinctive codec constants — 0/6).

### Two different compilations

In 13 binaries the code is **byte-for-byte identical** to `CONVERT.EXE` from the
signature onwards; only 12 bytes differ, and **all of them are `lcall`
immediates** pointing at the runtime (`fgetc` at image `0x22CE`, `exit` at
`0x3CD`). It is one statically linked library routine.

`OPENING.EXE` and `REPORT.EXE` (*) are **the same function compiled without
inlining** the buffered `getc` helper:

```
CONVERT   ... a9 00 01 75 48   26 8b 9f 1d 10 ff 0f 7c 14 8b 5e 06 ...
OPENING   ... a9 00 01 75 18   26 ff b7 1d 10 90 0e e8 d8 01 59 89 ...
                              ^ a subroutine call instead of inlined code
```

So the identity check is different for them: five of the six distinctive codec
constants are present (only the base+mask sequence of the copy loop is missing —
it too was re-scheduled). This does not get in the way: **none of the archives
used by `OPENING`/`REPORT` contains pictures in the 12-byte-header format** —
they draw `.GCP` screens (`kabe0.gcp`, `chara.gcp`, `score_g.gcp`) and `.pck`
files holding display lists (`op_wai_*.pck`, `names.pck`).

Checked automatically:

```powershell
python tools\verify.py --data ..\hdi\PD2D --floppy ..
```

---

## 4. How to get past the "DGROUP wall"

Cross-references to `.pck`/`.gcp` names were long considered unsolvable, because
the literal in the code does not equal the string's image offset — it is
**DGROUP-relative**. In fact DGROUP can be read from the EXE entry point:

```
CONVERT.EXE  image 0x0000:  BA 21 09              mov dx,0x0921  -> DGROUP = image 0x9210
TACTICS.EXE  image 0x0000:  BA 6B 17              mov dx,0x176B  -> DGROUP = image 0x176B0
PD2SHELL.EXE image 0x0000:  BA D1 08              mov dx,0x08D1  -> DGROUP = image 0x8D10
BRIEFING.EXE                                                      -> DGROUP = image 0x1D480
GO.EXE       image 0x0000:  8C D8 / BB 13 01 / 8E DB             -> DGROUP = image 0x1130
```

Then:

```
DS offset of a string = image offset - DGROUP
```

and the code is found as a 16-bit immediate of that offset. This immediately
produced every cross-reference, for example:

| string | image | DS | code site |
|---|---:|---:|---:|
| `.pck` (CONVERT) | 0x10D6C | 0x7B5C | 0x5752 (`push 0x7B5C`) |
| `.gcp` (CONVERT) | 0x10D67 | 0x7B57 | 0x5741 |
| `pal98 grb` (CONVERT) | 0x10D79 | 0x7B69 | 0x66CC |
| `kabe2.gcp` (CONVERT) | 0x10B0E | 0x78FE | 0x34C8 |
| `userdisk.exe` (GO) | 0x0116F | 0x003F | 0x01C9 |

> Note: EXEPACK-packed EXEs (`BRIEFING`, `CHOICE`, `OPENING`, `REPORT`,
> `STARTUP`, `MAKEINIT`) have `nreloc = 0` and an entry point near EOF, but
> **their image is not compressed** — EXEPACK there compresses only the
> relocation table (the stub at `BRIEFING` image `0x25192`, the relocation
> decoder at `0x251FC`). Image offsets therefore remain valid and strings can be
> read with the usual formula.

---

## 5. The `EXEC` map (who spawns whom)

Found as `mov ax,0x4B00 / int 21h` or `mov ah,0x4B / int 21h`.

| binary | EXEC sites | spawns |
|---|---:|---|
| `GO.EXE` | 6 | `userdisk.exe`, `startup.exe` (×2), `convert.exe`, `pd2shell.exe` (×2) |
| `PD2SHELL.EXE` | via a Borland wrapper | `convert.exe`, `makeinit`, the scenario EXEs |

For `GO.EXE` the six sites are at images `0x01E9`, `0x0220`, `0x02BC`, `0x030A`,
`0x0335`, `0x038F`.

---

## 6. Useful environment facts (so you do not re-test them)

* The working way to boot the HDI in DOSBox-X is `IMGMOUNT C "<hdi>"` plus
  `BOOT C:` in `[autoexec]`. A direct `BOOT "<file.hdi>"` fails with
  *"Failed to open disk image"*.
* DOSBox-X **silently ignores a config** unless it is launched with `-conf`.
* `debuggerrun = debugger` halts startup — it looks exactly like a crash.
* Autosave cycles slots and overwrites them; archiving needs a wide range and/or
  a watcher script.
* A `.sav` is a ZIP: `Memory` (17,055,880 bytes of guest RAM), `Vga`
  (1,104,208 bytes), `CPU` (21,106,744), and so on.
* `Vga` → GVRAM mapping: `base = 0x07C000`, plane stride `0x10000`, each plane
  400 rows × 80 bytes. This is **not** the physical GVRAM stride (`0x8000`) —
  which is why early renders came out as noise.
