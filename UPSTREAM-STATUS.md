# Public ext1 integration notes

Target: **A12 2026.06-ext1**, kernel **31.1.1**, base **30.0.2**.
The exact ten public source commits are recorded in
[the release manifest](releases/2026.06-ext1.json). The public metamodel repository
still supplies its ext0 export; the kernel specifies the metamodel artifact
versions and labels used by this build.

The previous plugin stub, old metamodel patch, Java-only staging and structural
mapping exclusion are removed. The bootstrap uses real upstream implementations.
The remaining integration is explicit and applies only to generated source trees.

## Compatibility fixes

[ext1-compatibility.patch](build-support/ext1-compatibility.patch) contains these
corrections to the public kernel export:

| Public export inconsistency | Correction |
| --- | --- |
| Workspace converter requests unpublished WCF API 0.2.0 | Build the exported WCF API 1.1.3 and reference its real version |
| Structural mapping requests a missing `a12` field-attributes variant | Use the exported `a12types` variant and its generated typedef enums |
| Structural mapping loads its field-check model without declaring the resource dependency | Add the actual generated `mmdmjsons` artifact to its runtime dependencies |
| TypeScript runtime root export points to a nonexistent file | Point it to the compiled runtime entry point |
| `npm_pack` can reuse a stale tarball after package metadata changes | Declare `package.json` as a task input |

No placeholder APIs, empty validators or fabricated artifact versions are used.
The enum migration changes references to generated types, not the validation
rules. Functional tests exercise both acceptance and rejection through the real
structural mapping validator.

## Generation and prerequisite wiring

The public metamodel Gradle aggregate references test projects absent from the
export, old module names, and a pre-release typed-accessor generator. The
[bootstrap generation build](build-support/java/build.gradle) reuses the upstream
Kotlin metamodel catalog and include-restoration utilities, and compiles the
actual typed-accessor generator from ext1. It generates all metamodel artifacts
needed by the complete kernel, including structural mapping.

The validator entry point calls upstream `ExternalDocumentModelService`; it
supplies the variant-qualified generation namespace still required by kernel
consumers after ext1 removed the old CLI variant option. It preserves model IDs,
fields and rules. The common validator has a genuine bootstrap cycle: its first
seed uses upstream's explicit bootstrap flag, followed by required regeneration
with metamodel validation enabled. The flag is never enabled for the final build.

The WCF API's root build requires private publishing/licensing plugins. The
[small API build](build-support/wcf/build.gradle) compiles the unchanged API
sources using its upstream dependency catalog and preserves the licenses.

TypeScript prerequisites use selected dependency workspaces and a temporary
loopback npm registry. This lets npm resolve the actual locally built packages,
including its ANTLR package alias. The selected workspaces retain their native
build/test scripts; unrelated supporting-repository codemods and applications
are separate products. pnpm 11.17.0 replaces devtools' broken 11.13.0 package.
Trusted semver 7.8.5 and chokidar 4.0.1 resolve provenance-policy failures without
disabling verification. The code-editor build uses the available tsconfig 2.0.1.

Gradle 9.8.2 supports the devtools configuration-cache tests that fail on 9.0.0.
JDKs 21 and 25 are required by the upstream kernel and base builds respectively.

## Validation boundaries

The full native kernel release tasks include all modules from its settings,
including both standalone Java APIs, structural mapping and workspace conversion.
The bootstrap builds source/javadoc jars, CLI jars, Maven publications and all
five TypeScript tarballs. Generated validators must complete their validated pass.

The kernel public export does not include runnable unit-test suites. Its
`npm_test` tasks report missing test files, and its Java test tasks report
`NO-SOURCE`. The bootstrap does not suppress failing assertions or label these
as passing upstream tests. It runs available prerequisite suites and independent
[Java](build-support/smoke/src/main/java/ReleaseSmoke.java) and
[TypeScript](build-support/tests/kernel.test.mjs) release checks. The TypeScript
checks install the tarballs into a separate consumer project, which catches
broken package exports that workspace compilation alone misses.

The separate [Javadoc correction patch](build-support/ext1-javadoc.patch) fixes
malformed HTML in upstream comments. The build registers the JDK's documentation
tags and makes Javadoc errors fatal. External JDK API links use a package index
created from the installed JDK's module exports, so documentation generation
works without contacting Oracle's website. Ordinary documentation/deprecation
warnings remain visible in the logs.
