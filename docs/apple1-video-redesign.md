# Apple-1 Terminal Section — Modern Discrete Redesign (NTSC Composite)

Status: **design draft, rev 0** · Scope: architecture, timing and logic specification. There is no schematic or ROM images yet.

Sources:
- `docs/apple1-man-Pg14-video.pdf` (schematic 00101 sheet 1/3, *Terminal Section*)
- `docs/apple1manual.pdf` p.15 (sheet 2/3, *Processor Section*)
- `t/signetics.zip` (2504 / 2513 / 2519 datasheets)
- <https://www.sbprojects.net/projects/apple1/terminal.php>

Items marked **⚠ verify** could not be read with certainty from the schematic scans. Check them against an original or replica board before you commit to a layout.

---

## 1. Goals

| Requirement | Decision |
|---|---|
| Technology | Discrete, currently produced 5 V parts only: 74HC/HCT/AC logic, SRAM, parallel NOR flash. No CPLD, FPGA or MCU. |
| Supply | Single +5 V. The -5 V and -12 V rails are no longer needed by the terminal. |
| Output | Monochrome NTSC composite, 1 Vp-p into 75 Ω, 262-line progressive ("240p"), about 60 Hz. |
| Display | 40 × 24 characters, 5 × 7 glyph in a 7 × 8 cell, blinking `@` cursor. |
| Compatibility | Same PIA port-B protocol (RD1-RD7, DA, RDA) and the same CLR switch behaviour. CR, auto-wrap and scrolling behave as in the original. |
| Speed | A character is accepted in microseconds, not one per frame (16.7 ms). An optional jumper restores the authentic slow timing. |
| Processor-sheet services | Still supplies **CLA** (CPU clock source) and the **DRAM refresh signals** that sheet 2/3 takes from the terminal. |

---

## 2. Analysis of the original terminal section (sheet 1/3)

### 2.1 Block map

```
14.31818 MHz xtal (C13 osc: D12/R13/R14/C3/C4)
      │
      ├─► ÷2 ──► DOT clock 7.159 MHz ──► D1 74166 shift reg ──► VID ──► Q5 emitter follower ──► composite
      │                     │
      │                    D11 74160 (char divider) ──► CLA (CHAR RATE) ──► sheet 2/3 CPU clock
      │                     │
      │         D6 74160 ─► D7 74161 ─► D8 74161 ─► D9 74161     H & V counters
      │          (H)         (H5,H6..)   (V0-V2…)    (V3-V5, LAST)
      │                     │
      │          sync/blank gates C9,C10,D10,B2,C5 ──► HSYNC, VBL, HBL, LINE Ø, LINE 7
      │
      └─► C1 DS0025 MOS clock driver ──► Ø3/Ø4 two-phase clocks for the 2504/2519 (-5/-12 V)

Display memory: D4A/B, D5A/B, D14A/B = six 2504 (1024 × 1 bit each, 6-bit chars, recirculating)
Cursor bit:     C11B 2504 (marks the cursor slot in the recirculating stream)
Line buffer:    C3 2519 (40 × 6, replays the current row for its 8 scan lines)
Char ROM:       D2 2513 (64 chars × 8 rows × 5 dots; A1-A3 = scan line, A4-A9 = char)
Input mux:      C4, C14 74157 (choose recirculated data, new char from RD1-RD7, or blank/CLR)
Write control:  C7 74174 + C5, C6, C8, C12 gates ──► WC1, WC2, WRITE, RDA
Cursor blink:   D13 555 (gated into the C14 mux to alternate '@'/blank)
```

### 2.2 How the original works

1. **Recirculating memory.** The 960 visible character codes plus 64 hidden slots circulate continuously through the 2504 shift registers, one full revolution per frame. Clocking is done by the two-phase Ø3/Ø4 MOS clocks from the DS0025.
2. **Row replay.** The first scan line of each text row loads 40 codes into the 2519 (C3). The 2519 then replays them on the remaining 7 scan lines, so the slow 2504s only have to advance once per row. Per sbprojects, the char clock to the memories runs in bursts of 40.
3. **Glyphs.** The 2519 output plus scan-line bits V0-V2 address the 2513 (D2). Its 5 dot outputs and 3 grounded inputs load D1 (74166), which shifts out at the dot clock. Scan line 0 of each 8-line cell is blank (2513 font layout).
4. **Writing a character.** A write is possible only when the slot marked by the cursor bit (C11B) passes the write point. At that moment C4/C14 substitute the new code for the recirculated one, and the cursor bit is moved one slot on (WC2). A character can therefore wait up to a full revolution, 16.7 ms.
5. **Acceptance test.** A character is written only if RD6 or RD7 is 1, i.e. the code is ≥ $20. A carriage return (RD1-RD7 = $0D) is decoded separately. It fills the rest of the line with blanks and moves the cursor to the next line. All other control codes are acknowledged and discarded.
6. **Scrolling** happens naturally. Writing past the end of the bottom line moves the "start" of the recirculating ring, and the 64 hidden slots are cleared during VBL so stale data never scrolls in.
7. **Clear screen.** The CLR switch forces blanks into the recirculation path for as long as it is held. One full frame (16.7 ms) clears everything.
8. **Cursor.** The cursor slot alternates between `@` and blank at the D13 555 rate.
9. **Video DAC.** The dot stream and composite sync are mixed through resistors into the Q5 emitter follower.

### 2.3 Handshake with the processor section (sheet 2/3)

```
6820 PIA (A4)                         Terminal
  PB0-PB6  ───────────────────────►  RD1-RD7
  CB2      ──► gate (C5?) ──► DA ──►  DA      (data available)
  PB7      ◄── same DA level          (software polls bit 7 of $D012 = busy)
  CB1      ◄── B3 74123 (3.5 µs) ◄──  RDA     (ready for data / char accepted)
```

The 6502 writes to DSP ($D012). CB2, in handshake mode, asserts DA, so PB7 reads "busy". The terminal accepts the character and pulses RDA. The 74123 stretches that pulse to 3.5 µs and presents it to CB1, which releases CB2/DA. The software can then send the next character. **⚠ verify** the exact active levels of DA and RDA at the terminal connector.

### 2.4 Signals the processor section takes from the terminal

Sheet 2/3 shows a *TERMINAL* header feeding B7/B8 (74157/74S257) and the DRAM timing (74123, RAS/CAS logic):

| Signal | Use on sheet 2/3 |
|---|---|
| **CLA** (char rate, 14.31818 MHz ÷ 14 = 1.0227 MHz) | Source of the 6502 clock, through the "CLA (TERM)" input |
| **H4, H5, H6/H10, V0, V1, V2, V3, CL** | Row addresses and timing for refresh of the MK4096 DRAM, through B7/B8 |

**Consequence:** the replacement must reproduce these signals with the same frequencies and phase relationships, or the CPU and DRAM stop working. **⚠ verify** the exact bit-for-bit mapping and the phase of CL and H6/H10 relative to CLA on a real or replica board before you lay out the new counters.

### 2.5 Parts that drive this redesign

| Original | Problem | Replacement |
|---|---|---|
| 2504 ×7 (D4, D5, D14, C11) | Obsolete PMOS, needs -5/-12 V and two-phase clocks | 1 × SRAM |
| 2519 (C3) | Obsolete PMOS | Not needed, because the SRAM is read every scan line |
| 2513 (D2) | Obsolete PMOS, -5/-12 V | Parallel flash char ROM |
| DS0025 (C1) | Obsolete MOS clock driver | Not needed |
| 555 blink (D13) | Works, but analog | Frame-counter bit |
| 74LS/74xx timing gates | Hard to change | Timing ROM |

---

## 3. Architecture

### 3.1 Block diagram

```
                ┌──────────── 14.31818 MHz oscillator (5 V can)
                ▼
            U2 74AC74 ÷2 ──► DOTCLK 7.15909 MHz ──────────────────────────┐ (clocks every sync. part)
                │                                                         │
            U3 74HC163 ÷7 (dot phase 0-6) ──► U11 74HC138 ──► U12 74HC574 ──► PH0…PH6 (clean phase strobes)
                │  TC ─► CHAR_END (enable)          CLA ─► sheet 2/3
                ▼
   U4-U5 74HC163  H counter 0-64 ─────┐
   U6-U8 74HC163  V counter 0-261 ────┤
                                      ▼
                         U9 SST39SF010A TIMING ROM (A0-A6=H, A7-A15=V)
                                      ▼
                         U10 74HC574 ──► /CSYNC /BLANK H_END V_END ROW_CLK FRAME_START

   U15-16 TOP (mod 24) ──load@FRAME_START──► U13-14 VROW (mod 24, steps on ROW_CLK)
                                                      │
   Video address  {VROW[4:0], H[5:0]} ──┐             │
   Cursor address {ROW[4:0],  COL[5:0]} ┴─► U21-23 3×74HC157 (sel=write slot) ──► A0-A10
                                                                                    │
            RD1-RD7 ─► U26 74HCT273 input latch ─► U27 74HC541 ─► D0-D6 ◄──► U24 AS6C62256 SRAM
                                                                                    │ (video read)
   U30-31 2×74HC688 {VROW,H}=={ROW,COL} ─► CURMATCH ──┐                             ▼
                                                      └──────────► U25 74HC574 (char[6:0] + CURMATCH)
                                                                                    │
         U35 74HC393 frame counter ─► BLINK ── AND ──► CURSOR ─┐                    ▼
                                                               └─► U28 SST39SF010A CHAR ROM
                                                                    (A0-2=V[2:0], A3-9=char,
                                                                     A10=CURSOR, A11=BANK)
                                                                                    ▼
                                                                 U29 74HC166 ─► DOTS
                                                                                    ▼
                                              U37 74AC08 (DOTS·BLANK, /CSYNC buffer) ─► R-DAC ─► 75 Ω

   Sequencer: U33/U34 2×SST39SF010A + U36/U38 2×74HC574 (state + controls)
              inputs: state, DA, CLR, char, COL==39, ROW==TOP, READY (SLOW jumper)
              outputs: next state, WE, COL_INC/CLR, ROW_INC/CLR, TOP_INC/CLR, LATCH_LD/CLR, RDA
```

### 3.2 Clocking: everything synchronous to DOTCLK

- A **14.31818 MHz** canned oscillator (4 × NTSC colour burst) feeds a 74AC74 ÷2, giving **DOTCLK = 7.15909 MHz** (139.7 ns per dot).
- **Dot-phase counter** U3 74HC163 counts 0-6. It is synchronously cleared on phase 6, giving 7 dots per character cell. **Char period = 977.8 ns, char rate = 1.02273 MHz.** That is the original Apple-1 CPU clock, so U3's MSB (or a registered phase decode) supplies **CLA** directly.
- U11 74HC138 decodes phases 0-6 and U12 74HC574 registers them on DOTCLK. This gives glitch-free one-dot strobes `PH0…PH6`. The design uses no gated clocks: every counter is clocked by DOTCLK and advanced through its CEP/CET enables, qualified by `CHAR_END = PH6`.

### 3.3 Video timing

**Horizontal: 65 characters × 7 dots = 455 dots = 63.556 µs (15.734 kHz, exactly NTSC)**

| H count | Chars | Time | Use |
|---|---|---|---|
| 0-39 | 40 | 39.11 µs | RAM fetch of columns 0-39. Dots appear one char later (pipeline). |
| 40-46 | 7 | 6.84 µs | Right border and front porch |
| 47-51 | 5 | 4.89 µs | **HSYNC** (NTSC 4.7 µs ±0.1) |
| 52-64 | 13 | 12.71 µs | Back porch and left border |

The sync leading edge to the first visible dot is 17.6 µs. The NTSC active window opens 10.9 µs after the sync edge and is 52.6 µs wide, so the 39.1 µs text area has about 6.7 µs of margin on each side, i.e. it is centred.

**Vertical: 262 lines, progressive (15734 / 262 = 60.05 Hz, frame = 16.65 ms)**

| V count | Lines | Use |
|---|---|---|
| 0-191 | 192 | 24 text rows × 8 scan lines. V[2:0] is the scan line within the row. |
| 192-215 | 24 | Bottom border |
| 216-218 | 3 | **VSYNC.** /CSYNC is inverted with serrations. |
| 219-261 | 43 | Top border and vertical blanking |

**Counters:** H is U4-U5 74HC163 ×2 (7 bits) and V is U6-U8 74HC163 ×3 (9 bits). Both clear synchronously from the registered `H_END` / `V_END` outputs of the timing ROM.

### 3.4 Timing ROM

U9 is an SST39SF010A (128K × 8, 70 ns, DIP-32, in production). **A0-A6 = H, A7-A15 = V, A16 = 0** (a spare table, e.g. an alternate timing). The outputs are registered in U10 74HC574 at `CHAR_END`, so every entry is written **one char early**.

| Bit | Signal | Active |
|---|---|---|
| D0 | /CSYNC | Low during HSYNC. During VSYNC lines it is low except for the serration pulses (equalising pulses optional). |
| D1 | /BLANK | Low outside the visible window. The visible window is H 1-40 (the RAM-to-dot pipeline delays it by one char) and V 0-191. |
| D2 | H_END | ROM entry at H=63, so the counter clears 64 → 0 |
| D3 | V_END | ROM entry at V=261, H=63 |
| D4 | ROW_CLK | At H=63 of every line with V[2:0]=7 and V<192 |
| D5 | FRAME_START | At V=261, H=63. VROW ← TOP and FRAMESEEN is set. |
| D6-D7 | spare | e.g. a refresh strobe for sheet 2/3 if needed |

The image is generated by a script (see §8), so changing porches or sync widths needs no rewiring.

### 3.5 Display memory and scrolling

- U24 **AS6C62256** (32K × 8, 55 ns, 5 V). Only A0-A10 are used and the higher address lines are tied low.
- **Address = {row[4:0], col[5:0]}**, a 64-byte row stride, so no adder or multiplier is needed. Columns 40-63 are never written or shown.
- **Hardware scroll:** U15-16 hold `TOP`, the physical row shown at the top of the screen. U13-14 hold `VROW`, the video row counter. VROW loads TOP at FRAME_START, steps on ROW_CLK, and wraps 23 → 0. Scrolling is just `TOP ← TOP+1` plus clearing one line, so no data moves.
- **Mod-24 wrap.** Values 0-23 contain exactly one value with Q4·Q2·Q1·Q0 = 1, which is 23. So one 4-input AND (74HC21, ½ package) per counter drives the synchronous clear. COL==39 uses the same trick (Q5·Q2·Q1·Q0 is only true for 39 among 0-39).

### 3.6 RAM time-slicing within one character period (977.8 ns)

```
dot phase   │ 0 │ 1 │ 2 │ 3 │ 4 │ 5 │ 6 │
addr mux    │◄── VIDEO {VROW,H} ─►│◄ CURSOR {ROW,COL} ►│
RAM /OE     │▔▔▔▔▔▔ low ▔▔▔▔▔▔▔▔▔▔│     high          │
video latch │               ↑ U25 clocks at end of PH3
'541 /OE    │       high          │ low if WE_REQ     │
RAM /WE     │       high              │ low│     high │   (PH5 only, 140 ns, if WE_REQ)
'166 load   │                               ↑ end of PH6 (shows the char latched in this period)
```

- **Video read:** the window is 4 dots = 559 ns. The path is '157 (~20 ns) + SRAM tAA (55 ns) + '574 setup (~12 ns), which leaves more than 400 ns of slack.
- **Write:** address and data are stable one dot before /WE falls and one dot after it rises. tWP is 140 ns against 45 ns required, and tAS/tAH are 140 ns against 0 ns required.
- **Char ROM:** U25 changes at the end of PH3, and U29 loads at the end of PH6. Flash tACC is 70 ns against about 400 ns available.
- **Result:** the CPU side gets a guaranteed write slot every character period. There is no contention and no waiting for the beam.

### 3.7 Character generator

U28 is an SST39SF010A. Address map:

| Addr | Source |
|---|---|
| A0-A2 | V[2:0], the scan line in the cell (line 0 is always blank, as on the 2513) |
| A3-A9 | stored code [6:0] |
| A10 | CURSOR = CURMATCH · BLINK |
| A11 | BANK jumper: 0 = original 2513 look, 1 = extended (true lowercase) |
| A12-A16 | 0 (spare banks) |

The data byte goes to U29 74HC166 inputs H…A, and D7 (input H) is shifted out first. D7-D3 hold the 5 glyph columns left to right, D2-D1 are the 2-dot gap of the 7-dot cell, and D0 is unused.

**Image generation rules:**
- **Bank 0:** reproduce the 2513 character set (64 glyphs, $20-$5F) from the Signetics datasheet. Codes **$00-$1F render blank**: they are never stored except as the clear value. Codes $60-$7F fold onto $40-$5F as on the original. **⚠ verify** the original's exact folding of $60-$7F against the C4/C14 → D2 wiring. sbprojects reports that lowercase shows as uppercase.
- **Cursor half (A10=1):** every code renders the `@` glyph, as in the original. A solid block is an alternative.
- **Bank 1:** the same, plus a real lowercase set at $60-$7F.

### 3.8 Cursor

- **Cursor position** is held in counters, not in memory. COL is U17-18 (0-39) and ROW is U19-20 (mod 24, physical row).
- **Match:** U30-31 2×74HC688 compare {VROW, H[5:0]} with {ROW, COL}. The result CURMATCH is latched in U25 bit 7 alongside the char, so it stays in step with the pipeline.
- **Blink:** U35 74HC393 counts frames (clocked by registered V_END). Bit 4 gives BLINK at 60/32 ≈ 1.9 Hz. It replaces the 555.

### 3.9 Input path and PIA interface

- **Inputs:** RD1-RD7 go to **U26 74HCT273**. HCT is required because the 6820 output-high level can be as low as 2.4 V, below the 3.5 V V_IH of 74HC.
  - U26 is clocked by the registered `LATCH_LD` strobe from the sequencer.
  - It is cleared to $00 by `LATCH_CLR`. That provides the "blank" value for line and screen clears without a second data source.
- **Write driver:** U27 74HC541 drives the RAM data bus only during a write slot that has `WE_REQ` set.
- **DA:** buffered by a 74HCT14, then synchronised by two flops (U2 spare half and U38) to DOTCLK.
- **CLR switch:** RC-debounced through the 74HCT14 (Schmitt) and synchronised the same way. A power-on RC on the same input makes the terminal clear itself at reset.
- **RDA:** a registered sequencer output, active for 3 char periods (about 2.9 µs) to trigger the B3 74123 on sheet 2/3. Its polarity is set by jumper or by the ROM image. **⚠ verify** the trigger edge.

### 3.10 Control sequencer (ROM state machine)

- **Hardware:** two SST39SF010A in parallel (U33 = D0-D7, U34 = D8-D15), sharing the same address. Their outputs are registered by U36/U38 74HC574 at CHAR_END.
- **Moore machine:** each ROM word is the next state *plus that state's fixed controls*. While the register shows a state, its controls are active: a `WE` is executed in that period's write slot, and counter INC/CLR take effect at the end of the period. Because the ROM knows the current state, it always knows which counter changes are about to happen on the same edge.
- The bit assignments below are the single source of truth in `a1video/spec.py`. The transition function is `next_state()` in `a1video/roms.py`.

**Address inputs (17 bits):**

| Bits | Input |
|---|---|
| A0-A4 | current state (5 bits, 19 states used) |
| A5 | DA (synced) |
| A6 | CLR (synced) |
| A7 | COL==39 (74HC21: Q5·Q2·Q1·Q0) |
| A8 | ROW==TOP (U32 74HC688, 5 bits used) |
| A9 | READY = ¬SLOW + FRAMESEEN (authentic-speed jumper) |
| A10-A16 | latched char [6:0] (U26 outputs) |

**Outputs (16 bits):**

| Bits | Output |
|---|---|
| D0-D4 | next state |
| D5 | WE |
| D6 | COL_INC |
| D7 | COL_CLR |
| D8 | ROW_INC (mod 24 in hardware) |
| D9 | ROW_CLR |
| D10 | TOP_INC (mod 24 in hardware) |
| D11 | TOP_CLR |
| D12 | LATCH_LD |
| D13 | LATCH_CLR |
| D14 | RDA |
| D15 | FRAMESEEN_CLR |

**State table** (controls are active while in the state; in "Next", the inputs show counter values *before* this state's controls are applied):

| # | State | Controls | Next |
|---|---|---|---|
| 0 | IDLE | — | CLR → CLRALL. DA → LOAD. Otherwise IDLE. |
| 1 | LOAD | LATCH_LD, FRAMESEEN_CLR | DECODE |
| 2 | DECODE | — | char = $0D → NL. char ≥ $20 → PRINT. Otherwise → ACK (ignored, as in the original). |
| 3 | PRINT | WE, COL_INC | COL==39 (column 39 was just written) → NL. Otherwise → ACK. |
| 4 | NL | COL_CLR, ROW_INC, LATCH_CLR | SCRCHK |
| 5 | SCRCHK | — | ROW (the new row) == TOP → SCROLL. Otherwise → CLRL_A. |
| 6 | SCROLL | TOP_INC | CLRL_A |
| 7 | CLRL_A | WE ($00), COL_INC | COL==39 → CLRL_A_END. Otherwise CLRL_A. |
| 8 | CLRL_A_END | COL_CLR | ACK |
| 9 | ACKW | — | READY → ACK1. Otherwise ACKW. |
| 10-12 | ACK1-3 | RDA (3 periods ≈ 2.9 µs) | ACK2, ACK3, then WAITDA |
| 13 | WAITDA | — | DA dropped → IDLE. Otherwise WAITDA. |
| 14 | CLRALL | TOP_CLR, ROW_CLR, COL_CLR, LATCH_CLR | CLRL_B |
| 15 | CLRL_B | WE ($00), COL_INC | COL==39 → NEXTROW. Otherwise CLRL_B. |
| 16 | NEXTROW | COL_CLR, ROW_INC | CLRCHK |
| 17 | CLRCHK | — | ROW wrapped back to TOP (= 0) → WAITCLR. Otherwise → CLRL_B. |
| 18 | WAITCLR | — | CLR released → IDLE. Otherwise WAITCLR. |
| 19-31 | (unused) | — | IDLE (power-up recovery) |

"ACK" means ACK1 when READY is set and ACKW otherwise. Because CLRALL sets TOP to 0, the clear-all loop ends when ROW wraps from 23 back to TOP, so no ROW==23 input is needed.

**Behaviour:**
- **Scroll rule:** a newline moves ROW down by one. If the new ROW equals TOP, the screen was full, so TOP advances (scroll up one line). The new line is always cleared. This matches the original: the cursor fills the screen top-down after CLR, then scrolls at the bottom.
- **Measured latency, DA to RDA** (simulator, `python3 -m a1video.simulate`):
  - Printable character: **4.9 µs**
  - CR or wrap (with line clear): **≤ 47 µs**
  - CLR: **< 1.1 ms**
  - Original: up to 16.7 ms per character
- **Authentic-speed jumper (SLOW):** with SLOW fitted, the machine waits in ACKW for the next FRAME_START. The terminal then accepts at most one character per frame, like the original (the simulator measures 17 019 periods ≈ 16.6 ms per character).

### 3.11 Outputs to the processor section (sheet 2/3)

| Original signal | New source | Note |
|---|---|---|
| CLA | Phase counter U3, registered | 1.0227 MHz. Same frequency as the original. **⚠ verify** duty cycle and phase vs. the old D11 output. |
| H4, H5, H6/H10 | Bits of the new H counter / phase counter | **⚠ verify.** The original H chain (D6 74160 → D7) may have a different modulus or bit weighting. If so, generate the equivalents from spare timing-ROM outputs (D6/D7) instead. |
| V0-V3 | V[0..3] of the new V counter | Refresh row addresses. The sequence must cover every MK4096 row within 2 ms. |
| CL | Dot-phase or char-phase strobe | **⚠ verify** what CL is on the original (it appears near D11). |

If the new counter bits cannot be made to match exactly, the doc's fallback is that the spare timing-ROM bits (and a second registered ROM if needed) synthesise each processor-side signal as an arbitrary function of (H, V).

### 3.12 Composite video output

U37 74AC08 forms `VID = DOTS · /BLANK` and buffers `/CSYNC`. AC parts are used because they can source about 15 mA with a good V_OH. The two signals drive a resistor network that also sets a **75 Ω source impedance**:

```
 /CSYNC ──[ 620 Ω ]──┐
                     ├──●────────► RCA out ──► TV (75 Ω)
 VID    ──[ 270 Ω ]──┘  │
                      [120 Ω]
                        │
                       GND
```

Into a 75 Ω load (Vcc = 5 V):

| State | /CSYNC | VID | V_out |
|---|---|---|---|
| Sync | 0 | 0 | 0.00 V |
| Black | 5 V | 0 | 5 × (1/620) / ΣG = **0.30 V** |
| White | 5 V | 5 V | 5 × (1/620 + 1/270) / ΣG = **0.99 V** |

ΣG = 1/620 + 1/270 + 1/120 + 1/75 = 0.02698 S. The source impedance is 1/(1/620 + 1/270 + 1/120) = **73 Ω**.

VID must be low during sync, which /BLANK guarantees. The 74AC V_OH sags about 0.2 V at 15 mA, so white is about 0.95 V; trim the 270 Ω if needed. An alternative output stage is a 2N3904 emitter follower, as in the original Q5, followed by a 75 Ω series resistor.

---

## 4. Bill of materials (preliminary)

| Ref | Part | Qty | Function |
|---|---|---|---|
| X1 | 14.31818 MHz 5 V oscillator | 1 | Master clock |
| U2 | 74AC74 | 1 | ÷2, DA synchroniser |
| U3, U4-8, U13-20 | 74HC163 | 14 | Dot phase, H ×2, V ×3, VROW ×2, TOP ×2, COL ×2, ROW ×2 |
| U9, U28, U33, U34 | SST39SF010A-70 | 4 | Timing ROM, char ROM, sequencer ×2 |
| U10, U12, U25, U36, U38 | 74HC574 | 5 | Registered timing, phases, video latch, sequencer |
| U11 | 74HC138 | 1 | Dot-phase decode |
| U21-23 | 74HC157 | 3 | RAM address mux |
| U24 | AS6C62256-55 | 1 | Display RAM |
| U26 | 74HCT273 | 1 | Input latch (TTL-level inputs) |
| U27 | 74HC541 | 1 | RAM write driver |
| U29 | 74HC166 | 1 | Dot shifter |
| U30-32 | 74HC688 | 3 | Cursor compare ×2, ROW==TOP |
| U35 | 74HC393 | 1 | Frame/blink counter |
| U39 | 74HCT14 | 1 | DA/CLR input buffers, debounce |
| U40-41 | 74HC21 | 2 | ==23 / ==39 detects |
| U37 | 74AC08 | 1 | Video gating and drivers |
| | Resistors 620/270/120 Ω, RCA jack, jumpers (SLOW, BANK, RDA polarity), decoupling | | |

**Total: about 41 ICs, all in current production, single +5 V.** The original terminal section had about 30 ICs plus a three-rail supply. The count is higher because one SRAM replaces the self-sequencing shift registers and needs explicit addressing. In exchange the design gets fast writes, hardware scroll and editable timing.

---

## 5. Differences from the original, and risks

| Item | Original | New | Impact |
|---|---|---|---|
| Char acceptance | ≤ 16.7 ms | ~5 µs (CR ~44 µs) | Software that uses screen output as a delay will run faster. Use the SLOW jumper for those programs. |
| Hidden slots | 64 hidden slots, cleared during VBL | None | No visible effect |
| Clear | Held CLR clears progressively. A short press clears part of the screen. | Clears the whole screen in about 1 ms on any press | A partial clear is no longer possible |
| Lowercase | Folded (⚠ verify) | Folded (bank 0) or real lowercase (bank 1) | — |
| Cell | 7-dot (CLA = dot/7) | 7-dot | Same aspect ratio |
| Line/field rate | ⚠ verify the original's H modulus | Exact NTSC 15.734 kHz / 60.05 Hz progressive | Better compatibility with modern TVs and capture devices |
| Processor services | CLA, refresh addresses | Reproduced from the new counters | **Highest risk.** See §3.11. |
| Supply | +5, -5, -12 V | +5 V only | -5/-12 V are still needed elsewhere on the board for the MK4096 DRAM |

---

## 6. Open items (verify on hardware)

1. DA and RDA active levels, and which RDA edge triggers B3, at the terminal connector.
2. The original H counter modulus and line length (D6/D7 presets), and the exact meaning of H6/H10, CL and V0-V3 as used by B7/B8 on sheet 2/3.
3. The CLA duty cycle and phase, and whether the 6502 clock stretch depends on terminal timing.
4. The original case folding of codes $60-$7F (C4/C14 → D2 wiring).
5. Whether any Apple-1 software (e.g. games or Integer BASIC programs) depends on output being slow.

---

## 7. Verification plan

1. **Arithmetic** (done in this doc):
   - DOTCLK 7.15909 MHz ⇒ 139.68 ns per dot and 977.8 ns per char
   - 455 dots = 63.556 µs ⇒ 15.734 kHz
   - 262 lines ⇒ 16.651 ms frame ⇒ 60.05 Hz
   - 40 × 7 = 280 dots = 39.11 µs, which fits the 52.6 µs active window
   - The DAC levels 0 / 0.30 / 0.99 V and the 73 Ω source impedance
2. **ROM image generator** (done): `python3 -m a1video.gen_roms` writes `roms/timing.bin`, `roms/chargen.bin`, `roms/seq_lo.bin` and `roms/seq_hi.bin` from the tables in §3.4, §3.7 and §3.10. Before writing, it checks the generated video timing.
3. **Simulation** (done): `a1video/sim.py` steps the hardware one character period at a time and uses only the ROM images, so it validates their contents. It also models the PIA handshake and renders composite frames (`python3 -m a1video.simulate --png frame.png`). `python3 -m unittest discover -s tests -t .` checks the following against a behavioural reference terminal:
   - video timing: line and frame length, sync widths, serrations, visible window
   - char ROM: the 2513 example 'S', blank control codes, case folding, cursor glyph
   - sequencer ROM: power-up recovery, no conflicting controls
   - screen behaviour: Woz-style output, wrap, scroll, ignored control codes, a 3000-byte random stream, CLR mid-stream, power-up garbage
   - latency, RDA pulse width and slow mode
   - pixel-exact glyph and cursor rendering
4. **Logic simulation** in Digital or Logisim-Evolution with the real ROM images, before laying out a PCB in KiCad.
5. **Bench bring-up:**
   - Stand-alone, driven by a 6821 or a logic-analyser pattern generator on RD/DA
   - Scope the composite output: sync 0 V, black 0.3 V, white 1.0 V, H 63.56 µs
   - Then connect to a replica processor board and confirm CPU clock and DRAM refresh
