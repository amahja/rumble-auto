# GitHub Actions Rumble Auto Downloader

This GitHub Actions setup checks daily for the newest America First episode on Rumble, downloads the working `240p` HLS stream, creates a GitHub Release, uploads the MP4 as a release asset, and sends you a Telegram notification with the link.

Default schedule:

- **11:05 AM Asia/Riyadh**
- GitHub cron uses UTC, so this is `08:05 UTC`.

## Why GitHub Actions

- No VPS account.
- No always-on machine.
- Works well for a daily 240p episode.
- Stores files as GitHub Release assets instead of Actions artifacts.

Important:

- Use a **public repository** if you want the best free experience.
- GitHub scheduled workflows can sometimes be delayed.
- Do not store huge daily files forever. This workflow keeps the last 10 releases by default.

## Setup

1. Create a new GitHub repository.
   - Recommended: public repo.
   - Example name: `rumble-auto`.

2. Upload this folder's contents into the repository.
   Your repo should contain:

```text
.github/workflows/rumble.yml
scripts/rumble_discover.py
```

3. In GitHub, go to:

```text
Repository -> Settings -> Secrets and variables -> Actions -> New repository secret
```

Add these secrets:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Optional repository variables:

```text
QUALITY = 240
KEEP_RELEASES = 10
RUMBLE_CHANNEL_URL = https://rumble.com/c/nickjfuentes
OPENRSS_FALLBACK = 1
```

4. Enable GitHub Actions if GitHub asks.

5. Test manually:

```text
Actions -> Rumble Auto Downloader -> Run workflow
```

## Telegram Bot Setup

1. Open Telegram and message `@BotFather`.
2. Run `/newbot`.
3. Copy the bot token to the GitHub secret `TELEGRAM_BOT_TOKEN`.
4. Send any message to your bot.
5. Get your chat ID:

```text
https://api.telegram.org/botYOUR_TOKEN/getUpdates
```

Look for:

```json
"chat":{"id":123456789}
```

Put that number in the GitHub secret `TELEGRAM_CHAT_ID`.

## Manual Quality Choices

The workflow default is:

```text
240p
```

Known rough sizes for episode 1700:

- 240p: about 418 MB
- 360p: about 1.3 GB
- 480p: about 2 GB

I recommend staying with `240` for GitHub Actions.

## If Rumble Blocks Discovery

The script first tries the Rumble channel page directly. If that fails, it falls back to Open RSS:

```text
https://openrss.org/rumble.com/c/nickjfuentes
```

Set `OPENRSS_FALLBACK=0` only if you want to disable that fallback.
