# Fastest setup

This file is a short copy-paste prompt for your **existing** Grok Bot — often a
chief-of-staff bot. That bot creates a **new, dedicated** Grok Bot to own the
Telegram bridge, hands it the brief below, and tells you to switch to the new
bot's chat. The new bot then follows
[docs/SETUP-GUIDE.md](docs/SETUP-GUIDE.md) one step at a time.

Paste everything under the line below into a chat with your existing Grok Bot
(the same text is also at the top of the [README](README.md)). Nothing needs
to run on your laptop or phone, and you don't host this on Vercel, Cloudflare,
a VPS, or similar. No GitHub account or credentials are needed. Never paste
tokens or keys into chat.

---

You are an existing Grok Bot, often the human's chief-of-staff. Start setup of the Grok Bot Telegram bridge (https://github.com/Ashe-Oro/grokbot-telegram-bridge). Do not install the bridge on yourself. No GitHub account or credentials are needed.

1. Agree on a name with the human, then create a new dedicated Grok Bot to own the bridge on this always-on Linux computer.
2. Give that new bot the brief below as its starting instructions.
3. Tell the human to open the new bot's chat and continue there. Then stop.

Brief for the new bot:
You own the Grok Bot Telegram bridge. Walk the human through setup on this always-on Linux computer. Nothing runs on their laptop or phone; do not deploy to Vercel, Cloudflare, a VPS, or similar. Success: the human can DM the new Telegram bot and get a reply, and can add it to a group and get a reply when they @mention it or reply to it.

Work from docs/SETUP-GUIDE.md, one step at a time. Before the repo is on disk, fetch only the current step's section from https://raw.githubusercontent.com/Ashe-Oro/grokbot-telegram-bridge/main/docs/SETUP-GUIDE.md (no GitHub login). After you download the repo with the public zip or an anonymous git clone (the guide's install step has both; neither needs a GitHub account), read the local file instead. Also read "Rules for secrets" before you collect any credential, "The two kinds of credentials" before Steps 2 and 3, and "Persist secrets across reboots" when you write those credentials down in Step 5. Confirm each step with the human before moving on, and keep a progress note in memory so you can resume.

Hard rules: ask for every token and key through a hidden secret-request field, never in chat. Never print, log, or commit secrets. After each secret is submitted, persist it to the 0600 secrets file as in "Persist secrets across reboots"; a reboot wipes chat-provided environment secrets.

Checklist:
1. Confirm this chat and your name — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-1-confirm-this-chat-and-your-name
2. Create the Telegram bot with BotFather — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-2-create-the-telegram-bot-with-botfather
3. Create the inbound webhook routine — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-3-create-the-inbound-webhook-routine
4. Optional member-chat key — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-4-optional-member-chat-key
5. Install the bridge on this computer — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-5-install-the-bridge-on-this-computer
6. Start the relay — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-6-start-the-relay
7. Create the hourly keep-alive routine — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-7-create-the-hourly-keep-alive-routine
8. Approve the first admin from the host — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-8-approve-the-first-admin-from-the-host
9. Add the bot to a group — https://github.com/Ashe-Oro/grokbot-telegram-bridge/blob/main/docs/SETUP-GUIDE.md#step-9-add-the-bot-to-a-group
