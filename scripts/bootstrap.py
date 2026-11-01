#!/usr/bin/env python3
"""Build the complete pinned A12 Java and TypeScript release from public sources."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

KIT = Path(__file__).resolve().parents[1]
RELEASE_FILE = KIT / "releases" / "2026.06-ext1.json"


class BootstrapError(RuntimeError):
    pass


def run(argv, *, cwd=None, env=None, capture=False):
    result = subprocess.run([str(a) for a in argv], cwd=cwd, env=env,
                            text=True, stdout=subprocess.PIPE if capture else None)
    if result.returncode:
        raise BootstrapError(f"Command failed ({result.returncode}): {' '.join(map(str, argv))}")
    return result.stdout.strip() if capture else None


def load_release():
    release = json.loads(RELEASE_FILE.read_text())
    for name, commit in release["repositories"].items():
        if not re.fullmatch(r"a12-[a-z0-9-]+", name) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise BootstrapError("Invalid repository identity or commit in release manifest")
    return release


def prepare_sources(state, repositories):
    """Build generated source trees, leaving existing project checkouts alone."""
    for name, commit in repositories.items():
        cache = state / "git" / f"{name}.git"
        source = state / "sources" / name
        marker = source / ".bootstrap-source.json"
        if marker.exists():
            if json.loads(marker.read_text()) != {"repository": name, "commit": commit}:
                raise BootstrapError(f"Source pin changed for {name}; use a new A12_BOOTSTRAP_HOME")
            continue
        if source.exists():
            raise BootstrapError(f"Refusing to overwrite unmarked source directory: {source}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists():
            run(["git", "clone", "--bare", f"https://github.com/mgm-tp/{name}.git", cache])
        run(["git", f"--git-dir={cache}", "cat-file", "-e", f"{commit}^{{commit}}"])
        source.parent.mkdir(parents=True, exist_ok=True)
        # Extract atomically. Interrupted preparation cannot masquerade as a complete tree.
        with tempfile.TemporaryDirectory(dir=source.parent) as temporary:
            temporary = Path(temporary)
            archive = temporary / "source.tar"
            run(["git", f"--git-dir={cache}", "archive", "--format=tar", f"--output={archive}", commit])
            tree = temporary / "tree"
            tree.mkdir()
            with tarfile.open(archive) as tar:
                tar.extractall(tree, filter="data")
            (tree / marker.name).write_text(json.dumps({"repository": name, "commit": commit}) + "\n")
            tree.rename(source)


def verify_checksum(archive, checksum):
    fields = checksum.read_text().strip().split()
    expected = fields[0] if fields else ""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise BootstrapError(f"Invalid SHA-256 checksum: {checksum}")
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected.lower():
        raise BootstrapError(f"SHA-256 mismatch: {archive}; refusing to use this download")


def gradle_binary(state, version):
    supplied = os.environ.get("GRADLE_BIN")
    if supplied:
        return str(Path(supplied).resolve())
    tools = state / "tools"
    binary = tools / f"gradle-{version}" / "bin" / "gradle"
    if binary.exists():
        return str(binary)
    downloads = state / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / f"gradle-{version}-bin.zip"
    checksum = archive.with_suffix(".zip.sha256")
    url = f"https://services.gradle.org/distributions/{archive.name}"
    for destination, source in [(archive, url), (checksum, url + ".sha256")]:
        if not destination.exists():
            with urllib.request.urlopen(source) as response, destination.with_suffix(destination.suffix + ".part").open("wb") as output:
                shutil.copyfileobj(response, output)
            destination.with_suffix(destination.suffix + ".part").rename(destination)
    verify_checksum(archive, checksum)
    with zipfile.ZipFile(archive) as distribution:
        distribution.extractall(tools)
    binary.chmod(0o755)
    return str(binary)


def jdk(major):
    candidates = [os.environ.get(f"JAVA{major}_HOME"), os.environ.get("JAVA_HOME")]
    if sys.platform == "darwin" and Path("/usr/libexec/java_home").exists():
        detected = subprocess.run(["/usr/libexec/java_home", "-v", str(major)], capture_output=True, text=True)
        if detected.returncode == 0:
            candidates.append(detected.stdout.strip())
    for candidate in filter(None, candidates):
        compiler = Path(candidate) / "bin" / "javac"
        if compiler.is_file():
            version = run([compiler, "-version"], capture=True)
            if re.match(rf"javac {major}(?:\.|\s|$)", version):
                return str(Path(candidate).resolve())
    raise BootstrapError(f"A complete JDK {major} is required; set JAVA{major}_HOME (a JRE is insufficient)")


def build_plan():
    return [
        ("Java prerequisites", "Gradle", ["real devtools plugins", "base", "workspace conversion API"]),
        ("Metamodels", "Gradle", ["typed accessors", "resources", "validator seed", "validated regeneration"]),
        ("TypeScript prerequisites", "pnpm/npm", ["devtools", "collections", "logging", "localization", "base", "ANTLR", "code editor"]),
        ("Every kernel module", "Gradle", ["build", "test", "publishToMavenLocal", "npm_pack"]),
        ("Published release artifacts", "Java/Node", ["structural mapping", "workspace conversion", "TypeScript functional tests"]),
    ]


def prepare_javadoc_index(state, jdks):
    directory = state / 'javadoc-api'
    for major, home in jdks.items():
        java = Path(home) / 'bin/java'
        modules = run([java, '--list-modules'], capture=True)
        target = directory / str(major)
        marker = target / 'modules.txt'
        if marker.exists() and marker.read_text() == modules and (target / 'element-list').exists():
            continue
        lines = []
        for module in modules.splitlines():
            name = module.split('@')[0]
            description = run([java, '--describe-module', name], capture=True)
            packages = [line.split()[1] for line in description.splitlines() if line.startswith('exports ')]
            if packages:
                lines += ['module:' + name, *sorted(packages)]
        target.mkdir(parents=True, exist_ok=True)
        (target / 'element-list').write_text('\n'.join(lines) + '\n')
        marker.write_text(modules)
    return str(directory)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true", help="prepare pinned source trees only; does not establish build readiness")
    mode.add_argument("--plan", action="store_true", help="show the complete Java and TypeScript build scope without executing it")
    mode.add_argument("--check-upstream", action="store_true", help="show public branch/tag refs without changing the pinned release")
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("A12_BOOTSTRAP_HOME", KIT.parent / ".a12-bootstrap" / "2026.06-ext1")))
    args = parser.parse_args(argv)
    release = load_release()
    if args.plan:
        print(f"Target: {release['release']} / kernel {release['kernel_version']}")
        for repository, manager, tasks in build_plan():
            print(f"{repository}: {manager} {' '.join(tasks)}")
        return
    if args.check_upstream:
        for name in release["repositories"]:
            print(f"\n{name} (pinned {release['repositories'][name]})", flush=True)
            run(["git", "ls-remote", "--heads", "--tags", f"https://github.com/mgm-tp/{name}.git"])
        return
    state = args.home.resolve()
    state.mkdir(parents=True, exist_ok=True)
    prepare_sources(state, release["repositories"])
    if args.prepare:
        print(f"Prepared {len(release['repositories'])} pinned source trees in {state / 'sources'}; no build was run.")
        return

    env = os.environ.copy()
    env["JAVA_HOME"] = jdk(21)
    java25 = jdk(25)
    env['A12_JAVADOC_DIR'] = prepare_javadoc_index(state, {21: env['JAVA_HOME'], 25: java25})
    env["PATH"] = str(Path(env["JAVA_HOME"]) / "bin") + os.pathsep + env["PATH"]
    gradle_home = Path(env.get("A12_GRADLE_USER_HOME", state / "gradle-home"))
    (gradle_home / "init.d").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KIT / "gradle/public-repos.init.gradle", gradle_home / "init.d/public-repos.init.gradle")
    env["GRADLE_USER_HOME"] = str(gradle_home)
    env["npm_config_cache"] = str(state / "npm-cache")
    env["XDG_CACHE_HOME"] = str(state / "cache")
    env["XDG_DATA_HOME"] = str(state / "data")
    gradle = [gradle_binary(state, release["gradle_version"]), "--console=plain",
              "--no-configuration-cache", "--max-workers=2", f"-Dmaven.repo.local={state / 'maven'}",
              "-I", KIT / "build-support/javadoc.init.gradle",
              f"-Dorg.gradle.java.installations.paths={env['JAVA_HOME']},{java25}"]
    actual_version = run(gradle[:1] + ["--version"], env=env, capture=True)
    if f"Gradle {release['gradle_version']}\n" not in actual_version:
        raise BootstrapError(f"This release requires Gradle {release['gradle_version']}")
    node_version = run(["node", "--version"], env=env, capture=True)
    if not node_version.startswith("v24."):
        raise BootstrapError("Upstream requires Node.js 24")

    from build_release import ReleaseBuilder
    ReleaseBuilder(state, release, gradle, env).build()


if __name__ == "__main__":
    # The build helper imports these shared functions; keep one error class when
    # this file is executed as a script rather than imported as a module.
    sys.modules["bootstrap"] = sys.modules[__name__]
    try:
        main()
    except (BootstrapError, OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"\nBootstrap incomplete: {error}", file=sys.stderr)
        sys.exit(1)
