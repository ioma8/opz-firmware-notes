/* opzload -- re-insert the OP-Z update medium with a SCSI START STOP UNIT (load).
 *
 * The device presents a normal composite CDC + Bulk-Only Mass Storage device, so
 * interface 2 exists; unprivileged it is denied with LIBUSB_ERROR_ACCESS -- a
 * permission denial, not a busy interface.  So the reset/re-enumerate dance is NOT a
 * prerequisite: just claim it.  Re-enumeration is now a last resort, capped at two,
 * because hammering it may be what dropped the unit off the bus.
 *
 * Only exits 0 when interface 2 was claimed and START STOP UNIT was issued.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <libusb.h>
#include <unistd.h>

static libusb_device *find(libusb_context *ctx, libusb_device ***out_list) {
  libusb_device **l; ssize_t m = libusb_get_device_list(ctx, &l);
  libusb_device *dev = NULL;
  for (ssize_t i = 0; i < m; i++) {
    struct libusb_device_descriptor d;
    if (libusb_get_device_descriptor(l[i], &d)) continue;
    if (d.idVendor == 0x2367) { dev = l[i]; break; }
  }
  if (!dev) { libusb_free_device_list(l, 1); return NULL; }
  *out_list = l;
  return dev;
}

static int reenumerate(libusb_context *ctx) {
  libusb_device **l = NULL;
  libusb_device *dev = find(ctx, &l);
  if (!dev) return -1;
  libusb_device_handle *h = NULL;
  if (libusb_open(dev, &h)) { libusb_free_device_list(l, 1); return -1; }
  printf("re-enumerating the device...\n");
  int r = libusb_reset_device(h);
  printf("  reset -> %s\n", r ? libusb_error_name(r) : "ok");
  libusb_close(h);
  libusb_free_device_list(l, 1);
  return 0;
}

static int try_claim(libusb_context *ctx, int attempts) {
  int last = 0;
  for (int i = 0; i < attempts; i++) {
    libusb_device **l = NULL;
    libusb_device *dev = find(ctx, &l);
    if (!dev) { last = LIBUSB_ERROR_NO_DEVICE; usleep(200000); continue; }
    libusb_device_handle *h = NULL;
    if (libusb_open(dev, &h)) { libusb_free_device_list(l, 1); usleep(100000); continue; }
    libusb_set_auto_detach_kernel_driver(h, 1);
    int r = libusb_claim_interface(h, 2);
    if (r != 0) {
      int d = libusb_detach_kernel_driver(h, 2);
      if (d == 0) r = libusb_claim_interface(h, 2);
      if (i == 0)
        printf("claim: auto_detach=ok detach=%s claim=%s\n",
               d ? libusb_error_name(d) : "ok", r ? libusb_error_name(r) : "ok");
    }
    if (r == 0) {
      printf("CLAIMED interface 2 (attempt %d)\n", i);
      unsigned char inq[6] = {0x12, 0, 0, 0, 36, 0}, tur[6] = {0}, rs[6] = {0x03, 0, 0, 0, 18, 0};
      unsigned char avert[6] = {0x1e, 0, 0, 0, 0, 0};
      unsigned char lo1[6] = {0x1b, 0, 0, 0, 0x01, 0};   /* LoEj=1               */
      unsigned char lo2[6] = {0x1b, 0, 0, 0, 0x03, 0};   /* Start=1, LoEj=1      */
      unsigned char buf[512];
      struct { const char *n; unsigned char *c; int dl; int in; } cmds[] = {
        {"INQUIRY:", inq, 36, 1}, {"TEST UNIT READY:", tur, 0, 0},
        {"REQUEST SENSE:", rs, 18, 1}, {"ALLOW MEDIUM REMOVAL:", avert, 0, 0},
        {"START STOP UNIT (LoEj=1):", lo1, 0, 0},
        {"START STOP UNIT (Start=1,LoEj=1):", lo2, 0, 0},
        {"TEST UNIT READY:", tur, 0, 0},
      };
      for (unsigned c = 0; c < sizeof cmds / sizeof cmds[0]; c++) {
        printf("%s\n", cmds[c].n);
        unsigned char cbw[31] = {0}, csw[13] = {0};
        cbw[0] = 'U'; cbw[1] = 'S'; cbw[2] = 'B'; cbw[3] = 'C';
        cbw[4] = 0x11; cbw[5] = 0x22; cbw[6] = 0x33; cbw[7] = 0x44;
        cbw[8] = cmds[c].dl & 0xff; cbw[9] = (cmds[c].dl >> 8) & 0xff;
        cbw[12] = cmds[c].in ? 0x80 : 0; cbw[14] = 6;
        memcpy(cbw + 15, cmds[c].c, 6);
        int x = 0, r2 = libusb_bulk_transfer(h, 0x08, cbw, 31, &x, 3000);
        if (r2 || x != 31) { printf("  CBW -> %s (x=%d)\n", r2 ? libusb_error_name(r2) : "short", x); continue; }
        if (cmds[c].dl) {
          int g = 0;
          r2 = libusb_bulk_transfer(h, cmds[c].in ? 0x87 : 0x08, buf,
                                    cmds[c].dl > 512 ? 512 : cmds[c].dl, &g, 3000);
          printf("  data %d bytes -> %s\n", g, r2 ? libusb_error_name(r2) : "ok");
        }
        r2 = libusb_bulk_transfer(h, 0x87, csw, 13, &x, 3000);
        printf("  CSW -> %s (x=%d) status=%d\n", r2 ? libusb_error_name(r2) : "ok", x,
               (r2 || x != 13) ? -1 : csw[12]);
      }
      libusb_release_interface(h, 2);
      libusb_close(h);
      libusb_free_device_list(l, 1);
      return 0;
    }
    last = r;
    libusb_close(h);
    libusb_free_device_list(l, 1);
    usleep(100000);
  }
  return last;
}

int main(void) {
  libusb_context *ctx = NULL;
  libusb_init(&ctx);

  libusb_device **l = NULL;
  if (!find(ctx, &l)) { libusb_free_device_list(l, 1); }
  else { libusb_free_device_list(l, 1); }

  int r = try_claim(ctx, 30);            /* no reset: as root this should just work */
  if (r != 0) {
    printf("claim failed without a reset (%s)\n", r ? libusb_error_name(r) : "?");
    for (int round = 0; round < 2; round++) {   /* capped: hammering may drop the unit */
      if (reenumerate(ctx) != 0) break;
      usleep(500000);
      r = try_claim(ctx, 15);
      if (r == 0) { libusb_exit(ctx); return 0; }
    }
  } else { libusb_exit(ctx); return 0; }

  if (r == LIBUSB_ERROR_ACCESS)
    printf("could not claim interface 2: permission denied (LIBUSB_ERROR_ACCESS).\n"
           "Run this as root, or install the sudoers rule (OP-Z-unstick.command).\n");
  else if (r == LIBUSB_ERROR_NO_DEVICE)
    printf("no OP-Z on the bus -- the unit is powered off or unplugged; press PLAY.\n");
  else
    printf("could not claim interface 2 (%s)\n", r ? libusb_error_name(r) : "no OP-Z found");
  libusb_exit(ctx);
  return 1;
}
