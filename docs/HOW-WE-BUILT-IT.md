# How we built it

A short build story: the decisions we made and the bugs we hit along the way. It was built in
one afternoon in November 2026 for a household that wanted its Grok Bot in the family
Telegram group.

## The goal

We had used Hermes Agent, and before that OpenClaw, in a family Telegram group, and it worked
well: the whole family talking to one assistant in a chat everyone already
had open. We wanted the same with a Grok Bot.

## Decisions

**Write a small bridge, don't fork a framework.** Hermes and OpenClaw both do Telegram, but
they bring a whole agent runtime with them. Grok Bot already is the agent. All we needed was
a pipe. A stdlib-only Python file is easy to read and audit, and has no dependencies to keep
patched.

**Long-poll instead of a Telegram webhook.** Telegram can push updates to a public HTTPS URL,
but that means an open port, a certificate, and a server. `getUpdates` with a 25-second
timeout needs none of that and runs fine on a box behind NAT.

**Use a Grok Bot webhook routine as the "inbox."** Routines can be triggered by an HTTP POST
with a Bearer key. Each Telegram message becomes one routine run, and the event JSON carries
everything the bot needs, including the path to write its reply to.

**Replies through files, not an API.** The bot and the bridge ran on the same persistent
machine, so the simplest return path was a folder: the bot writes `outbox/<update_id>.json`
and the bridge sends it. Write-to-`.tmp`-then-rename makes it atomic, and the half-second age
check is extra insurance. The same folder lets any routine post proactively.

**Private by default.** An allowlist plus pairing codes, similar to how
OpenClaw handles strangers in DMs: unknown users get a code, the owner approves it. In groups, the
bridge forwards only messages that mention or reply to the bot.

**Crawl, walk, run.** Text first. Photos and voice notes came after the text round trip
worked end to end. Then groups.

## Bugs we hit

### 401 from the webhook: wrong key

The first live test got `webhook HTTP 401`. The webhook URL was right, but the key in the
environment wasn't the routine's current sender key. Re-entering the key from the routine's Webhook section in the desktop app
fixed it. Lessons: the relay logs the HTTP status (never the key), and to confirm a secret
changed without revealing it, compare a short hash prefix such as
`printf %s "$KEY" | sha256sum | cut -c1-8`.

A related gotcha: the webhook URL and key show only in the Grok Bot **desktop** app. On a
phone you can see the routine's instructions but not its Webhook section.

### `set -e` and an `&&` chain in start.sh

`start.sh` runs under `set -eu` and had a one-liner like
`[ -z "$URL" ] && [ -f webhook_url.txt ] && export URL=...`. When a test in the chain is false,
the whole line returns non-zero. Depending on where such a line sits (the end of the script
or a function, or a later edit that changes its position), that status leaks out as a failure
and bites you in confusing ways. We appended `|| true` at the time; this version avoids the
pattern and uses plain `if` blocks.

### PEP 668 blocked pip, so voice got its own venv

`pip install faster-whisper` into the system Python failed with
`error: externally-managed-environment` (PEP 668, Debian/Ubuntu-style distros). Instead of
forcing it with `--break-system-packages`, we put speech-to-text in its own venv
(`.venv-asr`) and kept `relay.py` on the standard library. The relay talks to the
transcriber as a subprocess over one-JSON-object-per-line stdin/stdout, which also keeps the
model warm between voice notes.

### `av.open()` and `metadata_errors`

faster-whisper decodes audio files with PyAV. On our versions, passing a file path to
`model.transcribe()` failed with a `TypeError` about an unexpected keyword argument
`metadata_errors` inside `av.open`. Rather than pinning around it, `transcriber.py` skips
PyAV: `ffmpeg -i <file> -f f32le -ac 1 -ar 16000 -` produces raw 16 kHz mono float32, which
goes to faster-whisper as a numpy array. It works for Telegram's Ogg/Opus voice notes, audio
files, and round video notes.

### Privacy mode changed on the wrong bot

The bot was added to the family group but never saw messages. BotFather's `/setprivacy`
asks you to pick a bot from a list, and the change had been made on a different bot in that
list. `python3 relay.py --check` prints `can_read_all_group_messages` for the token the relay
is actually using, which made the mismatch obvious.

### Privacy changes need the bot to rejoin

After disabling privacy mode on the right bot, group messages still didn't arrive. Telegram
applies the privacy setting when the bot joins a group, so the bot had to be removed from
the group and added back. After that, the next @mention was forwarded and the reply
came back to the group. We added a log line for group messages that arrive but
aren't addressed to the bot, so you can tell "Telegram isn't delivering" apart from "the
relay is ignoring it."

### Admins and members: a hard boundary, not a polite prompt

Once other people could talk to the bot, the owner wanted them able to chat but not to drive
the agent: no shell, no files, no routines, no settings. The first idea was to route members
to a second, "restricted" Grok Bot. We dropped it: agents on the same host share a machine
with shell access, so a restricted agent is not a sandbox. Instead, members never reach any
agent. The relay answers them itself with one plain chat-completion call that sends no tools,
and only admins' messages go to the webhook. New pairings default to member, only admins can
approve, promote, or demote, and the old allowlist migrated with its first entry (the owner)
as admin.

## What we'd do next

See the roadmap in [docs/SETUP.md](SETUP.md#roadmap-ideas): an opt-in all-messages
group mode, rate limits, edits and media replies, and a relay that doesn't need a
shared filesystem. Auto-restart, a keep-alive check, and a persistent typing
indicator landed shortly after the first afternoon.
