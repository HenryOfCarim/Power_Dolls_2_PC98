> 🌐 **Українська** · [English](README.md)

# pd2gfx — Power Dolls 2 (PC-98, Kogado 1994) graphics toolkit

> **English summary.** Reverse-engineered decoder and extraction tools for the
> graphics of *Power Dolls 2* (Kogado, PC-98, 1994). The compressed image format
> is a 4096-byte-ring LZSS (12-bit absolute offset, 4-bit length, LSB-first bit
> stream) reached through three container variants. Raster image entries contain
> **no palette**. Separately, each `.GCP` has a 32-byte packed palette at offset
> `0xB`; 24 contain the PC-98 default ramp and two contain custom ramps. This is
> not the screen palette used for artwork: screen palettes are 48-byte tables in
> the EXEs (channel order B,R,G), passed with `--pal-exe`. `.GCP` files are GDC
> display lists, not raster images — but they **are** decoded now: a GRCG tile
> stream whose rows are XOR deltas, rendered by `pd2gcp.py` (77 blocks across
> both games, including `CHARA.PCK`'s 27 portraits). `pd2img.py` is the library,
> `pd2extract.py` the PNG dumper,
> `pd2pal.py` the palette tool, `pd2gcp.py` the display-list tool,
> `tools/verify.py` the self-check.
> Docs are in Ukrainian; code and docstrings are in English.

Розшифровка й витягування графіки з **Power Dolls 2** (Kogado Software
Products, PC-98, 1994).
Доповненні версії такі як **Power Dolls 2 Dash** **Advanced Power Dolls 2 Dash** також
повинні працювати

Кодек і контейнери відновлено з дизасемблера (`CONVERT.EXE`, образ `0x54E6`) і
перевірено на всіх 360 растрових зображеннях. Display-list'и `.GCP` /
`CHARA.PCK` теж розкодовано — це потоки тайлів GRCG із рядками-дельтами XOR, а
не растр. Пояснення про кольори — одразу після швидкого старту.

---

## Що вирішено

| | статус |
|---|---|
| Контейнери `.ASK`, `.PCK`, «сирий блок» | ✅ повністю |
| Кодек (LZSS) | ✅ повністю, байт-точно |
| Розкладка площин і бітів | ✅ доведено кодом вивантаження в GVRAM |
| Витягування у PNG | ✅ 361 картинка (348 записів `.PCK`, 12 кадрів `.ASK`, «сирий блок» `S_ROLL.ASK`) |
| **Display-list'и** (`.GCP`, `CHARA.PCK`) | ✅ **розкодовано** — 77 блоків рендеряться в PNG через `pd2gcp.py` |
| **Збірка Advanced PD2** (`PD2DT.IDX` + `.BND`) | ✅ **розв'язано** — 169 членів, 74 `.PCK` + 39 `.GCP` + 9 `.ASK` + 6 `.SLD`, розрізає `pd2bnd.py` |
| Механізм установки палітри | ✅ доведено |
| Вбудовані 32-байтові палітри `.GCP` / `CHARA.PCK` | ✅ 26 таблиць у `.GCP` (2 кастомні) і 27 записів `CHARA.PCK` |
| Палітри екранів | ✅ 48-байтові таблиці в EXE (порядок каналів B,R,G); їх знаходить `tools/pal_tables.py`, див. [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.uk.md) |
| Кольори прогону `--all` без параметрів | ⚠️ **можуть бути неправильні** — фолбек це шкала PC-98; див. примітку про палітру нижче |
| `.GCP` як растр | ✅ це display-list для GRCG, і він рендериться — див. [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.uk.md) |
| Компресор | ❌ не відновлювався (він є в `CONVERT.EXE`) |

---

## Вимоги

Сама гра Power Dolls 2, установлена на HDI образ або як файли в теці

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

Якщо замість теки з інстальованими файлами гри маєш HDI-образи, спочатку розпакуй їх. Команда
`img_extract.py --all` рекурсивно знаходить підтримувані образи дисків, зокрема
`.HDI`, і створює для кожного окрему підтеку. Потім `pd2extract.py --all`
проходить уже розпаковані теки, знаходить `.PCK` і `.ASK` та записує графіку в
PNG:

```powershell
python tools\img_extract.py --all ..\hdi -o out\disks
python pd2extract.py --all out\disks out\png --palette auto
```

`--palette auto` застосує відому палітру екрана, якщо назва `.PCK`/`.ASK` дає
підказку (наприклад, `FACE.PCK` → художня палітра); для невідомих назв буде
стандартна палітра PC-98. Якщо EXE лежать окремо, передай їхню теку через
`--palette-dir DIR`. Власну відповідність назви файла до `.pal` можна задати
через JSON і `--palette-map`; наприклад, щоб примусово застосувати
`REPORT.EXE_0138b7.pal` до `M_CLR.PCK`:

```json
{
  "M_CLR": "out/palettes/REPORT.EXE_0138b7.pal"
}
```

Збережи це як `palette-map.json` у корені проєкту. Шлях до `.pal` у JSON
відносний до теки самого JSON-файла. Передай файл мапи під час витягування:

```powershell
python pd2extract.py --all out\disks out\png --palette auto --palette-map palette-map.json
```

Для одного HDI передай шлях до нього напряму, а потім вкажи витягнуту теку для
`pd2extract.py`:

```powershell
python tools\img_extract.py ..\hdi\PD2S.HDI -o out\disks\PD2S
python pd2extract.py --all out\disks\PD2S out\png --palette auto
```

Якщо файли гри вже розпаковані, команди нижче припускають, що тека з ними лежить
поруч із репозиторієм (наприклад `..\hdi\PD2D`).

```powershell
# 1. усе з теки гри -> PNG
#    без --pal/--pal-exe буде шкала PC-98; якщо кольори не ті, див. нижче
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

# 6. display-list'и: файли .GCP і CHARA.PCK
python pd2gcp.py --gcp ..\hdi\PD2D\KOGADO.GCP out\kogado
python pd2gcp.py --pck ..\hdi\PD2D\CHARA.PCK out\chara --entry 0
python pd2gcp.py --all ..\hdi\PD2D out\display-list
```

Display-list'ам потрібен ще один рядок: `.GCP` у PD1 власної палітри не мають, а
портрети `CHARA.PCK` малюються спільною палітрою малюнків, а не таблицею
всередині блоку, тож для цих двох наборів потрібен `--pal-exe`:

```powershell
python pd2gcp.py --all "..\power dolls 1\_unpacked" out\pd1 --pal-exe "..\power dolls 1\_unpacked\PREMIUM.EXE:0xEDF1"
python pd2gcp.py --pck ..\hdi\PD2D\CHARA.PCK out\chara --pal-exe ..\hdi\PD2D\BRIEFING.EXE:0x234C6
```

Якщо не хочеться вгадувати, яка палітра якому екрану належить, — переберіть
усе: `pd2sweep.py` розпаковує все, що знайде, збирає всі палітри, які знайде, і
пише по одному підписаному контактному аркушу на картинку.

```powershell
python pd2sweep.py --data ..\hdi\PD2D -o out\sweep
python pd2sweep.py --image ..\hdi\PD2S.HDI -o out\sweep --orders all
```

## Палітра: якщо кольори неправильні

Якщо контури правильні, а кольори — ні, виберіть палітру екрана, де з’являється
зображення. Звичайний запуск `--all` використовує стандартну шкалу PC-98.

![Запис FACE.PCK з дефолтною палітрою, палітрою художнього екрана та геймплею](docs/img/palette_default_vs_screen.png)

Наприклад, портрети з `FACE.PCK` використовують палітру художнього екрана:

```powershell
python pd2extract.py --pck ..\hdi\PD2D\FACE.PCK out\face --pal-exe ..\hdi\PD2D\BRIEFING.EXE:0x234C6
```

`--all` застосовує одну палітру до всіх зображень прогону; для різних екранів
запускайте витягування окремо. Якщо таблиці для екрана немає, збережіть знімок
у DOSBox-X через **Ctrl+F5** і передайте створений `.pal`
параметром `--pal`. Деталі — у [`docs/PALETTE.md`](docs/PALETTE.uk.md) та
[`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.uk.md).

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
                     [--palette pc98|gray|vivid|auto] [--palette-dir DIR] [--palette-map FILE.json]
                     [--pal FILE.pal]
                     [--pal-exe FILE.EXE:0xOFFSET] [--raw-geom WxH] [--scale N]
```

| опція | що робить |
|---|---|
| `--all DIR` | усе `.PCK` та `.ASK` у теці (рекурсивно) |
| `--pck` / `--ask` | один архів / один файл |
| `--palette pc98` | дефолтна шкала PC-98 (використовується без `--pal*`) |
| `--palette gray` | сіра шкала — добре видно геометрію |
| `--palette vivid` | контрастні кольори |
| `--palette auto` | обрати відому палітру екрана за назвою; для невідомих назв — дефолт PC-98 |
| `--palette-dir DIR` | шукати EXE для `--palette auto` тут (типово тека вводу) |
| `--palette-map FILE.json` | власна відповідність базової назви файла або повного імені джерела до `.pal`; працює лише з `auto`, відносні шляхи — від теки JSON |
| `--pal FILE.pal` | своя палітра (JASC-PAL, сирі 768 байтів, 48 байтів або текст) |
| `--pal-exe FILE.EXE:0xOFFSET` | використати 48-байтову палітру екрана з EXE; див. примітку вище |
| `--raw-geom WxH` | геометрія для «сирого блоку» `.ASK`; за замовчуванням виводиться з `decoded_size` (`S_ROLL.ASK` → 640x320) |
| `--scale N` | цілочисельне збільшення (nearest) |

Для архівів створює підтеку на архів; імена файлів — `<архів>_<індекс>.png`.
Повний прогін `--all` по HDI-даних пише **361** картинку: 348 записів `.PCK`,
12 кадрів `.ASK` і «сирий блок» `S_ROLL.ASK`.
`--palette auto` вибирає відому палітру за назвою кожного джерела `.PCK`/`.ASK`;
якщо підказки немає, лишає шкалу PC-98. Це евристика на рівні файла, не
підтвердження палітри конкретного екрана. `--palette-map` задає винятки, які
мають пріоритет над евристикою. Наприклад, запис `"M_CLR":
"out/palettes/REPORT.EXE_0138b7.pal"` застосує цю палітру до `M_CLR.PCK`;
також можна вказати повне ім'я, наприклад `"M_CLR.PCK"`. Порівняння назв не
залежить від регістру.

Щоб порівняти всі збережені палітри з одним файлом, запусти `pd2pal_sweep.py`.
Він рекурсивно знаходить `.pal` у теці й записує результат кожного кандидата в
окрему підтеку:

```powershell
python pd2pal_sweep.py ..\hdi\PD2D\FACE.PCK out\palettes out\face-sweep
```

Для сирого `.ASK` можна передати `--raw-geom WxH`, якщо розмір не визначається.

### `pd2gcp.py` — display-list'и (`.GCP`, `CHARA.PCK`)

```
python pd2gcp.py (--all DIR | --gcp FILE | --pck FILE [--entry N]) OUTDIR
                 [--pal FILE.pal] [--pal-exe FILE.EXE:0xOFFSET]
                 [--full] [--no-xor] [--dump] [--list] [--scale N] [--base N]
python pd2gcp.py --self-test
```

`.GCP` — не растр: це потік команд для **GRCG** PC-98 (порти `0x7C`/`0x7E`),
рядки якого збережено як XOR-дельти, а завершує його прохід декодування XOR по
рядках. Інструмент виконує завантажувач гри (`CONVERT.EXE 0x5DE5`), обох гравців
(`0x5FCD` / `0x63E3`) і цей прохід, та записує картинку. Геометрія лежить у
заголовку блоку, тож жодного пошуку вирівнювання не потрібно; 27 display-list'ів
`CHARA.PCK` — це портрети 160x240, а 24 `.GCP` у PD1 — його повноекранні
картинки. Повна модель: [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.uk.md).

| опція | дія |
|---|---|
| `--all DIR` | усі `.GCP` під DIR і всі display-list'и в його `.PCK` |
| `--gcp` / `--pck` | один файл / один архів (`--entry N` для одного запису) |
| `--pal FILE.pal` | палітра для блоків, які її не несуть (усі `.GCP` у PD1) |
| `--pal-exe FILE.EXE:0xOFFSET` | одна з 48-байтових палітр екранів усередині EXE |
| `--full` | лишити оголошену область `width x height`, а не обрізати за намальованим |
| `--no-xor` | зупинитися після display-list'а — це сира дельта-маска по рядках |
| `--dump` | додатково записати `<image>.txt` — декодований список команд |
| `--list` | надрукувати таблицю знайдених блоків |
| `--self-test` | перевірити модель на зібраних вручну блоках, нічого не пише |

### `pd2sweep.py` — брутфорс-перебір палітр

Палітра — єдине, що не виводиться з файлів: гра обирає таблицю під час
виконання, а `.GCP` у PD1 не мають її взагалі. Цей інструмент припиняє
здогадуватися й рендерить усе з усім.

```
python pd2sweep.py --data DIR  -o OUTDIR [--mode sheets|full|both] [--cell 160]
                   [--orders engine|all] [--palette-dir DIR]
                   [--images GLOB] [--palettes GLOB] [--max-palettes N] [--list]
python pd2sweep.py --image PD2S.HDI -o OUTDIR          # спершу розпакує образ диска
```

| опція | дія |
|---|---|
| `--data DIR` / `--image FILE` | розпаковане дерево даних або `.HDI`/`.FDI`/`.fdd`/`.d88`, який спершу розпакує `tools/img_extract.py` |
| `--mode sheets` | **типово**: один контактний аркуш на картинку — клітинка на палітру, з підписами; власна палітра блоку йде першою й позначена `*` |
| `--mode full` / `both` | додатково окремий PNG на кожну пару картинка×палітра (`full/`) |
| `--cell` / `--cols` / `--scale` | розмір клітинки, клітинок у рядку, збільшення для `full` |
| `--orders all` | ще й п'ять інших перестановок каналів для кожної 48-байтової таблиці з EXE |
| `--palette-dir DIR` | додати всі `.pal` з DIR |
| `--images` / `--palettes` | фільтри-glob за id картинок і палітр (можна повторювати) |
| `--max-palettes N` | обмежити кількість палітр на аркуші (власна палітра картинки виживає) |
| `--split-bundles` | з `--data` ще й розпакувати кожну пару `.IDX`/`.BND` (Advanced PD2 тримає всю гру в одній збірці). `--image` робить це автоматично |
| `--list` | показати знайдені картинки й палітри, нічого не писати |

Перебирає **усі** види картинок, які знайде (растрові записи `.PCK`/`.ASK`,
«сирі блоки», display-list'и `.GCP` і `CHARA.PCK`, а також членів збірки
`.IDX`/`.BND`) проти **усіх** палітр, які знайде (паковані таблиці `+0xB` з
файлів даних, усі 48-байтові таблиці з EXE через `tools/pal_tables.py`, усі
вказані `.pal` і стандартна гама PC-98). Вивід:

```
OUTDIR/palettes/<NNN>_<id>.pal     кожна унікальна палітра, JASC
OUTDIR/palettes/index.txt          номер -> id, джерело, hex — на нього посилаються підписи
OUTDIR/sheets/<picture>.png        контактний аркуш
```

Контактний аркуш тут кращий за окремі файли: 400 картинок × 60 палітр — це чверть
мільйона PNG, тоді як аркуш — один файл на картинку й один погляд на палітру.
Клітинки підписані `*N id`, де `*` позначає палітру, яку блок несе сам.

### `pd2pal.py` — палітри

```
python pd2pal.py --list  DIR                     # усі палітри в записах .PCK / .GCP
python pd2pal.py --suggest DIR [--for ASSET]      # евристичний список палітр екранів
python pd2pal.py --gcp   FILE.GCP  [-o OUT.pal]
python pd2pal.py --pck   FILE.PCK  [--entry N] [-o OUT.pal]
python pd2pal.py --read  FILE.pal                # прочитати .pal з DOSBox-X
python pd2pal.py --shot  SHOT.png --vram Vga.bin [-o OUT.pal]
python pd2pal.py --default [-o OUT.pal]
                     [--fmt jasc|raw|nibbles]
```

`--suggest` сканує таблиці палітр у EXE всередині вже розпакованої теки гри.
З `--for FACE.PCK` підказка в назві ставить відому художню палітру на перше
місце; біля кожного кандидата показано файл-джерело та зсув для `--pal-exe`.
Це евристичне впорядкування, а не підтверджене зіставлення палітри з файлом.

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

### `pd2bnd.py` — збірка `.IDX` + `.BND` (Advanced PD2)

Advanced PD2 не постачає файлів даних гри окремо: він постачає `PD2DT.BND`
(7.2 МБ конкатенованого payload'у) разом із `PD2DT.IDX` — таблицею вмісту.

```
python pd2bnd.py --list PD2_3/PD2DT.IDX
python pd2bnd.py --idx PD2_3/PD2DT.IDX --bnd PD2_3/PD2DT.BND -o out/apd2
python pd2bnd.py --auto extracted_dir -o out/bundles
python pd2bnd.py --self-test
```

`.IDX` — це плаский масив 24-байтових записів (`name[16]`, `size` u32,
`offset` u32), а `.BND` — сира конкатенація, яку вони описують. 169 членів, без
стиснення й вирівнювання: `offset[k] + size[k] == offset[k+1]` для кожного k, а
останній член закінчується рівно на останньому байті збірки, тож таблиця
перевіряє себе сама. У payload'і 74 `.PCK`, 39 `.GCP`, 9 `.ASK`, 6 `.SLD` плюс
драйвери, MIDI й дані установлювача — зокрема екрани, яких немає в інших релізах
(`SINGLE`, `GAMEOVER`, `M_FAIL`, `AD_END`, `APD_STF*`, `KOKUPI*`).
Деталі: [`docs/ADVANCED_PD2.md`](docs/ADVANCED_PD2.uk.md).

### `tools/verify.py` — самоперевірка

Нічого не пише; звіряє твердження зі [`docs/FORMAT.md`](docs/FORMAT.uk.md),
[`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.uk.md) і
[`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.uk.md):

1. декодер лежить **рівно за документованими адресами** в 7 бінарниках HDI та
   8 бінарниках флопі-релізу (з урахуванням двох форм прологу);
2. це **один бібліотечний рутин**: у 4 бінарниках код байт-у-байт збігається з
   `CONVERT.EXE` (розбіжності — лише імедіати `lcall`), а `OPENING`/`REPORT`
   зібрані іншою компіляцією — для них перевіряються 6 характерних констант
   кодека;
3. кожен запис-картинка декодується рівно до `decoded_size` і споживає потік до
   останнього байта (допуск 1 байт на хвіст бітового буфера);
4. кількості: 348 записів `.PCK` + 12 `.ASK` = 360 (плюс «сирий блок»
   `S_ROLL.ASK`, який `pd2extract.py` рендерить як кадр 640x320);
5. 26/26 `.GCP` мають валідну палітру за зсувом `0xB`, з них рівно 2 не
   дефолтні;
6. чотири відомі палітри екранів лежать в EXE за задокументованими зсувами
   (порядок каналів B,R,G);
7. `S_ROLL.ASK` — «сирий блок», його геометрія виводиться як 640x320;
8. усі display-list'и (26 `.GCP` у теці даних + 27 записів `CHARA.PCK`)
   доходять до закривного `0x7F` рівно тоді, коли в блоці закінчуються байти;
9. геометрія з заголовка display-list'а для чотирьох відомих блоків
   (`KOGADO.GCP` 24×56, `K_BLANC1.GCP` 48×112, `PD2TITLE.GCP` 80×400,
   `USAGI.GCP` 10×80).

```
python tools\verify.py --data "..\power dolls 2 dash HDI\_unpacked\PD2D" --floppy "..\power dolls 2 FDI\_unpacked"
```

### `tools/img_extract.py` — розпакування образу диска

```
python tools\img_extract.py --probe IMAGE [IMAGE ...]
python tools\img_extract.py IMAGE -o OUTDIR [--base 0x1000]
python tools\img_extract.py --all IMAGEDIR -o OUTDIR
```

Власний читач FAT12/FAT16, бо частина дампів не піддається 98Bridge: чистий
FAT12 з медіабайтом `0xFE` (`MS-DOS.FDI`), FAT12 за 0x1000-байтовою обгорткою
(FDI `S-Premium` і `Premium Disc`), а також образи, у яких завантажувальний
сектор не за зсувом 0. `--probe` показує знайдену геометрію, а сам інструмент
витягує все дерево каталогів. Образам без самодостатнього BPB (набір `.fdd`
Advanced PD2) розпакування поки не світить — але їх усе одно можна сканувати
на палітри як непрозорі бінарники.

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
| `.GCP` | заголовок + необов'язкова **32-байтова packed-палітра** + display-list | `9 + hdr[8]` (`0x2B`, коли палітра є) | не растр, але **так, рендериться** — display-list GRCG, див. `pd2gcp.py` |

Повний розбір контейнерів — [`docs/FORMAT.md`](docs/FORMAT.uk.md), а `.GCP` —
[`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.uk.md).

---

## Документація

| файл | про що |
|---|---|
| [`docs/FORMAT.md`](docs/FORMAT.uk.md) | **глибокий огляд:** усі контейнери, точний алгоритм кодека, стан, біт-рідер, токени, пастки, розкладка виводу, доведення правильності |
| [`docs/PALETTE.md`](docs/PALETTE.uk.md) | основи палітр: як вибрати палітру екрана, що означає 32-байтова шкала в `.GCP` і як отримати правильні кольори |
| [`docs/PALETTE_TABLES.md`](docs/PALETTE_TABLES.uk.md) | докази й деталі 48-байтових таблиць палітр екранів у EXE, порядок каналів B,R,G і як знаходити/витягувати таблиці |
| [`docs/ADVANCED_PD2.md`](docs/ADVANCED_PD2.uk.md) | Advanced PD2: розкладка `.fdd` без BPB, збірка `PD2DT.IDX` + `.BND` (169 членів, розв'язано), що це патч-надбудова над PD2 |
| [`docs/PD1.md`](docs/PD1.uk.md) | Power Dolls 1: шість логотипів `.ASK` плюс 24 display-list'и `.GCP` — його портрети й екрани |
| [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.uk.md) | display-list'и розв'язано: модель GRCG, завантажувач і обидва гравці, потік команд, прохід декодування XOR по рядках, палітри, перевірка |
| [`docs/LOAD_ORDER.md`](docs/LOAD_ORDER.uk.md) | порядок завантаження з HDI, карта `EXEC`, таблиця розташування декодера в 15 бінарниках, як резолвити DGROUP |
| [`docs/PITFALLS.md`](docs/PITFALLS.uk.md) | пастки, які збили попередні дослідження (щоб не повторити) |
| [`docs/LIVE_PALETTE_DUMP.uk.md`](docs/LIVE_PALETTE_DUMP.uk.md) | живий знімок палітри з DOSBox-X: MCP-тули (`dosbox_mcp_palette.py`, `mcp_probe.py`, `mcp_poll_palette.py`, `mcp_dump_vram.py`), `pal_from_shot.py` і закритий експеримент «дампер усередині гостя» |

Відпрацьовані інструменти лежать у [`_attic-tools/`](_attic-tools/MANIFEST.md)
(перенесені, не видалені: причина по кожному файлу + відкат однією командою).

---

## Обмеження

* **Палітра:** растрові записи зазвичай не мають палітри екрана; без `--pal`
  або `--pal-exe` використовується шкала PC-98. З display-list'ами та сама
  історія: `.GCP` несуть 32-байтову таблицю, але в PD1 її немає взагалі, а
  портрети `CHARA.PCK` малюються палітрою малюнків, а не таблицею всередині
  блоку. Див. примітку про палітру вище та §6 у
  [`docs/DISPLAYLIST.md`](docs/DISPLAYLIST.uk.md).
* **Компресор** не відновлювався; він є в `CONVERT.EXE` (шукати поруч із
  декодером за образом `0x54E6`).
* Кілька архівів не містять картинок взагалі (`MES`, `WMES`, `NAMES`, `MOJI`,
  `NPC`, `MUNIT`, `TUNIT`, `MAP_CHG`, `MISSON*D`, `SCEN_MIS`, `YAOUPD1`,
  `CHARA`, `ANIME`) — там текст або display-list'и. З них display-list'и вже
  розкодовано (`pd2gcp.py`: 27 із 38 записів `CHARA.PCK`); решта — досі не
  ідентифіковані дані.

---

## Походження

Усе відновлено статичним аналізом (дизасемблер 16-бітного DOS із розв'язанням
`lcall` і DGROUP-рядків) плюс читання GVRAM зі save-state DOSBox-X. Декодер
байт-у-байт однаковий у 15 бінарниках (розбіжності — лише імедіати `lcall` на
рантайм), що й підтверджує: це один статично злінкований бібліотечний рутин.

Інструменти не потребують самої гри — тільки її файли даних.
