#!/usr/bin/env python3
"""Grok Bot Telegram bridge: long-polls Telegram, forwards allowed text, photo and
voice messages to a Grok Bot webhook routine, and sends replies from outbox/.
Photos and audio are saved under media/<update_id>/; voice is transcribed locally by
transcriber.py (faster-whisper in a separate venv) in a long-lived subprocess.

Configuration comes from environment variables (see .env.example).
Secrets come only from the environment; nothing secret is logged or saved.
"""
import base64, collections, fcntl, json, os, re, secrets, select, shutil, subprocess, sys, threading, time, urllib.error, urllib.request
from contextlib import contextmanager

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
# Runtime data (state, outbox, media, logs) lives here. The receiving Grok Bot must be able
# to read media/ and write outbox/ at these same absolute paths.
HOME = os.path.abspath(os.environ.get("GROKBOT_DATA_DIR") or CODE_DIR)
STATE = os.path.join(HOME, "state.json")
LOCK = os.path.join(HOME, "state.lock")
OUTBOX = os.path.join(HOME, "outbox")
FAILED = os.path.join(OUTBOX, "failed")
CODE_TTL = 24 * 3600
MAX_TEXT = 4096
MEDIA = os.path.join(HOME, "media")
MAX_FILE = 20 * 1024 * 1024          # Telegram Bot API getFile limit
MEDIA_TTL = 7 * 24 * 3600
BOT_NAME = os.environ.get("GROKBOT_BOT_NAME") or "The bot"
ASR_PY = os.environ.get("GROKBOT_ASR_PYTHON") or os.path.join(CODE_DIR, ".venv-asr", "bin", "python")
ASR_SCRIPT = os.path.join(CODE_DIR, "transcriber.py")
ASR_LOAD_TIMEOUT = 180
ASR_TIMEOUT = int(os.environ.get("GROKBOT_ASR_TIMEOUT") or "180")
TYPING_MAX = float(os.environ.get("GROKBOT_TYPING_MAX") or "180")
_BOT_URL_RE = re.compile(r"/bot[0-9]+:[A-Za-z0-9_-]+")

def load_dotenv(path=None):
    """Load KEY=VALUE lines from .env next to this file. Existing environment variables win.
    Values are never printed."""
    path = path or os.path.join(CODE_DIR, ".env")
    try:
        with open(path) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) and k not in os.environ:
            os.environ[k] = v

def configure_paths():
    """(Re)compute data paths from GROKBOT_DATA_DIR. Called after .env is loaded."""
    global HOME, STATE, LOCK, OUTBOX, FAILED, MEDIA, BOT_NAME, ASR_PY, ASR_TIMEOUT, TYPING_MAX
    HOME = os.path.abspath(os.environ.get("GROKBOT_DATA_DIR") or CODE_DIR)
    STATE, LOCK = os.path.join(HOME, "state.json"), os.path.join(HOME, "state.lock")
    OUTBOX = os.path.join(HOME, "outbox")
    FAILED = os.path.join(OUTBOX, "failed")
    MEDIA = os.path.join(HOME, "media")
    BOT_NAME = os.environ.get("GROKBOT_BOT_NAME") or "The bot"
    ASR_PY = os.environ.get("GROKBOT_ASR_PYTHON") or os.path.join(CODE_DIR, ".venv-asr", "bin", "python")
    ASR_TIMEOUT = int(os.environ.get("GROKBOT_ASR_TIMEOUT") or "180")
    TYPING_MAX = float(os.environ.get("GROKBOT_TYPING_MAX") or "180")

def log(msg):
    tok = os.environ.get("TELEGRAM_BOT_TOKEN")
    key = os.environ.get("GROKBOT_WEBHOOK_KEY")
    for s in (tok, key, member_llm_key()):
        if s:
            msg = msg.replace(s, "***")
    msg = _BOT_URL_RE.sub("/bot***", msg)
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)

# ---------- state (shared with approve.py via a file lock) ----------
ROLES = ("admin", "member")

def _blank():
    return {"offset": 0, "allowlist": [], "roles": {}, "pending": {}}

def _migrate_roles(s):
    """Pre-roles state had only an allowlist (everyone fully trusted). Make the first
    allowlisted id (the owner, who paired first) admin and everyone else member.
    A one-time copy of the old file is kept as state.json.bak-preroles."""
    if "roles" in s:
        return False
    if os.path.exists(STATE) and not os.path.exists(STATE + ".bak-preroles"):
        shutil.copy2(STATE, STATE + ".bak-preroles")
    al = s.get("allowlist") or []
    s["roles"] = {str(u): ("admin" if i == 0 else "member") for i, u in enumerate(al)}
    return True

def _sync(s):
    """Keep allowlist == ids that have a role (roles is the source of truth)."""
    for u in s["allowlist"]:
        s["roles"].setdefault(str(u), "member")
    s["allowlist"] = sorted(int(u) for u in s["roles"])

def role_of(s, uid):
    """'admin', 'member', or None (not approved). Unknown values fail safe to member."""
    r = s["roles"].get(str(uid))
    if r is None:
        return None
    return r if r in ROLES else "member"

@contextmanager
def state(write=True):
    with open(LOCK, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            with open(STATE) as f:
                s = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            s = _blank()
        migrated = _migrate_roles(s)
        for k, v in _blank().items():
            s.setdefault(k, v)
        _sync(s)
        if migrated:
            write = True
            log("state migrated to roles: " + " ".join(f"{u}={r}" for u, r in s["roles"].items()))
        now = time.time()
        s["pending"] = {c: p for c, p in s["pending"].items() if now - p.get("created", 0) < CODE_TTL}
        yield s
        _sync(s)
        if write:
            tmp = STATE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(s, f, indent=2)
            os.replace(tmp, STATE)

def parse_allowlist(raw, var="GROKBOT_ALLOWLIST"):
    """Parse a comma/space separated list of numeric Telegram user ids."""
    ids = []
    for part in re.split(r"[,\s]+", raw or ""):
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                raise SystemExit(f"{var}: not a numeric user id: {part!r}")
    return ids

def seed_allowlist(raw=None, admins_raw=None):
    """Seed users from the environment (never removes anyone, never demotes anyone).
    GROKBOT_ADMINS ids become admin; GROKBOT_ALLOWLIST ids are added as member."""
    admins = parse_allowlist(os.environ.get("GROKBOT_ADMINS") if admins_raw is None else admins_raw,
                             "GROKBOT_ADMINS")
    ids = parse_allowlist(os.environ.get("GROKBOT_ALLOWLIST") if raw is None else raw)
    if not ids and not admins:
        return 0
    added = 0
    with state() as s:
        for uid in admins:
            if role_of(s, uid) != "admin":
                s["roles"][str(uid)] = "admin"; added += 1
        for uid in ids:
            if role_of(s, uid) is None:
                s["roles"][str(uid)] = "member"; added += 1
        no_admin = "admin" not in s["roles"].values()
    if added:
        log(f"seeded {added} user role(s) from GROKBOT_ADMINS / GROKBOT_ALLOWLIST")
    if no_admin and s["roles"]:
        log("warning: no admin configured; nobody's messages reach the webhook. "
            "Set GROKBOT_ADMINS or run: python3 approve.py --role <user_id> admin")
    return added

def approve_code(code, role="member"):
    """Approve a pending code's user with a role (default member; an existing role is only
    changed if role is given explicitly as admin). Returns the pending dict or None."""
    assert role in ROLES
    code = code.strip().upper()
    with state() as s:
        p = s["pending"].pop(code, None)
        if p:
            cur = role_of(s, p["user_id"])
            s["roles"][str(p["user_id"])] = "admin" if "admin" in (cur, role) else "member"
            p["role"] = s["roles"][str(p["user_id"])]
        return p

def set_role(uid, role):
    """Set an approved user's role. Returns (ok, message). Refuses to remove the last admin."""
    assert role in ROLES
    with state() as s:
        cur = role_of(s, uid)
        if cur is None:
            return False, f"User {uid} isn't approved yet. Approve their pairing code first."
        if cur == role:
            return True, f"User {uid} is already {role}."
        if cur == "admin" and sum(1 for r in s["roles"].values() if r == "admin") <= 1:
            return False, "Can't demote the last admin."
        s["roles"][str(uid)] = role
        return True, f"User {uid} is now {role}."

def remove_user(uid):
    with state() as s:
        if role_of(s, uid) == "admin" and sum(1 for r in s["roles"].values() if r == "admin") <= 1:
            return False
        s["roles"].pop(str(uid), None)
        s["allowlist"] = [u for u in s["allowlist"] if u != uid]
        return True

# ---------- Telegram API ----------
class TgError(Exception):
    def __init__(self, status, desc, retry_after=None):
        super().__init__(f"HTTP {status}: {desc}")
        self.status, self.desc, self.retry_after = status, desc, retry_after

def tg(method, params=None, timeout=35):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(params or {}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
        except Exception:
            body = {"description": e.reason}
        ra = (body.get("parameters") or {}).get("retry_after")
        raise TgError(e.code, body.get("description", "error"), ra) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TgError(0, f"network: {type(e).__name__}") from None
    if not body.get("ok"):
        raise TgError(200, body.get("description", "not ok"))
    return body["result"]

def send_text(chat_id, text, reply_to=None):
    for i in range(0, max(len(text), 1), MAX_TEXT):
        p = {"chat_id": chat_id, "text": text[i:i + MAX_TEXT]}
        if reply_to and i == 0:
            p["reply_to_message_id"] = reply_to
            p["allow_sending_without_reply"] = True
        tg("sendMessage", p, timeout=20)

def chat_action(chat_id, action="typing"):
    try:
        tg("sendChatAction", {"chat_id": chat_id, "action": action}, timeout=10)
    except Exception:
        pass

# ---------- media ----------
IMG_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
           "image/heic": ".heic", "image/heif": ".heif", "image/bmp": ".bmp", "image/tiff": ".tif"}
AUD_EXT = {"audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/x-m4a": ".m4a",
           "audio/aac": ".aac", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/flac": ".flac",
           "audio/webm": ".webm", "audio/opus": ".opus"}

def _ext(name, mime, table, default):
    e = os.path.splitext(name or "")[1].lower()
    if re.fullmatch(r"\.[a-z0-9]{1,5}", e or ""):
        return e
    return table.get((mime or "").lower(), default)

def extract_media(msg):
    """Return dict(kind, file_id, size, ext, mime) for a supported attachment, else None."""
    if msg.get("photo"):
        p = max(msg["photo"], key=lambda x: (x.get("file_size") or 0, x.get("width", 0) * x.get("height", 0)))
        return {"kind": "photo", "file_id": p["file_id"], "size": p.get("file_size"),
                "ext": ".jpg", "mime": "image/jpeg"}
    d = msg.get("document")
    if d and (d.get("mime_type") or "").lower().startswith("image/"):
        return {"kind": "photo", "file_id": d["file_id"], "size": d.get("file_size"),
                "ext": _ext(d.get("file_name"), d.get("mime_type"), IMG_EXT, ".img"), "mime": d.get("mime_type")}
    for field, default in (("voice", ".ogg"), ("audio", ".mp3"), ("video_note", ".mp4")):
        a = msg.get(field)
        if a:
            ext = default if field != "audio" else _ext(a.get("file_name"), a.get("mime_type"), AUD_EXT, default)
            return {"kind": "voice", "source_field": field, "file_id": a["file_id"], "size": a.get("file_size"),
                    "ext": ext, "mime": a.get("mime_type"), "duration": a.get("duration")}
    return None

class TooLarge(Exception):
    pass

class DownloadError(Exception):
    pass

def _open_file_url(url, timeout):
    return urllib.request.urlopen(url, timeout=timeout)

def download_file(file_id, dest_dir, ext):
    """getFile + download. Never logs or stores the file URL (it contains the token)."""
    info = tg("getFile", {"file_id": file_id}, timeout=20)
    if (info.get("file_size") or 0) > MAX_FILE:
        raise TooLarge()
    fp = info.get("file_path")
    if not fp:
        raise DownloadError("no file_path")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "media" + ext)
    tmp = dest + ".part"
    try:
        with _open_file_url(f"https://api.telegram.org/file/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{fp}", 60) as r, \
                open(tmp, "wb") as f:
            n = 0
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                n += len(chunk)
                if n > MAX_FILE:
                    raise TooLarge()
                f.write(chunk)
    except TooLarge:
        _rm(tmp); raise
    except urllib.error.HTTPError as e:
        _rm(tmp); raise DownloadError(f"HTTP {e.code}") from None
    except Exception as e:
        _rm(tmp); raise DownloadError(type(e).__name__) from None
    os.replace(tmp, dest)
    return dest, n

def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass

def cleanup_media(now=None):
    now = now or time.time()
    if not os.path.isdir(MEDIA):
        return 0
    removed = 0
    for name in os.listdir(MEDIA):
        p = os.path.join(MEDIA, name)
        try:
            if now - os.path.getmtime(p) > MEDIA_TTL:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
                removed += 1
        except OSError:
            pass
    if removed:
        log(f"media cleanup removed {removed} item(s)")
    return removed

class Transcriber:
    """Keeps one faster-whisper helper process warm; restarts it on error or timeout."""
    def __init__(self):
        self.proc, self.lock = None, threading.Lock()

    def _kill(self):
        if self.proc:
            try:
                self.proc.kill(); self.proc.wait(5)
            except Exception:
                pass
            for s in (self.proc.stdin, self.proc.stdout):
                try:
                    s.close()
                except Exception:
                    pass
        self.proc = None

    def _readline(self, timeout):
        r, _, _ = select.select([self.proc.stdout], [], [], timeout)
        if not r:
            raise TimeoutError()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("transcriber exited")
        return json.loads(line)

    def _start(self):
        errf = open(os.path.join(HOME, "transcriber.err"), "ab")
        self.proc = subprocess.Popen([ASR_PY, ASR_SCRIPT], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=errf, text=True, bufsize=1, cwd=CODE_DIR)
        errf.close()
        if not self._readline(ASR_LOAD_TIMEOUT).get("ready"):
            raise RuntimeError("transcriber not ready")

    def transcribe(self, path, timeout=None):
        """Return (transcript_or_None, error_or_None)."""
        with self.lock:
            try:
                if not self.proc or self.proc.poll() is not None:
                    self._start()
                self.proc.stdin.write(json.dumps({"path": path}) + "\n"); self.proc.stdin.flush()
                res = self._readline(timeout or ASR_TIMEOUT)
            except TimeoutError:
                self._kill(); return None, "timeout"
            except Exception as e:
                self._kill(); return None, type(e).__name__
            if res.get("ok"):
                return res.get("text", ""), None
            return None, (res.get("error") or "error").split(":")[0]

TRANSCRIBER = Transcriber()

# ---------- webhook ----------
def webhook_config():
    url, key = os.environ.get("GROKBOT_WEBHOOK_URL"), os.environ.get("GROKBOT_WEBHOOK_KEY")
    return (url, key) if url and key else None

def forward(event):
    cfg = webhook_config()
    if not cfg:
        log(f"webhook not configured; not forwarding update_id={event['update_id']}")
        return False
    url, key = cfg
    req = urllib.request.Request(url, data=json.dumps(event).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                log(f"forwarded update_id={event['update_id']} status={r.status}")
                return True
        except urllib.error.HTTPError as e:
            log(f"webhook HTTP {e.code} update_id={event['update_id']}")
            if e.code < 500 and e.code != 429:
                return False
        except Exception as e:
            log(f"webhook error {type(e).__name__} update_id={event['update_id']}")
        time.sleep(2 ** attempt)
    return False

# ---------- member chat (hard sandbox) ----------
# Members never reach the Grok Bot webhook (that agent has tools and a shell). Their messages
# go to a plain chat-completion call: no tools, no function calling, no files, no shell.
MEMBER_HISTORY_MAX = 10
MEMBER_HISTORY = collections.defaultdict(lambda: collections.deque(maxlen=MEMBER_HISTORY_MAX))
MEMBER_HISTORY_LOCK = threading.Lock()
MEMBER_THREADED = True          # tests set False to run replies inline
VISION_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
NO_KEY_REPLY = "I'm only set up to chat with admins right now."
LLM_FAIL_REPLY = "Sorry, I couldn't come up with a reply just now. Please try again in a bit."
ADMIN_ONLY_REPLY = "Only an admin can do that."

def _menv(suffix, default=None):
    return os.environ.get("GROKBOT_MEMBER_LLM_" + suffix) or default

def member_llm_key():
    return _menv("API_KEY")

def member_llm_config():
    return {"base_url": _menv("BASE_URL", "https://api.x.ai/v1").rstrip("/"),
            "model": _menv("MODEL", "grok-4.3"),
            "key": member_llm_key(),
            "timeout": float(_menv("TIMEOUT", "60")),
            "vision": (_menv("VISION", "1") or "1").lower() not in ("0", "false", "no", "off")}

def MEMBER_BOT_NAME():
    return os.environ.get("GROKBOT_BOT_NAME") or "the household assistant"

def member_system_prompt():
    name = MEMBER_BOT_NAME()
    return (f"You are {name}, a friendly household assistant chatting in Telegram with family and "
            "friends. In this conversation you can only talk: answer questions, brainstorm, explain, "
            "help with wording, and keep people company. You cannot take any actions. You can't run "
            "commands or programs, open or read files, access anyone's accounts, email, calendar or "
            "devices, browse the web, buy anything, or set reminders, timers, schedules or routines. "
            "If someone asks for any of that, say kindly that you can't do it from this chat and "
            "suggest they ask the bot's admin. Never pretend you did something. You may not know "
            "recent events. Several people may be in the chat; user messages start with the "
            "sender's first name. Keep replies short and warm, plain text, no markdown headings.")

def _post_chat(cfg, payload):
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=json.dumps(payload).encode(),
        method="POST", headers={"Content-Type": "application/json",
                                "Authorization": f"Bearer {cfg['key']}"})
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        return json.loads(r.read())

def member_reply_text(chat_id, first_name, text, image_path=None):
    """Return (reply, status). Never raises. Only text in, text out; no tools are offered."""
    cfg = member_llm_config()
    if not cfg["key"]:
        return NO_KEY_REPLY, "no-key"
    who = (first_name or "Someone").strip()[:40]
    turn = f"{who}: {text}" if text else f"{who}: (no text)"
    with MEMBER_HISTORY_LOCK:
        history = list(MEMBER_HISTORY[chat_id])
    content = turn
    if image_path and cfg["vision"]:
        mime = VISION_MIME.get(os.path.splitext(image_path)[1].lower())
        if mime:
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            content = [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                       {"type": "text", "text": turn}]
    messages = [{"role": "system", "content": member_system_prompt()}] + history + \
               [{"role": "user", "content": content}]
    payload = {"model": cfg["model"], "messages": messages, "stream": False, "max_tokens": 800}
    try:
        body = _post_chat(cfg, payload)
        reply = (body["choices"][0]["message"].get("content") or "").strip()
        if not reply:
            raise ValueError("empty reply")
    except urllib.error.HTTPError as e:
        return LLM_FAIL_REPLY, f"http-{e.code}"
    except Exception as e:
        return LLM_FAIL_REPLY, type(e).__name__
    with MEMBER_HISTORY_LOCK:
        h = MEMBER_HISTORY[chat_id]
        h.append({"role": "user", "content": turn if not image_path else f"{who}: [sent a photo] {text}".rstrip()})
        h.append({"role": "assistant", "content": reply[:4000]})
    return reply, "ok"

def _member_job(upd_id, chat_id, mid, first_name, text, image_path, name):
    t0 = time.time()
    try:
        reply, status = member_reply_text(chat_id, first_name, text, image_path)
        try:
            send_text(chat_id, reply, mid)
        except TgError as e:
            status += f" send-failed:{e.status}"
        log(f"member reply update_id={upd_id} path=member-llm status={status} chars={len(reply)} secs={time.time() - t0:.1f}")
    except Exception as e:
        log(f"member reply error update_id={upd_id}: {type(e).__name__}")
    finally:
        typing_stop(name)

def run_member_job(*args):
    if MEMBER_THREADED:
        threading.Thread(target=_member_job, args=args, daemon=True).start()
    else:
        _member_job(*args)

# ---------- inbound handling ----------
class Bot:
    def __init__(self):
        me = tg("getMe", timeout=15)
        self.id, self.username = me["id"], (me.get("username") or "").lower()

    def addressed(self, msg):
        r = msg.get("reply_to_message") or {}
        if (r.get("from") or {}).get("id") == self.id:
            return True
        text = msg.get("text") or msg.get("caption") or ""
        for ent in (msg.get("entities") or []) + (msg.get("caption_entities") or []):
            frag = text[ent["offset"]:ent["offset"] + ent["length"]].lower()
            if ent["type"] == "mention" and frag == "@" + self.username:
                return True
            if ent["type"] == "bot_command" and frag.endswith("@" + self.username):
                return True
            if ent["type"] == "text_mention" and (ent.get("user") or {}).get("id") == self.id:
                return True
        return False

    def pairing_reply(self, msg, user):
        uid = user["id"]
        with state() as s:
            code = next((c for c, p in s["pending"].items() if p["user_id"] == uid), None)
            if not code:
                code = secrets.token_hex(3).upper()
                s["pending"][code] = {"user_id": uid, "username": user.get("username"),
                                      "first_name": user.get("first_name"),
                                      "chat_id": msg["chat"]["id"], "created": time.time()}
        log(f"pairing code issued user_id={uid}")
        send_text(msg["chat"]["id"], "This bot is private. To request access, ask the owner to "
                  f"approve pairing code: {code}", msg.get("message_id"))

    def handle(self, upd):
        msg = upd.get("message")
        if not msg:
            return
        media = None if "text" in msg else extract_media(msg)
        if "text" not in msg and not media:
            return  # edits, stickers, video, joins, etc. are ignored
        user, chat = msg.get("from") or {}, msg["chat"]
        if user.get("is_bot") or "id" not in user:
            return
        uid, ctype = user["id"], chat.get("type")
        text = msg["text"] if "text" in msg else (msg.get("caption") or "")
        is_dm = ctype == "private"
        if not is_dm and not (ctype in ("group", "supergroup") and self.addressed(msg)):
            log(f"update_id={upd['update_id']} user_id={uid} chat_type={ctype} not addressed; ignored")
            return
        with state(write=False) as s:
            role = role_of(s, uid)
        allowed = role is not None
        kind = media["kind"] if media else "text"
        log(f"update_id={upd['update_id']} user_id={uid} chat_type={ctype} kind={kind} allowed={allowed} role={role}")
        if not allowed:
            self.pairing_reply(msg, user)
            return
        mid = msg.get("message_id")
        cmd = text.strip().split() if not media else []
        verb = cmd[0].split("@")[0].lower() if cmd else ""
        if verb in ("/approve", "/promote", "/demote"):
            if role != "admin":
                log(f"update_id={upd['update_id']} user_id={uid} role={role} command={verb} denied")
                send_text(chat["id"], ADMIN_ONLY_REPLY, mid)
                return
            if verb == "/approve":
                p = approve_code(cmd[1]) if len(cmd) > 1 else None
                send_text(chat["id"], f"Approved user {p['user_id']} as {p['role']}." if p else
                          "Usage: /approve <code> (code unknown or expired)", mid)
                if p:
                    log(f"approved user_id={p['user_id']} role={p['role']} by user_id={uid}")
                return
            target = cmd[1] if len(cmd) > 1 else ""
            if not re.fullmatch(r"-?[0-9]+", target):
                send_text(chat["id"], f"Usage: {verb} <user_id>", mid)
                return
            new = "admin" if verb == "/promote" else "member"
            ok, note = set_role(int(target), new)
            send_text(chat["id"], note, mid)
            log(f"{verb[1:]} user_id={target} ok={ok} by user_id={uid}")
            return
        if verb == "/whoami":
            send_text(chat["id"], f"user_id={uid} chat_id={chat['id']} role={role}", mid)
            return
        if role != "admin":
            self.handle_member(upd, msg, user, chat, text, media, kind)
            return
        event = {"source": "telegram", "update_id": upd["update_id"],
                 "chat_id": chat["id"], "chat_type": ctype, "chat_title": chat.get("title"),
                 "message_id": msg.get("message_id"), "user_id": uid,
                 "username": user.get("username"), "first_name": user.get("first_name"),
                 "text": text, "date": msg.get("date"),
                 "reply_file": os.path.join(OUTBOX, f"{upd['update_id']}.json"),
                 "kind": kind, "media_path": None, "transcript": None, "role": "admin"}
        name = f"{upd['update_id']}.json"
        typing_start(name, chat["id"])
        if media and not self.prepare_media(upd, msg, media, event):
            typing_stop(name)
            return
        log(f"update_id={upd['update_id']} role=admin path=webhook")
        ok = forward(event)
        if not ok:
            typing_stop(name)
        if not ok and webhook_config() is None:
            send_text(chat["id"], f"{BOT_NAME} isn't connected yet. Try again later.", msg.get("message_id"))

    def handle_member(self, upd, msg, user, chat, text, media, kind):
        """Members never reach the webhook. The relay answers them itself (chat only)."""
        uidd, mid = upd["update_id"], msg.get("message_id")
        log(f"update_id={uidd} role=member path=member-llm kind={kind}")
        name = f"member-{uidd}"
        typing_start(name, chat["id"])
        image_path = None
        if media:
            ev = {"text": text}
            if not self.prepare_media(upd, msg, media, ev):
                typing_stop(name)
                return
            if media["kind"] == "photo":
                image_path = ev["media_path"]
                if not (member_llm_config()["vision"] and
                        VISION_MIME.get(os.path.splitext(image_path)[1].lower())):
                    text = "[sent a photo I can't view]" + (f" {text}" if text else "")
                    image_path = None
            else:
                text = ev["text"].replace("; the audio file is at media_path", "")
        run_member_job(uidd, chat["id"], mid, user.get("first_name"), text, image_path, name)

    def prepare_media(self, upd, msg, media, event):
        """Download (and for voice, transcribe) the attachment into event. False = stop."""
        chat_id, mid, uidd = msg["chat"]["id"], msg.get("message_id"), upd["update_id"]
        if (media.get("size") or 0) > MAX_FILE:
            log(f"update_id={uidd} kind={media['kind']} rejected size={media['size']} (over 20MB)")
            send_text(chat_id, "That file is over Telegram's 20 MB limit for bots, so I can't open it. "
                      "Could you send a smaller or compressed version?", mid)
            return False
        chat_action(chat_id, "typing")
        try:
            path, size = download_file(media["file_id"], os.path.join(MEDIA, str(uidd)), media["ext"])
        except TooLarge:
            log(f"update_id={uidd} kind={media['kind']} rejected (over 20MB)")
            send_text(chat_id, "That file is over Telegram's 20 MB limit for bots, so I can't open it. "
                      "Could you send a smaller or compressed version?", mid)
            return False
        except (DownloadError, TgError) as e:
            log(f"update_id={uidd} kind={media['kind']} download failed: {type(e).__name__} {e}")
            send_text(chat_id, "Sorry, I couldn't download that file from Telegram. Please try again.", mid)
            return False
        event["media_path"], event["media_mime"], event["media_size"] = path, media.get("mime"), size
        if media["kind"] == "photo":
            log(f"update_id={uidd} kind=photo saved size={size}")
            return True
        event["media_duration"] = media.get("duration")
        event["voice_source"] = media.get("source_field")
        caption = event["text"]
        chat_action(chat_id, "typing")
        t0 = time.time()
        transcript, err = TRANSCRIBER.transcribe(path)
        event["transcript"] = transcript
        if transcript is not None:
            body = f"[Voice note, transcribed] {transcript}" if transcript else "[Voice note, transcribed: no speech detected]"
            log(f"update_id={uidd} kind=voice saved size={size} transcribed chars={len(transcript)} secs={time.time() - t0:.1f}")
        else:
            body = f"[Voice note: transcription failed ({err}); the audio file is at media_path]"
            event["transcript_error"] = err
            log(f"update_id={uidd} kind=voice saved size={size} transcription failed: {err}")
        event["text"] = body + (f"\n[Caption] {caption}" if caption else "")
        return True

    def poll_forever(self):
        backoff = 1
        while True:
            with state(write=False) as s:
                offset = s["offset"]
            try:
                updates = tg("getUpdates", {"offset": offset, "timeout": 25,
                                            "allowed_updates": ["message"]}, timeout=40)
                backoff = 1
            except TgError as e:
                wait = e.retry_after or backoff
                log(f"getUpdates failed: {e}; sleeping {wait}s")
                time.sleep(wait)
                backoff = min(backoff * 2, 60)
                if e.status == 401:
                    backoff = 60
                continue
            for upd in updates:
                try:
                    self.handle(upd)
                except Exception as e:
                    log(f"handler error update_id={upd.get('update_id')}: {type(e).__name__} {e}")
                with state() as s:
                    s["offset"] = max(s["offset"], upd["update_id"] + 1)

# ---------- typing indicator ----------
# Telegram's "typing..." lasts ~5s per call, so refresh it every 4s while a reply is pending.
TYPING = {}            # reply file name -> (chat_id, started_at)
TYPING_LOCK = threading.Lock()

def typing_start(name, chat_id):
    with TYPING_LOCK:
        TYPING[name] = (chat_id, time.time())
    chat_action(chat_id, "typing")

def typing_stop(name):
    with TYPING_LOCK:
        TYPING.pop(name, None)

def typing_loop():
    while True:
        time.sleep(4)
        now = time.time()
        with TYPING_LOCK:
            for k, (_, t0) in list(TYPING.items()):
                if now - t0 > TYPING_MAX:
                    TYPING.pop(k, None)
            chats = {c for c, _ in TYPING.values()}
        for c in chats:
            chat_action(c, "typing")

# ---------- outbox ----------
def drain_outbox_once():
    for name in sorted(os.listdir(OUTBOX)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(OUTBOX, name)
        try:
            if time.time() - os.path.getmtime(path) < 0.5:
                continue  # may still be being written
            with open(path) as f:
                r = json.load(f)
            chat_id, text = int(r["chat_id"]), str(r["text"])
            if not text.strip():
                raise ValueError("empty text")
        except FileNotFoundError:
            continue
        except Exception as e:
            typing_stop(name)
            log(f"outbox bad file {name}: {type(e).__name__}; moved to failed/")
            os.replace(path, os.path.join(FAILED, name))
            continue
        try:
            send_text(chat_id, text, r.get("reply_to_message_id"))
            typing_stop(name)
            os.remove(path)
            log(f"sent reply {name} chat_id={chat_id}")
        except TgError as e:
            if e.status == 429 or e.status == 0 or e.status >= 500:
                log(f"reply {name} deferred: {e}")
                time.sleep(e.retry_after or 5)
                return
            typing_stop(name)
            log(f"reply {name} failed: {e}; moved to failed/")
            os.replace(path, os.path.join(FAILED, name))

def outbox_loop():
    while True:
        try:
            drain_outbox_once()
        except Exception as e:
            log(f"outbox loop error: {type(e).__name__}")
        global _last_cleanup
        if time.time() - _last_cleanup > 6 * 3600:
            _last_cleanup = time.time()
            try:
                cleanup_media()
            except Exception as e:
                log(f"media cleanup error: {type(e).__name__}")
        time.sleep(1)

_last_cleanup = 0.0

def main():
    load_dotenv()
    configure_paths()
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        sys.exit("TELEGRAM_BOT_TOKEN is not set")
    os.makedirs(FAILED, exist_ok=True)
    os.makedirs(MEDIA, exist_ok=True)
    seed_allowlist()
    if "--check" in sys.argv:
        try:
            me = tg("getMe", timeout=15)
        except TgError as e:
            sys.exit(f"getMe failed: {e}")
        print(json.dumps({"id": me["id"], "username": me.get("username"),
                          "name": me.get("first_name"),
                          "can_read_all_group_messages": me.get("can_read_all_group_messages")}))
        print("webhook configured:", bool(webhook_config()))
        return
    while True:
        try:
            bot = Bot()
            break
        except TgError as e:
            log(f"getMe failed: {e}; retrying in 30s")
            time.sleep(30)
    log(f"started as @{bot.username} id={bot.id}; webhook configured={bool(webhook_config())}; "
        f"member llm key set={bool(member_llm_key())} model={member_llm_config()['model']}")
    threading.Thread(target=outbox_loop, daemon=True).start()
    threading.Thread(target=typing_loop, daemon=True).start()
    bot.poll_forever()

if __name__ == "__main__":
    main()
