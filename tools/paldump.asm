; PALDUMP.COM - read the PC-98's *current* 16-colour palette from inside the
; guest OS and write it as the game's own 32-byte packed table.
;
; Why ports: the game programs the palette by writing the index to 0xA8 and the
; three 4-bit components to 0xAA/0xAC/0xAE (see docs/PALETTE.md). Those ports are
; the only window onto the palette - the game keeps no copy in its data files,
; and DOSBox-X does not serialise the PC-98 palette into save states. Reading
; them back asks the emulator (or real hardware) what the DAC currently holds.
;
; Usage:   PALDUMP.COM [filename]
;          filename defaults to C:\PD2PAL.DAT and must be an 8.3 name with no
;          directory part, because the command tail is used verbatim.
;
; Output:  48 hex characters (32 table bytes) + CR/LF, written to stdout and to
;          the file. Table format:  byte[2i] = (i << 4) | R ; byte[2i+1] = (G << 4) | B
;
; Build:   python tools\pd2asm.py tools\paldump.asm -o tools\PALDUMP.COM --listing

        org 100h

; ---------------------------------------------------------------- data ----
defname:    db  "C:\PD2PAL.DAT", 0
fname_len:  db  0
fname:      db  13 dup (0), 0
hexbuf:                                     ; 32 table bytes, then 48 chars + CRLF + '$'

; ---------------------------------------------------------------- code ----
start:
; --- optional filename from the command tail ------------------------------
        mov     si, 80h                     ; PSP: command tail length
        lodsb
        mov     cl, al
        mov     ch, 0
        mov     di, fname

skipsp:
        cmp     cl, 0
        je      names_done
        lodsb
        dec     cl
        cmp     al, 20h
        je      skipsp
        cmp     al, 0Dh
        je      names_done

take:
        mov     [di], al
        inc     di
        inc     byte [fname_len]
        cmp     cl, 0
        je      names_done
        lodsb
        dec     cl
        cmp     al, 20h
        je      names_done
        cmp     al, 0Dh
        je      names_done
        jmp     take

names_done:
        cmp     byte [fname_len], 0
        jne     have_name
        mov     si, defname
        mov     di, fname
copydef:
        lodsb
        mov     [di], al
        inc     di
        cmp     al, 0
        jne     copydef

; --- read the 16 palette entries -----------------------------------------
have_name:
        mov     bx, hexbuf
        add     bx, 32                      ; BX -> first 2 bytes of the table
        mov     di, 0                       ; DI = palette index 0..15

next_index:
        mov     dx, 0A8h                    ; palette index port
        mov     dh, dl
        mov     ax, 0
        mov     al, dh
        out     dx, al

        mov     dx, 0AAh                    ; red
        in      al, dx
        and     al, 0Fh
        mov     ah, al                      ; AH = R

        mov     dx, 0ACh                    ; green
        in      al, dx
        and     al, 0Fh
        mov     ch, al                      ; CH = G

        mov     dx, 0AEh                    ; blue
        in      al, dx
        and     al, 0Fh
        mov     cl, al                      ; CL = B

        mov     al, dh                      ; index
        shl     al, 1
        shl     al, 1
        shl     al, 1
        shl     al, 1                       ; index << 4
        or      al, ah                      ; | R
        mov     [bx], al

        mov     al, ch                      ; G
        shl     al, 1
        shl     al, 1
        shl     al, 1
        shl     al, 1                       ; G << 4
        or      al, cl                      ; | B
        mov     [bx + 1], al

        add     bx, 2
        inc     di
        cmp     di, 16
        jb      next_index

; --- hex-encode the 32 table bytes in place -> 48 chars + CRLF + '$' -------
        mov     si, hexbuf
        mov     di, hexbuf
        mov     cx, 32
hexloop:
        lodsb
        mov     ah, al
        shr     al, 1
        shr     al, 1
        shr     al, 1
        shr     al, 1                       ; high nibble
        call    hexdig
        mov     [di], al
        inc     di
        mov     al, ah
        and     al, 0Fh                     ; low nibble
        call    hexdig
        mov     [di], al
        inc     di
        loop    hexloop
        mov     [di], 0Dh
        mov     [di + 1], 0Ah
        mov     [di + 2], 24h               ; '$' terminator for INT 21h AH=09h

; --- console --------------------------------------------------------------
        mov     dx, hexbuf
        mov     ah, 09h
        int     21h

; --- file -----------------------------------------------------------------
        mov     dx, fname
        mov     ax, 3C00h                   ; create / truncate
        mov     cx, 0
        int     21h
        jc      done
        mov     bx, ax                      ; handle
        mov     dx, hexbuf
        mov     cx, 50
        mov     ah, 40h                     ; write
        int     21h
        mov     ah, 3Eh                     ; close
        int     21h
done:
        mov     ax, 4C00h
        int     21h

; --- AL (0..15) -> ASCII hex digit ---------------------------------------
hexdig:
        cmp     al, 10
        jb      hexd_low
        add     al, 7                       ; 'A' - '0' - 10
hexd_low:
        add     al, 30h
        ret
