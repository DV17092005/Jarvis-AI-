"""Local, cross-platform actions that do not require an AI API."""

import datetime
import glob
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser

import jarvis_market


SITES = {
    "youtube": "https://www.youtube.com",
    "whatsapp": "https://web.whatsapp.com",
    "gmail": "https://mail.google.com",
    "google": "https://www.google.com",
    "github": "https://github.com",
    "maps": "https://maps.google.com",
    "calendar": "https://calendar.google.com",
    "drive": "https://drive.google.com",
}

ALIASES = {
    "vs code": "code",
    "visual studio code": "code",
    "chrome": "chrome",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "terminal": "wt",
    "spotify": "spotify",
    "notepad": "notepad",
    "calculator": "calc",
}

MAC_APP_ALIASES = {
    "vs code": "Visual Studio Code",
    "visual studio code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "word": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpoint": "Microsoft PowerPoint",
    "terminal": "Terminal",
}


def _open_url(url):
    return webbrowser.open_new_tab(url)


def _start_menu_shortcut(name):
    if sys.platform != "win32":
        return False
    roots = (
        os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
    )
    target = name.lower()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for shortcut in glob.iglob(os.path.join(root, "**", "*.lnk"), recursive=True):
            if target in os.path.basename(shortcut).lower():
                os.startfile(shortcut)
                return True
    return False


def _launch_app(name):
    app = ALIASES.get(name.lower().strip(), name).strip()
    executable = shutil.which(app)
    if executable:
        subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    if _start_menu_shortcut(name) or _start_menu_shortcut(app):
        return True
    if sys.platform == "darwin":
        mac_app = MAC_APP_ALIASES.get(name.lower().strip(), name)
        result = subprocess.run(["open", "-a", mac_app], capture_output=True, check=False)
        return result.returncode == 0
    if sys.platform.startswith("linux"):
        executable = shutil.which(app)
        if executable:
            subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    return False


def _set_volume(key):
    if sys.platform == "darwin":
        scripts = {
            "up": "set volume output volume ((output volume of (get volume settings)) + 15)",
            "down": "set volume output volume ((output volume of (get volume settings)) - 15)",
            "mute": "set volume with output muted",
        }
        return subprocess.run(["osascript", "-e", scripts[key]], capture_output=True).returncode == 0
    if sys.platform == "win32":
        import ctypes

        keys = {"up": 0xAF, "down": 0xAE, "mute": 0xAD}
        key = keys[key]
        ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        ctypes.windll.user32.keybd_event(key, 0, 2, 0)
        return True
    return False


def send_whatsapp_message(contact_name, message="Hello from Jarvis"):
    encoded_msg = urllib.parse.quote(message)
    _open_url(f"https://web.whatsapp.com/send?text={encoded_msg}")
    return (
        f"WhatsApp Web is open with a message ready for {contact_name}. "
        "Choose the contact and review it before sending."
    )


def get_mail_brief():
    cache_file = os.path.join(os.path.expanduser("~"), ".openjarvis", "mail_cache.txt")
    if os.path.isfile(cache_file):
        with open(cache_file, "r", encoding="utf-8", errors="replace") as cache:
            content = cache.read().strip()
        if content:
            return "Here is your latest mail briefing: " + content[:600]
    return (
        "Email is not connected yet. Jarvis has not accessed your inbox. "
        "You can open Gmail and review your messages there."
    )


def try_action(q):
    """Run a supported local action, or return None to pass the query to the AI."""
    q_clean = q.lower().strip(" .,!?")

    if any(k in q_clean for k in ("stock", "market", "nifty", "sensex", "crypto", "bitcoin", "buy or sell")):
        for symbol, name in jarvis_market.DEFAULT_TICKERS.items():
            if name.lower() in q_clean or symbol.lower().replace(".ns", "") in q_clean:
                data = jarvis_market.analyze_ticker(symbol)
                if data:
                    direction = "up" if data["pct_change"] >= 0 else "down"
                    return (
                        f"{data['name']} is trading at {data['currency']}{data['price']:,}, "
                        f"{direction} {abs(data['pct_change'])}%. "
                        f"Technical indicator: {data['signal']}. {data['reason']} "
                        "This is informational only, not financial advice."
                    )
                return f"I couldn't retrieve current market data for {name}. Please try again later."
        return "Here is the market overview: " + (jarvis_market.market_briefing() or "Market data is temporarily unavailable.")

    match = re.search(
        r"(?:send|reply|message)\s+(?:on\s+whatsapp\s+to|whatsapp\s+to|to)\s+(.+?)(?:\s+saying\s+(.+))?$",
        q_clean,
    )
    if "whatsapp" in q_clean and match:
        contact = match.group(1).strip()
        message = match.group(2).strip() if match.group(2) else "Hello from Jarvis."
        return send_whatsapp_message(contact, message)

    if q_clean in ("open whatsapp", "check whatsapp", "whatsapp"):
        return "Opening WhatsApp." if _open_url(SITES["whatsapp"]) else "I couldn't open WhatsApp Web."

    if any(k in q_clean for k in ("mail brief", "check mail", "read emails", "inbox summary", "unread emails")):
        return get_mail_brief()

    match = re.search(r"(?:play|search|find|open)\s+(.+?)\s+(?:on|in)\s+youtube", q_clean)
    if match:
        query = match.group(1).strip()
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        return f"Searching YouTube for {query}." if _open_url(url) else "I couldn't open YouTube."

    match = re.match(r"(?:search|google)(?: for)?\s+(.+)", q_clean)
    if match:
        query = match.group(1).strip()
        url = "https://www.google.com/search?q=" + urllib.parse.quote(query)
        return f"Searching Google for {query}." if _open_url(url) else "I couldn't open Google."

    match = re.match(r"(?:please\s+)?(?:open|launch|start)\s+(.+)", q_clean)
    if match:
        name = match.group(1).strip()
        if name in SITES:
            return f"Opening {name}." if _open_url(SITES[name]) else f"I couldn't open {name}."
        if _launch_app(name):
            return f"Opening {name}."
        return f"I couldn't find an application named {name}. Check that it's installed."

    if any(phrase in q_clean for phrase in ("volume up", "louder")):
        return "Volume increased." if _set_volume("up") else "Volume controls are unavailable on this system."
    if any(phrase in q_clean for phrase in ("volume down", "quieter")):
        return "Volume decreased." if _set_volume("down") else "Volume controls are unavailable on this system."
    if q_clean in ("mute", "mute volume", "mute the volume"):
        return "System audio muted." if _set_volume("mute") else "Volume controls are unavailable on this system."

    if "time" in q_clean:
        return "It is currently " + datetime.datetime.now().strftime("%I:%M %p")
    if "date" in q_clean or "today" in q_clean:
        return "Today is " + datetime.datetime.now().strftime("%A, %B %d, %Y")

    if q_clean in ("help", "what can you do", "commands"):
        return (
            "I can answer questions with a configured AI key, open apps and websites, search YouTube or Google, "
            "tell the time and date, adjust volume, and give market-data summaries."
        )

    return None
