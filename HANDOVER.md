# OP-Z – předávací dokument pro dalšího agenta

> Tento soubor je v češtině záměrně (na přání zadavatele). Všechny identifikátory, cesty, příkazy a názvy
> souborů zůstávají v původním tvaru. Hloubkové detaily jsou v `FIRMWARE_ANALYSIS.md` (sekce 1–66);
> výtěžek hypotéz v `HYPOTHESES.csv` (4 sloupce: hypothesis, test, conclusion, notes).

## Nejnovější transportní zjištění (2026-10-11) — čti před staršími oddíly

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

## 0. Úkol a stav v jedné minutě

Dva cíle, které se navzájem podmiňují:

1. **Opravit bricknutou OP-Z** – jednotka naběhne jen do update módu, OS při každém normálním bootu spadne.
2. **Dekódovat firmware** (`.zfw`) – běží přes console oracle, zatím 327 z 1 490 575 bajtů.

Stav při předání:

| Co | Hodnota |
|---|---|
| Zařízení | **není na USB busu** (žádný `/dev/cu.usbmodem*`, žádný `/Volumes/OP-Z`) |
| Dekódováno | **327 B** z 1 490 575, `cycles=3`, `pending=4` intervaly |
| Farma | běží pod launchd (`com.opz.decode`), čeká na medium |
| Ground truth | 142 bajtů ověřených hardwarem, všechny sedí |
| Jednotka | X3CJN79E, fw 1.2.45, os 1.2.43, bootloader 1.1.35, kb 1.2.26, ble 1.1.9 |

**Medium se vrací jen bootem zařízení** (tlačítko PLAY / odpojit-připojit). Žádná host-side operace ho
nevrátí – což je ověřené, ne předpoklad.

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

## 5. Zbývající cesty a pořadí prací

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

## 6. Jak provést experiment na zařízení

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

## 7. Interakce s uživatelem (co od něj čekat a co mu dát)

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
