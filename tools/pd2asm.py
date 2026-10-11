"""Minimal 16-bit assembler for the PC-98 palette dumper (no NASM/TASM needed).

Deliberately small: it understands exactly the instructions and directives the
dumper uses, plus labels, numbers (`1Fh`, `0x1F`, `31`) and string literals.
All label references assemble as short (2-byte) near jumps, which is what a
<128-byte .COM needs.

Supported:
    org N                          label:
    db <bytes/labels/strings>      dw <words/labels>
    mov r8, imm8 | r16, imm16 | r16, label | [si], al | al, [si] | [si], imm8
    mov ah, al | al, ah | al, dil          (byte-register moves)
    out dx, al     in al, dx       lodsb        xchg ax, r16
    int N          ret             int3         hlt
    cmp al, imm8   and al, imm8    or al, imm8   add al, imm8   sub al, imm8
    or al, ah      inc r16         add r16, imm8
    shl al, 1      shl ah, 1       shr al, 1
    loop label     jb label        jae label    jc label      jmp label

Usage:
    python tools\\pd2asm.py tools\\paldump.asm -o tools\\PALDUMP.COM [--listing]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ORG = 0x100
R8 = {"al": 0, "cl": 1, "dl": 2, "bl": 3, "ah": 4, "ch": 5, "dh": 6, "bh": 7}
R16 = {"ax": 0, "cx": 1, "dx": 2, "bx": 3, "sp": 4, "bp": 5, "si": 6, "di": 7}


class AsmError(Exception):
    pass


def literal(token: str, symbols: dict[str, int] | None = None):
    """Return an int for a literal or a known symbol, else None."""
    t = token.strip()
    try:
        if re.fullmatch(r"[0-9A-Fa-f]+h", t):
            return int(t[:-1], 16)
        if re.fullmatch(r"[01]+b", t):
            return int(t[:-1], 2)
        return int(t, 0)
    except ValueError:
        pass
    if symbols is not None and t in symbols:
        return symbols[t]
    return None


def le(value: int, size: int) -> bytes:
    return bytes([value & 0xFF]) if size == 1 else bytes([value & 0xFF, (value >> 8) & 0xFF])


def parse_mem(token: str):
    """`[bx]`, `[bx+1]`, `[bx-1]`, `[si]`, `[di+2]`, `[label]` -> (base, disp).

    `base` is a register name, or None for a direct address (`mov ax, [label]`,
    encoded as mod=00 rm=110 with a 16-bit displacement).
    """
    m = re.fullmatch(r"\[\s*(bx|si|di|bp)\s*(?:([+-])\s*([^\]]+))?\s*\]", token.strip(), re.I)
    if m:
        base = m.group(1).lower()
        disp = 0
        if m.group(3):
            n = literal(m.group(3))
            if n is None:
                return None
            disp = -n if m.group(2) == "-" else n
        return base, disp
    m = re.fullmatch(r"\[\s*([A-Za-z_.$][\w.$]*)\s*\]", token.strip())
    if m:
        return None, ("sym", m.group(1))
    return None


MEM_BASE = {"bx": 7, "bp": 6, "si": 4, "di": 5}


def mem_modrm(base, disp, reg_field: int, size: int, symbols: dict | None = None) -> bytes:
    """ModRM (+disp) for a 16-bit memory operand. No SIB, no index registers."""
    if base is None:                                   # direct address [label]
        if isinstance(disp, tuple) and disp[0] == "sym":
            n = literal(disp[1], symbols)
            if n is None:
                raise AsmError(f"unknown symbol {disp[1]!r}")
            return bytes([0x00 | (reg_field << 3) | 0x06]) + le(n, 2)
        raise AsmError("direct memory operand needs a label")
    if disp == 0 and base != "bp":
        return bytes([0x00 | (reg_field << 3) | MEM_BASE[base]])
    if -128 <= disp <= 127:
        return bytes([0x40 | (reg_field << 3) | MEM_BASE[base], disp & 0xFF])
    return bytes([0x80 | (reg_field << 3) | MEM_BASE[base]]) + le(disp, 2)


def tokenize(src: str) -> list[str]:
    """Split operands, keeping `[bx + 1]` (spaces allowed) as one token.

    Brackets are stripped of internal spaces, parentheses (used only by
    `db N dup (x)`) are kept as one token so the directive parser sees
    "N", "dup", "(x)".
    """
    src = src.replace(",", " ")
    out = []
    for chunk in re.findall(r"\[[^\]]*\]|\S+", src):
        if chunk.startswith("["):
            out.append(re.sub(r"\s+", "", chunk))
            continue
        # split a token such as "dup(0)" or "13dup(0)" into "dup", "(0)"
        while True:
            m = re.match(r"^([A-Za-z_][\w.$]*)\s*(\()", chunk)
            if m:
                out.append(m.group(1))
                chunk = chunk[m.end(1):]
                continue
            m = re.match(r"^(\d+)\s*([A-Za-z_][\w.$]*)", chunk)
            if m and m.group(2).lower() == "dup":
                out.append(m.group(1))
                chunk = chunk[m.end(1):]
                continue
            break
        if chunk:
            out.append(chunk)
    return out


def encode(line: str, pc: int, symbols: dict[str, int], line_no: int,
           size_only: bool = False) -> bytes:
    """size_only=True is used by pass 1: unresolved symbols encode as 0 so that
    instruction *sizes* (and therefore label addresses) are still correct."""
    src = line.split(";")[0].strip()
    if not src:
        return b""
    parts = tokenize(src)
    op = parts[0].lower()
    args = parts[1:]
    low = [x.lower() for x in args]

    def val(token: str, size: int) -> bytes:
        n = literal(token, symbols)
        if n is None:
            if size_only:
                return bytes(size)
            raise AsmError(f"line {line_no}: unknown symbol {token!r}")
        return le(n, size)

    def rel(token: str) -> bytes:
        n = literal(token, symbols)
        if n is None:
            if size_only:
                return b"\x00"
            raise AsmError(f"line {line_no}: unknown symbol {token!r}")
        d = n - (pc + 2)
        if not -128 <= d <= 127:
            raise AsmError(f"line {line_no}: relative jump out of range ({d})")
        return bytes([d & 0xFF])

    if op == "org":
        return b""
    if op == "db":
        out = bytearray()
        # `db N dup (x)`  -> N copies of x   (values may precede it: db 1, 2 dup (0))
        i = 0
        while i < len(args):
            tok = args[i]
            if i + 1 < len(args) and args[i + 1].lower() == "dup":
                n = val(tok, 1)[0]
                fill = args[i + 2] if i + 2 < len(args) else "(0)"
                fill = fill.strip("()")
                for _ in range(n):
                    out += val(fill, 1)
                i += 3
                continue
            if len(tok) >= 2 and tok[0] == '"' and tok[-1] == '"':
                out += tok[1:-1].encode("ascii")
            else:
                out += val(tok, 1)
            i += 1
        return bytes(out)
    if op == "dw":
        out = bytearray()
        for x in args:
            out += val(x, 2)
        return bytes(out)

    if op == "mov":
        # optional size prefix: `mov byte [x], v` / `mov word [x], v`
        size_prefix = None
        if low and low[0] in ("byte", "word"):
            size_prefix = low.pop(0)
            args = args[1:]
        if len(args) == 2 and low[0] in R16 and low[1] in R16:      # mov r16, r16
            return bytes([0x89, 0xC0 | (R16[low[1]] << 3) | R16[low[0]]])
        if len(args) == 2 and low[0] in R8 and low[1] in R8:        # mov r8, r8
            return bytes([0x88, 0xC0 | (R8[low[1]] << 3) | R8[low[0]]])
        if len(args) == 2 and low[0] in R16:                        # mov r16, imm/label
            return bytes([0xB8 + R16[low[0]]]) + val(args[1], 2)
        if len(args) == 2 and low[0] in R8:                         # mov r8, imm
            return bytes([0xB0 + R8[low[0]]]) + val(args[1], 1)

        mem = parse_mem(args[0]) if len(args) == 2 else None
        if mem is not None:
            base, disp = mem
            if low[1] in R8:                                        # mov [mem], r8
                return bytes([0x88]) + mem_modrm(base, disp, R8[low[1]], 1, symbols)
            size = 2 if size_prefix == "word" else 1
            opcode = 0xC7 if size == 2 else 0xC6
            try:
                modrm = mem_modrm(base, disp, 0, size, symbols)
            except AsmError:
                if not size_only:
                    raise
                modrm = bytes([0x06, 0x00, 0x00])
            return bytes([opcode]) + modrm + val(args[1], size)
        mem = parse_mem(args[1]) if len(args) == 2 else None
        if mem is not None and low[0] in R8:                        # mov r8, [mem]
            base, disp = mem
            try:
                modrm = mem_modrm(base, disp, R8[low[0]], 1, symbols)
            except AsmError:
                if not size_only:
                    raise
                modrm = bytes([0x06, 0x00, 0x00])
            return bytes([0x8A]) + modrm
    if op == "out" and low == ["dx", "al"]:
        return bytes([0xEE])
    if op == "in" and low == ["al", "dx"]:
        return bytes([0xEC])
    if op == "int":
        return bytes([0xCD]) + val(args[0], 1)
    if op == "xchg" and len(args) == 2 and low[0] == "ax" and low[1] in R16:
        reg = R16[low[1]]
        return bytes([0x90 if reg == 0 else 0x90 + reg])
    if op == "push" and len(args) == 1 and low[0] in R16:
        return bytes([0x50 + R16[low[0]]])
    if op == "pop" and len(args) == 1 and low[0] in R16:
        return bytes([0x58 + R16[low[0]]])
    if op == "lodsb":
        return bytes([0xAC])
    if op == "cmp" and low[0] == "al":
        return bytes([0x3C]) + val(args[1], 1)
    if op == "cmp" and len(args) == 2 and low[0] in R8:
        return bytes([0x80, 0xF8 | R8[low[0]]]) + val(args[1], 1)
    if op == "cmp" and len(args) == 3 and low[0] == "byte" and parse_mem(args[1]):
        base, disp = parse_mem(args[1])
        try:
            modrm = mem_modrm(base, disp, 7, 1, symbols)
        except AsmError:
            if not size_only:
                raise
            modrm = bytes([0x06, 0x00, 0x00])
        return bytes([0x80]) + modrm + val(args[2], 1)
    if op == "cmp" and len(args) == 2 and low[0] in R16:
        return bytes([0x83, 0xF8 | R16[low[0]]]) + val(args[1], 1)
    if op == "sub" and len(args) == 2 and low[0] in R16:
        return bytes([0x83, 0xE8 | R16[low[0]]]) + val(args[1], 1)
    if op == "and" and low[0] == "al":
        return bytes([0x24]) + val(args[1], 1)
    if op == "or" and len(args) == 2 and low[0] == "al" and low[1] in R8:
        return bytes([0x08, 0xC0 | (R8[low[1]] << 3) | R8["al"]])
    if op == "or" and low[0] == "al":
        return bytes([0x0C]) + val(args[1], 1)
    if op == "add" and low[0] == "al":
        return bytes([0x04]) + val(args[1], 1)
    if op == "add" and len(args) == 2 and low[0] in R16:
        return bytes([0x83, 0xC0 | R16[low[0]]]) + val(args[1], 1)
    if op == "sub" and low[0] == "al":
        return bytes([0x2C]) + val(args[1], 1)
    if op in ("inc", "dec") and len(args) == 2 and low[0] == "byte" and parse_mem(args[1]):
        base, disp = parse_mem(args[1])
        field = 0 if op == "inc" else 1
        try:
            modrm = mem_modrm(base, disp, field, 1, symbols)
        except AsmError:
            if not size_only:
                raise
            modrm = bytes([0x06, 0x00, 0x00])
        return bytes([0xFE]) + modrm
    if op == "inc" and len(args) == 1 and low[0] in R16:
        return bytes([0x40 + R16[low[0]]])
    if op == "inc" and len(args) == 1 and low[0] in R8 and low[0] not in ("ah", "ch", "dh", "bh"):
        return bytes([0xFE, 0xC0 | R8[low[0]]])
    if op == "dec" and len(args) == 1 and low[0] in R8 and low[0] not in ("ah", "ch", "dh", "bh"):
        return bytes([0xFE, 0xC8 | R8[low[0]]])
    if op == "dec" and len(args) == 1 and low[0] in R16:
        return bytes([0x48 + R16[low[0]]])
    if op == "shl" and len(args) == 2 and low[1] == "1":
        if low[0] == "al":
            return bytes([0xD0, 0xE0])
        if low[0] == "ah":
            return bytes([0xD0, 0xE4])
        if low[0] == "dil":
            return bytes([0xD0, 0xE7])
    if op == "shr" and len(args) == 2 and low[1] == "1":
        if low[0] == "al":
            return bytes([0xD0, 0xE8])
    if op == "call":
        n = literal(args[0], symbols)
        if n is None:
            if size_only:
                return b"\x00\x00\x00"
            raise AsmError(f"line {line_no}: unknown symbol {args[0]!r}")
        d = n - (pc + 3)
        return bytes([0xE8]) + le(d & 0xFFFF, 2)
    if op == "loop":
        return bytes([0xE2]) + rel(args[0])
    if op in ("jb", "jc"):
        return bytes([0x72]) + rel(args[0])
    if op in ("je", "jz"):
        return bytes([0x74]) + rel(args[0])
    if op in ("jne", "jnz"):
        return bytes([0x75]) + rel(args[0])
    if op == "ja":
        return bytes([0x77]) + rel(args[0])
    if op == "jae":
        return bytes([0x73]) + rel(args[0])
    if op == "jmp":
        return bytes([0xEB]) + rel(args[0])
    if op == "ret":
        return bytes([0xC3])
    if op == "int3":
        return bytes([0xCC])
    if op == "hlt":
        return bytes([0xF4])
    raise AsmError(f"line {line_no}: unsupported instruction {src!r}")


def assemble(text: str, listing: bool = False) -> bytes:
    """Two passes: pass 1 only needs label *addresses*, so unresolved symbols
    are assembled as zero - that keeps every instruction size correct."""
    lines = text.splitlines()

    def strip_label(code: str):
        m = re.match(r"^([A-Za-z_.$][\w.$]*):\s*(.*)$", code)
        return m

    # pass 1: label addresses, unknown symbols -> 0
    labels: dict[str, int] = {}
    pc = ORG
    for i, raw in enumerate(lines, 1):
        code = raw.split(";")[0].strip()
        m = strip_label(code)
        if m:
            if m.group(1) in labels:
                raise AsmError(f"line {i}: duplicate label {m.group(1)}")
            labels[m.group(1)] = pc
        if not code:
            continue
        body = re.sub(r"^([A-Za-z_.$][\w.$]*):\s*", "", code)
        pc += len(encode(body, pc, labels, i, size_only=True))
    # pass 2: final encoding
    out = bytearray()
    pc = ORG
    table = []
    for i, raw in enumerate(lines, 1):
        body = re.sub(r"^([A-Za-z_.$][\w.$]*):\s*", "", raw.split(";")[0].strip())
        b = encode(body, pc, labels, i)
        table.append((pc, b, raw.split(";")[0].strip()))
        out += b
        pc += len(b)
    if listing:
        for addr, b, line in table:
            if line:
                print(f"  {addr:04X}  {b.hex(' '):<22} {line}")
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("asm")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--listing", action="store_true")
    a = ap.parse_args()
    data = assemble(Path(a.asm).read_text(encoding="utf-8"), a.listing)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_bytes(data)
    print(f"{a.asm} -> {a.out}: {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
