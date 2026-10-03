# Contributing

Run `python -m unittest discover -s tests -v` before submitting a change.

Prefer small rules with precise preconditions and explicit refusal cases. Include synthetic examples covering ambiguous syntax, encoding, candidate revalidation, source drift, partial-write recovery and exact rollback. Document what was statically checked and what was tested in the game separately.

This repository distributes original tooling only. Do not submit original game scripts/assets, third-party mod source without permission, saves, dumps, complete local scan/staging folders, personal settings, authentication credentials or conversation exports. A minimal fictional example is usually enough for a parser bug.

Format/package adapters need exact format evidence and roundtrip tests before becoming writable. A header edit is not a resource migration. Gameplay/API migrations need a known original base, a target base and mod-specific runtime evidence.
