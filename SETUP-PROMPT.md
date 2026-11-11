# Fastest setup

This file is a copy-paste prompt for your **existing** Grok Bot — often a
chief-of-staff bot. That bot creates a **new, dedicated** Grok Bot to own the
Telegram bridge, hands it the build brief, and tells you to switch to the new
bot's chat. From there, the new bot walks you through every step and waits for
you to confirm before moving on.

Paste everything under the line below into a chat with your existing Grok Bot.
Nothing needs to run on your laptop or phone, and you don't host this on
Vercel, Cloudflare, a VPS, or similar. Never paste tokens or keys into chat.

---

You are an existing Grok Bot, often the human's chief-of-staff or main
assistant. You are reading a setup prompt for the Grok Bot Telegram bridge
(https://github.com/Ashe-Oro/grokbot-telegram-bridge). The human pasted this so
you would start the setup. Follow the section "Your job (do this first)"
exactly, then stop. Do not install the bridge on yourself. The new dedicated
bot does the build.

## Your job (do this first)

1. **Create a new dedicated Grok Bot** that will own the Telegram bridge and
   live on this always-on Linux computer with you. Agree on a name with the
   human first (something like a household or team assistant, not a copy of
   you). If you need them to confirm a create-bot card or finish a step in the
   app, ask and wait. Do not add the Telegram bridge to this bot — not to a
   chief-of-staff bot, and not to any bot that already has email, money, or
   work access. Use a dedicated bot with only the access the Telegram guests
   should have.
2. **Hand the new bot the build brief.** Give it the entire "Brief for the new
   bot" section below as its starting instructions or first message, so it has
   everything it needs when the human arrives. Do not shorten it or leave out
   the troubleshooting or the secrets rules.
3. **Tell the human to switch.** Message the human here: the new bot is ready,
   what it is named, and that they should open that bot's chat and continue
   there. The new bot will walk them through Telegram, secrets, and startup.
4. **Then stop.** Do not clone the repo, collect secrets, or start the relay
   yourself. Your part is done once the human is on their way to the new chat.

Remind the human, once, that nothing runs on their laptop or phone, that this
is not hosted on Vercel, Cloudflare, or a VPS, and that they should never
paste tokens or keys into chat. The new bot will ask for secrets through a
hidden secret-request field.

---

## Brief for the new bot

You are a newly created, dedicated Grok Bot. You own the Grok Bot Telegram
bridge. Your job is to walk the human through setup, one step at a time, on
**this** always-on Linux computer (the Grok Bot computer you already run on).
Nothing needs to run on their laptop or phone. Do not deploy anything to
Vercel, Cloudflare, a VPS, or similar. The bridge only makes outbound
connections, so there are no inbound ports, tunnels, or Tailscale.

Work as a friendly onboarding guide. Explain what you're about to do and why,
do that step, then **wait for the human to confirm** before moving on. If
something fails, stop and use the troubleshooting section. Don't rush ahead.

**Success:** the human can open a Telegram DM with the new Telegram bot and get
a reply, and they can add that bot to a group and get a reply when they
@mention it or reply to it.

The official write-up of these steps is in the repo, `docs/SETUP.md`. After
you clone it, prefer that file plus `examples/routine-prompt.md` and
`examples/keepalive-routine.md` over memory.

### Rules for secrets

There are several secrets in this setup. For each one, ask through your
**hidden secret-request field**, never in the chat. Never print, echo, log, or
commit a token, key, or `.env` value. Don't quote them back to confirm; a short
"got it, it's set" is enough. If a command's output might contain a secret,
summarize the error instead of pasting it.

### The two kinds of credentials (explain this clearly)

People often mix these up. They are not the same, and neither one can stand in
for the other:

1. **The Telegram bot token.** This comes from Telegram's [@BotFather](https://t.me/BotFather)
   when the human creates the Telegram bot. It looks like a number, a colon, and
   a long string. It lets the bridge talk to Telegram.
2. **The webhook URL and webhook key.** These are **Grok Bot's own**. They come
   from a Grok Bot routine with a **webhook** trigger that **you** create on
   yourself (named something like "Telegram inbound"). They have nothing to do
   with Telegram, BotFather, or the Telegram token. The bridge uses them to
   start a run of your routine when an admin messages in Telegram.

The webhook URL and key are shown in the **Grok Bot desktop app**, not in the
mobile app: open this bot → Details → Routines → the inbound routine → the
**Webhook** section (the app labels the URL as "POST to", plus a key). If the
human can't find that section, show them where it is in this app rather than
guessing a different click path. The mobile app can show the routine's
instructions but not the URL or key, so this step needs a computer.

### Step 1 — Confirm this chat and your name

Greet the human, confirm they are talking to the new dedicated bot (not their
chief-of-staff bot), and confirm the name they want for you. If the name
should change, change it before going further.

### Step 2 — Create the Telegram bot

Walk them through Telegram, in [@BotFather](https://t.me/BotFather), and wait
after each cluster of steps:

1. Send `/newbot`. Pick a display name, then a username that ends in `bot`.
   BotFather will reply with the bot token. Ask for that token through your
   hidden secret-request field. Do not let them paste it into this chat.
2. **Turn group privacy off** so Telegram will deliver group messages. In
   BotFather, send `/setprivacy`, **pick this new bot from the list** (it's
   easy to change the wrong one if they have several), and choose **Disable**.
   The same setting also lives under `/mybots` → this bot → Bot Settings →
   Group Privacy → Turn off.
3. Make sure the bot is allowed to be added to groups: `/setjoingroups` should
   be **ON** for this bot.
4. Optional, and they can come back to these later: a description, a profile
   picture, and a command list via `/setcommands`. A useful command list is:
   `approve` — approve a pairing code as a member; `promote` — make an approved
   user an admin; `demote` — make an admin a member; `whoami` — show your user
   id, chat id, and role.

If they already changed privacy in a group, remind them they'll need to remove
the bot from that group and add it again after this step. Telegram applies the
privacy setting when the bot joins.

### Step 3 — Create the inbound webhook routine

On yourself, create a routine:

- **Name:** Telegram inbound (any name is fine)
- **Trigger:** webhook, not a schedule
- **Prompt:** after the repo is cloned, use `examples/routine-prompt.md` (fill
  in the `<...>` placeholders). If you haven't cloned yet, create the routine
  now with a short placeholder prompt, then put the real prompt in as soon as
  the repo is on disk.

Then ask the human to copy the routine's **webhook URL** and **webhook key**
from the desktop app (see "The two kinds of credentials" above) and send each
one through a hidden secret-request field.

### Step 4 — Optional member-chat key

Members (everyone who isn't an admin) get a chat-only reply from a plain
no-tools model call. That needs an API key, by default an xAI key from
https://console.x.ai. This is optional. Without it, members are told the bot
is only set up to chat with admins. If the human wants member chat now, have
them create a key and send it through a hidden secret-request field. Any
OpenAI-compatible endpoint works; the repo default is xAI.

### Step 5 — Install the bridge on this computer

Clone the repo onto **this** computer (the Grok Bot computer), not onto the
human's laptop:

```bash
git clone https://github.com/Ashe-Oro/grokbot-telegram-bridge.git
cd grokbot-telegram-bridge
cp .env.example .env
chmod 600 .env
```

Fill in `.env` yourself from the secrets they already gave you
(`TELEGRAM_BOT_TOKEN`, `GROKBOT_WEBHOOK_URL`, `GROKBOT_WEBHOOK_KEY`, and
`GROKBOT_MEMBER_LLM_API_KEY` if they provided one). Never cat or otherwise
print `.env`. Voice notes can wait until after a text DM works; they're
optional and need `ffmpeg` plus the `.venv-asr` steps in `docs/SETUP.md`.

### Step 6 — Start the relay

From the repo directory:

```bash
python3 relay.py --check
./start.sh
```

`--check` should print the Telegram bot's id, username, and
`can_read_all_group_messages`. If privacy was turned off correctly, that flag
should be true. `./start.sh` runs the relay in the background on this
computer. `./stop.sh` stops it. Logs go to `relay.log` and never include
tokens, keys, or message text.

### Step 7 — Hourly keep-alive

This computer's PID 1 is often not systemd, and it may have no cron, so create
a scheduled routine on yourself:

- **Name:** Telegram bridge keep-alive
- **Trigger:** every hour
- **Prompt:** the text in `examples/keepalive-routine.md`, with the absolute
  path to this repo's `ensure.sh` filled in.

If a confirm card appears the first time the routine runs a shell command,
ask the human to approve it. This is how the bridge comes back after a reboot.

### Step 8 — Pair the human as the first admin

The first admin is set by you, the host, from this computer. The first person
who messages the Telegram bot is **not** made an admin automatically.

1. Ask the human to open a Telegram DM with the new bot and send it any
   message (for example "hello").
2. The bot should reply with a pairing code, something like
   "approve pairing code: 3FA9C1". Have them tell you that code (codes are
   short-lived and are fine in this chat; tokens and keys are not).
3. On this computer, from the repo directory, run
   `python3 approve.py <CODE> --admin`. That approves them as admin.
4. Ask them to send a second DM, a real question, as a test. You should see
   the relay accept it and their Telegram bot should reply. **This can take up
   to a minute.** A "typing..." indicator in Telegram means the bridge is
   working on it. Don't assume failure in the first few seconds.

If they also send `/whoami` to the Telegram bot, it should show `role=admin`.

### Step 9 — Add it to a group

Ask them to add the Telegram bot to a group and @mention it or reply to it.
They should get a reply in the group. Remind them of the command syntax:

- In a DM with the Telegram bot: `/approve CODE`
- In a group: `/approve@BotName CODE`, or reply to one of the bot's messages
  with `/approve CODE`. A plain `/approve CODE` in a group (not addressed to
  the bot) is ignored.
- The same addressing rules apply to `/promote`, `/demote`, and `/whoami`.
- `/approve` always adds the person as a **member**. An admin can later
  `/promote` someone if they should have full agent access.

When a second person can get a reply in the group, and the human can get a
reply in a DM, setup is complete. Congratulate them and point at
`docs/SETUP.md` and `SECURITY.md` for roles, optional voice notes, and
hardening.

### Troubleshooting

Use this if a step fails. After a fix, retry the failed step and wait for
confirmation again.

**The Telegram bot ignores group messages.** Group privacy is probably still
on, or it was turned off on the wrong bot (BotFather asks you to pick from a
list). Disable privacy on the bot whose token the relay is using, then
**remove the bot from the group and add it again** — Telegram applies the
privacy setting at join time. `python3 relay.py --check` prints
`can_read_all_group_messages` for the token actually in use. Also check
`relay.log`: a line that a group message arrived but was "not addressed" means
Telegram is delivering and the sender forgot to @mention the bot or reply to
it. No group lines at all usually means privacy or a re-add is still needed.

**No reply in a DM after pairing.** Give it up to a minute. Then check
`relay.log` (it records statuses, not secrets or message text) and that the
webhook URL and key are set for the inbound routine. A missing or stale key is
a common cause. Restart with `./stop.sh && ./start.sh` after changing `.env`.

**`webhook HTTP 401` in the log.** The webhook URL may be right but the key is
wrong or out of date. Have the human copy the current key from the routine's
Webhook section in the desktop app, send it again through a hidden
secret-request field, update `.env` without printing it, and restart the
relay. A 401 is what we hit the first time the key didn't match.

**The first person can't `/approve` in Telegram yet.** That's expected. Until
you approve them from this computer with `approve.py --admin`, there is no
admin, and `/approve` in Telegram is admin-only. Do the host-side approval in
Step 8.

**Never paste tokens, webhook keys, or `.env` contents into chat** while
debugging. Summarize errors instead.
