#!/usr/bin/env python3
"""Offline tests for start.sh secrets-file loading. No network, no real secrets."""
import os
import subprocess
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


if __name__ == "__main__":
    unittest.main()
