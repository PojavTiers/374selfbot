# Multi-Token Discord Selfbot

Runs multiple Discord user accounts (tokens) simultaneously with a command prefix, rich presence, autoreacts, and mock commands.

## Requirements

- Python 3.11+
- `discord.py>=2.3.0`
- `aiohttp`

## Setup (local)

```bash
pip install -r requirements.txt
export DISCORD_TOKEN="token1,token2,token3"
python main.py
```

## Setup (Railway)

1. Push this folder to a GitHub repo.
2. Create a new Railway project → **Deploy from GitHub repo**.
3. Railway auto-detects the `Dockerfile`.
4. Go to **Variables** → add:
   - `DISCORD_TOKEN` = `token1,token2,token3`
5. Deploy. Check logs for `[Client N] Selfbot ready.`

## Commands

Default prefix `-`. Run `-help` in Discord.

## Notes

- Selfbots violate Discord ToS. Use at your own risk.
- `config.json` is ephemeral on Railway unless you attach a volume.
