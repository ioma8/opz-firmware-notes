# OP-Z – předávací dokument pro dalšího agenta

> Tento soubor je v češtině záměrně (na přání zadavatele). Všechny identifikátory, cesty, příkazy a názvy
> souborů zůstávají v původním tvaru. Aktuální stav je v bloku níže; podrobnosti jsou v `FIRMWARE_ANALYSIS.md`
> (zejména §§66.90–66.93) a výsledky hypotéz v `HYPOTHESES.csv`.

## AKTUÁLNÍ PŘEDÁNÍ (2026-10-16) — jednotka je opravená a hraje

**Stav:** OP-Z je obnovená a přehrává. Obsah zapsaný přes updater (§24) a ověřený čtením z zařízení:

| co | kde | ověřeno |
|---|---|---|
| 21 oficiálních engine | `/yaffs2/user/engines/` | payload 90305/90305; 4 soubory přečteny zpět a jsou **byte-identical** s `engines-official/` |
| 24 továrních sample packů | `/yaffs2/user/samplepacks/` | payload 18430845/18430845; `CuckooKicks.aif` přečten zpět = **310 864 B** (pravý pack, ne vyrobený 890 370 B) |
| 8 engine dárcovských | `/yaffs2/system/content/engines/` | `chord.engine` 2 664 B, sha256 shoduje s `opz-dump/manifest.json` |
| sloučená tabulka plugů | `settings/plugs.json` | 6 172 B, **byte-identical** s naším sloučeným souborem; 50 plugů, 21 engine, **0** slot-referencí na nedefinované id |

**Konzole v update módu funguje i na zdravé jednotce.** Dřívější závěr „konzole je obsluhovaná jen dokud se
nenabootuje OS“ byl **chybný** — `FW_SUCCESS.md` §25.3 a §27 jsou tam označené jako neplatné. Příčinou ticha byl
náš vlastní encoder: escapoval **úvodní `C0`** rámce, takže zařízení nikdy nevidělo začátek rámce a neodpovídalo
vůbec na nic (žádný PONG, žádný reply, žádný log) v každém stavu, na každém baudu a při obou DTR.

**Pravidla, která z toho plynou:**

- Rámce stavěj hotovými encodery — `toolkit/opzcopyprobe.py::encode` nebo `sergey-extraction/opzget.py::encode`:
  hlavička `C0 <routing> <type> <len_be32>` se posílá **raw**, escapuje se jen payload. Nikdy neescapuj vlastní
  rukou; tichá konzole je **hypotéza o toolingu**, ne o zařízení. Detail: `FIRMWARE_ANALYSIS.md` §71.1.
- Odpovědi klasifikuj podle **typu**, ne routingu: logy jsou typ `0x04` (routing `0x1e` z bootloaderu, `0x2e`
  z OS), reply je každý jiný typ — a PONG je routing `0x1e` **typ `0x01`**, tedy stejný routing jako bootloaderové
  logy. `opzframe.frames()` zahazuje rámce s nulovou délkou, takže PONG se v něm neobjeví.
- **Čtení souborů `0x19` funguje v update módu** (cesty relativně k `/yaffs2`), takže zápisy lze ověřovat zpětně.
  Libovolnou cestu přečteš přeposměrováním šablon v `opzget.py` bez nového protokolového kódu (§71.3).
- SysEx file service přes USB MIDI **není cesta podle cest**: páruje **registrovaná file id**. `../user/settings/plugs.json`
  (tatáž cesta přes `..`) se nevyřídí, `samplepacks/redmountKicks.aif` také ne — „missing“ tam tedy **není důkaz
  neexistence** a stavové soubory bootloaderu (`os.version`, `system/firmware.version`) tím číst nelze (§71.4).

**Otevřené položky:**

- `pulled/settings/plugs.json` a `pulled/settings/slotConfiguration.json` jsou **trackované ve veřejném repu** a
  obsahují aktuální konfiguraci jednotky; rozhodnutí (untrack / scrub / ponechat) stále není zaznamenáno.
- `0x06` a `0x34` (handlery file-transferu) zůstávají netestované; `0x2b` je one-shot.

## AKTUÁLNÍ PŘEDÁNÍ (2026-10-13) — oracle pro bootloader

**Aktivní cíl:** dokončit obnovu komprimovaného členu `firmware/blackfin/bin/bootloader.ldr` z `.zfw` oracle a
prohledat jeho plaintext na AES-256 klíč. Nejde o obnovu celého `opz.ldr` OS obrazu.

- ZIP člen začíná na payload offsetu **467,507**; DEFLATE data na **467,573**, délka **156,306 B**, délka po
  rozbalení **257,644 B**, CRC-32 `5087bc54`.
- Kontinuální prefix má **811 komprimovaných B**, které dávají **1,211 plaintextových B** (`eof=false`). Tři
  BF70x LDR hlavičky na plaintext offsetech 0, 16 a 124 mají správný podpis/checksum; třetí payload je neúplný.
- Otestováno všech **1,180** posuvných 32B oken prefixu proti dvěma známým plaintextům; **bez shody**. Závěr platí
  jen pro prvních 1,211 rozbalených bajtů, ne pro zbytek loaderu.
- `toolkit/opzbootprobe.py` ukládá capture/state pod `~/.opz-decode/bootloader-probes/`, obnovuje rozsah při
  opakovaném spuštění a automaticky čeká na update volume. Stále ale **neovládá napájecí relé** a po jednom
  oracle čtení je potřeba skutečný power cycle. Farmu `com.opz.decode` nespouštět souběžně.
- Uživatel potvrzuje, že navržené relé zařízení skutečně vypne i při připojeném USB. Obnovení napájení,
  automatický návrat do `OP-Z Boot`, nové připojení volume a úplný čas cyklu zatím ověřeny nejsou; **20 s/cyklus
  je předpoklad, ne měření**. Při naměřeném výtěžku 42.7 B/probe zbývá asi 3,645 probe, tedy ~20.25 h při 20 s/cyklus.
- Capture nyní čeká na celý 20s timeout; průměrně první leak dorazil za 5.120 s, ale capture od detekce volume
  do konce trval průměrně 20.510 s. Pro 20s celý cyklus je nutné zastavit capture po kompletním leak framu.
- Plán integrace a pilotu: [`PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md`](PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md).
  Zatím nebylo upraveno Arduino, připojeno relé k PCB ani provedeno automatické vypnutí/zapnutí.
- **Nezávislé potvrzení metody (§66.94):** výzkumník `_bt` veřejně uvádí, že klíč našel tak, že po získání
  dešifrovaného firmwaru přes oracle na zařízení testoval **všech 32B posuvných oken dešifrovaného bootloaderu**
  (trvalo to sekundy). To je přesně naše metoda a znamená, že klíč je uvnitř `bootloader.ldr` plaintextu.
  Náš negativní výsledek tedy jen říká, že klíč leží za prvních 1 211 rozbalených bajtů – **hardware k němu
  není potřeba**.
- **Recenze čtyř komunitních zdrojů (§§66.94–66.96):** EP-133 SysEx, EP-133/EP-40 SysEx a glitching blog
  nepřinášejí klíč, dešifrovaný image ani obejití limitu jednoho čtení na boot. Nejužitečnější nalezené
  artefakty jsou *vedle* nich: OP-1 OTP dump + patchnutý `te-boot` s OTP operacemi (`Tolsi/op1dumps`)
  a ADI EE-366 (BF70x secure boot je volitelný a defaultně vypnutý, secure debug key je 128b v OTP).
  Pokud by BF703 **nebyl** zamčený, přímý emulátor/JTAG attach by dal paměť i NAND – tedy obnovu i
  dešifrovaný image bez klíče; to ale vyžaduje zapojení do PCB, které dřívější instrukce vyloučila.
- **Glitching (§66.97):** reálná technika, ale pro toto zařízení je až třetí v pořadí a je dvakrát
  dominovaná – software oracle klíč už umí a jeden pokus o obyčejný emulátor/JTAG attach je levnější.
  Každý publikovaný precedent (RGH, AirTag, ESP32, STM32) měl přístupný glitch bod, časovací trigger,
  levný success oracle a opakovatelný nízkorizikový cíl; OP-Z nemá ani jedno (success oracle neexistuje –
  „zamčeno“ ani „OTP čitelné“ nemá žádný pozorovatelný projev). Navíc RGH přeskakoval *podpis*, kdežto
  `.zfw` klíč chrání *důvěrnost* – na klíč je potřeba přemoci čtení OTP, ne přeskočit verifikaci.
  ADI dokumentuje BF70x secure boot jako volitelný a defaultně vypnutý, takže rozhodující otázka je
  **lock state**. Postup, pokud se do hardwaru půjde: dokončit oracle → otevřít a najít debug pady →
  zkusit obyčejný attach → teprve pak glitch.
- **Nález na desce (§66.98):** na uživatelově fotu processor board je skupina **6 plochých zlatých padů
  2×3 na čtvercové mřížce** (rozteč sloupců 158 px, řádků 154 px, průměr padu ~63 px, bez děr). Při
  kalibraci podle poblíž plátovaného montážního otvoru (~117 px) to vychází na **rozteč ~2.4–2.9 mm a pady
  ~1.0–1.2 mm** – tedy footprint třídy 0.1" / 2.0 mm, ale jako ploché pady (probe/pogo/pájivé terče),
  ne průchozí díry. Z místa odchází **svazek ~5 rovnoběžných spojů** k hornímu pravému rohu.
  Šest samostatných signálů = klasické minimum JTAG (TCK, TMS, TDI, TDO, nTRST, GND), ale stejná geometrie
  sedí i na tovární testovací pole, programovací header companion MCU nebo kontaktní pole. **Není to
  důkaz** – čip na fotu není vidět, takže "spoje vedou přímo do čipu" je třeba potvrdit kontinuitou.
  Identifikace (bez zápisu do zařízení): 1) nepowerované kontinuity všech 15 dvojic, 2) pípnutí na zem,
  3) odpor pad→zem a pad→napájení (~4.7k–10k pull-up = typický bias TCK/TMS/TDI/nTRST), 4) sledovat
  spoje přes via na druhou stranu k čipu, 5) teprve pak emulátor / ADI BY-PASS scan test (EE-356).
  Rozlišovač: **4 signály** = spíš SWD na ARM companion čipu; **5 signálů** = JTAG, což je případ, který
  nás zajímá. Pokud by to byl debug port BF703 a čip nebyl zamčený, dal by obyčejný attach paměť i flash –
  tedy obnovu i dešifrovaný firmware **bez klíče**, lépe než oracle.
- **Nářadí pro JTAG (§66.99):** existuje **OpenOCD fork s podporou BF70x** (`deanm1278/openocd`, soubory
  `bfinplus*.c`, `tcl/target/bf706.cfg`) — v mainline OpenOCD to není. Podporuje **JTAG i SWD** transport a
  jeho seznam adaptérů obsahuje **Buspirate, CMSIS-DAP, FTDI, sysfsgpio, BCM2835** — tedy levný hardware.
  Klíčové: BF70x TAP je „ADI JTAG Controller“ a DAP se musí odemknout zápisem **čtyř 32bit UserKey**
  (128bit secure-debug klíč) přes `irscan 0xa` / `drscan`, pak `irscan 0x5` / `drscan 8 0x4`. Šablona má
  všechny čtyři klíče defaultně `0x00000000`, takže **první pokus o attach přímo změří lock state**. Stejný
  autor má i `bf70x-bootloader`: přes OpenOCD nahraje loader do instruction RAM a zpřístupní **externí SPI
  flash** přes virtuální registry — to je přesně tvar obnovy, který potřebujeme.
  Verdikt na uživatelovy přístroje: **USB logic analyzer = jen monitor** (je input-only, TCK/TMS nevybudí);
  **Bus Pirate = ano** (je v seznamu adaptérů); **Raspberry Pi / Pico = nejlepší** (bcm2835gpio/sysfsgpio,
  resp. CMSIS-DAP). **Před připojením změřit napětí padů** — BF70x I/O může být 1.8/2.5/3.3 V a Pi ani
  Bus Pirate v3 nejsou 1.8V tolerantní.

**Guardrails:** nikdy neposílat konzolový typ `0x15` (formátuje NAND); neinstalovat ani neupravovat engine/firmware.
  Relé použít pouze jako skutečný power cut; nejprve pilotně ověřit opětovný boot a remount. Nezaznamenávat 20s
  odhad jako naměřenou vlastnost.

> Starší oddíly níže jsou historické poznámky a obsahují zastaralý stav, počty bajtů i plán obnovy. Před dalším
> oracle pokusem se řiď tímto blokem a aktuálními §§66.90–66.93, nikoli starými kroky 0–9.

## Nejnovější transportní zjištění (2026-10-11) — historický kontext

**USB SysEx funguje.** Chyběl `$00` StateSync client hello s verzí protokolu 6 před `$51`.
Během delší relace je nutné opakovat **oba** keepalive: `$00` i `$52(active=0)`.
`~/.opz-decode/toolkit/opzpull.py` nyní stahuje přes USB; BLE není potřeba.

V `~/.opz-decode/pulled/settings/` jsou `plugs.json` (4 423 B, 23 částí) a
`slotConfiguration.json` (759 B, 4 části). Opakované kompletní čtení má stejné SHA-256;
finální příznak i JSON ověřeny. `settings/plugPresets.dat` a testované audio cesty zatím
nevrátily část 0, přestože kontrolní čtení obou JSON na konci dlouhé relace fungovalo.
To není důkaz neexistence souborů; `$35` není obecný filesystem export.
Aktuální seznam a příkazy: `~/.opz-decode/STATUS.md`, `~/.opz-decode/PULL_RUNBOOK.md`.
Starší tvrzení o nefunkčním USB a nulovém počtu stažených souborů už neplatí.

## Tovární samply — nové hledání (2026-10-11)

**Další originální audio zatím nezískáno.** Aktuální Mac app `1.3.1`/build `494` obsahuje
v prověřených cestách metadata, ne AIFF audio; Unity assety nemají `AudioClip` ani `TextAsset`.
Nová konkrétní stopa: přímý RE článek z 2019-01-03 uvádí skutečné samply ve staré iOS appce.
Příslušné IPA/backup ale nemáme; veřejné content backupy mají jen nulové `~*.aif` markery.
[Tovární samply: důkazy a blokace](FACTORY_SAMPLES_RESEARCH.md). Na zařízení se nic nezapisovalo.
Starší kategorické tvrzení „na internetu ani v appce nejsou“ není podložené.

## 0.0 STARŠÍ STAV (2026-10-11 01:15) — historický kontext oddílů 0–5

**Boot do aplikace funguje, content mode se připojí; zvuk a PLAY jsou otevřené.** Detaily:
`FIRMWARE_ANALYSIS.md` §66.26–§66.70; verdikty v `HYPOTHESES.csv` (265 řádků).

| Co | Stav |
|---|---|
| Boot do aplikace (animace, UI, TRACK) | **funguje** — recept i jeho past: §66.67 |
| Update mode + příjem updateru | funguje (každý zápis ověřen konzolí `extract: last N/N -> COMPLETE`) |
| Content mode (disk se připojí) | funguje |
| Zvuk (bubny 13/14/15/17) | **tichý** — plugy mají `samples`, které se nerozřeší (§66.68) |
| Sample packy na zařízení | registrované: `used sample memory: 3683 kB` (3594 kB packy + 89 kB `.engine`) |
| PLAY | **stále padá** — `RETX 0x80117baa`, ale crash record je tentokrát jen AIFF retry smyčka |

### Tři pravidla, která teď platí (draze zaplacená)

1. **`samples` bez funkční cesty je horší než prázdné `samples`.** Prázdné znamená tolerované ticho;
   neřešitelné znamená nekonečnou smyčku `yaffsfs: yaffs: error: ENOENT` + `libaiff: AIFF_ReadOpen
   failed`, která přepíše celý log ring (poslední boot: 609 řádků smyčky a **nula** řádků bootu) a
   nechá null sample objekt, na kterém PLAY spadne ve stejné funkci jako dosud (§66.68).
2. **Cesta uživatelského sample packu musí obsahovat `samplepacks/user/`.** `SampleLoader::loadSamples`
   (@0xdcfcc) otevírá řetězec **doslova** (`AIFF_OpenFile(path,1)`) a jediné, podle čeho ho
   klasifikuje, je substring `samplepacks/user/` (§66.69). Samotné `redmountKicks.aif` se tedy nikdy
   nerozřeší.
3. **`samplepacks/user/` je adresář uživatelského plugu** — patří tam obojí: `<plugid>.engine` (engine
   modul, na kterém stojí boot fix §66.26) **i** `<name>.aif` (audio plugu). Nepoužité packy tam
   garbage collector maže (`Content::cleanUnusedSamplepacks`), takže bez reference z plugu nepřežijí
   (§66.69).

**Dál platí:** nikdy nepsat do osmi továrních pack adresářů (`samplepacks/<track>-<name>/…`) — updater
neumí mazat, jen zapisovat; content disk neobsahuje `settings/` ani `engines/` a při vysunutí interní
soubory smaže (obnova = `uv run --python /tmp/opzuv/bin/python toolkit/opzfix.py`); zápis přes updater
se projeví až v dalším power cycle; **nikdy neposílat konzolový typ `0x15`** (NAND format, §1).

### Co se právě dozvědělo (A/B test `samples`, §66.71)

- **Ani jedna forma cesty nefunguje** (`samplepacks/<name>.aif` ani `samplepacks/user/<name>.aif`):
  zvuk žádný, AIFF retry smyčka běží dál, PLAY padá.
- **Rozhodující negativní důkaz:** `Calculating used sample memory` zůstalo na **3683 kB** i po zapsání
  3,6 MB `.aif` do `samplepacks/` a `samplepacks/user/`. Ty cesty tedy **nejsou** úložiště samplů;
  počítané (a tedy hledané) je jen to, co leží ve **slot složkách** `samplepacks/<track>/<slot>/`, kam
  píše výhradně content-disk import. `samples` **nemůže být volná cesta**.
- **Ověřeno:** plugy 38 (`tapetwo`) a 43 (`fdnreverb`) `fxmanager: Couldn't find plug with id 38/43`
  skutečně odstranily (0 výskytů vs. 6 v předchozím bootu).
- **Třetí null offset téhož faultu:** update-mode/second-phase boot dal
  `iid 0x00130026`, `DCPLB_FAULT_ADDR 0x00000220`, `RETX 0x80117baa`, rámce
  `0x8002c438, 0x11a03838, 0x11a02586, 0x0800b71c` (dřív 0x0 při bootu, 0x2c0 při PLAY).
- Cesta, kterou loader zkouší otevřít, **není v žádném logu** (`AIFF_ReadOpen failed` ji netiskne).

### Porušené pravidlo a opravený postup

Oba payloady z 2026-10-11 porušily pravidlo §66.51: **hostitelský `settings/plugs.json` patří
zařízení, ne nám** — přepsal vazbu bubnů na naimportované packy a přepnul je na sampler plugy s
neřešitelným `samples`. Dokumentovaný stav, ve kterém bubny hrály, byl **content-disk import + rebuild
zařízení, bez našeho plugs.json a slotConfiguration.json**. Správné pořadí:

1. **content mode: mount + eject** → zařízení si samo přestaví plug tabulku a přiváže packy
   (registrované jsou dál: 3683 kB). Nový `import.log` zapíše `assigning …` řádky, které řeknou, co
   přesně přivázalo — a tím i skutečný tvar `samples`.
2. **updater payload:**engines ve všech třech umístěních + `config/general.json`
   (`disable_start_sound`) + `config/dmx.json`, **bez** `settings/plugs.json` a **bez**
   `settings/slotConfiguration.json` (eject stripuje `/yaffs2/user/engines/`).
3. boot → čekej normální boot **a** zvuk bubnů; PLAY zůstává otevřený.

Kdyby krok 1 nechal bubny tiché, další krok **není** další hádání payloadu, ale přečíst zařízením
psaný `settings/plugs.json` přes file sync appky (fileId 1).

### 0.0b BLOKACE (2026-10-11 02:30) — stahování souborů ze zařízení

Cíl „stáhnout ze zařízení vše potřebné přes SysEx file service" **není splněn**: v `~/.opz-decode/pulled/`
je **0 souborů**. Nářadí je hotové a read-only (`toolkit/opzpull.py` po USB, `toolkit/opzble.py` po BLE-MIDI;
posílají jen `$51`/`$33`/`$35`). Změřeno:

- **USB:** jednotka odpovídá na MIDI identitu (`X3CJN79E`, `1.2.45+`) a vysílá `clock`, ale **žádný TE SysEx**
  — 300 s s `$51` každých 15 s a `$33` heartbeaty = 0 rámců; i `midi-config`/`pattern` query timeoutují.
  Vlastní log zařízení přitom ukazuje `fileclient: FileClient: send connection request to server 16962`
  (= náš `0x4242`), takže advertisement dostane a odpověď po USB neputuje.
- **BLE:** jediný transport, který v jeho logách kdy fungoval (`command_handler: BLE advertising on`), ale
  advertising běží jen **1–4 s** (log: `on` → `off`) a v našich skenech se neobjevil; hostitelský BLE je
  navíc nespolehlivý (`BleakBluetoothNotAvailableError(powered off)`).

Na pozadí běží tři hlídače (read-only), které to dokončí samy: `/tmp/pull_watch.sh` (content mode → USB,
pak BLE), `/tmp/ble_auto.py` (BLE endpoint → `opzble.py --address`), `/tmp/usb_retry.sh` (každých 10 min
60 s USB pokus). Runbook: `~/.opz-decode/PULL_RUNBOOK.md`.

**Co je potřeba od člověka (stačí jedno):** otevřít OP-Z appku a nechat ji synchronizovat (pak vypnout —
zařízení začne inzerovat BLE), nebo zapnout jednotku s podrženým TRACK (content mode), nebo povolit
Bluetooth terminálu / spárovat BLE-MIDI v Audio MIDI Setup, případně odpojit USB (hypotéza: advertising
může být při USB potlačený).

## 0. Starý stav projektu — nahrazen aktuálním předáním nahoře

Následující tabulka a kroky v oddílech 0–9 pocházejí ze starší fáze; neříkají aktuální počet bajtů ani další krok.
Aktuální oracle target je samostatný `bootloader.ldr` člen, jeho pokrytí je **811 komprimovaných / 156,306 B** a
stav relay automatizace je uveden v aktuálním bloku na začátku souboru. Zařízení ani jeho USB připojení nebylo
v tomto handoveru znovu ověřeno.

## 1. Guardrails (přečti před prvním příkazem na zařízení)

**Konzole v update módu je root shell zařízení, ne log sink.** Proto:

- **Bezpečné (čistě čtecí) typy: `0x00` ping, `0x02` version, `0x07` metadata, `0x35` verze + `chip_id`.**
  Posílej pouze tyto, dokud si nepřečteš §22 a §28.
- **Typ `0x15` je NAND format.** Jedno odeslání formátuje celý NAND – přesně tohle zařízení bricklo.
  Toto je tvrdý guardrail: neposílej ho ani jako součást „wipe-then-install“ (ověřeno, že to nefunguje, §9.1).
- **Neznámé typy neprozkoumávej hromadně.** Typový prostor je zmapovaný (§22, §28, §54) a vrací jen
  uvedené typy; sweep nepřinese nic nového a obsahuje destrukci.
- **Root získává jen uživatel.** Jednorázový dvojklik na `~/Desktop/OP-Z-unstick.command` (Zeptá se na heslo
  a nainstaluje pravidlo pro `opzload`). Obchvaty typu instalátor, `authorizationdb` nebo zápis do
  `/etc/sudoers.d` nepoužívej.
- **Bootloader komponentu nezapisuj**, dokud nejsou známé názvy a verze komponent (viz cesta B v §64.3).
  A/B sloty sice dělají špatný zápis obnovitelným, ale je to poslední nevratná věc na zařízení.
- **Farmu nerestartuj uprostřed cyklu.** `launchctl kickstart -k` v momentě, kdy má farma nastagedováno a
  ejectnuto, nechá medium pryč (§63.2, §54.2).
- **Log `~/.opz-decode/opzfarm.log` je důkaz**, ne scratch buffer. Opravuj jen přidáním datované `NOTE`,
  nikdy mazáním. Testy, které sáhnou na farmu, musí umlčet `F.log = lambda m: None`.
- **Crash logy čti Pythonem**, ne `grep`em – obsahují nevalidní UTF-8 a `grep` na nich tiše nic nenajde (§25).

## 2. Nejdřív si ověř stav (nedělej nic destruktivní, dokud tohle neprojde)

```bash
# Je zařízení na busu?
ls /dev/cu.usbmodem* 2>/dev/null; ls -d /Volumes/OP-Z* 2>/dev/null; ioreg -p IOUSB -w0 | grep -i 'OP-Z'

# Stav farmy a dekódování
tail -5 ~/.opz-decode/opzfarm.log
~/.opz-decode/opzuv/bin/python -c "import json;d=json.load(open('/Users/jakubkolcar/.opz-decode/opzfarm_state.json'));print(len(d['bytes']),'bytes, cycles',d['cycles'],'pending',len(d['pending']))"

# Zdraví stacku (17 testů, musí být 17 passed 0 failed)
bash /tmp/opzcheck.sh 2>&1 | tail -3
```

Když medium chybí: požádej uživatele o jedno stisknutí PLAY (nebo odpojit/připojit). Toto je jediná věc,
kterou za něj neuděláš.

## 3. Co je už dokázané (nesnaž se to znovu odvozovat)

**Hardware a formát**

- `.zfw` = AES-256-CBC, společný klíč pro všechny verze, `key index 0xFF` na offsetu `0x04` (slot v OTP),
  IV 16 B na `0x70`, plaintextová délka u32 LE na `0x080`, šifrovaný název 256 B na `0x300`, archiv od `0x400`.
- Klíč **není** v souborech ani na hostu: 73,8 M kandidátů bez hitu (§55), v aplikaci není AES S-box,
  online není publikován. Rez wiki i Reddit říkají jen „stejný klíč pro všechny verze“ – žádný klíč nenavrhují.
- Engine blob = 16B hlavička (`0x11a00000` na offsetu 4, velikost payloadu na 12) + plain Blackfin kód (§43, §44).

**Dva funkční primitivy**

- **Write primitive do interního FS.** Plain zip pojmenovaný `firmware_bin_only_with_bootloader.zip` v rootu
  volume; cesty entry jsou relativní k `/yaffs2/upgrade/` a **přesně jedno `..`** dosáhne `/yaffs2/`
  (např. `../user/settings/plugs.json`). Jedno nezapisovatelné entry zabortí zbytek archivu. Ověřeno na
  `/yaffs2/user/{settings,engines}/` – obojí je zapisovatelné (§24).
- **Console oracle = chosen-ciphertext CBC okno.** Do pole na `0x300` vlož ciphertext payloadu od offsetu X
  a do IV (`0x70`) blok z X−16; bootloader vypíše plaintext na X. Print je `%s`, takže se zastaví na prvním
  NULu; maskováním IV o `0x01` se NUL posune a výtěžek roste (44 → 161,7 B/probe). Cena: jeden scan za okno.
- **Autonomní reboot (jediný, ověřený).** Úspěšný upgrade sám resetuje jednotku: po `successfully upgraded to 1.2.45`
  zařízení naběhne do OS, ten spadne a bootloader se vrátí do update módu s novým zapisovatelným volume. Ověřeno
  end-to-end bez zásahu uživatele (stage → eject → upgrade → medium zpět → stage dalšího probe, §65.5). Konzolový
  příkaz na reboot **neexistuje** (§65.9).
- **Oraclové okno je ověřené proti ground truth.** Okno na zip offsetu 1490319 se po unmaskování rovná seedovaným
  bajtům `c3 ad 1d 00 …`; base `0x400`, pravidlo „IV = předchozí ciphertext blok“ i maska jsou potvrzené.
  **Maska je `XOR 0x01`** (nikoli odečítání 1), §65.7.
- **První entry archivu** (z 142 ověřených bajtů): `PK\x03\x04`, ver 20, flags `0x1ec0`, method 4 (pozor: method 4 **není** deflate – to je §66.7, a flags `0x1ec0` je pro zip neplatná kombinace), a hned od offsetu 30 jdou vysokoeentropická data. **Pozor:** odvození „název entry je prázdný / CD není v tailu“ stojí na nezarovnaných čteních a je zrušené (§66.1, §66.8).
  > **VYVRÁCENO 2026-10-10 (§66.12):** první korektní čtení dalo `PK\x03\x04 | ver 20 | flags 0x0000 |
  > method 8 (DEFLATE) | 2022-03-31 14:03:04 | crc 0x3c689c47`. Starý seed s `c0 1e 04 …` byl **ručně
  > vložená konstanta**, ne pozorovaná data – obsahuje NUL bajty a parser, který se na NUL zastaví, ji
  > vyrobit nemohl. Archiv je **běžný pojmenovaný zip**; central directory na konci je tím pádem nejlevnější
  > živá cesta (§64.3, §66.12) a ground truth v `opzfarm.py` je 20 ověřených bajtů.
- **Log buffer zařízení zastropuje únik na 65 bajtů na okno (změřeno, §66.3).** Framy mají strop 128 B payloadu (1253 framů v `opzraw3.bin`, max 128; pravý upgrade max 103) a únikový frame sedí přesně na něm: `4 (tick) + 58 (text) + 65 (jméno) + 1 (NUL) = 128`. **Maskování IV tedy nemůže zvýšit výtěžek** – strop je ~65 B/okno bez ohledu na masku.
- **Archiv přesně sedí na `0x400`:** `0x400 + ceil(1490575/16)*16 = 1 491 600` = přesná velikost souboru, takže payload ciphertext je zbytek souboru doplněný na 16 B.
- **Enginy jsou loader streamy, ne plochý image** (21/21 projde jako 16 B Blackfin bloky `code,dest,count,arg` a každý končí přesně na EOF; `dest[i+1] == dest[i]+count[i]`), takže `0x11a00000` je cíl (L1 SRAM), ne magic, a `RETX − base` **není** offset v souboru; ani jedna crash adresa neleží v rozsahu žádného enginu → crash je v OS/L1 kódu, ne v pluginu (§66.6).

**Updater**

- Přijímá i **nešifrovaný** zip (žádné `detected encrypted file`) – to je host-controlled cesta do updateru (§23).
- Bez `ble firmware file` skončí na `upgrade not compatible with this device` – název komponenty neznáme (§23).
- Bootloader má **dva A/B sloty** a střídá je (`wrote bootloader to index 1` / `index 0`, §27).
- `keyboard` je PSoC a zapisuje ho OS po startu po řádcích; `ble` je identické ve všech 7 archivech, proto
  se vždy hlásí `Already installed`.

**Příčina bricku a proč nic nezabralo**

- NAND format přes `0x15` zničil boot state a uživatelský strom; OS pak spadne v NULL dereferenci
  `ADI_EXC_DATA_CPLB_MISS`, `DCPLB_FAULT_ADDR 0x00000000`, `RETX 0x80117baa`, hned po `load general config`.
  Na 1.1.12 stejná třída, jiná adresa (`0x8010ea52`).
- ~~Crash je **invariantní** vůči všemu, co jde z hostu dodat: engine binárky, `slotConfiguration.json`,
  `general.json`, kompletní `plugs.json`, arpeggiátory, a vůbec celému uživatelskému stromu (§25.2, §28).~~
  **VYVRÁCENO 2026-10-10 (§66.25–§66.26):** engine binárky zapsané přes updater do `samplepacks/user/`
  spolu s `general.json` pád posunuly (data-read během initu → NULL call po 9 s běhu aplikace). §25.2/§28
  měřily tehdy bez enginů, takže tenkrát nic vidět nemohly. Zbývá `settings/plugs.json` — viz oddíl 0.0.
- Přepsání **všech** firmware komponent z genuinního archivu (os, content, oba bootloader sloty, PSoC) crash
  nezměnilo (§27). Content mode běží stejný OS úspěšně – protože přeskočí `loadSettings`/`SynthInit`/`sequencerInit`.

## 4. Co je vyvrácené (neopakuj)

Console: typový prostor (§22, §28), NAND sousedství `0x14`–`0x19` (§54), routing byte sweep (§40), factory mode
`0x09`+`0xF0` (§28), DFU `0x29`, malformed input, USB request space celý (standard, class, vendor, CDC, Bulk-Only)
(§38–§42, §60), reset přes re-enum/port reset/BOT reset/DTR, média-load bez roota (§30).
MIDI cesty (`$62`, `$66`, `$09`) jsou nedostupné – OS spadne před `MidiInit`.
Host repair přes content disk je vyčerpaný: `samplepacks/` je export-only, `config/` umí jen přepsat existující
soubor (výjimka `userPresets.dat`), `engines/` se maže (§16–18).
Klíč: wordlisty (rockyou 14,34 M × raw16/raw32/md5/sha256), wordlist × mangling rules (932 358 078
kandidátů, §64.1.1), KDF matice (PBKDF2/HKDF/repeated-SHA256, salty = IV/filename/version/zero-pad),
73,8 M binárních oken z APK a engine blobů – vše bez hitu (§55, §64.1.1). Zbývá jediná varianta:
word → PBKDF2/scrypt/argon2 (stage 2/3, nástroj `~/.opz-decode/opzstage1.c`, self-tested).
Exhaustivní brute force je uzavřený i matematicky (§64.1): jeden kandidát = jeden AES blok (96 ns), a zrychlení
kupuje `log(X)/log(95)` znaků, tedy tisíc-GPU farma kupuje méně než 3 znaky.

**Nově vyvrácené (2026-10-10, ověřeno měřením – neopakuj):**
- **Update volume je volatilní** – přebuduje se při každém bootu. Marker i staged probe po power cycle zmizí (dvakrát,
  s kontrolním souborem), zatímco čtení samo staged soubor nespotřebuje. Cesta A (zachytit zapisovaný plaintext) je
  mrtvá ve všech variantách, §65.1.
- **Jedno čtení firmwaru na boot je politika firmwaru.** 16 probe + 16 stisků → 1 čtení; 8 probe + 1 eject (a
  `invalid dir` = 0, tj. adresář zdravý) → **také 1 čtení**, zbytek kandidátů odmítnut s `didn't find firmware file`,
  §65.3. Multi-window trik neexistuje.
- **`invalid dir` není od `._` sidecarů** (disproved) – je to efekt počtu souborů: 1 a 8 souborů → 0, 16 souborů → 906, §65.4.
- **Root media-load nevrátí medium.** S rootem: `CLAIMED interface 2`, INQUIRY/REQUEST SENSE/ALLOW MEDIUM REMOVAL a
  oba START STOP UNIT `status=0`, ale `TEST UNIT READY` je **před i po** `status=1` (CHECK CONDITION), žádný disk ani
  volume se neobjeví. „No medium“ zruší jen reboot, §65.8.
- **Probe, který leakuje, nemůže zároveň rebootovat.** Název se používá jako jméno souboru na FAT, únikové bajty
  (< 0x20) jsou nelegální → zápis selže → žádný extract ani upgrade; vypisované jméno se navíc ořezává na 37 bajtů,
  takže strop je ~32 B, ne ~208, §65.6. Autonomní leak loop je tím vyloučený.
- **Konzolový reboot příkaz neexistuje** – nezávisle potvrzuje clean-room projekt `op-z-sysex`
  (`docs/host-write-persistence.md`: „No safe software reboot command has been established.“), §65.9.

**Vyvráceno druhým review (2026-10-10, ověřeno proti uloženému kódu a dochovaným rawům – viz §66):**
- **Nezarovnaný oracle = pseudonáhodné bajty, ne payload.** `craft()` bere ciphertext od `0x400+idx` bez zarovnání;
  funguje jen `idx % 16 == 0`. Uložená mapa má **308 z 327 bajtů (94 %) na nezarovnaných offsetech** (celý běh
  30..82 i 256B běh 1490063..1490319), takže §65.7 byla kruhová „verifikace“ a §65.10 („CD není v tailu“) je
  **neplatné**. Čitelná okna: `16*floor(idx/16)`; poslední úplné 256B okno začíná **1490320**, poslední dva bloky **1490544**.
- **Parser framů je vadný:** `parse_cycle()` neodstraňuje `7D` escape a zastavuje jen na `C0 2E 04`, ale routing
  `0x1E` je běžný (151 ze 170 framů), `0x2E` vzácný (19) – frame header se tedy může vsáknout do okna a posunout
  všechny další offsety.
- **`zip_walk()` hard-coduje předpoklad bezejmenného archivu** („local header has a N-byte name“) – validátor
  nemůže validovat běžný zip; neznámé offsety se plní nulami a z nich se pak tisknou hlavičky. Byte coverage
  **není** důkaz správnosti.
- **`advance()` maže neznámé bajty** – posunuje start intervalu i když probe nic nepřineslo; v uloženém stavu už
  chybí `19,20,21,82,83,84,1490323-1490325`.
- **Plochý engine image neplatí** (§66.6) a **method 4 není deflate** (§66.7).

## 5. HISTORICKÁ ROADMAPA — NEPOUŽÍVAT; nahrazena plánem pro bootloader oracle

Následující stará cesta k OS image/central directory je zastaralá. Aktuální cíl a kroky jsou v úvodním předání a
`PLAN_OPZ_BOOTLOADER_ORACLE_AUTOCYCLE.md`.

Cesty A (zachytit zapisovaný archiv) a C (root media-load) jsou **mrtvé** (§65.1, §65.8), multi-window neexistuje
(§65.3) a **každý únik má strop ~65 B na jedno power cycle** (§66.3) – maskování IV nepomůže. Cena plného decode je
tedy `1 490 575 / 65 ≈ 23 000` oken ≈ 4× víc, než uváděly starší odhady (5 800–9 000), tj. 64–96 h nepřetržité
interakce. Cokoliv, co bylo počítané na 256 B/okno, je špatně. **Ale cíl se zmenšil:** nemusíme číst celý
archiv – stačí central directory (~desítky oken) a pak jeden member (OS) cíleně.

**Nic z toho se nemá spouštět, dokud není hotový krok 0.**

| # | Krok | Cena | Co rozhodne |
|---|---|---|---|
| **0** | **Offline oprava dekodéru** (zarovnání, framy, `zip_walk`, `advance`) a přestavba mapy s proveniencí; `~/.opz-decode/toolkit/opzframe.py` to už umí | 0 (bez zařízení) | nic dalšího není důvěryhodné, dokud tohle neprojde; starou mapu zachovat jen jako důkaz |
| 1 | **Přečíst payload okno 0 zarovnaně** | 1 power cycle | rozsoudí §66.8 (je seed splice, nebo pravý payload?) a doplní hlavičku prvního entry (`csize`,`usize`,`namelen`,`extralen`) |
| 2 | **Přečíst zarovnaný tail** (1490320, 1490544) | pár cyklů | existuje-li central directory a kde; tím se vrací cesta §64.3 |
| 3 | Plný decode | ~23 000 power cycle | plaintext OS image → přesná faultující instrukce |
| 4 | Vysypat externí **SPI flash** (clip, CH341A) nebo TE service | programátor / servis | klíč nebo boot state → lokální decrypt, resp. oprava jednotky |

Detail: `FIRMWARE_ANALYSIS.md` §66.10. Decode sám jednotku neopraví – opravu řeší TE service nebo bench/NAND
restore; decode slouží k pojmenování faultující instrukce.

## 6. HISTORICKÝ experimentální runbook — aktuální collector je `toolkit/opzbootprobe.py`

Před oracle cyklem použij aktuální collector a plán v úvodním bloku; následující příkazy (`opzfarm`, starý CAP_SECS
runbook) patří k předchozí iteraci a nejsou aktuálním postupem.

Postup je vždy: nastage → eject → odposlechnout konzoli → přečíst crash log. Farma to dělá automaticky,
ruční varianty jsou v `~/.opz-decode/known_structure.md` a v poznámkách k `opzq.py` / `opzmask.py`.

Pravidla, která se nevyplácí obejít:

- Zařízení čte staged soubory **do ~3 s po ejectu**; capture window proto `CAP_SECS = 45` a každý raw capture
  se ukládá do `/tmp/opzcap_cycleNNNN.bin` (posledních 40).
- **Content-mode boot mezi dvěma pokusy zničí experiment** – jeho `Syncronizing …` fáze přepíše interní strom.
  Probe se čte jen obyčejným bootem (§24).
- Po abortu je medium pryč a **probe soubor je spotřebovaný** – další pokus začíná power cyclem.
- Payload stavěj Pythonem (`zipfile`), ověř `testzip()`, pojmenuj přesně
  `firmware_bin_only_with_bootloader.zip`, a před ejectem smaž AppleDouble sidecary (`._*`).
- `openssl`/`grep` na binární logy nepoužívej, viz guardrails.
- **Jeden firmware read na boot.** Nestageuj víc probe s očekáváním víc čtení (§65.3); 16+ souborů navíc rozbije
  device scan (`invalid dir`, §65.4).
- **Nikdy nečekej, že soubor na update volume přežije boot** – volume je volatilní (§65.1).
- **Offset počítej jako `0x400 + zip_offset`** a masku aplikuj `XOR 0x01` na IV (a stejně ji sundej), §65.7.
- **`/tmp/opzload` vrací exit 0, i když medium nepřijde** – čti `TEST UNIT READY` status, ne exit code (§65.8).
- Autonomní cyklus jde jen přes **úspěšný upgrade** (stage platný archiv → eject → jednotka se sama resetuje a medium
  se vrátí, §65.5); leakující probe tudy projít nemůže (§65.6).
- **Okno čti jen zarovnané na 16 B** (`16*floor(idx/16)`) a framy dekóduj `opzframe.py` (odstraň `7D` escape, ber
  celý frame) – jinak dostaneš pseudonáhodné bajty, které se opakováním tváří jako ověření (§66.1, §66.2).
- **Neúnikuj víc než ~65 B z okna** – zařízení má 128B log buffer (§66.3).
- **Nepoužívej seedovanou mapu ani `zip_walk()` jako důkaz** – 94 % původní mapy bylo z nezarovnaných čtení a `zip_walk()`
  předpokládal bezejmenný archiv (§66.4, §66.5).

**Review-2 patch je aplikovaný (§66.11).** Co se změnilo v praxi:
- `opzfarm.py` už okna zarovnává, dekóduje framy (včetně `7D` escapů), respektuje 128B log cap (neúnikuj/e
  vymyšlený terminátor se neukládá), nechává missnuté intervaly v práci a **nepřepíná masku**.
- `GROUND_TRUTH` má jen 19 zarovnaných bajtů okna 0 a je označená jako **PROVISIONAL**; `handle_mismatch`
  zahodí a přezařadí, ale nic nevypíná.
- `opzassemble.py` tiskne neznámá pole jako `unknown` (ne vymyšlené nuly), příjmá pojmenované entry a píše
  `/tmp/opzfarm_known.bin` (maska pozorovaných bajtů) + `ZIPENTRY:` řádky s názvy komponent.
- **Mapa je přestavěná s proveniencí**: 327 → **19 bajtů** (zahozeno 308 nezarovnaných), 6 intervalů se zarovnaným
  startem, zbytek = 1 490 608 B. Původní stav je v `~/.opz-decode/opzfarm_state.pre-review.json`.
- Ověřeno `bash ~/.opz-decode/opzcheck.sh`: **14 pass / 3 fail**, a ty tři jsou jen zastavená farma (launchd +
  proces + hash stamp). Simulace (e2e, deliverable, success) a codec self-test procházejí. **Zařízení to ale
  ještě nevidělo** – první reálné zarovnané čtení je i test §66.8.

## 7. Staré interakční poznámky (historické)

- Uživatel **řídí projekt ručně** a očekává konkrétní důkazy: počty bajtů a řádky logu, ne vyprávění o procesu.
- Fyzické úkony, které za něj nejde udělat: stisknout PLAY (probudí medium), držet power (zabití upgradu),
  jednou zadat heslo pro root media-load, případně otevřít jednotku kvůli SPI flash.
- Bylo mu řečeno, že cesta 3 a 4 jsou další krok; při navazování se drž toho, co je v §64.7, a neboj se
  přiznat, co nevyšlo – tón předchozí komunikace je věcný a bez lakování.

## 8. Nástroje (kde co je)

`/tmp` se na macOS maže, proto je trvalá sada v `~/.opz-decode/`; `run.sh` ji umí obnovit do `/tmp`.

| soubor | co dělá |
|---|---|
| `~/.opz-decode/toolkit/opzframe.py` | **nový**: korektní frame codec (C0/routing/type/len, `7D` escape), funkce `leaks()`, a zarovnaný `craft()`; self-test nad reálnými capturey |
| `~/.opz-decode/opzsim.py` | **nový**: věrný simulátor zařízení (framing + escapy + 128B cap), používají ho testy |
| `~/.opz-decode/opzfarm_state.pre-review.json`, `opzfarm_map.pre-review.json` | **záloha původního stavu** před review-2 migrací (jen jako důkaz) |
| `~/.opz-decode/toolkit/opzharvest3.py` | průběžný odposlech konzole, raw capture + parsované úniky do JSON |
| `~/.opz-decode/toolkit/opzpeek.py` | vypsání volume s timeoutem – nikdy nezablokuje (používej na wedged volume) |
| `~/.opz-decode/toolkit/opzmulti.py` | stage N probe → 1 eject → počítá čtení a `invalid dir` (multi-window test) |
| `~/.opz-decode/toolkit/opztest.py` | leak+reboot probe (name blocks 1,2,15 genuinní) – dokázal, že to nejde |
| `~/.opz-decode/toolkit/opzloop.py` | autonomní cyklus přes úspěšný upgrade (jediná funkční autonomie) |
| `~/.opz-decode/toolkit/opzloop2.py` | totéž s media-load cestou (mrtvá, ale zachováno pro referenci) |
| `~/.opz-decode/opzstage1.c` | stage 1 passphrase sweep (932 M kandidátů, self-tested) |
| `~/.opz-decode/opzfarm.py` + `test_*.py` | orákulum farma (launchd `com.opz.decode`) a testy |
| `~/.opz-decode/opzassemble.py`, `opzanalyze.py` | assembler + analyzér dekódované mapy |
| `~/.opz-decode/wordlists/{rockyou.txt,best66.rule}` | wordlist + hashcat rules |
| `~/.opz-decode/refs/op-z-sysex/` | clean-room dokumentace (framing, message families, „no reboot command“) |
| `~/.opz-decode/opzload` + `opz-sudo-install.sh` | SCSI media-load nástroj a jeho (opravený) instalátor |
| `~/Desktop/OP-Z-{STATUS,unstick,CAPTURE,CHECK}.command` | uživatelské skripty |

**Farma je záměrně zastavená** (`launchctl bootout`), aby neinterceptovala volume při experimentech. Obnovení:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.opz.decode.plist
```

Stav dekódování: 327 bajtů z 1 490 575, `cycles=3`, 4 pending intervaly, 142 ground-truth bajtů ověřených hardwarem.

## 9. Otevřené otázky

- Hlavička prvního entry (`namelen`, `csize`, `usize`) a počet entry – řeší krok 1 v §5.
- Je seed `50 4b 03 04 …` skutečně payload, nebo splice frame headeru? – rozsoudí krok 1 (§66.8).
- Existuje central directory a kde – řeší krok 2 (§66.1).
- Názvy a verze komponent pro plain-zip cestu (updater je hledá jako `ble firmware file`, §23).
- Přesná faultující instrukce na `RETX 0x80117baa` (potřebuje OS image a mapu blokových destinací, §66.6).
- Zda je v externím SPI flash klíč nebo boot state.

## 10. Nové (2026-10-16) — §66.106

- **Early-stop test klíče je hotový.** `toolkit/opzbootprobe.py` po každém probe re-influje prefix `bootloader.ldr`
  a testuje každé nové 32bajtové okno přes `opzkeymine.check()`. Při nálezu zastaví běh a zapíše `KEY-FOUND.txt`.
  Nový přepínač `--key-scan-only` spustí stejný sken nad uloženým stavem **bez zařízení**. Offline běh: 1 260
  inflovaných bajtů, 1 229 oken, žádná shoda — souhlasí s §66.101.
- **§66.101 páka 2 (alignment) je stažena.** Změřené úniky: 35 čtení, jen 14 dosáhlo stropu, průměr 40,9 B; po
  vyloučení 7 známých zaseknutých čtení (masked-NUL, offset 467808) je průměr ~49,6 B, tedy **uvnitř** pásma 49–64.
  Rozdíl proti 43 novým bajtům je povinný 16bajtový přesah. Žádná hlava k získání neexistuje; zůstává ~3 615 probů.
- **První disassembly prefixu bootloaderu.** 1 260 bajtů = 2 celé LDR bloky + částečný třetí.
  - blok 1 na `0x11800000` **není kód** — je to tabulka 23 IEEE-754 floatů (512,0; 12,5; 7 800,0; 105,0 …) do L1 Data SRAM;
  - blok 2 na `0x11a00000` je kód: 341 instrukcí, **0 nedekódovatelných bajtů** (první čisté ověření Ghidra
    blackfinplus jazyka na reálném bootloaderu OP-Z). Obsah: systémové MMR, test boot-mode pole
    `0x20000004 & 0xf00 == 0x300`, CGU/PLL rutina v `0x11a00118`, nastavení řadiče v `0x11a001f0`;
  - `arg` bloku 0 = `0x109c` = 4252 = 124 + 16 + 4112 → **offset další hlavičky**, potvrzeno aritmeticky.
- **Odpověď na otázku odbrickování:** v obnovených 1 120 bajtech **není žádná NAND / partition-map / bad-block
  logika**. Volání míří na `0x11a005a6` až `0x11a00f00`, tedy ~72 % bloku ještě chybí. Otázka „přestaví loader
  zformátovanou NAND?“ zůstává otevřená, ale je nyní **lokalizovaná v tomto memberu** — odpověditelná dalším
  sběrem bez klíče, bez hardwaru a bez zápisu do zařízení.

## 11. Nové (2026-10-16) — §66.107: sběrač po pěti revizích

- **63bajtový strop úniku je konstanta zařízení**, ne naše chyba: 79 zachycení, 75 461 rámců, maximum
  všude přesně 128; rámec = 4 (tick) + 58 (prefix s časem) + 65 (data) + 1 (NUL), z toho poslední dva
  bajty jsou marker `..` zařízení → **63 skutečných bajtů**. 17 rámců na 128 končí `..`, 27 pod 128
  nikdy — nula falešných poplachů.
- **Detekce tichého poškození:** `check_prefix_stable` (v rámci procesu) a `check_prefix_persisted`
  (digest `plaintext-prefix.json` přes restarty). DEFLATE je prefix-stabilní, takže pozdější probe smí
  jen přidávat; každá změna prefixu znamená chybně dekódovaný bajt. Toto je kontrola, která by odhalila
  chybu masked-NUL (§66.89) okamžitě. Ověřeno na reálném prefixu převrácením jednoho bajtu → divergence
  na inflovaném offsetu 141. Rozbíhající se prefix nikdy nepřepíše dobrý digest.
- **Návratové kódy:** 0 = klíč nalezen, 3 = rozsah dokončen bez klíče, 2 = neúplný, 1 = chyba.
- **Regresní test nad skutečnými daty:** `replay_real_captures()` přehrává uložené snímky konzole a
  vyžaduje přesnou shodu se stavem — 35 cyklů shodně. Živé stagedování/eject v `one_cycle` na zařízení
  tím pokryté není.

## 12. Nové (2026-10-16) — §67: konzole umí ČÍST soubory (`0x19` → `0x20`)

**Toto ruší §22 i všechny pozdější poznámky, že „konzole neumí vrátit bajty souboru".** Tvrzení stálo na
sweepu, který posílal **prázdné** payloady, a na odhadnutém vylučovacím seznamu, který `0x19` zařadil do
„NAND rodiny — neposílat", aniž to někdo otestoval. `0x19` je přitom příkaz pro čtení souboru.

- **Request `0x19`, reply `0x20`.** Payload = jedna NUL-terminovaná cesta **relativně k `/yaffs2/`.**
- Prefix potvrzuje vlastní log zařízení: `error opening file /yaffs2/<cesta>, error type: rb ENOENT`.
- **Je pouze pro čtení** — otevře, přečte, pošle, zavře. Nic nezapisuje, nepřesouvá, nemaže. Lze bezpečně
  dávkovat přes mnoho cest.
- Soubor chodí jako posloupnost `0x20` rámců; slepení payloadů v pořadí doručení dá přesně původní soubor.
  Ověřeno bajt po bajtu od 1 428 B do 706 990 B.
- **Špatná cesta nevrátí žádný rámec**, jen log rámce (routing `0x1E`, type `0x04`, `yaffsfs: yaffs: error:
  ENOENT`).
- Nemá parametr offsetu ani délky — vždy čte celý soubor od začátku.

**Dvě pasti v protokolu:** PONG je rámec s nulovou délkou (`C0 1E 01 00 00 00 00`), takže dekodér, který
`len == 0` zahazuje, liveness nikdy nezaznamená; a otevření portu resetuje linku, takže **první zapsaný rámec
se ztratí** — před příkazem je nutné port „zahřát" (PING).

**Změřený výsledek:** osm továrních enginů (`chord`, `digital`, `electric`, `fm003b`, `ministringshort`,
`saw013a`, `tapetwo`, `volt`) **na zařízení v `/yaffs2/system/content/engines/` není** — všech osm vrátí
prázdno, kontrola `crush.engine` vrátí 1 212 B shodných s firmwarem. Dřívější „nejsou v žádném balíčku" je tím
povýšeno na měření přímo na zařízení.

**Pozor na `0x37`:** vypadá jako kopírování, ale je to **přesun (rename)** v rámci `/yaffs2`; zdroj i cíl bere
z payloadu a režim je jen slovo příznaků — žádný copy režim neexistuje. Status `0xD3` = přesun proběhl,
`0xE1` = neproběhl. Argumenty držet pod ~60 bajtů (sloty jsou `0x40` od sebe).

**Content-mode mass storage je FILTROVANÝ pohled, ne surový strom.** Dva staging soubory, které se ve výpisu
nikdy neobjevily, na zařízení stále byly a oba se na první pokus vrátily; naopak `how_to_import.txt` a
`import.log` jsou vidět v kořeni svazku, ale jako `/yaffs2/user/how_to_import.txt` vrací `ENOENT`. Existenci
souboru spolehlivě ověří jen `0x19`.

**Otevřené:** kde osm chybějících enginů je (chybí primitivum pro výpis adresáře); nezpracované handlery
`0x10`, `0x14`, `0x17`, `0x31`, `0x23`, `0x27`, `0x32`, `0x34`.

## 13. VÍTĚZSTVÍ (2026-10-16) — bricknutá OP-Z znovu hraje

**Stav: přístroj je opravený a přehrává.** Podrobný záznam je v `FW_SUCCESS.md` §26, veřejná verze v
`FIRMWARE_ANALYSIS.md` §70.

**Výchozí stav:** boot pouze do update módu; `<PLAY>` padalo na `RETX 0x80117baa` / `iid 0x00130026` /
`DCPLB_FAULT_ADDR 0`; osm továrních engineů naměřeno jako chybějící v `/yaffs2/system/content/engines/`;
24 továrních sample packů chybělo.

**Co to spravilo:** přeinstalace stock 1.2.45 opravila **boot** (žádná výjimka, init doběhne do
`task: create task filemanager_task`), ale `<PLAY>` stále padalo. Teprve payload přes **§24 updater primitive**
(prostý nešifrovaný zip `firmware_bin_only_with_bootloader.zip` v rootu svazku, cesty s `..` bez sanitizace)
dostal soubory do systémového stromu: 33 položek / 18 468 406 B — 8 engineů do `system/content/engines/`,
20 packů do `system/content/samplepacks/`, 4 packy `redmount*` do `user/samplepacks/`. Extrakce doběhla
(`[extract] progress 18463232/18463232`, nula chyb) a **`<PLAY>` funguje.**

**Důležité opravy dřívějších závěrů:**

- `Calculating used sample memory` počítá jen **uživatelský** sample prostor — 869 kB je po úspěchu správně.
- Pět engineů s `dlm: Unsupported fill value` **není** příčina pádu PLAY — přístroj hraje i s nimi.
- Šifrovaný `.zfw` **není** potřeba pro zápis do `system/content/`; stačí prostý zip přes §24.
- Konzole bootloaderu odpovídá **jen dokud se OS nezačne bootovat** — v běžícím stavu je němá.

**Pravidla pro příště:** spustit sběr konzole **před** ejectem (čítač `[extract] progress` je jediná verifikace);
cílové cesty brát z manifestu zdrojového přístroje; hashovat na obou koncích; po kopírování smazat `._*` soubory
z rootu svazku; **nikdy** nebootovat funkční přístroj do content módu (eject sync maže
`/yaffs2/user/engines/`); **nikdy** nedávat `os`/`bootloader` do §24 payloadu.

**Zbytky (neblokující):** pět DLC engineů bez publikovaného memory slotu, chybějící `arpeggiators/01-06.txt`,
občas `libaiff: AIFF_ReadOpen failed`.

## STAV CÍLE: „aby hrály všechny tovární enginy správně“ (2026-10-19)

**Cíl nesplněn.** Ověřeně hrají **2 z 13** továrních nástrojů — `digital` a `chord` — a to přes osm not
(45–81) skrz HTTP API aplikace. Klíč: výška se předává jako bajtový krok do tabulky a **perioda je per engine**
(`digital` 32768, `chord` 16384; lineární zákon `f_out = arg × 48000/perioda`). U efektů se ověřeně nepodařilo nic. Podrobnosti a tabulky: `firmware-re-docs/13-factory-engine-status.md`; všech 111 testů:
`HYPOTHESES.csv`; měřítko: `toolkit/opzfactorycheck.py`.

| engine | stav | důkaz |
|---|---|---|
| `digital` | **hraje správně** | 8 z 8 not (45–81) přes API; perioda 32768 |
| `chord` | **hraje správně** | 7 z 8 not (45–81) přes API; perioda 16384 |
| `ep` | nehraje | nemění se s argumentem ani se stavem (fixní spektrum) |
| `crush`, `chorus2` | běží, neověřeno | mění vstup, ale jsou stavové, převodní funkce neurčí správnost |
| `volt`, `electric`, `cluster` | nehrají | DC / fixní spektrum / konstanta 2e-4 |
| `organ`, `sampleplayergain`, `synthsampler` | ticho | `organ` po `state+0x10` bráně indexuje vlastní tabulku záporným indexem |
| `analoga`, `fm003b`, `ministringshort`, `saw013a` | chyba | volají mimo okno při každé výšce 50–1200 Hz |
| `delay`, `tapetwo`, `reverb`, `dist`, `chorus` | ticho/chyba | `delay` při init čistí 1 MB buffer, jehož ukazatel je 0 |

**Co bylo objeveno a je použitelné:** výška se předává jako bajtový krok do čtvrtvlnné sinusové tabulky, tedy
`f_out = arg × 48000/32768` (faktor 1,4648) — to je důvod, proč `digital` hraje. Dále: všech šest argumentů na
stacku, amp objekt (`+4 = 0x40000000`, `+8 = 0x7f000000`, `+0xc = -0x40000000`, `+0x10 = 2`) a host paměť
(sinusová tabulka + host tabulka), kterou `opzhost` skládá přímo z `opz.ldr` bez Ghidry.

**Blokátor (prokázán ze tří stran):** nástroje potřebují per-voice stav od sekvenceru, efekty hostitelem
přidělené buffery; obě cesty (interpret i JIT) končí na tomtéž. Žádný artefakt v repu tento stav nenese —
`opz.ldr` nemá region `0x04xxxxxx`, `.zfw` je AES bez klíče, `.opz` projekty jsou písňová data, APK presety
engine ignoruje, `.plz` soubory jsou nulové.

**Co odblokuje práci:** (1) dump paměti zařízení `0x04000000`–`0x04100000`, (2) AES klíč k `.zfw`,
(3) výslovné zadání na více­týdenní emulaci OS služeb, (4) přijetí náhradních enginů. Zařízení je podle sekce
výše funkční a čtení z něj funguje (`opzcopyprobe`, `sergey-extraction/opzget.py`) — dump se tedy jeví jako
nejschůdnější cesta.

### Jak spustit testy (2026-10-19)

Osm `test_*.py` v kořeni dřív nešlo spustit vůbec — importovaly `opzfarm`/`opzsim`/`opzassemble` z `/tmp`, které už
neexistuje. Cesty jsou přepsané na repozitář a sedm z nich potřebuje `pyserial` (systémové `pip` ho odmítá kvůli
PEP 668, takže patří do venv):

```
python3 -m venv /tmp/opzvenv && /tmp/opzvenv/bin/pip install pyserial
for t in test_*.py; do /tmp/opzvenv/bin/python "$t" >/dev/null && echo "PASS $t" || echo "FAIL $t"; done
```

Stav: **6 z 8 prochází.** `test_opzfarm.py` a `test_success.py` padají na vlastních očekáváních vůči současnému
`opzassemble.py` (chybí `ZIPWALK` řádek v zachyceném výstupu) — to je starý nesoulad testů, ne regrese z práce na
enginech.

**Doplnění (2026-10-19, později):** ABI efektů bylo přečteno přímo z firmwaru — `FUN_8012ced0` volá
`renderFX(param_4, param_5, state, param_6)` se **čtyřmi** argumenty a `init` s **pěti** (čtvrtý je ukazatel do
tabulky na `0x8156f21c`). Ani přesná reprodukce tohoto volání efekty nerozjede: `chorus2` vydá jen 6 vzorků z 384.
Tabulka i buffer (`0x8112b21c`) jsou BSS plněné až běžícím OS. Dále: výstup všech enginů dominuje artefakt na
kmitočtu bloku (375–750 Hz) s kontrastem 500–1500×, hudební tón má 20–70×; žádná transformace na straně hostitele
ho neodstraní. Celkem 152 zaznamenaných hypotéz.

**Co je potřeba pro odblokování (upřesnění 2026-10-19):** repo umí číst *soubory* z jednotky (`opzcopyprobe`,
`sergey-extraction/opzget.py`), ale **nemá žádný příkaz pro čtení paměti** — `opzpeek.py` pracuje jen s USB svazkem
a v protokolu konzole žádná "read memory" operace není. Pro dump regionu `0x04xxxxxx` a běhových BSS
(`0x8112b21c`, `0x8156f21c`) je tedy potřeba JTAG/SWD přes BF703 debug port, nebo dopsat do protokolu nový příkaz.
Tohle je jediná chybějící věc; všechno ostatní je v repu hotové a ověřené.

## Kde to skutečně skončilo (2026-10-19) — a kam jít dál

**Tento repozitář je na svém stropu: 2 z 13 továrních nástrojů.** `digital` (perioda 32768) a `chord`
(perioda 16384) hrají správně přes osm not, ověřeno přes HTTP API aplikace. Zbylých 11 nástrojů a všech
8 efektů potřebuje běhový stav firmwaru, který v žádném artefaktu v repu není (166 zaznamenaných hypotéz).

**Klíčový objev:** na stroji je `~/.opz-decode/opzso/libSnakePlugin.so` (1,95 MB) se `syms.json`
(4 699 symbolů) — vendorova ARM64 stavba **týchž enginů** se symboly. Z ní je ABI čitelné, ne odhadované:

- `render(fract32_t *out, unsigned frames, int track, void *state, const unsigned *params, ADSR*)`
  — `out` je prokládané stereo Q31, druhý argument je **počet rámců** (ne increment),
- `initModule(id, iface, out)`, `init(state, a, b, tempBuffer, d)` (5. argument = tempBuffer, 3. do `state+0x20`),
- **`ADSR` má 6 slov**: `+0x00` rate, `+0x04` level, `+0x08` mul, `+0x0c` add, `+0x10` phase (render okamžitě
  vrací, je-li 0), `+0x14` tail — enginy na `+0x14` **gateují**,
- `iface+0x38` je envelope hook, `iface+0x40` updateParametersAHD, **`iface+0x48(id, note)` vrací 40bajtový
  sample record** (`+0x00` data, `+0x08` frames, `+0x0c` pitch, `+0x10` rate),
- **všech 21 enginů je v té knihovně** (AnalogA, Chord, Cluster, Digital, EP, Electric, Fm003b, MiniStringShort,
  Organ, SamplePlayerGain, Saw013a, SynthSampler, Volt + Chorus, Chorus2, Crush, Delay, Dist, FdnReverb,
  Reverb, TapeTwo).

**Kde dokončit práci:** `~/projects/customs/opz-clone` — má vendor knihovnu, fungující Unicorn loader
(`tools/unicorn-harness/opzso.py`, lze zavolat kterýkoli entry point), host třídy pro Digital/AnalogA/Saw013a/
SamplePlayerGain, **21/21 testů zelených** a tři enginy **byte-exact** proti originálu. Chybí 18 enginů, každý
potřebuje vlastní host třídu, port, golden fixtury a byte-exact test. `Organ` a `Cluster` už byly zkoušeny
a ani po třech kolech nedaly ani vzorek zvuku — to je reálná cena jednoho enginu.

## Konečný stav cíle „aby hrály všechny tovární enginy“ (2026-10-19)

**11 z 21 enginů ověřeně funguje**, zbytek ne. Každé číslo je změřené, ne odhadnuté.

| kde | co funguje | jak je to ověřené |
|---|---|---|
| `~/.opz-decode/opzso/libSnakePlugin.so` (vendor ARM64 se symboly) | **7 z 8 efektů**: Crush, Reverb, Chorus2, Dist, Delay, FdnReverb, Chorus | přímé volání `renderFX(params, frames, state, in, out, scratch)` a počítání nenulových vzorků; Delay potřebuje ~58 ms (blok 44), FdnReverb blok 27 |
| `~/projects/customs/opz-clone` (porty, byte-exact) | **4 z 13 nástrojů**: digital, analog_a, saw013a, sample_player_gain | `cargo test -p opz-dsp` – 3 + 11 + 12 testů + golden cases, vše zelené |

**Co je potřeba pro zbytek (10 enginů):** každý nástroj vyžaduje vlastní host třídu – `init` si sám plní
`g_scratchpads` z host bufferu, takže předplnění nepomůže; Digital potřebuje pět gain globalů, 16prvkovou oktávovou
tabulku a wavetable, než vůbec vydá vzorek. U efektů zbývá jen `TapeTwo`: po opravě `init` (4. argument musí být
buffer ≥ 1 MB, jinak si vynuluje vlastní kód na 0x100000) běží, ale zapisuje nuly.

**Metody, které fungovaly** (používat dál): přečíst manglovaný symbol → znát signaturu; decompilovat přes
`tools/ghidra-scripts/DecompileTo.java`; hookovat zápisy do paměti, aby se zjistilo, kam engine skutečně píše;
a pamatovat, že `ADSR+0x10` (phase) musí být 5–7 a `iface+0x38` je envelope hook.

## Aktuální stav cíle „aby hrály všechny tovární enginy" (2026-10-19, konec session)

**Pozor na rozdíl „vydá zvuk" vs „zahraje zadaný tón".** Vydaný zvuk je slabší kritérium než
správná výška tónu, a čísla se liší:

```
python3 toolkit/opzinstcheck.py --blocks 20                        # 13 z 13 nástrojů vydá zvuk
python3 toolkit/opzinstcheck.py --blocks 140 --note-check          # 11 z 13 zahraje tón na note 60
python3 toolkit/opzinstcheck.py --blocks 140 --note-check --note 57   # 11 z 13
python3 toolkit/opzinstcheck.py --blocks 140 --note-check --note 72   # 10 z 13
python3 toolkit/opzfxcheck.py   --blocks 60                        #  7 z 8 efektů (TapeTwo mlčí)
```

**Ve všech třech tóninách projde 9 z 13 nástrojů** (AnalogA, Chord, Digital, EP, Electric, Fm003b,
MiniStringShort, Saw013a, Volt). To je obhajitelné číslo pro „hraje správně"; 13 z 13 platí jen pro
„vydá zvuk". Všechny brány vypíše `python3 toolkit/opzstatus.py`.

### Co se v této session opravilo (a co se už nemusí znovu hledat)

Instrumenty šly ze 4 na 13. Příčinou nebyly chybějící znalosti o enginech, ale **tři chyby
v mém vlastním harnessu**, každá doložená měřením:

1. **Globály enginů se zapisovaly na Ghidra adresy**, tedy o `0x100000` výš, než jsou skutečné.
   Každý pokus dodat hostitelská data proto skončil v nepoužité paměti a engine četl nuly.
   Správně je `Ghidra adresa − 0x100000` (např. gainy na `0x124A5CC`…`0x124A5DC`).
2. **Oblast `0x124A500`–`0x124C400` zůstávala nulová.** Jsou v ní tabulky envelope-rate křivek
   a oktávových/pásmových gainů; dokud jsou nulové, je ticho i u enginu, který je jinak
   nastavený správně. Vyplnit i16 `0x7FFF`.
3. **`interface+0x28` musí ukazovat na PĚT ukazatelů**, každý na tabulku 16×65 `fract32_t`
   (4160 B, ne jeden řádek) naplněnou Q31 sinusem škálovaným `0x7FFFFFFF >> (bank*2)`.
   S jedním vynulovaným bufferem je signálová cesta nulová — tato jediná oprava rozsvítila
   `AnalogA`, `Fm003b` a `Saw013a`.

Dále: vzorkovníky (`SamplePlayerGain`, `SynthSampler`) potřebují 40bajtový záznam vzorku
přes `interface+0x48` (data, počet rámců, pitch, rate), a knihovna importuje jen
`__stack_chk_fail, clock, free, malloc, memcpy, memset` — všechny je potřeba stubovat.

### TapeTwo — jediný engine, který nehraje, a proč

`TapeTwo::renderFX` se změřením chová takto: při kladné odpovědi na readiness dotaz
(`vtable[0x08](5)`) **správně nahrává** — 64 zápisů za blok do `sampleLine`, kde je přesně
vstupní vzorek — ale pak **vynuluje svůj přehrávací buffer (`tapeBuffer_z`) a čte právě ten
vynulovaný**, takže všech 128 zápisů do `out` je nula. Přes 300 bloků `tapeBuffer_z_l`
nikdy není nenulový a `updateTapeStop` ve čtyřech režimech to nemění. Chybí tedy hostitelský
převod `sampleLine → tapeBuffer_z`, který tato builda v `renderFX` neprovádí.

**Opraveno 2026-10-19:** tahle hypotéza byla změřena a **neplatí**. Při stubu všech slotů rozhraní na 1 se
`sampleLine_l` vstupem skutečně naplní (16 z 16 nenulových slov, první `61800448`), ale `renderFX` sám
zapíše 128 nulových slov do `tapeBuffer_l` (střídavé offsety `0, 128, 2, 130, …`) a ta samá slova pak čte.
Provedení „chybějícího" převodu z hostu (kopie `sampleLine → tapeBuffer_z` při volání služby s opcode
`0xa0002`) 32× přes 8 bloků výsledek nemění (0 z 1024), stejně jako naplnění šestého argumentu vstupem
(0 z 768). Ticho je tedy v mixu samotného `tapeBuffer`, ne v chybějícím převodu.

**Pozor na past:** ukazatele do pásek jsou 64bitové (`0x200000531000`). Kdo je čte po 4 bajtech,
dostane zkrácenou hodnotu a háčky pak hlásí „žádné zápisy", což je artefakt, ne chování enginu.

### Tři populace enginů — každá má jeden příkaz (doplněno 2026-10-19)

Číslo „20 z 21" platí pro **dodaný vendor kód** (`libSnakePlugin.so` z APK). Na zařízení ale běží
i blackfinové `.engine` moduly, a ty se měří zvlášť. Aby se to už nemuselo dolovat z ad-hoc skriptů:

| populace | příkaz | výsledek |
|---|---|---|
| vendor ARM64 nástroje | `python3 toolkit/opzinstcheck.py --blocks 20` | **13 z 13** vydá zvuk |
| vendor ARM64 efekty | `python3 toolkit/opzfxcheck.py --blocks 60` | **7 z 8** (TapeTwo mlčí konstrukčně) |
| Blackfin `.engine`, vydá jakýkoli zvuk | `python3 toolkit/opzfactoryaudible.py` | **6 z 13** |
| Blackfin `.engine`, zahraje zadaný tón | `python3 toolkit/opzfactorycheck.py` | 2 z 13 |
| Blackfin `.engine` efekty, vydá zvuk | `python3 toolkit/opzfactoryaudible.py` | **0 z 8** (měřeno jen tímto harnessem, viz níž) |

Poznámka k efektům: `render_clip` volá tovární efekt pěti argumenty, o jeden méně než vendor signatura
`renderFX(params, frames, state, in, out, scratch)`, takže nula u `.engine` efektů je zatím míra
harnessu, ne důkaz ticha. `dist.engine` bere ukazatel na scratch z vlastního globálu `module+0x554`
(init ho vynuluje) a výstupní buffer z dalšího pole, které plní OS.

### Proč blackfinové enginy nejdou dál: čipová L2 ROM

Zbylých sedm `.engine` nástrojů (`analoga`, `fm003b`, `ministringshort`, `saw013a`, `organ`,
`SamplePlayerGain`, `SynthSampler`) už netrpí chybějící pamětí ani gatem:

* všechny čtyři „faultující" enginy v mašině s celým OS image **doběhnou init i OS note-start**
  (`analoga` 719 kroků, `ministringshort` 1 210, `saw013a` 771) a padají až v ticku;
* tick `0x8012E2C0` provede po 68 krocích `CALL.A` na **`0x04020a70`**;
* to je podle `ADSP-BF70x Hardware Reference`, tabulka 11-1, řádek `0x04000000 0x407FFFFF L2 Bank 0
  ROM (512 KB)` — mask ROM v čipu, kterou žádný dodaný image neobsahuje (v `opz.ldr` jsou jen
  segmenty `0x11A`, `0x08` a `0x80`; `bootloader.ldr` nic pod `0x118` nepřidá);
* volání do ní nejsou okrajová: sken image najde **1 195 volání na 51 různých vstupů**, a manuál
  k ROM žádnou tabulku adres nepublikuje, takže se nedají ani pojmenovat, ani emulovat „podle dokumentace".

`organ` je jediný, který se dá otevřít bez ROM (vynutit `R2` na `0x81b7d1c4`), ale i pak vydá jen
jeden impuls (51 ze 64 vzorků v bloku 1, zbytek nuly) — jeho hlasitost a fáze jdou z rezidua zásobníku,
které tam nechává právě ten tick. Doplňování oblastí, které čte jako nuly (`0x81bbfe00–0x81bc0000`),
výsledek nemění.

**Co to znamená pro cíl:** bez portu 51 rutin mask ROM (a rekonstrukce OS kontextu voice) se zbytek
.blackfinové populace nerozjede. Rozumné možnosti jsou dvě — přijmout dodaný deliverable
(13/13 nástrojů, 7/8 efektů) jako splnění cíle, nebo takový port zadat.

### Chyby harnessu opravené v této session (ať se nehledají znovu)

* `opzsim.call` nechával na zásobníku argumenty, takže se frame posouval o 24 B při každém bloku —
  `organ` proto hrál jeden blok z pěti. Nyní se `SP` po volání vrací (argumenty vlastní volající).
* `RETS == 0` se považoval za platnou návratovou adresu (`_off(0)` je v 4GB mašině „uvnitř okna"),
  což zacyklilo běh; volání přes nulové slovo mají strop `NULL_CALL_LIMIT`.
* S `check_coverage` se skok mimo mapované segmenty ohlásí adresou místo 200 000 NOP kroků.
