# a12-kernel-bootstrap — agent guide

This kit builds one pinned A12 release (kernel, its metamodels and its prerequisite libraries) from public mgm-tp GitHub sources. [README.md](README.md) is the user guide; [UPSTREAM-STATUS.md](UPSTREAM-STATUS.md) records every deviation from the public exports and why. Keep both current with any change here.

## Invariants

- No A12 content in this repository: no A12 source, patch, model file or jar. Corrections and missing inputs live in temporary public forks (below); the kit only pins commits.
- Public sources only; never let a build resolve A12 artifacts from a private repository. The Gradle home, npm cache, pnpm store and Maven repository are isolated under the state directory on purpose: the user's global Gradle/npm config adds a credentialed mgm Artifactory that would silently satisfy a missing public input.
- Nothing fabricated: no placeholder APIs, stub validators, guessed metamodels or invented artifact versions. If an input is not public, stop and report it as a blocker.
- `build-success.json` and the `~/.m2` install happen only after every build stage and both release smoke tests pass.
- Versions live in exactly one place: the release manifest `releases/<release>.json`, or the kernel's own `gradle/libs.versions.toml`. Gradle files under `build-support/` read them from `A12_*` environment variables set in `ReleaseBuilder.prepare_java`; do not hardcode a version there.

## Layout

| Path | Role |
| --- | --- |
| `releases/<release>.json` | Release identity: versions, pnpm, the ten repository commits, and the `forks` that replace an mgm-tp repository |
| `scripts/bootstrap.py` | CLI, toolchain checks, source export from mgm-tp or a fork |
| `scripts/build_release.py` | Ordered build stages, local npm registry, lock handling, `~/.m2` install |
| `scripts/compare_reference.py` | Entry-name comparison of built jars with an official distribution |
| `build-support/locks/<repo>/` | Committed dependency locks; loopback URL `http://127.0.0.1:4873/` is a placeholder |
| `build-support/java/` | Metamodel generation build (typings, dmjsons, validators) and the validator entry point |
| `build-support/wcf/`, `build-support/smoke/`, `build-support/tests/` | WCF API build, Java and TypeScript release smoke tests |

The metamodel list is not maintained by hand: `kernel_metamodels()` derives it from the pinned kernel catalog and build scripts.

## Tests

Unit tests need Python 3.12+ (`python3` may be older; `bootstrap.sh` picks a suitable interpreter):

```bash
python3.13 -m unittest discover -s tests -v
```

Use red/green TDD for script changes. A full build takes long; run it once with output saved to a file, and put Node.js 24 first on PATH (`./bootstrap.sh --doctor` prints the fix).

## Upgrading to a new release

The 2026.06-ext1 → ext2 migration followed these steps; expect the same shape next time.

1. **Find the release commits.** `./bootstrap.sh --check-upstream` lists refs, but mgm-tp publishes releases as commits on `main` named `Release <release> - <version>`, not as tags. Fetch each cached bare clone (`git --git-dir=<state>/git/<repo>.git fetch origin '+refs/heads/*:refs/heads/*'`) and read `git log --oneline main`. A repository without a new release keeps its pin.
2. **Write the manifest.** Copy the previous `releases/<release>.json` to the new name (git keeps history; the kit builds one release), update versions from the kernel's `gradle/libs.versions.toml` (`a12KernelVersion`, `kernelCoreRuntimeApiVersion`, `kernelCoreCustomfieldtypeApiVersion`, `com-mgmtp-a12-base`), the newest `packageManager` pnpm among the TypeScript repos, and point `RELEASE_FILE` and the default `--home` in `scripts/bootstrap.py` at it. Use a fresh state directory; copying the old `git/` caches into it saves the clones.
3. **Diff the kernel between releases** (`git diff <old> <new> -- gradle settings.gradle '*.gradle' package.json`): moved modules, new metamodels (`libs.kernelMm*`), changed dependency coordinates.
4. **Check every metamodel the kernel needs exists in the public export** (`a12-kernel-mm/documentModels/<Model>_<version>/`). A missing one is a blocker unless a fork can carry its exact model JSON (next section).
5. **Carry the forks forward.** For each fork in the manifest, check its fix commits (listed in UPSTREAM-STATUS.md) against the new release commit. Drop the fork when mgm-tp's release carries them: remove its `forks` entry and pin the mgm-tp commit. Otherwise create branch `<release>-fixes` in the fork from the new release commit, cherry-pick the fixes still needed, push, and pin the branch head. A new correction gets its own fork commit with the rationale in the message.
   Do fork work in the sibling checkout `../<repo>`: `origin` is mgm-tp, and the fork is the remote `fixes` (`git remote add fixes https://github.com/mbackschat/<repo>-fixes.git` where it is missing). Leave its `main` and local changes alone; work on the `<release>-fixes` branch. The build never uses these checkouts; it fetches the pinned commits into `<state>/git/`.
6. **Refresh locks.** Delete `build-support/locks/<repo>/` for each repository whose dependencies changed. The build installs unfrozen and records the resolved lock back into the kit; review and commit it.
7. **Build, then compare.** Run the full build. With an official distribution of the same release at hand (A12 Tools bundle: `bin/preview-app-server/<v>/previewapp-server-<v>.jar`), run `python3.13 scripts/compare_reference.py <that jar> <state>/maven`; every shared kernel and metamodel jar should report SAME, except the DIFFs UPSTREAM-STATUS.md explains under validation boundaries.
8. **Update the docs**: README.md (release names, versions), UPSTREAM-STATUS.md (fork commits, boundaries), and this runbook if a step changed.

## Forks

When a public release export cannot build as published (a wrong coordinate, a missing model file), the correction goes into a public fork `mbackschat/<repo>-fixes` (EUPL, like upstream). Its branch `<release>-fixes` starts at mgm-tp's release commit and adds one commit per correction. The manifest's `forks` map names the fork's URL, and `repositories` pins the branch head; the bootstrap fetches that commit from the fork, even into a cache cloned from mgm-tp. A file taken from an mgm distribution must be copied verbatim from an artifact whose license permits redistribution. It must also be generation input, not derived output: for sibling models present in both, the distribution's copies must be byte-identical to the public export's files. Record every fork commit and its reason in UPSTREAM-STATUS.md. Retire a fork as soon as mgm-tp publishes the fixes.
