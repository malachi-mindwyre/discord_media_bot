# Discord Media Bot

> A Python `discord.py` bot that watches configured Discord channels and reposts media
> (images, videos, GIFs, link embeds) into one designated channel, building a gallery/highlights feed.
> Last updated: 2026-09-12

---

## What It Is

A single-file Discord bot (`discord-media-bot.py`, 535 lines) plus a JSON config file. For each guild it
watches either a specific list of channels or every channel, and whenever a human posts a message whose
attachments or embeds contain media, it re-uploads that media into the guild's configured "media channel"
with a small info embed (author, source channel, jump link).

There is no database and no daemon unit: state is one JSON file on disk, and the process is kept alive by a
`screen` session on a DigitalOcean droplet.

## How It Works

```
Human posts in monitored channel
  → on_message (ignores bots)
  → should_copy_message: guild configured? media channel set? not the media channel itself?
                         monitor_all OR channel in monitored_channels list?
  → has_media_content: attachment extension allowlist, or embed with image/video/thumbnail
  → asyncio.sleep(0.5)
  → download each attachment ≤ 8 MB and re-upload as discord.File
  → send info embed + up to 9 copied source embeds (10 embeds max per message)
```

Media detection rules, exactly as implemented:

- **Attachments**: filename must end in `.png .jpg .jpeg .gif .webp .mp4 .mov .avi .webm .bmp .tiff`.
- **Embeds**: copied if `embed.type` is `image`, `video`, or `gifv`, or if it is `article`/`link` **and** carries
  an image or thumbnail. Plain text links are not copied.
- **Info embed** always contains `Source` (`#channel-name`) and `Jump to Original` (`message.jump_url`),
  description is `message.content` truncated to 1024 chars, timestamp is the original `created_at`.
- **Author attribution** (`embed.set_author` with display name + avatar) is a per-guild toggle, default on.

## Repository Layout

| Path | Purpose |
|---|---|
| `discord-media-bot.py` | The entire bot: `MediaCopyBot`, event handlers, all commands, error handler. |
| `bot_config.json` | Runtime state — guild → channels. **Tracked in git** despite being listed in `.gitignore` (force-added). |
| `.env` | Holds `DISCORD_TOKEN` only. Gitignored, not tracked. Never commit it. |
| `requirements.txt` | Pinned dependencies. |
| `README.md` | User-facing docs — **stale in several places, see Gotchas**. |
| `DEPLOYMENT_DIGITALOCEAN.md` | Droplet setup guide (automated + manual paths, management commands). |
| `deploy_to_digitalocean.sh` | One-shot droplet bootstrap: apt packages, `botuser`, clone, venv, `manage_bots.sh`, ufw. |
| `venv/` | Local virtualenv (Python 3.9.6 on this Mac). Gitignored, untracked. |

`CONFIG_FILE` is the **relative** string `"bot_config.json"`, resolved against the process working
directory — the bot must be started from the project directory or it silently creates a fresh empty config.

## Bot Commands

All commands are `@bot.hybrid_command`/`hybrid_group`, so they work as both slash commands and `!`-prefixed
text commands (`command_prefix="!"`). Every command requires the **Manage Channels** permission, enforced via
`@commands.has_permissions(manage_channels=True)`; failures are answered with an error embed.

| Command | Effect |
|---|---|
| `/setup <#channel>` | Sets the guild's media destination channel. |
| `/monitor add <#channel>` | Appends a channel to `monitored_channels[guild]`. |
| `/monitor remove <#channel>` | Removes a channel from that list. |
| `/monitor all [true/false]` | Sets `monitor_all`; with no argument it toggles. Turning it **on clears the monitored list**. |
| `/monitor list` | Status embed: media channel, mode, monitored channels, author attribution. |
| `/toggle_author` | Flips `include_author` for the guild. |
| `/help` | Static help embed (`help_command=None`, so this is a real command). |

`/monitor exclude` and `/monitor include` are documented in `README.md` but **do not exist in the code**.

## Configuration

`bot_config.json` is keyed by guild ID (string) and written on every change via `save_config()`
(`json.dump(..., indent=4)`). The live file at time of writing configures two guilds.

| Key | Shape | Meaning |
|---|---|---|
| `monitored_channels` | `{guild_id: [channel_id, ...]}` | Source channels, used only when `monitor_all` is false. |
| `media_channels` | `{guild_id: channel_id}` | Destination. No copy happens until this is set. |
| `include_author` | `{guild_id: bool}` | Defaults to `true` on first `on_ready`. |
| `monitor_all` | `{guild_id: bool}` | `true` = every channel except the destination is a source. |
| `excluded_channels` | `{guild_id: [channel_id, ...]}` | **Dead key** — present in the file, no longer read by the code. |

On startup `on_ready` backfills any missing guild keys for every guild the bot is in, then saves. If the JSON
is corrupt, the bot logs `Invalid JSON in config file, creating new config` and overwrites it with defaults —
**the previous configuration is lost**.

## Running Locally

```bash
cd /Users/malachi/Developer/personal/discord_media_bot
source venv/bin/activate
python discord-media-bot.py            # foreground, Ctrl-C to stop

# background instead
nohup python3 discord-media-bot.py > bot.log 2>&1 &
tail -f bot.log
pkill -f "discord-media-bot.py"
```

Logging is `logging.basicConfig(level=logging.INFO)` to stdout; useful lines are
`<user> has connected to Discord!`, `Bot is in N guilds`, and `Copied media from #a to #b`.
If `DISCORD_TOKEN` is missing the process prints `❌ Please set DISCORD_TOKEN environment variable` and exits 1.

Required Discord setup: bot scopes `bot` + `applications.commands`; permissions Read Messages, Send Messages,
Embed Links, Attach Files (permission integer `2147485696`). The code enables the **privileged
Message Content intent** (`intents.message_content = True`) — it must also be switched on in the Discord
Developer Portal or login fails.

## Deployment (DigitalOcean)

Documented target: Ubuntu 22.04 LTS, Basic $6/month 1 GB droplet; `README.md` states the live host is
**`144.126.215.207`** (not verifiable from this repo — confirm before relying on it).

| Item | Value |
|---|---|
| Bot OS user | `botuser` |
| Code directory | `/home/botuser/discord-media-bot` |
| Management script | `/home/botuser/manage_bots.sh` (`start` \| `stop` \| `status`) |
| Supervisor | GNU `screen`, session name `media_bot` (+ `ffmpeg` installed, unused by current code) |
| Firewall | `ufw`, SSH only |
| Token file | `/home/botuser/discord-media-bot/.env`, mode `600`, owned by `botuser` |

```bash
# Bootstrap a fresh droplet (as root)
wget https://raw.githubusercontent.com/MalachiMindwyre/discord-media-bot/main/deploy_to_digitalocean.sh
chmod +x deploy_to_digitalocean.sh && ./deploy_to_digitalocean.sh
```

> That `wget` URL is the old repo name and now **404s** — see Gotchas for the working URL.

```bash
# Token, then start
echo 'DISCORD_TOKEN=YOUR_TOKEN_HERE' > /home/botuser/discord-media-bot/.env
chmod 600 /home/botuser/discord-media-bot/.env
chown botuser:botuser /home/botuser/discord-media-bot/.env
/home/botuser/manage_bots.sh start
/home/botuser/manage_bots.sh status

# Logs: attach to the session, Ctrl+A then D to detach
screen -r media_bot

# Deploy / update
ssh root@YOUR_DROPLET_IP
su - botuser && cd discord-media-bot && git pull && source venv/bin/activate && pip install -r requirements.txt
exit
/home/botuser/manage_bots.sh stop && /home/botuser/manage_bots.sh start

# Preserve local settings onto the droplet
scp bot_config.json root@YOUR_DROPLET_IP:/home/botuser/discord-media-bot/
ssh root@YOUR_DROPLET_IP "chown botuser:botuser /home/botuser/discord-media-bot/bot_config.json && /home/botuser/manage_bots.sh stop && /home/botuser/manage_bots.sh start"
```

## Gotchas & Known Issues

- **Two bot instances = duplicate posts.** There is only one `screen` session named `media_bot`; a second
  process started by hand (e.g. leaving the local `nohup` run alive) will double-post everything.
- **No duplicate prevention in the current code.** The 2026-09-12 commit `3c4c7d2` deleted the
  `recently_processed` / batch-queue tracking (298 lines) along with Twitter link handling. `README.md` still
  advertises "Duplicate Prevention" and the 8s Twitter/X embed wait; neither exists. The only pacing left is
  `asyncio.sleep(0.5)` before each copy.
- **Ahead of origin.** Local `master` is **1 commit ahead** of `origin/master` at time of writing; the
  Twitter/tracking removal is unpushed, so a droplet `git pull` will not pick it up.
- **The old clone URL is dead.** `deploy_to_digitalocean.sh` (line 49) and `README.md` point at
  `github.com/MalachiMindwyre/discord-media-bot`, which returns 404. The live remote is
  `git@github.com:malachi-mindwyre/discord_media_bot.git` / `https://github.com/malachi-mindwyre/discord_media_bot`
  (verified 200, public). Fix both references when re-running the bootstrap script.
- **`bot_config.json` is committed despite being gitignored.** `.gitignore` lists it under "Configuration",
  but it is tracked, so real guild and channel IDs live in git history. Editing it locally makes the tree dirty.
- **8 MB attachment ceiling.** Bot uploads skip any file over `8 * 1024 * 1024` bytes; the message is still
  posted, but only the info embed and the original embeds appear — the media itself is missing. This is a
  silent drop, logged nowhere.
- **`excluded_channels` is stale config.** The exclusion feature was removed with the rest of the tracking
  code; with `monitor_all: true` there is no way to exempt a noisy channel short of flipping to explicit
  `/monitor add` mode.
- **README sections that no longer match the code**: duplicate prevention, Twitter/X embed delay, the
  `/monitor exclude` and `/monitor include` commands, and the "MIT License — see LICENSE file" claim
  (no `LICENSE` file exists in the repo).
- **Config-migration hazards.** Because `CONFIG_FILE` is relative, starting the bot outside the project
  directory creates an empty `bot_config.json` there and the bot appears unconfigured. Corrupt JSON is
  overwritten with defaults rather than repaired.
- **Turning `/monitor all true` wipes the monitored channel list** (`monitored_channels[guild] = []`), so
  switching back to `false` leaves nothing configured.
- **`requirements.txt` over-declares.** `pillow`, `yt-dlp`, and `pydub` are installed but never imported by
  `discord-media-bot.py`; only `discord.py`, `python-dotenv`, and `aiohttp` are used.

## History / Lessons

| Date | Commit | Change |
|---|---|---|
| 2025-07-13 | `52e8611` | Initial commit. |
| 2025-07-29 | `a9f5cda`–`0eae1be` | Cleanup, dependency updates, DigitalOcean guide added, `bot_config.json` committed. |
| 2025-07-30 | `44a77c2` | Channel exclusion system for `monitor_all` mode (since removed). |
| 2025-07-31 | `d210977` | Switched supervision from systemd to `screen` + `manage_bots.sh` specifically to prevent double posting. |
| 2026-09-12 | `3c4c7d2` | Dropped Twitter link handling and the message-tracking/batch queue; `discord-media-bot.py` shrank by 298 lines. Unpushed. |

Lessons carried forward: run exactly one instance (systemd→screen was the fix for double posting); the
destination channel is never a source; bot messages are ignored, so reposts cannot loop.

## Files To Read First

| Question | File |
|---|---|
| How does copying decide? | `discord-media-bot.py` → `should_copy_message`, `has_media_content`, `copy_media_message` |
| What is this guild configured to do? | `bot_config.json` |
| How do I deploy or restart it? | `DEPLOYMENT_DIGITALOCEAN.md`, `deploy_to_digitalocean.sh` |
