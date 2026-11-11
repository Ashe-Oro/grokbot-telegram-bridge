#!/usr/bin/env python3
"""Offline runtime permission tests; no ASR venv, ffmpeg, or network needed."""
import contextlib, io, json, os, tempfile, unittest
from unittest.mock import patch
import relay

@contextlib.contextmanager
def umask(mode):
    old = os.umask(mode)
    try:
        yield
    finally:
        os.umask(old)

class TestPermissions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = self.tmp.name
        paths = dict(HOME=home, STATE=os.path.join(home, "state.json"),
                     LOCK=os.path.join(home, "state.lock"), OUTBOX=os.path.join(home, "outbox"),
                     FAILED=os.path.join(home, "outbox", "failed"), MEDIA=os.path.join(home, "media"))
        p = patch.multiple(relay, **paths)
        p.start(); self.addCleanup(p.stop)

    def assert_mode(self, path, mode):
        self.assertEqual(os.stat(path).st_mode & 0o777, mode)

    def test_state_atomic_replace(self):
        with umask(0o022):
            with relay.state():
                pass
            self.assert_mode(relay.STATE, 0o600)
            self.assert_mode(relay.LOCK, 0o600)
            # A stale, manually relaxed temp file must also be tightened before writing.
            with open(relay.STATE + ".tmp", "w"):
                pass
            os.chmod(relay.STATE + ".tmp", 0o644)
            replace = os.replace
            def check_replace(src, dst):
                self.assert_mode(src, 0o600)
                replace(src, dst)
            with patch.object(relay.os, "replace", side_effect=check_replace):
                with relay.state() as s:
                    s["offset"] = 1
            self.assert_mode(relay.STATE, 0o600)
            self.assertFalse(os.path.exists(relay.STATE + ".tmp"))

    def test_runtime_dirs_created_and_existing_tightened(self):
        with umask(0o022):
            relay.secure_runtime()
            paths = (relay.HOME, relay.OUTBOX, relay.FAILED, relay.MEDIA)
            for path in paths:
                self.assert_mode(path, 0o700)
                os.chmod(path, 0o755)
            subdir = os.path.join(relay.MEDIA, "example")
            os.mkdir(subdir, 0o755)
            relay.secure_runtime()
            for path in (*paths, subdir):
                self.assert_mode(path, 0o700)

    def test_migration_backup(self):
        with umask(0o022):
            with open(relay.STATE, "w") as f:
                json.dump({"offset": 0, "allowlist": [], "pending": {}}, f)
            with contextlib.redirect_stdout(io.StringIO()), relay.state(write=False):
                pass
        self.assert_mode(relay.STATE, 0o600)
        self.assert_mode(relay.STATE + ".bak-preroles", 0o600)

    def test_dotenv_warning(self):
        path = os.path.join(self.tmp.name, ".env")
        with open(path, "w") as f:
            f.write("KEY=value\n")
        with patch.dict(os.environ):
            for mode, warns in ((0o644, True), (0o600, False)):
                os.chmod(path, mode)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    relay.load_dotenv(path)
                self.assertEqual(".env is group- or other-readable" in out.getvalue(), warns)
                self.assertNotIn("KEY=value", out.getvalue())
                self.assert_mode(path, mode)     # warning only

    def test_download_permissions(self):
        with patch.dict(os.environ, TELEGRAM_BOT_TOKEN=""), \
             patch.object(relay, "tg", return_value={"file_path": "example"}), \
             patch.object(relay, "_open_file_url", side_effect=lambda *a: io.BytesIO(b"media")), \
             umask(0o022):
            for ext in (".ogg", ".jpg"):
                dest_dir = os.path.join(relay.MEDIA, ext[1:])
                os.makedirs(dest_dir, mode=0o755, exist_ok=True)
                path, size = relay.download_file("example", dest_dir, ext)
                self.assertEqual(size, 5)
                self.assert_mode(dest_dir, 0o700)
                self.assert_mode(path, 0o600)

    def test_runtime_files_tightened(self):
        paths = (relay.STATE, relay.STATE + ".bak-preroles", relay.LOCK,
                 os.path.join(relay.HOME, "transcriber.err"), os.path.join(relay.HOME, "relay.log"))
        for path in paths:
            with open(path, "w"):
                pass
            os.chmod(path, 0o644)
        relay.secure_runtime()
        for path in paths:
            self.assert_mode(path, 0o600)

    def test_approve_creates_private_runtime(self):
        import approve
        with patch.object(relay, "load_dotenv"), patch.object(relay, "configure_paths"), \
             contextlib.redirect_stdout(io.StringIO()), umask(0o022):
            self.assertEqual(approve.main(["--list"]), 0)
        for path in (relay.HOME, relay.OUTBOX, relay.FAILED, relay.MEDIA):
            self.assert_mode(path, 0o700)
        self.assert_mode(relay.LOCK, 0o600)

if __name__ == "__main__":
    unittest.main()
