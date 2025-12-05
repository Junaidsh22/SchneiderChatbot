from flask import Flask, render_template, request, jsonify
import os
import re
import random
from difflib import get_close_matches

# Flask app
app = Flask(__name__)

DATA_FOLDER = "chatbot_data"


# -------------------------------------------------
# DATA LOADING
# -------------------------------------------------
def _normalise_display_name(filename_base: str) -> str:
    """Turn a filename like 'IPA Sharepoint FAQ' into a nice display name."""
    name = filename_base.replace("_", " ").replace("-", " ").strip()
    # Capitalise each word
    return " ".join(w.capitalize() for w in name.split())


def load_knowledge():
    """
    Load all .txt files from chatbot_data.

    Returns:
        topics: dict[topic_key -> content]
        display_names: dict[topic_key -> human-friendly name]
        synonyms: dict[alt_phrase -> canonical_topic_key]
        keywords: dict[keyword -> set(topic_keys)]
    """
    topics = {}
    display_names = {}
    synonyms = {}
    keywords = {}

    if not os.path.isdir(DATA_FOLDER):
        return topics, display_names, synonyms, keywords

    # First pass: load raw file contents
    raw_files = {}
    for filename in os.listdir(DATA_FOLDER):
        if not filename.lower().endswith(".txt"):
            continue

        path = os.path.join(DATA_FOLDER, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="latin-1") as f:
                content = f.read()

        base = filename[:-4]  # drop .txt
        topic_key = base.lower().strip()
        raw_files[topic_key] = content

    # Second pass: separate helper docs (synonyms/keywords) from real topics
    for topic_key, content in raw_files.items():
        display = _normalise_display_name(topic_key)
        lower_name = display.lower()

        # Synonyms file, e.g. "Synonyms & Alternative Terms"
        if "synonym" in lower_name:
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Expected format:
                #   MAIN TERM : synonym1, synonym2, synonym3
                parts = re.split(r"[:\-]", line, maxsplit=1)
                if len(parts) != 2:
                    continue

                canonical_raw, synonyms_raw = parts[0].strip(), parts[1].strip()
                canonical_key = canonical_raw.lower()

                for syn in re.split(r"[;,/]", synonyms_raw):
                    s = syn.strip().lower()
                    if not s:
                        continue
                    synonyms[s] = canonical_key

            continue  # do not treat this file as a topic

        # Keyword/tag file, e.g. "Keywords & Tags"
        if "keyword" in lower_name or "tag" in lower_name:
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Expected format:
                #   topic name : kw1, kw2, kw3
                parts = re.split(r"[:\-]", line, maxsplit=1)
                if len(parts) != 2:
                    continue

                topic_raw, kw_raw = parts[0].strip(), parts[1].strip()
                topic_key_for_kw = topic_raw.lower()

                for kw in re.split(r"[;,/]", kw_raw):
                    k = kw.strip().lower()
                    if not k:
                        continue
                    keywords.setdefault(k, set()).add(topic_key_for_kw)

            continue  # do not treat this file as a topic

        # Everything else is a regular topic file
        topics[topic_key] = content.strip()
        display_names[topic_key] = display

    return topics, display_names, synonyms, keywords


TOPICS, TOPIC_DISPLAY, SYNONYMS, KEYWORDS = load_knowledge()


# -------------------------------------------------
# INTENT DEFINITIONS
# -------------------------------------------------
INTENTS = {
    "greeting": [
        "hello", "hi", "hey",
        "good morning", "good afternoon", "good evening"
    ],
    "how_are_you": ["how are you", "how's it going", "how are u"],
    "thanks": ["thanks", "thank you", "cheers"],
    "capabilities": ["what can you do", "how can you help", "what do you do"],
    "identity": ["who are you", "what are you", "what is this"],
    "main_topics": ["main topics", "topics", "help", "what do you know"],
    "joke": ["joke", "funny", "make me laugh"],
}

JOKES = [
    "Why did the PLC go to therapy? Because it had too many unresolved inputs! 😄",
    "Why don't electricians ever get lost? They always follow the current. ⚡",
    "I'm reading a book on anti-gravity… it's impossible to put down! 📘",
]


# -------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------
def match_intent(message: str, intent_key: str) -> bool:
    """Return True if the message contains any phrase for this intent."""
    message = message.lower()
    return any(phrase in message for phrase in INTENTS.get(intent_key, []))


def list_topics_text() -> str:
    """Return a nicely formatted list of available topics."""
    if not TOPICS:
        return "I don't have any topics loaded yet. Please check the training data folder."

    lines = ["Here are some of the topics I can help with:\n"]
    for key in sorted(TOPIC_DISPLAY.keys()):
        lines.append(f"• {TOPIC_DISPLAY[key]}")
    return "\n".join(lines)


def detect_topic(message: str):
    """
    Try several strategies to map a user message to a topic key.

    Strategies (in order):
      1. Direct match on topic name
      2. Synonym match
      3. Keyword/tag match
      4. Extract phrase using patterns and fuzzy match
    """
    msg = message.lower()

    # 1. Direct mention of topic name or key
    direct_candidates = []
    for topic_key, disp in TOPIC_DISPLAY.items():
        simple_name = disp.lower()
        if simple_name in msg or topic_key in msg:
            direct_candidates.append(topic_key)
    if direct_candidates:
        # Prefer the longest match (more specific)
        direct_candidates.sort(key=len, reverse=True)
        return direct_candidates[0]

    # 2. Synonyms
    for syn_phrase, canonical in SYNONYMS.items():
        if syn_phrase in msg:
            # If we have a real topic with that canonical key, return it
            if canonical in TOPICS:
                return canonical
            # Otherwise try fuzzy match canonical against topics
            best = get_close_matches(canonical, list(TOPICS.keys()), n=1, cutoff=0.5)
            if best:
                return best[0]

    # 3. Keywords
    keyword_hits = {}
    for kw, topic_keys in KEYWORDS.items():
        if kw in msg:
            for t in topic_keys:
                keyword_hits[t] = keyword_hits.get(t, 0) + 1

    if keyword_hits:
        # pick topic with highest score
        best_topic = max(keyword_hits, key=keyword_hits.get)
        if best_topic in TOPICS:
            return best_topic

    # 4. Pattern-based fuzzy matching: "tell me about X", "where is X"
    patterns = [
        r"tell me about (.+)",
        r"what is (.+)",
        r"where is (.+)",
        r"where can i find (.+)",
        r"show me (.+)",
        r"explain (.+)",
        r"info about (.+)",
        r"information about (.+)",
    ]
    for p in patterns:
        m = re.search(p, msg)
        if m:
            phrase = m.group(1).strip().lower()
            if not phrase:
                continue
            # Fuzzy match against topic display names + keys + keywords
            candidates = list(TOPIC_DISPLAY.values()) + list(TOPICS.keys()) + list(KEYWORDS.keys())
            best = get_close_matches(phrase, candidates, n=1, cutoff=0.5)
            if best:
                match = best[0].lower()
                # Map back to topic key
                # 1) If it is already a key
                if match in TOPICS:
                    return match
                # 2) If it matches a display name
                for key, disp in TOPIC_DISPLAY.items():
                    if disp.lower() == match:
                        return key
                # 3) If it matches a keyword
                for kw, tset in KEYWORDS.items():
                    if kw == match:
                        for t in tset:
                            if t in TOPICS:
                                return t

    return None


# -------------------------------------------------
# MAIN CHATBOT LOGIC
# -------------------------------------------------
def generate_response(user_message: str) -> str:
    """Core conversation logic."""
    if not user_message or not user_message.strip():
        return "Please type a question or a keyword related to the IPA Hub or SharePoint."

    msg = user_message.strip()

    # 1. Intents
    if match_intent(msg, "greeting"):
        return "Hello 👋 I'm your IPA Hub Navigation Assistant. How can I help you today?"

    if match_intent(msg, "how_are_you"):
        return "I'm running at 100% uptime and ready to help ⚡"

    if match_intent(msg, "capabilities"):
        return (
            "I'm here to help you navigate the IPA SharePoint Hub.\n\n"
            "You can ask me things like:\n"
            "• 'Where do I find project templates?'\n"
            "• 'What is the purpose of the IPA Hub?'\n"
            "• 'Show me troubleshooting tips.'\n"
            "• 'Tell me about SharePoint best practices.'"
        )

    if match_intent(msg, "identity"):
        return (
            "I'm the IPA Hub Navigation Assistant for Schneider Electric.\n"
            "My job is to guide you around SharePoint pages, templates, tools and documentation."
        )

    if match_intent(msg, "joke"):
        return random.choice(JOKES)

    if match_intent(msg, "thanks"):
        return random.choice([
            "You're welcome! 😊",
            "Glad I could help!",
            "Anytime — just ask if you need anything else."
        ])

    if match_intent(msg, "main_topics"):
        return list_topics_text()

    # 2. Topic detection
    topic_key = detect_topic(msg)
    if topic_key and topic_key in TOPICS:
        title = TOPIC_DISPLAY.get(topic_key, topic_key.title())
        body = TOPICS[topic_key]
        return f"📘 {title}\n\n{body}"

    # 3. Hard-coded example for troubleshooting
    if "troubleshoot" in msg or "error" in msg or "issue" in msg:
        for key, disp in TOPIC_DISPLAY.items():
            if "troubleshooting" in disp.lower():
                return f"🛠 {disp}\n\n{TOPICS[key]}"

    # 4. Final fallback
    return (
        "I'm not completely sure how to answer that yet 🤔\n\n"
        "You can try:\n"
        "• Asking about a specific IPA SharePoint page\n"
        "• Typing 'main topics' to see what I know\n"
        "• Mentioning words like 'templates', 'navigation', 'best practices', or 'troubleshooting'"
    )


# -------------------------------------------------
# FLASK ROUTES
# -------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def get_route():
    data = request.get_json(force=True)
    user_msg = data.get("message", "")
    reply = generate_response(user_msg)
    return jsonify({"reply": reply})


if __name__ == "__main__":
    # For local testing
    app.run(debug=True)
