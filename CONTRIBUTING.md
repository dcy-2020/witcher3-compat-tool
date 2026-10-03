# Contributing

Run `python -m unittest discover -s tests -v` before submitting a change.

Prefer small rules with precise preconditions and explicit refusal cases. Include synthetic examples covering ambiguous syntax, encoding, candidate revalidation, source drift, partial-write recovery and exact rollback. Document what was statically checked and what was tested in the game separately.

This repository distributes original tooling only. Do not submit original game scripts/assets, third-party mod source without permission, saves, dumps, complete local scan/staging folders, personal settings, authentication credentials or conversation exports. A minimal fictional example is usually enough for a parser bug.

Format/package adapters need exact format evidence and roundtrip tests before becoming writable. A header edit is not a resource migration. Gameplay/API migrations need a known original base, a target base and mod-specific runtime evidence.

## Publishing

The release workflow reuses the Windows/Linux x Python 3.10/3.12 test matrix before building the allowlisted source ZIP, Python zipapp and checksum file. Only its publish job receives the repository-scoped, temporary Actions token with contents-write access.

After the reviewed commit is on the default branch, push a matching release branch such as release/v0.1.0, or push a matching lightweight tag. A manual run must select the version-matching release branch or tag. The package version and reference must agree. Existing releases or conflicting tags are preserved and cause the job to stop. Annotated tag references are conservatively refused by the existing-tag guard.

Releases are marked experimental prereleases. Do not add game/mod samples, scan outputs, user settings or repair histories to the build allowlist. Packaging does not validate gameplay compatibility.
