// ==== Saw013a::initModule @ 002238c4 (32 bytes)

/* Saw013a::initModule(unsigned int, ModuleCallbackInterface const*, unsigned int*) */

bool Saw013a::initModule(uint param_1,ModuleCallbackInterface *param_2,uint *param_3)

{
  if (param_1 == 0) {
    *(ModuleCallbackInterface **)PTR_interface_002d6010 = param_2;
    *param_3 = 0;
  }
  return param_1 == 0;
}



// ==== Saw013a::init @ 002238e4 (176 bytes)

/* Saw013a::init(void*, unsigned int, unsigned int, void*, void*) */

void Saw013a::init(void *param_1,uint param_2,uint param_3,void *param_4,void *param_5)

{
  uint uVar1;
  uint uVar2;
  long lVar3;
  int iVar4;
  long lVar5;
  
  *(undefined8 *)((long)param_1 + 0x60) = 0;
  *(undefined8 *)((long)param_1 + 0x48) = 0;
  *(undefined8 *)((long)param_1 + 0x40) = 0;
  *(undefined8 *)((long)param_1 + 0x58) = 0;
  *(undefined8 *)((long)param_1 + 0x50) = 0;
  *(undefined8 *)((long)param_1 + 0x28) = 0;
  *(undefined8 *)((long)param_1 + 0x20) = 0;
  *(undefined8 *)((long)param_1 + 0x38) = 0;
  *(undefined8 *)((long)param_1 + 0x30) = 0;
  *(undefined8 *)((long)param_1 + 8) = 0;
  *(undefined8 *)param_1 = 0;
  *(undefined8 *)((long)param_1 + 0x18) = 0;
  *(undefined8 *)((long)param_1 + 0x10) = 0;
  switch(param_2) {
  case 4:
    lVar5 = -0x13333340;
    lVar3 = (long)DAT_0134a5d0;
    break;
  case 5:
    *(undefined4 *)((long)param_1 + 0x38) = DAT_0134a5d4;
    return;
  case 6:
    lVar5 = -0x199999a0;
    lVar3 = (long)DAT_0134a5d8;
    break;
  case 7:
    lVar5 = -0xcccccd0;
    lVar3 = (long)DAT_0134a5dc;
    break;
  default:
    *(undefined4 *)((long)param_1 + 0x38) = DAT_0134a5cc;
    return;
  }
  iVar4 = (int)((ulong)(lVar3 * lVar5) >> 0x1f);
  uVar1 = (int)lVar3 + iVar4;
  uVar2 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4((int)lVar3,iVar4)) {
    uVar2 = uVar1;
  }
  *(uint *)((long)param_1 + 0x38) = uVar2;
  return;
}



// ==== Saw013a::render @ 00223994 (3180 bytes)

/* Saw013a::render(fract32_t*, unsigned int, int, void*, unsigned int const*, ADSR*) */

void Saw013a::render(fract32_t *param_1,uint param_2,int param_3,void *param_4,uint *param_5,
                    ADSR *param_6)

{
  uint uVar1;
  short sVar2;
  uint uVar3;
  uint uVar4;
  uint uVar5;
  uint uVar6;
  uint uVar7;
  long lVar8;
  undefined1 auVar9 [16];
  undefined *puVar10;
  bool bVar11;
  bool bVar12;
  int iVar13;
  int iVar14;
  long lVar15;
  int iVar16;
  uint uVar17;
  long lVar18;
  long lVar19;
  int iVar20;
  uint uVar21;
  long lVar22;
  ulong uVar23;
  uint uVar24;
  ulong uVar25;
  ulong uVar26;
  ulong uVar27;
  int iVar28;
  long *plVar29;
  undefined1 auVar30 [16];
  undefined1 auVar31 [16];
  undefined8 uVar32;
  undefined8 uVar33;
  undefined8 uVar34;
  undefined8 uVar35;
  ulong uVar36;
  long lVar38;
  undefined1 auVar37 [16];
  ulong uVar39;
  int iVar40;
  undefined8 uVar41;
  undefined8 uVar42;
  
  puVar10 = PTR_interface_002d6010;
  lVar8 = tpidr_el0;
  lVar18 = *(long *)(lVar8 + 0x28);
  if (*(int *)(param_6 + 0x10) == 0) goto LAB_002245ac;
  if (*(char *)((long)param_4 + 0x65) != '\0') {
    *(char *)((long)param_4 + 0x65) = *(char *)((long)param_4 + 0x65) + -1;
    goto LAB_002245ac;
  }
  uVar21 = *param_5;
  lVar19 = (long)(int)uVar21;
  uVar24 = param_5[1];
  lVar22 = (long)(int)uVar24;
  uVar17 = (int)(0x7fffffff - uVar21) >> 0x1f ^ 0x80000000;
  if (!SBORROW4(0x7fffffff,uVar21)) {
    uVar17 = 0x7fffffff - uVar21;
  }
  uVar26 = (ulong)uVar17;
  uVar17 = (int)(0x7fffffff - uVar24) >> 0x1f ^ 0x80000000;
  if (!SBORROW4(0x7fffffff,uVar24)) {
    uVar17 = 0x7fffffff - uVar24;
  }
  uVar23 = (ulong)uVar17;
  uVar25 = uVar26 * 0xfffffffe >> 0x20;
  iVar13 = (int)((lVar19 * 0xd5504300 >> 0x20) * uVar23 >> 0x1f);
  iVar20 = (int)(uVar25 * uVar23 >> 0x1f);
  uVar17 = iVar20 + iVar13;
  uVar21 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar20,iVar13)) {
    uVar21 = uVar17;
  }
  iVar13 = (int)((uVar26 * 0x73ef0d00 >> 0x20) * lVar22 >> 0x1f);
  uVar17 = uVar21 + iVar13;
  uVar24 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar21,iVar13)) {
    uVar24 = uVar17;
  }
  iVar13 = (int)((lVar19 * -0x4c968a00 >> 0x20) * uVar23 >> 0x1f);
  iVar14 = (int)(((long)(uVar26 * -0x4542c000) >> 0x20) * uVar23 >> 0x1f);
  uVar17 = iVar14 + iVar13;
  uVar21 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar14,iVar13)) {
    uVar21 = uVar17;
  }
  iVar13 = (int)((ulong)(((long)(uVar26 * -0x2c940800) >> 0x20) * lVar22) >> 0x1f);
  uVar17 = uVar21 + iVar13;
  lVar15 = (long)(uVar26 * -0x88d5c400) >> 0x20;
  uVar6 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar21,iVar13)) {
    uVar6 = uVar17;
  }
  iVar14 = (int)((lVar19 * -0x624dd200 >> 0x20) * uVar23 >> 0x1f);
  iVar13 = (int)(lVar15 * uVar23 >> 0x1f);
  uVar17 = iVar13 + iVar14;
  uVar21 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar13,iVar14)) {
    uVar21 = uVar17;
  }
  iVar13 = (int)((ulong)(lVar15 * lVar22) >> 0x1f);
  uVar17 = uVar21 + iVar13;
  uVar7 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar21,iVar13)) {
    uVar7 = uVar17;
  }
  iVar14 = (int)((lVar19 * 0x68d44900 >> 0x20) * uVar23 >> 0x1f);
  iVar13 = (int)((uVar26 * 0x3eb70f40 >> 0x20) * uVar23 >> 0x1f);
  uVar17 = iVar13 + iVar14;
  uVar21 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar13,iVar14)) {
    uVar21 = uVar17;
  }
  iVar13 = (int)((uVar26 * 0x38f07e40 >> 0x20) * lVar22 >> 0x1f);
  uVar17 = uVar21 + iVar13;
  uVar1 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar21,iVar13)) {
    uVar1 = uVar17;
  }
  uVar27 = uVar26 * 0x28760540 >> 0x20;
  iVar13 = (int)((ulong)((lVar19 * 0x607f9180 >> 0x20) * lVar22) >> 0x1f);
  uVar17 = uVar1 + iVar13;
  uVar21 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar1,iVar13)) {
    uVar21 = uVar17;
  }
  iVar14 = (int)((lVar19 * 0x39583880 >> 0x20) * uVar23 >> 0x1f);
  iVar13 = (int)(uVar27 * uVar23 >> 0x1f);
  uVar17 = iVar13 + iVar14;
  uVar1 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar13,iVar14)) {
    uVar1 = uVar17;
  }
  iVar13 = (int)(uVar27 * lVar22 >> 0x1f);
  uVar17 = uVar1 + iVar13;
  lVar15 = lVar19 * 0xfffffffe >> 0x20;
  uVar3 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar1,iVar13)) {
    uVar3 = uVar17;
  }
  iVar13 = (int)((ulong)((lVar19 * 0x28760540 >> 0x20) * lVar22) >> 0x1f);
  uVar17 = uVar3 + iVar13;
  uVar1 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar3,iVar13)) {
    uVar1 = uVar17;
  }
  iVar13 = (int)(lVar15 * uVar23 >> 0x1f);
  uVar17 = iVar20 + iVar13;
  uVar3 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar20,iVar13)) {
    uVar3 = uVar17;
  }
  iVar13 = (int)(uVar25 * lVar22 >> 0x1f);
  uVar17 = (int)(uVar3 + iVar13) >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar3,iVar13)) {
    uVar17 = uVar3 + iVar13;
  }
  iVar14 = (int)((ulong)(lVar15 * lVar22) >> 0x1f);
  uVar3 = (int)(uVar17 + iVar14) >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar17,iVar14)) {
    uVar3 = uVar17 + iVar14;
  }
  iVar16 = (int)((lVar19 * 0x31a51200 >> 0x20) * uVar23 >> 0x1f);
  uVar17 = iVar20 + iVar16;
  auVar30._12_4_ = (int)((ulong)((lVar19 * -0x30b06600 >> 0x20) * lVar22) >> 0x1f);
  auVar30._8_4_ = (int)((ulong)((lVar19 * -0x30c51400 >> 0x20) * lVar22) >> 0x1f);
  uVar4 = (int)uVar17 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar20,iVar16)) {
    uVar4 = uVar17;
  }
  auVar30._4_4_ = (int)((ulong)((lVar19 * 0x7bcfbe00 >> 0x20) * lVar22) >> 0x1f);
  auVar30._0_4_ = (int)((ulong)((lVar19 * 0x65666680 >> 0x20) * lVar22) >> 0x1f);
  auVar37._4_4_ = (int)((uVar26 * 0xff62b700 >> 0x20) * lVar22 >> 0x1f);
  auVar37._0_4_ = uVar24;
  auVar37._8_4_ = uVar6;
  auVar37._12_4_ = uVar7;
  auVar30 = NEON_sqadd(auVar37,auVar30,4);
  uVar17 = (int)(uVar4 + iVar13) >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar4,iVar13)) {
    uVar17 = uVar4 + iVar13;
  }
  auVar30 = NEON_sqsub(auVar30,*(undefined1 (*) [16])((long)param_4 + 0x4c),4);
  uVar24 = (int)(uVar17 + iVar14) >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar17,iVar14)) {
    uVar24 = uVar17 + iVar14;
  }
  if ((int)param_2 < 0x184cbb7) {
    if (0x6132ed < (int)param_2) {
      bVar11 = 0xc265d9 < param_2;
      bVar12 = param_2 == 0xc265da;
      uVar17 = 3;
      goto LAB_00223e54;
    }
    if (0x184cba < (int)param_2) {
      bVar11 = 0x309975 < param_2;
      bVar12 = param_2 == 0x309976;
      uVar17 = 1;
      goto LAB_00223e54;
    }
    uVar17 = 0;
  }
  else {
    if (param_2 < 0x309976df) {
      if (param_2 < 0xc265db8) {
        if (param_2 < 0x309976e) {
          uVar17 = 5;
          goto LAB_00223e58;
        }
        bVar11 = 0x6132eda < param_2;
        bVar12 = param_2 == 0x6132edb;
        uVar17 = 6;
      }
      else {
        bVar11 = 0x184cbb6e < param_2;
        bVar12 = param_2 == 0x184cbb6f;
        uVar17 = 8;
      }
    }
    else {
      bVar11 = 0x6132edbc < param_2;
      bVar12 = param_2 == 0x6132edbd;
      uVar17 = 10;
    }
LAB_00223e54:
    if (bVar11 && !bVar12) {
      uVar17 = uVar17 + 1;
    }
  }
LAB_00223e58:
  auVar31._0_8_ = CONCAT44(auVar30._4_4_ >> 6,auVar30._0_4_ >> 6);
  auVar31._8_4_ = auVar30._8_4_ >> 6;
  auVar31._12_4_ = auVar30._12_4_ >> 6;
  uVar6 = param_2 - (&DAT_0017dc78)[uVar17];
  lVar22 = (long)(int)(&DAT_0017dc78)[uVar17 + 1] - (long)(int)(&DAT_0017dc78)[uVar17];
  lVar19 = 0;
  if (lVar22 != 0) {
    lVar19 = (long)(-(ulong)(uVar6 >> 0x1f) & 0x8000000000000000 | (ulong)uVar6 << 0x1f) / lVar22;
  }
  if (0x7ffffffe < lVar19) {
    lVar19 = 0x7fffffff;
  }
  iVar13 = (int)*(short *)((long)&DAT_0134a890 + (ulong)uVar17 * 2);
  iVar14 = *(short *)((long)&DAT_0134a890 + (ulong)(uVar17 + 1) * 2) - iVar13;
  iVar20 = (int)lVar19;
  if (lVar19 < -0x7fffffff) {
    iVar20 = -0x80000000;
  }
  if (0x7ffe < iVar14) {
    iVar14 = 0x7fff;
  }
  iVar20 = (iVar20 >> 0x10) * (iVar20 >> 0x10);
  if (iVar14 < -0x7fff) {
    iVar14 = -0x8000;
  }
  iVar16 = 0x7fff;
  if (iVar20 != 0x40000000) {
    iVar16 = iVar20 * 2 >> 0x10;
  }
  sVar2 = 0x7fff;
  if (iVar16 * iVar14 != 0x40000000) {
    sVar2 = (short)((uint)(iVar16 * iVar14) >> 0xf);
  }
  iVar13 = iVar13 + sVar2;
  if (0x7ffe < iVar13) {
    iVar13 = 0x7fff;
  }
  lVar19 = ((ulong)((uint)*(byte *)((long)param_4 + 100) * 0x1020408) +
           (ulong)(*(byte *)((long)param_4 + 100) >> 4)) * (long)(int)param_5[0xb];
  if (iVar13 < -0x7fff) {
    iVar13 = -0x8000;
  }
  lVar22 = 0x7fffffff;
  if (lVar19 != 0x4000000000000000) {
    lVar22 = lVar19 * 2 >> 0x20;
  }
  uVar17 = 0x7fffffff - param_5[10];
  lVar22 = lVar22 * *(int *)((long)param_4 + 0x38);
  uVar26 = -(ulong)(uVar17 >> 0x1f) & 0xfffffffe00000000 | (ulong)uVar17 << 1;
  lVar19 = 0x7fffffff;
  if (lVar22 != 0x4000000000000000) {
    lVar19 = lVar22 * 2 >> 0x20;
  }
  if (0x7ffffffe < (long)uVar26) {
    uVar26 = 0x7fffffff;
  }
  lVar22 = (long)(int)param_5[10] * 2;
  lVar19 = lVar19 * (iVar13 << 0x10);
  if ((long)uVar26 < -0x7fffffff) {
    uVar26 = 0xffffffff80000000;
  }
  if (0x7ffffffe < lVar22) {
    lVar22 = 0x7fffffff;
  }
  if (lVar22 < -0x7fffffff) {
    lVar22 = -0x80000000;
  }
  lVar15 = 0x7fffffff;
  if (lVar19 != 0x4000000000000000) {
    lVar15 = lVar19 * 2 >> 0x20;
  }
  iVar13 = (int)lVar22 >> 1;
  iVar20 = (int)uVar26 >> 1;
  lVar19 = 0x7fffffff;
  if (lVar15 * uVar26 != 0x4000000000000000) {
    lVar19 = (long)(lVar15 * uVar26 * 2) >> 0x20;
  }
  uVar17 = (int)(0x40000000U - iVar13) >> 0x1f ^ 0x80000000;
  if (!SBORROW4(0x40000000,iVar13)) {
    uVar17 = 0x40000000U - iVar13;
  }
  lVar38 = 0x7fffffff;
  if (lVar15 * lVar22 != 0x4000000000000000) {
    lVar38 = lVar15 * lVar22 * 2 >> 0x20;
  }
  uVar6 = (int)(0x40000000U - iVar20) >> 0x1f ^ 0x80000000;
  if (!SBORROW4(0x40000000,iVar20)) {
    uVar6 = 0x40000000U - iVar20;
  }
  uVar32 = NEON_sqsub(CONCAT44((int)(lVar15 * (ulong)uVar17 >> 0x1f),
                               (int)(lVar19 * (ulong)(iVar13 + 0x40000000) >> 0x1f)),
                      *(undefined8 *)((long)param_4 + 0x28),4);
  uVar34 = NEON_sqsub(CONCAT44((int)(lVar15 * (ulong)uVar6 >> 0x1f),
                               (int)(lVar38 * (ulong)(iVar20 + 0x40000000) >> 0x1f)),
                      *(undefined8 *)((long)param_4 + 0x30),4);
  uVar41 = CONCAT44((int)((long)uVar32 >> 0x28),(int)uVar32 >> 8);
  uVar42 = CONCAT44((int)((long)uVar34 >> 0x28),(int)uVar34 >> 8);
  (**(code **)(*(long *)PTR_interface_002d6010 + 0x38))
            (param_6,param_5[2],param_5[3],param_5[4],param_5[5]);
  (**(code **)(*(long *)puVar10 + 0x38))((long)param_4 + 8,uVar21,uVar1,uVar3,uVar24);
  auVar30 = NEON_fmov(0x4000000000000000,8);
  lVar19 = 0;
  uVar24 = *(uint *)param_4;
  uVar21 = *(uint *)((long)param_4 + 4);
  auVar9._8_8_ = auVar31._8_8_;
  auVar9._0_8_ = auVar31._0_8_;
  uVar17 = *(uint *)((long)param_4 + 0x20);
  uVar32 = *(undefined8 *)((long)param_4 + 0x28);
  uVar34 = *(undefined8 *)((long)param_4 + 0x30);
  do {
    uVar35 = uVar34;
    uVar33 = uVar32;
    iVar20 = *(int *)((long)param_4 + 0x5c);
    iVar14 = *(int *)((long)param_4 + 0x60);
    uVar17 = uVar17 + param_2;
    uVar6 = uVar17 ^ 0x80000000;
    *(int *)((long)param_4 + 0x5c) = iVar14;
    *(uint *)((long)param_4 + 0x60) = uVar17;
    iVar13 = 0x7fffffff;
    if (uVar6 < param_2) {
      lVar22 = 0;
      if ((long)(int)param_2 != 0) {
        lVar22 = (long)(-(ulong)(uVar6 >> 0x1f) & 0x8000000000000000 | (ulong)uVar6 << 0x1f) /
                 (long)(int)param_2;
      }
      if (0x7ffffffe < lVar22) {
        lVar22 = 0x7fffffff;
      }
      if (lVar22 < -0x7fffffff) {
        lVar22 = -0x80000000;
      }
      lVar15 = 0x7fffffff;
      if (lVar22 * lVar22 != 0x4000000000000000) {
        lVar15 = lVar22 * lVar22 * 2 >> 0x20;
      }
      iVar16 = 0x7fffffff;
      if (lVar15 * lVar22 != 0x4000000000000000) {
        iVar16 = (int)((ulong)(lVar15 * lVar22) >> 0x1f);
      }
      iVar28 = (int)lVar22;
      iVar40 = (int)((ulong)((long)iVar16 * (long)(iVar28 >> 1)) >> 0x1f);
      uVar7 = iVar16 - iVar40;
      uVar6 = (int)uVar7 >> 0x1f ^ 0x80000000;
      if (!SBORROW4(iVar16,iVar40)) {
        uVar6 = uVar7;
      }
      uVar26 = -(ulong)(uVar6 >> 0x1f) & 0xfffffffe00000000 | (ulong)uVar6 << 1;
      if (0x7ffffffe < (long)uVar26) {
        uVar26 = 0x7fffffff;
      }
      iVar16 = (int)uVar26;
      if ((long)uVar26 < -0x7fffffff) {
        iVar16 = -0x80000000;
      }
      uVar6 = iVar14 - iVar16 >> 0x1f ^ 0x80000000;
      if (!SBORROW4(iVar14,iVar16)) {
        uVar6 = iVar14 - iVar16;
      }
      uVar7 = (int)(0x7fffffffU - iVar28) >> 0x1f ^ 0x80000000;
      if (!SBORROW4(0x7fffffff,iVar28)) {
        uVar7 = 0x7fffffffU - iVar28;
      }
      uVar26 = (ulong)uVar7;
      uVar26 = (uVar26 * uVar26 >> 0x1f) * uVar26 >> 0x1f;
      lVar22 = (uVar26 - (uVar26 * (uVar7 >> 1) >> 0x1f)) * 2;
      if (0x7ffffffe < lVar22) {
        lVar22 = 0x7fffffff;
      }
      iVar14 = (int)lVar22;
      if (lVar22 < -0x7fffffff) {
        iVar14 = -0x80000000;
      }
      uVar7 = (int)(uVar17 + iVar14) >> 0x1f ^ 0x80000000;
      if (!SCARRY4(uVar17,iVar14)) {
        uVar7 = uVar17 + iVar14;
      }
      *(uint *)((long)param_4 + 0x5c) = uVar6;
      *(uint *)((long)param_4 + 0x60) = uVar7;
    }
    param_2 = param_2 + param_3;
    uVar26 = (long)*(int *)(param_6 + 4) * (long)iVar20;
    iVar14 = iVar13;
    if (uVar26 != 0x4000000000000000) {
      iVar14 = (int)(uVar26 >> 0x1f);
    }
    uVar6 = iVar14 * 2 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(iVar14,iVar14)) {
      uVar6 = iVar14 * 2;
    }
    uVar7 = (int)(uVar6 + iVar14) >> 0x1f ^ 0x80000000;
    if (!SCARRY4(uVar6,iVar14)) {
      uVar7 = uVar6 + iVar14;
    }
    lVar22 = 0x7fffffff;
    if ((long)(int)uVar7 * (long)(int)uVar7 != 0x4000000000000000) {
      lVar22 = (long)(int)uVar7 * (long)(int)uVar7 * 2 >> 0x20;
    }
    if (lVar22 * (int)uVar7 != 0x4000000000000000) {
      iVar13 = (int)((ulong)(lVar22 * (int)uVar7) >> 0x1f);
    }
    uVar6 = (int)(uVar7 - iVar13) >> 0x1f ^ 0x80000000;
    if (!SBORROW4(uVar7,iVar13)) {
      uVar6 = uVar7 - iVar13;
    }
    uVar1 = uVar7 + ((int)uVar6 >> 1);
    iVar13 = *(int *)((long)param_4 + 0x50);
    uVar3 = (int)uVar1 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(uVar7,(int)uVar6 >> 1)) {
      uVar3 = uVar1;
    }
    iVar16 = 0x7fffffff;
    uVar6 = (int)(0x7fffffffU - iVar13) >> 0x1f ^ 0x80000000;
    if (!SBORROW4(0x7fffffff,iVar13)) {
      uVar6 = 0x7fffffffU - iVar13;
    }
    iVar28 = iVar16;
    if ((long)(int)uVar3 * (long)iVar13 != 0x4000000000000000) {
      iVar28 = (int)((ulong)((long)(int)uVar3 * (long)iVar13) >> 0x1f);
    }
    iVar13 = (int)((long)iVar14 * (ulong)uVar6 >> 0x1f);
    uVar6 = iVar13 + iVar28;
    uVar7 = (int)uVar6 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(iVar13,iVar28)) {
      uVar7 = uVar6;
    }
    lVar15 = (long)(int)uVar7 * (long)*(int *)((long)param_4 + 0x4c);
    uVar26 = (long)*(int *)((long)param_4 + 0xc) * (long)*(int *)((long)param_4 + 0x58);
    lVar22 = 0x7fffffff;
    if (lVar15 != 0x4000000000000000) {
      lVar22 = lVar15 >> 0x1f;
    }
    if (0x7ffffffe < lVar22) {
      lVar22 = 0x7fffffff;
    }
    iVar13 = iVar16;
    if (uVar26 != 0x4000000000000000) {
      iVar13 = (int)(uVar26 >> 0x1f);
    }
    uVar6 = *(int *)((long)param_4 + 0x54) + iVar13;
    uVar7 = (int)uVar6 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(*(int *)((long)param_4 + 0x54),iVar13)) {
      uVar7 = uVar6;
    }
    uVar6 = ((int)uVar7 >> 1) + 0x40000000;
    plVar29 = *(long **)(*(long *)puVar10 + 0x28);
    iVar13 = (int)((ulong)uVar6 * (long)*(int *)((long)param_4 + 0x3c) >> 0x1f);
    uVar7 = uVar6 + iVar13;
    uVar1 = (int)uVar7 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(uVar6,iVar13)) {
      uVar1 = uVar7;
    }
    uVar25 = -(ulong)((uint)((int)uVar1 >> 0x19) >> 0x1f) & 0xfffffffc00000000 |
             (ulong)(uint)((int)uVar1 >> 0x19) << 2;
    lVar15 = uVar25 + 4;
    uVar6 = (uVar1 & 0x1ffffff) << 6;
    uVar23 = (ulong)uVar6;
    uVar26 = (ulong)(uVar6 ^ 0x7fffffff);
    iVar13 = (int)(uVar23 * (long)*(int *)(*plVar29 + 0x410 + lVar15) >> 0x1f);
    iVar14 = (int)(uVar26 * (long)*(int *)(*plVar29 + 0x410 + uVar25) >> 0x1f);
    uVar6 = iVar14 + iVar13;
    uVar7 = (int)uVar6 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(iVar14,iVar13)) {
      uVar7 = uVar6;
    }
    iVar13 = (int)(uVar23 * (long)*(int *)(plVar29[1] + 0x410 + lVar15) >> 0x1f);
    iVar14 = (int)(uVar26 * (long)*(int *)(plVar29[1] + 0x410 + uVar25) >> 0x1f);
    uVar6 = iVar14 + iVar13;
    uVar1 = (int)uVar6 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(iVar14,iVar13)) {
      uVar1 = uVar6;
    }
    iVar13 = (int)((long)*(int *)(plVar29[2] + 0x410 + lVar15) * uVar23 >> 0x1f);
    iVar14 = (int)(uVar26 * (long)*(int *)(plVar29[2] + 0x410 + uVar25) >> 0x1f);
    uVar6 = iVar14 + iVar13;
    uVar3 = (int)uVar6 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(iVar14,iVar13)) {
      uVar3 = uVar6;
    }
    iVar13 = (int)((long)*(int *)(plVar29[3] + 0x410 + lVar15) * uVar23 >> 0x1f);
    iVar14 = (int)((long)*(int *)(plVar29[3] + 0x410 + uVar25) * uVar26 >> 0x1f);
    uVar6 = iVar14 + iVar13;
    uVar4 = (int)uVar6 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(iVar14,iVar13)) {
      uVar4 = uVar6;
    }
    iVar13 = (int)((long)*(int *)(plVar29[4] + 0x410 + lVar15) * uVar23 >> 0x1f);
    iVar14 = (int)((long)*(int *)(plVar29[4] + 0x410 + uVar25) * uVar26 >> 0x1f);
    uVar6 = iVar14 + iVar13;
    uVar5 = (int)uVar6 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(iVar14,iVar13)) {
      uVar5 = uVar6;
    }
    iVar13 = (int)((ulong)(lVar22 * (int)uVar7) >> 0x1f);
    uVar6 = iVar13 + uVar24;
    uVar7 = (int)uVar6 >> 0x1f ^ 0x80000000;
    if (!SCARRY4(iVar13,uVar24)) {
      uVar7 = uVar6;
    }
    iVar13 = iVar16;
    if ((long)(int)uVar7 * (long)(int)uVar4 != 0x4000000000000000) {
      iVar13 = (int)((ulong)((long)(int)uVar7 * (long)(int)uVar4) >> 0x1f);
    }
    iVar14 = (int)((ulong)(lVar22 * (int)uVar1) >> 0x1f);
    uVar26 = (long)(int)uVar7 * (long)(int)uVar33;
    uVar25 = (long)(int)uVar7 * (long)(int)uVar35;
    uVar23 = (long)(int)uVar7 * (long)(int)((ulong)uVar33 >> 0x20);
    uVar27 = (long)(int)uVar7 * (long)(int)((ulong)uVar35 >> 0x20);
    uVar24 = (int)(uVar21 + iVar14) >> 0x1f ^ 0x80000000;
    if (!SCARRY4(uVar21,iVar14)) {
      uVar24 = uVar21 + iVar14;
    }
    lVar15 = -(ulong)(uVar26 == auVar30._0_8_);
    lVar38 = -(ulong)(uVar25 == auVar30._8_8_);
    uVar26 = uVar26 >> 0x1f;
    uVar25 = uVar25 >> 0x1f;
    iVar28 = -(uint)(uVar23 == auVar30._0_8_);
    iVar40 = -(uint)(uVar27 == auVar30._8_8_);
    uVar23 = uVar23 >> 0x1f;
    uVar27 = uVar27 >> 0x1f;
    uVar21 = (int)(uVar24 - iVar13) >> 0x1f ^ 0x80000000;
    if (!SBORROW4(uVar24,iVar13)) {
      uVar21 = uVar24 - iVar13;
    }
    uVar36 = CONCAT44((int)lVar38,(int)lVar15) & 0x7fffffff7fffffff;
    uVar39 = CONCAT44(iVar40,iVar28) & 0x7fffffff7fffffff;
    uVar6 = (int)(uVar21 + iVar14) >> 0x1f ^ 0x80000000;
    if (!SCARRY4(uVar21,iVar14)) {
      uVar6 = uVar21 + iVar14;
    }
    if ((long)(int)uVar7 * (long)(int)uVar5 != 0x4000000000000000) {
      iVar16 = (int)((ulong)((long)(int)uVar7 * (long)(int)uVar5) >> 0x1f);
    }
    iVar14 = (int)((ulong)(lVar22 * (int)uVar3) >> 0x1f);
    uVar24 = iVar14 - iVar16;
    uVar32 = NEON_sqadd(CONCAT17((byte)(uVar36 >> 0x38) |
                                 (byte)(uVar25 >> 0x18) & ~(byte)((ulong)lVar38 >> 0x18),
                                 CONCAT16((byte)(uVar36 >> 0x30) |
                                          (byte)(uVar25 >> 0x10) & ~(byte)((ulong)lVar38 >> 0x10),
                                          CONCAT15((byte)(uVar36 >> 0x28) |
                                                   (byte)(uVar25 >> 8) & ~(byte)((ulong)lVar38 >> 8)
                                                   ,CONCAT14((byte)(uVar36 >> 0x20) |
                                                             (byte)uVar25 & ~(byte)lVar38,
                                                             CONCAT13((byte)(uVar36 >> 0x18) |
                                                                      (byte)(uVar26 >> 0x18) &
                                                                      ~(byte)((ulong)lVar15 >> 0x18)
                                                                      ,CONCAT12((byte)(uVar36 >>
                                                                                      0x10) |
                                                                                (byte)(uVar26 >>
                                                                                      0x10) &
                                                                                ~(byte)((ulong)
                                                  lVar15 >> 0x10),
                                                  CONCAT11((byte)(uVar36 >> 8) |
                                                           (byte)(uVar26 >> 8) &
                                                           ~(byte)((ulong)lVar15 >> 8),
                                                           (byte)uVar36 |
                                                           (byte)uVar26 & ~(byte)lVar15))))))),
                        CONCAT17((byte)(uVar39 >> 0x38) |
                                 (byte)(uVar27 >> 0x18) & ~(byte)((uint)iVar40 >> 0x18),
                                 CONCAT16((byte)(uVar39 >> 0x30) |
                                          (byte)(uVar27 >> 0x10) & ~(byte)((uint)iVar40 >> 0x10),
                                          CONCAT15((byte)(uVar39 >> 0x28) |
                                                   (byte)(uVar27 >> 8) & ~(byte)((uint)iVar40 >> 8),
                                                   CONCAT14((byte)(uVar39 >> 0x20) |
                                                            (byte)uVar27 & ~(byte)iVar40,
                                                            CONCAT13((byte)(uVar39 >> 0x18) |
                                                                     (byte)(uVar23 >> 0x18) &
                                                                     ~(byte)((uint)iVar28 >> 0x18),
                                                                     CONCAT12((byte)(uVar39 >> 0x10)
                                                                              | (byte)(uVar23 >>
                                                                                      0x10) &
                                                                                ~(byte)((uint)iVar28
                                                                                       >> 0x10),
                                                                              CONCAT11((byte)(uVar39
                                                                                             >> 8) |
                                                                                       (byte)(uVar23
                                                                                             >> 8) &
                                                                                       ~(byte)((uint
                                                  )iVar28 >> 8),
                                                  (byte)uVar39 | (byte)uVar23 & ~(byte)iVar28)))))))
                        ,4);
    uVar34 = NEON_sqadd(uVar35,uVar42,4);
    uVar32 = NEON_sqadd(*(undefined8 *)(param_1 + lVar19),uVar32,4);
    *(undefined8 *)(param_1 + lVar19) = uVar32;
    uVar32 = NEON_sqadd(uVar33,uVar41,4);
    lVar19 = lVar19 + 8;
    uVar21 = (int)uVar24 >> 0x1f ^ 0x80000000;
    if (!SBORROW4(iVar14,iVar16)) {
      uVar21 = uVar24;
    }
    lVar22 = 0x7fffffff;
    if ((long)*(int *)(param_6 + 8) * (long)*(int *)(param_6 + 4) != 0x4000000000000000) {
      lVar22 = (long)*(int *)(param_6 + 8) * (long)*(int *)(param_6 + 4) >> 0x1f;
    }
    if (0x7ffffffe < lVar22) {
      lVar22 = 0x7fffffff;
    }
    iVar14 = (int)((ulong)((lVar22 * lVar22 * 2 >> 0x20) * lVar22) >> 0x1f);
    uVar7 = 0x7fffffff - iVar14;
    uVar24 = (int)uVar7 >> 0x1f ^ 0x80000000;
    if (!SBORROW4(0x7fffffff,iVar14)) {
      uVar24 = uVar7;
    }
    iVar14 = (int)((ulong)uVar24 * (long)*(int *)(param_6 + 0xc) >> 0x1f);
    uVar24 = (int)lVar22 + iVar14;
    uVar7 = (int)uVar24 >> 0x1f ^ 0x80000000;
    if (!SCARRY4((int)lVar22,iVar14)) {
      uVar7 = uVar24;
    }
    *(uint *)(param_6 + 4) = uVar7;
    lVar15 = (long)*(int *)((long)param_4 + 0x10) * (long)*(int *)((long)param_4 + 0xc);
    auVar37 = NEON_sqadd(*(undefined1 (*) [16])((long)param_4 + 0x4c),auVar9,4);
    lVar22 = 0x7fffffff;
    if (lVar15 != 0x4000000000000000) {
      lVar22 = lVar15 >> 0x1f;
    }
    if (0x7ffffffe < lVar22) {
      lVar22 = 0x7fffffff;
    }
    *(long *)((long)param_4 + 0x54) = auVar37._8_8_;
    *(long *)((long)param_4 + 0x4c) = auVar37._0_8_;
    iVar14 = (int)((ulong)((lVar22 * lVar22 * 2 >> 0x20) * lVar22) >> 0x1f);
    uVar7 = 0x7fffffff - iVar14;
    uVar24 = (int)uVar7 >> 0x1f ^ 0x80000000;
    if (!SBORROW4(0x7fffffff,iVar14)) {
      uVar24 = uVar7;
    }
    iVar14 = (int)((ulong)uVar24 * (long)*(int *)((long)param_4 + 0x14) >> 0x1f);
    uVar24 = (int)lVar22 + iVar14;
    uVar7 = (int)uVar24 >> 0x1f ^ 0x80000000;
    if (!SCARRY4((int)lVar22,iVar14)) {
      uVar7 = uVar24;
    }
    uVar24 = (int)(uVar6 - iVar13) >> 0x1f ^ 0x80000000;
    if (!SBORROW4(uVar6,iVar13)) {
      uVar24 = uVar6 - iVar13;
    }
    *(uint *)((long)param_4 + 0xc) = uVar7;
  } while ((int)lVar19 != 0x200);
  uVar34 = NEON_sqadd(uVar33,uVar41,4);
  uVar32 = NEON_sqadd(uVar35,uVar42,4);
  *(uint *)((long)param_4 + 0x20) = uVar17;
  *(int *)((long)param_4 + 0x24) = iVar20;
  *(uint *)param_4 = uVar24;
  *(uint *)((long)param_4 + 4) = uVar21;
  *(undefined8 *)((long)param_4 + 0x28) = uVar34;
  *(undefined8 *)((long)param_4 + 0x30) = uVar32;
LAB_002245ac:
  if (*(long *)(lVar8 + 0x28) != lVar18) {
                    /* WARNING: Subroutine does not return */
    __stack_chk_fail();
  }
  return;
}



// ==== Saw013a::onNoteOn @ 00224600 (996 bytes)

/* Saw013a::onNoteOn(int, unsigned char, void*, unsigned int const*) */

void Saw013a::onNoteOn(int param_1,uchar param_2,void *param_3,uint *param_4)

{
  uint uVar1;
  short sVar2;
  uint uVar3;
  long lVar4;
  uint uVar5;
  uint uVar6;
  int iVar7;
  int iVar8;
  int iVar9;
  long lVar10;
  ulong uVar11;
  long lVar12;
  ulong uVar13;
  long lVar14;
  int iVar15;
  
  iVar7 = *(int *)((long)param_3 + 0x38);
  *(undefined8 *)((long)param_3 + 0x60) = 0;
  *(undefined8 *)((long)param_3 + 8) = 0;
  *(undefined8 *)param_3 = 0;
  *(undefined8 *)((long)param_3 + 0x18) = 0;
  *(undefined8 *)((long)param_3 + 0x10) = 0;
  *(undefined8 *)((long)param_3 + 0x28) = 0;
  *(undefined8 *)((long)param_3 + 0x20) = 0;
  *(undefined8 *)((long)param_3 + 0x38) = 0;
  *(undefined8 *)((long)param_3 + 0x30) = 0;
  *(int *)((long)param_3 + 0x38) = iVar7;
  *(int *)((long)param_3 + 0x3c) = param_1 * 0x100000 + -0x3c00000;
  *(undefined8 *)((long)param_3 + 0x48) = 0;
  *(undefined8 *)((long)param_3 + 0x40) = 0;
  *(undefined8 *)((long)param_3 + 0x58) = 0;
  *(undefined8 *)((long)param_3 + 0x50) = 0;
  *(undefined4 *)((long)param_3 + 0x10) = 0x7fffffff;
  *(undefined4 *)((long)param_3 + 0x14) = *(undefined4 *)((long)param_3 + 8);
  *(undefined4 *)((long)param_3 + 0x18) = 1;
  *(undefined1 *)((long)param_3 + 0x1c) = 1;
  uVar5 = *param_4;
  lVar10 = (long)(int)uVar5;
  uVar6 = param_4[1];
  lVar12 = (long)(int)uVar6;
  *(uchar *)((long)param_3 + 100) = param_2;
  *(undefined1 *)((long)param_3 + 0x65) = 0;
  uVar1 = (int)(0x7fffffff - uVar5) >> 0x1f ^ 0x80000000;
  if (!SBORROW4(0x7fffffff,uVar5)) {
    uVar1 = 0x7fffffff - uVar5;
  }
  uVar13 = (ulong)uVar1;
  uVar1 = (int)(0x7fffffff - uVar6) >> 0x1f ^ 0x80000000;
  if (!SBORROW4(0x7fffffff,uVar6)) {
    uVar1 = 0x7fffffff - uVar6;
  }
  uVar11 = (ulong)uVar1;
  iVar9 = (int)((lVar10 * 0xd5504300 >> 0x20) * uVar11 >> 0x1f);
  iVar15 = (int)((uVar13 * 0xfffffffe >> 0x20) * uVar11 >> 0x1f);
  uVar1 = iVar15 + iVar9;
  uVar5 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar15,iVar9)) {
    uVar5 = uVar1;
  }
  iVar9 = (int)((uVar13 * 0x73ef0d00 >> 0x20) * lVar12 >> 0x1f);
  uVar1 = uVar5 + iVar9;
  uVar6 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar5,iVar9)) {
    uVar6 = uVar1;
  }
  iVar9 = (int)((ulong)((lVar10 * 0x65666680 >> 0x20) * lVar12) >> 0x1f);
  uVar1 = uVar6 + iVar9;
  uVar5 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar6,iVar9)) {
    uVar5 = uVar1;
  }
  iVar9 = (int)((ulong)((lVar10 * 0x7bcfbe00 >> 0x20) * lVar12) >> 0x1f);
  iVar15 = (int)((uVar13 * 0xff62b700 >> 0x20) * lVar12 >> 0x1f);
  uVar1 = iVar15 + iVar9;
  uVar6 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar15,iVar9)) {
    uVar6 = uVar1;
  }
  iVar15 = (int)((lVar10 * -0x4c968a00 >> 0x20) * uVar11 >> 0x1f);
  iVar9 = (int)(((long)(uVar13 * -0x4542c000) >> 0x20) * uVar11 >> 0x1f);
  uVar1 = iVar9 + iVar15;
  *(uint *)((long)param_3 + 0x4c) = uVar5;
  *(uint *)((long)param_3 + 0x50) = uVar6;
  uVar5 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar9,iVar15)) {
    uVar5 = uVar1;
  }
  iVar9 = (int)((ulong)(((long)(uVar13 * -0x2c940800) >> 0x20) * lVar12) >> 0x1f);
  uVar1 = uVar5 + iVar9;
  uVar6 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar5,iVar9)) {
    uVar6 = uVar1;
  }
  iVar9 = (int)((ulong)((lVar10 * -0x30c51400 >> 0x20) * lVar12) >> 0x1f);
  uVar1 = uVar6 + iVar9;
  lVar14 = (long)(uVar13 * -0x88d5c400) >> 0x20;
  uVar5 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar6,iVar9)) {
    uVar5 = uVar1;
  }
  iVar15 = (int)((lVar10 * -0x624dd200 >> 0x20) * uVar11 >> 0x1f);
  iVar9 = (int)(lVar14 * uVar11 >> 0x1f);
  uVar1 = iVar9 + iVar15;
  uVar6 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(iVar9,iVar15)) {
    uVar6 = uVar1;
  }
  iVar9 = (int)((ulong)(lVar14 * lVar12) >> 0x1f);
  uVar1 = uVar6 + iVar9;
  uVar3 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar6,iVar9)) {
    uVar3 = uVar1;
  }
  iVar9 = (int)((ulong)((lVar10 * -0x30b06600 >> 0x20) * lVar12) >> 0x1f);
  uVar1 = uVar3 + iVar9;
  uVar6 = (int)uVar1 >> 0x1f ^ 0x80000000;
  if (!SCARRY4(uVar3,iVar9)) {
    uVar6 = uVar1;
  }
  *(uint *)((long)param_3 + 0x54) = uVar5;
  *(uint *)((long)param_3 + 0x58) = uVar6;
  lVar10 = (long)(param_1 / 0xc) * 2;
  iVar8 = ((param_1 % 0xc) * 0x7fff) / 0xc;
  iVar9 = (int)*(short *)((long)&DAT_0134a890 + lVar10);
  iVar15 = *(short *)((long)&DAT_0134a890 + lVar10 + 2) - iVar9;
  if (0x7ffe < iVar15) {
    iVar15 = 0x7fff;
  }
  if (iVar15 < -0x7fff) {
    iVar15 = -0x8000;
  }
  uVar1 = (iVar8 * iVar8 * 2 >> 0x10) * iVar15;
  sVar2 = 0x7fff;
  if (uVar1 != 0x40000000) {
    sVar2 = (short)(uVar1 >> 0xf);
  }
  iVar9 = iVar9 + sVar2;
  if (0x7ffe < iVar9) {
    iVar9 = 0x7fff;
  }
  if (iVar9 < -0x7fff) {
    iVar9 = -0x8000;
  }
  lVar12 = (long)(int)param_4[0xb] * (ulong)((uint)param_2 * 0x1020408 + (uint)(param_2 >> 4));
  lVar10 = 0x7fffffff;
  if (lVar12 != 0x4000000000000000) {
    lVar10 = lVar12 * 2 >> 0x20;
  }
  lVar10 = lVar10 * iVar7;
  uVar1 = 0x7fffffff - param_4[10];
  lVar12 = 0x7fffffff;
  if (lVar10 != 0x4000000000000000) {
    lVar12 = lVar10 * 2 >> 0x20;
  }
  uVar13 = -(ulong)(uVar1 >> 0x1f) & 0xfffffffe00000000 | (ulong)uVar1 << 1;
  lVar10 = (long)(int)param_4[10] * 2;
  lVar12 = lVar12 * (iVar9 << 0x10);
  if (0x7ffffffe < (long)uVar13) {
    uVar13 = 0x7fffffff;
  }
  if ((long)uVar13 < -0x7fffffff) {
    uVar13 = 0xffffffff80000000;
  }
  if (0x7ffffffe < lVar10) {
    lVar10 = 0x7fffffff;
  }
  if (lVar10 < -0x7fffffff) {
    lVar10 = -0x80000000;
  }
  iVar7 = (int)lVar10 >> 1;
  lVar14 = 0x7fffffff;
  if (lVar12 != 0x4000000000000000) {
    lVar14 = lVar12 * 2 >> 0x20;
  }
  iVar9 = (int)uVar13 >> 1;
  lVar12 = 0x7fffffff;
  if (lVar14 * uVar13 != 0x4000000000000000) {
    lVar12 = (long)(lVar14 * uVar13 * 2) >> 0x20;
  }
  uVar1 = (int)(0x40000000U - iVar7) >> 0x1f ^ 0x80000000;
  if (!SBORROW4(0x40000000,iVar7)) {
    uVar1 = 0x40000000U - iVar7;
  }
  lVar4 = 0x7fffffff;
  if (lVar14 * lVar10 != 0x4000000000000000) {
    lVar4 = lVar14 * lVar10 * 2 >> 0x20;
  }
  uVar5 = (int)(0x40000000U - iVar9) >> 0x1f ^ 0x80000000;
  if (!SBORROW4(0x40000000,iVar9)) {
    uVar5 = 0x40000000U - iVar9;
  }
  *(int *)((long)param_3 + 0x28) = (int)(lVar12 * (ulong)(iVar7 + 0x40000000) >> 0x1f);
  *(int *)((long)param_3 + 0x2c) = (int)(lVar14 * (ulong)uVar1 >> 0x1f);
  *(int *)((long)param_3 + 0x30) = (int)(lVar4 * (ulong)(iVar9 + 0x40000000) >> 0x1f);
  *(int *)((long)param_3 + 0x34) = (int)(lVar14 * (ulong)uVar5 >> 0x1f);
  return;
}



// ==== Saw013a::onNoteOff @ 002249e4 (4 bytes)

/* Saw013a::onNoteOff(int, void*) */

int Saw013a::onNoteOff(int param_1,void *param_2)

{
  return param_1;
}



