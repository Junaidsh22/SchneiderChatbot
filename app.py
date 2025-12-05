import os
import re
import random
from difflib import get_close_matches

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ============================================================
# 1. GLOBAL CONFIG
# ============================================================

DATA_FOLDER = "chatbot_data"

# Main knowledge containers
TOPIC_CONTENT = {}        # topic_key -> full text
TOPIC_DISPLAY = {}        # topic_key -> nice title
SYNONYMS = {}             # phrase/synonym -> canonical topic_key or phrase
KEYWORDS = {}             # keyword -> set(topic_keys)
NAV_PAGES = {}            # page_key -> {"name": display_name, "url": link}
FAQ_LIST = []             # list of {"q": question, "a": answer, "topic": optional_topic_key}


# ============================================================
# 2. TEXT NORMALISATION HELPERS
# ============================================================

def normalise_text(text: str) -> str:
    """Lowercase + strip + remove extra spaces and punctuation for matching."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def to_topic_key(name: str) -> str:
    """Convert any name to a canonical topic key (used as dictionary key)."""
    return normalise_text(name)


# ============================================================
# 3. TRAINING DATA LOADING
# ============================================================

def load_all_training_data():
    """Load all .txt files from chatbot_data and dispatch to processors."""
    global TOPIC_CONTENT, TOPIC_DISPLAY, SYNONYMS, KEYWORDS, NAV_PAGES, FAQ_LIST

    TOPIC_CONTENT = {}
    TOPIC_DISPLAY = {}
    SYNONYMS = {}
    KEYWORDS = {}
    NAV_PAGES = {}
    FAQ_LIST = []

    if not os.path.isdir(DATA_FOLDER):
        print(f"[WARN] Training data folder '{DATA_FOLDER}' not found.")
        return

    for filename in os.listdir(DATA_FOLDER):
        if not filename.lower().endswith(".txt"):
            continue

        filepath = os.path.join(DATA_FOLDER, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(filepath, "r", encoding="latin-1") as f:
                content = f.read()

        base = filename[:-4].strip()  # drop .txt
        base_lower = base.lower()

        # Decide what type of file this is based on its name
        if "synonym" in base_lower:
            process_synonyms_file(content)
        elif "keyword" in base_lower or "tag" in base_lower:
            process_keywords_file(content)
        elif "faq" in base_lower:
            process_faq_file(content, base)
        elif "navigation" in base_lower or "list of all the pages" in base_lower:
            process_navigation_file(content)
        else:
            process_topic_file(base, content)


def process_topic_file(base_name: str, content: str):
    """Treat this file as a main topic."""
    key = to_topic_key(base_name)
    display = " ".join(w.capitalize() for w in base_name.replace("_", " ").split())
    TOPIC_CONTENT[key] = content.strip()
    TOPIC_DISPLAY[key] = display


def process_synonyms_file(text: str):
    """
    Expected formats (we support both):
        Working Time Regulations : working hours, hours of work
        wfh = working from home = remote working
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Try ":" or "-" style
        if ":" in line:
            left, right = line.split(":", 1)
            canonical = to_topic_key(left)
            for syn in re.split(r"[;,/]", right):
                s = to_topic_key(syn)
                if s:
                    SYNONYMS[s] = canonical
            continue

        # Try "=" style
        if "=" in line:
            parts = [p.strip() for p in line.split("=")]
            canonical = to_topic_key(parts[0])
            for syn in parts:
                s = to_topic_key(syn)
                if s:
                    SYNONYMS[s] = canonical


def process_keywords_file(text: str):
    """
    Expected format:
        Topic name : kw1, kw2, kw3
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if ":" not in line:
            continue

        topic_raw, kw_raw = line.split(":", 1)
        topic_key = to_topic_key(topic_raw)

        for kw in re.split(r"[;,/]", kw_raw):
            k = to_topic_key(kw)
            if not k:
                continue
            KEYWORDS.setdefault(k, set()).add(topic_key)


def process_navigation_file(text: str):
    """
    Parse navigation data: page names + URLs.
    Accepts patterns like:
        Governance Dashboard - https://...
        Templates Library: https://...
        Graduate Hub    https://...
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or "http" not in line:
            continue

        # Split at first 'http'
        before, after = line.split("http", 1)
        name = before.strip()
        url = "http" + after.strip()
        if not name or not url:
            continue

        key = to_topic_key(name)
        NAV_PAGES[key] = {"name": name.strip(), "url": url}


def process_faq_file(text: str, base_name: str):
    """
    Parse FAQ file, expecting blocks like:

        Q: Question text
        A: Answer text

    Multiple blocks allowed. Blank lines between are fine.
    """
    blocks = re.split(r"\bQ:", text, flags=re.IGNORECASE)
    for block in blocks:
        block = block.strip()
        if not block or "A:" not in block:
            continue
        q_raw, a_raw = re.split(r"\bA:", block, maxsplit=1, flags=re.IGNORECASE)
        q = q_raw.strip()
        a = a_raw.strip()
        if not q or not a:
            continue
        FAQ_LIST.append({
            "q": normalise_text(q),
            "a": a,
            "topic": to_topic_key(base_name)
        })


# Load once at startup
load_all_training_data()


# ============================================================
# 4. INTENTS & SMALL-TALK (from original GUI bot)
# ============================================================

INTENTS = {
    "greetings": [
        "hello", "hi", "hey", "good morning", "good afternoon", "good evening"
    ],
    "how_are_you": [
        "how are you", "how's it going", "how you doing", "whats up", "what's up"
    ],
    "capabilities": [
        "what can you do", "how can you help", "your features", "what are you capable of"
    ],
    "identity": [
        "who are you", "what are you", "introduce yourself"
    ],
    "joke": [
        "joke", "make me laugh", "funny"
    ],
    "topics": [
        "main topics", "documents", "training files", "help", "resources", "files", "what do you know"
    ],
    "thanks": [
        "thanks", "thank you", "cheers", "cool", "great", "awesome", "nice", "perfect"
    ],
}

JOKES = [
    "Why did the PLC go to therapy? Because it had too many unresolved inputs! 😄",
    "Why don't electricians ever get lost? Because they always follow the current! ⚡",
    "I'm reading a book on anti-gravity... it's impossible to put down! 📘",
]


def match_intent(message: str, intent_key: str) -> bool:
    message = message.lower()
    return any(phrase in message for phrase in INTENTS.get(intent_key, []))


# ============================================================
# 5. TOPIC / NAVIGATION / FAQ DETECTION
# ============================================================

TOPIC_EXTRACTION_PATTERNS = [
    r"tell me about (.+)",
    r"show me (.+)",
    r"give info on (.+)",
    r"give information on (.+)",
    r"what is (.+)",
    r"details on (.+)",
    r"info about (.+)",
    r"information about (.+)",
    r"explain (.+)",
    r"(.+) info",
    r"where is (.+)",
    r"where can i find (.+)",
    r"how do i get to (.+)",
]

def extract_candidate_phrase(message: str) -> str | None:
    """Extract 'topic phrase' from natural language questions."""
    msg = message.lower()
    for pattern in TOPIC_EXTRACTION_PATTERNS:
        m = re.search(pattern, msg)
        if m:
            phrase = m.group(1).strip()
            if phrase:
                return phrase
    return None


def expand_with_synonyms(text: str) -> str:
    """Replace known synonyms in the text with canonical forms."""
    tokens = normalise_text(text).split()
    rebuilt = []
    for t in tokens:
        tk = to_topic_key(t)
        if tk in SYNONYMS:
            rebuilt.append(SYNONYMS[tk])
        else:
            rebuilt.append(tk)
    return " ".join(rebuilt)


def score_topic_against_text(topic_key: str, text: str) -> float:
    """
    Lightweight scoring: direct mention, keyword overlap, similarity.
    """
    score = 0.0
    text_norm = normalise_text(text)
    topic_norm = topic_key

    # Direct mention in text
    if topic_norm in text_norm:
        score += 3.0

    # Display name mention
    display = TOPIC_DISPLAY.get(topic_key, "").lower()
    if display and display in text_norm:
        score += 3.0

    # Keywords
    for kw, tset in KEYWORDS.items():
        if topic_key in tset and kw in text_norm:
            score += 1.5

    # Simple token overlap
    text_tokens = set(text_norm.split())
    topic_tokens = set(topic_norm.split())
    overlap = len(text_tokens & topic_tokens)
    score += overlap * 0.7

    return score


def detect_topic(message: str) -> str | None:
    """Return the best topic key for the message, or None."""
    if not TOPIC_CONTENT:
        return None

    candidate_phrase = extract_candidate_phrase(message)
    text_for_scoring = candidate_phrase if candidate_phrase else message

    text_for_scoring = expand_with_synonyms(text_for_scoring)

    best_topic = None
    best_score = 0.0

    for topic_key in TOPIC_CONTENT.keys():
        s = score_topic_against_text(topic_key, text_for_scoring)
        if s > best_score:
            best_score = s
            best_topic = topic_key

    # Simple threshold to avoid random matches
    if best_score >= 1.5:
        return best_topic
    return None


def detect_navigation(message: str) -> dict | None:
    """
    Detect if the user wants a specific SharePoint page.
    Returns NAV_PAGES entry, or None.
    """
    if not NAV_PAGES:
        return None

    msg = normalise_text(message)
    candidate_phrase = extract_candidate_phrase(message)
    search_text = candidate_phrase.lower() if candidate_phrase else msg

    # Try fuzzy match against page keys and names
    keys = list(NAV_PAGES.keys())
    names = [normalise_text(v["name"]) for v in NAV_PAGES.values()]
    all_candidates = keys + names

    best = get_close_matches(search_text, all_candidates, n=1, cutoff=0.6)
    if not best:
        return None

    match = best[0]

    # Map match back to NAV_PAGES entry
    if match in NAV_PAGES:
        return NAV_PAGES[match]

    for key, info in NAV_PAGES.items():
        if normalise_text(info["name"]) == match:
            return info

    return None


def detect_faq(message: str) -> str | None:
    """
    Try to match the question to a FAQ Q: line.
    """
    if not FAQ_LIST:
        return None

    msg_norm = normalise_text(message)

    # First try exact / substring matches
    for entry in FAQ_LIST:
        q_norm = entry["q"]
        if q_norm in msg_norm or msg_norm in q_norm:
            return entry["a"]

    # Then simple fuzzy match
    q_texts = [e["q"] for e in FAQ_LIST]
    best = get_close_matches(msg_norm, q_texts, n=1, cutoff=0.6)
    if best:
        for entry in FAQ_LIST:
            if entry["q"] == best[0]:
                return entry["a"]

    return None


def list_all_topics() -> str:
    if not TOPIC_CONTENT:
        return "I don't have any topics loaded yet. Please check the training data folder."
    lines = ["Here are some of the main topics I know:\n"]
    for key in sorted(TOPIC_DISPLAY.keys()):
        lines.append(f"• {TOPIC_DISPLAY[key]}")
    return "\n".join(lines)


# ============================================================
# 6. MAIN CONVERSATION ENGINE
# ============================================================

def generate_response(user_message: str) -> str:
    if not user_message or not user_message.strip():
        return "Please type a question related to the IPA Hub or SharePoint, and I'll do my best to help."

    msg = user_message.strip()

    # ---------- Intents / Small talk ----------
    if match_intent(msg, "greetings"):
        return random.choice([
            "Hey there! 👋 Ready to explore the IPA Hub together?",
            "Hi! I'm your IPA Hub Navigation Assistant ⚡",
            "Hello! How can I help you find your way around today?"
        ])

    if match_intent(msg, "how_are_you"):
        return "I'm fully charged and ready to help ⚡ How can I support you today?"

    if match_intent(msg, "capabilities"):
        return (
            "I'm here to help you navigate the IPA SharePoint Hub.\n\n"
            "You can ask me things like:\n"
            "• 'Where do I find project templates?'\n"
            "• 'Show me troubleshooting tips.'\n"
            "• 'What does the Governance page do?'\n"
            "• 'Explain the Working Time Regulations.'"
        )

    if match_intent(msg, "identity"):
        return (
            "I'm the IPA Hub Navigation Assistant for Schneider Electric 🤖.\n"
            "Think of me as your friendly guide to SharePoint pages, templates, tools, FAQs and best practices."
        )

    if match_intent(msg, "joke"):
        return random.choice(JOKES)

    if match_intent(msg, "topics"):
        return list_all_topics()

    if match_intent(msg, "thanks"):
        return random.choice([
            "You're very welcome! 😊",
            "Anytime — I'm here to help ⚡",
            "Glad I could help. Ask away if you need anything else!"
        ])

    # ---------- Navigation first (to catch 'where is', 'open', etc.) ----------
    nav_hit = detect_navigation(msg)
    if nav_hit:
        return (
            f"🧭 Here is the page you're looking for:\n\n"
            f"**{nav_hit['name']}**\n{nav_hit['url']}"
        )

    # ---------- FAQs ----------
    faq_answer = detect_faq(msg)
    if faq_answer:
        return faq_answer

    # ---------- Topic content ----------
    topic_key = detect_topic(msg)
    if topic_key and topic_key in TOPIC_CONTENT:
        title = TOPIC_DISPLAY.get(topic_key, topic_key.title())
        body = TOPIC_CONTENT[topic_key]
        return f"📘 {title}\n\n{body}"

    # ---------- Last-resort fallback ----------
    return (
        "I'm not completely sure how to answer that yet 🤔\n\n"
        "You can try:\n"
        "• Asking about a specific IPA SharePoint page (e.g. 'Where is the Graduate Hub?')\n"
        "• Typing 'main topics' to see what I know\n"
        "• Using keywords like 'templates', 'navigation', 'governance', 'best practices', or 'troubleshooting'\n\n"
        "If you're stuck, you can also contact junaid.sheikh@se.com for further help."
    )


# ============================================================
# 7. FLASK ROUTES
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def get_route():
    data = request.get_json(force=True)
    user_msg = data.get("message", "")
    reply = generate_response(user_msg)
    return jsonify({"reply": reply})


# ============================================================
# 8. LOCAL DEV ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    # Run locally with: python app.py
    app.run(host="0.0.0.0", port=5000, debug=True)
