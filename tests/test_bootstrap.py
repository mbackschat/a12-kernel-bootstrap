import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("bootstrap", Path(__file__).resolve().parents[1] / "scripts/bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bootstrap
spec.loader.exec_module(bootstrap)
helper_spec = importlib.util.spec_from_file_location("build_release", Path(__file__).resolve().parents[1] / "scripts/build_release.py")
build_release = importlib.util.module_from_spec(helper_spec)
helper_spec.loader.exec_module(build_release)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"

    def git(self, *args, cwd=None):
        return subprocess.check_output(["git", *map(str, args)], cwd=cwd, text=True,
                                       stderr=subprocess.DEVNULL).strip()

    def make_cache(self, unsafe_link=False):
        source = self.root / "upstream"
        source.mkdir()
        self.git("init", source)
        (source / "library.txt").write_text("pinned upstream source\n")
        if unsafe_link:
            (source / "escape").symlink_to("../../outside")
        self.git("add", ".", cwd=source)
        self.git("-c", "user.name=Bootstrap Test", "-c", "user.email=test@example.invalid",
                 "commit", "-m", "fixture", cwd=source)
        commit = self.git("rev-parse", "HEAD", cwd=source)
        cache = self.state / "git/a12-fixture.git"
        cache.parent.mkdir(parents=True)
        self.git("clone", "--bare", source, cache)
        return source, commit

    def test_prepare_preserves_upstream_and_reuses_exact_snapshot(self):
        original, commit = self.make_cache()
        bootstrap.prepare_sources(self.state, {"a12-fixture": commit})
        generated = self.state / "sources/a12-fixture"
        self.assertEqual((generated / "library.txt").read_text(), "pinned upstream source\n")
        (generated / "build-output.txt").write_text("retained output")
        bootstrap.prepare_sources(self.state, {"a12-fixture": commit})
        self.assertEqual((generated / "build-output.txt").read_text(), "retained output")
        self.assertEqual(self.git("status", "--porcelain", cwd=original), "")

    def test_unmarked_existing_files_are_never_overwritten(self):
        source = self.state / "sources/a12-fixture"
        source.mkdir(parents=True)
        (source / "user-work.txt").write_text("keep me")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "Refusing to overwrite"):
            bootstrap.prepare_sources(self.state, {"a12-fixture": "1" * 40})
        self.assertEqual((source / "user-work.txt").read_text(), "keep me")

    def test_changed_pin_cannot_silently_reuse_old_build(self):
        _, commit = self.make_cache()
        bootstrap.prepare_sources(self.state, {"a12-fixture": commit})
        with self.assertRaisesRegex(bootstrap.BootstrapError, "Source pin changed"):
            bootstrap.prepare_sources(self.state, {"a12-fixture": "1" * 40})
        metadata = json.loads((self.state / "sources/a12-fixture/.bootstrap-source.json").read_text())
        self.assertEqual(metadata["commit"], commit)

    def test_archive_cannot_escape_source_root(self):
        _, commit = self.make_cache(unsafe_link=True)
        with self.assertRaises(tarfile.FilterError):
            bootstrap.prepare_sources(self.state, {"a12-fixture": commit})
        self.assertFalse((self.state / "sources/a12-fixture").exists())
        self.assertFalse((self.state / "outside").exists())

    def test_tampered_download_is_rejected(self):
        archive = self.root / "distribution.zip"
        checksum = self.root / "distribution.zip.sha256"
        archive.write_bytes(b"verified bytes")
        checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest())
        bootstrap.verify_checksum(archive, checksum)
        archive.write_bytes(b"tampered bytes")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "SHA-256 mismatch"):
            bootstrap.verify_checksum(archive, checksum)
        checksum.write_text("")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "Invalid SHA-256"):
            bootstrap.verify_checksum(archive, checksum)

    def test_failed_build_command_is_not_success(self):
        with self.assertRaisesRegex(bootstrap.BootstrapError, r"Command failed \(7\)"):
            bootstrap.run([sys.executable, "-c", "raise SystemExit(7)"])

    def test_prepare_only_does_not_claim_build_success(self):
        _, commit = self.make_cache()
        with patch.object(bootstrap, "load_release", return_value={"repositories": {"a12-fixture": commit}}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                bootstrap.main(["--prepare", "--home", str(self.state)])
        self.assertIn("no build was run", output.getvalue())
        self.assertNotIn("commands completed", output.getvalue())

    def test_failed_dependency_build_removes_stale_success_record(self):
        self.state.mkdir()
        marker = self.state / "build-success.json"
        marker.write_text('{"old": "success"}')
        builder = build_release.ReleaseBuilder(self.state, {}, ["gradle"], {})
        with patch.object(builder, "build_java_dependencies", side_effect=bootstrap.BootstrapError("compile failed")):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "compile failed"):
                builder.build()
        self.assertFalse(marker.exists())

    def test_failed_artifact_check_prevents_success_and_stops_registry(self):
        self.state.mkdir()
        builder = build_release.ReleaseBuilder(self.state, {}, ["gradle"], {})
        stopped = []

        @contextlib.contextmanager
        def registry():
            builder.registry_url = 'http://127.0.0.1:4873/'
            try:
                yield
            finally:
                stopped.append(True)

        with patch.object(builder, "build_java_dependencies"), \
                patch.object(builder, "registry", registry), \
                patch.object(builder, "build_typescript_dependencies"), \
                patch.object(builder, "stage"), \
                patch.object(builder, "java"), \
                patch.object(builder, "check_typescript_artifacts", side_effect=bootstrap.BootstrapError("broken export")):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "broken export"):
                builder.build()
        self.assertEqual(stopped, [True])
        self.assertFalse((self.state / "build-success.json").exists())


def write_tool(path, script):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return path


class PythonSelectionTests(unittest.TestCase):
    """bootstrap.sh must not hand the build to a Python older than 3.12."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.bin = Path(temporary.name)
        # An isolated PATH keeps host Pythons out; the wrapper only needs these tools.
        for tool in ["dirname", "grep", "sort", "uniq"]:
            (self.bin / tool).symlink_to(subprocess.check_output(["which", tool], text=True).strip())

    def fake_python(self, name, supported):
        write_tool(self.bin / name, f'[ "$1" = -c ] && exit {0 if supported else 1}\necho "{name} $@"\n')

    def run_wrapper(self):
        return subprocess.run(["/bin/bash", Path(__file__).resolve().parents[1] / "bootstrap.sh", "--plan"],
                              env={"PATH": str(self.bin)}, capture_output=True, text=True)

    def test_skips_old_default_python_for_newest_supported_version(self):
        self.fake_python("python3", supported=False)
        self.fake_python("python3.12", supported=True)
        self.fake_python("python3.13", supported=True)
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"^python3\.13 .*/scripts/bootstrap\.py --plan$")

    def test_reports_missing_supported_python(self):
        self.fake_python("python3", supported=False)
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.12+", result.stderr)


class DoctorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path_bin = self.root / "path-bin"
        self.path_bin.mkdir()
        (self.path_bin / "git").symlink_to(subprocess.check_output(["which", "git"], text=True).strip())
        self.release = {"gradle_version": "9.8.2"}

    def fake_node(self, directory, version):
        write_tool(directory / "node", f"echo {version}\n")
        write_tool(directory / "npm", "echo 11.0.0\n")

    def doctor(self, state=None):
        output = io.StringIO()
        env = {"PATH": str(self.path_bin)}
        with patch.object(bootstrap, "jdk", side_effect=lambda major: f"/jdk/{major}"), \
                contextlib.redirect_stdout(output):
            try:
                bootstrap.doctor(self.release, state or self.root / "state", env)
            except bootstrap.BootstrapError as error:
                return output.getvalue(), error
        return output.getvalue(), None

    def test_wrong_node_on_path_points_to_installed_node24(self):
        self.fake_node(self.path_bin, "v26.10.0")
        node24 = self.root / "homebrew/opt/node@24/bin"
        self.fake_node(node24, "v24.22.2")
        with patch.object(bootstrap, "NODE_SEARCH_PATTERNS", [str(self.root / "homebrew/opt/node@*/bin")]):
            output, error = self.doctor()
        self.assertIsNotNone(error)
        self.assertRegex(output, r"MISSING\s+Node\.js 24: .*v26\.10\.0")
        self.assertIn(f'export PATH="{node24}:$PATH"', output)
        self.assertRegex(output, r"OK\s+JDK 21: /jdk/21")

    def test_complete_toolchain_passes_without_creating_state(self):
        self.fake_node(self.path_bin, "v24.22.2")
        state = self.root / "state"
        output, error = self.doctor(state)
        self.assertIsNone(error, output)
        self.assertRegex(output, r"OK\s+Node\.js 24: v24\.22\.2")
        self.assertRegex(output, r"OK\s+Gradle: 9\.8\.2 will be downloaded")
        self.assertNotIn("MISSING", output)
        self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
