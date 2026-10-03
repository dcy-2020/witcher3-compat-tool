# Witcher 3 Compat Tool

An experimental, offline CLI for a **limited** part of Witcher 3 4.04 → 5.x mod migration. Python 3.10+, standard library only at runtime. [中文说明](README.md).

v0.1.0 recognizes unambiguous function parameters and local variables named `set` or `map`, then renames their declarations and references. It preserves comments, literals, member names, UTF encoding/BOM and line endings. Ambiguity anywhere blocks automatic repair of the entire file.

It also reports duplicate loose-script engine paths, core character/inventory overrides, SSS-named mods, and mismatching loose localization/CR2W headers. The default reference header version, 164, was observed in one 5.00b/5.00c installation. Header mismatches are review hints, not proof of broken assets. Bundled payloads are **not inspected**.

## Quick start

Run from the extracted source/package directory:

[Release downloads](https://github.com/dcy-2020/witcher3-compat-tool/releases) include a source ZIP and a single-file `.pyz` app. Use `python witcher3-compat-tool-0.1.0.pyz --help` without installing the package; replace `python -m w3compat` in the commands below with that app invocation if preferred.

```powershell
python -m w3compat scan --game-root 'D:\Games\The Witcher 3' --out out\scan-01
python -m w3compat stage --game-root 'D:\Games\The Witcher 3' --out out\stage-01
# Review out\stage-01\preview.diff. Close the game before applying.
python -m w3compat apply --game-root 'D:\Games\The Witcher 3' --stage out\stage-01 --backup-dir out\transactions
python -m w3compat rollback --game-root 'D:\Games\The Witcher 3' --transaction out\transactions\TRANSACTION-ID
python -m w3compat rollback --game-root 'D:\Games\The Witcher 3' --transaction out\transactions\TRANSACTION-ID --apply
```

Add `--mod-settings PATH` to scan/stage to honor `Enabled=0`. Without it, activation is inferred from folder names only. Output must be a **new** directory outside engine-loaded folders. `apply` explicitly authorizes mutation; `rollback` is a dry run unless `--apply` is present.

Before writing, candidates are rederived from current source bytes. All targets are backed up and SHA-256 verified before any script is replaced. Source drift, tampered candidates, links/junctions, read-only targets and a running game block mutation. A journal supports rollback after interrupted writes; changed third-party edits are never overwritten. A persistent `.w3compat.lock` file coordinates tool instances; OS locks are released on process exit. Multi-file operations are not globally atomic.

Only mod-owned `content/scripts/*.ws` files are writable. Native scripts, official DLC, saves, personal settings, resources and Script Merger metadata are not modified. Staging contains original/candidate source: keep it local and do not publish it.

## Limits and validation

No three-way script migration, field renaming, automated merges, binary conversion, font/UI reconstruction, talent-tree adapter, save editing or game-launch validation is provided. The tool does not claim to adapt most mods. After applying, check merge-source metadata using the existing workflow and separately test the game, menus and an existing save.

Tests:

```powershell
python -m unittest discover -s tests -v
```

The rule was checked against 56 affected old scripts (183 identifier edits) without distributing their source. Default staging selected 49 active-folder samples; seven inactive-folder samples were analyzed directly only. The selected copies were applied and restored byte-for-byte. These are script/transaction checks, not proof of complete gameplay compatibility. See [validation](docs/VALIDATION.md) and [rule boundaries](docs/RULES.md).

MIT covers original code, documentation and synthetic tests only. No game/mod assets, saves, personal configuration or private repair history are included. This project is unaffiliated with CD PROJEKT RED. [Contributing](CONTRIBUTING.md).
