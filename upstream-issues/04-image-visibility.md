# Published image `ghcr.io/hyland/openarch-app-jvm` is not anonymously pullable

## Summary
The README's "clone and run" story implies pulling a published image, but
`ghcr.io/hyland/openarch-app-jvm` could not be pulled anonymously, and
authenticating as a non-org account returned `denied`. This blocks the
quickstart for external developers and forces a from-source build.

## Observed
- Anonymous pull → `unauthorized`.
- Authenticated (non-org GitHub account) pull → `denied`.

## Why it matters
If the published image is meant to back the README's `docker compose up`
quickstart, external developers can't use it; they fall back to building from
source (which currently has its own friction — see the build/Dockerfile issues).

## Expected behaviour
Either the image is anonymously pullable, or the README documents the required
`docker login ghcr.io` + the org access needed to pull it.

## Possible non-issue
If gating the image is intentional, this is a **docs** gap rather than a bug —
happy to move it to Discussions if that's preferred. Filing here because the
README presents the image as part of the getting-started path.

## Context
Found while standing up OpenArch locally to run a POC against it; ended up
building from source because the image wasn't pullable.
