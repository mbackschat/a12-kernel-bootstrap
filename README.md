# a12-kernel-bootstrap

Build **A12 2026.06-ext1 / kernel 31.1.1** from pinned public sources, including
Java, TypeScript, structural mapping, workspace conversion, code generation,
CLI jars, Maven publications and npm tarballs.

The old build-utilities stub, obsolete metamodel patch and Java-only staging
build are removed. The bootstrap builds the real upstream prerequisites and
all projects selected by the kernel's release settings. Small remaining
compatibility fixes are documented in [UPSTREAM-STATUS.md](UPSTREAM-STATUS.md).

## Build

Install Git, Python 3.12+, Node.js 24 with npm, and complete JDKs 21 and 25. JDK 25 is required by the base modules; the kernel targets Java 21.

Check the toolchain first. `--doctor` reports each prerequisite as OK or MISSING, and for a wrong Node.js on PATH it prints the `export PATH=…` line for any installed Node.js 24 (Homebrew `node@24`, nvm). It neither creates state nor builds.

```bash
./bootstrap.sh --doctor
./bootstrap.sh
```

`bootstrap.sh` uses `python3` when it is 3.12+, otherwise the newest `python3.N` on PATH. JDKs are found through `JAVA21_HOME` / `JAVA25_HOME`, `JAVA_HOME`, or on macOS `/usr/libexec/java_home`; set the variables to select specific installations.

Gradle 9.8.2 is downloaded from its official distribution and checked against its
published SHA-256. `GRADLE_BIN` can select an existing installation of the
version pinned in [the release manifest](releases/2026.06-ext1.json).

By default, state is kept in `../.a12-bootstrap/2026.06-ext1`. Override it with
`A12_BOOTSTRAP_HOME` or `--home /path/to/state`. Existing project checkouts are
not modified. Git caches and generated source trees live under that directory;
a changed source pin requires a new state directory.

```bash
./bootstrap.sh --doctor           # check installed tools, suggest fixes
./bootstrap.sh --plan             # show the scope
./bootstrap.sh --prepare          # fetch/extract sources without building
./bootstrap.sh --check-upstream   # inspect public refs without changing pins
python3 -m unittest discover -s tests -v
```

## Outputs and verification

A successful run writes `build-success.json` only after building and checking the release. A failure exits nonzero and identifies the stage log under `logs/`.

| Path within the state directory | Contents |
| --- | --- |
| `maven/` | Maven artifacts, including kernel sources, Javadocs and CLI jars |
| `npm-artifacts/` | Five kernel TypeScript packages and their source-built prerequisites |
| `logs/` | Build, test and functional-check output for each stage |
| `npm-smoke/` | Independent consumer installation of the built kernel tarballs |
| `sources/` | Pinned upstream exports with documented build integration applied |

The bootstrap uses a temporary npm registry bound to loopback to resolve the source-built A12 packages. It stops that process on exit and never publishes to a public registry. TLS, downloaded artifact checksums and upstream dependency trust policies remain enabled.

### Local Maven repository (`~/.m2`)

After `build-success.json` is written, the release's Maven artifacts are installed into `~/.m2/repository`, so Maven and Gradle projects pick them up through `mavenLocal()` as they did with the 2025.06 kit. A failed or unverified build never reaches `~/.m2`.

The install follows `publishToMavenLocal` semantics: files of this release's coordinates are replaced (so a rerun refreshes them), every other version is left untouched (2025.06-ext5 and other releases coexist), and each artifact's `maven-metadata-local.xml` is merged, adding this release's versions to the list and making them `latest`/`release`. That only affects dynamic selectors such as `latest.release`; pinned versions resolve as before. A `<localRepository>` set in Maven's `settings.xml` is not honoured.

**Why the build does not publish to `~/.m2` directly.** The build passes `-Dmaven.repo.local=<state>/maven` to every Gradle stage, because `mavenLocal()` is also how later stages resolve earlier ones (devtools plugins, base, WCF API, metamodels). Isolated, only artifacts built by this run can satisfy those dependencies. Sharing `~/.m2` would let an older or foreign jar at the same coordinates, such as an earlier run's output or a vendor binary, stand in for a broken from-source stage and hide it. Installing into `~/.m2` is therefore a separate delivery step after verification.

**Issue fixed.** The first 2026.06-ext1 version of this kit (commit 70e6b58) isolated the build but never delivered the result: artifacts stayed in `<state>/maven`, and consumers had to point `-Dmaven.repo.local` at it, unlike the 2025.06 kit, which published to `~/.m2`. Using that state repository as a consumer's local repository also mixes the consumer's own downloads and installs into the release output.

Validation includes the prerequisite libraries' available tests, mandatory
regeneration of the common validator with metamodel validation enabled, and
the kernel's native `build`, `test`, `publishToMavenLocal` and `npm_pack` tasks.
The public kernel export has no runnable Java or TypeScript unit-test suites;
its standalone `npm_test` tasks fail because their test directories are absent.
The bootstrap therefore also runs its own functional checks against the
published Java artifacts and installed npm tarballs: compatible/incompatible
structural mapping, workspace conversion, date comparisons, localization,
IBAN validation, model deserialization/search, and generated lexer behavior.
These checks are release integration tests, not a claim that unpublished
upstream test suites ran.

Supporting repositories are built for the libraries required by this kernel
release. Their unrelated documentation applications, codemods and example
applications are not part of the kernel release. The sibling demo repository
is not rewritten by this script.

## Reproducibility

[releases/2026.06-ext1.json](releases/2026.06-ext1.json) records the public Git commits and release versions. The dependency lockfiles in `build-support/locks/` are installed with frozen/CI checks. Their loopback URL is rebound to the temporary local registry, and the integrity of each A12 package built by this run is bound to the tarball it just packed: gzip output is platform dependent (its header alone records the OS), so a hash recorded on another machine cannot match. A lock that names an A12 package the run has not built fails the build. Every third-party integrity hash stays locked.

Generated sources reuse the upstream metamodel catalog and the actual ext1 generators. The initial common-validator seed is followed by a required validated pass; a seed alone never marks a build complete.

Set `A12_GRADLE_USER_HOME` to reuse a configured Gradle cache or proxy setup.
Otherwise the bootstrap uses its own `gradle-home/`. Java tools may need proxy
and trust-store configuration in restricted environments; no credentials are
required for the public source workflow.
