; Saw013a (saw013a.engine, plug 26) - disassembly for the port.
; initModule 0x1238c4 (32 B), init 0x1238e4 (176 B), render 0x123994 (3180 B),
; onNoteOn 0x124480 (996 B), onNoteOff 0x124864 (4 B), interface 0x124a30 (8 B).

;; ---- 0x1238c4 ----
;-- Saw013a::initModule(unsigned int, ModuleCallbackInterface const*, unsigned int*):
; Saw013a::initModule(unsigned int, ModuleCallbackInterface const*, un
; signed int*)
0x001238c4      a0000035       cbnz w0, 0x1238d8
0x001238c8      880500f0       adrp x8, reloc.Crush::sampBuffer_l      ; 0x1d6000
0x001238cc      080940f9       ldr x8, [x8, 0x10]
0x001238d0      010100f9       str x1, [x8]
0x001238d4      5f0000b9       str wzr, [x2]
0x001238d8      1f000071       cmp w0, 0
0x001238dc      e0179f1a       cset w0, eq
0x001238e0      c0035fd6       ret
;-- Saw013a::init(void*, unsigned int, unsigned int, void*, void*):
0x001238e4      00e4006f       movi v0.2d, 0000000000000000            ; Saw013a::init(void*, unsigned int, unsigned int, void*, void*)
0x001238e8      28100051       sub w8, w1, 4
0x001238ec      1f0d0071       cmp w8, 3
0x001238f0      1f3000f9       str xzr, [x0, 0x60]
0x001238f4      000002ad       stp q0, q0, [x0, 0x40]
0x001238f8      000001ad       stp q0, q0, [x0, 0x20]
0x001238fc      000000ad       stp q0, q0, [x0]
0x00123900      88010054       b.hi 0x123930

;; ---- 0x1238e4 ----
;-- Saw013a::init(void*, unsigned int, unsigned int, void*, void*):
0x001238e4      00e4006f       movi v0.2d, 0000000000000000            ; Saw013a::init(void*, unsigned int, unsigned int, void*, void*)
0x001238e8      28100051       sub w8, w1, 4
0x001238ec      1f0d0071       cmp w8, 3
0x001238f0      1f3000f9       str xzr, [x0, 0x60]
0x001238f4      000002ad       stp q0, q0, [x0, 0x40]
0x001238f8      000001ad       stp q0, q0, [x0, 0x20]
0x001238fc      000000ad       stp q0, q0, [x0]
0x00123900      88010054       b.hi 0x123930
0x00123904      c9faffd0       adrp x9, 0x7d000
0x00123908      29392c91       add x9, x9, 0xb0e
0x0012390c      8a000010       adr x10, 0x12391c
0x00123910      2b696838       ldrb w11, [x9, x8]
0x00123914      4a090b8b       add x10, x10, x11, lsl 2
0x00123918      40011fd6       br x10
0x0012391c      288900f0       adrp x8, 0x124a000
0x00123920      e9678692       mov x9, -0x3340
0x00123924      8999bdf2       movk x9, 0xeccc, lsl 16
0x00123928      08d185b9       ldrsw x8, [x8, 0x5d0]
0x0012392c      12000014       b 0x123974
0x00123930      288900f0       adrp x8, 0x124a000
0x00123934      08cd45b9       ldr w8, [x8, 0x5cc]
0x00123938      083800b9       str w8, [x0, 0x38]
0x0012393c      c0035fd6       ret
0x00123940      288900f0       adrp x8, 0x124a000
0x00123944      08d545b9       ldr w8, [x8, 0x5d4]
0x00123948      083800b9       str w8, [x0, 0x38]
0x0012394c      c0035fd6       ret
0x00123950      288900f0       adrp x8, 0x124a000
0x00123954      e9339392       mov x9, -0x99a0
0x00123958      c9ccbcf2       movk x9, 0xe666, lsl 16
0x0012395c      08d985b9       ldrsw x8, [x8, 0x5d8]
0x00123960      05000014       b 0x123974
0x00123964      288900f0       adrp x8, 0x124a000
0x00123968      e9999992       mov x9, -0xccd0
0x0012396c      6966bef2       movk x9, 0xf333, lsl 16
0x00123970      08dd85b9       ldrsw x8, [x8, 0x5dc]
0x00123974      097d099b       mul x9, x8, x9
0x00123978      29fd5fd3       lsr x9, x9, 0x1f
0x0012397c      0801092b       adds w8, w8, w9
0x00123980      097d1f13       asr w9, w8, 0x1f
0x00123984      29010152       eor w9, w9, 0x80000000
0x00123988      2861881a       csel w8, w9, w8, vs
0x0012398c      083800b9       str w8, [x0, 0x38]
0x00123990      c0035fd6       ret
;-- Saw013a::render(fract32_t*, unsigned int, int, void*, unsigned int const*, ADSR*):
; Saw013a::render(fract32_t*, unsigned int, int, void*, unsigned int c
; onst*, ADSR*)
0x00123994      ffc302d1       sub sp, sp, 0xb0
0x00123998      e923046d       stp d9, d8, [sp, 0x40]
0x0012399c      fd7b05a9       stp x29, x30, [sp, 0x50]
0x001239a0      fd430191       add x29, sp, 0x50
0x001239a4      fc6f06a9       stp x28, x27, [sp, 0x60]
0x001239a8      fa6707a9       stp x26, x25, [sp, 0x70]
0x001239ac      f85f08a9       stp x24, x23, [sp, 0x80]
0x001239b0      f65709a9       stp x22, x21, [sp, 0x90]
0x001239b4      f44f0aa9       stp x20, x19, [sp, 0xa0]
0x001239b8      58d03bd5       mrs x24, tpidr_el0
0x001239bc      081740f9       ldr x8, [x24, 0x28]
0x001239c0      a8831ef8       stur x8, [x29, -0x18]
0x001239c4      a81040b9       ldr w8, [x5, 0x10]
0x001239c8      285f0034       cbz w8, 0x1245ac
0x001239cc      f30303aa       mov x19, x3
0x001239d0      68944139       ldrb w8, [x3, 0x65]

;; ---- 0x123994 ----
;-- Saw013a::render(fract32_t*, unsigned int, int, void*, unsigned int const*, ADSR*):
; Saw013a::render(fract32_t*, unsigned int, int, void*, unsigned int c
; onst*, ADSR*)
0x00123994      ffc302d1       sub sp, sp, 0xb0
0x00123998      e923046d       stp d9, d8, [sp, 0x40]
0x0012399c      fd7b05a9       stp x29, x30, [sp, 0x50]
0x001239a0      fd430191       add x29, sp, 0x50
0x001239a4      fc6f06a9       stp x28, x27, [sp, 0x60]
0x001239a8      fa6707a9       stp x26, x25, [sp, 0x70]
0x001239ac      f85f08a9       stp x24, x23, [sp, 0x80]
0x001239b0      f65709a9       stp x22, x21, [sp, 0x90]
0x001239b4      f44f0aa9       stp x20, x19, [sp, 0xa0]
0x001239b8      58d03bd5       mrs x24, tpidr_el0
0x001239bc      081740f9       ldr x8, [x24, 0x28]
0x001239c0      a8831ef8       stur x8, [x29, -0x18]
0x001239c4      a81040b9       ldr w8, [x5, 0x10]
0x001239c8      285f0034       cbz w8, 0x1245ac
0x001239cc      f30303aa       mov x19, x3
0x001239d0      68944139       ldrb w8, [x3, 0x65]
0x001239d4      e8600035       cbnz w8, 0x1245f0
0x001239d8      88244069       ldpsw x8, x9, [x4]
0x001239dc      0b00b012       mov w11, 0x7fffffff
0x001239e0      0c608852       mov w12, 0x4300
0x001239e4      2a008012       mov w10, -2
0x001239e8      0caaba72       movk w12, 0xd550, lsl 16
0x001239ec      0da08152       mov w13, 0xd00
0x001239f0      f70300aa       mov x23, x0
0x001239f4      6e01086b       subs w14, w11, w8
0x001239f8      ed7dae72       movk w13, 0x73ef, lsl 16
0x001239fc      d17d1f13       asr w17, w14, 0x1f
0x00123a00      0c7d0c9b       mul x12, x8, x12
0x00123a04      31020152       eor w17, w17, 0x80000000
0x00123a08      f03f9192       mov x16, -0x8a00
0x00123a0c      2e628e1a       csel w14, w17, w14, vs
0x00123a10      6b01096b       subs w11, w11, w9
0x00123a14      717d1f13       asr w17, w11, 0x1f
0x00123a18      8cfd6093       asr x12, x12, 0x20
0x00123a1c      c07daa9b       umull x0, w14, w10
0x00123a20      31020152       eor w17, w17, 0x80000000
0x00123a24      2b628b1a       csel w11, w17, w11, vs
0x00123a28      d17dad9b       umull x17, w14, w13
0x00123a2c      0dfc60d3       lsr x13, x0, 0x20
0x00123a30      f603012a       mov w22, w1
0x00123a34      efff9792       mov x15, -0xc000
0x00123a38      306db6f2       movk x16, 0xb369, lsl 16
0x00123a3c      8c7d0b9b       mul x12, x12, x11
0x00123a40      af57b7f2       movk x15, 0xbabd, lsl 16
0x00123a44      a17d0b9b       mul x1, x13, x11
0x00123a48      f503022a       mov w21, w2
0x00123a4c      107d109b       mul x16, x8, x16
0x00123a50      31fe60d3       lsr x17, x17, 0x20
0x00123a54      82fd5fd3       lsr x2, x12, 0x1f
0x00123a58      2cfc5fd3       lsr x12, x1, 0x1f
0x00123a5c      cf7d0f9b       mul x15, x14, x15
0x00123a60      8101022b       adds w1, w12, w2
0x00123a64      10fe6093       asr x16, x16, 0x20
0x00123a68      317e099b       mul x17, x17, x9
0x00123a6c      227c1f13       asr w2, w1, 0x1f
0x00123a70      effd6093       asr x15, x15, 0x20
0x00123a74      42000152       eor w2, w2, 0x80000000
0x00123a78      107e0b9b       mul x16, x16, x11
0x00123a7c      31fe5fd3       lsr x17, x17, 0x1f
0x00123a80      4160811a       csel w1, w2, w1, vs
0x00123a84      ef7d0b9b       mul x15, x15, x11
0x00123a88      3100112b       adds w17, w1, w17
0x00123a8c      01fe5fd3       lsr x1, x16, 0x1f
0x00123a90      307e1f13       asr w16, w17, 0x1f
0x00123a94      effd5fd3       lsr x15, x15, 0x1f
0x00123a98      10020152       eor w16, w16, 0x80000000
0x00123a9c      1062911a       csel w16, w16, w17, vs
0x00123aa0      ef01012b       adds w15, w15, w1
0x00123aa4      e0ff8092       mov x0, -0x800
0x00123aa8      e17d1f13       asr w1, w15, 0x1f
0x00123aac      606dbaf2       movk x0, 0xd36b, lsl 16
0x00123ab0      21000152       eor w1, w1, 0x80000000
0x00123ab4      2f608f1a       csel w15, w1, w15, vs
0x00123ab8      e17f8292       mov x1, -0x1400
0x00123abc      c07d009b       mul x0, x14, x0
0x00123ac0      41e7b9f2       movk x1, 0xcf3a, lsl 16
0x00123ac4      e33f9a92       mov x3, -0xd200
0x00123ac8      e6bf8c92       mov x6, -0x6600
0x00123acc      43b6b3f2       movk x3, 0x9db2, lsl 16
0x00123ad0      00fc6093       asr x0, x0, 0x20
0x00123ad4      017d019b       mul x1, x8, x1
0x00123ad8      e6e9b9f2       movk x6, 0xcf4f, lsl 16
0x00123adc      037d039b       mul x3, x8, x3
0x00123ae0      07d08c52       mov w7, 0x6680
0x00123ae4      007c099b       mul x0, x0, x9
0x00123ae8      c7acac72       movk w7, 0x6566, lsl 16                 ; 'fe'
0x00123aec      067d069b       mul x6, x8, x6
0x00123af0      63fc6093       asr x3, x3, 0x20
0x00123af4      00fc5fd3       lsr x0, x0, 0x1f
0x00123af8      2000679e       fmov d0, x1
0x00123afc      ef01002b       adds w15, w15, w0
0x00123b00      007d079b       mul x0, x8, x7
0x00123b04      617c0b9b       mul x1, x3, x11
0x00123b08      03c09752       mov w3, 0xbe00
0x00123b0c      e27f9892       mov x2, -0xc400
0x00123b10      e379af72       movk w3, 0x7bcf, lsl 16
0x00123b14      42e5aef2       movk x2, 0x772a, lsl 16                 ; '*w'
0x00123b18      f40305aa       mov x20, x5
0x00123b1c      c01c184e       mov v0.d[1], x6
0x00123b20      037d039b       mul x3, x8, x3
0x00123b24      c27d029b       mul x2, x14, x2
0x00123b28      0100679e       fmov d1, x0
0x00123b2c      e67d1f13       asr w6, w15, 0x1f
0x00123b30      21fc5fd3       lsr x1, x1, 0x1f
0x00123b34      42fc6093       asr x2, x2, 0x20
0x00123b38      c6000152       eor w6, w6, 0x80000000
0x00123b3c      0004604f       sshr v0.2d, v0.2d, 0x20
0x00123b40      cf608f1a       csel w15, w6, w15, vs
0x00123b44      611c184e       mov v1.d[1], x3
0x00123b48      457c0b9b       mul x5, x2, x11
0x00123b4c      427c099b       mul x2, x2, x9
0x00123b50      06208952       mov w6, 0x4900
0x00123b54      a0fc5fd3       lsr x0, x5, 0x1f
0x00123b58      861aad72       movk w6, 0x68d4, lsl 16
0x00123b5c      0500669e       fmov x5, d0
0x00123b60      0000012b       adds w0, w0, w1
0x00123b64      033c184e       mov x3, v0.d[1]
0x00123b68      017c1f13       asr w1, w0, 0x1f
0x00123b6c      2004604f       sshr v0.2d, v1.2d, 0x20
0x00123b70      21000152       eor w1, w1, 0x80000000
0x00123b74      a57c099b       mul x5, x5, x9
0x00123b78      2060801a       csel w0, w1, w0, vs
0x00123b7c      41fc5fd3       lsr x1, x2, 0x1f
0x00123b80      067d069b       mul x6, x8, x6
0x00123b84      0000012b       adds w0, w0, w1
0x00123b88      617c099b       mul x1, x3, x9
0x00123b8c      0300669e       fmov x3, d0
0x00123b90      077c1f13       asr w7, w0, 0x1f
0x00123b94      023c184e       mov x2, v0.d[1]
0x00123b98      a000679e       fmov d0, x5
0x00123b9c      05e88152       mov w5, 0xf40                           ; '@\x0f'
0x00123ba0      e7000152       eor w7, w7, 0x80000000
0x00123ba4      e5d6a772       movk w5, 0x3eb7, lsl 16
0x00123ba8      637c099b       mul x3, x3, x9
0x00123bac      201c184e       mov v0.d[1], x1
0x00123bb0      e060801a       csel w0, w7, w0, vs
0x00123bb4      c57da59b       umull x5, w14, w5
0x00123bb8      11e09652       mov w17, 0xb700
0x00123bbc      427c099b       mul x2, x2, x9
0x00123bc0      51ecbf72       movk w17, 0xff62, lsl 16
0x00123bc4      a5fc60d3       lsr x5, x5, 0x20
0x00123bc8      6100679e       fmov d1, x3
0x00123bcc      c3fc6093       asr x3, x6, 0x20
0x00123bd0      06c88f52       mov w6, 0x7e40                          ; '@~'
0x00123bd4      061ea772       movk w6, 0x38f0, lsl 16
0x00123bd8      a57c0b9b       mul x5, x5, x11
0x00123bdc      637c0b9b       mul x3, x3, x11
0x00123be0      0202271e       fmov s2, w16
0x00123be4      c17da69b       umull x1, w14, w6
0x00123be8      06108752       mov w6, 0x3880
0x00123bec      411c184e       mov v1.d[1], x2
0x00123bf0      a2fc5fd3       lsr x2, x5, 0x1f
0x00123bf4      63fc5fd3       lsr x3, x3, 0x1f
0x00123bf8      21fc60d3       lsr x1, x1, 0x20
0x00123bfc      4200032b       adds w2, w2, w3
0x00123c00      03309252       mov w3, 0x9180
0x00123c04      e30fac72       movk w3, 0x607f, lsl 16                 ; '\x7f`'
0x00123c08      457c1f13       asr w5, w2, 0x1f
0x00123c0c      217c099b       mul x1, x1, x9
0x00123c10      a5000152       eor w5, w5, 0x80000000
0x00123c14      037d039b       mul x3, x8, x3
0x00123c18      a260821a       csel w2, w5, w2, vs
0x00123c1c      21fc5fd3       lsr x1, x1, 0x1f
0x00123c20      05a88052       mov w5, 0x540
0x00123c24      4100012b       adds w1, w2, w1
0x00123c28      62fc6093       asr x2, x3, 0x20
0x00123c2c      237c1f13       asr w3, w1, 0x1f
0x00123c30      c50ea572       movk w5, 0x2876, lsl 16                 ; 'v('
0x00123c34      062ba772       movk w6, 0x3958, lsl 16                 ; 'X9'
0x00123c38      427c099b       mul x2, x2, x9
0x00123c3c      63000152       eor w3, w3, 0x80000000
0x00123c40      d17db19b       umull x17, w14, w17
0x00123c44      ce7da59b       umull x14, w14, w5
0x00123c48      6160811a       csel w1, w3, w1, vs
0x00123c4c      037d069b       mul x3, x8, x6
0x00123c50      42fc5fd3       lsr x2, x2, 0x1f
0x00123c54      cefd60d3       lsr x14, x14, 0x20
0x00123c58      2100022b       adds w1, w1, w2
0x00123c5c      62fc6093       asr x2, x3, 0x20
0x00123c60      237c1f13       asr w3, w1, 0x1f
0x00123c64      c67d0b9b       mul x6, x14, x11
0x00123c68      63000152       eor w3, w3, 0x80000000
0x00123c6c      427c0b9b       mul x2, x2, x11
0x00123c70      6360811a       csel w3, w3, w1, vs
0x00123c74      c1fc5fd3       lsr x1, x6, 0x1f
0x00123c78      ce7d099b       mul x14, x14, x9
0x00123c7c      42fc5fd3       lsr x2, x2, 0x1f
0x00123c80      31fe60d3       lsr x17, x17, 0x20
0x00123c84      2100022b       adds w1, w1, w2
0x00123c88      cefd5fd3       lsr x14, x14, 0x1f
0x00123c8c      307c1f13       asr w16, w1, 0x1f
0x00123c90      317e099b       mul x17, x17, x9
0x00123c94      10020152       eor w16, w16, 0x80000000
0x00123c98      0a7d0a9b       mul x10, x8, x10
0x00123c9c      1062811a       csel w16, w16, w1, vs
0x00123ca0      017d059b       mul x1, x8, x5
0x00123ca4      0e020e2b       adds w14, w16, w14
0x00123ca8      31fe5fd3       lsr x17, x17, 0x1f
0x00123cac      21fc6093       asr x1, x1, 0x20
0x00123cb0      d07d1f13       asr w16, w14, 0x1f
0x00123cb4      10020152       eor w16, w16, 0x80000000
0x00123cb8      4afd6093       asr x10, x10, 0x20
0x00123cbc      217c099b       mul x1, x1, x9
0x00123cc0      0e628e1a       csel w14, w16, w14, vs
0x00123cc4      221e0c4e       mov v2.s[1], w17
0x00123cc8      ad7d099b       mul x13, x13, x9
0x00123ccc      30fc5fd3       lsr x16, x1, 0x1f
0x00123cd0      497d099b       mul x9, x10, x9
0x00123cd4      ce01102b       adds w14, w14, w16
0x00123cd8      507d0b9b       mul x16, x10, x11
0x00123cdc      d17d1f13       asr w17, w14, 0x1f
0x00123ce0      adfd5fd3       lsr x13, x13, 0x1f
0x00123ce4      31020152       eor w17, w17, 0x80000000
0x00123ce8      10fe5fd3       lsr x16, x16, 0x1f
0x00123cec      21628e1a       csel w1, w17, w14, vs
0x00123cf0      8e01102b       adds w14, w12, w16
0x00123cf4      d07d1f13       asr w16, w14, 0x1f
0x00123cf8      11408252       mov w17, 0x1200
0x00123cfc      10020152       eor w16, w16, 0x80000000
0x00123d00      b134a672       movk w17, 0x31a5, lsl 16
0x00123d04      0e628e1a       csel w14, w16, w14, vs
0x00123d08      29fd5fd3       lsr x9, x9, 0x1f
0x00123d0c      ce010d2b       adds w14, w14, w13
0x00123d10      087d119b       mul x8, x8, x17
0x00123d14      d07d1f13       asr w16, w14, 0x1f
0x00123d18      2184210f       shrn v1.2s, v1.2d, 0x1f
0x00123d1c      0a020152       eor w10, w16, 0x80000000
0x00123d20      08fd6093       asr x8, x8, 0x20
0x00123d24      4a618e1a       csel w10, w10, w14, vs
0x00123d28      f81300f9       str x24, [sp, 0x20]
0x00123d2c      4a01092b       adds w10, w10, w9
0x00123d30      087d0b9b       mul x8, x8, x11
0x00123d34      e21d144e       mov v2.s[2], w15
0x00123d38      4b7d1f13       asr w11, w10, 0x1f
0x00123d3c      6b010152       eor w11, w11, 0x80000000
0x00123d40      08fd5fd3       lsr x8, x8, 0x1f
0x00123d44      6b618a1a       csel w11, w11, w10, vs
0x00123d48      8801082b       adds w8, w12, w8
0x00123d4c      0a7d1f13       asr w10, w8, 0x1f
0x00123d50      e10f0329       stp w1, w3, [sp, 0x18]
0x00123d54      0184214f       shrn2 v1.4s, v0.2d, 0x1f
0x00123d58      4a010152       eor w10, w10, 0x80000000
0x00123d5c      021c1c4e       mov v2.s[3], w0
0x00123d60      4861881a       csel w8, w10, w8, vs
0x00123d64      08010d2b       adds w8, w8, w13
0x00123d68      0a7d1f13       asr w10, w8, 0x1f
0x00123d6c      4a010152       eor w10, w10, 0x80000000
0x00123d70      400ca14e       sqadd v0.4s, v2.4s, v1.4s
0x00123d74      61c2c43c       ldur q1, [x19, 0x4c]
0x00123d78      4861881a       csel w8, w10, w8, vs
0x00123d7c      0801092b       adds w8, w8, w9
0x00123d80      097d1f13       asr w9, w8, 0x1f
0x00123d84      002ca14e       sqsub v0.4s, v0.4s, v1.4s
0x00123d88      29010152       eor w9, w9, 0x80000000
0x00123d8c      2961881a       csel w9, w9, w8, vs
0x00123d90      e8769952       mov w8, 0xcbb7
0x00123d94      8830a072       movk w8, 0x184, lsl 16
0x00123d98      df02086b       cmp w22, w8
0x00123d9c      e92f0229       stp w9, w11, [sp, 0x10]
0x00123da0      4b010054       b.lt 0x123dc8
0x00123da4      e8db8e52       mov w8, 0x76df
0x00123da8      2813a672       movk w8, 0x3099, lsl 16
0x00123dac      df02086b       cmp w22, w8
0x00123db0      e3010054       b.lo 0x123dec
0x00123db4      a8b79d52       mov w8, 0xedbd
0x00123db8      4826ac72       movk w8, 0x6132, lsl 16                 ; '2a'
0x00123dbc      df02086b       cmp w22, w8
0x00123dc0      48018052       mov w8, 0xa
0x00123dc4      24000014       b 0x123e54
0x00123dc8      c85d8652       mov w8, 0x32ee
0x00123dcc      280ca072       movk w8, 0x61, lsl 16                   ; 'a'
0x00123dd0      df02086b       cmp w22, w8
0x00123dd4      eb010054       b.lt 0x123e10
0x00123dd8      48bb8c52       mov w8, 0x65da
0x00123ddc      4818a072       movk w8, 0xc2, lsl 16
0x00123de0      df02086b       cmp w22, w8
0x00123de4      68008052       mov w8, 3
0x00123de8      1b000014       b 0x123e54
0x00123dec      08b78b52       mov w8, 0x5db8
0x00123df0      c884a172       movk w8, 0xc26, lsl 16                  ; '&\f'
0x00123df4      df02086b       cmp w22, w8
0x00123df8      e3010054       b.lo 0x123e34
0x00123dfc      e86d9752       mov w8, 0xbb6f
0x00123e00      8809a372       movk w8, 0x184c, lsl 16                 ; 'L\x18'
0x00123e04      df02086b       cmp w22, w8
0x00123e08      08018052       mov w8, 8
0x00123e0c      12000014       b 0x123e54
0x00123e10      68978952       mov w8, 0x4cbb
0x00123e14      0803a072       movk w8, 0x18, lsl 16
0x00123e18      df02086b       cmp w22, w8
0x00123e1c      2b3e0054       b.lt 0x1245e0
0x00123e20      c82e9352       mov w8, 0x9976
0x00123e24      0806a072       movk w8, 0x30, lsl 16                   ; '0'
0x00123e28      df02086b       cmp w22, w8
0x00123e2c      28008052       mov w8, 1
0x00123e30      09000014       b 0x123e54
0x00123e34      c8ed9252       mov w8, 0x976e
0x00123e38      2861a072       movk w8, 0x309, lsl 16
0x00123e3c      df02086b       cmp w22, w8
0x00123e40      433d0054       b.lo 0x1245e8
0x00123e44      68db8552       mov w8, 0x2edb
0x00123e48      68c2a072       movk w8, 0x613, lsl 16
0x00123e4c      df02086b       cmp w22, w8
0x00123e50      c8008052       mov w8, 6
0x00123e54      0895881a       cinc w8, w8, hi
0x00123e58      cafaffd0       adrp x10, 0x7d000
0x00123e5c      09050011       add w9, w8, 1
0x00123e60      4ae13191       add x10, x10, 0xc78
0x00123e64      1c00b012       mov w28, 0x7fffffff
0x00123e68      f88361b2       mov x24, -0x80000000
0x00123e6c      1a00a852       mov w26, 0x40000000
0x00123e70      4b59a8b8       ldrsw x11, [x10, w8, uxtw 2]
0x00123e74      0e818052       mov w14, 0x408
0x00123e78      4a59a9b8       ldrsw x10, [x10, w9, uxtw 2]
0x00123e7c      4e20a072       movk w14, 0x102, lsl 16
0x00123e80      1b00e8d2       mov x27, 0x4000000000000000
0x00123e84      990500f0       adrp x25, reloc.Crush::sampBuffer_l     ; 0x1d6000
0x00123e88      00043a4f       sshr v0.4s, v0.4s, 6
0x00123e8c      e00314aa       mov x0, x20
0x00123e90      cc020b4b       sub w12, w22, w11
0x00123e94      8c7d6193       sbfiz x12, x12, 0x1f, 0x20
0x00123e98      4a010bcb       sub x10, x10, x11
0x00123e9c      2b8900f0       adrp x11, 0x124a000
0x00123ea0      8a0dca9a       sdiv x10, x12, x10
0x00123ea4      6b412291       add x11, x11, 0x890
0x00123ea8      0c00b052       mov w12, -0x80000000
0x00123eac      6859e878       ldrsh w8, [x11, w8, uxtw 1]
0x00123eb0      6959e978       ldrsh w9, [x11, w9, uxtw 1]
0x00123eb4      ebff8f52       mov w11, 0x7fff
0x00123eb8      5f011ceb       cmp x10, x28
0x00123ebc      4ab19c9a       csel x10, x10, x28, lt
0x00123ec0      2901084b       sub w9, w9, w8
0x00123ec4      5f0118eb       cmp x10, x24
0x00123ec8      4ac18c1a       csel w10, w10, w12, gt
0x00123ecc      3f010b6b       cmp w9, w11
0x00123ed0      4a7d1013       asr w10, w10, 0x10
0x00123ed4      29b18b1a       csel w9, w9, w11, lt
0x00123ed8      ecff8f12       mov w12, -0x8000
0x00123edc      3f214031       cmn w9, 8, lsl 12
0x00123ee0      4a7d0a1b       mul w10, w10, w10
0x00123ee4      29c18c1a       csel w9, w9, w12, gt
0x00123ee8      4d790f13       sbfx w13, w10, 0xf, 0x10
0x00123eec      5f011a6b       cmp w10, w26
0x00123ef0      6a924139       ldrb w10, [x19, 0x64]
0x00123ef4      6d018d1a       csel w13, w11, w13, eq
0x00123ef8      a97d091b       mul w9, w13, w9
0x00123efc      4d7d0e1b       mul w13, w10, w14
0x00123f00      2e7d0f53       lsr w14, w9, 0xf
0x00123f04      3f011a6b       cmp w9, w26
0x00123f08      69018e1a       csel w9, w11, w14, eq
0x00123f0c      aa114a8b       add x10, x13, x10, lsr 4
0x00123f10      8d384569       ldpsw x13, x14, [x4, 0x28]
0x00123f14      08a1290b       add w8, w8, w9, sxth
0x00123f18      1f010b6b       cmp w8, w11
0x00123f1c      08b18b1a       csel w8, w8, w11, lt
0x00123f20      497d0e9b       mul x9, x10, x14
0x00123f24      1f214031       cmn w8, 8, lsl 12
0x00123f28      6a3a80b9       ldrsw x10, [x19, 0x38]
0x00123f2c      08c18c1a       csel w8, w8, w12, gt
0x00123f30      2bf95f93       sbfx x11, x9, 0x1f, 0x20
0x00123f34      3f011beb       cmp x9, x27
0x00123f38      89038b9a       csel x9, x28, x11, eq
0x00123f3c      8b030d4b       sub w11, w28, w13
0x00123f40      083d1053       lsl w8, w8, 0x10
0x00123f44      390b40f9       ldr x25, [x25, 0x10]
0x00123f48      297d0a9b       mul x9, x9, x10
0x00123f4c      6a7d7f93       sbfiz x10, x11, 1, 0x20
0x00123f50      087d4093       sxtw x8, w8
0x00123f54      e003803d       str q0, [sp]
0x00123f58      2bf95f93       sbfx x11, x9, 0x1f, 0x20
0x00123f5c      3f011beb       cmp x9, x27
0x00123f60      89038b9a       csel x9, x28, x11, eq
0x00123f64      5f011ceb       cmp x10, x28
0x00123f68      4ab19c9a       csel x10, x10, x28, lt
0x00123f6c      abf97fd3       lsl x11, x13, 1
0x00123f70      5f0118eb       cmp x10, x24
0x00123f74      287d089b       mul x8, x9, x8
0x00123f78      49c1989a       csel x9, x10, x24, gt
0x00123f7c      7f011ceb       cmp x11, x28
0x00123f80      6ab19c9a       csel x10, x11, x28, lt
0x00123f84      0bf95f93       sbfx x11, x8, 0x1f, 0x20
0x00123f88      5f0118eb       cmp x10, x24
0x00123f8c      4ac1989a       csel x10, x10, x24, gt
0x00123f90      1f011beb       cmp x8, x27
0x00123f94      88038b9a       csel x8, x28, x11, eq
0x00123f98      4c7d0113       asr w12, w10, 1
0x00123f9c      6392426d       ldp d3, d4, [x19, 0x28]
0x00123fa0      0b7d099b       mul x11, x8, x9
0x00123fa4      297d0113       asr w9, w9, 1
0x00123fa8      0a7d0a9b       mul x10, x8, x10
0x00123fac      6df95f93       sbfx x13, x11, 0x1f, 0x20
0x00123fb0      7f011beb       cmp x11, x27
0x00123fb4      8b038d9a       csel x11, x28, x13, eq
0x00123fb8      4d030c6b       subs w13, w26, w12
0x00123fbc      ae7d1f13       asr w14, w13, 0x1f
0x00123fc0      8c011a0b       add w12, w12, w26
0x00123fc4      ce010152       eor w14, w14, 0x80000000
0x00123fc8      cd618d1a       csel w13, w14, w13, vs
0x00123fcc      5f011beb       cmp x10, x27
0x00123fd0      4af95f93       sbfx x10, x10, 0x1f, 0x20
0x00123fd4      2e011a0b       add w14, w9, w26
0x00123fd8      8a038a9a       csel x10, x28, x10, eq
0x00123fdc      4903096b       subs w9, w26, w9
0x00123fe0      8101271e       fmov s1, w12
0x00123fe4      2c7d1f13       asr w12, w9, 0x1f
0x00123fe8      8c010152       eor w12, w12, 0x80000000
0x00123fec      c201271e       fmov s2, w14
0x00123ff0      8961891a       csel w9, w12, w9, vs
0x00123ff4      a11d0c4e       mov v1.s[1], w13
0x00123ff8      81084129       ldp w1, w2, [x4, 8]
0x00123ffc      221d0c4e       mov v2.s[1], w9
0x00124000      83104229       ldp w3, w4, [x4, 0x10]
0x00124004      21a4202f       ushll v1.2d, v1.2s, 0
0x00124008      42a4202f       ushll v2.2d, v2.2s, 0
0x0012400c      2900669e       fmov x9, d1
0x00124010      2c3c184e       mov x12, v1.d[1]
0x00124014      4d3c184e       mov x13, v2.d[1]
0x00124018      697d099b       mul x9, x11, x9
0x0012401c      4b00669e       fmov x11, d2
0x00124020      4a7d0b9b       mul x10, x10, x11
0x00124024      0b7d0c9b       mul x11, x8, x12
0x00124028      2101679e       fmov d1, x9
0x0012402c      087d0d9b       mul x8, x8, x13
0x00124030      4201679e       fmov d2, x10
0x00124034      611d184e       mov v1.d[1], x11
0x00124038      021d184e       mov v2.d[1], x8
0x0012403c      280340f9       ldr x8, [x25]
0x00124040      2184210f       shrn v1.2s, v1.2d, 0x1f
0x00124044      081d40f9       ldr x8, [x8, 0x38]
0x00124048      4284210f       shrn v2.2s, v2.2d, 0x1f
0x0012404c      212ca30e       sqsub v1.2s, v1.2s, v3.2s
0x00124050      422ca40e       sqsub v2.2s, v2.2s, v4.2s
0x00124054      2804380f       sshr v8.2s, v1.2s, 8
0x00124058      4904380f       sshr v9.2s, v2.2s, 8
0x0012405c      00013fd6       blr x8
0x00124060      280340f9       ldr x8, [x25]
0x00124064      60220091       add x0, x19, 8
0x00124068      e2074329       ldp w2, w1, [sp, 0x18]
0x0012406c      e40f4229       ldp w4, w3, [sp, 0x10]
0x00124070      081d40f9       ldr x8, [x8, 0x38]
0x00124074      00013fd6       blr x8
0x00124078      6392426d       ldp d3, d4, [x19, 0x28]
0x0012407c      00f4006f       fmov v0.2d, 2.00000000
0x00124080      e9031faa       mov x9, xzr
0x00124084      6c2a4029       ldp w12, w10, [x19]
0x00124088      e703c03d       ldr q7, [sp]
0x0012408c      682240b9       ldr w8, [x19, 0x20]
0x00124090      a8c31db8       stur w8, [x29, -0x24]
0x00124094      00010014       b 0x124494
0x00124098      8e0680b9       ldrsw x14, [x20, 4]
0x0012409c      4338810e       zip1 v3.2s, v2.2s, v1.2s
0x001240a0      4578810e       zip2 v5.2s, v2.2s, v1.2s
0x001240a4      d602150b       add w22, w22, w21
0x001240a8      cd7d0d9b       mul x13, x14, x13
0x001240ac      aefd5fd3       lsr x14, x13, 0x1f
0x001240b0      bf011beb       cmp x13, x27
0x001240b4      8d038e1a       csel w13, w28, w14, eq
0x001240b8      ae010d2b       adds w14, w13, w13
0x001240bc      cf7d1f13       asr w15, w14, 0x1f
0x001240c0      ef010152       eor w15, w15, 0x80000000
0x001240c4      ee618e1a       csel w14, w15, w14, vs
0x001240c8      ce010d2b       adds w14, w14, w13
0x001240cc      ad7d4093       sxtw x13, w13
0x001240d0      cf7d1f13       asr w15, w14, 0x1f
0x001240d4      ef010152       eor w15, w15, 0x80000000
0x001240d8      ee618e1a       csel w14, w15, w14, vs
0x001240dc      cf7d2e9b       smull x15, w14, w14
0x001240e0      f0f95f93       sbfx x16, x15, 0x1f, 0x20
0x001240e4      ff011beb       cmp x15, x27
0x001240e8      cf7d4093       sxtw x15, w14
0x001240ec      9003909a       csel x16, x28, x16, eq
0x001240f0      0f7e0f9b       mul x15, x16, x15
0x001240f4      f0fd5fd3       lsr x16, x15, 0x1f
0x001240f8      ff011beb       cmp x15, x27
0x001240fc      8f03901a       csel w15, w28, w16, eq
0x00124100      cf010f6b       subs w15, w14, w15
0x00124104      f07d1f13       asr w16, w15, 0x1f
0x00124108      10020152       eor w16, w16, 0x80000000
0x0012410c      0f628f1a       csel w15, w16, w15, vs
0x00124110      ce058f2b       adds w14, w14, w15, asr 1
0x00124114      71be4969       ldpsw x17, x15, [x19, 0x4c]
0x00124118      d07d1f13       asr w16, w14, 0x1f
0x0012411c      10020152       eor w16, w16, 0x80000000
0x00124120      0e628e1a       csel w14, w16, w14, vs
0x00124124      90030f6b       subs w16, w28, w15
0x00124128      ce7d4093       sxtw x14, w14
0x0012412c      007e1f13       asr w0, w16, 0x1f
0x00124130      00000152       eor w0, w0, 0x80000000
0x00124134      ce7d0f9b       mul x14, x14, x15
0x00124138      1060901a       csel w16, w0, w16, vs
0x0012413c      cffd5fd3       lsr x15, x14, 0x1f
0x00124140      df011beb       cmp x14, x27
0x00124144      ad7d109b       mul x13, x13, x16
0x00124148      8e038f1a       csel w14, w28, w15, eq
0x0012414c      6f0e80b9       ldrsw x15, [x19, 0xc]
0x00124150      adfd5fd3       lsr x13, x13, 0x1f
0x00124154      ad010e2b       adds w13, w13, w14
0x00124158      ae7d1f13       asr w14, w13, 0x1f
0x0012415c      ce010152       eor w14, w14, 0x80000000
0x00124160      cd618d1a       csel w13, w14, w13, vs
0x00124164      ad7d4093       sxtw x13, w13
0x00124168      70ba4a29       ldp w16, w14, [x19, 0x54]
0x0012416c      ad7d119b       mul x13, x13, x17
0x00124170      ce7d4093       sxtw x14, w14
0x00124174      bf011beb       cmp x13, x27
0x00124178      ee7d0e9b       mul x14, x15, x14
0x0012417c      affd5f93       asr x15, x13, 0x1f
0x00124180      8d038f9a       csel x13, x28, x15, eq
0x00124184      bf011ceb       cmp x13, x28
0x00124188      cffd5fd3       lsr x15, x14, 0x1f
0x0012418c      adb19c9a       csel x13, x13, x28, lt
0x00124190      df011beb       cmp x14, x27
0x00124194      8e038f1a       csel w14, w28, w15, eq
0x00124198      0e020e2b       adds w14, w16, w14
0x0012419c      703e80b9       ldrsw x16, [x19, 0x3c]
0x001241a0      cf7d1f13       asr w15, w14, 0x1f
0x001241a4      ef010152       eor w15, w15, 0x80000000
0x001241a8      ee618e1a       csel w14, w15, w14, vs
0x001241ac      2f0340f9       ldr x15, [x25]
0x001241b0      4e078e0b       add w14, w26, w14, asr 1
0x001241b4      ef1540f9       ldr x15, [x15, 0x28]
0x001241b8      d07d109b       mul x16, x14, x16
0x001241bc      10fe5fd3       lsr x16, x16, 0x1f
0x001241c0      ce01102b       adds w14, w14, w16
0x001241c4      f10140a9       ldp x17, x0, [x15]
0x001241c8      d07d1f13       asr w16, w14, 0x1f
0x001241cc      10020152       eor w16, w16, 0x80000000
0x001241d0      0e628e1a       csel w14, w16, w14, vs
0x001241d4      f01140f9       ldr x16, [x15, 0x20]
0x001241d8      e10941a9       ldp x1, x2, [x15, 0x10]
0x001241dc      c37d1913       asr w3, w14, 0x19
0x001241e0      2f421091       add x15, x17, 0x410
0x001241e4      717c7e93       sbfiz x17, x3, 2, 0x20
0x001241e8      00401091       add x0, x0, 0x410
0x001241ec      26120091       add x6, x17, 4
0x001241f0      10421091       add x16, x16, 0x410
0x001241f4      21401091       add x1, x1, 0x410
0x001241f8      ce611a53       ubfiz w14, w14, 6, 0x19
0x001241fc      42401091       add x2, x2, 0x410
0x00124200      e369b1b8       ldrsw x3, [x15, x17]
0x00124204      ef69a6b8       ldrsw x15, [x15, x6]
0x00124208      c4790052       eor w4, w14, 0x7fffffff
0x0012420c      0568b1b8       ldrsw x5, [x0, x17]
0x00124210      2768b1b8       ldrsw x7, [x1, x17]
0x00124214      5e68b1b8       ldrsw x30, [x2, x17]
0x00124218      837c039b       mul x3, x4, x3
0x0012421c      116ab1b8       ldrsw x17, [x16, x17]
0x00124220      cf7d0f9b       mul x15, x14, x15
0x00124224      0068a6b8       ldrsw x0, [x0, x6]
0x00124228      857c059b       mul x5, x4, x5
0x0012422c      2168a6b8       ldrsw x1, [x1, x6]
0x00124230      effd5fd3       lsr x15, x15, 0x1f
0x00124234      4268a6b8       ldrsw x2, [x2, x6]
0x00124238      877c079b       mul x7, x4, x7
0x0012423c      106aa6b8       ldrsw x16, [x16, x6]
0x00124240      de7f049b       mul x30, x30, x4
0x00124244      c07d009b       mul x0, x14, x0
0x00124248      217c0e9b       mul x1, x1, x14
0x0012424c      427c0e9b       mul x2, x2, x14
0x00124250      00fc5fd3       lsr x0, x0, 0x1f
0x00124254      0e7e0e9b       mul x14, x16, x14
0x00124258      70fc5fd3       lsr x16, x3, 0x1f
0x0012425c      0f020f2b       adds w15, w16, w15
0x00124260      a3fc5fd3       lsr x3, x5, 0x1f
0x00124264      e57d1f13       asr w5, w15, 0x1f
0x00124268      317e049b       mul x17, x17, x4
0x0012426c      a5000152       eor w5, w5, 0x80000000
0x00124270      e4fc5fd3       lsr x4, x7, 0x1f
0x00124274      af608f1a       csel w15, w5, w15, vs
0x00124278      6000002b       adds w0, w3, w0
0x0012427c      037c1f13       asr w3, w0, 0x1f
0x00124280      21fc5fd3       lsr x1, x1, 0x1f
0x00124284      63000152       eor w3, w3, 0x80000000
0x00124288      d0ff5fd3       lsr x16, x30, 0x1f
0x0012428c      6060801a       csel w0, w3, w0, vs
0x00124290      8100012b       adds w1, w4, w1
0x00124294      237c1f13       asr w3, w1, 0x1f
0x00124298      42fc5fd3       lsr x2, x2, 0x1f
0x0012429c      63000152       eor w3, w3, 0x80000000
0x001242a0      ef7d4093       sxtw x15, w15
0x001242a4      6160811a       csel w1, w3, w1, vs
0x001242a8      1002022b       adds w16, w16, w2
0x001242ac      027e1f13       asr w2, w16, 0x1f
0x001242b0      31fe5fd3       lsr x17, x17, 0x1f
0x001242b4      cefd5fd3       lsr x14, x14, 0x1f
0x001242b8      42000152       eor w2, w2, 0x80000000
0x001242bc      af7d0f9b       mul x15, x13, x15
0x001242c0      5060901a       csel w16, w2, w16, vs
0x001242c4      2e020e2b       adds w14, w17, w14
0x001242c8      d17d1f13       asr w17, w14, 0x1f
0x001242cc      effd5fd3       lsr x15, x15, 0x1f
0x001242d0      31020152       eor w17, w17, 0x80000000
0x001242d4      2e628e1a       csel w14, w17, w14, vs
0x001242d8      ec010c2b       adds w12, w15, w12
0x001242dc      8f7d1f13       asr w15, w12, 0x1f
0x001242e0      ef010152       eor w15, w15, 0x80000000
0x001242e4      ef618c1a       csel w15, w15, w12, vs
0x001242e8      0c7c4093       sxtw x12, w0
0x001242ec      207c4093       sxtw x0, w1
0x001242f0      f07d309b       smull x16, w15, w16
0x001242f4      e40d040e       dup v4.2s, w15
0x001242f8      ac7d0c9b       mul x12, x13, x12
0x001242fc      11fe5fd3       lsr x17, x16, 0x1f
0x00124300      1f021beb       cmp x16, x27
0x00124304      90fd5fd3       lsr x16, x12, 0x1f
0x00124308      8c03911a       csel w12, w28, w17, eq
0x0012430c      4a01102b       adds w10, w10, w16
0x00124310      ad7d009b       mul x13, x13, x0
0x00124314      83c0a30e       smull v3.2d, v4.2s, v3.2s
0x00124318      517d1f13       asr w17, w10, 0x1f
0x0012431c      84c0a50e       smull v4.2d, v4.2s, v5.2s
0x00124320      31020152       eor w17, w17, 0x80000000
0x00124324      2a628a1a       csel w10, w17, w10, vs
0x00124328      ee7d2e9b       smull x14, w15, w14
0x0012432c      4a010c6b       subs w10, w10, w12
0x00124330      affd5fd3       lsr x15, x13, 0x1f
0x00124334      658ce06e       cmeq v5.2d, v3.2d, v0.2d
0x00124338      6384210f       shrn v3.2s, v3.2d, 0x1f
0x0012433c      868ce06e       cmeq v6.2d, v4.2d, v0.2d
0x00124340      517d1f13       asr w17, w10, 0x1f
0x00124344      8484210f       shrn v4.2s, v4.2d, 0x1f
0x00124348      31020152       eor w17, w17, 0x80000000
0x0012434c      2a628a1a       csel w10, w17, w10, vs
0x00124350      a528a10e       xtn v5.2s, v5.2d
0x00124354      4a01102b       adds w10, w10, w16
0x00124358      c628a10e       xtn v6.2s, v6.2d
0x0012435c      4d7d1f13       asr w13, w10, 0x1f
0x00124360      631c650e       bic v3.8b, v3.8b, v5.8b
0x00124364      0574042f       bic v5.2s, 0x80, lsl 24
0x00124368      841c660e       bic v4.8b, v4.8b, v6.8b
0x0012436c      0674042f       bic v6.2s, 0x80, lsl 24
0x00124370      ad010152       eor w13, w13, 0x80000000
0x00124374      d0fd5fd3       lsr x16, x14, 0x1f
0x00124378      ad618a1a       csel w13, w13, w10, vs
0x0012437c      df011beb       cmp x14, x27
0x00124380      a31ca30e       orr v3.8b, v5.8b, v3.8b
0x00124384      e56a69fc       ldr d5, [x23, x9]
0x00124388      c41ca40e       orr v4.8b, v6.8b, v4.8b
0x0012438c      8e03901a       csel w14, w28, w16, eq
0x00124390      ee010e6b       subs w14, w15, w14
0x00124394      cf7d1f13       asr w15, w14, 0x1f
0x00124398      ef010152       eor w15, w15, 0x80000000
0x0012439c      630ca40e       sqadd v3.2s, v3.2s, v4.2s
0x001243a0      240ca90e       sqadd v4.2s, v1.2s, v9.2s
0x001243a4      a30ca30e       sqadd v3.2s, v5.2s, v3.2s
0x001243a8      e36a29fc       str d3, [x23, x9]
0x001243ac      430ca80e       sqadd v3.2s, v2.2s, v8.2s
0x001243b0      8ac24069       ldpsw x10, x16, [x20, 4]
0x001243b4      910e80b9       ldrsw x17, [x20, 0xc]
0x001243b8      29210091       add x9, x9, 8
0x001243bc      107e0a9b       mul x16, x16, x10
0x001243c0      ea618e1a       csel w10, w15, w14, vs
0x001243c4      0efe5f93       asr x14, x16, 0x1f
0x001243c8      1f021beb       cmp x16, x27
0x001243cc      8e038e9a       csel x14, x28, x14, eq
0x001243d0      df011ceb       cmp x14, x28
0x001243d4      ceb19c9a       csel x14, x14, x28, lt
0x001243d8      cf7d0e9b       mul x15, x14, x14
0x001243dc      eff95f93       sbfx x15, x15, 0x1f, 0x20
0x001243e0      ef7d0e9b       mul x15, x15, x14
0x001243e4      effd5fd3       lsr x15, x15, 0x1f
0x001243e8      8f030f6b       subs w15, w28, w15
0x001243ec      f07d1f13       asr w16, w15, 0x1f
0x001243f0      10020152       eor w16, w16, 0x80000000
0x001243f4      0f628f1a       csel w15, w16, w15, vs
0x001243f8      ef7d119b       mul x15, x15, x17
0x001243fc      effd5fd3       lsr x15, x15, 0x1f
0x00124400      ce010f2b       adds w14, w14, w15
0x00124404      cf7d1f13       asr w15, w14, 0x1f
0x00124408      ef010152       eor w15, w15, 0x80000000
0x0012440c      ee618e1a       csel w14, w15, w14, vs
0x00124410      8e0600b9       str w14, [x20, 4]
0x00124414      6ebe4169       ldpsw x14, x15, [x19, 0xc]
0x00124418      711680b9       ldrsw x17, [x19, 0x14]
0x0012441c      65c2c43c       ldur q5, [x19, 0x4c]
0x00124420      ee7d0e9b       mul x14, x15, x14
0x00124424      a50ca74e       sqadd v5.4s, v5.4s, v7.4s
0x00124428      cffd5f93       asr x15, x14, 0x1f
0x0012442c      df011beb       cmp x14, x27
0x00124430      8e038f9a       csel x14, x28, x15, eq
0x00124434      df011ceb       cmp x14, x28
0x00124438      ceb19c9a       csel x14, x14, x28, lt
0x0012443c      65c2843c       stur q5, [x19, 0x4c]
0x00124440      cf7d0e9b       mul x15, x14, x14
0x00124444      eff95f93       sbfx x15, x15, 0x1f, 0x20
0x00124448      ef7d0e9b       mul x15, x15, x14
0x0012444c      effd5fd3       lsr x15, x15, 0x1f
0x00124450      8f030f6b       subs w15, w28, w15
0x00124454      f07d1f13       asr w16, w15, 0x1f
0x00124458      10020152       eor w16, w16, 0x80000000
0x0012445c      0f628f1a       csel w15, w16, w15, vs
0x00124460      ef7d119b       mul x15, x15, x17
0x00124464      effd5fd3       lsr x15, x15, 0x1f
0x00124468      ce010f2b       adds w14, w14, w15
0x0012446c      cf7d1f13       asr w15, w14, 0x1f
0x00124470      ef010152       eor w15, w15, 0x80000000
0x00124474      ee618e1a       csel w14, w15, w14, vs
0x00124478      ac010c6b       subs w12, w13, w12
0x0012447c      8d7d1f13       asr w13, w12, 0x1f
0x00124480      ad010152       eor w13, w13, 0x80000000
0x00124484      ac618c1a       csel w12, w13, w12, vs
0x00124488      3f010871       cmp w9, 0x200
0x0012448c      6e0e00b9       str w14, [x19, 0xc]
0x00124490      00080054       b.eq 0x124590
0x00124494      6bba4b29       ldp w11, w14, [x19, 0x5c]
0x00124498      8140601e       fmov d1, d4
0x0012449c      6240601e       fmov d2, d3
0x001244a0      0801160b       add w8, w8, w22
0x001244a4      0f010152       eor w15, w8, 0x80000000
0x001244a8      6d7d4093       sxtw x13, w11
0x001244ac      ff01166b       cmp w15, w22
0x001244b0      6ea20b29       stp w14, w8, [x19, 0x5c]
0x001244b4      22dfff54       b.hs 0x124098
0x001244b8      ef7d6193       sbfiz x15, x15, 0x1f, 0x20
0x001244bc      d07e4093       sxtw x16, w22
0x001244c0      ef0dd09a       sdiv x15, x15, x16
0x001244c4      ff011ceb       cmp x15, x28
0x001244c8      efb19c9a       csel x15, x15, x28, lt
0x001244cc      ff0118eb       cmp x15, x24
0x001244d0      efc1989a       csel x15, x15, x24, gt
0x001244d4      f07d0f9b       mul x16, x15, x15
0x001244d8      11fa5f93       sbfx x17, x16, 0x1f, 0x20
0x001244dc      1f021beb       cmp x16, x27
0x001244e0      9003919a       csel x16, x28, x17, eq
0x001244e4      107e0f9b       mul x16, x16, x15
0x001244e8      11fe5fd3       lsr x17, x16, 0x1f
0x001244ec      1f021beb       cmp x16, x27
0x001244f0      9003911a       csel w16, w28, w17, eq
0x001244f4      f17d0113       asr w17, w15, 1
0x001244f8      117e319b       smull x17, w16, w17
0x001244fc      31fe5fd3       lsr x17, x17, 0x1f
0x00124500      1002116b       subs w16, w16, w17
0x00124504      117e1f13       asr w17, w16, 0x1f
0x00124508      31020152       eor w17, w17, 0x80000000
0x0012450c      3062901a       csel w16, w17, w16, vs
0x00124510      1100b052       mov w17, -0x80000000
0x00124514      107e7f93       sbfiz x16, x16, 1, 0x20
0x00124518      1f021ceb       cmp x16, x28
0x0012451c      10b29c9a       csel x16, x16, x28, lt
0x00124520      1f0218eb       cmp x16, x24
0x00124524      10c2911a       csel w16, w16, w17, gt
0x00124528      ce01106b       subs w14, w14, w16
0x0012452c      d07d1f13       asr w16, w14, 0x1f
0x00124530      10020152       eor w16, w16, 0x80000000
0x00124534      0e628e1a       csel w14, w16, w14, vs
0x00124538      8f030f6b       subs w15, w28, w15
0x0012453c      f07d1f13       asr w16, w15, 0x1f
0x00124540      10020152       eor w16, w16, 0x80000000
0x00124544      0f628f1a       csel w15, w16, w15, vs
0x00124548      f07daf9b       umull x16, w15, w15
0x0012454c      10fe5fd3       lsr x16, x16, 0x1f
0x00124550      107e0f9b       mul x16, x16, x15
0x00124554      ef7d0153       lsr w15, w15, 1
0x00124558      10fe5fd3       lsr x16, x16, 0x1f
0x0012455c      0f7e0f9b       mul x15, x16, x15
0x00124560      0f7e4fcb       sub x15, x16, x15, lsr 31
0x00124564      eff97fd3       lsl x15, x15, 1
0x00124568      ff011ceb       cmp x15, x28
0x0012456c      efb19c9a       csel x15, x15, x28, lt
0x00124570      ff0118eb       cmp x15, x24
0x00124574      efc1911a       csel w15, w15, w17, gt
0x00124578      0f010f2b       adds w15, w8, w15
0x0012457c      f07d1f13       asr w16, w15, 0x1f
0x00124580      10020152       eor w16, w16, 0x80000000
0x00124584      0f628f1a       csel w15, w16, w15, vs
0x00124588      6ebe0b29       stp w14, w15, [x19, 0x5c]
0x0012458c      c3feff17       b 0x124098
0x00124590      400ca80e       sqadd v0.2s, v2.2s, v8.2s
0x00124594      210ca90e       sqadd v1.2s, v1.2s, v9.2s
0x00124598      f81340f9       ldr x24, [sp, 0x20]
0x0012459c      682e0429       stp w8, w11, [x19, 0x20]
0x001245a0      6c2a0029       stp w12, w10, [x19]
0x001245a4      601600fd       str d0, [x19, 0x28]
0x001245a8      611a00fd       str d1, [x19, 0x30]
0x001245ac      081740f9       ldr x8, [x24, 0x28]
0x001245b0      a9835ef8       ldur x9, [x29, -0x18]
0x001245b4      1f0109eb       cmp x8, x9
0x001245b8      21020054       b.ne 0x1245fc
0x001245bc      f44f4aa9       ldp x20, x19, [sp, 0xa0]
0x001245c0      f65749a9       ldp x22, x21, [sp, 0x90]
0x001245c4      f85f48a9       ldp x24, x23, [sp, 0x80]
0x001245c8      fa6747a9       ldp x26, x25, [sp, 0x70]
0x001245cc      fc6f46a9       ldp x28, x27, [sp, 0x60]
0x001245d0      fd7b45a9       ldp x29, x30, [sp, 0x50]
0x001245d4      e923446d       ldp d9, d8, [sp, 0x40]
0x001245d8      ffc30291       add sp, sp, 0xb0
0x001245dc      c0035fd6       ret
0x001245e0      e8031f2a       mov w8, wzr
0x001245e4      1dfeff17       b 0x123e58
0x001245e8      a8008052       mov w8, 5
0x001245ec      1bfeff17       b 0x123e58
0x001245f0      08050051       sub w8, w8, 1
0x001245f4      68960139       strb w8, [x19, 0x65]
0x001245f8      edffff17       b 0x1245ac
0x001245fc      498c0294       bl sym.imp.__stack_chk_fail
;-- Saw013a::onNoteOn(int, unsigned char, void*, unsigned int const*):
0x00124600      00e4006f       movi v0.2d, 0000000000000000            ; Saw013a::onNoteOn(int, unsigned char, void*, unsigned int const*)
0x00124604      0888bf52       mov w8, -0x3c00000
0x00124608      493880b9       ldrsw x9, [x2, 0x38]
0x0012460c      0a51000b       add w10, w8, w0, lsl 20
0x00124610      2b008052       mov w11, 1

;; ---- 0x124480 ----
0x00124480      ad010152       eor w13, w13, 0x80000000
0x00124484      ac618c1a       csel w12, w13, w12, vs
0x00124488      3f010871       cmp w9, 0x200
0x0012448c      6e0e00b9       str w14, [x19, 0xc]
0x00124490      00080054       b.eq 0x124590
0x00124494      6bba4b29       ldp w11, w14, [x19, 0x5c]
0x00124498      8140601e       fmov d1, d4
0x0012449c      6240601e       fmov d2, d3
0x001244a0      0801160b       add w8, w8, w22
0x001244a4      0f010152       eor w15, w8, 0x80000000
0x001244a8      6d7d4093       sxtw x13, w11
0x001244ac      ff01166b       cmp w15, w22
0x001244b0      6ea20b29       stp w14, w8, [x19, 0x5c]
0x001244b4      22dfff54       b.hs 0x124098
0x001244b8      ef7d6193       sbfiz x15, x15, 0x1f, 0x20
0x001244bc      d07e4093       sxtw x16, w22
0x001244c0      ef0dd09a       sdiv x15, x15, x16
0x001244c4      ff011ceb       cmp x15, x28
0x001244c8      efb19c9a       csel x15, x15, x28, lt
0x001244cc      ff0118eb       cmp x15, x24
0x001244d0      efc1989a       csel x15, x15, x24, gt
0x001244d4      f07d0f9b       mul x16, x15, x15
0x001244d8      11fa5f93       sbfx x17, x16, 0x1f, 0x20
0x001244dc      1f021beb       cmp x16, x27
0x001244e0      9003919a       csel x16, x28, x17, eq
0x001244e4      107e0f9b       mul x16, x16, x15
0x001244e8      11fe5fd3       lsr x17, x16, 0x1f
0x001244ec      1f021beb       cmp x16, x27
0x001244f0      9003911a       csel w16, w28, w17, eq
0x001244f4      f17d0113       asr w17, w15, 1
0x001244f8      117e319b       smull x17, w16, w17
0x001244fc      31fe5fd3       lsr x17, x17, 0x1f
0x00124500      1002116b       subs w16, w16, w17
0x00124504      117e1f13       asr w17, w16, 0x1f
0x00124508      31020152       eor w17, w17, 0x80000000
0x0012450c      3062901a       csel w16, w17, w16, vs
0x00124510      1100b052       mov w17, -0x80000000
0x00124514      107e7f93       sbfiz x16, x16, 1, 0x20
0x00124518      1f021ceb       cmp x16, x28
0x0012451c      10b29c9a       csel x16, x16, x28, lt
0x00124520      1f0218eb       cmp x16, x24
0x00124524      10c2911a       csel w16, w16, w17, gt
0x00124528      ce01106b       subs w14, w14, w16
0x0012452c      d07d1f13       asr w16, w14, 0x1f
0x00124530      10020152       eor w16, w16, 0x80000000
0x00124534      0e628e1a       csel w14, w16, w14, vs
0x00124538      8f030f6b       subs w15, w28, w15
0x0012453c      f07d1f13       asr w16, w15, 0x1f
0x00124540      10020152       eor w16, w16, 0x80000000
0x00124544      0f628f1a       csel w15, w16, w15, vs
0x00124548      f07daf9b       umull x16, w15, w15
0x0012454c      10fe5fd3       lsr x16, x16, 0x1f
0x00124550      107e0f9b       mul x16, x16, x15
0x00124554      ef7d0153       lsr w15, w15, 1
0x00124558      10fe5fd3       lsr x16, x16, 0x1f
0x0012455c      0f7e0f9b       mul x15, x16, x15
0x00124560      0f7e4fcb       sub x15, x16, x15, lsr 31
0x00124564      eff97fd3       lsl x15, x15, 1
0x00124568      ff011ceb       cmp x15, x28
0x0012456c      efb19c9a       csel x15, x15, x28, lt
0x00124570      ff0118eb       cmp x15, x24
0x00124574      efc1911a       csel w15, w15, w17, gt
0x00124578      0f010f2b       adds w15, w8, w15
0x0012457c      f07d1f13       asr w16, w15, 0x1f
0x00124580      10020152       eor w16, w16, 0x80000000
0x00124584      0f628f1a       csel w15, w16, w15, vs
0x00124588      6ebe0b29       stp w14, w15, [x19, 0x5c]
0x0012458c      c3feff17       b 0x124098
0x00124590      400ca80e       sqadd v0.2s, v2.2s, v8.2s
0x00124594      210ca90e       sqadd v1.2s, v1.2s, v9.2s
0x00124598      f81340f9       ldr x24, [sp, 0x20]
0x0012459c      682e0429       stp w8, w11, [x19, 0x20]
0x001245a0      6c2a0029       stp w12, w10, [x19]
0x001245a4      601600fd       str d0, [x19, 0x28]
0x001245a8      611a00fd       str d1, [x19, 0x30]
0x001245ac      081740f9       ldr x8, [x24, 0x28]
0x001245b0      a9835ef8       ldur x9, [x29, -0x18]
0x001245b4      1f0109eb       cmp x8, x9
0x001245b8      21020054       b.ne 0x1245fc
0x001245bc      f44f4aa9       ldp x20, x19, [sp, 0xa0]
0x001245c0      f65749a9       ldp x22, x21, [sp, 0x90]
0x001245c4      f85f48a9       ldp x24, x23, [sp, 0x80]
0x001245c8      fa6747a9       ldp x26, x25, [sp, 0x70]
0x001245cc      fc6f46a9       ldp x28, x27, [sp, 0x60]
0x001245d0      fd7b45a9       ldp x29, x30, [sp, 0x50]
0x001245d4      e923446d       ldp d9, d8, [sp, 0x40]
0x001245d8      ffc30291       add sp, sp, 0xb0
0x001245dc      c0035fd6       ret
0x001245e0      e8031f2a       mov w8, wzr
0x001245e4      1dfeff17       b 0x123e58
0x001245e8      a8008052       mov w8, 5
0x001245ec      1bfeff17       b 0x123e58
0x001245f0      08050051       sub w8, w8, 1
0x001245f4      68960139       strb w8, [x19, 0x65]
0x001245f8      edffff17       b 0x1245ac
0x001245fc      498c0294       bl sym.imp.__stack_chk_fail
;-- Saw013a::onNoteOn(int, unsigned char, void*, unsigned int const*):
0x00124600      00e4006f       movi v0.2d, 0000000000000000            ; Saw013a::onNoteOn(int, unsigned char, void*, unsigned int const*)
0x00124604      0888bf52       mov w8, -0x3c00000
0x00124608      493880b9       ldrsw x9, [x2, 0x38]
0x0012460c      0a51000b       add w10, w8, w0, lsl 20
0x00124610      2b008052       mov w11, 1
0x00124614      0800b012       mov w8, 0x7fffffff
0x00124618      5f3000f9       str xzr, [x2, 0x60]
0x0012461c      0e608852       mov w14, 0x4300
0x00124620      400000ad       stp q0, q0, [x2]
0x00124624      0eaaba72       movk w14, 0xd550, lsl 16
0x00124628      400001ad       stp q0, q0, [x2, 0x20]
0x0012462c      2f008012       mov w15, -2
0x00124630      49280729       stp w9, w10, [x2, 0x38]
0x00124634      4a0840b9       ldr w10, [x2, 8]
0x00124638      400002ad       stp q0, q0, [x2, 0x40]
0x0012463c      11d08c52       mov w17, 0x6680
0x00124640      481000b9       str w8, [x2, 0x10]
0x00124644      d1acac72       movk w17, 0x6566, lsl 16                ; 'fe'
0x00124648      4aac0229       stp w10, w11, [x2, 0x14]
0x0012464c      04e09652       mov w4, 0xb700
0x00124650      4b700039       strb w11, [x2, 0x1c]
0x00124654      44ecbf72       movk w4, 0xff62, lsl 16
0x00124658      6a2c4069       ldpsw x10, x11, [x3]
0x0012465c      e53f9192       mov x5, -0x8a00
0x00124660      41900139       strb w1, [x2, 0x64]
0x00124664      256db6f2       movk x5, 0xb369, lsl 16
0x00124668      5f940139       strb wzr, [x2, 0x65]
0x0012466c      0c010a6b       subs w12, w8, w10
0x00124670      4e7d0e9b       mul x14, x10, x14
0x00124674      8d7d1f13       asr w13, w12, 0x1f
0x00124678      517d119b       mul x17, x10, x17
0x0012467c      ad010152       eor w13, w13, 0x80000000
0x00124680      cefd6093       asr x14, x14, 0x20
0x00124684      ad618c1a       csel w13, w13, w12, vs
0x00124688      0c010b6b       subs w12, w8, w11
0x0012468c      907d1f13       asr w16, w12, 0x1f
0x00124690      10020152       eor w16, w16, 0x80000000
0x00124694      af7daf9b       umull x15, w13, w15
0x00124698      0c628c1a       csel w12, w16, w12, vs
0x0012469c      10a08152       mov w16, 0xd00
0x001246a0      f07dae72       movk w16, 0x73ef, lsl 16
0x001246a4      effd60d3       lsr x15, x15, 0x20
0x001246a8      ce7d0c9b       mul x14, x14, x12
0x001246ac      b07db09b       umull x16, w13, w16
0x001246b0      ef7d0c9b       mul x15, x15, x12
0x001246b4      cefd5fd3       lsr x14, x14, 0x1f
0x001246b8      10fe60d3       lsr x16, x16, 0x20
0x001246bc      a47da49b       umull x4, w13, w4
0x001246c0      effd5fd3       lsr x15, x15, 0x1f
0x001246c4      ee010e2b       adds w14, w15, w14
0x001246c8      0f7e0b9b       mul x15, x16, x11
0x001246cc      d07d1f13       asr w16, w14, 0x1f
0x001246d0      10020152       eor w16, w16, 0x80000000
0x001246d4      effd5fd3       lsr x15, x15, 0x1f
0x001246d8      0e628e1a       csel w14, w16, w14, vs
0x001246dc      30fe6093       asr x16, x17, 0x20
0x001246e0      ce010f2b       adds w14, w14, w15
0x001246e4      0fc09752       mov w15, 0xbe00
0x001246e8      d17d1f13       asr w17, w14, 0x1f
0x001246ec      107e0b9b       mul x16, x16, x11
0x001246f0      ef79af72       movk w15, 0x7bcf, lsl 16
0x001246f4      31020152       eor w17, w17, 0x80000000
0x001246f8      2e628e1a       csel w14, w17, w14, vs
0x001246fc      10fe5fd3       lsr x16, x16, 0x1f
0x00124700      4f7d0f9b       mul x15, x10, x15
0x00124704      ce01102b       adds w14, w14, w16
0x00124708      90fc60d3       lsr x16, x4, 0x20
0x0012470c      e4ff9792       mov x4, -0xc000
0x00124710      d17d1f13       asr w17, w14, 0x1f
0x00124714      a457b7f2       movk x4, 0xbabd, lsl 16
0x00124718      effd6093       asr x15, x15, 0x20
0x0012471c      31020152       eor w17, w17, 0x80000000
0x00124720      a47d049b       mul x4, x13, x4
0x00124724      2e628e1a       csel w14, w17, w14, vs
0x00124728      517d059b       mul x17, x10, x5
0x0012472c      e5ff8092       mov x5, -0x800
0x00124730      107e0b9b       mul x16, x16, x11
0x00124734      656dbaf2       movk x5, 0xd36b, lsl 16
0x00124738      ef7d0b9b       mul x15, x15, x11
0x0012473c      84fc6093       asr x4, x4, 0x20
0x00124740      31fe6093       asr x17, x17, 0x20
0x00124744      10fe5fd3       lsr x16, x16, 0x1f
0x00124748      effd5fd3       lsr x15, x15, 0x1f
0x0012474c      a57d059b       mul x5, x13, x5
0x00124750      847c0c9b       mul x4, x4, x12
0x00124754      0f020f2b       adds w15, w16, w15
0x00124758      307e0c9b       mul x16, x17, x12
0x0012475c      f17d1f13       asr w17, w15, 0x1f
0x00124760      a5fc6093       asr x5, x5, 0x20
0x00124764      31020152       eor w17, w17, 0x80000000
0x00124768      84fc5fd3       lsr x4, x4, 0x1f
0x0012476c      10fe5fd3       lsr x16, x16, 0x1f
0x00124770      2f628f1a       csel w15, w17, w15, vs
0x00124774      9000102b       adds w16, w4, w16
0x00124778      a47c0b9b       mul x4, x5, x11
0x0012477c      e57f8292       mov x5, -0x1400
0x00124780      117e1f13       asr w17, w16, 0x1f
0x00124784      45e7b9f2       movk x5, 0xcf3a, lsl 16
0x00124788      31020152       eor w17, w17, 0x80000000
0x0012478c      4ebc0929       stp w14, w15, [x2, 0x4c]
0x00124790      3062901a       csel w16, w17, w16, vs
0x00124794      91fc5fd3       lsr x17, x4, 0x1f
0x00124798      447d059b       mul x4, x10, x5
0x0012479c      e57f9892       mov x5, -0xc400
0x001247a0      45e5aef2       movk x5, 0x772a, lsl 16                 ; '*w'
0x001247a4      1002112b       adds w16, w16, w17
0x001247a8      84fc6093       asr x4, x4, 0x20
0x001247ac      f13f9a92       mov x17, -0xd200
0x001247b0      51b6b3f2       movk x17, 0x9db2, lsl 16
0x001247b4      ad7d059b       mul x13, x13, x5
0x001247b8      057e1f13       asr w5, w16, 0x1f
0x001247bc      847c0b9b       mul x4, x4, x11
0x001247c0      a5000152       eor w5, w5, 0x80000000
0x001247c4      517d119b       mul x17, x10, x17
0x001247c8      b060901a       csel w16, w5, w16, vs
0x001247cc      84fc5fd3       lsr x4, x4, 0x1f
0x001247d0      1002042b       adds w16, w16, w4
0x001247d4      31fe6093       asr x17, x17, 0x20
0x001247d8      adfd6093       asr x13, x13, 0x20
0x001247dc      047e1f13       asr w4, w16, 0x1f
0x001247e0      84000152       eor w4, w4, 0x80000000
0x001247e4      317e0c9b       mul x17, x17, x12
0x001247e8      ac7d0c9b       mul x12, x13, x12
0x001247ec      9060901a       csel w16, w4, w16, vs
0x001247f0      e4bf8c92       mov x4, -0x6600
0x001247f4      31fe5fd3       lsr x17, x17, 0x1f
0x001247f8      e4e9b9f2       movk x4, 0xcf4f, lsl 16
0x001247fc      8cfd5fd3       lsr x12, x12, 0x1f
0x00124800      8c01112b       adds w12, w12, w17
0x00124804      ad7d0b9b       mul x13, x13, x11
0x00124808      4a7d049b       mul x10, x10, x4
0x0012480c      917d1f13       asr w17, w12, 0x1f
0x00124810      31020152       eor w17, w17, 0x80000000
0x00124814      adfd5fd3       lsr x13, x13, 0x1f
0x00124818      4afd6093       asr x10, x10, 0x20
0x0012481c      2c628c1a       csel w12, w17, w12, vs
0x00124820      8c010d2b       adds w12, w12, w13
0x00124824      2e8900d0       adrp x14, 0x124a000
0x00124828      4a7d0b9b       mul x10, x10, x11
0x0012482c      6b559552       mov w11, 0xaaab
0x00124830      8d7d1f13       asr w13, w12, 0x1f
0x00124834      4b55a572       movk w11, 0x2aaa, lsl 16
0x00124838      ad010152       eor w13, w13, 0x80000000
0x0012483c      4afd5fd3       lsr x10, x10, 0x1f
0x00124840      ac618c1a       csel w12, w13, w12, vs
0x00124844      0d7c2b9b       smull x13, w0, w11
0x00124848      8a010a2b       adds w10, w12, w10
0x0012484c      ce412291       add x14, x14, 0x890
0x00124850      b1fd60d3       lsr x17, x13, 0x20
0x00124854      4c7d1f13       asr w12, w10, 0x1f
0x00124858      adfd7fd3       lsr x13, x13, 0x3f
0x0012485c      8c010152       eor w12, w12, 0x80000000
0x00124860      ad05910b       add w13, w13, w17, asr 1
0x00124864      91018052       mov w17, 0xc
0x00124868      8a618a1a       csel w10, w12, w10, vs
0x0012486c      ac81111b       msub w12, w13, w17, w0
0x00124870      50a80a29       stp w16, w10, [x2, 0x54]
0x00124874      8a411153       lsl w10, w12, 0xf
0x00124878      4a010c4b       sub w10, w10, w12
0x0012487c      ccc52d8b       add x12, x14, w13, sxtw 1
0x00124880      eeff8f12       mov w14, -0x8000
0x00124884      10818052       mov w16, 0x408
0x00124888      4a7d2b9b       smull x10, w10, w11
0x0012488c      5020a072       movk w16, 0x102, lsl 16

;; ---- 0x124864 ----
0x00124864      91018052       mov w17, 0xc
0x00124868      8a618a1a       csel w10, w12, w10, vs
0x0012486c      ac81111b       msub w12, w13, w17, w0
0x00124870      50a80a29       stp w16, w10, [x2, 0x54]
