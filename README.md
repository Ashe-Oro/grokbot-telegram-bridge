# Grok Bot Telegram bridge

This bridge turns your [Grok Bot](https://cursor.com/help/grok-bot) into a
**multiplayer agent**. Add it to a Telegram DM or a group chat and it talks with
other people — family, teammates, whoever you invite — in the place you already
chat. Access is gated by pairing codes: only people you approve can reach the
bot. **Admins** drive the full agent; **members** can chat but can never touch
the agent's tools or the machine it runs on.

It is a small, self-hosted relay: one Python file using only the standard
library, plus an optional local speech-to-text helper for voice notes. It needs
no inbound ports, no public server, and no database.

> **Status:** early and small. It works well for one household, but it has not
> been hardened for public bots. Read [SECURITY.md](SECURITY.md) before you
> connect it to a bot that has access to your email, money, or work.

## How it works

```mermaid
sequenceDiagram
    participant U as Telegram users
    participant R as relay.py (your Linux box)
    participant G as Grok Bot webhook routine
    participant L as Chat model (no tools)
    U->>R: DM, @mention, photo, or voice note
    Note over R: pairing and roles, transcribe voice
    alt sender is an admin
        R->>G: POST event JSON (role: admin)
        G-->>R: write reply to outbox/
    else sender is a member
        R->>L: plain chat completion (text and photo only)
        L-->>R: reply text
    end
    R->>U: sendMessage (and keep "typing..." until then)
```

## Features

- **Multiplayer DMs and groups.** One Grok Bot, many people. Anyone you approve
  can talk to it in a private chat or in a shared group.
- **Mention or reply in groups.** The bridge forwards a group message only when
  someone @mentions the bot or replies to it, and only if that person is
  approved.
- **Allowlist and pairing codes.** Strangers get a short code, not access. You
  approve them on the machine or with `/approve` in Telegram.
- **Admin and member roles, with a hard boundary.** Only admins' messages reach
  the Grok Bot webhook. Members are chat-only: the relay answers them itself
  with a plain chat-completion call that has no tools, no function calling, and
  no file or shell access, so they can't touch the host, the bot's connectors,
  routines, or settings. New people are approved as members. Only admins can
  `/approve`, `/promote <user_id>`, or `/demote <user_id>`.
- **Photos.** Downloaded to disk so the bot can look at the image.
- **Voice notes.** Transcribed locally with faster-whisper; the bot sees the
  transcript.
- **Persistent typing indicator.** Telegram's "typing..." refreshes until the
  reply is sent, or until a configurable cap (default 180s).
- **Auto-restart.** A watchdog restarts the relay if it crashes. `ensure.sh`
  brings it back after a reboot (cron, a systemd timer, or a scheduled Grok Bot
  routine).
- **Proactive messages.** Any routine on the same bot can post to a chat by
  writing a file to `outbox/`.

## Quick start

You need a persistent Linux machine the Grok Bot can also read and write files
on, Python 3.10+, and `ffmpeg` if you want voice notes. Full detail is in
[docs/SETUP.md](docs/SETUP.md).

1. **Create a Telegram bot** with [@BotFather](https://t.me/BotFather). Copy the
   token. For groups, send `/setprivacy`, pick this bot, choose **Disable**, then
   remove the bot from the group and add it again.
2. **Create a webhook routine** on the Grok Bot that should answer. Start from
   [examples/routine-prompt.md](examples/routine-prompt.md). Copy the webhook URL
   and key from the **Grok Bot desktop app**: bot → Details → Routines → your
   routine → Webhook. The mobile app does not show them.
3. **Configure.** `git clone` this repo, `cp .env.example .env`, `chmod 600 .env`,
   and fill in `TELEGRAM_BOT_TOKEN`, `GROKBOT_WEBHOOK_URL`, and
   `GROKBOT_WEBHOOK_KEY`. Put your own Telegram user id in `GROKBOT_ADMINS`.
   For member chat, set `GROKBOT_MEMBER_LLM_API_KEY` (an xAI API key by
   default; any OpenAI-compatible endpoint works). See
   [.env.example](.env.example) for the rest. For
   voice notes: `sudo apt install ffmpeg`, then
   `python3 -m venv .venv-asr && .venv-asr/bin/pip install -r requirements-asr.txt`.
4. **Start.** `python3 relay.py --check` then `./start.sh`. Logs go to
   `relay.log`. `./stop.sh` stops it. On systemd, use
   [examples/grokbot-telegram-bridge.service](examples/grokbot-telegram-bridge.service)
   instead. On a host without systemd, run
   [examples/keepalive-routine.md](examples/keepalive-routine.md) so the bridge
   comes back after a reboot.
5. **Pair people.** Message the bot; if you are not approved yet it replies
   with a pairing code. Approve with `python3 approve.py <CODE>` (member) or
   `python3 approve.py <CODE> --admin`. `/whoami` prints your user id, the chat
   id, and your role.

## Security

This is a private bridge, not a public bot. Admins can start runs of your Grok
Bot, with that bot's connectors and tools, so make only people you fully trust
admins. Members never reach the bot: their messages go only to a no-tools chat
model (and so leave the machine for that model's API). Use a dedicated bot with
only the access it needs, keep the admin list short, and treat the Telegram
token, webhook key, and member LLM key like passwords. Details, including how to report
a vulnerability, are in [SECURITY.md](SECURITY.md).

## Docs

- [docs/SETUP.md](docs/SETUP.md): full setup, configuration, how it runs, and limitations
- [SECURITY.md](SECURITY.md): threat model and vulnerability reporting
- [docs/HOW-WE-BUILT-IT.md](docs/HOW-WE-BUILT-IT.md): the build story and the bugs we hit
- [examples/](examples/): routine prompt, systemd unit, and a keep-alive routine

## License

MIT. See [LICENSE](LICENSE).

This is a community project, not an official Grok Bot or Telegram product.
