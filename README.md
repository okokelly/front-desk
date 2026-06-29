# Front Desk

Always someone at the desk.

Front Desk is a small AI receptionist for your personal website. Most personal
sites give visitors a wall and maybe an email address they're nervous to use.
This puts a friendly face at the door instead — it says hello, listens, answers
what it can, and makes you feel reachable, while quietly noting which
conversations are worth your time.

One Python file. No dependencies. You write the rules; it sets the tone.

```
Visitor → yoursite.com/front-desk → Pikachu → you (for the conversations that matter)
```

The default receptionist is named **Pikachu**. Rename it in one flag — see below.

## Why

A contact form is a closed door with a mail slot. It asks a stranger to write a
cold email to someone they've never met and hope for a reply — so most people
don't bother, and you never hear from them at all.

Front Desk lowers that barrier. Anyone can walk up and have a real conversation:
ask a question, introduce themselves, get a warm and useful answer on the spot.
You become more approachable to everyone — and, at the same time, more selective,
because you read the transcripts later and choose which conversations to pick up.
No one is turned away at the door; you simply decide what's worth your time.

## Quick Start

You need a DeepSeek API key — grab one at https://platform.deepseek.com.

```bash
# 1. Hand it your key
export FRONTDESK_API_KEY=sk-your-key-here

# 2. Give it something to say
cp SOUL.example.md SOUL.md          # then edit SOUL.md (see "The Soul" below)

# 3. Open the desk
python3 frontdesk.py

# 4. Let the world in
cloudflared tunnel --url http://localhost:8765
```

Now visit **http://localhost:8765/front-desk** and say hello to your receptionist.

## The Soul

`SOUL.md` is the agent's brief — who it works for, what you're open to, and where
the line is. It's just a prompt, so write it like you'd brief a real person on
their first day.

```bash
cp SOUL.example.md SOUL.md
```

Open `SOUL.md` and fill in the blanks: replace `[PRINCIPAL NAME]` with your name
and `[AGENT NAME]` with whatever you call your receptionist. Be specific about
what you're always glad to hear about and what's better pointed elsewhere — that
warmth and that judgment are the whole job.

The more of yourself you pour into it, the more it sounds like you. Don't stop at
a job title — give it your story, your voice, the things you care about. A
receptionist who actually knows you makes everyone feel like they've reached the
right place.

Edits take effect on restart.

## Naming It

The receptionist answers to **Pikachu** out of the box. Call it anything:

```bash
python3 frontdesk.py --name Iris
```

The name shows up in the page title, the header, the greeting, and the footer.

## Configuration

```bash
python3 frontdesk.py --port 8080          # port (default: 8765)
python3 frontdesk.py --name Iris          # agent name (default: Pikachu)
python3 frontdesk.py --key sk-...         # API key on the command line
python3 frontdesk.py --soul desk.md       # a different soul file
```

Prefer a file over an environment variable? Drop your key here:

```bash
# ~/.frontdesk/.env
FRONTDESK_API_KEY=sk-your-key-here
```

## How It Works

```
Visitor opens /front-desk
        │
        ▼
   frontdesk.py
        ├─ loads SOUL.md ............. your rules
        ├─ calls DeepSeek ............ deepseek-chat, temp 0.5
        ├─ trusts nothing ............ sanitizes every message from the browser
        ├─ rate limits ............... 20 requests / minute / visitor IP
        ├─ hears a goodbye ........... wraps up and closes the chat
        ├─ caps the visit ............ auto-closes after 10 messages
        └─ writes it down ............ sessions/<id>.json
```

## Reading the Mail

Every conversation lands in `sessions/` as JSON, from the visitor's second
message onward — so even the ones who wander off leave a note behind.

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

Session files are written owner-only (`0600`). The folder is git-ignored — your
visitors' words never leave your machine.

## Keeping It Open (macOS)

To run the desk around the clock, hand it to `launchd`:

```bash
# 1. Edit com.example.frontdesk.plist — fix the paths and the name
# 2. Install it
cp com.example.frontdesk.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.example.frontdesk.plist
```

For a real domain, point a Cloudflare Tunnel at it:

```bash
cloudflared tunnel create my-front-desk
# then configure DNS and run it as a service
```

## Sandboxing (macOS)

`frontdesk.sb` walls the process off from your home directory — it can read its
own folder and your `.env`, write to `sessions/`, and nothing else.

```bash
sandbox-exec -f frontdesk.sb python3 frontdesk.py
```

One honest caveat: this is **filesystem** isolation, not network isolation. The
profile uses `(allow default)`, so the process can still reach any host — macOS
sandboxes can't filter outbound traffic by domain. Treat it as a lock on the
filing cabinet, not on the phone line.

## Model & Cost

Runs on **DeepSeek V3** (`deepseek-chat`) — about $0.27 per million input
tokens, so a full ten-message visit costs roughly a tenth of a cent. The API is
OpenAI-compatible; point the endpoint in `frontdesk.py` at any provider you like.

## License

MIT — take it, rename it, make it yours.
