# Keep-alive routine

The intended setup runs the bridge on your Grok Bot's own always-on Linux
computer. That machine's PID 1 is not systemd and often has no cron, so run
`ensure.sh` from a scheduled Grok Bot routine. An hourly schedule is usually
enough: after a reboot the bridge may be down for up to an hour.

You don't need this routine if you optionally self-host the relay elsewhere
with the example systemd unit.

## Setup

1. Install the bridge and fill in `.env` as described in
   [docs/SETUP.md](../docs/SETUP.md).
2. On the Grok Bot that shares the machine with the bridge, create a scheduled
   routine:
   - **Name:** Telegram bridge keep-alive
   - **Trigger:** every hour (or more often if you want a shorter gap after a
     reboot)
   - **Prompt:** the text below. Replace the `<...>` parts.
3. The routine should be allowed to run a shell command on that machine (the
   bot's computer). If a confirm card appears the first time, approve it.

## Prompt

```text
You are checking whether the Telegram bridge on this computer is running.

Run this command and read only its stdout/stderr:

  <absolute path to the bridge>/ensure.sh

Interpret the result:

- If the output starts with "ok: running", the bridge is healthy. Do not
  message anyone. End the run quietly.
- If the output includes "relay not running; starting" and then "started pid",
  the bridge was down and you restarted it. Send me a short message here (in
  this Grok Bot chat, not Telegram) that the Telegram bridge was down and you
  started it again. Include the pid from the output. Do not paste any other
  output.
- If the command failed, or start.sh printed an error (for example a missing
  token or a failed --check), tell me the bridge is down and quote the error
  text. Never include tokens, webhook keys, URLs with secrets, or the contents
  of .env in that message. If an error looks like it contains a secret,
  summarize it instead of quoting it.
- "warn: ffmpeg missing" or "warn: ASR venv missing" is not a failure on its
  own. If the bridge is running, stay silent. If you also had to restart it or
  it failed, mention the warning in your message to me.

Never print, log, or send secrets, the webhook URL, the webhook key, or the
Telegram bot token. Never write to the Telegram outbox during this check.
```
