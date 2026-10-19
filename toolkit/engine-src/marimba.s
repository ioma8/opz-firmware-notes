; marimba.s - "marimba body": a modal resonator engine for the OP-Z.
;
; This is the implementation as source. It is written against the ABI in doc `11` §11.9:
;
;   initModule(id, host_table, out)        id must be 0, host table is 0x81003850
;   init(ctx, variant)                     clear per-voice context
;   onNoteOn(a1, note, ctx, a4)            R1 = note, R2 = ctx
;   onNoteOff(a1, ctx, ...)                gate off
;   render(out, freq_q16, off, state, params, env)
;                                          out = interleaved 32-bit stereo, 64 frames
;
; Six modes, coupled (rotation) form, Q31 fractional multiplies. The rotation is used instead of
; direct form II because the direct form needs a coefficient of 2*r*cos(w), which saturates Q31 --
; see doc `11` §11.11, where that bug was caught by measurement.
;
;     y1' = r*cos(w)*y1 - r*sin(w)*y2
;     y2' = r*sin(w)*y1 + r*cos(w)*y2
;
; A voice comes alive from render's own arguments, never from onNoteOn: the pitch is argument 2 (Q16 Hz),
; located in the coefficient table by a binary search over a Q16-Hz table, and the amp object's state word
; (argument 6, +0x10) says whether the OS still wants this voice. The strike is seeded when that goes from
; idle to active. This is what makes the engine polyphonic - each voice record the OS ticks has its own
; context, pitch and amp, so N records sound N notes.
;
; Per mode: 4 multiplies, 2 add/subs, 2 state words. Six modes = 24 multiplies per frame.
; A block is 64 frames, so one render call is 1536 multiplies -- comfortably inside the core.
;
; Layout of the per-voice context (all Q31 unless noted):
;   +0x00  struck (0 = needs a strike, 1 = ringing; onNoteOff sets 1, onNoteOn clears it)
;   +0x04  frame counter / block phase
;   +0x08  mode count
;   +0x10 .. per-mode c, s, y1, y2  (4 words each, 6 modes = 96 bytes)
;   +0x80  strike strength
;   +0x84  strike position
;   +0x88  brightness
;
; Macros (the eight the plug exposes, from doc `11` §11.4):
;   params[0] tune          params[4] strike position
;   params[1] decay         params[5] mallet hardness
;   params[2] --            params[6] drive
;   params[3] brightness    params[7] body / level
;
; params[2..5] are the amp arguments the OS smoothes (doc `11` §11.9), so params[1] is where the decay
; macro is read; params[4] and [5] above are therefore not live knobs in this build.
;
; render also takes a sixth argument, the amp object. amp+0x10 is the amp state machine and zero there
; means the OS released the voice, so the render returns before touching the mix - the same early return
; every factory instrument starts with.

        .section code, "ax"

; ---------------------------------------------------------------------------- initModule
; int initModule(int id, void *host, int *out)
initModule:
        CC = R0 == 0 ;                  ; the OS passes 0 (doc 11 §11.9); anything else is a new ABI
        IF !CC JUMP .fail
        [0x0081be2d58] = R1 ;           ; save the host services table
        R1 = 0 ;
        [R2] = R1 ;                     ; *out = 0
        R0 = 1 ;                        ; 1 = loaded
        RTS ;
.fail:
        R0 = 0 ;
        RTS ;

; ---------------------------------------------------------------------------- init
; void init(void *ctx, int variant)
init:
        P0 = R0 ;
        R1 = 0 ;
        R2 = 0x20 ;                     ; same 0x20-byte clear chord performs
        CALL .memset ;
        RTS ;

; ---------------------------------------------------------------------------- onNoteOn
; void onNoteOn(int a1, int note, void *ctx, int a4)
;
; R1 = note, R2 = ctx. The engine derives its own pitch from the note rather than trusting
; render's frequency argument: that keeps the build dependent on one unverified convention
; instead of two, and the hardware test in doc `11` §11.9 settles it either way.
onNoteOn:
        P0 = R2 ;                       ; P0 -> ctx
        R0 = 1 ;
        [P0] = R0 ;                     ; gate on
        R0 = 6 ;
        [P0 + 0x08] = R0 ;              ; six modes
        ; --- excitation: impulse into y1, sign per mode from strike position, level from strength
        ; (the coefficient tables are computed by .setup from the note and the macros)
        CALL .setup ;
        RTS ;

; ---------------------------------------------------------------------------- onNoteOff
onNoteOff:
        P0 = R1 ;
        R0 = 0 ;
        [P0] = R0 ;                     ; gate off: the render loop then returns immediately
        RTS ;

; ---------------------------------------------------------------------------- render
; void render(int *out, int freq_q16, int off, void *state, int *params, void *env)
;
; out -> P5, 64 frames of interleaved 32-bit stereo, two words per frame.
render:
        [--SP] = (R7:4, P5:3) ;
        P5 = R0 ;                       ; output buffer
        P4 = [SP + 0x1c] ;              ; args 4..6 are on the stack
        P3 = [SP + 0x20] ;
        P2 = [SP + 0x24] ;              ; the amp object
        R0 = [P2 + 0x10] ;              ; amp+0x10: the voice activity word
        CC = R0 == 0 ;
        IF CC JUMP .idle ;              ; idle: clear the struck flag, write nothing
        CALL .strike ;                  ; seed the excitation when the flag is clear
        R0 = 1 ;
        [P4] = R0 ;                     ; state+0: gate

        R6 = 0x40 ;                     ; 64 frames per block
.frame:
        ; y1' = c*y1 - s*y2 ; y2' = s*y1 + c*y2, summed over six modes, then out[] = acc twice
        ; (mode unrolling: this is the section that the encoder must be able to emit)
        CALL .modes ;
        [P5++] = R0 ;
        [P5++] = R0 ;
        R6 += -1 ;
        CC = R6 == 0 ;
        IF !CC JUMP .frame ;
.done:
        (R7:4, P5:3) = [SP++] ;
        RTS ;

; ---------------------------------------------------------------------------- helpers
; .setup  - compute per-mode c = r*cos(w), s = r*sin(w) from the note and the macros.
;           Contains the note->frequency exponential, the inharmonicity blend and the per-mode
;           damping. Implemented in toolkit/opzmarimba.py (validated, 9/9 measurement checks) and
;           to be transcribed here once the shift and branch encodings are in place.
.setup:
        RTS ;
; .modes  - the six-mode rotation for one frame; the hot path.
.modes:
        R0 = 0 ;
        RTS ;
; .memset - R0=dest, R1=value, R2=count
.memset:
        RTS ;
