# TR-808 samples, packaged for fluid-music

`npm install @fluid-music/tr-808`

Free 808 drum sample library packaged for [`fluid-music`](https://www.npmjs.com/package/fluid-music). The module exports multiple `fluid-music` technique libraries.

```JavaScript
const tr808 = require('@fluid-music/tr-808')
tr808.kit  // a drum technique library
tr808.bass // a pitched bass technique library
```


## The `tr808.kit` Technique Library

The `tr808.kit` technique library contains the following drum sample audio file techniques:

- `B` - less click, longer sustain
- `b` - more click, short sustain
- `h` - closed hat
- `H` - open hat
- `k` - short snare
- `K` - long snare
- `p` - clap 👏
- `👏` - clap (same as `p`)
- `w` - cowbell


## The `tr808.bass` Technique Library

The bass drum sound on the original TR-808 drum machine had an adjustable decay. Setting the decay parameter to a high value causes the bass drum to sound more like a bass guitar with a long, low, resonant pitch. A tuned 808 bass drum sample with a long decay is often used to fill the role of a bass guitar or bass synthesizer in trap and other styles of electronic music. These two samples in this the `tr808.bass` technique library can be re-tuned to make melodic trap-style bass lines:

- `G` - a sustained pitch bass note, tuned to g1 with minimal click
- `g` - a sustained pitch bass note, tuned to g1 with some click

## License

The samples were downloaded from [machines.hyperreal.org](http://machines.hyperreal.org/categories/drum-machines/TR-808/samples/).

The original audio files were recorded by Michael Fischer (fischer1@student.msu.edu), who included a [.TXT](https://github.com/fluid-music/open-drums/blob/main/tr-808/TR808WAV/TR808.TXT) with detailed information about the samples, and no licensing restrictions.

## Other Open Drum Packages

See [fluid-music/open-drums](https://github.com/fluid-music/open-drums/) on github for other drum packages.

Or [search npm for `fluid-music`](https://www.npmjs.com/search?q=fluid-music).
