# Open Drums For Fluid Music

This repo contains a collection of drum sample libraries packaged for the fluid-music system. All packages are available via npm:

- `npm i` [`@fluid-music/tr-707`](https://www.npmjs.com/package/@fluid-music/tr-707)
- `npm i` [`@fluid-music/tr-808`](https://www.npmjs.com/package/@fluid-music/tr-808)
- `npm i` [`@fluid-music/tr-909`](https://www.npmjs.com/package/@fluid-music/tr-909)

The samples are originally came from [machines.hyperreal.org](http://machines.hyperreal.org/).

## Notation

In Open Drums, all drum sounds are mapped to one character. Case matters, you can even use emojis.

## Example

This is what two measures of snare, kick, and hi-hat transcribed with 'fluid-music' look like:

```javascript
const score = {
  r:      '1 + 2 + 3 + 4 + ',
  snare: ['    k       k   ', '    k       k   '],
  kick:  ['B               ', '          B  B  '],
  hat:   ['h h h h h h h h ', 'h h h h h h h h '],
}
```

Here, we have 4 tracks, the first one is the rhythm string, notated with 'r', and then we have three tracks, one for each drum voice: 'snare', 'kick' and 'hat'.

For more info https://github.com/fluid-music/fluid-music/blob/main/docs/concepts.md#rhythm-string

* B: Bass drum - less click, longer sustain
* b: Bass drum - more click, short sustain
* h: closed hat
* H: open hat
* k: short snare
* K: long snare
* p: clap 👏
* '👏':emoji clap

## Example

We suggest this example to try a score to be rendered with three different drum machines.

```javascript
const fluid = require('fluid-music');
const tr707 = require('@fluid-music/tr-707');
const tr808 = require('@fluid-music/tr-808');
const tr909 = require('@fluid-music/tr-909');

const session = new fluid.FluidSession({bpm: 180});

const score = {
  r:      '1 + 2 + 3 + 4 + ',
  snare: ['    k       k   ', '    k       k   '],
  kick:  ['B               ', '          B  B  '],
  hat:   ['h h h h h h h h ', 'h h h h h h h h '],
}

const tLibraries = [tr707.tLibrary, tr808.tLibrary, tr909.tLibrary];

for (const tLibrary of tLibraries) {
  session.insertScore(score, {tLibrary});
}

session.finalize();

session.saveAsReaperFile('drumExamples')
  .then(() => console.log('done'))
  .catch((error) => console.log(error));
```
