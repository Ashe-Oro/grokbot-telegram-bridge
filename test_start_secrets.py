#!/usr/bin/env python3
"""Offline tests for start.sh secrets-file loading. No network, no real secrets."""
import os
import subprocess
import signal
import shutil
import time
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
START_SH = ROOT / "start.sh"

# Dummy values only. Tests assert these never appear in command output.
TOKEN = "unit-test-token-aaa"
URL = "https://example.invalid/hook"
KEY = "unit-test-webhook-key-bbb"
LLM_KEY = "unit-test-member-key-ccc"
FRESH_TOKEN = "unit-test-token-fresh-zzz"
FRESH_KEY = "unit-test-webhook-key-fresh-yyy"
SENTINELS = (TOKEN, URL, KEY, LLM_KEY, FRESH_TOKEN, FRESH_KEY)


def secrets_block():
    text = START_SH.read_text()
    start = text.find(
        'SECRETS_FILE="${GROKBOT_SECRETS_FILE:-/workspace/.secrets/grokbot-telegram.env}"'
    )
    if start < 0:
        raise AssertionError("start.sh is missing the GROKBOT_SECRETS_FILE default")
    end = text.find('PID="$DATA_DIR/relay.pid"', start)
    if end < 0:
        raise AssertionError("start.sh secrets-file block is not followed by the pid setup")
    return text[start:end]


def write_secrets(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use bash printf %q so the test file matches what the guide writes.
    subprocess.run(
        [
            "bash",
            "-c",
            'umask 077; out="$5"; {'
            '  printf "export TELEGRAM_BOT_TOKEN=%q\\n" "$1";'
            '  printf "export GROKBOT_WEBHOOK_URL=%q\\n" "$2";'
            '  printf "export GROKBOT_WEBHOOK_KEY=%q\\n" "$3";'
            '  printf "export GROKBOT_MEMBER_LLM_API_KEY=%q\\n" "$4";'
            '} > "$out" && chmod 600 "$out"',
            "write_secrets",
            TOKEN,
            URL,
            KEY,
            LLM_KEY,
            str(path),
        ],
        check=True,
    )


def run_block(secrets_path, mode, extra_env=None):
    env = os.environ.copy()
    # Drop any real relay secrets from the test process environment.
    for name in (
        "TELEGRAM_BOT_TOKEN",
        "GROKBOT_WEBHOOK_URL",
        "GROKBOT_WEBHOOK_KEY",
        "GROKBOT_MEMBER_LLM_API_KEY",
        "GROKBOT_SECRETS_FILE",
        "SECRETS_FILE",
    ):
        env.pop(name, None)
    # Always override the default path so this test never touches a real secrets file.
    env["GROKBOT_SECRETS_FILE"] = secrets_path
    env["EXPECTED_TOKEN"] = TOKEN
    env["EXPECTED_KEY"] = KEY
    env["EXPECTED_LLM"] = LLM_KEY
    if extra_env:
        env.update(extra_env)
    script = (
        "set -eu\n"
        "umask 077\n"
        + secrets_block()
        + """
# Print only presence flags and a marker, never values.
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then echo token_set=yes; else echo token_set=no; fi
if [ -n "${GROKBOT_WEBHOOK_URL:-}" ]; then echo url_set=yes; else echo url_set=no; fi
if [ -n "${GROKBOT_WEBHOOK_KEY:-}" ]; then echo key_set=yes; else echo key_set=no; fi
if [ -n "${GROKBOT_MEMBER_LLM_API_KEY:-}" ]; then echo llm_set=yes; else echo llm_set=no; fi
# Compare without printing the value.
if [ "${TELEGRAM_BOT_TOKEN:-}" = "$EXPECTED_TOKEN" ]; then echo token_match=yes; else echo token_match=no; fi
if [ "${GROKBOT_WEBHOOK_KEY:-}" = "$EXPECTED_KEY" ]; then echo key_match=yes; else echo key_match=no; fi
if [ "${GROKBOT_MEMBER_LLM_API_KEY:-}" = "$EXPECTED_LLM" ]; then echo llm_match=yes; else echo llm_match=no; fi
echo LOAD_DONE
"""
    )
    if secrets_path and os.path.isfile(secrets_path):
        os.chmod(secrets_path, mode)
    return subprocess.run(
        ["bash", "-c", script],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class TestStartSecrets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.secrets = Path(self.tmp.name) / "grokbot-telegram.env"

    def assert_no_sentinels(self, proc):
        blob = (proc.stdout or "") + (proc.stderr or "")
        for value in SENTINELS:
            self.assertNotIn(value, blob)

    def test_pairing_mode_wiring(self):
        self.assertIn("export GROKBOT_PAIRING_ONLY=1", START_SH.read_text())
        self.assertIn('rm -f "$DATA_DIR/pairing-only"', START_SH.read_text())
        self.assertIn('./start.sh --pairing-only', (ROOT / "ensure.sh").read_text())
        self.assertIn('[ "${1:-}" = "--pairing-only" ]', (ROOT / "ensure.sh").read_text())
        self.assertIn('python3 -u relay.py', (ROOT / "supervise.sh").read_text())

    def test_start_sh_has_expected_loader(self):
        block = secrets_block()
        self.assertIn(
            "GROKBOT_SECRETS_FILE:-/workspace/.secrets/grokbot-telegram.env", block
        )
        self.assertIn("set -a", block)
        self.assertIn('."$SECRETS_FILE"', block.replace(" ", ""))
        self.assertIn("set +a", block)
        self.assertIn("_SECRETS_KEEP_", block)
        self.assertIn("group- or other-readable", block)
        self.assertIn("group- or other-writable", block)
        self.assertIn("not owned by the current user", block)
        self.assertNotIn("echo $", block)
        self.assertNotIn("cat ", block)

    def test_loads_0600_file_without_echoing(self):
        write_secrets(self.secrets)
        proc = run_block(str(self.secrets), 0o600)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_no_sentinels(proc)
        self.assertIn("token_set=yes", proc.stdout)
        self.assertIn("url_set=yes", proc.stdout)
        self.assertIn("key_set=yes", proc.stdout)
        self.assertIn("llm_set=yes", proc.stdout)
        self.assertIn("token_match=yes", proc.stdout)
        self.assertIn("key_match=yes", proc.stdout)
        self.assertIn("llm_match=yes", proc.stdout)
        self.assertNotIn("warning:", proc.stdout + proc.stderr)
        self.assertEqual(self.secrets.stat().st_mode & 0o777, 0o600)

    def test_env_wins_over_stale_file(self):
        write_secrets(self.secrets)
        proc = run_block(
            str(self.secrets),
            0o600,
            extra_env={
                "TELEGRAM_BOT_TOKEN": FRESH_TOKEN,
                "GROKBOT_WEBHOOK_KEY": FRESH_KEY,
                "EXPECTED_TOKEN": FRESH_TOKEN,
                "EXPECTED_KEY": FRESH_KEY,
                # Member key is unset: the stale file should fill it.
            },
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_no_sentinels(proc)
        self.assertIn("token_match=yes", proc.stdout)
        self.assertIn("key_match=yes", proc.stdout)
        self.assertIn("llm_match=yes", proc.stdout)
        self.assertIn("llm_set=yes", proc.stdout)
        self.assertNotIn("warning:", proc.stdout + proc.stderr)

    def test_file_fills_unset_vars(self):
        write_secrets(self.secrets)
        proc = run_block(str(self.secrets), 0o600, extra_env={"TELEGRAM_BOT_TOKEN": ""})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_no_sentinels(proc)
        self.assertIn("token_match=yes", proc.stdout)
        self.assertIn("key_match=yes", proc.stdout)

    def test_warns_if_group_or_other_readable_and_still_loads(self):
        write_secrets(self.secrets)
        proc = run_block(str(self.secrets), 0o644)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_no_sentinels(proc)
        self.assertIn("group- or other-readable", proc.stdout)
        self.assertNotIn("group- or other-writable", proc.stdout)
        self.assertIn("token_match=yes", proc.stdout)
        # Warning only; do not chmod the file.
        self.assertEqual(self.secrets.stat().st_mode & 0o777, 0o644)

    def test_warns_if_group_or_other_writable_and_still_loads(self):
        write_secrets(self.secrets)
        proc = run_block(str(self.secrets), 0o620)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_no_sentinels(proc)
        self.assertIn("group- or other-writable", proc.stdout)
        self.assertNotIn("group- or other-readable", proc.stdout)
        self.assertIn("token_match=yes", proc.stdout)
        self.assertEqual(self.secrets.stat().st_mode & 0o777, 0o620)

    def test_missing_file_is_ok(self):
        missing = Path(self.tmp.name) / "missing.env"
        proc = run_block(str(missing), 0o600)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_no_sentinels(proc)
        self.assertIn("token_set=no", proc.stdout)
        self.assertIn("token_match=no", proc.stdout)
        self.assertNotIn("warning:", proc.stdout + proc.stderr)


class TestSupervisorIdentity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ("start.sh", "stop.sh", "ensure.sh", "supervise.sh", "pidutil.sh"):
            shutil.copy(ROOT / name, self.root / name)
        self.data = self.root / "data"
        self.data.mkdir()
        binpath = self.root / "bin"
        binpath.mkdir()
        python = binpath / "python3"
        python.write_text('#!/bin/bash\nif [ "${1:-}" = -u ]; then exec sleep 30; fi\nexit 1\n')
        python.chmod(0o700)
        self.env = dict(os.environ, GROKBOT_DATA_DIR=str(self.data),
                        GROKBOT_SECRETS_FILE=str(self.root / "absent"),
                        TELEGRAM_BOT_TOKEN=TOKEN, GROKBOT_WEBHOOK_URL=URL,
                        GROKBOT_WEBHOOK_KEY=KEY, PATH=str(binpath) + ":" + os.environ["PATH"])

    def run_script(self, name):
        return subprocess.run(["bash", name], cwd=self.root, env=self.env,
                              capture_output=True, text=True, timeout=5)

    def write_pid(self, pid, start=None):
        if start is None:
            start = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
        (self.data / "relay.pid").write_text(f"{pid}\n{start}\n")

    def test_foreign_live_pid_is_not_relay(self):
        with subprocess.Popen(["sleep", "30"]) as sleeper:
            try:
                for script in ("start.sh", "ensure.sh", "stop.sh"):
                    self.write_pid(sleeper.pid)
                    result = self.run_script(script)
                    self.assertNotIn("already running", result.stdout)
                    self.assertNotIn("ok: running", result.stdout)
                    self.assertIsNone(sleeper.poll())
                self.assertIn("not running", result.stdout)
                self.assertFalse((self.data / "relay.pid").exists())
            finally:
                sleeper.terminate()

    def test_real_supervisor_and_starttime(self):
        proc = subprocess.Popen(["bash", "./supervise.sh"], cwd=self.root,
                                env=self.env, start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.1)
            self.write_pid(proc.pid)
            self.assertIn("ok: running", self.run_script("ensure.sh").stdout)
            self.assertIn("already running", self.run_script("start.sh").stdout)
            self.write_pid(proc.pid, "1")
            self.assertNotIn("ok: running", self.run_script("ensure.sh").stdout)
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)

    def test_supervisor_path_as_unrelated_argument_is_rejected(self):
        proc = subprocess.Popen(["bash", "-c", "sleep 30 & wait", "./supervise.sh"],
                                cwd=self.root, start_new_session=True)
        try:
            self.write_pid(proc.pid)
            result = self.run_script("stop.sh")
            self.assertIn("not running", result.stdout)
            self.assertIsNone(proc.poll())
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=5)

    def test_concurrent_starts_launch_one_supervisor(self):
        python = self.root / "bin" / "python3"
        python.write_text('#!/bin/bash\nif [ "${1:-}" = -u ]; then exec sleep 30; fi\nexit 0\n')
        processes = [subprocess.Popen(["bash", "start.sh"], cwd=self.root, env=self.env,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for _ in range(2)]
        try:
            output = [p.communicate(timeout=5)[0] for p in processes]
            self.assertTrue(all(p.returncode == 0 for p in processes))
            self.assertEqual(sum("started pid" in out for out in output), 1)
            self.assertEqual(sum("already running" in out for out in output), 1)
            lines = (self.data / "relay.pid").read_text().splitlines()
            self.assertEqual(len(lines), 2)
            for name in ("relay.pid", "relay.start.lock"):
                self.assertEqual((self.data / name).stat().st_mode & 0o777, 0o600)
        finally:
            self.run_script("stop.sh")
            for proc in processes:
                if proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=5)

    def test_startup_lock_wiring(self):
        self.assertIn("relay_start_lock", START_SH.read_text())
        self.assertIn('flock -x 9', (ROOT / "pidutil.sh").read_text())
        self.assertIn('9>&-', START_SH.read_text())


if __name__ == "__main__":
    unittest.main()
