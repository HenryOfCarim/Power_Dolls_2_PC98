> 🌐 **Українська** · [English](README.md)

# pd2gfx — Power Dolls 2 (PC-98, Kogado 1994) graphics toolkit

> **English summary.** Reverse-engineered decoder and extraction tools for the
> graphics of *Power Dolls 2* (Kogado, PC-98, 1994). The compressed image format
> is a 4096-byte-ring LZSS (12-bit absolute offset, 4-bit length, LSB-first bit
> stream) reached through three container variants. The image data contains **no
> palette**; the game programs the PC-98 palette through I/O ports
> `0xA8/0xAA/0xAC/0xAE` from a 32-byte packed table that is present in every
> `.GCP` file at offset `0xB`. `pd2img.py` is the library, `pd2extract.py` the
> PNG dumper, `pd2pal.py` the palette tool, `tools/verify.py` the self-check.
> Docs are in Ukrainian; code and docstrings are in English.

Розшифровка й витягування графіки з **Power Dolls 2** (Kogado Software
Products, PC-98, 1994).

Кодек, контейнери й механізм палітри відновлено з дизасемблера
(`CONVERT.EXE`, образ `0x54E6`) і перевірено на всіх 360 зображеннях гри.

---

## Що вирішено

| | статус |
|---|---|
| Контейнери `.ASK`, `.PCK`, «сирий блок» | ✅ повністю |
| Кодек (LZSS) | ✅ повністю, байт-точно |
| Розкладка площин і бітів | ✅ доведено кодом вивантаження в GVRAM |
| Витягування у PNG | ✅ 361 картинка (348 записів `.PCK`, 12 кадрів `.ASK`, «сирий блок» `S_ROLL.ASK`) |
| Механізм установки палітри | ✅ доведено |
| Палітри з `.GCP` / `CHARA.PCK` | ✅ (2 кастомні з 26) |
| Палітра художніх екранів (напр. спорядження) | ✅ таблиці постачаються в самих EXE (48 байтів, порядок каналів B,R,G) — `tools/pal_tables.py`; знімок з емулятора лише вказує, **яку** таблицю бере екран, див. [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.uk.md) |
| `.GCP` як растр | ❌ це display-list для GDC, а не картинка |
| Компресор | ❌ не відновлювався (він є в `CONVERT.EXE`) |

---

## Вимоги

```
Python 3.10+
Pillow            # запис PNG
numpy             # лише для pd2pal.py --shot
```

```powershell
pip install Pillow numpy
```

---

## Швидкий старт

Припускається, що тека з даними гри лежить поруч (наприклад `..\hdi\PD2D`).

```powershell
# 1. усе з теки гри -> PNG (дефолтна палітра PC-98)
python pd2extract.py --all ..\hdi\PD2D out\png

# 2. один архів
python pd2extract.py --pck ..\hdi\PD2D\FACE.PCK out\face

# 3. одна картинка
python pd2extract.py --ask ..\hdi\PD2D\GAMEOVER.ASK out

# 4. палітри, які реально лежать у файлах
python pd2pal.py --gcp ..\hdi\PD2D\HARDY.GCP -o out\hardy.pal
python pd2pal.py --list ..\hdi\PD2D

# 5. самоперевірка (нічого не пише, тільки звіряє)
python tools\verify.py --data ..\hdi\PD2D
```

---

## Інструменти

### `pd2img.py` — бібліотека

Канонічна реалізація кодека. Публічний API:

```python
from pd2img import (decode_lzss, parse_entry, parse_archive, parse_ask,
                    is_image_entry, planes_from_stream, indices_from_planes)

# архів -> [(індекс, blob)]
for i, blob in parse_archive("FACE.PCK"):
    if not is_image_entry(blob):
        continue                      # це не картинка (див. docs/FORMAT.md)
    r = parse_entry(blob)             # {'w','h','x','y','size','stream_bytes',...}
    planes = planes_from_stream(r['stream_bytes'], r['w'], r['h'])   # 4 x (w/8*h)
    idx    = indices_from_planes(planes, r['w'], r['h'])             # 1 байт/піксель
```

| функція | призначення |
|---|---|
| `decode_lzss(data, start, outlen)` | сам кодек; повертає `(байти, скільки_з'їдено)` |
| `parse_entry(blob)` | розібрати один блок-картинку |
| `parse_archive(path)` | розібрати `.PCK` на записи |
| `parse_ask(path)` | розібрати одиночний `.ASK` |
| `is_image_entry(blob)` | чи проходить блок перевірку `decoded_size == w*h/2` |
| `planes_from_stream(...)` | потік → 4 бітові площини |
| `indices_from_planes(...)` | площини → індекси пікселів (1 байт/піксель) |

### `pd2extract.py` — витягувач у PNG

```
python pd2extract.py (--all DIR | --pck FILE | --ask FILE) OUTDIR
                     [--palette pc98|gray|vivid] [--pal FILE.pal]
                     [--pal-exe FILE.EXE:0xOFFSET] [--raw-geom WxH] [--scale N]
```

| опція | що робить |
|---|---|
| `--all DIR` | усе `.PCK` та `.ASK` у теці (рекурсивно) |
| `--pck` / `--ask` | один архів / один файл |
| `--palette pc98` | дефолтна палітра PC-98 (за замовчуванням) |
| `--palette gray` | сіра шкала — добре видно геометрію |
| `--palette vivid` | контрастні кольори |
| `--pal FILE.pal` | своя палітра (JASC-PAL, сирі 768 байтів, 48 байтів або текст) |
| `--pal-exe FILE.EXE:0xOFFSET` | **справжня палітра екрана** з 48-байтової таблиці в EXE — `BRIEFING.EXE:0x234C6` (екіпірування/художні), `TACTICS.EXE:0x1ECA4` (геймплей), `PD2SHELL.EXE:0x98E6` (меню) |
| `--raw-geom WxH` | геометрія для «сирого блоку» `.ASK`; за замовчуванням виводиться з `decoded_size` (`S_ROLL.ASK` → 640x320) |
| `--scale N` | цілочисельне збільшення (nearest) |

Для архівів створює підтеку на архів; імена файлів — `<архів>_<індекс>.png`.
Повний прогін `--all` по HDI-даних пише **361** картинку: 348 записів `.PCK`,
12 кадрів `.ASK` і «сирий блок» `S_ROLL.ASK`.

### `pd2pal.py` — палітри

```
python pd2pal.py --list  DIR                     # усі палітри в записах .PCK / .GCP
python pd2pal.py --gcp   FILE.GCP  [-o OUT.pal]
python pd2pal.py --pck   FILE.PCK  [--entry N] [-o OUT.pal]
python pd2pal.py --read  FILE.pal                # прочитати .pal з DOSBox-X
python pd2pal.py --shot  SHOT.png --vram Vga.bin [-o OUT.pal]
python pd2pal.py --default [-o OUT.pal]
                     [--fmt jasc|raw|nibbles]
```

`--shot` виводить палітру з реального скріншота, зіставляючи його з GVRAM зі
save-state (`Vga.bin`). Друкує `confidence` — якщо він низький, скріншот і
save-state зняті з різних екранів. Див. [`docs/PALETTE.md`](docs/PALETTE.uk.md).

### `tools/pal_tables.py` — банки палітр усередині EXE

Палітри екранів лежать не поруч із пікселями, а банками 48-байтових таблиць
усередині самих EXE (порядок каналів **B,R,G**). Інструмент їх знаходить,
витягує і визначає джерело живого дампа:

```
python tools\pal_tables.py --list  [--data DIR ...] [--out tables.txt]
python tools\pal_tables.py --dump  OUTDIR [--data DIR ...]
python tools\pal_tables.py --find  DUMP_analog.rgb
python tools\pal_tables.py --self-test
```

У shipped-даних HDI+FDI знайдено **127 таблиць у 22 файлах, 59 різних палітр**
(наприклад `TACTICS.EXE 0x1ECA4` — екран геймплею, `BRIEFING.EXE 0x234C6` —
спільна художня палітра/екіпірування, `PD2SHELL.EXE 0x98E6` — меню).
Деталі — [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.uk.md).

### `pd2raw.py` — «сирі блоки» `.SLD`

```
python pd2raw.py --file FILE.SLD -o OUT.bin
python pd2raw.py --all  DIR      -o OUTDIR
```

Той самий LZSS, але контейнер — просто `u32 decoded_size` + потік зі зсуву 4.
Так зроблені всі `.SLD` і `S_ROLL.ASK`. Розпізнавання живе в
`pd2img.is_raw_block`, тому `pd2extract.py` теж рендерить такий файл як
картинку (геометрія з `decoded_size` або з `--raw-geom WxH`).

### `tools/verify.py` — самоперевірка

Нічого не пише; звіряє твердження зі [`docs/FORMAT.md`](docs/FORMAT.uk.md) і
[`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.uk.md):

1. декодер лежить **рівно за документованими адресами** в 7 бінарниках HDI та
   8 бінарниках флопі-релізу (з урахуванням двох форм прологу);
2. це **один бібліотечний рутин**: у 4 бінарниках код байт-у-байт збігається з
   `CONVERT.EXE` (розбіжності — лише імедіати `lcall`), а `OPENING`/`REPORT`
   зібрані іншою компіляцією — для них перевіряються 6 характерних констант
   кодека;
3. кожен запис-картинка декодується рівно до `decoded_size` і споживає потік до
   останнього байта (допуск 1 байт на хвіст бітового буфера);
4. кількості: 348 записів `.PCK` + 12 `.ASK` = 360;
5. 26/26 `.GCP` мають валідну палітру за зсувом `0xB`, з них рівно 2 не
   дефолтні.

```
python tools\verify.py --data ..\hdi\PD2D --floppy ..
```

### `tools/render_vram.py` — рендер GVRAM зі save-state

```
python tools\render_vram.py dump\Vga.bin out\screen.png [--pal file.pal]
```

Маппінг нетривіальний: `base = 0x07C000`, крок між площинами `0x10000`
(а не фізичні `0x8000`), кожна площина 400×80 байтів. З неправильним кроком
виходить шум.


---

## Формати — дуже стисло

| розширення | контейнер | потік зі зсуву | це картинка? |
|---|---|---|---|
| `.ASK` | `u32 decoded_size; u16 x,y,w,h` | 12 | так (крім `S_ROLL.ASK` — він «сирий блок») |
| `.PCK` | архів записів, кожен — як `.ASK` | 12 | буває по-різному: частина записів — display-list'и |
| `.SLD` | `u32 decoded_size` | 4 | ні (це дані) |
| `.GCP` | заголовок + **палітра** + display-list | 4 | **ні** — це команди для GDC |

Повний розбір — [`docs/FORMAT.md`](docs/FORMAT.uk.md).

---

## Документація

| файл | про що |
|---|---|
| [`docs/FORMAT.md`](docs/FORMAT.uk.md) | **глибокий огляд:** усі контейнери, точний алгоритм кодека, стан, біт-рідер, токени, пастки, розкладка виводу, доведення правильності |
| [`docs/PALETTE.md`](docs/PALETTE.uk.md) | палітра: механізм, 32-байтовий формат, де лежить, де її немає, як дістати |
| [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.uk.md) | **виправлення:** палітри екранів **є** у файлах — 48-байтові банки в EXE, порядок каналів B,R,G, і як їх знаходити/витягувати |
| [`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.uk.md) | порядок завантаження з HDI, карта `EXEC`, таблиця розташування декодера в 15 бінарниках, як резолвити DGROUP |
| [`docs/PITFALLS.md`](docs/PITFALLS.uk.md) | пастки, які збили попередні дослідження (щоб не повторити) |

---

## Обмеження

* **Палітри екранів лежать в EXE, а не в графіці.** Це 48-байтові таблиці
  (порядок каналів B,R,G, банки з кроком `0x60`/`0xC0`) — витягуються через
  `tools/pal_tables.py`, див. [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.uk.md).
  Дамп з емулятора потрібен лише щоб дізнатися, яку таблицю використовує екран.
  Тож витягнуті PNG мають правильну геометрію, а з потрібною таблицею в `--pal` —
  і правильні кольори.
* **`.GCP` не декодується** — це display-list для апаратного GDC, не растр.
* **Компресор** не відновлювався; він є в `CONVERT.EXE` (шукати поруч із
  декодером за образом `0x54E6`).
* Кілька архівів не містять картинок взагалі (`MES`, `WMES`, `NAMES`, `MOJI`,
  `NPC`, `MUNIT`, `TUNIT`, `MAP_CHG`, `MISSON*D`, `SCEN_MIS`, `YAOUPD1`,
  `CHARA`, `ANIME`) — там текст або display-list'и.

---

## Походження

Усе відновлено статичним аналізом (дизасемблер 16-бітного DOS із розв'язанням
`lcall` і DGROUP-рядків) плюс читання GVRAM зі save-state DOSBox-X. Декодер
байт-у-байт однаковий у 15 бінарниках (розбіжності — лише імедіати `lcall` на
рантайм), що й підтверджує: це один статично злінкований бібліотечний рутин.

Інструменти не потребують самої гри — тільки її файли даних.

---

## Як зробити з цього git-репозиторій

```powershell
cd pd2gfx
git init
git add .
git commit -m "Power Dolls 2 (PC-98) graphics decoder and extraction tools"
```

`.gitignore` уже виключає `out/` (результати) і `__pycache__/`.
Файли гри в репозиторій не входять — інструменти працюють із будь-якою копією
`PD2D`, шлях передається параметром `--data`.
