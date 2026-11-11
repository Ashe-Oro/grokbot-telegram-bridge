# Security

This bridge lets people in Telegram start runs of your Grok Bot. That is powerful, and it is
the main risk. This page is a candid look at what the bridge protects, what it doesn't, and
what you should do about it.

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
  `GROKBOT_ADMINS` ids are always admin; `GROKBOT_ALLOWLIST` ids are added as members
  only if they don't already have a role (existing admins are never demoted).
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
  only from the environment (or a local `.env` file you create). The relay never writes
  them to disk.
- Log lines are scrubbed: the token, the keys, and any `/bot<id>:<token>` URL pattern are
  replaced with `***`. Telegram file-download URLs contain the token, so they are never
  logged or stored. Download errors log only the error type or HTTP status.
- Log lines carry no message text, captions, transcripts, or model replies. They record the
  role and path (`webhook` or `member-llm`) and the member call's status.
- The tests check that a fake token and keys never appear in logs or in any file written.
- If you use `.env`, `chmod 600 .env`, keep it out of git (it is in `.gitignore`), and
  prefer your bot's secrets store if it has one.

### If the webhook key leaks

Anyone with the URL and key can start runs of your routine with any JSON they like, without
going through Telegram or the allowlist. That costs you usage and lets them feed the bot
arbitrary "messages." Rotate the key (or delete and recreate the webhook routine) in the
Grok Bot desktop app, then update the relay's environment and restart it.

### If the Telegram token leaks

Anyone with it can read your bot's updates and send as your bot. Revoke it in BotFather
(`/revoke`), put the new token in the environment, and restart.

## Transport and storage

- **Telegram bot chats are not end-to-end encrypted.** Telegram's servers can read them.
  Don't use this for anything you wouldn't put in a normal Telegram cloud chat.
- The relay only makes outbound connections (Telegram, the webhook, and the member chat
  API). There are no inbound ports, tunnels, or Tailscale.
- Webhook POSTs go over HTTPS to the Grok Bot service.
- **Media is stored on disk** under `media/<update_id>/` and deleted after 7 days. Anyone
  with access to that machine can read photos and voice notes until then. Transcripts are
  not stored by the relay, but they are part of the webhook body and become part of the
  bot's run history.
- `state.json` holds Telegram user ids, usernames, first names, and pending codes. No
  secrets, but it is personal data.

## The outbox is trusted input

The relay sends every valid `.json` file in `outbox/` to whatever `chat_id` it names. It
doesn't check that the chat is one the bot was talking to. So **anyone who can write to the
outbox folder can make your bot send any text to any chat it can reach.** Keep the data
directory owned by the user that runs the relay and the bot, and don't share it with other
users or services.

## Not built yet

- **No rate limiting.** An approved person (or a stranger, for pairing replies) can send
  as many messages as they like. Each admin message starts a run and each member message is
  one paid chat-model call. Watch usage, and remove people who abuse it.
- No per-chat allowlist, no content filtering, no audit log beyond `relay.log`.

## Reporting a vulnerability

Please don't open a public issue for a security problem. Use GitHub's
**"Report a vulnerability"** button on this repository (private vulnerability reporting), or
contact the maintainer listed on the repository profile. Include steps to reproduce and the
version or commit. We'll acknowledge within a week and credit you if you'd like.

Never include real tokens, webhook URLs, or keys in a report. If you think one of yours has
leaked, rotate it first.
