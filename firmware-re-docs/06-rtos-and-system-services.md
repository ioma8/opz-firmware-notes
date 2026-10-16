# 06 — RTOS architecture, tasks and system services

The OS is not bare-metal. Recovered string evidence establishes the full runtime architecture, which
matters for anyone reasoning about timing, concurrency and where a given behaviour lives.

## 6.1 Two RTOSes and a USB stack

The binary contains **three** distinct system-software layers, all separately identifiable:

| layer | evidence | role |
|---|---|---|
| **uC/OS-III** | `uC/OS-III Idle Task`, `uC/OS-III Tick Task`, `?Task`, `?MUTEX` | the application RTOS |
| **SMX** | `All available SMX tasks already created!`, `No stack found for task!`, `smx set Ilim callback: %dmA`, `smx session active callback: %d` | a *second*, commercial RTOS plus its USB stack |
| **SMX USB** | `USBD_*` / `USBH_*` services (below) | device and host USB stacks |

`C:\snake-software\ext\smx_usb\XBASE\bos.c` and `XUSBH\USBH\USBD\udriver.c` (from
`01-ldr-format-and-image-layout.md`) confirm SMX is a vendored third-party component, not in-house. So
the OP-Z runs **uC/OS-III for the music application and SMX for USB**, side by side. `OSAL Mutex` and
`OSAL Semaphore` show an abstraction layer sitting between them.

## 6.2 Named tasks

```
main_task          #8110 bytes from 81003ef0
sequencer_task                                   <- src/sequencer/task.cpp
filemanager_task
jack_task                                        <- jack detect
```

Plus the RTOS's own `uC/OS-III Idle Task` and `uC/OS-III Tick Task`. The `filemanager_task` is the
consumer of the file-manager MIDI queue found in `05-midi-sysex-and-config.md` §5.3.1 — that is the
task to decompile to recover the MIDI opcode table.

## 6.3 Named synchronisation objects

The mutex/semaphore *names are present as strings*, which means the firmware was built with RTOS
object naming enabled (`OS_CFG_OBJ_NAME_ENABLE`). That is a gift: it turns an anonymous RTOS into a
labelled one.

**Platform services:**

```
nand_rb_semaphore      nand_dma_semaphore      i2c_semaphore
dynamic_serial_semaphore
g_Mutex
OSAL Mutex             OSAL Semaphore
```

**Codec / audio path:**

```
Create codec semaphore error
Create codec mutex error
Failed to post to jack semaphore?
Semaphore error
```

**USB device stack (`USBD_*`):**

```
USBD_ListMutex   USBD_MSMutex   USBD_SerialMutex   USBD_SerialSem
USBD_Blackfin7Sem
sud_TlsfMutex
```

**USB host stack (`USBH_*`)** — a large, fully-labelled set:

```
USBH_HostBusMutex      USBH_DeviceMutex     USBH_ClassDrvMutex
USBH_RequestDoneSema   USBH_MSCmdMutex      USBH_HeapMutex
USBH_HubSem            USBH_HubMutex        USBH_ExtHubMutex
USBH_AudioMutex        USBH_AudioPlaybackMutex
USBH_AudioRecordMutex  USBH_AudioMIDIMutex
USBH_BlackfinSem       USBH_BlackfinMutex
USBH_FTDI232Mutex
```

The host stack having **Audio, AudioPlayback, AudioRecord and AudioMIDI mutexes plus an FTDI232
mutex** indicates the OP-Z can act as a **USB host** for external audio interfaces, MIDI devices and
FTDI-based serial gear. `USBH_ExtHubMutex` means external hubs are supported. The FTDI entry is now more than
an inference: the firmware ships `readme/how_to_dmx.txt`, which states that the OP-Z *"can transform sequencer
data to DMX channel data and send it out using a **USB DMX interface**"* (doc `05` §5.8) — and USB DMX
interfaces are FTDI-based, so that mutex is the DMX output path.

## 6.4 Power management

```
power_sleep()
System suspend requested, shutting down keyboard LED:s
g_audio.suspend()
close twi and suspend rtc
battery status: removed.
psoc acc power mode
this profile powerdraw is %d (override:%d, limit: %d, hubaddr: %d)
```

Two things worth noting:

- **The suspend sequence is explicit and ordered**: keyboard LEDs off → audio suspended → TWI closed →
  RTC suspended. This is the graceful path taken when the USB cable is unplugged.
- **USB host power is profile-gated**: `This profile powerdraw is %d (override:%d, limit: %d,
  hubaddr: %d)` shows the device budgets the power it supplies to a downstream device, with an
  *override* and a *limit* — and reports it against a hub address. That is a real USB-host power
  management implementation, and it explains how the OP-Z can drive bus-powered gear.

> **Attribution correction (see doc `07` §7.4).** The `PowerPreSleep` and `Going to charging state` log
> lines observed on the device do **not** come from the Blackfin. Neither string exists in `opz.ldr`; both
> are in the **PSoC power controller** image, together with `psStandby`/`psOnHost`/`psCharging`/`psDeadBatt`
> and `Wake Leds`/`LedSleep`/`LedWake`. The Blackfin does have its own suspend path (above), but the `ps*`
> state machine and those two messages are PSoC-side. Both chips log into the same serial stream, which is
> what makes this easy to mis-attribute — so classify frames by **content and string provenance**, not by
> routing. The line `System suspend requested, shutting down keyboard LED:s` *is* genuinely Blackfin (it is
> present in `opz.ldr`), which is exactly why the two are easy to confuse.

## 6.5 Log channels and the log format

Four log destinations are named, and the bootloader holds the matching directory paths
(`02-string-and-symbol-inventory.md` §2.2):

```
/yaffs2/logs/system     /yaffs2/logs/upgrade
/yaffs2/logs/import     /yaffs2/logs/battery
```

The OS log format strings (`#dat[%d:%d]`, `S%02d%02dIN`, `S%02d%02dRW` and the codec cycle counters are
**bootloader** strings; the percentage-log prefix appears in both, consistent with the shared
`SerialMessageHandler.cpp`):

```
[%02d-%02d-%02d %02d:%02d:%02d] %s%s        <- the log prefix
[%02d:%02d]                                 <- short form
#dat[%d:%d]                                 <- raw serial frame debug
```

`#dat[%d:%d]` is the raw-frame debug form, and `S%02d%02dIN` / `S%02d%02dRW` in the bootloader are the
serial-message handler's state tags.

## 6.6 CRC hardware acceleration

```
BF arm CRC        BF enable CRC        BF try to enable CRC
BF enable CRC     unexpected SOF
BF arm CRC
```

`BF enable CRC` / `BF arm CRC` / `BF try to enable CRC` are the Blackfin's **hardware CRC unit** being
brought up for the serial protocol, with `unexpected SOF` as the framing error. The bootloader's error
table lists `CRC error` among the filesystem errors, and `05-`/`03-` documents show CRC32 used for file
identity elsewhere (`opz.crc32`, `invalid file crc`). So there are **three** distinct CRC users:
hardware-accelerated serial framing, firmware image integrity, and file-sync identity.

Also present, and a useful performance note:

```
%llu bytes decoded in %llu cycles = %llu per byte
%llu bytes encoded in %llu cycles = %llu per byte
id 0x%x failed to set routing to id 0x%02x
```

The firmware **measures its own codec throughput in cycles per byte** and can log it. If it ever
appears in a log, it is a direct measurement of the serial path's performance rather than an inference.

## 6.7 Method note

This section came from a deliberate change of target. Having stalled on resolving individual MIDI
opcodes (`05-…` §5.7), I searched the string pool for **task and synchronisation vocabulary** instead of
for command names — and found a fully labelled RTOS. When a specific symbol resists, broadening to the
*architecture* that contains it is often the faster route, and it produced the named-task list that is
the lead for the outstanding MIDI work.

## 6.8 What this does not establish

The uC/OS-III task priorities, stack sizes and the exact number of additional tasks are **not**
recovered. Only the four application task names above are visible as strings; others may exist unnamed
(created without `OS_CFG_OBJ_NAME_ENABLE` for that object, or with a name I did not recognise). Task
construction sites have not been decompiled.
