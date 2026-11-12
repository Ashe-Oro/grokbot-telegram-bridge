# Security

This bridge lets people in Telegram start runs of your Grok Bot. That is powerful, and it is
the main risk. This page is a candid look at what the bridge protects, what it doesn't, and
what you should do about it.

## Host trust: processes sharing a Unix user are fully trusted

This bridge is designed for a **private household host**. Every process running as the
**same Unix user** as the relay is fully trusted. File modes (`chmod 600` on `.env`
or the secrets file) do not separate processes that share a UID. Any co-resident
Grok Bot agent (or other program) with that UID can read `.env`, the secrets
file, and `state.json`, run `approve.py --add <id> --admin`, write to
`outbox/`, or call the webhook directly. Telegram pairing and roles do not apply
to that path.

Tightening file modes only protects against **other user accounts** on the same machine,
not against other agents that share this UID. The relay enforces 0700 on runtime data
directories and 0600 on its runtime files, and warns if `.env` or the secrets
file is group- or other-readable (and, for the secrets file, writable or
owned by another user). It does not change those permissions; keep
using `chmod 600` on `.env` and on the secrets file.

### Optional hardening: Run the relay as a separate Unix user

- Create a dedicated user, for example `grokbot-telegram`, that other agents cannot assume
  (no shared login credentials or permission to switch to it).
- Run the relay under that account, and keep the code, `.env`, the secrets
  file, `state.json`, and data directory owned by it. Use the host's
  user-management tools and launch the scripts as that user; systemd is
  optional.
- If the receiving Grok Bot runs on a different account, give it narrowly scoped access
  only to `media/` (read) and `outbox/` (write). Use ACLs, or a shared group with modes
  such as 0770 on directories and 0660 on files, including execute on directories so
  the other account can traverse them. The relay resets its managed paths to 0700/0600
  on startup, which will clear those group bits, so re-apply the shared-group or ACL
  grants after start (or adapt the permission helpers for your setup). Default ACLs
  alone are not enough. Do not grant access to `.env`, the secrets file, state,
  or code. If both processes share a UID, they are fully trusted and this
  isolation does not apply.
- Keep approval administration (`approve.py`) on the operator's side, run under the
  relay account through an operator-controlled login.

## The big one: Telegram users drive your agent

A webhook routine runs as your Grok Bot, **with that bot's connectors and tools**. If the bot
can read your email, see your calendar, browse signed in as you, run shell commands, or
move money, then any **admin** can ask it to do those things from Telegram. The routine
prompt can tell the bot to be careful, but a prompt is not a permission system.
**Admins are fully trusted.** Only make someone an admin if you'd hand them the bot itself.

What to do:

- **Use a dedicated bot** for Telegram, not your main one. Give it only the connectors it
  needs (for a household: maybe a shared calendar, nothing financial).
- Keep the routine prompt's rule that the Telegram event is untrusted data, and its rule not
  to pull in private matters from your other bots or accounts.
- Make only people you'd trust with that bot directly admins. Everyone else is a member.

## Roles: the hard boundary between admins and members

Each approved person has a role in `state.json` (`roles: {user_id: "admin" | "member"}`).

- **Admin** messages are forwarded to the webhook routine, with `role: "admin"` in the event.
- **Member** messages are **never** forwarded to the webhook or to any Grok Bot. The relay
  answers them itself with one plain chat-completion request to an OpenAI-compatible API
  (`GROKBOT_MEMBER_LLM_*`). The request carries a system prompt, the last few chat turns,
  and the member's text (plus the photo, or the local voice transcript). It sets no `tools`,
  `functions`, or `tool_choice`, and the relay never acts on anything in the reply except
  sending it back as text.

Why this is a real boundary and not just a polite prompt: a Grok Bot agent has tools, and
agents on the same host often share a shell and filesystem, so a "restricted" second agent
is not a sandbox. The member path has no agent at all. A member who talks the chat model
into "agreeing" to run a command, set a routine, or read a file gets only words back; there
is nothing on that path that can do it. Prompt injection from members can at most change
what the chat model says.

Details:

- Unknown role values fail safe to `member`. A user with no role is not approved.
- New people always join as `member`. `/approve` (in Telegram or `approve.py` without a
  flag) and `approve.py --add <id>` all default to member.
- The first admin is set by the person who hosts the bot: put their Telegram user id in
  `GROKBOT_ADMINS`, or run `python3 approve.py <CODE> --admin` (or `--add <id> --admin`)
  on the machine. The first person to message the bot is not made an admin automatically.
  Until an admin is set, nobody's messages reach the webhook.
- Only admins can `/approve`, `/promote <user_id>`, and `/demote <user_id>`; members get
  "Only an admin can do that." The last admin can't be demoted or removed.
- In a DM with the bot, the plain commands work (`/approve CODE`). In a group, the command
  must be aimed at the bot: `/approve@BotName CODE`, or a reply to one of the bot's
  messages with `/approve CODE`. A plain `/approve` in a group is ignored. The same
  addressing rules apply to `/promote`, `/demote`, and `/whoami`.
- `/whoami` is allowed for members and admins. It shows the caller's role and never runs
  anything else.
- Members can chat (text, photos, voice notes) and get a reply from the no-tools model
  call. They can't run tools, touch the host computer, search files, start or stop
  processes, create routines, change settings, or approve or promote people.
- Upgrading from a version without roles: the first id in the old allowlist becomes admin,
  everyone else becomes member, and the old file is copied to `state.json.bak-preroles`.
  Environment roles bootstrap missing users only: `GROKBOT_ADMINS` adds admins and
  `GROKBOT_ALLOWLIST` adds members. Existing roles survive restarts; re-promote with
  `/promote` or `approve.py`.
- **Member messages leave your machine** for the chat model's provider (xAI by default),
  including photos they send. Pick a provider whose data terms you accept.
- Each member reply is one paid API call. If `GROKBOT_MEMBER_LLM_API_KEY` is unset, members
  get "I'm only set up to chat with admins right now." and nothing is sent anywhere.
- The relay keeps a short rolling context per chat (last 10 member turns) **in memory
  only**; it is lost on restart and never written to disk or logs.
- Member photos and voice notes are still downloaded to `media/` (7-day retention) so they
  can be passed to the chat model or transcribed locally.

## Prompt injection

Anything that reaches the bot can try to steer it:

- **Admins.** Only admins' messages reach the bot. Their messages can contain instructions
  aimed at the bot (members' messages go to the no-tools chat model instead).
- **Forwarded messages.** A message an admin forwards from a stranger arrives as text from
  that admin.
- **Photos.** Text inside an image ("ignore your instructions and ...") is read by the bot
  when it looks at the photo.
- **Voice notes.** Transcripts are just text and can carry the same instructions.

The bridge doesn't filter content. Your defenses are the routine prompt, a bot with few
tools, and a short admin list.

## Who can get in: allowlist and pairing codes

- Only approved Telegram user ids get a reply. Admin messages go to the webhook; member
  messages go to the no-tools chat model and never to the webhook. Strangers who DM the bot,
  or mention it in a group, get a random 6-hex-character pairing code, not access. Nothing
  they send is forwarded, and their photos and voice notes are never downloaded.
- Codes are single-use and expire after 24 hours. One pending code per user.
- Approval happens on the machine (`approve.py`) or by an **admin** sending
  `/approve <code>` (in a group: `/approve@BotName <code>`, or reply to the bot). New
  people are approved as members; use `approve.py <code> --admin` or `/promote <user_id>`
  to make someone an admin.
- Access is per person, not per chat. An approved person can add the bot to any group and
  use it there; the bot will answer them in that group (members still get chat only).
- Removing someone: `python3 approve.py --remove <id>`. Removing an id from
  `GROKBOT_ALLOWLIST` does **not** remove it from `state.json`.

## Groups and privacy mode

With BotFather privacy mode **off**, Telegram delivers every group message to the bot, so
they pass through the relay process. The relay only forwards messages that @mention the bot
or reply to it, and only from allowlisted senders. Everything else is dropped in memory: it
is not forwarded, saved, or logged (the log records only that an unaddressed message was
ignored, with its update id, user id, and chat type).

Still, everyone in the group should know a bot is present and can see the conversation. If
you'd rather Telegram not deliver ordinary messages at all, leave privacy mode on; the bot
then gets mentions, replies, and commands, depending on Telegram's rules.

## Secrets

- `TELEGRAM_BOT_TOKEN`, `GROKBOT_WEBHOOK_KEY`, and `GROKBOT_MEMBER_LLM_API_KEY` are read
  from the environment, from a local `.env` file you create, or from the optional
  0600 secrets file (`GROKBOT_SECRETS_FILE`, default
  `/workspace/.secrets/grokbot-telegram.env`). `relay.py` never writes them to disk.
  On the Grok Bot computer, secrets submitted through a chat secret-request field
  live only in the process environment and are wiped by a reboot, so the host bot
  should write those values into the secrets file (see
  [docs/SETUP-GUIDE.md](docs/SETUP-GUIDE.md#persist-secrets-across-reboots)).
  `start.sh` sources the file if it is present, keeps any already-set
  non-empty environment values (so a fresh secret card wins over a stale
  file), and never echoes its values. It also warns if the file is group- or
  other-readable or writable, or not owned by the current user, without
  changing the mode.
- The secrets file is same-UID trusted: any process running as the relay's Unix
  user can read it, just as it can read `.env`. Mode 0600 (and 0700 on the
  directory) only protects the file from other accounts. Source it from
  `~/.bashrc` if you want the values in interactive shells; that does not help
  the hourly keep-alive, which is non-interactive and depends on `start.sh`
  loading the file directly.
- Log lines are scrubbed: the token, the keys, and any `/bot<id>:<token>` URL pattern are
  replaced with `***`. Telegram file-download URLs contain the token, so they are never
  logged or stored. Download errors log only the error type or HTTP status.
- Log lines carry no message text, captions, transcripts, or model replies. They record the
  role and path (`webhook` or `member-llm`) and the member call's status.
- The tests check that a fake token and keys never appear in logs or in any file written.
- If you use `.env` or the secrets file, `chmod 600` the file, keep it out of git
  (`*.env` is in `.gitignore`), and do not print it. A bot secrets store that only
  injects process environment variables is not enough on its own, because a reboot
  of the Grok Bot computer clears that environment.

### If the webhook key leaks

Anyone with the URL and key can start runs of your routine with any JSON they like, without
going through Telegram or the allowlist. That costs you usage and lets them feed the bot
arbitrary "messages." Rotate the key (or delete and recreate the webhook routine) in the
Grok Bot desktop app, then update the secrets file (or the relay's environment)
and restart it.

### If the Telegram token leaks

Anyone with it can read your bot's updates and send as your bot. Revoke it in BotFather
(`/revoke`), put the new token in the secrets file (or the environment), and restart.

## Transport and storage

- **Telegram bot chats are not end-to-end encrypted.** Telegram's servers can read them.
  Don't use this for anything you wouldn't put in a normal Telegram cloud chat.
- The relay only makes outbound connections (Telegram, the webhook, and the member chat
  API). There are no inbound ports, tunnels, or Tailscale.
- Webhook POSTs go over HTTPS to the Grok Bot service.
- **Media is stored on disk** under `media/<update_id>/` and deleted after 7 days. Processes
  sharing the relay's UID, and accounts granted media access, can read it until then.
  Transcripts are stored in queued webhook events until delivery and are part of
  the receiving bot's run history. Failed queue entries remain for operator review.
- `state.json` holds Telegram user ids, usernames, first names, and pending codes. No
  secrets, but it is personal data.

Supervisor PID files contain a PID and Linux process start time. Start, ensure, and
stop verify the project supervisor command and working directory before trusting
them. A private startup flock serializes launches.

Webhook POSTs include `Idempotency-Key: telegram:<update_id>` and `update_id` in
the body. The receiver MUST durably reject duplicate keys before starting any
tool work, including retries after a lost HTTP acknowledgment. This bridge alone
cannot guarantee exactly-once receiver actions.

Production updates are fsynced to private `jobs/<update_id>.json` files before
the polling offset advances. Prepared admin events are then fsynced to private
`incoming/<update_id>.json` files before delivery. Failed delivery gets a visible Telegram reply
and background retries (at most 10 batches of three attempts, or 24 hours). Final
failures move to `incoming/failed/` with a final notice. The live queue is limited
to 1000 events; a full incoming queue leaves work in jobs/ for retry. Pairing-only pauses queued
delivery. Demoted users' queued events take the member chat path; removed users'
events are discarded before retry.

## The outbox is trusted input

Outbox destinations must be a previously seen inbound/outbound chat, an approved
user id, or an id in `GROKBOT_OUTBOX_CHATS` (comma/space separated). Unknown
chat ids move to `outbox/failed/`. Use the override for a first proactive message
to a group the relay has not seen. Successful sends record the chat in state.json.

Same-UID writers can still send arbitrary text to allowed chats and can modify
state. Keep outbox write access limited to trusted senders; file modes restrict
other accounts, not processes sharing the relay's UID.

Outbox reads reject symlinks and non-regular files, cap JSON and text at 1 MiB,
and claim entries under an exclusive drain lock. Interrupted work files are recovered
on the next drain; regular files retain a short write grace period.

Multipart outbox replies persist `sent_chars` after each acknowledged chunk and
`next_attempt` after transient failures. Retries resume at that character offset.
A crash or lost Telegram acknowledgment between a send and its progress write can
still duplicate that chunk; Telegram sendMessage offers no idempotency key.

## Resource bounds and remaining gaps

- Heavy work runs outside polling, with two admin and two member slots by default
  (`GROKBOT_ADMIN_WORKERS`, `GROKBOT_MEMBER_JOBS`). Admission is durable, keyed by
  update id, and limited to 1000 pending jobs (each at most 1 MiB). Saturation holds
  the polling offset. Failed jobs retry up to ten times, then move to `jobs/failed/`.
- Member vision is capped at 4 MiB (`GROKBOT_VISION_MAX_BYTES`); larger photos get a
  text-only fallback. History retains ten messages in at most 128 chats with LRU
  eviction (`GROKBOT_MEMBER_HISTORY_CHATS`), and failed empty chats are not retained.
- Media cleanup applies a seven-day TTL and a 512 MiB quota
  (`GROKBOT_MEDIA_MAX_BYTES`), oldest first, once a minute and after worker jobs.
  Active jobs are temporarily exempt. ASR's default response timeout is 90 seconds.
- Pairing replies have a persisted 60-second cooldown per stranger. There are still
  no per-user paid-call budgets or general per-chat rate limits. New stranger ids,
  seen-chat state, logs, and failed queue directories can grow until operator cleanup.
- No inbound per-chat allowlist, no content filtering, no audit log beyond `relay.log`.

## Reporting a vulnerability

Please don't open a public issue for a security problem. Use GitHub's
**"Report a vulnerability"** button on this repository (private vulnerability reporting), or
contact the maintainer listed on the repository profile. Include steps to reproduce and the
version or commit. We'll acknowledge within a week and credit you if you'd like.

Never include real tokens, webhook URLs, or keys in a report. If you think one of yours has
leaked, rotate it first.
