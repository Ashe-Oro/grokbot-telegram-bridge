#!/usr/bin/env python3
"""Offline tests for the relay (no network: tg(), file download and webhook are mocked).
Run: python3 test_media.py   (uses a fake token; never touches a real bot)

Needs ffmpeg on PATH (fixtures are generated into a temp dir). The voice tests also need the
faster-whisper venv (GROKBOT_ASR_PYTHON, default ./.venv-asr/bin/python); they are skipped
if it is missing. tests/fixtures/speech.ogg is a public-domain clip (JFK, 1961 inaugural
address) re-encoded from whisper.cpp's samples/jfk.wav."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, time, unittest, urllib.error

FAKE_TOKEN = "123456789:FAKE_test_TOKEN_abcdefghijklmnopqrstu"
FAKE_KEY = "fake-webhook-key-zzz"
os.environ.update(TELEGRAM_BOT_TOKEN=FAKE_TOKEN, GROKBOT_WEBHOOK_KEY=FAKE_KEY,
                  GROKBOT_WEBHOOK_URL="https://example.invalid/hook")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import relay

OWNER, STRANGER, BOT_ID = 111, 222, 999
BOT_USERNAME = "ExampleGrokBot"
MENTION = "@" + BOT_USERNAME

def _make_fixtures():
    """Generate small media fixtures with ffmpeg; copy the speech clip from tests/fixtures."""
    d = tempfile.mkdtemp(prefix="bridge-fixtures-")
    run = lambda *a: subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *a], check=True)
    run("-f", "lavfi", "-i", "testsrc=size=320x240:rate=1", "-frames:v", "1", f"{d}/img.jpg")
    run("-f", "lavfi", "-i", "testsrc=size=16x16:rate=1", "-frames:v", "1", f"{d}/img.png")
    run("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:a", "libopus", f"{d}/sine.ogg")
    shutil.copy(os.path.join(HERE, "tests", "fixtures", "speech.ogg"), f"{d}/speech.ogg")
    return d

TD = _make_fixtures()
relay.HOME = TD   # transcriber.err goes here, not into the repo

def fixture(name):
    with open(os.path.join(TD, name), "rb") as f:
        return f.read()
HAVE_ASR = os.path.exists(relay.ASR_PY)

class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for name, sub in (("STATE", "state.json"), ("LOCK", "state.lock"), ("OUTBOX", "outbox"), ("MEDIA", "media")):
            setattr(relay, name, os.path.join(self.tmp, sub))
        relay.FAILED = os.path.join(relay.OUTBOX, "failed")
        os.makedirs(relay.FAILED); os.makedirs(relay.MEDIA)
        relay.TYPING.clear()
        with relay.state() as s:
            s["allowlist"] = [OWNER]
        self.calls, self.forwarded, self.files, self.urls = [], [], {}, []
        def tg(method, params=None, timeout=35):
            self.calls.append((method, params))
            if method == "getMe":
                return {"id": BOT_ID, "username": BOT_USERNAME}
            if method == "getFile":
                fid = params["file_id"]
                data = self.files.get(fid, b"")
                return {"file_id": fid, "file_path": f"stuff/{fid}.bin", "file_size": len(data) if fid != "huge" else 30 << 20}
            return {"message_id": 1}
        def opener(url, timeout):
            self.urls.append(url)
            assert FAKE_TOKEN in url
            fid = url.rsplit("/", 1)[1][:-4]
            if fid == "boom":
                raise urllib.error.URLError(f"failed to reach {url}")
            return FakeResp(self.files[fid])
        relay.tg, relay._open_file_url = tg, opener
        relay.forward = lambda ev: self.forwarded.append(ev) or True
        self.out = io.StringIO()
        self._redir = contextlib.redirect_stdout(self.out); self._redir.__enter__()
        self.bot = relay.Bot()

    def tearDown(self):
        self._redir.__exit__(None, None, None)
        log = self.out.getvalue()
        self.assertNotIn(FAKE_TOKEN, log); self.assertNotIn(FAKE_KEY, log)
        self.assertNotRegex(log, r"/bot[0-9]+:")
        for root, _, names in os.walk(self.tmp):
            for n in names:
                with open(os.path.join(root, n), "rb") as f:
                    b = f.read()
                self.assertNotIn(FAKE_TOKEN.encode(), b, n); self.assertNotIn(FAKE_KEY.encode(), b, n)
        shutil.rmtree(self.tmp)

    def upd(self, uid_, msg, user=OWNER, chat=None):
        m = {"message_id": 7, "date": 1, "from": {"id": user, "first_name": "A"},
             "chat": chat or {"id": user, "type": "private"}}
        m.update(msg)
        self.bot.handle({"update_id": uid_, "message": m})

    def sends(self):
        return [p for m, p in self.calls if m == "sendMessage"]

class TestText(Base):
    def test_text_dm(self):
        self.upd(1, {"text": "hello there"})
        ev = self.forwarded[0]
        self.assertEqual((ev["text"], ev["kind"], ev["media_path"], ev["transcript"]), ("hello there", "text", None, None))
        self.assertEqual(ev["reply_file"], os.path.join(relay.OUTBOX, "1.json"))
        self.assertNotIn("hello there", self.out.getvalue())

    def test_group_needs_mention(self):
        g = {"id": -5, "type": "group", "title": "fam"}
        self.upd(2, {"text": "just chatting"}, chat=g)
        self.upd(3, {"text": MENTION + " hi", "entities": [{"type": "mention", "offset": 0, "length": len(MENTION)}]}, chat=g)
        self.assertEqual([e["update_id"] for e in self.forwarded], [3])

    def test_stranger_gets_pairing(self):
        self.upd(4, {"text": "hi"}, user=STRANGER)
        self.assertFalse(self.forwarded)
        self.assertIn("pairing code", self.sends()[0]["text"])

    def test_whoami(self):
        self.upd(5, {"text": "/whoami"})
        self.assertFalse(self.forwarded); self.assertIn("user_id=111", self.sends()[0]["text"])

class TestPhoto(Base):
    def test_photo_largest(self):
        self.files = {"small": b"x" * 10, "big": fixture("img.jpg")}
        self.upd(10, {"photo": [{"file_id": "small", "file_size": 10, "width": 90, "height": 90},
                                {"file_id": "big", "file_size": len(self.files["big"]), "width": 320, "height": 240}],
                      "caption": "what is this?"})
        ev = self.forwarded[0]
        self.assertEqual((ev["kind"], ev["text"], ev["transcript"]), ("photo", "what is this?", None))
        self.assertEqual(ev["media_path"], os.path.join(relay.MEDIA, "10", "media.jpg"))
        self.assertTrue(os.path.isabs(ev["media_path"]))
        with open(ev["media_path"], "rb") as f:
            self.assertEqual(f.read(), self.files["big"])
        self.assertIn(("sendChatAction", {"chat_id": OWNER, "action": "typing"}), self.calls)
        self.assertNotIn("what is this", self.out.getvalue())

    def test_photo_no_caption(self):
        self.files = {"p": b"jpgdata"}
        self.upd(11, {"photo": [{"file_id": "p", "file_size": 7, "width": 1, "height": 1}]})
        self.assertEqual(self.forwarded[0]["text"], "")

    def test_image_document(self):
        self.files = {"doc": fixture("img.png")}
        self.upd(12, {"document": {"file_id": "doc", "file_name": "receipt.PNG", "mime_type": "image/png",
                                   "file_size": len(self.files["doc"])}})
        ev = self.forwarded[0]
        self.assertEqual(ev["kind"], "photo"); self.assertTrue(ev["media_path"].endswith("/12/media.png"))

    def test_non_image_document_ignored(self):
        self.upd(13, {"document": {"file_id": "d", "file_name": "a.pdf", "mime_type": "application/pdf"}})
        self.assertFalse(self.forwarded); self.assertFalse(self.calls[1:])

    def test_group_photo_caption_mention(self):
        g = {"id": -5, "type": "supergroup", "title": "fam"}
        self.files = {"p": b"jpg"}
        ph = [{"file_id": "p", "file_size": 3, "width": 1, "height": 1}]
        self.upd(14, {"photo": ph, "caption": "nice"}, chat=g)
        self.upd(15, {"photo": ph, "caption": MENTION + " look",
                      "caption_entities": [{"type": "mention", "offset": 0, "length": len(MENTION)}]}, chat=g)
        self.assertEqual([e["update_id"] for e in self.forwarded], [15])

    def test_stranger_photo_not_downloaded(self):
        self.upd(16, {"photo": [{"file_id": "p", "file_size": 3, "width": 1, "height": 1}]}, user=STRANGER)
        self.assertFalse(self.forwarded); self.assertFalse(self.urls)

class TestLimitsAndErrors(Base):
    def test_oversize_declared(self):
        self.upd(20, {"document": {"file_id": "x", "mime_type": "image/jpeg", "file_size": 25 << 20}})
        self.assertFalse(self.forwarded); self.assertFalse(self.urls)
        self.assertIn("20 MB", self.sends()[0]["text"])
        self.assertIn("rejected size=", self.out.getvalue())

    def test_oversize_from_getfile(self):
        self.upd(21, {"voice": {"file_id": "huge", "duration": 5, "mime_type": "audio/ogg"}})
        self.assertFalse(self.forwarded); self.assertFalse(self.urls)
        self.assertIn("20 MB", self.sends()[0]["text"])

    def test_oversize_stream(self):
        old = relay.MAX_FILE; relay.MAX_FILE = 100
        try:
            self.files = {"s": b"y" * 500}
            self.upd(22, {"photo": [{"file_id": "s", "width": 1, "height": 1}]})
        finally:
            relay.MAX_FILE = old
        self.assertFalse(self.forwarded); self.assertIn("20 MB", self.sends()[0]["text"])
        d = os.path.join(relay.MEDIA, "22")
        self.assertFalse(os.path.isdir(d) and os.listdir(d))

    def test_download_error_scrubbed(self):
        self.upd(23, {"photo": [{"file_id": "boom", "file_size": 3, "width": 1, "height": 1}]})
        self.assertFalse(self.forwarded)
        self.assertIn("download failed: DownloadError URLError", self.out.getvalue())

    def test_log_scrubs_token_and_url(self):
        relay.log(f"oops https://api.telegram.org/file/bot{FAKE_TOKEN}/x and /bot999:Abc_def-1/ {FAKE_KEY}")
        line = self.out.getvalue().splitlines()[-1]
        self.assertNotIn("FAKE_test", line); self.assertNotIn("Abc_def", line)

    def test_cleanup(self):
        old_dir, new_dir = os.path.join(relay.MEDIA, "1"), os.path.join(relay.MEDIA, "2")
        os.makedirs(old_dir); os.makedirs(new_dir)
        t = time.time() - 8 * 86400
        os.utime(old_dir, (t, t))
        self.assertEqual(relay.cleanup_media(), 1)
        self.assertEqual(os.listdir(relay.MEDIA), ["2"])

class TestAllowlistSeed(Base):
    def test_seed_from_env(self):
        self.assertEqual(relay.seed_allowlist("333, 444 333"), 2)
        self.assertEqual(relay.seed_allowlist("444"), 0)
        with relay.state(write=False) as s:
            self.assertEqual(s["allowlist"], [OWNER, 333, 444])
        self.upd(40, {"text": "hi"}, user=333)
        self.assertEqual(self.forwarded[0]["user_id"], 333)

    def test_seed_rejects_garbage(self):
        with self.assertRaises(SystemExit):
            relay.parse_allowlist("123,@someone")

    def test_not_connected_uses_bot_name(self):
        old_name, old_url = relay.BOT_NAME, os.environ.pop("GROKBOT_WEBHOOK_URL")
        relay.BOT_NAME = "Helper"
        try:
            relay.forward = lambda ev: False
            self.upd(41, {"text": "hello"})
        finally:
            relay.BOT_NAME = old_name; os.environ["GROKBOT_WEBHOOK_URL"] = old_url
        self.assertEqual(self.sends()[0]["text"], "Helper isn't connected yet. Try again later.")

class TestDotenv(unittest.TestCase):
    def test_dotenv_does_not_override(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("# c\nexport BRIDGE_T1='one'\nBRIDGE_T2=\"two\"\nTELEGRAM_BOT_TOKEN=should-not-win\nbad line\n")
        try:
            relay.load_dotenv(f.name)
            self.assertEqual((os.environ["BRIDGE_T1"], os.environ["BRIDGE_T2"]), ("one", "two"))
            self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], FAKE_TOKEN)
        finally:
            os.remove(f.name); os.environ.pop("BRIDGE_T1", None); os.environ.pop("BRIDGE_T2", None)

@unittest.skipUnless(HAVE_ASR, "faster-whisper venv not found (set GROKBOT_ASR_PYTHON)")
class TestVoice(Base):
    def test_voice_speech(self):
        self.files = {"v": fixture("speech.ogg")}
        self.upd(30, {"voice": {"file_id": "v", "duration": 6, "mime_type": "audio/ogg", "file_size": len(self.files["v"])}})
        ev = self.forwarded[0]
        self.assertEqual(ev["kind"], "voice"); self.assertTrue(ev["media_path"].endswith("/30/media.ogg"))
        self.assertTrue(ev["transcript"] and len(ev["transcript"]) > 5, ev["transcript"])
        self.assertTrue(ev["text"].startswith("[Voice note, transcribed] "))
        self.assertIn(ev["transcript"], ev["text"])
        self.assertNotIn(ev["transcript"], self.out.getvalue())
        print("\n  speech transcript chars:", len(ev["transcript"]), file=sys.stderr)

    def test_reply_voice_in_group_and_warm(self):
        g = {"id": -5, "type": "group", "title": "fam"}
        self.files = {"s": fixture("sine.ogg")}
        t0 = time.time()
        self.upd(31, {"voice": {"file_id": "s", "duration": 2}, "reply_to_message": {"message_id": 3, "from": {"id": BOT_ID}}}, chat=g)
        self.upd(32, {"voice": {"file_id": "s", "duration": 2}}, chat=g)   # not addressed
        self.assertEqual([e["update_id"] for e in self.forwarded], [31])
        self.assertIsNotNone(self.forwarded[0]["transcript"])   # tone -> "" or junk, but not a failure
        print(f"  warm transcriber call took {time.time() - t0:.1f}s", file=sys.stderr)

    def test_audio_and_video_note(self):
        self.files = {"a": fixture("speech.ogg")}
        self.upd(33, {"audio": {"file_id": "a", "file_name": "memo.ogg", "mime_type": "audio/ogg"}, "caption": "fyi"})
        ev = self.forwarded[0]
        self.assertEqual(ev["kind"], "voice"); self.assertTrue(ev["media_path"].endswith(".ogg"))
        self.assertTrue(ev["text"].endswith("\n[Caption] fyi"))

    def test_transcription_failure_still_forwards(self):
        self.files = {"bad": b"not audio at all"}
        self.upd(34, {"voice": {"file_id": "bad", "duration": 1}})
        ev = self.forwarded[0]
        self.assertIsNone(ev["transcript"]); self.assertIn("transcription failed", ev["text"])
        self.assertEqual(ev["kind"], "voice"); self.assertTrue(os.path.exists(ev["media_path"]))

    def test_transcription_timeout(self):
        self.files = {"v": fixture("speech.ogg")}
        old = relay.ASR_TIMEOUT; relay.ASR_TIMEOUT = 0.001
        try:
            self.upd(35, {"voice": {"file_id": "v", "duration": 6}})
        finally:
            relay.ASR_TIMEOUT = old
        ev = self.forwarded[0]
        self.assertIsNone(ev["transcript"]); self.assertEqual(ev["transcript_error"], "timeout")

class TestTyping(Base):
    def test_typing_starts_on_forward_and_stops_when_sent(self):
        self.upd(50, {"text": "hello", "message_id": 7})
        self.assertIn("50.json", relay.TYPING)
        self.assertEqual(relay.TYPING["50.json"][0], OWNER)
        self.assertIn(("sendChatAction", {"chat_id": OWNER, "action": "typing"}), self.calls)
        path = os.path.join(relay.OUTBOX, "50.json")
        with open(path, "w") as f:
            json.dump({"chat_id": OWNER, "text": "hi back", "reply_to_message_id": 7}, f)
        os.utime(path, (time.time() - 1, time.time() - 1))
        relay.drain_outbox_once()
        self.assertNotIn("50.json", relay.TYPING)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(any(m == "sendMessage" and p.get("text") == "hi back" for m, p in self.calls))

    def test_typing_stops_on_forward_failure_bad_outbox_and_expiry(self):
        relay.forward = lambda ev: False
        self.upd(51, {"text": "hello"})
        self.assertNotIn("51.json", relay.TYPING)

        relay.TYPING["52.json"] = (OWNER, time.time())
        path = os.path.join(relay.OUTBOX, "52.json")
        with open(path, "w") as f:
            f.write("not-json")
        os.utime(path, (time.time() - 1, time.time() - 1))
        relay.drain_outbox_once()
        self.assertNotIn("52.json", relay.TYPING)
        self.assertTrue(os.path.exists(os.path.join(relay.FAILED, "52.json")))

        old = relay.TYPING_MAX
        relay.TYPING_MAX = 0.01
        n = {"sleeps": 0}
        def fake_sleep(_):
            n["sleeps"] += 1
            if n["sleeps"] > 1:
                raise RuntimeError("stop")
        relay.TYPING["old.json"] = (OWNER, time.time() - 10)
        relay.TYPING["new.json"] = (999, time.time())
        orig = relay.time.sleep
        relay.time.sleep = fake_sleep
        try:
            with self.assertRaises(RuntimeError):
                relay.typing_loop()
        finally:
            relay.time.sleep = orig
            relay.TYPING_MAX = old
        self.assertNotIn("old.json", relay.TYPING)
        self.assertIn("new.json", relay.TYPING)
        self.assertIn(("sendChatAction", {"chat_id": 999, "action": "typing"}), self.calls)

if __name__ == "__main__":
    import warnings; warnings.simplefilter("ignore", ResourceWarning)
    try:
        unittest.main(verbosity=2)
    finally:
        relay.TRANSCRIBER._kill()
        shutil.rmtree(TD, ignore_errors=True)
