# 10 — Architecture and data flow, as two diagrams

This document is a map, not a source of new findings. Everything in it is drawn from the other nine
documents; where an edge is an inference rather than a read fact, it is marked in §10.4 rather than
smoothed over. Its purpose is orientation: after reading docs `01`–`09` a reader knows a great deal
about individual subsystems and still cannot see the shape of the thing.

Both diagrams are Mermaid, so they render in any Markdown viewer that supports it (GitHub does).

## 10.1 The architecture: three processors, two RTOSes, one source tree

```mermaid
flowchart TB
  subgraph HOST["Host side and external gear"]
    APP["OP-Z app + firmware payloads<br/>ZIP with ../user/... entry paths"]
    FTDI["USB DMX interface<br/>FTDI-class, bus-powered"]
    GEAR["USB audio and MIDI gear,<br/>hubs"]
  end

  subgraph BF["Blackfin+ — opz.ldr (the OS), 1,993 functions"]
    L1["L1 overlay 0x1180_0000-0x11a0_d3d4<br/>serial_command_handler.cpp + the companion<br/>send primitive FUN_11a01d24"]
    RTOS["uC/OS-III for the application<br/>main_task, sequencer_task, filemanager_task, jack_task<br/>plus SMX, a second vendored RTOS, for USB<br/>USBD_* device stack and USBH_* host stack"]
    subgraph SW["src/sequencer/ — the musical application"]
      SEQ["Sequencer, Pattern, Arpeggio<br/>7 contexts: Default, Pattern, Tempo,<br/>Track, Sampler, RenderSong, Score"]
      SYN["Synth, Voice, InstrumentManager,<br/>FxManager, PlugManager"]
      MID["Midi, UsbMidi, SequencerMidi"]
      FMGR["filemanager: FileManager,<br/>FileClient, FileServer, FileSync"]
      DMXC["DmxController"]
      LIT["light engine: slot table,<br/>palette, change-only flush"]
    end
    subgraph PLAT["src/bf/ — platform layer"]
      DLM["dlm — the module loader<br/>opens /yaffs2/user/engines/NAME.engine"]
      STORE["Nand, fs, spi_flash, yaffs2,<br/>mass_storage, metadata, otp, rtc"]
      COD["Codec"]
      UCTL["UsbControl — cable attach/detach,<br/>the 0x801fa74 USB/power state block"]
    end
    SHR["src/shared/ — KeyHandler, SerialMessageHandler,<br/>command_handler (plain / ble / kb)<br/>linked into BOTH Blackfin images"]
  end

  subgraph BOOT["Blackfin+ — bootloader.ldr, 1,389 functions"]
    BCMD["serial console: 21 commands,<br/>numeric AND @EIV: dialects"]
    BUPD["updater: ZIP entry-CRC gate, extract,<br/>retain to /yaffs2/last_upgrade/"]
    BPKT["PSoC packet protocol<br/>types 0x31-0x3B and 0x44-0x4D"]
  end

  subgraph NRF["nRF52832 Cortex-M4 — nrf52832_opz.bin"]
    BLED["message dispatch, 129 slots,<br/>20 types used"]
    BLET["transport: 1024-byte ring,<br/>frames of at most 255 bytes"]
    BDTM["Bluetooth Direct Test Mode"]
    BPB["protobuf descriptor + 64-byte signature"]
  end

  subgraph P5LP["PSoC 5LP Cortex-M3 — kb_DVT2.cyacd"]
    P2D["host-message dispatch, 146 slots,<br/>39 types implemented"]
    PPIPE["64-slot 8-byte message ring,<br/>allocator FUN_000140d4"]
    PPWR["power, charger, PMIC, USB-PD<br/>and the I2C charger at 0x69"]
    PLED["key matrix + LED driver"]
  end

  APP -->|"firmware zip on the<br/>update-mode volume"| BUPD
  BUPD -->|"verify then write"| STORE
  BUPD -->|"cyacd rows"| BPKT
  BPKT --> P2D
  BUPD -->|"BLE image and .dat"| BLED

  STORE -->|"*.engine"| DLM
  DLM --> SYN
  SEQ --> SYN
  SYN --> COD
  COD -->|"analog out"| GEAR
  MID --> SEQ
  SYN --> LIT
  SEQ --> DMXC
  DMXC -->|"56-byte blocks over<br/>USB bulk"| FTDI
  UCTL -->|"device mode: mass storage,<br/>MIDI, audio"| APP
  RTOS -->|"USB host: audio, MIDI,<br/>FTDI, external hubs"| GEAR

  SHR -->|"type byte = receiver's own<br/>dispatch index"| P2D
  SHR --> BLED
  L1 --> P2D
  BLET -->|"the Nordic's own<br/>'send to uart' path"| L1
  LIT -->|"type 0x10 light flush"| PPIPE
  PPIPE --> PLED
  UCTL -->|"types 0x3c and 0x3d: a charger<br/>reading, floored at 5.0 V and 9.0 V"| PPWR
  PPWR -->|"reply: the I2C 0x69 register,<br/>divided by ten"| UCTL
  BDTM --> BLET
  BPB --> BLED
```

**Reading it.** The unit is not one computer. The **Blackfin+** runs the music application on
uC/OS-III and the USB stacks on a second, commercial RTOS (SMX) — two RTOSes side by side with an
`OSAL` shim between them (doc `06` §6.1). The **nRF52832** is the radio, and it is a peer rather than
a modem: it has its own 129-slot message dispatcher, its own protobuf descriptor, and a Direct Test
Mode that the *Blackfin* can command (doc `04` §4.6b). The **PSoC 5LP** is not a keyboard controller
— it is the power, charging and USB-PD subsystem that also happens to scan the keys and drive the
LEDs (doc `07` §7.4c). The **bootloader** is a separate Blackfin image, and it is the only actor that
can write the other two CPUs.

Two structural notes that took work to see. `src/shared/` is **compiled into both Blackfin images**,
which is why the console's command vocabulary appears in the bootloader and the OS alike (doc `01`,
the "Source tree and build environment" section). And the `0x1180_0000`/`0x11a0_0000` region is a **separately loaded L1 overlay** holding
`serial_command_handler.cpp` and the companion send primitive `FUN_11a01d24`; the rest of that span
is mostly zeros, which is why a naive sweep of it burns its whole instruction budget (doc `09` §9.4).

## 10.2 The basic data flows: sound, notes and light

The runtime path. One diagram, left to right: what comes in, what turns it into sound, and what
leaves as light.

```mermaid
flowchart LR
  subgraph IN["Input"]
    KEYS["PSoC key matrix<br/>and encoders"]
    MIN["MIDI in<br/>USB, BLE or jack"]
    SAMPLES["samples on NAND<br/>.aif / .aiff / .wav"]
  end

  subgraph PLAYER["Sequencer"]
    PAT["Pattern, Arpeggio,<br/>ParameterSweep"]
    CTX["the active context<br/>(Default, Pattern, Tempo, Track,<br/>Sampler, RenderSong, Score)"]
  end

  subgraph VOICEBOX["Synthesis"]
    INST["InstrumentManager + PlugManager<br/>resolve slot to a plug"]
    ENG["the .engine module<br/>initModule / render / renderFX"]
    VOICE["Synth, Voice, FxManager"]
  end

  subgraph OUTBOX["Output"]
    CODEC["Codec"]
    AUDIO["analog audio out"]
    LIT["light engine flush"]
    DMXOUT["DmxController frame<br/>00 06 COUNT 00 + payload"]
  end

  KEYS --> CTX
  MIN --> CTX
  PAT <--> CTX
  CTX --> INST
  SAMPLES -->|"SampleLoader"| VOICE
  INST --> ENG
  ENG --> VOICE
  VOICE --> CODEC --> AUDIO
  CTX --> LIT
  LIT -->|"companion type 0x10,<br/>a diff of the slot table"| LEDOUT["PSoC LED driver"]
  CTX --> DMXOUT
  DMXOUT -->|"only while the USB power<br/>state byte is 0x10"| FTDI["USB host, FTDI DMX interface"]

  subgraph SIDE["Side channel, always running"]
    MIDIOUT["Midi, UsbMidi, SeqMidi<br/>out to USB and BLE"]
    STATE["StateSync, Serialize<br/>settings and patterns"]
  end
  CTX --> MIDIOUT
  CTX <--> STATE
  STATE <--> NANDW["NAND + yaffs2"]
```

**Reading it.** The centre of gravity is the **context** object: input does not go straight to the
synth, it goes to whichever of the seven contexts is active, and that context both drives the voices
and paints the lights. The lighting is not a side effect of the audio at all — `FUN_8003ac64` derives
its per-fixture preview flags by switching on the **note byte** of each track record (doc `05` §5.8c),
so the LED and DMX state is computed from the same note stream that feeds the engines.

Three flows in this diagram have a gate worth remembering:

- **Audio to the outside** needs the engines loaded; a slot whose `.engine` will not load is silent,
  and the log says `Can't load engine <id>` (that is what the recovery work in the repository's
  `FIRMWARE_ANALYSIS.md` was fixing).
- **Light out** is a *difference*, not a frame: the flush walks the 53-record table, compares against
  a second copy, and emits only the 6-byte changes, capped at 154 bytes (doc `08` §8.4).
- **DMX out** is gated on the USB power state byte at `0x801fa75` being exactly `0x10` (doc `05`
  §5.8b), and it leaves through the **host** stack to an FTDI interface, not through the device port.

## 10.3 The other basic flow: content and firmware

Kept separate because it has different actors — this is the only flow where the bootloader and the
host are both in charge.

```mermaid
flowchart LR
  Z["firmware_*.zip<br/>written as the update-mode volume's<br/>firmware_bin_only_with_bootloader.zip"]
  GATE{"ZIP entry CRC<br/>the only integrity gate"}
  EX["extract to /yaffs2"]
  KEEPC["settings/plugs.json and<br/>slotConfiguration.json are the app's:<br/>rewriting them gets undone"]
  ENG["/yaffs2/user/engines/NAME.engine"]
  DLM2["dlm loads by engine memory slot"]
  CY["PSoC .cyacd rows,<br/>256-byte payloads"]
  BLEI["BLE image nrf52832_opz.bin<br/>+ nrf52832_opz.dat"]
  RETAIN["/yaffs2/last_upgrade/"]
  BOOT2["reset and run"]

  Z --> GATE --> EX
  EX --> ENG --> DLM2
  EX --> CY --> RETAIN
  EX --> BLEI
  EX --> KEEPC
  BLEI --> BOOT2
  DLM2 --> BOOT2
```

**Reading it.** The gate is the **ZIP entry CRC**, decompiled rather than assumed (doc `03` §3.3) —
which is why the per-line `.cyacd` trailer needs no reproduction, an item this project closed and
should not reopen (doc `07` §7.4). The two settings files are listed because overwriting them is the
classic mistake: the app owns them and will restore its own copies. And `/yaffs2/firmware_auto.zip`
is a second entry point to this same flow — a file-presence hook checked at boot (doc `04` §4.5c).

## 10.4 What these diagrams deliberately do not claim

A map that overstates itself is worse than no map, so the boundaries:

- **The wires between the chips are not established.** The diagrams label edges by *protocol* (the companion
  type byte, the packet protocol, the transport ring) because that is what was read. Only one edge names a
  transport at all — the Nordic's `uart` path, and only because `FUN_00027e0c` and its `Failed to send to uart`
  string name it. Which physical bus the companion message channel crosses is not settled here.
- **The companion bus is drawn bidirectional, and only some directions are proven.** Blackfin → PSoC
  is well evidenced for several types; the PSoC → Blackfin direction is evidenced by reply-building
  code (doc `07` §7.4c) but not enumerated type by type.
- **The audio block is coarse on purpose.** `Codec` is a named translation unit and
  `g_audio.suspend()` is a named call, but the codec's register sequence and the exact routing through
  the L1 overlay were not read, so `Codec --> analog out` is a summary, not a traced path.
- **`jack_task` is not placed.** It is a named task and a named semaphore exists (`Failed to post to
  jack semaphore?`), but what the jack is — audio detect, a line module, CV — is not established, so
  it appears only in §10.1's task list.
- **The L1 overlay is a box, not a description.** Its two clusters are named by what was found in
  them; its full contents are unmapped.
- **The `nRF52832` and `PSoC` inboxes are drawn as one node each.** Both have their own two-level
  dispatch, ring buffers and hardware helpers; those are in doc `07`, not here.
