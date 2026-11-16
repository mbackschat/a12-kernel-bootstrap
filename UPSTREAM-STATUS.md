# Public ext2 integration notes

Target: **A12 2026.06-ext2**, kernel **31.3.1**, base **30.1.1**. The exact source commits are recorded in [the release manifest](releases/2026.06-ext2.json). a12-utils, a12-kernel-antlr4 and a12-dataservices-wcf published no ext2 release; they keep their ext1 commits.

Every deviation from the public exports is listed here. This repository holds no A12 content: corrections live as commits in temporary public forks, which the manifest's `forks` map pins in place of the mgm-tp repository. Each fork branch `2026.06-ext2-fixes` starts at mgm-tp's ext2 release commit; retire a fork as soon as mgm-tp publishes its fixes.

## Excluded feature: DependencyModel

The public metamodel export `fee5d90` declares DependencyModel 1.4 but omits its generation inputs. The bootstrap pins that unmodified upstream commit. No Tools-distribution files may be copied, extracted, vendored or published by this build.

The kernel fork removes the isolated experimental DependencyModel implementation: six Java files from the facade and six from the runtime, its four metamodel dependencies, and the runtime serializer dependency introduced solely for it. The public runtime dependency interfaces and their existing default implementation remain unchanged. Normal validation, computation, structural mapping, workspace conversion and code generation remain supported. Experimental hidden-entity handling and alternative validation-message processing are excluded; consumers requiring that subsystem need a complete official distribution or a future public export with its inputs.

The initial exclusion check compiled the remaining 356 runtime/facade sources without any DependencyModel artifact, exercised the release Java smoke check and all Java showcases, generated and compiled typed accessors, and matched all eight Java/TypeScript parity results. The release build additionally rejects excluded classes/resources and Maven dependency metadata before installation. CI repeats the full build and downstream consumer checks from public inputs.

### Retiring the DependencyModel exclusion

Recheck this exclusion on every kernel upgrade. It can be retired when the matching public exports supply all generation inputs and dependencies needed by the subsystem, or when upstream removes the subsystem and its dependencies. A new release number alone does not establish either condition; verify the pinned public sources and a clean build.

1. Start the new kernel fixes branch from its upstream release and omit exclusion commit `44e051d` when it is no longer needed. Carry forward only compatibility fixes that still apply. Remove the kernel fork mapping entirely when none remain.
2. If the feature is restored, update the exclusion checks in [scripts/build_release.py](scripts/build_release.py), their consumer use in [scripts/check_consumer.py](scripts/check_consumer.py), and the regression expectations in [tests/test_bootstrap.py](tests/test_bootstrap.py). The current guards deliberately reject DependencyModel artifacts, including legitimate future public ones. Replace those expectations with checks for the restored release's intended artifacts and a functional regression check for the restored feature; retain public-source isolation and verified-release checks. If upstream removes the feature, review the guards against that release's contract instead.
3. Build in a fresh state directory using only public inputs. Require release smoke checks, the downstream demo checks, and both repositories' GitHub CI to pass. The existing demo does not exercise the excluded feature, so its success alone cannot verify restoration.
4. Update the release manifest, [README.md](README.md), this status record, and the demo's documented feature scope and bootstrap workflow pin. Record which upstream release made the exclusion unnecessary.

## Fork: a12-kernel (compatibility fixes)

[mbackschat/a12-kernel-fixes](https://github.com/mbackschat/a12-kernel-fixes/commits/2026.06-ext2-fixes), on top of `6e6b3a6`:

| Commit | Public export inconsistency | Correction |
| --- | --- | --- |
| `0097f2c` | Workspace converter requests unpublished WCF API 0.3.0 | Build the exported WCF API 1.1.3 and reference its real version |
| `03affc9` | Structural mapping requests a missing `a12` field-attributes variant | Use the exported `a12types` variant and its generated typedef classes (`DATE_FORMAT_2`, `DATE_RANGE_FORMAT_2`, …) |
| `13dbb2c` | TypeScript runtime root export points to a nonexistent file | Point it to the compiled runtime entry point |
| `ecc77b5` | `npm_pack` can reuse a stale tarball after package metadata changes | Declare `package.json` as a task input |
| `9dd68c4` | The root npm workspace newly lists the kernel codemod, which pins devtools codemod 2.2.2 while the devtools export carries 2.2.3; the codemod is no module of the kernel Gradle build and no release tarball | Drop it from the root workspace list; codemods are separate products, as in ext1 |
| `d7cefcd` | ext2 dropped `kernel-md-document-v2`'s Javadoc-only classpath, so its 19 links into the `kernel-md-documentmodel` model API (`IDocumentModel`, `IField`, `IGroup`, …) no longer resolve; upstream's `failOnError = false` turns them into dead text | Restore the ext1 classpath |
| `44e051d` | The experimental DependencyModel requires model inputs absent from the public export | Remove the isolated implementation and its dependencies; preserve the existing public runtime dependency interfaces |

## Fork: a12-base (plugin versions)

[mbackschat/a12-base-fixes](https://github.com/mbackschat/a12-base-fixes/commits/2026.06-ext2-fixes), on top of `3160b1c`:

| Commit | Public export inconsistency | Correction |
| --- | --- | --- |
| `2f78e43` | Base requests devtools Gradle plugins `integration` 0.1.11 and `build-utilities` 0.7.0; the public devtools ext2 export still builds 0.1.8 and 0.5.0, and neither newer version is published | Reference the exported versions, and call `Helper.getVersion` with the file-based signature 0.5.0 provides (same inputs; base only loses the lazy provider) |

## Generation and prerequisite wiring

The WCF API build compiles the unchanged ext1 WCF sources against this release's base: its catalog key `a12BaseVersion` is the one upstream's own `a12DependencyVersions` task moves per release. WCF's own tests run in that stage.

Inside the kernel build, [an init script](build-support/kernel-projects.init.gradle) resolves the kernel's own coordinates to its projects: the remaining metamodel POMs in Maven local name kernel modules that this build has not published yet.

No placeholder APIs, empty validators or fabricated artifact versions are used.

The metamodel artifacts to generate are derived from the pinned kernel catalog and build scripts at build time. The [bootstrap generation build](build-support/java/build.gradle) reuses the upstream Kotlin metamodel catalog and include-restoration utilities and compiles the actual typed-accessor generator from this kernel. Resource jars carry the same files as upstream's, including the `-ER-<n>` copies named after the extension release.

The validator entry point calls upstream `ExternalDocumentModelService`. Since ext2 the variant is part of the package prefix (A12K-3986), so it passes the catalog's prefix unchanged and preserves model IDs, fields and rules. The common validator has a genuine bootstrap cycle: its first seed uses upstream's explicit bootstrap flag, followed by required regeneration with metamodel validation enabled. The flag is never enabled for the final build.

The WCF API's root build requires private publishing/licensing plugins. The [small API build](build-support/wcf/build.gradle) compiles the unchanged API sources using its upstream dependency catalog and preserves the licenses.

TypeScript prerequisites use selected dependency workspaces and a temporary loopback npm registry, so npm resolves the locally built packages, including its ANTLR package alias. Each workspace runs on the pnpm major it declares: 12.3.4 for base, logging, localization and the code editor; 11.17.0 for devtools and utils. devtools' pinned 11.13.0 is marked broken on npm, utils' workspace settings are rejected by pnpm 12, and pnpm 12 no longer matches the `./*` workspace globs that devtools' Gradle plugin tests use. Every pnpm call uses the isolated store through `pnpm_config_store_dir`: a `pnpm run` against a different store relinks `node_modules`, which silently undid the code editor's antlr4 type correction. Trusted semver 7.8.5 and chokidar 4.0.1 resolve provenance-policy failures without disabling verification. The code-editor build uses the available tsconfig 2.0.1.

Gradle 9.8.2 runs every stage. JDKs 21 and 25 are required by the upstream kernel and base builds respectively.

## Validation boundaries

The native kernel release tasks include all modules from its settings, with the explicitly excluded DependencyModel implementation removed from the fork. The bootstrap builds source/javadoc jars, CLI jars, Maven publications and all five TypeScript tarballs. Generated validators must complete their validated pass.

Before the DependencyModel exclusion, built jars were compared by entry names with their counterparts in the A12 Tools 2026.06-ext2 bundle ([scripts/compare_reference.py](scripts/compare_reference.py)). Every validator and resource jar matches, as do the typings, with two exceptions caused by the generator, not the input. Upstream generated its typings with a pre-release kernel 31.0.1 generator that nests typedef enums under the views (e.g. `mm_mappingmodel_2…_content.MappingType`, `_source.SortType`). Every public kernel generator, ext0 to ext2, emits one shared class per typedef instead (`typedefs.MAPPING_KEY_3`), and no public source reproduces the older form. This affects `mmtypings-mm_mappingmodel-2` and `mmtypings-extmpinternal-mm_smm_fieldtypechecks-1-a12`. The kernel itself references neither form; consumers that import those nested enums from upstream's jar need the shared typedef classes instead.

The reduced build also intentionally lacks the DependencyModel implementation classes in the facade/runtime jars and omits its four metamodel artifacts entirely. These are expected differences from the official distribution; the comparison script only compares shared jars.

The kernel public export does not include runnable unit-test suites. Its `npm_test` tasks report missing test files, and its Java test tasks report `NO-SOURCE`. The bootstrap does not suppress failing assertions or label these as passing upstream tests. It runs available prerequisite suites and independent [Java](build-support/smoke/src/main/java/ReleaseSmoke.java) and [TypeScript](build-support/tests/kernel.test.mjs) release checks. The TypeScript checks install the tarballs into a separate consumer project, which catches broken package exports that workspace compilation alone misses.

The build registers the JDK's documentation tags and makes Javadoc errors fatal. External JDK API links use a package index created from the installed JDK's module exports, so documentation generation works without contacting Oracle's website. Ordinary documentation/deprecation warnings remain visible in the logs.
