# Front Desk

An AI receptionist for your personal website. Visitors chat; they screen them,
take notes, and save transcripts. You stay in control. You pick their name.

- **One Python file** — stdlib only, no dependencies
- **Your rules** — customize the prompt, they follow it
- **Your name** — call them Alex, Casey, whatever you want
- **Rate limited** — 20 req/min per IP
- **Sandbox-ready** — macOS sandbox profile included
- **Auto-saves** — every conversation written to disk

## Quick Start

```bash
# 1. Get a DeepSeek API key (https://platform.deepseek.com)

# 2. Set your key
export CLAIRE_API_KEY=*** 3. Copy and customize your prompt
cp SOUL.example.md SOUL.md
# Edit SOUL.md — replace [PRINCIPAL NAME] and [AGENT NAME] with your info

# 4. Run (pick any name)
python3 frontdesk.py --name Alexis

# 5. Expose to the internet
cloudflared tunnel --url http://localhost:8765
```

Visit `http://localhost:8765/front-desk` to see your front desk.

## Customizing

**SOUL.md** is your agent's personality. Fill in who you are, what you're open to,
and your boundaries. Replace `[PRINCIPAL NAME]` with your name and
`[AGENT NAME]` with whatever you want to call her.

**Agent name:** Pass `--name` to change it from the default (Alex):

```bash
python3 frontdesk.py --name Alexis
python3 frontdesk.py --name Taylor
```

The name appears in the page title, header, greeting, and chat UI.

## Configuration

```bash
python3 frontdesk.py --port 8080              # Custom port (default: 8765)
python3 frontdesk.py --name Alexis            # Custom agent name (default: Alex)
python3 frontdesk.py --key sk-...             # API key on command line
python3 frontdesk.py --soul my-prompt.md      # Custom prompt file
```

Or use environment variables / `.env`:

```
# ~/.claire/.env
CLAIRE_API_KEY=*** How It Works

```
Visitor → yoursite.com/front-desk
           │
           ▼
         frontdesk.py
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

On macOS, use launchd to keep the server running:

```bash
# 1. Edit com.example.frontdesk.plist — fix the paths and name
# 2. Install
cp com.example.frontdesk.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.example.frontdesk.plist

# 3. For a custom domain, create a Cloudflare Tunnel
cloudflared tunnel create my-front-desk
# Then configure DNS and install as launchd service
```

## Sandboxing (macOS)

`frontdesk.sb` is a macOS sandbox profile that restricts the process to ONLY:
- Read files in its own directory
- Read your API key from `.env`
- Make HTTPS requests to api.deepseek.com

Everything else in your home directory is blocked at the OS level.

```bash
sandbox-exec -f frontdesk.sb python3 frontdesk.py
```

## Model & Cost

Default: **DeepSeek V3** (`deepseek-chat`) at $0.27/M input tokens.
A full conversation of 10 messages costs roughly $0.001. You can swap to
any OpenAI-compatible API by changing the endpoint in `frontdesk.py`.

## License

MIT
