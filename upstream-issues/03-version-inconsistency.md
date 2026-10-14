# Version inconsistency across `VERSION`, root POM, and README image tag

## Summary
Three places disagree on the project version, which makes it unclear what to tag,
pull, or reference when building/running from source.

## Observed (current `main`, verified 2026-10-13)
- `VERSION` file: **`1.0`**
- Root `pom.xml` (`openarch-parent`): **`12.0-SNAPSHOT`**
- `README` references the container image tag **`1.0.0`** in its run instructions.

## Why it matters
A developer following the README to build and run can't tell which version string
is authoritative — e.g. which tag the locally built image should carry, or which
version the `VERSION` file is meant to track relative to the Maven version.

## Expected behaviour
A single source of truth (or a documented relationship) between `VERSION`, the
Maven project version, and the image tag used in the README.

## Proposed fix
Either derive `VERSION` and the README tag from the Maven version at build time,
or document how the three relate (e.g. `VERSION` = marketing version, POM =
internal snapshot, image tag = release version).

## Context
Found while standing up OpenArch locally to run a POC against it.
