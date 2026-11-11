# Security

This bridge lets people in Telegram start runs of your Grok Bot. That is powerful, and it is
the main risk. This page is a candid look at what the bridge protects, what it doesn't, and
what you should do about it.

## The big one: Telegram users drive your agent

A webhook routine runs as your Grok Bot, **with that bot's connectors and tools**. If the bot
can read your email, see your calendar, browse signed in as you, run shell commands, or
move money, then anyone on the allowlist can ask it to do those things from Telegram. The
routine prompt can tell the bot to be careful, but a prompt is not a permission system.

What to do:

- **Use a dedicated bot** for Telegram, not your main one. Give it only the connectors it
  needs (for a household: maybe a shared calendar, nothing financial).
- Keep the routine prompt's rule that the Telegram event is untrusted data, and its rule not
  to pull in private matters from your other bots or accounts.
- Allowlist only people you'd trust with that bot directly.

## Prompt injection

Anything that reaches the bot can try to steer it:

- **Group members.** Any allowlisted person can address the bot. Their messages can contain
  instructions aimed at the bot.
- **Forwarded messages.** A forwarded message from a stranger arrives as text from an
  allowlisted person.
- **Photos.** Text inside an image ("ignore your instructions and ...") is read by the bot
  when it looks at the photo.
- **Voice notes.** Transcripts are just text and can carry the same instructions.

The bridge doesn't filter content. Your defenses are the routine prompt, a bot with few
tools, and a short allowlist.

## Who can get in: allowlist and pairing codes

- Only Telegram user ids on the allowlist are forwarded. Strangers who DM the bot, or mention
  it in a group, get a random 6-hex-character pairing code, not access. Nothing they send is
  forwarded, and their photos and voice notes are never downloaded.
- Codes are single-use and expire after 24 hours. One pending code per user.
- Approval happens on the machine (`approve.py`) or by an allowlisted user sending
  `/approve <code>`. **Any allowlisted user can approve anyone.** If that is too loose for
  you, only approve from the machine and keep the allowlist small.
- The allowlist is per person, not per chat. An allowlisted person can add the bot to any
  group and use it there; the bot will answer them in that group.
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

- `TELEGRAM_BOT_TOKEN` and `GROKBOT_WEBHOOK_KEY` are read only from the environment (or a
  local `.env` file you create). The relay never writes them to disk.
- Log lines are scrubbed: the token, the key, and any `/bot<id>:<token>` URL pattern are
  replaced with `***`. Telegram file-download URLs contain the token, so they are never
  logged or stored. Download errors log only the error type or HTTP status.
- Log lines carry no message text, captions, or transcripts.
- The tests check that a fake token and key never appear in logs or in any file written.
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

- **No rate limiting.** An allowlisted person (or a stranger, for pairing replies) can send
  as many messages as they like, and each forwarded message starts a run. Watch usage, and
  remove people who abuse it.
- No per-chat allowlist, no admin-only approvals, no content filtering, no audit log beyond
  `relay.log`.

## Reporting a vulnerability

Please don't open a public issue for a security problem. Use GitHub's
**"Report a vulnerability"** button on this repository (private vulnerability reporting), or
contact the maintainer listed on the repository profile. Include steps to reproduce and the
version or commit. We'll acknowledge within a week and credit you if you'd like.

Never include real tokens, webhook URLs, or keys in a report. If you think one of yours has
leaked, rotate it first.
