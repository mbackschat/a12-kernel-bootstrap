#!/usr/bin/env bash
#
# bootstrap.sh — make the A12 Kernel available to any consumer project, from PUBLIC sources only.
#
# It (re-)runs, idempotently:
#   1. clone the needed A12 repos from GitHub (siblings of this repo by default),
#   2. apply the local patches in ./patches (build-utilities stub + a12-kernel-mm fixes),
#   3. publish the kernel + its A12 dependencies to your local Maven repo (~/.m2),
#      in the staged "bootstrap" order (base -> mm typings/dmjsons -> validator seed ->
#      rest -> kernel), so a consumer can resolve `com.mgmtp.a12.kernel:kernel-md-facade`.
#
# Only public sources are used — GitHub, Maven Central, and mavenLocal.
#
# Usage:
#   ./bootstrap.sh [--skip-clone] [--skip-patch] [--skip-publish] [-h|--help]
#
# Override locations / tools via environment variables (defaults in CONFIG below):
#   A12_ROOT, A12_KERNEL_DIR, A12_BASE_DIR, A12_MM_DIR, A12_DEVTOOLS_DIR,
#   GITHUB_ORG_URL, GRADLE_VERSION, GRADLE_BIN, GRADLE_DIST_DIR, A12_GRADLE_USER_HOME,
#   JAVA21_HOME, JAVA25_HOME, A12_CONSUMER_DIR
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ----------------------------- CONFIG (override via env) -----------------------------
: "${A12_ROOT:=$(cd "$SCRIPT_DIR/.." && pwd)}"        # where sibling repos live / get cloned (this repo's parent)
: "${A12_KERNEL_DIR:=$A12_ROOT/a12-kernel}"
: "${A12_BASE_DIR:=$A12_ROOT/a12-base}"
: "${A12_MM_DIR:=$A12_ROOT/a12-kernel-mm}"
: "${A12_DEVTOOLS_DIR:=$A12_ROOT/a12-devtools}"
: "${GITHUB_ORG_URL:=https://github.com/mgm-tp}"
: "${GRADLE_VERSION:=9.0.0}"                          # 9.5.1 is incompatible with a12-kernel-mm
: "${GRADLE_DIST_DIR:=$A12_ROOT/.gradle-dist}"
: "${A12_GRADLE_USER_HOME:=$A12_ROOT/.gradle-isolated}"   # public-repos-only Gradle home
: "${JAVA21_HOME:=$(/usr/libexec/java_home -v 21 2>/dev/null || true)}"   # runs Gradle
: "${JAVA25_HOME:=$(/usr/libexec/java_home -v 25 2>/dev/null || true)}"   # toolchain for build-utilities
: "${A12_CONSUMER_DIR:=}"                             # optional: a consumer project dir, used only to print a ready-to-run command at the end

# Canonical version pins this kit publishes under (overridable: a consumer needing a different
# version can export KERNEL_VERSION / BASE_VERSION before running).
BASE_VERSION=29.3.0     # the a12-base version the kernel pins (publish under this)
KERNEL_VERSION=30.8.1   # kernel version published (consumers pin this in their own build)

# On any non-zero exit, hint that it may be a version mismatch (a freshly cloned repo may have moved
# past these pins). Harmless on success (rc 0).
trap 'rc=$?; if [ "$rc" -ne 0 ]; then
  echo "" >&2
  echo "bootstrap.sh exited with code $rc." >&2
  echo "A common cause is a VERSION MISMATCH: this kit publishes kernel $KERNEL_VERSION and a12-base $BASE_VERSION," >&2
  echo "but a freshly cloned A12 repo may be at a different (newer) version. Build the matching release of" >&2
  echo "a12-kernel / a12-kernel-mm, export KERNEL_VERSION/BASE_VERSION to match, or align your consumer pins." >&2
fi' EXIT

# A12 dependency artifacts the kernel needs (project names within each repo).
BASE_MODULES=( base-parent base-bom model-api model-consistency model-migration-api model-utils model-marshalling )
MM_TYPINGS=( mmtypings-ct_model_header-1 mmtypings-ct_selection-v1 mmtypings-mm_combinationmodel-1
             mmtypings-mm_mappingmodel-2 mmtypings-mm_selectionmodel-2 mmtypings-mm_structuralmappingmodel-1
             mmtypings-extmpinternal-mm_smm_fieldtypechecks-1-a12 )
MM_DMJSONS=( mmdmjsons-extmpinternal-mm_combinationmodel-1-none mmdmjsons-extmpinternal-mm_combinationmodel-1-codegen
             mmdmjsons-extmpinternal-mm_mappingmodel-2-none mmdmjsons-extmpinternal-mm_mappingmodel-2-codegen
             mmdmjsons-extmpinternal-mm_selectionmodel-2-none mmdmjsons-extmpinternal-mm_selectionmodel-2-codegen
             mmdmjsons-extmpinternal-mm_structuralmappingmodel-1-none mmdmjsons-extmpinternal-mm_structuralmappingmodel-1-codegen )
MM_SEED=mmvalidators-extmpinternal-mm_common-v2-codegen          # bootstrap seed (built with the env var)
MM_VALIDATORS=( mmvalidators-extmpinternal-mm_combinationmodel-1-codegen mmvalidators-extmpinternal-mm_mappingmodel-2-codegen
                mmvalidators-extmpinternal-mm_selectionmodel-2-codegen mmvalidators-extmpinternal-mm_smm_fieldtypechecks-1-codegen
                mmvalidators-extmpinternal-mm_structuralmappingmodel-1-codegen )
# Kernel modules (everything except the structural-mapping subtree, which needs an mm artifact
# absent from the public export, and the TS-only modules).
KERNEL_MODULES=( kernel-conversion-java kernel-core-base-utils kernel-core-calc kernel-core-codegen
  kernel-core-codegen-base kernel-core-codegen-condition kernel-core-codegen-entities kernel-core-codegen-meta-base
  kernel-core-codegen-rules kernel-core-customfieldtype-impl kernel-core-extmpspecifics kernel-core-facade
  kernel-core-ontheflytesting kernel-core-parser kernel-core-parsetree-api kernel-core-runtime-30-8
  kernel-core-service kernel-core-tool-api kernel-core-utils kernel-mapping-rt-api kernel-md-a12internal
  kernel-md-combination-model kernel-md-document-api kernel-md-document-service kernel-md-document-v2
  kernel-md-facade kernel-md-join kernel-md-model kernel-md-model-api kernel-md-model-migration
  kernel-md-runtime-api kernel-md-runtime-service kernel-md-serializer kernel-md-typed-accessor-gen kernel-md-util )

DO_CLONE=1; DO_PATCH=1; DO_PUBLISH=1
for arg in "$@"; do case "$arg" in
  --skip-clone) DO_CLONE=0 ;; --skip-patch) DO_PATCH=0 ;; --skip-publish) DO_PUBLISH=0 ;;
  -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
  *) echo "unknown arg: $arg" >&2; exit 2 ;;
esac; done

log(){ printf '\n\033[1m== %s ==\033[0m\n' "$*"; }
die(){ echo "ERROR: $*" >&2; exit 1; }

# ----------------------------- tool checks -----------------------------
[ -n "$JAVA21_HOME" ] || die "No JDK 21 found. Install one or set JAVA21_HOME (e.g. \$(/usr/libexec/java_home -v 21))."
[ -d "$JAVA21_HOME" ] || die "JAVA21_HOME does not exist: $JAVA21_HOME"
if [ -z "$JAVA25_HOME" ]; then
  echo "WARNING: no JDK 25 detected. a12-devtools' build-utilities declares a Java 25 toolchain;" >&2
  echo "         install a JDK 25 (Gradle auto-detects Homebrew/SDKMAN/system) or set JAVA25_HOME." >&2
fi

ensure_gradle(){
  if [ -n "${GRADLE_BIN:-}" ] && [ -x "$GRADLE_BIN" ]; then return; fi
  GRADLE_BIN="$GRADLE_DIST_DIR/gradle-$GRADLE_VERSION/bin/gradle"
  if [ ! -x "$GRADLE_BIN" ]; then
    log "Downloading Gradle $GRADLE_VERSION (public services.gradle.org)"
    mkdir -p "$GRADLE_DIST_DIR"
    ( cd "$GRADLE_DIST_DIR" \
      && curl -fsSL -O "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
      && unzip -q -o "gradle-${GRADLE_VERSION}-bin.zip" )
  fi
  [ -x "$GRADLE_BIN" ] || die "Gradle not available at $GRADLE_BIN"
}

ensure_gradle_home(){
  mkdir -p "$A12_GRADLE_USER_HOME/init.d"
  cp "$SCRIPT_DIR/gradle/public-repos.init.gradle" "$A12_GRADLE_USER_HOME/init.d/public-repos.init.gradle"
}

# run Gradle: isolated (public-only) home, on JDK 21, no daemon/config-cache.
g(){ JAVA_HOME="$JAVA21_HOME" GRADLE_USER_HOME="$A12_GRADLE_USER_HOME" \
       "$GRADLE_BIN" --no-daemon --console=plain --no-configuration-cache "$@"; }

# ----------------------------- 1. clone -----------------------------
clone_one(){ # <dir> <repo-name>
  local dir="$1" name="$2"
  if [ -d "$dir/.git" ]; then echo "  present: $name ($dir)"; return; fi
  log "Cloning $name -> $dir"; git clone "$GITHUB_ORG_URL/$name.git" "$dir"
}
if [ "$DO_CLONE" = 1 ]; then
  log "Clone (missing) sibling repos from $GITHUB_ORG_URL"
  clone_one "$A12_KERNEL_DIR" a12-kernel
  clone_one "$A12_BASE_DIR" a12-base
  clone_one "$A12_MM_DIR" a12-kernel-mm
  clone_one "$A12_DEVTOOLS_DIR" a12-devtools
fi

# ----------------------------- 2. patch -----------------------------
apply_mm_patch(){
  local patch="$SCRIPT_DIR/patches/a12-kernel-mm.patch"
  if git -C "$A12_MM_DIR" apply --reverse --check "$patch" >/dev/null 2>&1; then
    echo "  a12-kernel-mm: patch already applied"; return; fi
  if git -C "$A12_MM_DIR" apply --check "$patch" >/dev/null 2>&1; then
    git -C "$A12_MM_DIR" apply "$patch"; echo "  a12-kernel-mm: patch applied"
  else
    die "a12-kernel-mm patch does not apply cleanly (upstream may have changed). See $patch"
  fi
}
install_build_utilities_stub(){
  # The build-utilities plugin source is stripped from the OSS export; install our stub.
  # (It is git-ignored in a12-devtools due to a 'gradle/' .gitignore rule — it just needs to be on disk.)
  local dest="$A12_DEVTOOLS_DIR/gradle-plugins/build-utilities"
  [ -d "$dest" ] || die "build-utilities dir not found: $dest"
  cp -R "$SCRIPT_DIR/patches/build-utilities-stub/src" "$dest/"
  echo "  a12-devtools: build-utilities stub installed"
}
if [ "$DO_PATCH" = 1 ]; then
  log "Apply patches"
  apply_mm_patch
  install_build_utilities_stub
fi

# ----------------------------- 3. publish to mavenLocal -----------------------------
publish(){
  ensure_gradle; ensure_gradle_home
  local skipTests=( -x :test-mmtypings:test -x :test-mmdmjsons:test -x :test-mmvalidators:test )

  log "Stage 1/8: build-utilities -> mavenLocal"
  g -p "$A12_DEVTOOLS_DIR" :gradle-plugins:build-utilities:publishToMavenLocal

  log "Stage 2/8: a12-base @ $BASE_VERSION -> mavenLocal"
  local bt=(); for m in "${BASE_MODULES[@]}"; do bt+=( ":$m:publishToMavenLocal" ); done
  g -p "$A12_BASE_DIR" -Pversion="$BASE_VERSION" "${bt[@]}"

  log "Stage 3/8: kernel composite APIs -> mavenLocal"
  g -p "$A12_KERNEL_DIR/kernel-core-customfieldtype-api" publishToMavenLocal
  g -p "$A12_KERNEL_DIR/kernel-core-runtime-api" publishToMavenLocal

  log "Stage 4/8: mm typings -> mavenLocal (kernel typed-accessor-gen from source via composite)"
  local tt=(); for a in "${MM_TYPINGS[@]}"; do tt+=( ":mmtypings:$a:publishToMavenLocal" ); done
  g -p "$A12_MM_DIR" --include-build "$A12_KERNEL_DIR" --no-parallel "${skipTests[@]}" "${tt[@]}"

  log "Stage 5/8: mm dmjsons -> mavenLocal (needs Node/npm for npm_pack)"
  local dt=(); for a in "${MM_DMJSONS[@]}"; do dt+=( ":mmdmjsons:$a:publishToMavenLocal" ); done
  g -p "$A12_MM_DIR" --include-build "$A12_KERNEL_DIR" --no-parallel "${skipTests[@]}" "${dt[@]}"

  log "Stage 6/8: mm_common validator SEED (bootstrap env var) -> mavenLocal"
  A12_KERNEL_BOOTSTRAP_VALIDATORS_DISABLE_MM_VALIDATION=true \
    g -p "$A12_MM_DIR" --include-build "$A12_KERNEL_DIR" "${skipTests[@]}" \
      ":mmvalidators:$MM_SEED:publishToMavenLocal"

  log "Stage 7/8: remaining mm validators -> mavenLocal"
  local vt=(); for a in "${MM_VALIDATORS[@]}"; do vt+=( ":mmvalidators:$a:publishToMavenLocal" ); done
  g -p "$A12_MM_DIR" --include-build "$A12_KERNEL_DIR" --no-parallel "${skipTests[@]}" "${vt[@]}"

  log "Stage 8/8: kernel modules -> mavenLocal"
  local kt=(); for m in "${KERNEL_MODULES[@]}"; do kt+=( ":$m:publishToMavenLocal" ); done
  g -p "$A12_KERNEL_DIR" --continue "${kt[@]}"
}
if [ "$DO_PUBLISH" = 1 ]; then publish; fi

# Non-fatal: warn if the kernel version now in mavenLocal differs from this kit's pin. The publish
# can succeed yet produce a version a consumer's build can't resolve (e.g. the cloned repo moved on).
check_versions() {
  local facade_dir="${HOME}/.m2/repository/com/mgmtp/a12/kernel/kernel-md-facade"
  if [ -d "$facade_dir" ] && [ ! -d "$facade_dir/$KERNEL_VERSION" ]; then
    local found; found=$(ls -1 "$facade_dir" 2>/dev/null | grep -vi 'maven-metadata' | tr '\n' ' ')
    echo "" >&2
    echo "WARNING: this kit publishes kernel $KERNEL_VERSION, but mavenLocal holds" >&2
    echo "         kernel-md-facade version(s): ${found:-none}. A consumer pinned to $KERNEL_VERSION won't resolve until they match —" >&2
    echo "         align your consumer's pin, export KERNEL_VERSION, or build the a12-kernel release matching $KERNEL_VERSION." >&2
  fi
}
check_versions

log "Done. The kernel + deps have been published to your local Maven repository (~/.m2 unless maven.repo.local is overridden)."
echo "To build a consumer project, run its build with this isolated, public-only Gradle home:"
echo "  GRADLE_USER_HOME=\"$A12_GRADLE_USER_HOME\" JAVA_HOME=\"$JAVA21_HOME\" \\"
echo "    \"${GRADLE_BIN:-$GRADLE_DIST_DIR/gradle-$GRADLE_VERSION/bin/gradle}\" -p \"${A12_CONSUMER_DIR:-<your-project-dir>}\" --no-daemon <task>"
