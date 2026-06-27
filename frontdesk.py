#!/usr/bin/env python3
"""
AI front desk for your personal website.

A single-file web server that puts a friendly AI receptionist between
you and the internet. Visitors chat; they screen them and saves
conversation transcripts. You review later.

Zero dependencies beyond Python stdlib. Sandbox-ready.

Usage:
  python3 frontdesk.py                              # http://localhost:8765
  python3 frontdesk.py --port 8080                  # custom port
  python3 frontdesk.py --name Alexis                 # custom agent name
  python3 frontdesk.py --key sk-...                 # API key (or set CLAIRE_API_KEY)
  python3 frontdesk.py --soul my-prompt.md          # custom prompt

For public access:
  cloudflared tunnel --url http://localhost:8765
"""

import http.server
import json
import os
import random
import socketserver
import sys
import time
import urllib.request
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────
PORT = 8765
MAX_USER_MSGS = 10
SESSIONS_DIR = Path(__file__).resolve().parent / "sessions"
SOUL_PATH = Path(__file__).resolve().parent / "SOUL.md"
AGENT_NAME = "Alex"  # override with --name

# Rate limiting: 20 requests per 60s per IP
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 20
_rate_limit_store = {}

API_KEY = ""
SYSTEM_PROMPT = ""

# ── API Key ────────────────────────────────────────────────────
def load_api_key():
    """Read CLAIRE_API_KEY from environment or ~/.claire/.env"""
    env_paths = [
        Path.home() / ".claire" / ".env",
        Path.home() / ".hermes" / ".env",
    ]
    for p in env_paths:
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("CLAIRE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("CLAIRE_API_KEY", "")

# ── Prompt ─────────────────────────────────────────────────────
def load_soul():
    """Load system prompt from SOUL.md. Edit and restart to update."""
    if SOUL_PATH.exists():
        return SOUL_PATH.read_text().strip()
    print(f"Warning: SOUL.md not found at {SOUL_PATH}")
    return "You are a front-desk assistant. Greet visitors and screen them politely."

# ── Rate Limiting ──────────────────────────────────────────────
def check_rate_limit(client_ip):
    """Return True if rate limit exceeded."""
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    timestamps = _rate_limit_store.get(client_ip, [])
    timestamps = [t for t in timestamps if t > cutoff]
    _rate_limit_store[client_ip] = timestamps
    if len(timestamps) >= RATE_LIMIT_MAX:
        return True
    timestamps.append(now)
    if len(_rate_limit_store) > 1000:
        dead = [ip for ip, ts in _rate_limit_store.items() if not ts]
        for ip in dead:
            del _rate_limit_store[ip]
    return False

# ── Session Saving ─────────────────────────────────────────────
def save_session(msgs, user_count, session_id=None):
    """Save full conversation to sessions/{session_id}.json"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    if session_id:
        path = SESSIONS_DIR / f"{session_id}.json"
    else:
        path = SESSIONS_DIR / f"{time.strftime('%Y-%m-%d_%H%M%S')}.json"

    first_user = next(
        (m["content"][:80] for m in msgs if m.get("role") == "user"), "unknown"
    )
    record = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "user_messages": user_count,
        "first_message": first_user,
        "conversation": [
            {"role": m["role"], "content": m["content"]} for m in msgs
        ],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2))
    print(f"  Session saved: {path.name}", flush=True)


# ── Closure Detection ──────────────────────────────────────────
CLOSING_PROMPT = (
    "\n\nThis is the final message of this conversation. "
    "Wrap up naturally: thank them, summarize, and say goodbye. "
    "Keep it short. Do not invite further replies."
)

CLOSURE_PHRASES = [
    "best of luck", "take care", "goodbye", "good bye", "all the best",
    "have a great", "have a good", "have a lovely", "wish you",
    "feel free to come back", "talk soon", "speak soon",
    "not the right time", "come back when you're ready",
]

# ── HTML ───────────────────────────────────────────────────────
BLANK_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>—</title>
<style>
  body { display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 100vh; margin: 0; background: #fff; color: #999; font-family: Georgia, serif; font-style: italic; gap: 24px; }
  a { font-style: normal; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 0.85rem; color: #888; text-decoration: none; border: 1px solid #ddd; padding: 8px 20px; border-radius: 6px; transition: all 0.2s; }
  a:hover { color: #333; border-color: #bbb; }
</style>
</head>
<body>This page intentionally left blank.<a href="/front-desk">Visit front desk →</a></body>
</html>"""

def build_html(name):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{name}</title>
<style>
  :root {{ --bg: #f5f3f0; --card: #fff; --text: #1a1a1a; --muted: #999; --accent: #2d2d2d; --bubble-me: #e8e6e3; --bubble-them: #fff; --border: #e0ddd8; --danger: #c44; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; justify-content: center; padding: 20px; }}
  .app {{ width: 100%; max-width: 540px; display: flex; flex-direction: column; min-height: 90vh; }}
  header {{ text-align: center; padding: 32px 0 12px; }}
  header h1 {{ font-size: 1.6rem; font-weight: 500; letter-spacing: 0.06em; }}
  header p {{ color: var(--muted); font-size: 0.82rem; margin-top: 4px; }}
  .chat {{ flex: 1; display: flex; flex-direction: column; gap: 8px; overflow-y: auto; padding: 12px 0; }}
  .msg {{ max-width: 88%; padding: 10px 14px; border-radius: 14px; font-size: 0.88rem; line-height: 1.55; word-break: break-word; }}
  .msg.user {{ align-self: flex-end; background: var(--bubble-me); border-bottom-right-radius: 6px; }}
  .msg.bot {{ align-self: flex-start; background: var(--bubble-them); border: 1px solid var(--border); border-bottom-left-radius: 6px; }}
  .msg.closed {{ align-self: center; color: var(--muted); font-size: 0.78rem; padding: 8px 0; font-style: italic; }}
  .msg.error {{ align-self: center; background: #fff0f0; border: 1px solid #fcc; color: var(--danger); font-size: 0.8rem; max-width: 95%; }}
  .input-area {{ display: flex; gap: 8px; padding: 12px 0 20px; border-top: 1px solid var(--border); margin-top: auto; }}
  .input-area input {{ flex: 1; padding: 12px 16px; border: 1px solid var(--border); border-radius: 20px; font-size: 0.88rem; background: #fff; }}
  .input-area input:disabled {{ opacity: 0.4; }}
  .input-area button {{ background: var(--accent); color: #fff; border: none; width: 40px; height: 40px; border-radius: 50%; font-size: 1rem; cursor: pointer; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }}
  .input-area button:disabled {{ opacity: 0.3; cursor: not-allowed; }}
  .typing {{ color: var(--muted); font-size: 0.8rem; padding: 4px 14px; align-self: flex-start; font-style: italic; display: none; }}
  footer {{ text-align: center; padding: 4px 0 12px; font-size: 0.7rem; color: var(--muted); }}
</style>
</head>
<body>
<div class="app">
  <header><h1>{name}</h1><p>Front desk</p></header>
  <div class="chat" id="chat"></div>
  <div class="typing" id="typing">{name} is thinking…</div>
  <div class="input-area" id="input-area">
    <input type="text" id="input" placeholder="Introduce yourself…" onkeydown="if(event.key==='Enter')send()" autofocus>
    <button id="sendBtn" onclick="send()">→</button>
  </div>
  <footer>You're talking to {name}, an AI assistant. They'll figure out how best to help.</footer>
</div>
<script>
const $chat = document.getElementById('chat');
const $input = document.getElementById('input');
const $sendBtn = document.getElementById('sendBtn');
const $typing = document.getElementById('typing');
let messages = [{{role:'system',content:''}}];
let waiting = false;
let closed = false;
let sessionId = null;

function addMsg(text, role) {{
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = renderMD(text);
  $chat.appendChild(div);
  $chat.scrollTop = $chat.scrollHeight;
}}

function renderMD(text) {{
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
    .replace(/\\*(.+?)\\*/g, '<em>$1</em>')
    .replace(/\\n\\n/g, '<br><br>')
    .replace(/\\n/g, '<br>');
  return html;
}}

function closeChat() {{
  closed = true;
  document.getElementById('input-area').style.display = 'none';
  document.querySelector('footer').textContent = 'Conversation ended.';
  addMsg('— end of conversation —', 'closed');
}}

async function send() {{
  const text = $input.value.trim();
  if (!text || waiting || closed) return;
  $input.value = '';
  waiting = true;
  $input.disabled = true;
  $sendBtn.disabled = true;
  addMsg(text, 'user');
  messages.push({{role:'user',content:text}});
  $typing.style.display = 'block';
  $chat.scrollTop = $chat.scrollHeight;

  try {{
    const resp = await fetch('/api/chat', {{
      method: 'POST',
      headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{messages, session_id: sessionId}})
    }});
    if (!resp.ok) {{
      const err = await resp.json().catch(()=>({{}}));
      throw new Error(err.error || 'Something went wrong');
    }}
    const data = await resp.json();
    sessionId = data.session_id;
    messages.push({{role:'assistant',content:data.reply}});
    addMsg(data.reply, 'bot');
    if (data.closed) closeChat();
  }} catch(e) {{
    addMsg('Sorry, something went wrong. Try again in a moment.', 'error');
  }} finally {{
    $typing.style.display = 'none';
    if (!closed) {{
      waiting = false;
      $input.disabled = false;
      $sendBtn.disabled = false;
    }}
    $input.focus();
    $chat.scrollTop = $chat.scrollHeight;
  }}
}}

addMsg("Hi! I'm {name}. Who are you, and what brings you here?", 'bot');
</script>
</body>
</html>"""

# ── Server ─────────────────────────────────────────────────────
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  {args[0]}", flush=True)

    def do_GET(self):
        from urllib.parse import urlparse
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path in ("/front-desk",):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(build_html(AGENT_NAME).encode())
        elif path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(BLANK_HTML.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path != "/api/chat":
            self.send_response(404)
            self.end_headers()
            return

        # Rate limit
        client_ip = self.client_address[0]
        if check_rate_limit(client_ip):
            self.send_json(429, {"error": "Too many requests. Please wait.", "closed": False})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
            msgs = data.get("messages", [])
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON", "closed": False})
            return

        web_sid = data.get("session_id", "")
        if not web_sid:
            web_sid = f"{time.strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"

        user_count = sum(1 for m in msgs if m.get("role") == "user")
        full_msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs[-20:]

        is_last = user_count >= MAX_USER_MSGS
        if is_last:
            full_msgs.append({"role": "system", "content": CLOSING_PROMPT})

        reply = ""
        try:
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/chat/completions",
                data=json.dumps({
                    "model": "deepseek-chat",
                    "messages": full_msgs,
                    "temperature": 0.5,
                    "max_tokens": 600,
                }).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {API_KEY}",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                reply = result["choices"][0]["message"]["content"]

            if len(reply) > 800:
                truncated = reply[:750]
                last = max(truncated.rfind("."), truncated.rfind("!"), truncated.rfind("?"))
                reply = reply[:last + 1] if last > 400 else truncated + "…"

            reply_lower = reply.lower()
            natural_close = any(phrase in reply_lower for phrase in CLOSURE_PHRASES)
            should_close = is_last or natural_close

            self.send_json(200, {"reply": reply, "closed": should_close, "session_id": web_sid})
        except Exception as e:
            print(f"  API error: {e}", flush=True)
            self.send_json(500, {"error": "Upstream error", "closed": False, "session_id": web_sid})

        if user_count >= 2 and reply:
            save_session(msgs + [{"role": "assistant", "content": reply}], user_count, web_sid)

    def send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())


# ── Main ───────────────────────────────────────────────────────
def main():
    global API_KEY, SYSTEM_PROMPT, AGENT_NAME, PORT

    # Parse CLI args
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] in ("--port", "-p") and i + 1 < len(args):
            PORT = int(args[i + 1]); i += 2
        elif args[i] in ("--key", "-k") and i + 1 < len(args):
            API_KEY = args[i + 1]; i += 2
        elif args[i] in ("--name", "-n") and i + 1 < len(args):
            AGENT_NAME = args[i + 1]; i += 2
        elif args[i] in ("--soul", "-s") and i + 1 < len(args):
            global SOUL_PATH
            SOUL_PATH = Path(args[i + 1]); i += 2
        else:
            i += 1

    if not API_KEY:
        API_KEY = load_api_key()
    if not API_KEY:
        print("Error: No API key found.")
        print("  Set CLAIRE_API_KEY in ~/.claire/.env or pass --key sk-...")
        sys.exit(1)

    SYSTEM_PROMPT = load_soul()
    print(f"SOUL.md loaded ({len(SYSTEM_PROMPT)} chars)")

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{AGENT_NAME} running at http://localhost:{PORT}")
    print(f"Model: deepseek-chat | temp=0.5 | max_tokens=600")
    print(f"Auto-close after {MAX_USER_MSGS} messages.")
    print(f"Sessions → {SESSIONS_DIR}")
    print()

    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
