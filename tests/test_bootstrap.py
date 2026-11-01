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


if __name__ == "__main__":
    unittest.main()
