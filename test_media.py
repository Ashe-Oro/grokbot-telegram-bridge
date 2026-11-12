#!/usr/bin/env python3
"""Offline tests for the relay (no network: tg(), file download and webhook are mocked).
Run: python3 test_media.py   (uses a fake token; never touches a real bot)

Needs ffmpeg on PATH (fixtures are generated into a temp dir). The voice tests also need the
faster-whisper venv (GROKBOT_ASR_PYTHON, default ./.venv-asr/bin/python); they are skipped
if it is missing. tests/fixtures/speech.ogg is a public-domain clip (JFK, 1961 inaugural
address) re-encoded from whisper.cpp's samples/jfk.wav."""
import contextlib, io, json, os, shutil, subprocess, sys, tempfile, time, unittest, urllib.error
from unittest.mock import patch

FAKE_TOKEN = "123456789:FAKE_test_TOKEN_abcdefghijklmnopqrstu"
FAKE_KEY = "fake-webhook-key-zzz"
FAKE_LLM_KEY = "fake-member-llm-key-qqq"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import relay

OWNER, STRANGER, BOT_ID, MEMBER = 111, 222, 999, 333
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
unittest.addModuleCleanup(shutil.rmtree, TD, ignore_errors=True)

def fixture(name):
    with open(os.path.join(TD, name), "rb") as f:
        return f.read()
HAVE_ASR = os.path.exists(relay.ASR_PY)

class FakeResp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()

class Base(unittest.TestCase):
    def setUp(self):
        names = ("tg", "_open_file_url", "forward", "_post_chat", "MEMBER_THREADED",
                 "BOT_NAME", "HOME", "STATE", "LOCK", "OUTBOX", "FAILED", "MEDIA",
                 "MAX_FILE", "ASR_TIMEOUT", "TYPING_MAX", "MEMBER_HISTORY", "TYPING",
                 "JOB_ACTIVE", "JOB_POOLS", "TRANSCRIBER")
        original = {n: getattr(relay, n) for n in names}
        self.original = original
        self.addCleanup(lambda: [setattr(relay, n, v) for n, v in original.items()])
        env = patch.dict(os.environ, TELEGRAM_BOT_TOKEN=FAKE_TOKEN, GROKBOT_WEBHOOK_KEY=FAKE_KEY,
                         GROKBOT_WEBHOOK_URL="https://example.invalid/hook",
                         GROKBOT_MEMBER_LLM_API_KEY=FAKE_LLM_KEY, MEMBER_LLM_API_KEY="",
                         GROKBOT_ADMINS="", GROKBOT_ALLOWLIST="", GROKBOT_PAIRING_ONLY="0",
                         GROKBOT_OUTBOX_CHATS="")
        env.start(); self.addCleanup(env.stop)
        relay.MEMBER_HISTORY = relay.collections.OrderedDict()
        relay.TYPING = {}
        relay.JOB_ACTIVE = set()
        relay.JOB_POOLS = {}
        relay.TRANSCRIBER = relay.Transcriber()
        self.addCleanup(relay.TRANSCRIBER._kill)
        self.tmp = tempfile.mkdtemp()
        relay.HOME = self.tmp
        for name, sub in (("STATE", "state.json"), ("LOCK", "state.lock"), ("OUTBOX", "outbox"), ("MEDIA", "media")):
            setattr(relay, name, os.path.join(self.tmp, sub))
        relay.FAILED = os.path.join(relay.OUTBOX, "failed")
        os.makedirs(relay.FAILED); os.makedirs(relay.MEDIA)
        relay.TYPING.clear()
        with relay.state() as s:
            s["allowlist"] = [OWNER]
            s["roles"] = {str(OWNER): "admin"}
        relay.MEMBER_THREADED = False
        relay.MEMBER_HISTORY.clear()
        self.llm = []
        def post_chat(cfg, payload):
            self.llm.append((cfg, payload))
            if getattr(self, "llm_fail", None):
                raise self.llm_fail
            return {"choices": [{"message": {"role": "assistant", "content": "Hi from the chat model"}}]}
        relay._post_chat = post_chat
        os.environ["GROKBOT_MEMBER_LLM_API_KEY"] = FAKE_LLM_KEY
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
        self.assertNotIn(FAKE_TOKEN, log); self.assertNotIn(FAKE_KEY, log); self.assertNotIn(FAKE_LLM_KEY, log)
        self.assertNotRegex(log, r"/bot[0-9]+:")
        for root, _, names in os.walk(self.tmp):
            for n in names:
                if not os.path.isfile(os.path.join(root, n)) or os.path.islink(os.path.join(root, n)):
                    continue
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
        self.assertEqual(ev["forward"], {"forwarded": False})
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

class TestRoles(Base):
    def add_member(self, uid=MEMBER):
        with relay.state() as s:
            s["roles"][str(uid)] = "member"

    def test_seed_admins(self):
        self.assertEqual(relay.seed_allowlist("444", admins_raw="555"), 2)
        self.assertEqual(relay.seed_allowlist("555", admins_raw="555"), 0)   # never demotes
        with relay.state(write=False) as s:
            self.assertEqual(s["roles"], {str(OWNER): "admin", "444": "member", "555": "admin"})

    def test_demotion_during_media_routes_to_member(self):
        def prepare(upd, msg, media, event):
            with relay.state() as s:
                s["roles"][str(OWNER)] = "member"
            event["media_path"] = os.path.join(TD, "img.jpg")
            return True
        with patch.object(self.bot, "prepare_media", side_effect=prepare):
            self.upd(390, {"photo": [{"file_id": "p"}]})
        self.assertFalse(self.forwarded)
        self.assertEqual(len(self.llm), 1)
        self.assertFalse(relay.TYPING)

    def test_removal_during_media_drops_message(self):
        def prepare(upd, msg, media, event):
            with relay.state() as s:
                s["roles"].pop(str(OWNER))
                s["allowlist"] = []
            return True
        with patch.object(self.bot, "prepare_media", side_effect=prepare):
            self.upd(392, {"photo": [{"file_id": "p"}]})
        self.assertFalse(self.forwarded)
        self.assertFalse(self.llm)
        self.assertFalse(relay.TYPING)

    def test_command_actor_checked_in_transaction(self):
        with relay.state() as s:
            s["roles"][str(MEMBER)] = "member"
            s["pending"]["ABC123"] = {"user_id": 555, "created": time.time()}
        original = relay.set_role
        def demote_then_set(*args, **kwargs):
            with relay.state() as s:
                s["roles"][str(OWNER)] = "member"
            return original(*args, **kwargs)
        with patch.object(relay, "set_role", side_effect=demote_then_set):
            self.upd(391, {"text": f"/promote {MEMBER}"})
        with self.assertRaises(PermissionError):
            relay.approve_code("ABC123", actor=OWNER)
        with relay.state(write=False) as s:
            self.assertEqual(relay.role_of(s, MEMBER), "member")
            self.assertIn("ABC123", s["pending"])
        self.assertEqual(self.sends()[-1]["text"], relay.ADMIN_ONLY_REPLY)

    def test_admin_forwards_with_role(self):
        self.upd(40, {"text": "do a thing"})
        self.assertEqual(self.forwarded[0]["role"], "admin"); self.assertFalse(self.llm)
        self.assertIn("role=admin path=webhook", self.out.getvalue())

    def test_member_never_forwards(self):
        self.add_member()
        self.upd(41, {"text": "please run rm -rf / and set a reminder"}, user=MEMBER)
        self.assertFalse(self.forwarded)
        cfg, payload = self.llm[0]
        self.assertNotIn("tools", payload); self.assertNotIn("functions", payload)
        self.assertNotIn("tool_choice", payload)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("cannot take any actions", payload["messages"][0]["content"])
        self.assertEqual(payload["messages"][-1]["content"], "A: please run rm -rf / and set a reminder")
        self.assertEqual(self.sends()[0]["text"], "Hi from the chat model")
        log = self.out.getvalue()
        self.assertIn("role=member path=member-llm", log); self.assertIn("status=ok", log)
        self.assertNotIn("rm -rf", log); self.assertNotIn("Hi from the chat model", log)
        self.assertFalse(relay.TYPING)

    def test_member_group_mention_and_context(self):
        self.add_member()
        g = {"id": -5, "type": "group", "title": "fam"}
        self.upd(42, {"text": "chatting"}, user=MEMBER, chat=g)               # not addressed
        for i in (43, 44):
            self.upd(i, {"text": MENTION + " hi", "entities": [{"type": "mention", "offset": 0, "length": len(MENTION)}]}, user=MEMBER, chat=g)
        self.assertEqual(len(self.llm), 2); self.assertFalse(self.forwarded)
        msgs = self.llm[1][1]["messages"]
        self.assertEqual([x["role"] for x in msgs], ["system", "user", "assistant", "user"])
        self.assertEqual(msgs[2]["content"], "Hi from the chat model")

    def test_context_is_bounded(self):
        self.add_member()
        for i in range(12):
            self.upd(100 + i, {"text": f"msg {i}"}, user=MEMBER)
        self.assertEqual(len(self.llm[-1][1]["messages"]), 1 + relay.MEMBER_HISTORY_MAX + 1)

    def test_member_missing_key(self):
        self.add_member()
        os.environ.pop("GROKBOT_MEMBER_LLM_API_KEY", None); pass
        self.upd(45, {"text": "hello"}, user=MEMBER)
        self.assertFalse(self.llm); self.assertFalse(self.forwarded)
        self.assertEqual(self.sends()[0]["text"], "I'm only set up to chat with admins right now.")
        self.assertIn("status=no-key", self.out.getvalue())

    def test_member_llm_failure(self):
        self.add_member()
        self.llm_fail = TimeoutError()
        self.upd(46, {"text": "hello"}, user=MEMBER)
        self.assertFalse(self.forwarded)
        self.assertIn("couldn't come up with a reply", self.sends()[0]["text"])
        self.assertIn("status=TimeoutError", self.out.getvalue())
        self.assertFalse(relay.TYPING)

    def test_member_photo_vision_and_voice(self):
        self.add_member()
        self.files = {"p": fixture("img.jpg"), "bad": b"not audio"}
        self.upd(47, {"photo": [{"file_id": "p", "file_size": 9, "width": 1, "height": 1}], "caption": "what is it"}, user=MEMBER)
        content = self.llm[0][1]["messages"][-1]["content"]
        self.assertTrue(content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(content[1]["text"], "A: what is it")
        self.upd(48, {"voice": {"file_id": "bad", "duration": 1}}, user=MEMBER)
        self.assertIn("[Voice note: transcription failed", self.llm[1][1]["messages"][-1]["content"])
        self.assertNotIn("media_path", self.llm[1][1]["messages"][-1]["content"])
        self.assertFalse(self.forwarded)

    def test_member_cannot_admin(self):
        self.add_member()
        with relay.state() as s:
            s["pending"]["ABC123"] = {"user_id": 555, "created": time.time()}
        for i, c in enumerate(("/approve ABC123", f"/promote {MEMBER}", f"/demote {OWNER}")):
            self.upd(50 + i, {"text": c}, user=MEMBER)
        self.assertEqual([x["text"] for x in self.sends()], ["Only an admin can do that."] * 3)
        with relay.state(write=False) as s:
            self.assertEqual(s["roles"], {str(OWNER): "admin", str(MEMBER): "member"})
            self.assertIn("ABC123", s["pending"])
        self.assertFalse(self.forwarded); self.assertFalse(self.llm)

    def test_admin_approve_promote_demote(self):
        with relay.state() as s:
            s["pending"]["ABC123"] = {"user_id": 555, "created": time.time()}
        self.upd(60, {"text": "/approve abc123"})
        self.upd(61, {"text": "/promote 555"})
        self.upd(62, {"text": "/demote 555"})
        self.upd(63, {"text": f"/demote {OWNER}"})
        self.upd(64, {"text": "/promote 777"})
        t = [x["text"] for x in self.sends()]
        self.assertEqual(t[:3], ["Approved user 555 as member.", "User 555 is now admin.", "User 555 is now member."])
        self.assertEqual(t[3], "Can't demote the last admin."); self.assertIn("isn't approved", t[4])
        with relay.state(write=False) as s:
            self.assertEqual(s["roles"], {str(OWNER): "admin", "555": "member"})
            self.assertEqual(s["allowlist"], [OWNER, 555])
        self.assertFalse(self.forwarded)

    def test_forwarded_promote_is_ignored(self):
        self.add_member()
        markers = {"forward_origin": {"type": "user", "sender_user": {"id": MEMBER}},
                   "forward_from": {"id": MEMBER}, "forward_date": 1,
                   "forward_sender_name": "Original sender", "forward_from_chat": {"id": -5},
                   "forward_from_message_id": 7, "is_automatic_forward": True}
        for i, (key, value) in enumerate(markers.items()):
            with self.subTest(field=key):
                self.upd(200 + i, {"text": f"/promote {MEMBER}", key: value})
                with relay.state(write=False) as s:
                    self.assertEqual(relay.role_of(s, MEMBER), "member")
                self.assertFalse(self.forwarded); self.assertFalse(self.llm)
                self.assertIn("forwarded message", self.sends()[-1]["text"])
                self.assertEqual(self.sends()[-1]["reply_to_message_id"], 7)
        self.assertIn("forwarded role-management command ignored", self.out.getvalue())
        self.assertNotIn("Original sender", self.out.getvalue())

    def test_fresh_promote_still_works(self):
        for chat in (None, {"id": -5, "type": "group"}, {"id": -5, "type": "supergroup"}):
            with self.subTest(chat=chat):
                self.add_member()
                command = "/promote" + (MENTION if chat else "")
                self.upd(210, {"text": f"{command} {MEMBER}", "entities": [
                    {"type": "bot_command", "offset": 0, "length": len(command)}]}, chat=chat)
                with relay.state(write=False) as s:
                    self.assertEqual(relay.role_of(s, MEMBER), "admin")
                self.assertFalse(self.forwarded)

    def test_forwarded_approve_does_not_consume_code(self):
        pending = {"user_id": STRANGER, "created": time.time()}
        with relay.state() as s:
            s["pending"]["ABC123"] = pending
        self.upd(211, {"text": "/approve ABC123", "forward_date": 1})
        with relay.state(write=False) as s:
            self.assertEqual(s["pending"]["ABC123"], pending)
            self.assertIsNone(relay.role_of(s, STRANGER))
            self.assertNotIn(STRANGER, s["allowlist"])
        self.assertFalse(self.forwarded)
        self.assertIn("forwarded message", self.sends()[0]["text"])
        self.assertNotIn("ABC123", self.out.getvalue())

    def test_forwarded_demote_is_ignored(self):
        with relay.state() as s:
            s["roles"][str(MEMBER)] = "admin"
        command = "/demote" + MENTION
        self.upd(212, {"text": f"{command} {MEMBER}", "forward_date": 1,
                      "entities": [{"type": "bot_command", "offset": 0, "length": len(command)}]},
                 chat={"id": -5, "type": "group"})
        with relay.state(write=False) as s:
            self.assertEqual(relay.role_of(s, MEMBER), "admin")
        self.assertFalse(self.forwarded)
        self.assertIn("forwarded message", self.sends()[0]["text"])

    def test_forwarded_admin_text_still_forwards(self):
        cases = [({"forward_origin": {"type": "user", "sender_user": {"id": MEMBER}, "date": 1}},
                  {"forwarded": True, "type": "user", "user_id": MEMBER, "date": 1}),
                 ({"forward_from": {"id": MEMBER}, "forward_date": 1},
                  {"forwarded": True, "user_id": MEMBER, "date": 1}),
                 ({"forward_origin": {"type": "hidden_user", "sender_user_name": "Original sender", "date": 1}},
                  {"forwarded": True, "type": "hidden_user", "sender_name": "Original sender", "date": 1}),
                 ({"forward_origin": {"type": "chat", "sender_chat": {"id": -5}, "date": 1}},
                  {"forwarded": True, "type": "chat", "chat_id": -5, "date": 1}),
                 ({"forward_origin": {"type": "channel", "chat": {"id": -5}, "message_id": 7, "date": 1}},
                  {"forwarded": True, "type": "channel", "chat_id": -5, "message_id": 7, "date": 1}),
                 ({"forward_from_chat": {"id": -5}, "forward_from_message_id": 7,
                   "forward_sender_name": "Original sender", "forward_date": 1},
                  {"forwarded": True, "chat_id": -5, "message_id": 7, "sender_name": "Original sender", "date": 1})]
        for i, (fields, expected) in enumerate(cases):
            with self.subTest(fields=fields):
                self.upd(220 + i, {"text": "forwarded text", **fields})
                self.assertEqual(self.forwarded[-1]["forward"], expected)
                self.assertEqual(self.forwarded[-1]["text"], "forwarded text")
        self.assertEqual(len(self.forwarded), len(cases))
        self.assertNotIn("Original sender", self.out.getvalue())
        self.assertNotIn("forwarded text", self.out.getvalue())

    def test_member_forwarded_promote_still_denied(self):
        self.add_member()
        self.upd(230, {"text": f"/promote {MEMBER}", "forward_from": {"id": MEMBER}}, user=MEMBER)
        with relay.state(write=False) as s:
            self.assertEqual(relay.role_of(s, MEMBER), "member")
        self.assertEqual(self.sends()[0]["text"], "Only an admin can do that.")
        self.assertFalse(self.forwarded); self.assertFalse(self.llm)

    def test_whoami_shows_role(self):
        self.add_member()
        self.upd(70, {"text": "/whoami"}, user=MEMBER)
        self.assertIn("role=member", self.sends()[0]["text"]); self.assertFalse(self.llm)

    def test_migration(self):
        with open(relay.STATE, "w") as f:
            json.dump({"offset": 5, "allowlist": [OWNER, 843], "pending": {}}, f)
        with relay.state(write=False) as s:
            self.assertEqual(s["roles"], {str(OWNER): "admin", "843": "member"})
        with open(relay.STATE) as f:
            saved = json.load(f)
        self.assertEqual(saved["roles"], {str(OWNER): "admin", "843": "member"})
        self.assertEqual(saved["allowlist"], [OWNER, 843]); self.assertEqual(saved["offset"], 5)
        with open(relay.STATE + ".bak-preroles") as f:
            self.assertNotIn("roles", json.load(f))
        self.upd(80, {"text": "hi"}, user=843)
        self.assertFalse(self.forwarded); self.assertEqual(len(self.llm), 1)

    def test_approve_cli(self):
        import approve
        orig = relay.configure_paths
        relay.configure_paths = lambda: None      # keep the temp state paths
        self.addCleanup(setattr, relay, "configure_paths", orig)
        with relay.state() as s:
            s["pending"]["AAA111"] = {"user_id": 601, "created": time.time()}
            s["pending"]["BBB222"] = {"user_id": 602, "created": time.time()}
        self.assertEqual(approve.main(["AAA111"]), 0)
        self.assertEqual(approve.main(["BBB222", "--admin"]), 0)
        self.assertEqual(approve.main(["--role", "602", "member"]), 0)
        self.assertEqual(approve.main(["--add", "603", "--role", "admin"]), 0)
        self.assertEqual(approve.main(["--remove", "603"]), 0)
        with relay.state(write=False) as s:
            self.assertEqual(s["roles"], {str(OWNER): "admin", "601": "member", "602": "member"})
        self.assertEqual(approve.main(["--remove", str(OWNER)]), 1)

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
    def test_voice_duration_over_cap_not_downloaded(self):
        for user in (OWNER, MEMBER):
            with relay.state() as s:
                s["roles"][str(MEMBER)] = "member"
            for field in ("voice", "audio", "video_note"):
                with self.subTest(user=user, field=field):
                    self.upd(60, {field: {"file_id": "v", "duration": relay.MAX_VOICE_SECONDS + 1,
                                         "file_size": 10}}, user=user)
        self.assertFalse(any(m == "getFile" for m, _ in self.calls))
        self.assertFalse(self.urls); self.assertFalse(os.listdir(relay.MEDIA))
        self.assertFalse(self.forwarded); self.assertFalse(self.llm)
        self.assertEqual(len(self.sends()), 6)
        self.assertTrue(all("too long" in p["text"] for p in self.sends()))

    def test_voice_duration_under_cap_is_downloaded(self):
        self.files = {"v": fixture("sine.ogg")}
        with patch.object(relay.TRANSCRIBER, "transcribe", return_value=("", None)):
            for i, duration in enumerate((relay.MAX_VOICE_SECONDS / 2, relay.MAX_VOICE_SECONDS)):
                self.upd(64 + i, {"voice": {"file_id": "v", "duration": duration}})
        self.assertEqual(sum(m == "getFile" for m, _ in self.calls), 2)
        self.assertEqual(len(self.urls), 2)
        self.assertEqual(len(self.forwarded), 2)
        self.assertTrue(all(os.path.isfile(ev["media_path"]) for ev in self.forwarded))

    def test_voice_missing_duration_still_downloads(self):
        self.files = {"v": fixture("sine.ogg")}
        with patch.object(relay.TRANSCRIBER, "transcribe", return_value=("", None)):
            for i, duration in enumerate(({}, {"duration": None})):
                self.upd(62 + i, {"voice": {"file_id": "v", **duration}})
        self.assertEqual(sum(m == "getFile" for m, _ in self.calls), 2)
        self.assertEqual(len(self.urls), 2)
        self.assertTrue(all(os.path.isfile(ev["media_path"]) for ev in self.forwarded))

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
        self.upd(40, {"text": "hi"}, user=333)      # GROKBOT_ALLOWLIST seeds members:
        self.assertFalse(self.forwarded); self.assertEqual(len(self.llm), 1)   # chat only

    def test_seed_preserves_demoted_admin(self):
        relay.seed_allowlist("", admins_raw="444")
        self.assertTrue(relay.set_role(444, "member")[0])
        self.assertEqual(relay.seed_allowlist("", admins_raw="444 555"), 1)
        with relay.state(write=False) as s:
            self.assertEqual(relay.role_of(s, 444), "member")
            self.assertEqual(relay.role_of(s, 555), "admin")

    @patch.dict(os.environ, GROKBOT_PAIRING_ONLY="1")
    def test_pairing_only_disables_configured_webhook(self):
        self.assertIsNone(relay.webhook_config())
        self.upd(42, {"text": "hello"})
        self.assertFalse(self.forwarded)
        self.assertIn("isn't connected yet", self.sends()[0]["text"])

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
    @patch.dict(os.environ, TELEGRAM_BOT_TOKEN=FAKE_TOKEN)
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

class TestResourceBounds(Base):
    def test_vision_byte_cap(self):
        with relay.state() as s:
            s["roles"][str(MEMBER)] = "member"
        self.files = {"p": fixture("img.jpg")}
        with patch.dict(os.environ, GROKBOT_VISION_MAX_BYTES="8"):
            self.upd(901, {"photo": [{"file_id": "p"}]}, user=MEMBER)
        content = self.llm[0][1]["messages"][-1]["content"]
        self.assertIsInstance(content, str)
        self.assertIn("photo I can't view", content)

    def test_history_chat_eviction_and_failed_chats(self):
        with patch.dict(os.environ, GROKBOT_MEMBER_HISTORY_CHATS="2"):
            for chat in (1, 2, 1, 3):
                relay.member_reply_text(chat, "A", "hi")
            self.assertEqual(list(relay.MEMBER_HISTORY), [1, 3])
            self.llm_fail = TimeoutError()
            relay.member_reply_text(4, "A", "hi")
        self.assertNotIn(4, relay.MEMBER_HISTORY)

    def test_media_quota_removes_oldest(self):
        for i in (1, 2, 3):
            directory = os.path.join(relay.MEDIA, str(i))
            os.mkdir(directory)
            with open(os.path.join(directory, "file"), "wb") as f:
                f.write(b"1234")
            os.utime(directory, (time.time() - 10 + i, time.time() - 10 + i))
        with patch.dict(os.environ, GROKBOT_MEDIA_MAX_BYTES="8"):
            self.assertEqual(relay.cleanup_media(), 1)
        self.assertEqual(sorted(os.listdir(relay.MEDIA)), ["2", "3"])

    def test_pairing_reply_cooldown(self):
        self.upd(902, {"text": "hi"}, user=STRANGER)
        self.upd(903, {"text": "hi again"}, user=STRANGER)
        self.assertEqual(len(self.sends()), 1)
        self.assertIn("pairing cooldown", self.out.getvalue())
        with patch.object(relay.time, "time", return_value=time.time() + 61):
            self.upd(904, {"text": "later"}, user=STRANGER)
        self.assertEqual(len(self.sends()), 2)
        self.assertEqual(self.sends()[0]["text"], self.sends()[1]["text"])

    def test_production_member_pool_is_bounded_and_deduplicated(self):
        import threading
        with relay.state() as s:
            s["roles"][str(MEMBER)] = "member"
        relay.MEMBER_THREADED = True
        release = threading.Event()
        two_started = threading.Event()
        lock = threading.Lock()
        counts = {"active": 0, "max": 0, "calls": 0}
        def slow(cfg, payload):
            with lock:
                counts["active"] += 1
                counts["calls"] += 1
                counts["max"] = max(counts["max"], counts["active"])
                if counts["active"] == 2:
                    two_started.set()
            release.wait(5)
            with lock:
                counts["active"] -= 1
            return {"choices": [{"message": {"content": "ok"}}]}
        threads = set()
        with patch.object(relay, "_post_chat", side_effect=slow), \
             patch.dict(os.environ, GROKBOT_MEMBER_JOBS="2"):
            try:
                for uid in range(910, 916):
                    self.upd(uid, {"text": "hi"}, user=MEMBER)
                self.upd(910, {"text": "duplicate"}, user=MEMBER)
                self.assertTrue(two_started.wait(2))
                self.assertEqual(counts["calls"], 2)
                self.assertEqual(len(relay.JOB_ACTIVE), 2)
                self.assertEqual(len([n for n in os.listdir(relay.jobs_dir()) if n.endswith(".json")]), 6)
                release.set()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    threads.update(t for t in threading.enumerate() if t.name.startswith("bridge-job-"))
                    for t in list(threads):
                        t.join(0.02)
                    relay.dispatch_jobs(self.bot)
                    if not relay.JOB_ACTIVE and counts["calls"] == 6:
                        break
                self.assertEqual(counts["calls"], 6)
                self.assertLessEqual(counts["max"], 2)
                self.assertFalse(relay.JOB_ACTIVE)
                self.upd(910, {"text": "duplicate again"}, user=MEMBER)
                self.assertEqual(counts["calls"], 6)
            finally:
                release.set()
                for t in threading.enumerate():
                    if t.name.startswith("bridge-job-"):
                        t.join(5)

class TestIncoming(Base):
    def test_idempotency_header_and_durable_retry(self):
        response = FakeResp(b"")
        response.status = 200
        with patch.object(relay, "forward", self.original["forward"]), \
             patch.object(relay.urllib.request, "urlopen", side_effect=TimeoutError()) as post, \
             patch.object(relay.time, "sleep"):
            self.upd(801, {"text": "do something"})
        self.assertEqual(post.call_count, 3)
        request = post.call_args.args[0]
        self.assertEqual(request.get_header("Idempotency-key"), "telegram:801")
        self.assertEqual(json.loads(request.data)["update_id"], 801)
        path = os.path.join(relay.HOME, "incoming", "801.json")
        self.assertTrue(os.path.exists(path))
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertIn("saved and I'll retry", self.sends()[-1]["text"])
        with patch.object(relay, "forward", self.original["forward"]), \
             patch.object(relay.urllib.request, "urlopen", return_value=response) as post, \
             patch.object(relay.time, "time", return_value=time.time() + 20):
            relay.drain_incoming_once()
        self.assertEqual(post.call_count, 1)
        self.assertFalse(os.path.exists(path))

    def test_invalid_webhook_url_is_queued_with_visible_error(self):
        with patch.object(relay, "forward", self.original["forward"]), \
             patch.object(relay.urllib.request, "Request", side_effect=ValueError("invalid")):
            self.upd(806, {"text": "hi"})
        self.assertTrue(os.path.exists(os.path.join(relay.HOME, "incoming", "806.json")))
        self.assertIn("saved and I'll retry", self.sends()[-1]["text"])

    def test_demoted_queued_event_uses_member_path(self):
        with patch.object(relay, "forward", return_value=False):
            self.upd(805, {"text": "hello"})
        with relay.state() as s:
            s["roles"][str(OWNER)] = "member"
        with patch.object(relay.time, "time", return_value=time.time() + 20):
            relay.drain_incoming_once()
        self.assertFalse(self.forwarded)
        self.assertEqual(len(self.llm), 1)
        self.assertFalse(os.path.exists(os.path.join(relay.HOME, "incoming", "805.json")))

    def test_queued_failure_can_advance_offset(self):
        update = {"update_id": 804, "message": {"message_id": 7, "from": {"id": OWNER},
                  "chat": {"id": OWNER, "type": "private"}, "text": "hello"}}
        original = relay.tg
        def polling(method, params=None, timeout=35):
            if method == "getUpdates":
                if params["offset"] == 0:
                    return [update]
                raise KeyboardInterrupt()
            return original(method, params, timeout)
        with patch.object(relay, "tg", side_effect=polling), \
             patch.object(relay, "forward", return_value=False):
            with self.assertRaises(KeyboardInterrupt):
                self.bot.poll_forever()
        with relay.state(write=False) as s:
            self.assertEqual(s["offset"], 805)
        self.assertTrue(os.path.exists(os.path.join(relay.HOME, "incoming", "804.json")))

    def test_failed_handling_does_not_advance_offset(self):
        with patch.object(self.bot, "handle", side_effect=OSError()), \
             patch.object(relay, "tg", side_effect=[[{"update_id": 802}], KeyboardInterrupt()]), \
             patch.object(relay.time, "sleep"):
            with self.assertRaises(KeyboardInterrupt):
                self.bot.poll_forever()
        with relay.state(write=False) as s:
            self.assertEqual(s["offset"], 0)

    def test_exhausted_queue_moves_to_failed(self):
        event = {"update_id": 803, "user_id": OWNER, "chat_id": OWNER}
        with relay.incoming_lock() as directory:
            path = os.path.join(directory, "803.json")
            record = {"event": event, "created": time.time(), "attempts": 9, "next_attempt": 0}
            relay.atomic_json(path, record)
        with patch.object(relay, "forward", return_value=False):
            relay.drain_incoming_once()
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(os.path.join(directory, "failed", "803.json")))
        self.assertIn("permanently", self.sends()[-1]["text"])

class TestOutboxSafety(Base):
    def entry(self, value, name="000.json"):
        path = os.path.join(relay.OUTBOX, name)
        with open(path, "w") as f:
            json.dump(value, f)
        os.utime(path, (1, 1))
        return path

    def test_fifo_and_symlink_do_not_block_or_follow(self):
        import signal
        fifo = os.path.join(relay.OUTBOX, "000.json")
        os.mkfifo(fifo)
        target = os.path.join(self.tmp, "target")
        with open(target, "w") as f:
            json.dump({"chat_id": OWNER, "text": "secret target"}, f)
        os.symlink(target, os.path.join(relay.OUTBOX, "001.json"))
        def timeout(*args):
            raise AssertionError("outbox blocked")
        old = signal.signal(signal.SIGALRM, timeout)
        signal.alarm(2)
        try:
            relay.drain_outbox_once()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
        self.assertFalse(self.sends())
        self.assertTrue(os.path.exists(target))
        self.assertEqual(len(os.listdir(relay.FAILED)), 2)
        os.unlink(os.path.join(relay.FAILED, "000.json"))  # leak scanner must not read a FIFO

    def test_destination_authorization(self):
        self.entry({"chat_id": -123, "text": "unknown"})
        relay.drain_outbox_once()
        self.assertFalse(self.sends())
        self.assertTrue(os.path.exists(os.path.join(relay.FAILED, "000.json")))
        relay.remember_chat(-124)
        for i, chat in enumerate((-124, OWNER, -125)):
            self.entry({"chat_id": chat, "text": "allowed"}, f"{i + 1}.json")
        with patch.dict(os.environ, GROKBOT_OUTBOX_CHATS="-125, -126"):
            relay.drain_outbox_once()
        self.assertEqual([p["chat_id"] for p in self.sends()], [-124, OWNER, -125])
        with relay.state(write=False) as s:
            self.assertIn(-125, s["seen_chats"])

    def test_invalid_retry_metadata_does_not_stall_other_entries(self):
        self.entry({"chat_id": OWNER, "text": "bad", "next_attempt": "never"})
        self.entry({"chat_id": OWNER, "text": "good"}, "001.json")
        relay.drain_outbox_once()
        self.assertEqual([p["text"] for p in self.sends()], ["good"])
        self.assertTrue(os.path.exists(os.path.join(relay.FAILED, "000.json")))

    def test_retry_resumes_after_successful_chunk(self):
        for status in (429, 500):
            with self.subTest(status=status):
                self.calls.clear()
                path = self.entry({"chat_id": OWNER, "text": "a" * 4096 + "tail"})
                original = relay.tg
                chunks = []
                def flaky(method, params=None, timeout=35):
                    if method == "sendMessage":
                        chunks.append(params["text"])
                        if len(chunks) == 2:
                            raise relay.TgError(status, "retry", retry_after=7)
                    return original(method, params, timeout)
                with patch.object(relay, "tg", side_effect=flaky):
                    relay.drain_outbox_once()
                    work = path + ".work"
                    with open(work) as f:
                        saved = json.load(f)
                    self.assertEqual(saved["sent_chars"], 4096)
                    with patch.object(relay.time, "time", return_value=time.time() + 10):
                        relay.drain_outbox_once()
                self.assertEqual(chunks, ["a" * 4096, "tail", "tail"])
                self.assertFalse(os.path.exists(work))

    def test_oversize_rejected_small_entry_delivered(self):
        path = self.entry({"chat_id": OWNER, "text": "x" * (relay.OUTBOX_MAX_BYTES + 1)})
        self.entry({"chat_id": OWNER, "text": "small"}, "001.json")
        relay.drain_outbox_once()
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(os.path.join(relay.FAILED, "000.json")))
        self.assertEqual([p["text"] for p in self.sends()], ["small"])

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
