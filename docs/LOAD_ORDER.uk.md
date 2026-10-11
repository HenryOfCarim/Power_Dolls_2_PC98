> 🌐 **Українська** · [English](LOAD_ORDER.md)

# Порядок завантаження з HDI та де живе декодер

## 1. Ланцюг запуску

Відновлено з аналізу `AUTOEXEC.BAT`, `START.COM`, `GO.EXE`, `PD2SHELL.EXE`
(усі — у корені HDI-образу; `hdi/` у цьому робочому просторі — це вже
розпакований образ).

```
BIOS
 └─ IO.SYS / MSDOS.SYS                 (MS-DOS)
     └─ CONFIG.SYS                    FILES=10, BUFFERS=20,
        │                             DEVICE=A:\DOS\HIMEM.SYS, DOS=HIGH,UMB
        └─ COMMAND.COM
            └─ AUTOEXEC.BAT           -> START.COM
                └─ START.COM          резидентний перехоплювач INT 21h
                   │  У ТІЛІ START.COM (COM-адреса 0x0B7B) лежить готовий
                   │  bat-шаблон, який він записує у BATCPTMP.BAT:
                   │
                   │      @ECHO OFF
                   │      \DOS\MAG -t -K \DOS\X68GP.MAG
                   │      CD PD2D
                   │      GO.EXE
                   │
                   └─ COMMAND.COM /C BATCPTMP.BAT
                       ├─ \DOS\MAG.EXE -t -K \DOS\X68GP.MAG
                       │     «MAKIchan Graphic Loader/Saver for PC-98»
                       │     (виводить свою картинку, ініціалізує режим)
                       └─ GO.EXE
                           ├─ перевіряє $force.id / BOOTDISK.ID / USERDISK.ID
                           │   (створює BOOTDISK.ID, якщо немає; звіряє літеру
                           │    диска через INT 21h AH=19h)
                           └─ один із запусків (INT 21h AH=4Bh):
                                USERDISK.EXE   образ 0x01E9
                                STARTUP.EXE    образи 0x0220, 0x02BC
                                CONVERT.EXE    образ 0x030A
                                PD2SHELL.EXE   образи 0x0335, 0x038F
```

`PD2SHELL.EXE` — меню/оболонка: вантажить `.GCP`-екрани (`normal.gcp`,
`easy.gcp`, `kogado.gcp`, `usagi.gcp`, `detach.gcp`, `pd2title.gcp`) і запускає
через Borland-обгортку (`lcall 0x676, 0x2D5`) `CONVERT.EXE` / `MAKEINIT.EXE`
та сценарні програми.

Сценарні програми — кожна окремий EXE, що сам малює свої ресурси:

| програма | ресурси |
|---|---|
| `STARTUP.EXE` | `kabe4.gcp`, `.gcp`/`.pck` |
| `CHOICE.EXE` | `.gcp`/`.pck` |
| `OPENING.EXE` | `names.pck`, `moji.pck`, `op_wai_*.pck`, `op_as.pck`, `yaoupd1.pck`, `kabe0/3.gcp` |
| `BRIEFING.EXE` | `INIT.PCK`, **`FACE.PCK`**, `chara.gcp`, `plan_g*.gcp`, `hensei_g.gcp`, `busou_*.gcp` |
| `TACTICS.EXE` | `MES.PCK`, `WMES.PCK`, `ANIME.PCK`, `nUNIT.PCK`, `MISSON?D.PCK`, `map_chg.pck`, `HEX_G.GCP`, `ido_g*.gcp` |
| `REPORT.EXE` | `score_g.gcp`, `chara.gcp`, `kabe0.gcp` |

> ⚠️ **Флопі-реліз і HDI-реліз — різні збірки.** Не монтувати разом: гра
> запускає не ту версію і зависає. `FACE.PCK` у них відрізняється (36 записів
> проти 38).

---

## 2. Головний підозрюваний

**`CONVERT.EXE`, функція за образом `0x54E6`** (`lcall 0x539, 0x156`) — це
декодер. Чому саме він:

* це конвертер/пакувальник: володіє обома розширеннями `.pck`/`.gcp`, має
  рядки `rb`/`wb`, `File is not found <%s>`, `..\pd2`, `PD2RECnn.BIN`;
* **не** запакований EXEPACK'ом і має повну таблицю релокацій (`nreloc = 416`),
  тому його образ читається безпосередньо.

---

## 3. Розташування декодера в усіх бінарниках

Тіло декодера — 539 байтів (`CONVERT.EXE` образ `0x54E6 … 0x5701`).

Сигнатури для пошуку (без релокацій, тому збігаються дослівно):

```
SIG_NIB  (образ CONVERT 0x566B)
  c4 5e 06 26 8b 47 02 25 f0 00 c1 e0 04 26 09 07 26 8b 47 02
  25 0f 00 05 02 00 26 89 47 02 26 c7 47 08 00 00

SIG_BIT  (образ CONVERT 0x5514)
  26 d1 6f 0a 26 8b 47 0a a9 00 01 75
```

Зсув тіла = зсув сигнатури − `0x185`.

Існують **дві форми прологу**, тому «якір» (обчислений від сигнатури) і
«вхід» (справжній початок функції) можуть різнитися на 2 байти:

```
enter 6,0                        c8 06 00 00      вхід == якір
push bp / mov bp,sp / sub sp,6   55 8b ec 83 ec 06   вхід == якір − 2
```

| файл | файл, байтів | hdr | образ | **вхід (образ)** | якір | файловий зсув | сигнатури |
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

**Немає декодера:** `GO.EXE`, `PD2SHELL.EXE`, `MAKEINIT.EXE`,
`EMI/NARU/SAMI.COM`, `MAG.EXE` (перевірено за шістьма характерними
константами кодека — 0/6).

### Дві різні компіляції

У 13 бінарниках код **байт-у-байт однаковий** із `CONVERT.EXE` від сигнатури
далі; різняться лише 12 байтів, і **всі вони — імедіати `lcall`** на рантайм
(`fgetc` за образом `0x22CE`, `exit` за `0x3CD`). Це один статично злінкований
бібліотечний рутин.

`OPENING.EXE` і `REPORT.EXE` (*) — **та сама функція, але скомпільована без
інлайнінгу** допоміжної `getc`:

```
CONVERT   ... a9 00 01 75 48   26 8b 9f 1d 10 ff 0f 7c 14 8b 5e 06 ...
OPENING   ... a9 00 01 75 18   26 ff b7 1d 10 90 0e e8 d8 01 59 89 ...
                              ^ виклик підпрограми замість вбудованого коду
```

Тому перевірка ідентичності для них інша: п'ять із шести характерних констант
кодека присутні (немає лише послідовності баз+маска циклу копіювання —
її теж перекомпоновано). Це не заважає: **жоден архів, який використовують
`OPENING`/`REPORT`, не містить картинок формату з 12-байтовим заголовком** —
вони малюють `.GCP`-екрани (`kabe0.gcp`, `chara.gcp`, `score_g.gcp`) і
`.pck`-и з display-list'ами (`op_wai_*.pck`, `names.pck`).

Перевіряється автоматично:

```powershell
python tools\verify.py --data ..\hdi\PD2D --floppy ..
```

---

## 4. Як обійти «стіну з DGROUP»

Xref-и на імена `.pck`/`.gcp` довгий час вважалися нерозв'язними, бо літерал у
коді не дорівнює зсуву рядка в образі — він **DGROUP-відносний**. Насправді
DGROUP читається з точки входу EXE:

```
CONVERT.EXE  образ 0x0000:  BA 21 09              mov dx,0x0921  -> DGROUP = образ 0x9210
TACTICS.EXE  образ 0x0000:  BA 6B 17              mov dx,0x176B  -> DGROUP = образ 0x176B0
PD2SHELL.EXE образ 0x0000:  BA D1 08              mov dx,0x08D1  -> DGROUP = образ 0x8D10
BRIEFING.EXE                                                      -> DGROUP = образ 0x1D480
GO.EXE       образ 0x0000:  8C D8 / BB 13 01 / 8E DB             -> DGROUP = образ 0x1130
```

Далі:

```
DS-зміщення рядка = зсув_в_образі − DGROUP
```

і код шукається як 16-бітний імедіат цього зміщення. Це одразу дало всі
xref-и, наприклад:

| рядок | образ | DS | сайт у коді |
|---|---:|---:|---:|
| `.pck` (CONVERT) | 0x10D6C | 0x7B5C | 0x5752 (`push 0x7B5C`) |
| `.gcp` (CONVERT) | 0x10D67 | 0x7B57 | 0x5741 |
| `pal98 grb` (CONVERT) | 0x10D79 | 0x7B69 | 0x66CC |
| `kabe2.gcp` (CONVERT) | 0x10B0E | 0x78FE | 0x34C8 |
| `userdisk.exe` (GO) | 0x0116F | 0x003F | 0x01C9 |

> Увага: упаковані EXEPACK'ом EXE (`BRIEFING`, `CHOICE`, `OPENING`, `REPORT`,
> `STARTUP`, `MAKEINIT`) мають `nreloc = 0` і точку входу в кінці файлу, але
> **їхній образ не стиснутий** — EXEPACK там стискає лише таблицю релокацій
> (стаб за образом `0x25192` у `BRIEFING`, релок-декодер за `0x251FC`). Тому
> зсуви в образі чинні, і рядки читаються за звичайною формулою.

---

## 5. Карта `EXEC` (хто кого запускає)

Шукається як `mov ax,0x4B00 / int 21h` або `mov ah,0x4B / int 21h`.

| бінарник | сайтів EXEC | запускає |
|---|---:|---|
| `GO.EXE` | 6 | `userdisk.exe`, `startup.exe` (×2), `convert.exe`, `pd2shell.exe` (×2) |
| `PD2SHELL.EXE` | через Borland-обгортку | `convert.exe`, `makeinit`, сценарні EXE |

Для `GO.EXE` шість сайтів лежать за образами `0x01E9`, `0x0220`, `0x02BC`,
`0x030A`, `0x0335`, `0x038F`.

---

## 6. Корисні факти середовища (щоб не перевіряти вдруге)

* Робочий спосіб завантаження HDI у DOSBox-X: `IMGMOUNT C "<hdi>"` + `BOOT C:`
  у `[autoexec]`. Прямий `BOOT "<file.hdi>"` падає з *«Failed to open disk
  image»*.
* DOSBox-X **тихо ігнорує конфіг**, якщо запускати без `-conf`.
* `debuggerrun = debugger` зупиняє старт — виглядає як падіння.
* Автозбереження циклічно перезаписує слоти; для архівування потрібен широкий
  діапазон і/або скрипт-сторож.
* `.sav` — це ZIP: `Memory` (17 055 880 байтів гостьової RAM), `Vga`
  (1 104 208 байтів), `CPU` (21 106 744) тощо.
* Маппінг `Vga` → GVRAM: `base = 0x07C000`, крок між площинами `0x10000`,
  кожна площина 400 рядків × 80 байтів. Це **не** фізичний крок GVRAM
  (`0x8000`) — саме через це ранні рендери були шумом.
