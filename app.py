import os
import re
import random
from difflib import get_close_matches

from rapidfuzz import fuzz, process
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

# Simple memory
LAST_TOPIC = None
LAST_PAGE = None


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

    print("[INFO] Training data loaded.")
    print(f"  Topics: {len(TOPIC_CONTENT)}")
    print(f"  Synonyms: {len(SYNONYMS)}")
    print(f"  Keywords: {len(KEYWORDS)}")
    print(f"  Nav pages: {len(NAV_PAGES)}")
    print(f"  FAQs: {len(FAQ_LIST)}")


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
        if not line:
            continue

        if ":" in line:
            left, right = line.split(":", 1)
            canonical = to_topic_key(left)
            for syn in re.split(r"[;,/]", right):
                syn = syn.strip()
                if syn:
                    SYNONYMS[to_topic_key(syn)] = canonical
        elif "=" in line:
            parts = [p.strip() for p in line.split("=") if p.strip()]
            if not parts:
                continue
            canonical = to_topic_key(parts[0])
            for syn in parts:
                SYNONYMS[to_topic_key(syn)] = canonical


def process_keywords_file(text: str):
    """
    Format:
        Annual Leave Policy : holiday, vacation, annual leave
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        topic_raw, kw_raw = line.split(":", 1)
        topic_key = to_topic_key(topic_raw)
        if topic_key not in TOPIC_CONTENT:
            continue

        for kw in re.split(r"[;,/]", kw_raw):
            kw = normalise_text(kw)
            if not kw:
                continue
            KEYWORDS.setdefault(kw, set()).add(topic_key)


def process_navigation_file(text: str):
    """
    Format:
        Page Name | https://sharepoint/site/page
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        name, url = [part.strip() for part in line.split("|", 1)]
        key = to_topic_key(name)
        NAV_PAGES[key] = {"name": name.strip(), "url": url.strip()}


def process_faq_file(text: str, base_name: str):
    """
    Format:
        Q: ... ?
        A: ...answer...

    Separated by blank lines.
    """
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue

        question = ""
        answer_lines = []
        for l in lines:
            if l.lower().startswith("q:"):
                question = l[2:].strip()
            elif l.lower().startswith("a:"):
                answer_lines.append(l[2:].strip())
            else:
                answer_lines.append(l)

        if question and answer_lines:
            FAQ_LIST.append(
                {
                    "q": question,
                    "a": "\n".join(answer_lines).strip(),
                    "topic": to_topic_key(base_name),
                }
            )


# ============================================================
# 4. SEARCH / MATCHING UTILITIES (NO ML, JUST SMART FUZZY)
# ============================================================

def expand_query_with_synonyms(msg: str) -> str:
    """
    If a synonym word/phrase is in the message, append its canonical form
    to improve matching.
    """
    msg_norm = normalise_text(msg)
    extra = []
    for syn, canonical in SYNONYMS.items():
        if syn in msg_norm and canonical not in msg_norm:
            extra.append(canonical)
    if extra:
        return msg + " " + " ".join(extra)
    return msg


def keyword_score(msg_norm: str, topic_key: str) -> float:
    """Score based on how many keywords linked to this topic appear."""
    score = 0.0
    for kw, topics in KEYWORDS.items():
        if topic_key in topics and kw in msg_norm:
            score += 0.4
    return score


def fuzzy_topic_score(msg: str, topic_key: str) -> float:
    """Fuzzy similarity between message and topic name/preview content."""
    title = TOPIC_DISPLAY.get(topic_key, "")
    body = TOPIC_CONTENT.get(topic_key, "")
    preview = body[:400]

    t_score = fuzz.partial_ratio(msg, title)
    c_score = fuzz.partial_ratio(msg, preview)

    return max(t_score, c_score) / 100.0


def hybrid_topic_rank(msg: str):
    """
    Combine:
      - fuzzy score on title/content
      - keyword score
      - close match on topic key
    Return list of (topic_key, score) sorted high → low.
    """
    msg = expand_query_with_synonyms(msg)
    msg_norm = normalise_text(msg)

    ranked = []

    for topic_key in TOPIC_CONTENT:
        # Fuzzy
        f_score = fuzzy_topic_score(msg, topic_key)

        # Keywords
        k_score = keyword_score(msg_norm, topic_key)

        # Close match on the topic ID itself
        close = get_close_matches(msg_norm, [topic_key], n=1, cutoff=0.8)
        c_score = 0.4 if close else 0.0

        total = f_score + k_score + c_score
        if total > 0:
            ranked.append((topic_key, total))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:5]


def detect_navigation(msg: str):
    """Return the best matching navigation page (if any)."""
    if not NAV_PAGES:
        return None

    msg_norm = normalise_text(msg)
    candidates = []
    for key, page in NAV_PAGES.items():
        name = page["name"]
        score = fuzz.partial_ratio(msg_norm, normalise_text(name)) / 100.0
        candidates.append((page, score))

    candidates.sort(key=lambda x: x[1], reverse=True)
    if candidates and candidates[0][1] >= 0.7:
        return candidates[0][0]
    return None


def detect_faq(msg: str):
    """Return best matching FAQ answer if high enough similarity."""
    if not FAQ_LIST:
        return None

    questions = [faq["q"] for faq in FAQ_LIST]
    best = process.extractOne(msg, questions, scorer=fuzz.token_set_ratio)
    if not best:
        return None

    best_question, score, idx = best
    if score < 70:
        return None

    faq = FAQ_LIST[idx]
    answer = faq["a"]
    if faq.get("topic") and faq["topic"] in TOPIC_DISPLAY:
        title = TOPIC_DISPLAY[faq["topic"]]
        return f"**FAQ – {title}**\n\nQ: {faq['q']}\n\nA: {answer}"
    else:
        return f"**FAQ**\n\nQ: {faq['q']}\n\nA: {answer}"


# ============================================================
# 5. RESPONSE LOGIC
# ============================================================

def list_main_topics():
    if not TOPIC_DISPLAY:
        return "I don't have any topics loaded yet."
    titles = sorted(TOPIC_DISPLAY.values())
    bullet = "\n".join(f"• {t}" for t in titles)
    return "Here are the main topics I can help with:\n\n" + bullet


def generate_response(msg: str) -> str:
    global LAST_TOPIC, LAST_PAGE

    # Lazy-load training data once
    if not TOPIC_CONTENT:
        load_all_training_data()

    msg = msg.strip()
    if not msg:
        return "Please type something so I can help 😊"

    msg_lower = msg.lower()

    # Simple greetings / help
    if msg_lower in {"hi", "hello", "hey"}:
        return (
            "Hi! I’m your Schneider onboarding assistant 👋\n\n"
            "Ask me about topics like annual leave, onboarding pages, training, policies, "
            "or type **main topics** to see everything I know."
        )

    if "main topics" in msg_lower or "what can you do" in msg_lower:
        return list_main_topics()

    if "all pages" in msg_lower or "navigation" in msg_lower:
        if not NAV_PAGES:
            return "I don't have any SharePoint navigation pages configured yet."
        lines = [f"• {p['name']} – {p['url']}" for p in NAV_PAGES.values()]
        return "Here are the SharePoint pages I know about:\n\n" + "\n".join(lines)

    # Follow-up like "tell me more about that"
    if "that" in msg_lower and LAST_TOPIC and "about that" in msg_lower:
        title = TOPIC_DISPLAY.get(LAST_TOPIC, "that topic")
        body = TOPIC_CONTENT.get(LAST_TOPIC, "")
        return f"You previously asked about **{title}**:\n\n{body}"

    # Navigation detection
    nav = detect_navigation(msg)
    if nav:
        LAST_PAGE = nav
        return f"🧭 **{nav['name']}**\n{nav['url']}"

    # FAQ detection
    faq_ans = detect_faq(msg)
    if faq_ans:
        return faq_ans

    # Hybrid topic ranking
    ranked = hybrid_topic_rank(msg)

    if ranked and ranked[0][1] >= 1.0:  # confidence threshold
        topic_key = ranked[0][0]
        LAST_TOPIC = topic_key
        title = TOPIC_DISPLAY.get(topic_key, "That topic")
        body = TOPIC_CONTENT.get(topic_key, "")
        return f"📘 **{title}**\n\n{body}"

    # If unclear → suggest closest topics
    if ranked:
        suggestions = [TOPIC_DISPLAY[t[0]] for t in ranked]
        return (
            "I'm not fully sure what you meant 🤔\n\n"
            "Did you mean one of these?\n"
            + "\n".join(f"• {s}" for s in suggestions)
        )

    # Final fallback
    return (
        "I couldn’t confidently match your question.\n\n"
        "Try asking about a SharePoint page, topic, template, or regulation.\n"
        "Type **main topics** to see everything I can explain."
    )


# ============================================================
# 6. FLASK ROUTES
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def get_reply():
    data = request.get_json(force=True)
    reply = generate_response(data.get("message", ""))
    return jsonify({"reply": reply})


# ============================================================
# 7. LOCAL RUN
# ============================================================

if __name__ == "__main__":
    # For local testing; Render will use gunicorn via Procfile
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
