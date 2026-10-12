# Contributing

Thanks for helping improve OP-Z interoperability.

Please open an issue or pull request for changes. Keep contributions scoped to
protocol documentation, app-independent codecs/transports, standalone tools,
tests, or redistributable evidence summaries. User-interface applications and
product features belong in separate repositories.

Do not submit copyrighted samples, factory projects, firmware, personal device
backups, installed-app binaries, or raw captures containing material you cannot
redistribute. Prefer synthetic fixtures and the smallest non-copyrightable byte
excerpt needed to reproduce a protocol observation.

Run the offline suite before opening a pull request:

```sh
python3 -m unittest discover -s Tests -p 'test*.py'
python3 -m unittest discover -s Tests/ToolingTests -p 'test*.py'
```
