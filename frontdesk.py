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
  python3 frontdesk.py --name Pikachu                 # custom agent name
  python3 frontdesk.py --key sk-...                 # API key (or set FRONTDESK_API_KEY)
  python3 frontdesk.py --soul my-prompt.md          # custom prompt

For public access:
  cloudflared tunnel --url http://localhost:8765
"""

import http.server
import json
import os
import random
import re
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
AGENT_NAME = "Pikachu"  # override with --name

# Request limits (defends against cost/DoS abuse)
MAX_BODY_BYTES = 256 * 1024   # reject request bodies larger than this
MAX_MSG_CHARS = 4000          # truncate any single visitor message

# Rate limiting: 20 requests per 60s per IP
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 20
_rate_limit_store = {}

API_KEY = ""
SYSTEM_PROMPT = ""

# ── API Key ────────────────────────────────────────────────────
def load_api_key():
    """Read the API key from ~/.frontdesk/.env or the environment."""
    env_path = Path.home() / ".frontdesk" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            for prefix in ("FRONTDESK_API_KEY=", "DEEPSEEK_API_KEY="):
                if line.startswith(prefix):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("FRONTDESK_API_KEY", "")

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

# ── Message Sanitizing ─────────────────────────────────────────
def sanitize_messages(raw):
    """Trust nothing from the client.

    The browser sends the whole conversation back each turn, so a visitor
    could otherwise inject their own 'system' messages or fake assistant
    turns to bypass the SOUL.md screening rules. We keep only user/assistant
    turns with string content, and cap each message's length.
    """
    if not isinstance(raw, list):
        return []
    clean = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        clean.append({"role": role, "content": content[:MAX_MSG_CHARS]})
    return clean


# ── Session Saving ─────────────────────────────────────────────
# session_id ends up in a filename, so a visitor must never be able to smuggle
# path separators or "../" into it. Only allow the shape we generate ourselves.
_SESSION_ID_RE = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")

def make_session_id():
    return f"{time.strftime('%Y%m%d_%H%M%S')}_{random.randint(1000, 9999)}"

def safe_session_id(raw):
    """Return a filesystem-safe session id, replacing anything untrusted."""
    if isinstance(raw, str) and _SESSION_ID_RE.match(raw):
        return raw
    return make_session_id()

def save_session(msgs, user_count, session_id=None):
    """Save full conversation to sessions/{session_id}.json"""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    # session_id is already validated by safe_session_id() before reaching here,
    # but re-validate so this stays safe if called from elsewhere.
    session_id = safe_session_id(session_id)
    path = SESSIONS_DIR / f"{session_id}.json"

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
    try:
        os.chmod(path, 0o600)  # transcripts may hold personal info — owner-only
    except OSError:
        pass
    print(f"  Session saved: {path.name}", flush=True)


# ── Closure Detection ──────────────────────────────────────────
CLOSING_PROMPT = (
    "\n\nThis is the final message of this conversation. "
    "Wrap up naturally: thank them, summarize, and say goodbye. "
    "Keep it short. Do not invite further replies."
)

# Kept deliberately conservative: phrases that almost only appear in a genuine
# sign-off. Vague ones like "have a good" / "wish you" were removed because they
# also show up mid-conversation and closed sessions prematurely.
CLOSURE_PHRASES = [
    "best of luck", "goodbye", "good bye", "all the best",
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

# ── Chat page ──────────────────────────────────────────────────
# Plain HTML / CSS / JS, kept out of Python's way. build_html() drops the
# agent's name into the {{NAME}} placeholders at request time.
CHAT_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{NAME}}</title>
<style>
  :root { --bg: #f5f3f0; --card: #fff; --text: #1a1a1a; --muted: #999; --accent: #2d2d2d; --bubble-me: #e8e6e3; --bubble-them: #fff; --border: #e0ddd8; --danger: #c44; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; justify-content: center; padding: 20px; }
  .app { width: 100%; max-width: 540px; display: flex; flex-direction: column; min-height: 90vh; }
  header { text-align: center; padding: 32px 0 12px; }
  header h1 { font-size: 1.6rem; font-weight: 500; letter-spacing: 0.06em; }
  header p { color: var(--muted); font-size: 0.82rem; margin-top: 4px; }
  .chat { flex: 1; display: flex; flex-direction: column; gap: 8px; overflow-y: auto; padding: 12px 0; }
  .msg { max-width: 88%; padding: 10px 14px; border-radius: 14px; font-size: 0.88rem; line-height: 1.55; word-break: break-word; }
  .msg.user { align-self: flex-end; background: var(--bubble-me); border-bottom-right-radius: 6px; }
  .msg.bot { align-self: flex-start; background: var(--bubble-them); border: 1px solid var(--border); border-bottom-left-radius: 6px; }
  .msg.closed { align-self: center; color: var(--muted); font-size: 0.78rem; padding: 8px 0; font-style: italic; }
  .msg.error { align-self: center; background: #fff0f0; border: 1px solid #fcc; color: var(--danger); font-size: 0.8rem; max-width: 95%; }
  .input-area { display: flex; gap: 8px; padding: 12px 0 20px; border-top: 1px solid var(--border); margin-top: auto; }
  .input-area input { flex: 1; padding: 12px 16px; border: 1px solid var(--border); border-radius: 20px; font-size: 0.88rem; background: #fff; }
  .input-area input:disabled { opacity: 0.4; }
  .input-area button { background: var(--accent); color: #fff; border: none; width: 40px; height: 40px; border-radius: 50%; font-size: 1rem; cursor: pointer; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
  .input-area button:disabled { opacity: 0.3; cursor: not-allowed; }
  .typing { color: var(--muted); font-size: 0.8rem; padding: 4px 14px; align-self: flex-start; font-style: italic; display: none; }
  footer { text-align: center; padding: 4px 0 12px; font-size: 0.7rem; color: var(--muted); }
</style>
</head>
<body>
<div class="app">
  <header><h1>{{NAME}}</h1><p>Front desk</p></header>
  <div class="chat" id="chat"></div>
  <div class="typing" id="typing">{{NAME}} is thinking…</div>
  <div class="input-area" id="input-area">
    <input type="text" id="input" placeholder="Introduce yourself…" onkeydown="if(event.key==='Enter')send()" autofocus>
    <button id="sendBtn" onclick="send()">→</button>
  </div>
  <footer>You're talking to {{NAME}}, an AI assistant. They'll figure out how best to help.</footer>
</div>
<script>
const $chat = document.getElementById('chat');
const $input = document.getElementById('input');
const $sendBtn = document.getElementById('sendBtn');
const $typing = document.getElementById('typing');
let messages = [{role:'system',content:''}];
let waiting = false;
let closed = false;
let sessionId = null;

function addMsg(text, role) {
  const div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = renderMD(text);
  $chat.appendChild(div);
  $chat.scrollTop = $chat.scrollHeight;
}

function renderMD(text) {
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n/g, '<br>');
  return html;
}

function closeChat() {
  closed = true;
  document.getElementById('input-area').style.display = 'none';
  document.querySelector('footer').textContent = 'Conversation ended.';
  addMsg('— end of conversation —', 'closed');
}

async function send() {
  const text = $input.value.trim();
  if (!text || waiting || closed) return;
  $input.value = '';
  waiting = true;
  $input.disabled = true;
  $sendBtn.disabled = true;
  addMsg(text, 'user');
  messages.push({role:'user',content:text});
  $typing.style.display = 'block';
  $chat.scrollTop = $chat.scrollHeight;

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({messages, session_id: sessionId})
    });
    if (!resp.ok) {
      const err = await resp.json().catch(()=>({}));
      throw new Error(err.error || 'Something went wrong');
    }
    const data = await resp.json();
    sessionId = data.session_id;
    messages.push({role:'assistant',content:data.reply});
    addMsg(data.reply, 'bot');
    if (data.closed) closeChat();
  } catch(e) {
    addMsg('Sorry, something went wrong. Try again in a moment.', 'error');
  } finally {
    $typing.style.display = 'none';
    if (!closed) {
      waiting = false;
      $input.disabled = false;
      $sendBtn.disabled = false;
    }
    $input.focus();
    $chat.scrollTop = $chat.scrollHeight;
  }
}

addMsg("Hi! I'm {{NAME}}. Who are you, and what brings you here?", 'bot');
</script>
</body>
</html>"""

def build_html(name):
    """Render the chat page with the agent's name filled in."""
    return CHAT_HTML.replace("{{NAME}}", name)


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

        # Rate limit. Behind cloudflared every request arrives from
        # 127.0.0.1, so the real visitor IP must come from the proxy header.
        client_ip = self.get_client_ip()
        if check_rate_limit(client_ip):
            self.send_json(429, {"error": "Too many requests. Please wait.", "closed": False})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_json(400, {"error": "Invalid request", "closed": False})
            return
        if length > MAX_BODY_BYTES:
            self.send_json(413, {"error": "Message too large", "closed": False})
            return

        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON", "closed": False})
            return

        msgs = sanitize_messages(data.get("messages", []))

        # Never trust the client's session_id verbatim — it becomes a filename.
        web_sid = safe_session_id(data.get("session_id"))

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

    def get_client_ip(self):
        """Real visitor IP. Trust Cloudflare's header when present (we sit
        behind cloudflared); otherwise fall back to the socket address.
        Only trust these headers if you actually run behind that proxy."""
        cf = self.headers.get("CF-Connecting-IP")
        if cf:
            return cf.strip()
        xff = self.headers.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

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
        print("  Set FRONTDESK_API_KEY in ~/.frontdesk/.env or pass --key sk-...")
        sys.exit(1)

    SYSTEM_PROMPT = load_soul()
    print(f"SOUL.md loaded ({len(SYSTEM_PROMPT)} chars)")

    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"{AGENT_NAME} running at http://localhost:{PORT}")
    print(f"Model: deepseek-chat | temp=0.5 | max_tokens=600")
    print(f"Auto-close after {MAX_USER_MSGS} messages.")
    print(f"Sessions → {SESSIONS_DIR}")
    print()

    # Threaded: one slow 30s DeepSeek call must not block other visitors.
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")


if __name__ == "__main__":
    main()
