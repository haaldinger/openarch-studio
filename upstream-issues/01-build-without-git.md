# Build fails from a source download (no `.git`): buildnumber & git-commit-id plugins hard-fail

## Summary
Building OpenArch from a source tarball / zip (i.e. without a `.git` directory)
fails during `package`. Two plugins require git metadata and abort the build
instead of degrading gracefully, so "download the source and build it" does not
work without first running `git init`.

## Environment
- OpenArch `12.0-SNAPSHOT` (also affects released source archives)
- JDK 25 (Temurin/Corretto), Maven 3.10
- Fresh source copy with **no** `.git` directory

## Steps to reproduce
```bash
# from a source download (no .git)
mvn -q -DskipTests package
```

## Actual behaviour
1. First failure — `buildnumber-maven-plugin:3.3.1:create`:
   ```
   Cannot get the branch information from the scm repository :
   ... git log command failed ... fatal: not a git repository
   ```
2. After working around that, second failure — `git-commit-id-maven-plugin:10.0.1:revision` (module `openarch-app`):
   ```
   .git directory is not found! Please specify a valid [dotGitDirectory] ...
   ```
   Notably `-Dgit.skip=true` did **not** skip it.

## Expected behaviour
A source build should succeed without a git repository, or at least be
skippable with documented flags.

## Proposed fix
Configure both plugins to degrade when git is absent:
- `buildnumber-maven-plugin`: set `<revisionOnScmFailure>` (e.g. `unknown`) and
  `<getRevisionOnlyOnce>true</getRevisionOnlyOnce>`.
- `git-commit-id-maven-plugin`: set `<failOnNoGitDirectory>false</failOnNoGitDirectory>`
  (and honor a skip property).

This keeps release builds unchanged while unblocking source-archive builds.

## Workaround
```bash
git init && git add -A && git commit -m "local build"
mvn -q -DskipTests package
```
