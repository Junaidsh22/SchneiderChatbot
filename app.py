import os
import re
import random
from difflib import get_close_matches

from rapidfuzz import fuzz, process
from flask import Flask, render_template, request, jsonify

# =============== SEMANTIC SEARCH ===============
from sentence_transformers import SentenceTransformer, util
import torch

app = Flask(__name__)

# ============================================================
# GLOBAL DATA CONTAINERS
# ============================================================

DATA_FOLDER = "chatbot_data"

TOPIC_CONTENT = {}
TOPIC_DISPLAY = {}
SYNONYMS = {}
KEYWORDS = {}
NAV_PAGES = {}
FAQ_LIST = []

# Memory — remembers recent conversation context
LAST_TOPIC = None
LAST_PAGE = None

# Debug mode
DEBUG = True


def log(msg):
    if DEBUG:
        print("[DEBUG]", msg)


# ============================================================
# TEXT NORMALISATION UTILITIES
# ============================================================

def normalise_text(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def to_topic_key(name: str) -> str:
    return normalise_text(name)


# ============================================================
# TRAINING DATA LOADING
# ============================================================

def load_all_training_data():
    global TOPIC_CONTENT, TOPIC_DISPLAY, SYNONYMS, KEYWORDS, NAV_PAGES, FAQ_LIST

    TOPIC_CONTENT = {}
    TOPIC_DISPLAY = {}
    SYNONYMS = {}
    KEYWORDS = {}
    NAV_PAGES = {}
    FAQ_LIST = []

    if not os.path.isdir(DATA_FOLDER):
        print(f"[WARN] Missing folder: {DATA_FOLDER}")
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

        base = filename[:-4]
        lower = base.lower()

        if "synonym" in lower:
            process_synonyms_file(content)
        elif "keyword" in lower or "tag" in lower:
            process_keywords_file(content)
        elif "faq" in lower:
            process_faq_file(content, base)
        elif "navigation" in lower or "list of all the pages" in lower:
            process_navigation_file(content)
        else:
            process_topic_file(base, content)

    log("Training data loaded.")


def process_topic_file(base_name, content):
    key = to_topic_key(base_name)
    display = " ".join(w.capitalize() for w in base_name.replace("_", " ").split())
    TOPIC_CONTENT[key] = content.strip()
    TOPIC_DISPLAY[key] = display


def process_synonyms_file(text):
    for line in text.splitlines():
        if ":" in line:
            left, right = line.split(":", 1)
            canonical = to_topic_key(left)
            for syn in re.split(r"[;,/]", right):
                SYNONYMS[to_topic_key(syn)] = canonical
        elif "=" in line:
            parts = [p.strip() for p in line.split("=")]
            canonical = to_topic_key(parts[0])
            for syn in parts:
                SYNONYMS[to_topic_key(syn)] = canonical


def process_keywords_file(text):
    for line in text.splitlines():
        if ":" not in line:
            continue
        topic_raw, kw_raw = line.split(":", 1)
        topic_key = to_topic_key(topic_raw)
        for kw in re.split(r"[;,/]", kw_raw):
            k = to_topic_key(kw)
            if k:
                KEYWORDS.setdefault(k, set()).add(topic_key)


def process_navigation_file(text):
    for line in text.splitlines():
        if "http" not in line:
            continue
        before, after = line.split("http", 1)
        name = before.strip()
        url = "http" + after.strip()
        if name and url:
            key = to_topic_key(name)
            NAV_PAGES[key] = {"name": name, "url": url}


def process_faq_file(text, base_name):
    blocks = re.split(r"\bQ:", text, flags=re.IGNORECASE)
    for block in blocks:
        if "A:" not in block:
            continue
        q_raw, a_raw = re.split(r"\bA:", block, 1, flags=re.IGNORECASE)
        q = normalise_text(q_raw.strip())
        a = a_raw.strip()
        FAQ_LIST.append({"q": q, "a": a})


# Load data
load_all_training_data()


# ============================================================
# SEMANTIC SEARCH INITIALISATION
# ============================================================

model = SentenceTransformer("all-MiniLM-L6-v2")

TOPIC_KEYS = list(TOPIC_CONTENT.keys())
TOPIC_TEXTS = [TOPIC_CONTENT[k] for k in TOPIC_KEYS]
TOPIC_EMBEDDINGS = model.encode(TOPIC_TEXTS, convert_to_tensor=True)


def semantic_rank(query):
    q_emb = model.encode(query, convert_to_tensor=True)
    scores = util.cos_sim(q_emb, TOPIC_EMBEDDINGS)[0]
    top_idx = torch.topk(scores, 3)
    results = []
    for score, idx in zip(top_idx.values, top_idx.indices):
        results.append((TOPIC_KEYS[idx], float(score)))
    return results


# ============================================================
# TOPIC DETECTION
# ============================================================

def expand_synonyms(text):
    tokens = normalise_text(text).split()
    rebuilt = []
    for t in tokens:
        canonical = SYNONYMS.get(t, t)
        rebuilt.append(canonical)
    return " ".join(rebuilt)


def keyword_fuzzy_score(topic_key, message):
    score = 0
    msg = normalise_text(message)

    if topic_key in msg:
        score += 3

    # fuzzy match
    score += fuzz.partial_ratio(topic_key, msg) / 25

    # keyword match
    for kw, tset in KEYWORDS.items():
        if topic_key in tset and kw in msg:
            score += 2

    return score


def hybrid_topic_rank(message):
    expanded = expand_synonyms(message)

    # fuzzy + keyword
    fuzzy_rank = []
    for t in TOPIC_KEYS:
        s = keyword_fuzzy_score(t, expanded)
        if s > 0:
            fuzzy_rank.append((t, s))

    fuzzy_rank.sort(key=lambda x: x[1], reverse=True)
    fuzzy_rank = fuzzy_rank[:3]

    # semantic
    semantic_scores = semantic_rank(expanded)

    combined = {}

    # merge fuzzy and semantic results
    for t, s in fuzzy_rank:
        combined[t] = combined.get(t, 0) + s

    for t, s in semantic_scores:
        combined[t] = combined.get(t, 0) + (s * 10)

    ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)

    return ranked[:3] if ranked else []


# ============================================================
# FAQ DETECTION
# ============================================================

def detect_faq(msg):
    norm = normalise_text(msg)
    questions = [f["q"] for f in FAQ_LIST]
    match = get_close_matches(norm, questions, n=1, cutoff=0.65)
    if match:
        for f in FAQ_LIST:
            if f["q"] == match[0]:
                return f["a"]
    return None


# ============================================================
# NAVIGATION DETECTION
# ============================================================

def detect_navigation(msg):
    norm = normalise_text(msg)
    keys = list(NAV_PAGES.keys())
    names = [normalise_text(NAV_PAGES[k]["name"]) for k in keys]

    candidates = keys + names

    best = get_close_matches(norm, candidates, n=1, cutoff=0.6)
    if not best:
        return None

    match = best[0]

    if match in NAV_PAGES:
        return NAV_PAGES[match]

    for k, info in NAV_PAGES.items():
        if normalise_text(info["name"]) == match:
            return info

    return None


# ============================================================
# MAIN RESPONSE ENGINE
# ============================================================

def generate_response(msg):
    global LAST_TOPIC, LAST_PAGE

    msg = msg.strip()
    if not msg:
        return "Please type something so I can help 😊"

    # Follow-up reference
    if "that" in msg.lower() and LAST_TOPIC:
        title = TOPIC_DISPLAY[LAST_TOPIC]
        body = TOPIC_CONTENT[LAST_TOPIC]
        return f"You previously asked about **{title}**:\n\n{body}"

    # Navigation
    nav = detect_navigation(msg)
    if nav:
        LAST_PAGE = nav
        return f"🧭 **{nav['name']}**\n{nav['url']}"

    # FAQ
    faq_ans = detect_faq(msg)
    if faq_ans:
        return faq_ans

    # Hybrid topic scoring
    ranked = hybrid_topic_rank(msg)

    if ranked and ranked[0][1] >= 1.2:  # confidence threshold
        topic_key = ranked[0][0]
        LAST_TOPIC = topic_key
        title = TOPIC_DISPLAY[topic_key]
        body = TOPIC_CONTENT[topic_key]
        return f"📘 **{title}**\n\n{body}"

    # If unclear → suggest closest topics
    if ranked:
        suggestions = [TOPIC_DISPLAY[t[0]] for t in ranked]
        return (
            "I'm not fully sure what you meant 🤔\n\n"
            "Did you mean one of these?\n"
            "• " + "\n• ".join(suggestions)
        )

    # Final fallback
    return (
        "I couldn’t confidently match your question.\n\n"
        "Try asking about a SharePoint page, topic, template, or regulation.\n"
        "Type **main topics** to see everything I can explain."
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
    reply = generate_response(data.get("message", ""))
    return jsonify({"reply": reply})


# ============================================================
# RUN LOCAL
# ============================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
