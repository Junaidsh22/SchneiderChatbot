import os
import re
from difflib import get_close_matches

from rapidfuzz import fuzz, process
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# ============================================================
# GLOBAL DATA / STATE
# ============================================================

DATA_FOLDER = "chatbot_data"

TOPIC_CONTENT = {}        # topic_key -> full text
TOPIC_DISPLAY = {}        # topic_key -> nice title
SYNONYMS = {}             # synonym/alt phrase -> canonical phrase or topic key
KEYWORDS = {}             # keyword -> set(topic_keys)
NAV_PAGES = {}            # topic_key -> {"name": display_name, "url": link}
FAQ_LIST = []             # list of {"q": question, "a": answer, "topic": optional_topic_key}

LAST_TOPIC = None         # remember last topic we answered about
LAST_PAGE = None          # remember last navigation page


# ============================================================
# TEXT UTILS
# ============================================================

def normalise_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def to_topic_key(name: str) -> str:
    return normalise_text(name)


# ============================================================
# BUILT-IN SYNONYMS & INTENT DEFINITIONS
# ============================================================

# Safety net synonyms in case the Synonyms file doesn’t cover something.
# These are generic, HR-safe and only help the routing, not the content.
BUILTIN_SYNONYMS = {
    "holiday": "annual leave",
    "holidays": "annual leave",
    "vacation": "annual leave",
    "pto": "annual leave",
    "time off": "annual leave",
    "working hours": "normal working hours",
    "hours of work": "normal working hours",
    "start time": "normal working hours",
    "finish time": "normal working hours",
}

# Intents = “I know exactly what the user is asking”.
# These trigger special HR-safe answers.
INTENT_PATTERNS = [
    {
        "name": "annual_leave",
        "keywords": ["annual leave", "holiday", "holidays", "vacation", "time off", "pto"],
        "question_triggers": ["how many", "how much", "entitlement", "days", "holiday allowance"],
    },
    {
        "name": "working_hours",
        "keywords": ["working hours", "hours of work", "normal working hours"],
        "question_triggers": ["what is", "what are", "normal", "standard"],
    },
]


# ============================================================
# TRAINING DATA LOADING
# ============================================================

def load_all_training_data():
    """Load all .txt training files from chatbot_data."""
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

        path = os.path.join(DATA_FOLDER, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(path, "r", encoding="latin-1") as f:
                content = f.read()

        base = filename[:-4].strip()
        base_lower = base.lower()

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

    # Merge in builtin synonyms if not already defined
    for syn, canonical in BUILTIN_SYNONYMS.items():
        if syn not in SYNONYMS:
            SYNONYMS[syn] = canonical

    print("[INFO] Training data loaded.")
    print(f"  Topics: {len(TOPIC_CONTENT)}")
    print(f"  Synonyms: {len(SYNONYMS)}")
    print(f"  Keywords: {len(KEYWORDS)}")
    print(f"  Nav pages: {len(NAV_PAGES)}")
    print(f"  FAQs: {len(FAQ_LIST)}")


def process_topic_file(base_name: str, content: str):
    key = to_topic_key(base_name)
    display = " ".join(w.capitalize() for w in base_name.replace("_", " ").split())
    TOPIC_CONTENT[key] = content.strip()
    TOPIC_DISPLAY[key] = display


def process_synonyms_file(text: str):
    """
    Supported formats:
        Annual Leave : holiday, vacation, time off
        WTR = working time regulations = working hours
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
        Working Time Regulations : annual leave, working hours, overtime
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        topic_raw, kw_raw = line.split(":", 1)
        topic_key = to_topic_key(topic_raw)
        if topic_key not in TOPIC_CONTENT:
            continue  # only bind to topics that actually exist
        for kw in re.split(r"[;,/]", kw_raw):
            kw = normalise_text(kw)
            if not kw:
                continue
            KEYWORDS.setdefault(kw, set()).add(topic_key)


def process_navigation_file(text: str):
    """
    Example line:
        Working Time Regulations page http://sharepoint/link
    """
    for line in text.splitlines():
        if "http" not in line:
            continue
        before, after = line.split("http", 1)
        name = before.strip()
        url = "http" + after.strip()
        if name and url:
            key = to_topic_key(name)
            NAV_PAGES[key] = {"name": name, "url": url}


def process_faq_file(text: str, base_name: str):
    """
    Format example:

        Q: What is the purpose of SharePoint in Schneider Electric?
        A: Its purpose is to centralize resources and improve collaboration.

    Blank lines separate FAQ blocks.
    """
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue

        question = ""
        answer_lines = []
        for l in lines:
            lower = l.lower()
            if lower.startswith("q:"):
                question = l[2:].strip()
            elif lower.startswith("a:"):
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
# MATCHING & INTENT HELPERS
# ============================================================

def expand_query(msg: str) -> str:
    """Expand the message with canonical synonyms to improve matching."""
    msg_norm = normalise_text(msg)
    extras = []
    for syn, canonical in SYNONYMS.items():
        if syn in msg_norm and canonical not in msg_norm:
            extras.append(canonical)
    if extras:
        return msg + " " + " ".join(extras)
    return msg


def detect_intent(msg: str) -> str | None:
    """
    Detect specific intents like 'annual_leave' or 'working_hours'.
    This is HR-safe and only chooses *which* content to show, never
    invents policy.
    """
    msg_norm = normalise_text(msg)
    for intent in INTENT_PATTERNS:
        has_kw = any(k in msg_norm for k in intent["keywords"])
        if not has_kw:
            continue
        has_trigger = any(t in msg_norm for t in intent["question_triggers"])
        if has_trigger:
            return intent["name"]
    return None


def keyword_score(msg_norm: str, topic_key: str) -> float:
    score = 0.0
    for kw, topics in KEYWORDS.items():
        if topic_key in topics and kw in msg_norm:
            score += 0.5
    return score


def fuzzy_topic_score(msg: str, topic_key: str) -> float:
    title = TOPIC_DISPLAY.get(topic_key, "")
    body = TOPIC_CONTENT.get(topic_key, "")
    preview = body[:500]

    s1 = fuzz.token_set_ratio(msg, title)
    s2 = fuzz.partial_ratio(msg, preview)
    return max(s1, s2) / 100.0


def hybrid_topic_rank(msg: str):
    """
    Hybrid scoring:
      - fuzzy vs title/content
      - keyword boost
      - small bonus if topic name is a close match
    """
    msg_expanded = expand_query(msg)
    msg_norm = normalise_text(msg_expanded)

    ranked = []
    for topic_key in TOPIC_CONTENT:
        f = fuzzy_topic_score(msg_expanded, topic_key)
        k = keyword_score(msg_norm, topic_key)
        close = get_close_matches(msg_norm, [topic_key], n=1, cutoff=0.85)
        c = 0.3 if close else 0.0
        total = f + k + c
        if total > 0:
            ranked.append((topic_key, total))

    ranked.sort(key=lambda x: x[1], reverse=True)
    return ranked[:5]


def detect_navigation(msg: str):
    if not NAV_PAGES:
        return None
    msg_norm = normalise_text(msg)
    best_page = None
    best_score = 0.0
    for key, page in NAV_PAGES.items():
        name_norm = normalise_text(page["name"])
        score = fuzz.partial_ratio(msg_norm, name_norm) / 100.0
        if score > best_score:
            best_score = score
            best_page = page
    if best_score >= 0.75:
        return best_page
    return None


def detect_faq(msg: str):
    if not FAQ_LIST:
        return None
    questions = [faq["q"] for faq in FAQ_LIST]
    best = process.extractOne(msg, questions, scorer=fuzz.token_set_ratio)
    if not best:
        return None
    best_q, score, idx = best
    if score < 75:
        return None
    return FAQ_LIST[idx]


def best_paragraph_for_question(topic_text: str, question: str) -> str | None:
    """
    Split topic text into paragraphs and return the one that best matches
    the question, if it is clearly better than the rest.
    """
    paras = [p.strip() for p in re.split(r"\n\s*\n", topic_text) if p.strip()]
    if not paras:
        return None
    best = process.extractOne(question, paras, scorer=fuzz.token_set_ratio)
    if not best:
        return None
    para, score, _ = best
    if score < 70:
        return None
    return para


# ============================================================
# ANSWER HELPERS (HR-SAFE)
# ============================================================

def list_main_topics() -> str:
    if not TOPIC_DISPLAY:
        return "I don't have any topics loaded yet."
    titles = sorted(TOPIC_DISPLAY.values())
    bullet = "\n".join(f"• {t}" for t in titles)
    return "Here are the main topics I can help with:\n\n" + bullet


def answer_annual_leave() -> str:
    """
    HR-safe guidance for annual leave. Does NOT state a fixed number of days.
    It points users to official sources and, if available, your Working Time
    Regulations / Annual Leave topic.
    """
    possible_topics = [
        "working time regulations",
        "annual leave",
        "annual leave policy",
    ]
    topic_key = None
    for cand in possible_topics:
        ck = to_topic_key(cand)
        if ck in TOPIC_CONTENT:
            topic_key = ck
            break

    base = (
        "🗓️ **Annual Leave / Holiday Entitlement**\n\n"
        "Your exact annual leave entitlement depends on your role, location, and contract.\n"
        "For HR-proof information, always refer to:\n"
        "• Your employment contract\n"
        "• The official HR / Working Time Regulations policy\n"
        "• Your time-off / leave balance in the HR system (for example, Workday)\n"
    )

    if topic_key:
        body = TOPIC_CONTENT.get(topic_key, "")
        para = best_paragraph_for_question(body, "annual leave entitlement")
        if para:
            return base + "\n" + para
        else:
            title = TOPIC_DISPLAY.get(topic_key, "Annual Leave Policy")
            return base + f"\nYou can also review the **{title}** section on the IPA Hub for detailed guidance."
    else:
        return base


def answer_working_hours() -> str:
    """
    HR-safe guidance for normal working hours – no fixed times or totals,
    always defers to contracts / local policy.
    """
    possible_topics = [
        "working time regulations",
        "normal working hours",
        "working hours",
    ]
    topic_key = None
    for cand in possible_topics:
        ck = to_topic_key(cand)
        if ck in TOPIC_CONTENT:
            topic_key = ck
            break

    base = (
        "⏱️ **Normal Working Hours**\n\n"
        "Standard working hours are defined by your employment contract and local labour regulations.\n"
        "They can vary by role, country, and business unit.\n\n"
        "For accurate details, please check:\n"
        "• Your contract / offer letter\n"
        "• The official Working Time / Working Hours policy\n"
        "• Any local HR or Works Council agreements\n"
    )

    if topic_key:
        body = TOPIC_CONTENT.get(topic_key, "")
        para = best_paragraph_for_question(body, "normal working hours")
        if para:
            return base + "\n" + para
        else:
            title = TOPIC_DISPLAY.get(topic_key, "Working Time Regulations")
            return base + f"\nYou can also review the **{title}** section on the IPA Hub for further detail."
    else:
        return base


# ============================================================
# MAIN RESPONSE FUNCTION
# ============================================================

def generate_response(msg: str) -> str:
    global LAST_TOPIC, LAST_PAGE

    if not TOPIC_CONTENT:
        load_all_training_data()

    msg = msg.strip()
    if not msg:
        return "Please type a question so I can help 😊"

    msg_lower = msg.lower()

    # Greetings
    if msg_lower in {"hi", "hello", "hey", "hi there"}:
        return (
            "Hi! I’m your IPA Hub assistant 👋\n\n"
            "You can ask me about annual leave, working hours, SharePoint pages, training, templates, and IPA governance.\n"
            "You can also type **main topics** to see everything I know."
        )

    # Main topics
    if "main topics" in msg_lower or "what can you do" in msg_lower:
        return list_main_topics()

    # All pages / navigation list
    if "all pages" in msg_lower or "navigation" in msg_lower:
        if not NAV_PAGES:
            return "I don't have any SharePoint navigation pages configured yet."
        lines = [f"• {p['name']} – {p['url']}" for p in NAV_PAGES.values()]
        return "Here are the SharePoint pages I know about:\n\n" + "\n".join(lines)

    # Follow-up: "tell me more about that"
    if "that" in msg_lower and LAST_TOPIC and ("about that" in msg_lower or "more about that" in msg_lower):
        title = TOPIC_DISPLAY.get(LAST_TOPIC, "that topic")
        body = TOPIC_CONTENT.get(LAST_TOPIC, "")
        return f"You previously asked about **{title}**:\n\n{body}"

    # 1) High-confidence HR intents
    intent = detect_intent(msg)
    if intent == "annual_leave":
        LAST_TOPIC = to_topic_key("working time regulations")
        return answer_annual_leave()
    if intent == "working_hours":
        LAST_TOPIC = to_topic_key("working time regulations")
        return answer_working_hours()

    # 2) Navigation detection
    nav = detect_navigation(msg)
    if nav:
        LAST_PAGE = nav
        return f"🧭 **{nav['name']}**\n{nav['url']}"

    # 3) FAQ detection
    faq = detect_faq(msg)
    if faq:
        header = "**FAQ**"
        if faq.get("topic") and faq["topic"] in TOPIC_DISPLAY:
            header = f"**FAQ – {TOPIC_DISPLAY[faq['topic']]}**"
        return f"{header}\n\nQ: {faq['q']}\n\nA: {faq['a']}"

    # 4) Hybrid topic ranking
    ranked = hybrid_topic_rank(msg)

    if ranked and ranked[0][1] >= 1.0:
        topic_key, score = ranked[0]
        LAST_TOPIC = topic_key
        title = TOPIC_DISPLAY.get(topic_key, "That topic")
        body = TOPIC_CONTENT.get(topic_key, "")

        para = best_paragraph_for_question(body, msg)
        if para and len(body) > 600:
            return f"📘 **{title}**\n\n{para}"
        else:
            return f"📘 **{title}**\n\n{body}"

    # 5) Fuzzy suggestions if still not certain
    if ranked:
        suggestions = [TOPIC_DISPLAY[t[0]] for t in ranked]
        suggestion_text = "\n".join(f"• {s}" for s in suggestions)
        return (
            "I’m not 100% sure what you meant, but these topics look close to your question:\n\n"
            + suggestion_text +
            "\n\nYou can ask me directly about any of these by name."
        )

    # Final fallback
    return (
        "I couldn’t confidently match your question.\n\n"
        "You can ask me about annual leave, working hours, SharePoint pages, IPA governance, templates, and training.\n"
        "Try something like:\n"
        "• *How do I find templates?*\n"
        "• *What are our working hours?*\n"
        "• *Why do we use SharePoint?*"
    )


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def get_reply():
    data = request.get_json(force=True)
    user_msg = data.get("message", "")
    reply = generate_response(user_msg)
    return jsonify({"reply": reply})


# ============================================================
# LOCAL DEV ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
