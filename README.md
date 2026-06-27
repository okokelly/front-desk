# Claire

An AI front desk for your personal website. Visitors chat with Claire; she
screens them, takes notes, and saves transcripts. You stay in control.

- **One Python file** — stdlib only, no dependencies
- **Your rules** — customize the prompt, she follows it
- **Rate limited** — 20 req/min per IP
- **Sandbox-ready** — macOS sandbox profile included
- **Auto-saves** — every conversation written to disk

## Quick Start

```bash
# 1. Get a DeepSeek API key (https://platform.deepseek.com)

# 2. Set your key
export CLAIRE_API_KEY=sk-...

# 3. Copy and customize your prompt
cp SOUL.example.md SOUL.md
# Edit SOUL.md — add who you are, what you're open to, your boundaries

# 4. Run
python3 claire.py

# 5. Expose to the internet
cloudflared tunnel --url http://localhost:8765
```

Visit `http://localhost:8765/front-desk` to see Claire.

## Customizing

The only thing you need to change is **SOUL.md** — that's Claire's personality.
Fill in who you are, what kinds of conversations you're open to, and your
boundaries. The example template has placeholders marked `[PRINCIPAL NAME]`.

Restart the server after editing SOUL.md — it loads at startup.

## Configuration

```bash
python3 claire.py --port 8080           # Custom port (default: 8765)
python3 claire.py --key sk-...          # API key on command line
python3 claire.py --soul my-prompt.md   # Custom prompt file
```

Or use environment variables / `.env`:

```
# ~/.claire/.env
CLAIRE_API_KEY=***
````

## How It Works

```
Visitor → yoursite.com/front-desk
           │
           ▼
         claire.py
           │
           ├─ Reads SOUL.md (your rules)
           ├─ Calls DeepSeek API (deepseek-chat, temp=0.5)
           ├─ Detects goodbye language → auto-closes
           ├─ Saves every conversation → sessions/*.json
           └─ Rate limits: 20 req/min per IP
```

## Session Files

Every conversation is saved to `sessions/YYYYMMDD_HHMMSS.json`:

```json
{
  "timestamp": "2026-06-28 09:15:00",
  "user_messages": 4,
  "first_message": "Hi, I'm a startup founder...",
  "conversation": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ]
}
```

Sessions start saving after the visitor's second message — even if they
abandon the conversation.

## Making It Permanent

On macOS, use launchd to keep Claire running:

```bash
# 1. Edit com.example.claire.plist — fix the paths
# 2. Install
cp com.example.claire.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.example.claire.plist

# 3. For a custom domain, create a Cloudflare Tunnel
cloudflared tunnel create claire
# Then configure DNS and install as launchd service
```

## Sandboxing (macOS)

`claire.sb` is a macOS sandbox profile that restricts Claire to ONLY:
- Read files in her own directory
- Read your API key from `.env`
- Make HTTPS requests to api.deepseek.com

Everything else in your home directory is blocked at the OS level.

```bash
sandbox-exec -f claire.sb python3 claire.py
```

## Advanced: Daily Review Automation

Claire's strength is saving conversations. The natural next step is an
automated daily review. Here's a sketch:

```bash
# Cron job runs every morning
# → Scans sessions/ for new conversations
# → Summarizes: who, what they want, your assessment
# → Sends a briefing to your messaging app
```

If you use [Hermes Agent](https://github.com/NousResearch/hermes-agent),
you can set this up as a cron job with the `file` toolset — it reads
sessions and writes briefings. See the Hermes docs for details.

## Model & Cost

Default: **DeepSeek V3** (`deepseek-chat`) at $0.27/M input tokens.
Front-desk traffic is extremely low-token — a full conversation of 10
messages costs roughly $0.001. You can swap to any OpenAI-compatible API
by changing the endpoint in `claire.py`.

## License

MIT
