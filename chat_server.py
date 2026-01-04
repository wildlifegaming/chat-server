from flask import Flask, request, redirect, url_for, jsonify, session
from flask_socketio import SocketIO, emit
import json, random, os, re, time, threading, subprocess, shutil, hashlib, bcrypt



app = Flask(__name__)
app.secret_key = "supergeheimes_passwort"
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Dateien / Speicher ---
DATA_FILE = "emails.json"
IPS_FILE = "ips.json"

# eingebaute (geschützte) Admins mit sichtbaren Namen
ADMINS = {
    "Yaruk@example.com": "Yaruk",
    "Dilah@example.com": "Dilah",
    "Fanty@example.com": "Fanty",
    "Nuggu@example.com": "Nuggu",
    "Tangy@dev.com": "Tangy"
}

# Zusatz-Admins (durch Yaruk/Tangy verwaltet)
ADMIN_EMAILS_FILE = "admin_emails.json"           # dict {email: name}
# --- Chat: ab jetzt getrennte Dateien ---
ADMIN_CHAT_FILE = "admin_chat.json"
COMMUNITY_CHAT_FILE = "community_chat.json"

# Gewinner-Historie
WINNERS_FILE = "winners.json"                      # list of {email, timestamp}
# Vorschläge
SUGGESTIONS_FILE = "suggestions.json"              # list of {user, text, timestamp}
# Cookie-Klicks
COOKIES_FILE = "cookie_clicks.json"                # dict {username: clicks}
# Einstellungen
SETTINGS_FILE = "settings.json"                    # dict {"max_participants": int, "theme": "dark"|"light"}

# Usernames & Admin-Passwörter
USERNAMES_FILE = "usernames.json"                  # dict {email: username}
ADMIN_PASSWORDS_FILE = "admin_passwords.json"      # dict {email: sha256_hex}
# Snake Leaderboard
SNAKE_SCORES_FILE = "snake_scores.json"            # list of {username, score, timestamp}

# ------------------- Helpers: JSON -------------------
def load_json(file, default):
    if not os.path.exists(file):
        return default
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

# generische Daten
def load_emails(): return load_json(DATA_FILE, [])
def save_emails(emails): save_json(DATA_FILE, emails)
def load_ips(): return load_json(IPS_FILE, [])
def save_ips(ips): save_json(IPS_FILE, ips)

# chat getrennt
def load_admin_chat(): return load_json(ADMIN_CHAT_FILE, [])
def save_admin_chat(history): save_json(ADMIN_CHAT_FILE, history)
def load_community_chat(): return load_json(COMMUNITY_CHAT_FILE, [])
def save_community_chat(history): save_json(COMMUNITY_CHAT_FILE, history)

# winners
def load_winners(): return load_json(WINNERS_FILE, [])
def save_winners(w): save_json(WINNERS_FILE, w)

# settings
def load_settings():
    s = load_json(SETTINGS_FILE, {})
    if "max_participants" not in s: s["max_participants"] = 0  # 0 = unlimitiert
    if "theme" not in s: s["theme"] = "dark"
    return s
def save_settings(s): save_json(SETTINGS_FILE, s)

# suggestions
def load_suggestions(): return load_json(SUGGESTIONS_FILE, [])
def save_suggestions(lst): save_json(SUGGESTIONS_FILE, lst)

# cookies
def load_cookie_clicks(): return load_json(COOKIES_FILE, {})
def save_cookie_clicks(d): save_json(COOKIES_FILE, d)

# additional admins
def load_admin_emails():
    data = load_json(ADMIN_EMAILS_FILE, {})
    # Safety: falls versehentlich Liste gespeichert wurde
    if isinstance(data, list):
        conv = {}
        for e in data:
            conv[e] = e.split("@")[0]
        data = conv
    return data
def save_admin_emails(d): save_json(ADMIN_EMAILS_FILE, d)

def get_all_admins():
    extra = load_admin_emails()
    merged = {**ADMINS, **extra}
    return merged

# usernames
def load_usernames(): return load_json(USERNAMES_FILE, {})
def save_usernames(d): save_json(USERNAMES_FILE, d)

# admin passwords (sha256 hex)
def load_admin_passwords(): return load_json(ADMIN_PASSWORDS_FILE, {})
def save_admin_passwords(d): save_json(ADMIN_PASSWORDS_FILE, d)
def hash_password(password: str) -> str:
    # erzeugt automatisch ein Salt, Ergebnis als String speichern
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

# --- Chat-History beim Start laden (getrennt) ---
admin_chat_messages = load_admin_chat()
community_chat_messages = load_community_chat()

def is_valid_email(email):
    return re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email) is not None

# ------------------- Name-Tier nach Klicks -------------------
def get_name_tier(username: str):
    clicks = load_cookie_clicks().get(username, 0)
    if clicks >= 10000:
        return "tier-rainbow"
    if clicks >= 100:
        return "tier-gold"
    return "tier-default"

# ------------------- Spezielle Nameffekte -------------------
def get_special_name_class(username: str):
    # Matrix für Tangy, Regenbogen für Yaruk, Neon-Blau für Dilah
    if username == "Tangy":
        return "matrix"
    if username == "Yaruk":
        return "tier-rainbow"
    if username == "Dilah":
        return "neon-blue"
    return ""

# ------------------- Login -------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip()
        username = (request.form.get("username") or "").strip()
        password = (request.form.get("password") or "").strip()
        ip = request.remote_addr

        admins = get_all_admins()
        is_admin = email in admins

        # Admin-Login
        if is_admin:
            admin_passwords = load_admin_passwords()
            stored_hash = admin_passwords.get(email)

            # Passwort existiert schon -> prüfen
            if stored_hash:
                if not password:
                    return render_message("Bitte Passwort eingeben (Admin).")
                if not check_password(password, stored_hash):
                    return render_message("Falsches Passwort.")
                # ok
                session["is_admin"] = True
                session["email"] = email
                session["name"] = admins[email]  # Anzeigename
                return redirect(url_for("admin_dashboard"))
                print("")
            else:
                # Erstes Mal: Passwort setzen
                if not password or len(password) < 6:
                    return render_message("Bitte neues Admin-Passwort setzen (mind. 6 Zeichen).")
                admin_passwords[email] = hash_password(password)
                save_admin_passwords(admin_passwords)
                session["is_admin"] = True
                session["email"] = email
                session["name"] = admins[email]
                return redirect(url_for("admin_dashboard"))

        # Normaler User
        if not is_valid_email(email):
            return render_message("Ungültige E-Mail-Adresse! Bitte korrekt eingeben.")
        if not username or len(username) < 3:
            return render_message("Bitte Username angeben (mind. 3 Zeichen).")

        # Max-Teilnehmer prüfen
        settings = load_settings()
        emails = load_emails()
        ips = load_ips()

        if settings.get("max_participants", 0) > 0 and len(emails) >= settings["max_participants"]:
            return render_message("Die maximale Teilnehmerzahl wurde erreicht.")

        if ip in ips:
            # trotzdem ins User-Dashboard lassen – Teilnahme-Limit bezieht sich nur auf Verlosung
            pass

        # --- Minimal invasiv: bestehendes Verhalten beibehalten ---
        # (User wird weiterhin automatisch eingetragen; kann sich aber in der Verlosung-Ansicht austragen)
        if email not in emails:
            emails.append(email)
            save_emails(emails)
        if ip not in ips:
            ips.append(ip)
            save_ips(ips)

        # Username speichern/aktualisieren
        unames = load_usernames()
        unames[email] = username
        save_usernames(unames)

        session["is_admin"] = False
        session["email"] = email
        session["name"] = username
        return redirect(url_for("user_dashboard"))

    return login_form()

def render_message(msg):
    return f"""
    <html><head><style>
    body {{ font-family: Arial; background-color: #0aff6c; text-align: center; padding: 50px; color: white; }}
    .box {{ background: rgba(0,0,0,0.7); padding: 20px; border-radius: 15px; display: inline-block; }}
    a {{ color: #0aff6c; text-decoration: none; }}
    </style></head><body>
    <div class='box'>
    <h2>{msg}</h2>
    <a href="/">Zurück</a>
    </div>
    </body></html>
    """

def login_form():
    # Formular: email; wenn Admin → Passwortfeld sichtbar; wenn User → Username-Feld
    # Passwortfeld wird clientseitig ein-/ausgeblendet, sobald E-Mail als Admin erkannt wird
    admin_list = list(get_all_admins().keys())
    admin_js_array = json.dumps(admin_list)
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <title>Login</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{ font-family: Arial; background: linear-gradient(135deg, #00ff88, #00cc66); display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; color: white; }}
        .login-box {{ background: rgba(0,0,0,0.8); padding: 25px; border-radius: 15px; box-shadow: 0 0 25px rgba(0,0,0,0.4); width: 90%; max-width: 380px; animation: fadeIn 1s; }}
        input, button {{ padding: 12px; border-radius: 8px; border: none; margin: 5px 0; width: 100%; font-size: 1em; }}
        input {{ background: white; color: black; }}
        button {{ background-color: #00ff88; color: black; font-weight: bold; cursor: pointer; transition: 0.3s; }}
        button:hover {{ background-color: #00cc66; }}
        @keyframes fadeIn {{ from {{ opacity: 0; transform: scale(0.9); }} to {{ opacity: 1; transform: scale(1); }} }}
        .hint {{ font-size:.9em; opacity:.85; }}
        .hidden {{ display:none; }}
        .link {{ text-decoration: underline; cursor: pointer; color: #0aff6c; }}
        .modal {{ display: none; position: fixed; z-index: 999; left: 0; top: 0; width: 100%; height: 100%; overflow: auto; background-color: rgba(0,0,0,0.7); }}
        .modal-content {{ background-color: #111; margin: 10% auto; padding: 20px; border-radius: 15px; width: 90%; max-width: 400px; color: white; text-align: left; max-height: 70%; overflow: hidden; display: flex; flex-direction: column; }}
        .agb-text {{ flex: 1; overflow-y: auto; padding-right: 10px; margin-bottom: 10px; border: 1px solid #00ff88; border-radius: 10px; background: rgba(0,255,136,0.05); }}
        .modal-content button {{ width: auto; padding: 10px; border-radius: 8px; background-color: #00ff88; color: black; font-weight: bold; cursor: pointer; }}
    </style>
    </head>
    <body>
    <div class="login-box">
        <h2>Einloggen</h2>
        <form method="POST">
            <input type="email" id="email" name="email" placeholder="E-Mail" required oninput="toggleFields()">
            <div id="row-username">
                <input type="text" id="username" name="username" placeholder="Dein Username">
                <div class="hint"></div>
            </div>
            <div id="row-password" class="hidden">
                <input type="password" id="password" name="password" placeholder="Admin-Passwort">
                <div id="pw-hint" class="hint">Wenn du noch kein Passwort hast, gib hier dein neues Passwort ein (mind. 6 Zeichen).</div>
            </div>
            <button type="submit">Weiter</button>
        </form>

        <p style="font-size:0.9em; margin-top:10px;">
            <span class="link" onclick="openAGB()">AGB / Teilnahmebedingungen lesen</span>
        </p>
    </div>

    <!-- Modal AGB -->
    <div id="agbModal" class="modal">
        <div class="modal-content">
            <h3>AGB / Teilnahmebedingungen</h3>
            <div class="agb-text" id="agbText">
                <p><b>Gewinner:</b> Der Gewinner wird nach dem Zufallsprinzip ermittelt. Der Gewinn ist nicht übertragbar und kann nicht ausgezahlt werden.</p>
                <p><b>Datenschutz:</b> Die angegebenen E-Mail-Adressen werden ausschließlich für die Durchführung der Verlosung gespeichert und nicht an Dritte weitergegeben.</p>
                <p><b>Haftung:</b> Der Veranstalter haftet nicht für technische oder andere Störungen, welche auf dieser Website erscheinen könnten</p>
                <p><b>Rechtsweg:</b> Der Rechtsweg ist ausgeschlossen.</p>
            </div>
            <button onclick="closeAGB()">Ich stimme zu / Weiter</button>
        </div>
    </div>

    <script>
    const ADMIN_LIST = {admin_js_array};

    function toggleFields() {{
        const email = (document.getElementById("email").value || "").trim().toLowerCase();
        const isAdmin = ADMIN_LIST.map(e=>e.toLowerCase()).includes(email);
        const rowU = document.getElementById("row-username");
        const rowP = document.getElementById("row-password");
        if(isAdmin) {{
            rowU.classList.add("hidden");
            rowP.classList.remove("hidden");
        }} else {{
            rowU.classList.remove("hidden");
            rowP.classList.add("hidden");
        }}
    }}

    function openAGB() {{ document.getElementById("agbModal").style.display = "block"; }}
    function closeAGB() {{ document.getElementById("agbModal").style.display = "none"; }}
    window.onload = () => {{
        if(!localStorage.getItem("agbSeen")) {{
            openAGB();
            localStorage.setItem("agbSeen", "true");
        }}
        toggleFields();
    }}
    </script>
    </body>
    </html>
    """

# ------------------- Admin Dashboard -------------------
@app.route("/Administration_panel")
def admin_dashboard():
    if not session.get("is_admin"):
        return redirect(url_for("login"))

    emails = load_emails()
    email_list = "".join([f"<li>{email} <span style='color:red;cursor:pointer' onclick='deleteEmail(\"{email}\")'>❌</span></li>" for email in emails])

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
    <title>Admin</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root {{
            --bgstart: #00ff88; --bgend:#00cc66; --text:#fff; --panelbg: rgba(0,0,0,0.85); --accent:#00ff88; --accentHover:#00cc66;
        }}
        body.light {{
            --bgstart: #f2f2f2; --bgend:#e6e6e6; --text:#111; --panelbg: rgba(255,255,255,0.92); --accent:#007a5e; --accentHover:#005a46;
        }}
        body {{ font-family: Arial; margin:0; padding:0; background: linear-gradient(135deg, var(--bgstart), var(--bgend)); color: var(--text); }}
        .top-bar {{ display:flex; justify-content:flex-end; padding:10px; background: rgba(0,0,0,0.35); position: sticky; top:0; z-index:100; }}
        .hamburger {{ font-size: 24px; cursor: pointer; }}

        .sidebar {{ height: 100%; width: 0; position: fixed; z-index: 200; top: 0; right: 0; background-color: rgba(0,0,0,0.95); overflow-x: hidden; transition: 0.5s; padding-top: 60px; }}
        .sidebar a {{ padding: 10px 15px; text-decoration: none; font-size: 20px; color: #00ff88; display: block; transition: 0.3s; cursor: pointer; }}
        .sidebar a:hover {{ color: #0aff6c; }}
        .sidebar .closebtn {{ position: absolute; top: 10px; right: 20px; font-size: 36px; }}

        .panel {{ padding: 20px; margin: 20px auto; max-width: 700px; background: var(--panelbg); border-radius: 15px; box-shadow: 0 0 25px rgba(0,0,0,0.4); }}
        ul {{ list-style:none; padding:0; }}
        li {{ background: rgba(255,255,255,0.1); padding: 8px; margin:5px 0; border-radius:8px; display:flex; justify-content:space-between; align-items:center; }}
        button {{ background-color: var(--accent); color:black; padding:10px; border:none; border-radius:8px; margin:5px; cursor:pointer; font-weight:bold; }}
        button:hover {{ background-color: var(--accentHover); }}
        input, select, textarea {{ width:100%; padding:10px; border-radius:8px; border:none; margin:5px 0; }}

        /* Chatbereich */
        #chat-area {{ margin-top:15px; }}
        #chat-messages {{ height:300px; overflow-y:auto; border:1px solid var(--accent); padding:10px; border-radius:10px; margin-bottom:10px; background: rgba(0,0,0,0.2); }}
        #chat-input {{ width:calc(100% - 80px); padding:10px; border-radius:8px; border:none; }}

        /* Name Styles */
        .name.tier-gold {{ color:#FFD700; }}
        .name.tier-rainbow {{
            background: linear-gradient(90deg, red, orange, yellow, green, blue, indigo, violet);
            -webkit-background-clip: text; color: transparent;
            background-size: 200% 100%;
            animation: rainbow 5s linear infinite;
        }}
        @keyframes rainbow {{ from {{ background-position: 0% 50%; }} to {{ background-position: 200% 50%; }} }}

        /* Spezialeffekte */
        .name.matrix {{
            color: #00ff88;
            text-shadow: 0 0 6px #00ff88, 0 0 12px #00ff88;
            position: relative;
        }}
        .name.neon-blue {{
            color: #00b7ff;
            text-shadow: 0 0 6px #00b7ff, 0 0 12px #00b7ff, 0 0 24px #00b7ff;
            animation: neonPulse 2.2s ease-in-out infinite;
        }}
        @keyframes neonPulse {{ 0%,100% {{ text-shadow: 0 0 6px #00b7ff, 0 0 12px #00b7ff, 0 0 24px #00b7ff; }} 50% {{ text-shadow: 0 0 2px #00b7ff, 0 0 6px #00b7ff, 0 0 12px #00b7ff; }} }}

        .muted {{ opacity:.7; font-size:.95em; }}
        .inline-btn {{ display:inline-block; margin-left:8px; }}
        .table {{ width:100%; border-collapse: collapse; }}
        .table th, .table td {{ padding:8px; border-bottom:1px solid rgba(255,255,255,0.15); text-align:left; }}
        .tag {{ font-size:12px; opacity:.8; }}
    </style>
    </head>
    <body>
    
    <div class="top-bar">
        <span class="hamburger" onclick="openSidebar()">☰</span>
    </div>

    <div id="mySidebar" class="sidebar">
        <a href="javascript:void(0)" class="closebtn" onclick="closeSidebar()">×</a>
        <a onclick="showPanel('verlosung')">🎟️ Verlosung</a>
        <a onclick="showPanel('chat')">💬 Chat</a>
        <a onclick="showPanel('communityChat')">🌍 Community Chat</a>
        <a onclick="showPanel('stats')">📊 Statistik</a>
        <a onclick="showPanel('winners')">🏆 Gewinner-Historie</a>
        <a onclick="showPanel('settings')">⚙️ Einstellungen</a>
        <a onclick="showPanel('suggestions')">💡 Verbesserungsvorschläge</a>
        <a id="cookieTab" style="display:none;" onclick="showPanel('cookie')">🍪 Cookie</a>
        <a id="emailTab" style="display:none;" onclick="showPanel('adminEmails')">📧 Admin-E-Mails</a>
    </div>
    
    <!-- Community Chat -->
    <div id="communityChat" class="panel" style="display:none;">
        <h2>🌍 Community-Chat </h2>
        <div id="community-chat-messages" style="height:300px; overflow-y:auto; border:1px solid var(--accent); padding:10px; border-radius:10px; background: rgba(0,0,0,0.2); margin-bottom:10px;"></div>
        <div style="display:flex; gap:5px;">
            <input type="text" id="community-chat-input" placeholder="Nachricht eingeben">
            <button onclick="sendCommunityMessage()">Senden</button>
        </div>
    </div>


    <!-- Verlosung -->
    <div id="verlosung" class="panel">
        <h2>Admin Dashboard - Verlosung</h2>
        <ul id="email-list">{email_list}</ul>

        <h3>Neue E-Mail hinzufügen:</h3>
        <input type="email" id="new-email" placeholder="Email eingeben">
        <button onclick="addEmail()">Hinzufügen</button>

        <h3>Aktionen:</h3>
        <button class="danger" onclick="deleteAll()">Alle löschen</button>
        <button onclick="draw()">Verlosung</button>
        <p id="winner"></p>
        <a href="/logout"><button>Logout</button></a>
    </div>

    <!-- Chat -->
    <div id="chat" class="panel" style="display:none;">
        <h2>Admin Chat</h2>
        <div id="chat-area">
            <div id="chat-messages"></div>
            <div style="display:flex;gap:5px;">
                <input type="text" id="chat-input" placeholder="Nachricht eingeben">
                <button onclick="sendMessage()">Senden</button>
            </div>
        </div>
    </div>

    <!-- Statistik -->
    <div id="stats" class="panel" style="display:none;">
        <h2>📊 Statistik</h2>
        <div id="stats-container">
            <p>Teilnehmer: <b id="stat-participants">–</b></p>
            <p>Geräte (IPs): <b id="stat-ips">–</b></p>
            <p>Chat-Nachrichten (Admin): <b id="stat-chat-admin">–</b></p>
            <p>Chat-Nachrichten (Community): <b id="stat-chat-community">–</b></p>
            <p>Vorschläge: <b id="stat-suggestions">–</b></p>
            <p>Ziehungen gesamt: <b id="stat-draws">–</b> <span class="tag" id="stat-lastdraw"></span></p>
        </div>
    </div>

    <!-- Gewinner-Historie -->
    <div id="winners" class="panel" style="display:none;">
        <h2>🏆 Gewinner-Historie</h2>
        <ul id="winners-list"></ul>
    </div>

    <!-- Einstellungen -->
    <div id="settings" class="panel" style="display:none;">
        <h2>⚙️ Einstellungen</h2>
        <label>Maximale Anzahl Teilnehmer (0 = unbegrenzt)</label>
        <input type="number" id="set-max" min="0" value="0">
        <label>Theme</label>
        <select id="set-theme">
            <option value="dark">Dark</option>
            <option value="light">Light</option>
        </select>
        <button onclick="saveSettings()">Speichern</button>
        <span id="settings-saved" class="tag"></span>
    </div>

    <!-- Verbesserungsvorschläge -->
    <div id="suggestions" class="panel" style="display:none;">
        <h2>💡 Verbesserungsvorschläge</h2>
        <div id="suggestions-admin" style="display:none;">
            <ul id="suggestion-list"></ul>
        </div>
        <div id="suggestions-user" style="display:none;">
            <p class="muted">Sende hier Vorschläge zur Verbesserung der Website.</p>
            <textarea id="suggestion-text" placeholder="Dein Verbesserungsvorschlag..."></textarea>
            <button onclick="sendSuggestion()">Absenden</button>
        </div>
    </div>

    <!-- Cookie -->
    <div id="cookie" class="panel" style="display:none;">
        <h2>🍪 Cookie</h2>
        <div id="cookie-admin" style="display:none;">
            <table class="table" id="cookie-admin-table">
                <thead><tr><th>Benutzer</th><th>Klicks</th><th>Aktion</th></tr></thead>
                <tbody></tbody>
            </table>
        </div>
        <div id="cookie-user" style="display:none;">
            <div class="cookie-btn" onclick="clickCookie()" title="Klick mich!"></div>
            <p id="cookie-msg" class="hint">Lecker. 🍪</p>
        </div>
    </div>

    <!-- Admin-E-Mails -->
    <div id="adminEmails" class="panel" style="display:none;">
        <h2>📧 Admin-E-Mail-Adressen</h2>
        <ul id="admin-email-list"></ul>
        <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <input type="email" id="new-admin-email" placeholder="Neue Admin-E-Mail">
            <input type="text" id="new-admin-name" placeholder="Anzeigename (optional)">
            <button onclick="addAdminEmail()">Hinzufügen</button>
        </div>
        <p class="hint">Eingebaute Admins sind geschützt (🔒) und können nicht gelöscht werden.</p>

        <div id="admin-password-reset" style="display:none; margin-top:15px;">
            <h3>🔐 Admin-Passwort zurücksetzen</h3>
            <div style="display:flex; gap:8px; flex-wrap:wrap;">
                <input type="email" id="reset-admin-email" placeholder="Admin-E-Mail">
                <button onclick="resetAdminPassword()">Zurücksetzen</button>
            </div>
            <span id="reset-msg" class="tag"></span>
        </div>
    </div>

    <script src="https://cdn.socket.io/4.6.1/socket.io.min.js"></script>
    <script>
        let currentUser = null;
        let currentEmail = null;
        let currentIsAdmin = false;

        function openSidebar() {{ document.getElementById("mySidebar").style.width = "260px"; }}
        function closeSidebar() {{ document.getElementById("mySidebar").style.width = "0"; }}

        function showPanel(panel) {{
            const ids = ['verlosung','communityChat','chat','stats','winners','settings','suggestions','cookie','adminEmails'];
            ids.forEach(id => document.getElementById(id).style.display = (id===panel ? 'block':'none'));
            if(panel==='stats') loadStats();
            if(panel==='winners') loadWinners();
            if(panel==='settings') loadSettings();
            if(panel==='suggestions') initSuggestions();
            if(panel==='cookie') initCookie();
            if(panel==='adminEmails') loadAdminEmails();
        }}
        showPanel('verlosung');
 
        function loadAdminChat() {{
            fetch("/chat_history/admin").then(r=>r.json()).then(list => {{
                const container = document.getElementById("chat-messages");
                container.innerHTML = "";
                list.forEach(data => {{
                    const time = new Date(data.timestamp * 1000).toLocaleTimeString();
                   const tierClass = data.tier || "tier-default";
                    const fx = data.namefx || "";
                    const titleAttr = (data.role === 'admin' && data.email) ? ` title="${{data.email}}"` : "";
                    container.innerHTML += `<p><b>[${{time}}] <span class="name ${{tierClass}} ${{fx}}"${{titleAttr}}>${{data.user}}</span>:</b> ${{data.message}}</p>`;
                }});
                container.scrollTop = container.scrollHeight;
            }});
        }}

        function loadCommunityChat() {{
            fetch("/chat_history/community").then(r=>r.json()).then(list => {{
                const community = document.getElementById("community-chat-messages");
                community.innerHTML = "";
                list.forEach(data => {{
                    const time = new Date(data.timestamp * 1000).toLocaleTimeString();
                    const tierClass = data.tier || "tier-default";
                    const fx = data.namefx || "";
                    const titleAttr = (data.role === 'admin' && data.email) ? ` title="${{data.email}}"` : "";
                    community.innerHTML += `<p><b>[${{time}}] <span class="name ${{tierClass}} ${{fx}}"${{titleAttr}}>${{data.user}}</span>:</b> ${{data.message}}</p>`;
                }});
                community.scrollTop = community.scrollHeight;
            }});
        }}


        function showPanel(panel) {{
            const ids = ['verlosung','communityChat','chat','stats','winners','settings','suggestions','cookie','adminEmails'];
            ids.forEach(id => document.getElementById(id).style.display = (id===panel ? 'block':'none'));
            if(panel==='chat') loadAdminChat();
            if(panel==='communityChat') loadCommunityChat();
            if(panel==='stats') loadStats();
            if(panel==='winners') loadWinners();
            if(panel==='settings') loadSettings();
            if(panel==='suggestions') initSuggestions();
            if(panel==='cookie') initCookie();
            if(panel==='adminEmails') loadAdminEmails();
        }}


        function refresh() {{ location.reload(); }}
        function deleteEmail(email) {{
            fetch(`/delete/${{encodeURIComponent(email)}}`, {{method: "POST"}}).then(refresh);
        }}
        function deleteAll() {{
            fetch("/delete_all", {{method: "POST"}}).then(refresh);
        }}
        function addEmail() {{
            const email = document.querySelector("#new-email").value;
            fetch("/add", {{
                method: "POST",
                headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
                body: "email=" + encodeURIComponent(email)
            }}).then(refresh);
        }}
        function draw() {{
            fetch("/draw").then(res => res.json()).then(data => {{
                document.querySelector("#winner").innerText = data.winner ? `Gewinner: ${{data.winner}}` : "Keine E-Mails vorhanden.";
                if(data.winner) loadWinners();
            }});
        }}

        // --- Socket.IO Chat ---
        const socket = io();

        socket.on("connect", () => {{ }});

        // Admin-Chat: nur Nachrichten mit channel==='admin'
        socket.on("new_message", (data) => {{
            if (data.channel !== 'admin') return;
            const container = document.getElementById("chat-messages");
            const time = new Date(data.timestamp * 1000).toLocaleTimeString();
            const tierClass = data.tier || "tier-default";
            const fx = data.namefx || "";
            const titleAttr = (data.role === 'admin' && data.email) ? ` title="${{data.email}}"` : "";
            container.innerHTML += `<p><b>[${{time}}] <span class="name ${{tierClass}} ${{fx}}"${{titleAttr}}>${{data.user}}</span>:</b> ${{data.message}}</p>`;
            container.scrollTop = container.scrollHeight;
        }});

        function sendMessage() {{
            const input = document.getElementById("chat-input");
            const message = input.value.trim();
            if(message) {{
                socket.emit("send_message", {{message, channel:'admin'}});
                input.value = "";
            }}
        }}

        // --- User + Theme laden ---
        fetch("/current_user").then(r=>r.json()).then(data => {{
            currentUser = data.name;
            currentEmail = data.email;
            currentIsAdmin = !!data.is_admin;
            if(["Tangy"].includes(data.name)) {{
                document.getElementById("cookieTab").style.display = "block";
                document.getElementById("cookie-admin").style.display = "block";
                document.getElementById("admin-password-reset").style.display = "block";
            }} else {{
                // Cookie-Tab ist für alle Admins sichtbar, aber nur als "Spaß"-Keks ohne Zahlen
                document.getElementById("cookieTab").style.display = "block";
                document.getElementById("cookie-user").style.display = "block";
            }}
            if(data.name === "Tangy" || data.name === "Yaruk") {{
                document.getElementById("emailTab").style.display = "block";
            }}
            applyTheme(data.theme || 'dark');
        }});

        function applyTheme(theme) {{
            if(theme === 'light') document.body.classList.add('light');
            else document.body.classList.remove('light');
        }}

        // --- Statistik ---
        function loadStats() {{
            fetch("/stats_data").then(r=>r.json()).then(s => {{
                document.getElementById("stat-participants").innerText = s.participants;
                document.getElementById("stat-ips").innerText = s.ips;
                document.getElementById("stat-chat-admin").innerText = s.chat_messages_admin;
                document.getElementById("stat-chat-community").innerText = s.chat_messages_community;
                document.getElementById("stat-suggestions").innerText = s.suggestions;
                document.getElementById("stat-draws").innerText = s.draws;
                document.getElementById("stat-lastdraw").innerText = s.last_draw ? ("Letzte Ziehung: " + new Date(s.last_draw*1000).toLocaleString()) : "";
            }});
        }}

        // --- Gewinner-Historie ---
        function loadWinners() {{
            fetch("/winners_history").then(r=>r.json()).then(list => {{
                const ul = document.getElementById("winners-list");
                ul.innerHTML = "";
                list.slice().reverse().forEach(w => {{
                    const dt = new Date(w.timestamp*1000).toLocaleString();
                    ul.innerHTML += `<li><span>${{w.email}}</span> <span class="tag">(${{dt}})</span></li>`;
                }});
            }});
        }}

        // --- Einstellungen ---
        function loadSettings() {{
            fetch("/settings").then(r=>r.json()).then(s => {{
                document.getElementById("set-max").value = s.max_participants || 0;
                document.getElementById("set-theme").value = s.theme || 'dark';
            }});
        }}
        function saveSettings() {{
            const payload = {{
                max_participants: parseInt(document.getElementById("set-max").value || "0"),
                theme: document.getElementById("set-theme").value
            }};
            fetch("/update_settings", {{
                method:"POST", headers:{{"Content-Type":"application/json"}}, body: JSON.stringify(payload)
            }}).then(r=>r.json()).then(s => {{
                document.getElementById("settings-saved").innerText = "Gespeichert.";
                applyTheme(s.theme);
                setTimeout(()=>document.getElementById("settings-saved").innerText="", 1500);
            }});
        }}

        // --- Vorschläge ---
        function initSuggestions() {{
            fetch("/current_user").then(r=>r.json()).then(u => {{
                if(u.name === "Tangy") {{
                    document.getElementById("suggestions-admin").style.display = "block";
                    document.getElementById("suggestions-user").style.display = "none"; // Tangy darf auch senden
                    loadSuggestions();
                }} else {{
                    document.getElementById("suggestions-user").style.display = "block";
                    document.getElementById("suggestions-admin").style.display = "none";
                }}
            }});
        }}
        function loadSuggestions() {{
            fetch("/suggestions").then(res => res.json()).then(data => {{
                const list = document.getElementById("suggestion-list");
                list.innerHTML = "";
                data.forEach(s => {{
                    const date = new Date(s.timestamp * 1000).toLocaleString();
                    list.innerHTML += `<li><b>${{s.user}}</b>: ${{s.text}} <span class="tag">(${{date}})</span></li>`;
                }});
            }});
        }}
        function sendSuggestion() {{
            const text = document.getElementById("suggestion-text").value.trim();
            if(!text) return;
            fetch("/send_suggestion", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{text}})
            }}).then(() => {{
                document.getElementById("suggestion-text").value = "";
                const wasAdminView = document.getElementById("suggestions-admin").style.display !== "none";
                if(wasAdminView) loadSuggestions();
                loadStats();
                alert("Vorschlag gesendet!");
            }});
        }}

        // --- Cookie ---
        function initCookie() {{
            fetch("/current_user").then(r=>r.json()).then(u => {{
                if(u.name === "Tangy") loadCookieAdmin();
            }});
        }}
        function clickCookie() {{
            fetch("/cookie_click", {{ method:"POST" }}).then(()=>{{
                const msg = document.getElementById("cookie-msg");
                msg.innerText = "Mmmh… 🍪";
                setTimeout(()=>msg.innerText="Lecker. 🍪", 800);
            }});
        }}
        function loadCookieAdmin() {{
            fetch("/cookie_admin").then(res => res.json()).then(data => {{
                const tbody = document.querySelector("#cookie-admin-table tbody");
                tbody.innerHTML = "";
                data.forEach(u => {{
                    tbody.innerHTML += `
                        <tr>
                            <td>${{u.username}}</td>
                            <td><input type="number" min="0" value="${{u.clicks}}" id="clicks-${{u.username}}"></td>
                            <td><button onclick="updateCookie('${{u.username}}')">Speichern</button></td>
                        </tr>`;
                }});
            }});
        }}
        function updateCookie(username) {{
            const clicks = parseInt(document.getElementById(`clicks-${{username}}`).value || "0");
            fetch("/update_cookie_clicks", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{username, clicks}})
            }}).then(() => {{
                loadCookieAdmin();
                alert("Shut up and Take your cookies!!!");
            }});
        }}

        // --- Admin-Emails ---
        function loadAdminEmails() {{
            fetch("/admin_emails").then(res => res.json()).then(data => {{
                const list = document.getElementById("admin-email-list");
                list.innerHTML = "";
                data.forEach(item => {{
                    const lock = item.builtin ? " 🔒" : "";
                    const btn = item.builtin ? "" : ` <button class="inline-btn" onclick="removeAdminEmail('${{item.email}}')">❌</button>`;
                    list.innerHTML += `<li>${{item.email}} <span class='tag'>(${{item.name}})</span>${{lock}}${{btn}}</li>`;
                }});
            }});
        }}
        function addAdminEmail() {{
            const email = document.getElementById("new-admin-email").value.trim();
            const name = document.getElementById("new-admin-name").value.trim();
            if(!email) return;
            fetch("/add_admin_email", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{email, name}})
            }}).then(() => {{
                document.getElementById("new-admin-email").value = "";
                document.getElementById("new-admin-name").value = "";
                loadAdminEmails();
            }});
        }}
        function removeAdminEmail(email) {{
            fetch("/remove_admin_email", {{
                method: "POST",
                headers: {{"Content-Type": "application/json"}},
                body: JSON.stringify({{email}})
            }}).then(() => loadAdminEmails());
        }}

        // --- Admin-Passwort-Reset ---
        function resetAdminPassword() {{
            const email = document.getElementById("reset-admin-email").value.trim();
            if(!email) return;
            fetch("/reset_admin_password", {{
                method: "POST",
                headers: {{"Content-Type":"application/json"}},
                body: JSON.stringify({{email}})
            }}).then(r=>r.json()).then(resp => {{
                document.getElementById("reset-msg").innerText = resp.ok ? "Zurückgesetzt." : (resp.error || "Fehler");
                setTimeout(()=>document.getElementById("reset-msg").innerText="", 2000);
            }});
        }}
        
        // Community-Chat im Admin-Dashboard: nur Nachrichten mit channel==='community'
        socket.on("new_message", (data) => {{
            if (data.channel !== 'community') return;
            const community = document.getElementById("community-chat-messages");
            if (!community) return;
            const time = new Date(data.timestamp * 1000).toLocaleTimeString();
            const tierClass = data.tier || "tier-default";
            const fx = data.namefx || "";
            const titleAttr = (data.role === 'admin' && data.email) ? ` title="${{data.email}}"` : "";
            community.innerHTML += `<p><b>[${{time}}] <span class="name ${{tierClass}} ${{fx}}"${{titleAttr}}>${{data.user}}</span>:</b> ${{data.message}}</p>`;
            community.scrollTop = community.scrollHeight;
        }});

        function sendCommunityMessage() {{
            const input = document.getElementById("community-chat-input");
            const message = input.value.trim();
            if(message) {{
                socket.emit("send_message", {{message, channel:'community'}});
                input.value = "";
            }}
        }}
    </script>

    </body>
    </html>
    """

# --- User Dashboard (Sidebar + Tabs) ---
@app.route("/user_dashboard")
def user_dashboard():
    if not session.get("email"):
        return redirect(url_for("login"))
    s = load_settings()
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>User Dashboard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            :root {{
                --bgstart: #00ff88; --bgend:#00cc66; --text:#fff; --panelbg: rgba(0,0,0,0.85); --accent:#00ff88; --accentHover:#00cc66;
            }}
            body {{ font-family: Arial; margin:0; padding:0; background: linear-gradient(135deg, var(--bgstart), var(--bgend)); color: var(--text); }}
            .container {{ max-width: 900px; margin: 0 auto; padding: 0 12px; }}
            .layout {{ display:grid; grid-template-columns: 220px 1fr; gap: 16px; margin: 20px 0; }}
            .sidebar {{ background: var(--panelbg); border-radius: 15px; padding: 12px; height: calc(100vh - 60px); position: sticky; top: 20px; }}
            .sidebar h3 {{ margin-top: 4px; }}
            .tab {{ display:block; padding:10px 12px; border-radius:10px; cursor:pointer; margin:6px 0; background: rgba(255,255,255,0.06); }}
            .tab:hover {{ background: rgba(255,255,255,0.12); }}
            .active {{ background: rgba(0,255,136,0.18); }}
            .panel {{ background: var(--panelbg); border-radius: 15px; padding: 16px; min-height: 60vh; }}
            h2 {{ margin-top:0; }}
            #chat-messages {{ height: 55vh; min-height: 280px; overflow-y:auto; border:1px solid var(--accent); padding:10px; border-radius:10px; margin-bottom:10px; background: rgba(0,0,0,0.2); }}
            input, button {{ padding:10px; border-radius:8px; border:none; }}
            #chat-input {{ width: calc(100% - 90px); }}
            button {{ background-color: var(--accent); color:black; font-weight:bold; cursor:pointer; }}
            button:hover {{ background-color: var(--accentHover); }}
            .name.tier-gold {{ color:#FFD700; }}
            .name.tier-rainbow {{
                background: linear-gradient(90deg, red, orange, yellow, green, blue, indigo, violet);
                -webkit-background-clip: text; color: transparent;
                background-size: 200% 100%;
                animation: rainbow 8s linear infinite;
            }}
            .name.matrix {{ color:#00ff88; text-shadow:0 0 6px #00ff88, 0 0 12px #00ff88; }}
            .name.neon-blue {{ color:#00b7ff; text-shadow:0 0 6px #00b7ff, 0 0 12px #00b7ff, 0 0 24px #00b7ff; }}
            .top {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }}
            .tag {{ font-size:12px; opacity:.8; }}
            a.btn {{ color:black; text-decoration:none; background: var(--accent); padding:8px 10px; border-radius:8px; }}
            .muted {{ opacity:.75; }}
            canvas {{ background: rgba(0,0,0,0.25); border:1px solid var(--accent); border-radius:10px; display:block; margin-bottom:10px; }}
            table {{ width:100%; border-collapse: collapse; }}
            th, td {{ padding:8px; border-bottom:1px solid rgba(255,255,255,0.12); text-align:left; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="top">
                <h2>Dashboard</h2>
                <div><a class="btn" href="/logout">Logout</a></div>
            </div>

            <div class="layout">
                <div class="sidebar">
                    <h3>Navigation</h3>
                    <span class="tab active" data-tab="tab-chat">💬 Community Chat</span>
                    <span class="tab" data-tab="tab-raffle">🎟️ Verlosung</span>
                    <span class="tab" data-tab="tab-snake">🐍 Snake</span>
                    <p class="muted" style="margin-top:8px;">Hallo, {session.get("name","")}</p>
                </div>

                <div id="main">
                    <!-- Community Chat Panel -->
                    <div class="panel" id="tab-chat">
                        <h2>Community-Chat</h2>
                        <p class="tag">Admins sehen den Chat hier net. Aber die Mods in Yaruks Keller schon</p>
                        <div id="chat-messages"></div>
                        <div style="display:flex; gap:6px;">
                            <input type="text" id="chat-input" placeholder="Nachricht eingeben">
                            <button onclick="sendMessage()">Senden</button>
                        </div>
                    </div>

                    <!-- Verlosung Panel -->
                    <div class="panel" id="tab-raffle" style="display:none;">
                        <h2>Verlosung</h2>
                        <p id="raffle-status" class="tag">Status wird geladen…</p>
                        <div style="display:flex; gap:8px; flex-wrap:wrap; margin-top:8px;">
                            <button id="btn-join" onclick="raffleJoin()">Teilnehmen</button>
                            <button id="btn-leave" onclick="raffleLeave()">Austragen</button>
                        </div>
                    </div>

                    <!-- Snake Panel -->
                    <div class="panel" id="tab-snake" style="display:none;">
                        <h2>Snake</h2>
                        <canvas id="snake" width="400" height="400"></canvas>
                        <div style="display:flex; gap:8px; margin-bottom:10px;">
                            <button onclick="startSnake()">Start</button>
                            <span id="snake-score" class="tag">Score: 0</span>
                        </div>
                        <h3>Leaderboard (Top 10)</h3>
                        <table id="snake-leader"><thead><tr><th>#</th><th>User</th><th>Score</th><th>Datum</th></tr></thead><tbody></tbody></table>
                    </div>
                </div>
            </div>
        </div>

        <script src="https://cdn.socket.io/4.6.1/socket.io.min.js"></script>
        <script>
            // Tabs
            document.querySelectorAll('.tab').forEach(t => {{
                t.addEventListener('click', () => {{
                    document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
                    t.classList.add('active');
                    document.querySelectorAll('.panel').forEach(p=>p.style.display='none');
                    document.getElementById(t.dataset.tab).style.display='block';
                    if(t.dataset.tab==='tab-raffle') updateRaffleStatus();
                    if(t.dataset.tab==='tab-snake') loadLeaderboard();
                }});
            }});

            const socket = io();
            socket.on("new_message", (data) => {{
                if (data.channel !== 'community') return;
                const container = document.getElementById("chat-messages");
                const time = new Date(data.timestamp * 1000).toLocaleTimeString();
                const tierClass = data.tier || "tier-default";
                const fx = data.namefx || "";
                const titleAttr = (data.role === 'admin' && data.email) ? ` title="${{data.email}}"` : "";
                container.innerHTML += `<p><b>[${{time}}] <span class="name ${{tierClass}} ${{fx}}"${{titleAttr}}>${{data.user}}</span>:</b> ${{data.message}}</p>`;
                container.scrollTop = container.scrollHeight;
            }});

            function sendMessage() {{
                const input = document.getElementById("chat-input");
                const message = input.value.trim();
                if(message) {{
                    socket.emit("send_message", {{message, channel:'community'}});
                    input.value = "";
                }}
            }}
            function loadCommunityChat() {{
                fetch("/chat_history/community").then(r=>r.json()).then(list => {{
                    const container = document.getElementById("chat-messages");
                    container.innerHTML = "";
                    list.forEach(data => {{
                        const time = new Date(data.timestamp * 1000).toLocaleTimeString();
                        const tierClass = data.tier || "tier-default";
                        const fx = data.namefx || "";
                        const titleAttr = (data.role === 'admin' && data.email) ? ` title="${{data.email}}"` : "";
                        container.innerHTML += `<p><b>[${{time}}] <span class="name ${{tierClass}} ${{fx}}"${{titleAttr}}>${{data.user}}</span>:</b> ${{data.message}}</p>`;
                    }});
                    container.scrollTop = container.scrollHeight;
                }});
            }}


            window.onload = () => {{
                loadCommunityChat();
            }};


            // --- Verlosung ---
            function updateRaffleStatus() {{
                fetch('/raffle_status').then(r=>r.json()).then(d=>{{
                    const s = document.getElementById('raffle-status');
                    s.innerText = d.participating ? "Du nimmst an der Verlosung teil." : "Du nimmst derzeit nicht teil.";
                }});
            }}
            function raffleJoin() {{ fetch('/raffle_join', {{method:'POST'}}).then(updateRaffleStatus); }}
            function raffleLeave() {{ fetch('/raffle_leave', {{method:'POST'}}).then(updateRaffleStatus); }}

            // --- Snake ---
            let snakeTimer=null, dir='right', snakeBody=[], food=null, score=0, grid=20;
            function startSnake() {{
                const c = document.getElementById('snake');
                const ctx = c.getContext('2d');
                snakeBody=[{{x:4,y:4}}]; dir='right'; score=0; updateScore();
                spawnFood();
                if(snakeTimer) clearInterval(snakeTimer);
                snakeTimer = setInterval(()=>{{
                    // move
                    const head = {{...snakeBody[0]}};
                    if(dir==='right') head.x++; else if(dir==='left') head.x--; else if(dir==='up') head.y--; else if(dir==='down') head.y++;
                    // wrap
                    const cols=c.width/grid, rows=c.height/grid;
                    head.x=(head.x+cols)%cols; head.y=(head.y+rows)%rows;
                    // collision with self
                    if(snakeBody.some((s,i)=>i>0 && s.x===head.x && s.y===head.y)) {{ endSnake(); return; }}
                    snakeBody.unshift(head);
                    // eat
                    if(food && head.x===food.x && head.y===food.y) {{ score+=10; updateScore(); spawnFood(); }}
                    else snakeBody.pop();
                    // draw
                    ctx.clearRect(0,0,c.width,c.height);
                    ctx.fillRect(food.x*grid, food.y*grid, grid-2, grid-2);
                    snakeBody.forEach(p=>ctx.fillRect(p.x*grid, p.y*grid, grid-2, grid-2));
                }}, 120);
            }}
            function spawnFood() {{
                const c = document.getElementById('snake');
                const cols=c.width/grid, rows=c.height/grid;
                food={{x: Math.floor(Math.random()*cols), y: Math.floor(Math.random()*rows)}};
            }}
            function endSnake() {{
                if(snakeTimer) clearInterval(snakeTimer);
                submitScore(score);
                alert('Game Over! Score: '+score);
            }}
            function updateScore() {{ document.getElementById('snake-score').innerText = 'Score: '+score; }}
            document.addEventListener('keydown', (e)=>{{
                if(e.key==='ArrowUp' && dir!=='down') dir='up';
                else if(e.key==='ArrowDown' && dir!=='up') dir='down';
                else if(e.key==='ArrowLeft' && dir!=='right') dir='left';
                else if(e.key==='ArrowRight' && dir!=='left') dir='right';
            }});
            function submitScore(sc) {{
                fetch('/snake_score', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{score: sc}})}}).then(loadLeaderboard);
            }}
            function loadLeaderboard() {{
                fetch('/snake_leaderboard').then(r=>r.json()).then(list=>{{
                    const tbody=document.querySelector('#snake-leader tbody');
                    tbody.innerHTML='';
                    list.forEach((row,idx)=>{{
                        const dt=new Date(row.timestamp*1000).toLocaleString();
                        tbody.innerHTML += `<tr><td>${{idx+1}}</td><td>${{row.username}}</td><td>${{row.score}}</td><td>${{dt}}</td></tr>`;
                    }});
                }});
            }}
        </script>
    </body>
    </html>
    """

# --- Logout ---
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# --- Socket.IO Chat (mit Kanal) ---
@socketio.on("send_message")
def handle_send_message(data):
    user = session.get("name", "User")
    msg = (data.get("message") or "").strip()
    channel = (data.get("channel") or "community").strip()  # 'admin' oder 'community'
    if not msg:
        return
    timestamp = int(time.time())
    role = "admin" if session.get("is_admin") else "user"
    # email nur mitsenden, wenn Absender Admin ist (für Tooltip)
    email = session.get("email") if session.get("is_admin") else None
    tier = get_name_tier(user)
    fx = get_special_name_class(user)

    # Speichern je Kanal
    entry = {"user": user, "message": msg, "timestamp": timestamp, "role": role, "email": email, "tier": tier, "namefx": fx, "channel": channel}
    if channel == "admin":
        # nur Admins dürfen in Admin-Channel schreiben
        if not session.get("is_admin"):
            return
        admin_chat_messages.append(entry)
        save_admin_chat(admin_chat_messages)
    else:
        community_chat_messages.append(entry)
        save_community_chat(community_chat_messages)

    emit("new_message", entry, broadcast=True)

# ------------------- API Endpunkte -------------------
@app.route("/current_user")
def current_user():
    s = load_settings()
    return jsonify(name=session.get("name",""), email=session.get("email",""), is_admin=session.get("is_admin", False), theme=s.get("theme","dark"))

@app.route("/delete/<email>", methods=["POST"])
def delete_email(email):
    if not session.get("is_admin"):
        return jsonify(success=False), 403
    emails = load_emails()
    if email in emails:
        emails.remove(email)
        save_emails(emails)
    return jsonify(success=True)

@app.route("/delete_all", methods=["POST"])
def delete_all():
    if not session.get("is_admin"):
        return jsonify(success=False), 403
    save_emails([])
    save_ips([])
    return jsonify(success=True)

@app.route("/add", methods=["POST"])
def add_email():
    if not session.get("is_admin"):
        return jsonify(success=False), 403
    email = request.form["email"].strip()
    if not is_valid_email(email):
        return jsonify(success=False), 400
    emails = load_emails()
    if email not in emails:
        emails.append(email)
        save_emails(emails)
    return jsonify(success=True)

@app.route("/draw", methods=["GET"])
def draw_email():
    if not session.get("is_admin"):
        return jsonify(success=False), 403
    emails = load_emails()
    if not emails:
        return jsonify(winner=None)
    winner = random.choice(emails)
    # Gewinnerhistorie speichern
    wins = load_winners()
    wins.append({"email": winner, "timestamp": int(time.time())})
    save_winners(wins)
    return jsonify(winner=winner)

# --- Statistik ---
@app.route("/stats_data")
def stats_data():
    if not session.get("is_admin"):
        return jsonify({}), 403
    stats = {
        "participants": len(load_emails()),
        "ips": len(load_ips()),
        "chat_messages_admin": len(admin_chat_messages),
        "chat_messages_community": len(community_chat_messages),
        "suggestions": len(load_suggestions()),
        "draws": len(load_winners()),
        "last_draw": (load_winners()[-1]["timestamp"] if load_winners() else None)
    }
    return jsonify(stats)

# --- Gewinner-Historie ---
@app.route("/winners_history")
def winners_history():
    if not session.get("is_admin"):
        return jsonify([]), 403
    return jsonify(load_winners())

# --- Einstellungen ---
@app.route("/settings")
def get_settings():
    if not session.get("is_admin"):
        return jsonify({}), 403
    return jsonify(load_settings())

@app.route("/update_settings", methods=["POST"])
def update_settings():
    if not session.get("is_admin"):
        return jsonify({}), 403
    data = request.get_json(force=True)
    s = load_settings()
    maxp = int(data.get("max_participants", 0))
    theme = data.get("theme", "dark")
    if theme not in ("dark","light"):
        theme = "dark"
    s["max_participants"] = max(0, maxp)
    s["theme"] = theme
    save_settings(s)
    return jsonify(s)

# --- Vorschläge ---
@app.route("/suggestions")
def get_suggestions():
    if not session.get("is_admin"):
        return jsonify([]), 403
    # Nur Tangy darf die Liste sehen
    if session.get("name") != "Tangy":
        return jsonify([])
    return jsonify(load_suggestions())

@app.route("/send_suggestion", methods=["POST"])
def send_suggestion():
    if not session.get("is_admin"):
        return jsonify({"ok": False}), 403
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False}), 400
    lst = load_suggestions()
    lst.append({"user": session.get("name","Admin"), "text": text, "timestamp": int(time.time())})
    save_suggestions(lst)
    return jsonify({"ok": True})

# --- Cookie ---
@app.route("/cookie_click", methods=["POST"])
def cookie_click():
    if not session.get("is_admin"):
        return jsonify({"ok": False}), 403
    user = session.get("name","Admin")
    d = load_cookie_clicks()
    d[user] = d.get(user, 0) + 1
    save_cookie_clicks(d)
    return jsonify({"ok": True, "clicks": d[user]})

@app.route("/cookie_admin")
def cookie_admin():
    # Nur Tangy darf verwalten
    if not session.get("is_admin") or session.get("name") != "Tangy":
        return jsonify([]), 403
    d = load_cookie_clicks()
    data = [{"username": k, "clicks": v} for k,v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
    return jsonify(data)

@app.route("/update_cookie_clicks", methods=["POST"])
def update_cookie_clicks():
    if not session.get("is_admin") or session.get("name") != "Tangy":
        return jsonify({"error": "no access"}), 403
    data = request.get_json(force=True)
    username = data.get("username")
    clicks = int(data.get("clicks", 0))
    d = load_cookie_clicks()
    if username:
        d[username] = max(0, clicks)
        save_cookie_clicks(d)
    return jsonify({"status": "ok"})

# --- Admin-E-Mails (nur Tangy & Yaruk) ---
@app.route("/admin_emails")
def admin_emails():
    if not session.get("is_admin") or session.get("name") not in ("Tangy", "Yaruk"):
        return jsonify([]), 403
    extra = load_admin_emails()
    result = []
    # eingebaute
    for em, nm in ADMINS.items():
        result.append({"email": em, "name": nm, "builtin": True})
    # zusätzliche
    for em, nm in extra.items():
        # falls Kollision mit builtin -> als builtin markieren
        result.append({"email": em, "name": nm, "builtin": em in ADMINS})
    # eindeutige Liste
    seen = set()
    uniq = []
    for item in result:
        if item["email"] in seen: continue
        seen.add(item["email"])
        uniq.append(item)
    return jsonify(uniq)

@app.route("/add_admin_email", methods=["POST"])
def add_admin_email():
    if not session.get("is_admin") or session.get("name") not in ("Tangy", "Yaruk"):
        return jsonify({"error": "no access"}), 403
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    name = (data.get("name") or "").strip() or (email.split("@")[0] if "@" in email else "Admin")
    if not is_valid_email(email):
        return jsonify({"error":"invalid email"}), 400
    extra = load_admin_emails()
    if email in ADMINS:
        # eingebaute Admins sind immer vorhanden – nur Name nicht überschreiben
        return jsonify({"ok": True})
    extra[email] = name
    save_admin_emails(extra)
    return jsonify({"ok": True})

@app.route("/remove_admin_email", methods=["POST"])
def remove_admin_email():
    if not session.get("is_admin") or session.get("name") not in ("Tangy", "Yaruk"):
        return jsonify({"error": "no access"}), 403
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    if email in ADMINS:
        return jsonify({"error":"builtin cannot be removed"}), 400
    extra = load_admin_emails()
    if email in extra:
        del extra[email]
        save_admin_emails(extra)
    return jsonify({"ok": True})

# --- Admin Passwort zurücksetzen (nur Tangy) ---
@app.route("/reset_admin_password", methods=["POST"])
def reset_admin_password():
    if not session.get("is_admin") or session.get("name") != "Tangy":
        return jsonify({"error":"no access"}), 403
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip()
    if not email:
        return jsonify({"error":"Gib ne fucking E-Mail aus der Liste ein"}), 400
    # nur Admin-Passwörter zurücksetzbar
    all_admins = get_all_admins()
    if email not in all_admins:
        return jsonify({"error":"Gib ne fucking E-Mail aus der Liste ein"}), 400
    pw = load_admin_passwords()
    if email in pw:
        del pw[email]
        save_admin_passwords(pw)
    return jsonify({"ok": True})

# --- Verlosung: User selbst verwalten ---
@app.route("/raffle_status")
def raffle_status():
    if not session.get("email"):
        return jsonify({"participating": False})
    emails = load_emails()
    return jsonify({"participating": session.get("email") in emails})

@app.route("/raffle_join", methods=["POST"])
def raffle_join():
    if not session.get("email"):
        return jsonify({"ok": False}), 403
    emails = load_emails()
    if session["email"] not in emails:
        emails.append(session["email"])
        save_emails(emails)
    return jsonify({"ok": True})

@app.route("/chat_history/<channel>")
def chat_history(channel):
    if channel == "admin":
        if not session.get("is_admin"):
            return jsonify([]), 403
        return jsonify(load_admin_chat())
    elif channel == "community":
        return jsonify(load_community_chat())
    else:
        return jsonify([]), 400

@app.route("/raffle_leave", methods=["POST"])
def raffle_leave():
    if not session.get("email"):
        return jsonify({"ok": False}), 403
    emails = load_emails()
    if session["email"] in emails:
        emails.remove(session["email"])
        save_emails(emails)
    return jsonify({"ok": True})

# --- Snake Leaderboard ---
@app.route("/snake_leaderboard")
def snake_leaderboard():
    lst = load_json(SNAKE_SCORES_FILE, [])
    # Top 10
    top = sorted(lst, key=lambda x: (-int(x.get("score",0)), -int(x.get("timestamp",0))))[:10]
    return jsonify(top)

@app.route("/snake_score", methods=["POST"])
def snake_score():
    if not session.get("email"):
        return jsonify({"ok": False}), 403
    data = request.get_json(force=True)
    score = int(data.get("score", 0))
    if score < 0: score = 0
    lst = load_json(SNAKE_SCORES_FILE, [])
    username = session.get("name","User")
    lst.append({"username": username, "score": score, "timestamp": int(time.time())})
    save_json(SNAKE_SCORES_FILE, lst)
    return jsonify({"ok": True})


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)


