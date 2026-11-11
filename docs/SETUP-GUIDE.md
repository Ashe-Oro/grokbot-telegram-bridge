# Walkthrough setup guide

This is the step-by-step reference for the **new dedicated Grok Bot** that
walks a human through setting up the
[Grok Bot Telegram bridge](https://github.com/Ashe-Oro/grokbot-telegram-bridge).
Your existing bot should have created you and handed you a short brief that
points here. Do not dump this whole file into one session. Work one numbered
step at a time.

**Where it runs.** Do this on **this** always-on Linux computer (the Grok Bot
computer you already run on). Nothing needs to run on the human's laptop or
phone. Do not deploy anything to Vercel, Cloudflare, a VPS, or similar. The
bridge only makes outbound connections, so there are no inbound ports,
tunnels, or Tailscale. No GitHub account or credentials are needed to get the
files.

**Success:** the human can open a Telegram DM with the new Telegram bot and
get a reply, and they can add that bot to a group and get a reply when they
@mention it or reply to it.

The operations write-up (configuration, roles, how the relay runs, and
limitations) is [SETUP.md](SETUP.md). After the repo is on disk, prefer that
file plus `examples/routine-prompt.md` and `examples/keepalive-routine.md`
over memory.

## How to use this guide

1. Read **Rules for secrets** once, before you collect any credential. Read
   **The two kinds of credentials** before Steps 2 and 3. Read
   **Persist secrets across reboots** before you write any credential down
   (Step 5, and again if a key is added or rotated later).
2. For the current checklist item, fetch **only that step's section**. Before
   the repo is on disk, use the public raw file (no GitHub login):
   `https://raw.githubusercontent.com/Ashe-Oro/grokbot-telegram-bridge/main/docs/SETUP-GUIDE.md`
   and take the section under that step's heading. After you download the repo
   in Step 5, read the local copy at `docs/SETUP-GUIDE.md` instead.
3. Explain what you're about to do and why, do the step, then **wait for the
   human to confirm** before moving on.
4. Keep a short progress note in memory (last completed step, anything still
   blocked) so you can resume if the chat is compacted or you start a new
   session.
5. If something fails, use that step's **If this step fails** notes and the
   [Troubleshooting](#troubleshooting) section at the end. Don't rush ahead.

Work as a friendly onboarding guide. Don't install this bridge on a
chief-of-staff bot or any bot that already has email, money, or work access.
You are the dedicated bot with only the access Telegram guests should have.

## Rules for secrets

There are several secrets in this setup. For each one, ask through your
**hidden secret-request field**, never in the chat. Never print, echo, log, or
commit a token, key, `.env` value, or secrets-file value. Don't quote them
back to confirm; a short "got it, it's set" is enough. If a command's output
might contain a secret, summarize the error instead of pasting it. Chat
secret-request fields only set the process environment, which a reboot
clears; persist each secret as described in
[Persist secrets across reboots](#persist-secrets-across-reboots).

## The two kinds of credentials

People often mix these up. They are not the same, and neither one can stand in
for the other:

1. **The Telegram bot token.** This comes from Telegram's
   [@BotFather](https://t.me/BotFather) when the human creates the Telegram
   bot. It looks like a number, a colon, and a long string. It lets the
   bridge talk to Telegram.
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

## Persist secrets across reboots

On this computer, values submitted through a hidden secret-request field live
only in the process environment. A reboot clears that environment, so the
hourly keep-alive cannot restart the bridge unless the same secrets are also
on disk.

Do not rely on a shell startup file alone. `~/.bashrc` is only read by
interactive shells. The keep-alive routine runs non-interactively and does
not load it. `start.sh` sources the secrets file itself, which is what lets
the keep-alive recover after a reboot without asking for the keys again.
Appending a one-line source to `~/.bashrc` is still useful so interactive
sessions have the same variables.

The default path is `/workspace/.secrets/grokbot-telegram.env`. If you use a
custom path, set `GROKBOT_SECRETS_FILE` in a place that survives a reboot: the
repository `.env` (it is not a secret) or the keep-alive routine's start
command — not only in the process environment. After a reboot, `start.sh`
falls back to the default path if that override is gone.

The directory should be mode 0700 and the file mode 0600. `start.sh` warns if
the file is group- or other-readable or writable, or not owned by the current
user; it does not change the mode, and it never prints the values. Already-set,
non-empty environment variables win over the file, so a freshly submitted
secret card is not overwritten by a stale saved copy.

**Threat model.** Every process running as the same Unix user as the relay
can read this file. That is the same same-UID trust already described in
[SECURITY.md](../SECURITY.md). File modes only protect against other
accounts on the machine.

**How to write the file.** After the human submits each secret card — and
again in Step 5 once you have the set — write the values that are already in
the environment. Include `TELEGRAM_BOT_TOKEN`, `GROKBOT_WEBHOOK_URL`,
`GROKBOT_WEBHOOK_KEY`, and `GROKBOT_MEMBER_LLM_API_KEY` if they provided one.

Do **not** source the existing secrets file first. Sourcing it would overwrite
a newly submitted rotation with the stale saved value. To keep keys you are
not changing, copy their existing `export` lines through and drop only the
line for a name you are rewriting from the environment. Write a temporary
file in the same directory (`umask 077`) and `mv` it over the destination so
the replacement is atomic. Never cat, echo, log, or open the file in a way
that would print it.

```bash
umask 077
SECRETS_FILE="${GROKBOT_SECRETS_FILE:-/workspace/.secrets/grokbot-telegram.env}"
mkdir -p "$(dirname "$SECRETS_FILE")"
chmod 700 "$(dirname "$SECRETS_FILE")"
tmp="$SECRETS_FILE.tmp.$$"
# Do not source the existing file. Keep lines for names that are unset in
# the environment; replace any name that is currently set.
{
  if [ -f "$SECRETS_FILE" ]; then
    while IFS= read -r line || [ -n "$line" ]; do
      key="${line#export }"
      key="${key%%=*}"
      case "$key" in
        TELEGRAM_BOT_TOKEN) [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && continue ;;
        GROKBOT_WEBHOOK_URL) [ -n "${GROKBOT_WEBHOOK_URL:-}" ] && continue ;;
        GROKBOT_WEBHOOK_KEY) [ -n "${GROKBOT_WEBHOOK_KEY:-}" ] && continue ;;
        GROKBOT_MEMBER_LLM_API_KEY) [ -n "${GROKBOT_MEMBER_LLM_API_KEY:-}" ] && continue ;;
      esac
      printf '%s\n' "$line"
    done < "$SECRETS_FILE"
  fi
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && printf 'export TELEGRAM_BOT_TOKEN=%q\n' "$TELEGRAM_BOT_TOKEN"
  [ -n "${GROKBOT_WEBHOOK_URL:-}" ] && printf 'export GROKBOT_WEBHOOK_URL=%q\n' "$GROKBOT_WEBHOOK_URL"
  [ -n "${GROKBOT_WEBHOOK_KEY:-}" ] && printf 'export GROKBOT_WEBHOOK_KEY=%q\n' "$GROKBOT_WEBHOOK_KEY"
  [ -n "${GROKBOT_MEMBER_LLM_API_KEY:-}" ] && printf 'export GROKBOT_MEMBER_LLM_API_KEY=%q\n' "$GROKBOT_MEMBER_LLM_API_KEY"
} > "$tmp"
chmod 600 "$tmp"
mv -f "$tmp" "$SECRETS_FILE"
```

Hook interactive shells once. This does not replace the `start.sh` load:

```bash
SECRETS_FILE="${GROKBOT_SECRETS_FILE:-/workspace/.secrets/grokbot-telegram.env}"
# The line added to ~/.bashrc is only a path; it does not print values.
touch "$HOME/.bashrc"
grep -Fqs "$SECRETS_FILE" "$HOME/.bashrc" || \
  printf '\n[ -f %q ] && . %q\n' "$SECRETS_FILE" "$SECRETS_FILE" >> "$HOME/.bashrc"
```

Do not `source ~/.bashrc` in a way that would dump variables into chat.

## Step 1: Confirm this chat and your name

**Goal.** Make sure the human is talking to the new dedicated bot, and that
your name is the one they want.

**Actions.**

1. Greet the human and confirm they are in this new bot's chat, not their
   chief-of-staff or other existing bot.
2. Confirm the name they want for you. If the name should change, change it
   before going further.

**Ask the human.** Confirm that this is the right chat and that they like your
name (or tell you a new one).

**Done when.** They have confirmed this chat and the name is settled.

**If this step fails.** If they are still talking to their existing bot, stop
and ask them to open the new dedicated bot's chat. Do not continue setup in
the wrong bot, and do not install the bridge on the existing bot.

## Step 2: Create the Telegram bot with BotFather

**Goal.** The human has a new Telegram bot, you have its token through a
hidden secret-request field, group privacy is off, and the bot is allowed in
groups.

**Actions.** Walk them through Telegram, in
[@BotFather](https://t.me/BotFather), and wait after each cluster of steps:

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

**Ask the human.** To complete the BotFather steps above, then send the bot
token only through the hidden secret-request field. Confirm that they picked
the new bot in the list, set privacy to Disable, and left `/setjoingroups` on.

**Done when.** You have the Telegram token (stored, never printed), and the
human has confirmed privacy is off and group joins are on for this bot.

**If this step fails.** If they pasted the token into chat, ask them to revoke
it in BotFather (`/revoke`) and send a new token through the hidden field
instead; don't reuse the exposed token. If they aren't sure privacy is off,
have them run `/setprivacy` again and pick this bot from the list. You'll
verify `can_read_all_group_messages` in Step 6.

## Step 3: Create the inbound webhook routine

**Goal.** You have a webhook-triggered routine on yourself, and the human has
sent you that routine's webhook URL and webhook key through hidden
secret-request fields. These are Grok Bot credentials, not Telegram's. See
[The two kinds of credentials](#the-two-kinds-of-credentials) if that isn't
already clear.

**Actions.**

1. On yourself, create a routine:
   - **Name:** Telegram inbound (any name is fine)
   - **Trigger:** webhook, not a schedule
   - **Prompt:** after the repo is on disk, use `examples/routine-prompt.md`
     (fill in the `<...>` placeholders). If you haven't downloaded the repo
     yet, create the routine now with a short placeholder prompt, then put the
     real prompt in as soon as the repo is on disk.
2. Ask the human to copy the routine's **webhook URL** and **webhook key**
   from the desktop app (see [The two kinds of credentials](#the-two-kinds-of-credentials))
   and send each one through a hidden secret-request field.

**Ask the human.** To open the Grok Bot desktop app (the mobile app cannot
show the URL or key), go to this bot → Details → Routines → the inbound
routine → the **Webhook** section, copy the URL ("POST to") and the key, and
send each through the hidden secret-request field. If they can't find that
section, show them where it is rather than guessing a different click path.

**Done when.** The routine exists with a webhook trigger, and you have both
the webhook URL and the webhook key stored, never printed.

**If this step fails.** If they looked in BotFather or Telegram for the
webhook URL or key, stop and explain again: those values come only from the
Grok Bot routine in the desktop app. If the mobile app doesn't show a Webhook
section, that's expected; they need a computer. If they pasted a credential
into chat, have them rotate the routine's key in the app and send the new
value through the hidden field.

## Step 4: Optional member-chat key

**Goal.** Decide whether members (everyone who isn't an admin) can chat now.
This step is optional.

**Actions.**

1. Explain that members get a chat-only reply from a plain no-tools model
   call. That needs an API key, by default an xAI key from
   https://console.x.ai. Any OpenAI-compatible endpoint works; the repo
   default is xAI.
2. Without a key, members are told the bot is only set up to chat with
   admins. Admins still work. The human can add a key later.
3. If they want member chat now, have them create a key and send it through a
   hidden secret-request field.

**Ask the human.** Whether they want member chat now. If yes, to create a key
and send it only through the hidden secret-request field.

**Done when.** They have either sent a member-chat key through the hidden
field, or clearly chosen to skip this and add it later.

**If this step fails.** If they don't have an xAI (or other) key yet, skip
this step and continue. Member chat can be enabled later by having them
send the key through a hidden secret-request field, adding
`GROKBOT_MEMBER_LLM_API_KEY` to the secrets file as in
[Persist secrets across reboots](#persist-secrets-across-reboots), and
restarting. Never paste the key into chat.

## Step 5: Install the bridge on this computer

**Goal.** The repo is on **this** computer (the Grok Bot computer), not on the
human's laptop, and the secrets they already gave you are written to the
0600 secrets file so they survive a reboot. No GitHub account or credentials
are needed.

**Actions.**

Download the public repo, then persist the secrets. Prefer the public zip
(no git, no login):

```bash
curl -fsSL -o /tmp/grokbot-telegram-bridge.zip \
  https://github.com/Ashe-Oro/grokbot-telegram-bridge/archive/refs/heads/main.zip
unzip -q /tmp/grokbot-telegram-bridge.zip
mv grokbot-telegram-bridge-main grokbot-telegram-bridge
cd grokbot-telegram-bridge
```

An anonymous `git clone` of the public HTTPS URL is equally fine and also
needs no GitHub account:

```bash
git clone https://github.com/Ashe-Oro/grokbot-telegram-bridge.git
cd grokbot-telegram-bridge
```

Do not use SSH (`git@github.com:...`) and do not pass a GitHub token. If a
clone asks for credentials, stop and use the zip instead.

Then write the secrets file and hook `~/.bashrc` exactly as in
[Persist secrets across reboots](#persist-secrets-across-reboots), using the
values already in the environment. Never cat or otherwise print the secrets
file.

You can still copy `.env.example` to `.env` (`chmod 600 .env`) for
non-secret settings such as `GROKBOT_ADMINS`. Tokens and keys belong in the
secrets file on this computer; a chat secret card alone will not survive a
reboot. `.env` remains supported (`start.sh` still loads it, and existing
environment variables win over `.env`), but after a reboot that has cleared
the process environment the keep-alive depends on `start.sh` finding the
secrets file (or a `.env` you already wrote).

Voice notes can wait until after a text DM works; they're optional and need
`ffmpeg` plus the `.venv-asr` steps in [SETUP.md](SETUP.md).

From this point on, read the rest of this guide from the local file
`docs/SETUP-GUIDE.md` instead of fetching it over the network.

**Ask the human.** Nothing, unless the download fails or you need them to
approve a command. You already have the secrets.

**Done when.** The project directory is on this computer, the secrets file
exists with mode 600 in a 0700 directory, `~/.bashrc` sources it, the known
secrets are written into the file, and you did not print the file.

**If this step fails.** If `git clone` asks for a GitHub login or fails with
an auth error, use the public zip via `curl` and `unzip` instead. If the zip
URL fails, retry; it is public and does not need an account. Don't put the
repo on the human's laptop. If you almost printed the secrets file or
`.env`, stop and confirm it was not pasted into chat.

## Step 6: Start the relay

**Goal.** The relay is running on this computer and a health check shows the
Telegram bot identity plus group-privacy status.

**Actions.** From the repo directory:

```bash
python3 relay.py --check
./start.sh
```

`--check` should print the Telegram bot's id, username, and
`can_read_all_group_messages`. If privacy was turned off correctly, that flag
should be true. `./start.sh` runs the relay in the background on this
computer. `./stop.sh` stops it. Logs go to `relay.log` and never include
tokens, keys, or message text.

**Ask the human.** Nothing unless `--check` fails or `can_read_all_group_messages`
is false, in which case go back to Step 2 and fix privacy on the correct bot.

**Done when.** `--check` succeeded, `can_read_all_group_messages` is true, and
`./start.sh` has started the relay.

**If this step fails.** If `--check` can't reach Telegram, the token may be
wrong; have them send a fresh token through the hidden field, update the
secrets file without printing it (see
[Persist secrets across reboots](#persist-secrets-across-reboots)), and
rerun `--check`. If
`can_read_all_group_messages` is false, disable privacy on the bot whose
token the relay is using, then continue; a group already joined will also need
the remove-and-re-add in Step 9. If `start.sh` fails, read `relay.log`
(statuses only) and fix the reported error before moving on.

## Step 7: Create the hourly keep-alive routine

**Goal.** A scheduled routine on you will bring the bridge back after a
reboot. This computer's PID 1 is often not systemd, and it may have no cron.

**Actions.** Create a scheduled routine on yourself:

- **Name:** Telegram bridge keep-alive
- **Trigger:** every hour
- **Prompt:** the text in `examples/keepalive-routine.md`, with the absolute
  path to this repo's `ensure.sh` filled in.

If a confirm card appears the first time the routine runs a shell command,
ask the human to approve it. This is how the bridge comes back after a
reboot: `ensure.sh` calls `start.sh`, which loads the secrets file even
though the routine's non-interactive environment does not. That only works
if you wrote the file in Step 5.

**Ask the human.** To approve the confirm card if one appears the first time
the routine runs a shell command.

**Done when.** The hourly keep-alive routine exists, points at this repo's
`ensure.sh`, and any first-run shell confirmation has been approved (or you
have noted that it will be asked on the first hourly run).

**If this step fails.** Double-check the absolute path to `ensure.sh`. Don't
fall back to systemd or cron on this computer unless you already know they
exist here; the keep-alive routine is the intended path. Setup can continue if
the routine is created and only the first-run confirmation is still pending,
but remind the human they'll need to approve it.

## Step 8: Approve the first admin from the host

**Goal.** The human is approved as the first admin from this computer, and a
test DM gets a reply. The first person who messages the Telegram bot is
**not** made an admin automatically. The first admin is set by you, the host.

**Actions.**

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
5. If they also send `/whoami` to the Telegram bot, it should show
   `role=admin`.

**Ask the human.** To DM the Telegram bot, send you the pairing code, then
send a real test question (and optionally `/whoami`) and tell you whether they
got a reply.

**Done when.** You have approved them with `approve.py --admin`, a test DM
has received a reply, and `/whoami` shows `role=admin` if they ran it.

**If this step fails.** See [Troubleshooting](#troubleshooting) for "No reply
in a DM after pairing", `webhook HTTP 401`, and "The first person can't
`/approve` in Telegram yet". Until you approve them from this computer with
`approve.py --admin`, there is no admin, and `/approve` in Telegram is
admin-only. Don't try to fix that by approving from Telegram.

## Step 9: Add the bot to a group

**Goal.** The Telegram bot is in a group, answers when the human @mentions it
or replies to it, and they know the group command syntax.

**Actions.**

1. Ask them to add the Telegram bot to a group and @mention it or reply to
   it. They should get a reply in the group.
2. Remind them of the command syntax:
   - In a DM with the Telegram bot: `/approve CODE`
   - In a group: `/approve@BotName CODE`, or reply to one of the bot's
     messages with `/approve CODE`. A plain `/approve CODE` in a group (not
     addressed to the bot) is ignored.
   - The same addressing rules apply to `/promote`, `/demote`, and
     `/whoami`.
   - `/approve` always adds the person as a **member**. An admin can later
     `/promote` someone if they should have full agent access.

When a second person can get a reply in the group, and the human can get a
reply in a DM, setup is complete. Congratulate them and point at
[SETUP.md](SETUP.md) and [SECURITY.md](../SECURITY.md) for roles, optional
voice notes, and hardening.

**Ask the human.** To add the bot to a group, @mention it or reply to it, and
tell you whether they got a reply. If someone else is available, have that
person get a pairing code and have the human approve them as a member.

**Done when.** The human gets a reply in a DM and in a group when they
@mention the bot or reply to it. A second person in the group is a bonus, not
required to finish.

**If this step fails.** See [Troubleshooting](#troubleshooting) for "The
Telegram bot ignores group messages". Privacy may still be on, or it may have
been turned off on the wrong bot. After fixing privacy, **remove the bot from
the group and add it again** — Telegram applies the privacy setting at join
time.

## Troubleshooting

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
a common cause. Restart with `./stop.sh && ./start.sh` after updating the
secrets file (or `.env`).

**`webhook HTTP 401` in the log.** The webhook URL may be right but the key is
wrong or out of date. Have the human copy the current key from the routine's
Webhook section in the desktop app, send it again through a hidden
secret-request field, update the secrets file without printing it (see
[Persist secrets across reboots](#persist-secrets-across-reboots)), and
restart the relay. A 401 is what we hit the first time the key didn't match.

**The first person can't `/approve` in Telegram yet.** That's expected. Until
you approve them from this computer with `approve.py --admin`, there is no
admin, and `/approve` in Telegram is admin-only. Do the host-side approval in
[Step 8](#step-8-approve-the-first-admin-from-the-host).

**Never paste tokens, webhook keys, secrets-file contents, or `.env`
contents into chat** while debugging. Summarize errors instead.
