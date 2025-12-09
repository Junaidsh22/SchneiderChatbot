import os
import re
from typing import Dict, List, Tuple, Optional

from flask import Flask, jsonify, render_template, request
from rapidfuzz import fuzz, process


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "chatbot_data")

app = Flask(__name__)


# ============================================================
# NORMALISATION HELPERS
# ============================================================

def normalise_text(text: str) -> str:
    """Normalise text for matching – lowercase, strip punctuation, condense spaces."""
    if not text:
        return ""
    text = text.lower()
    # keep letters, numbers and spaces
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_into_blocks(text: str) -> List[str]:
    """
    Split a training file into logical blocks using blank lines as boundaries.

    This keeps FAQ-style Q/A sections and long documents in smaller chunks so that
    we can return short, focused answers instead of the entire file.
    """
    if not text:
        return []
    blocks = re.split(r"\n\s*\n+", text.strip())
    return [b.strip() for b in blocks if b.strip()]


def split_into_sentences(text: str) -> List[str]:
    """Lightweight sentence splitter – good enough for support content."""
    if not text:
        return []
    # Break on ., ?, ! followed by whitespace / end-of-line
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [p.strip() for p in parts if p.strip()]
    return sentences


# ============================================================
# DATA STRUCTURES
# ============================================================

class TopicBlock:
    __slots__ = ("topic_key", "topic_title", "block_text", "norm_text")

    def __init__(self, topic_key: str, topic_title: str, block_text: str):
        self.topic_key = topic_key
        self.topic_title = topic_title
        self.block_text = block_text.strip()
        self.norm_text = normalise_text(self.block_text)


class FAQEntry:
    __slots__ = ("topic_key", "topic_title", "question_raw", "question_norm", "answer")

    def __init__(self, topic_key: str, topic_title: str, question_raw: str, answer: str):
        self.topic_key = topic_key
        self.topic_title = topic_title
        self.question_raw = question_raw.strip()
        self.question_norm = normalise_text(self.question_raw)
        self.answer = answer.strip()


# Global stores populated at startup
TOPIC_TEXT: Dict[str, str] = {}
TOPIC_TITLES: Dict[str, str] = {}
BLOCK_INDEX: List[TopicBlock] = []
FAQ_INDEX: List[FAQEntry] = []

# concept → list of phrases that should map to it
CONCEPT_PATTERNS: Dict[str, List[str]] = {}

# phrase (normalised) → canonical concept
PHRASE_TO_CONCEPT: Dict[str, str] = {}


# ============================================================
# LOADING SYNONYMS / KEYWORDS
# ============================================================

def add_concept_phrases(concept: str, phrases: List[str]):
    """Register helper phrases for a high-level intent."""
    concept_norm = normalise_text(concept)
    if concept_norm not in CONCEPT_PATTERNS:
        CONCEPT_PATTERNS[concept_norm] = []
    for p in phrases:
        p_norm = normalise_text(p)
        if not p_norm:
            continue
        if p_norm not in CONCEPT_PATTERNS[concept_norm]:
            CONCEPT_PATTERNS[concept_norm].append(p_norm)
        PHRASE_TO_CONCEPT[p_norm] = concept_norm


def load_synonyms_file():
    """
    Parse 'Synonyms & Alternative Terms.txt' if present.

    Expected pattern (examples from your training file):
        annual leave / holidays / vacation → Annual Leave
        bank holidays / public holidays → Bank Holidays
    """
    path = os.path.join(DATA_DIR, "Synonyms & Alternative Terms.txt")
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Look for "→" or "->" style mappings
            if "→" in line:
                left, right = line.split("→", 1)
            elif "->" in line:
                left, right = line.split("->", 1)
            else:
                continue

            canon = right.strip()
            # left side may be slash- or comma-separated synonyms
            raw_terms = re.split(r"[,/]", left)
            terms = [t.strip() for t in raw_terms if t.strip()]
            if not canon or not terms:
                continue

            add_concept_phrases(canon, terms)


def load_keywords_file():
    """
    Use 'Keywords & Tags.txt' as extra hints.

    We treat each line as describing a concept followed by example phrases, for example:
        Annual Leave: annual leave, holiday, holidays, time off
    """
    path = os.path.join(DATA_DIR, "Keywords & Tags.txt")
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # e.g. "Annual Leave: holidays, time off"
            if ":" not in line:
                continue
            concept, raw_terms = line.split(":", 1)
            canon = concept.strip()
            terms = [t.strip() for t in re.split(r"[,/]", raw_terms) if t.strip()]
            if canon and terms:
                add_concept_phrases(canon, terms)


def register_manual_concepts():
    """
    Add a curated set of core intents which we want to match perfectly even if
    the training files change.
    """
    add_concept_phrases(
        "Annual Leave",
        [
            "annual leave",
            "holiday entitlement",
            "holidays",
            "paid leave",
            "time off",
            "annual leave days",
        ],
    )
    add_concept_phrases(
        "Bank Holidays",
        [
            "bank holidays",
            "public holidays",
            "uk bank holidays",
        ],
    )
    add_concept_phrases(
        "Working Time Regulations",
        [
            "working hours",
            "work hours",
            "work time",
            "working time regulations",
            "weekly hours",
            "daily hours",
        ],
    )
    add_concept_phrases(
        "SharePoint Access",
        [
            "what can i access",
            "what is on the sharepoint",
            "what is on the ipa sharepoint",
            "what pages are on ipa sharepoint",
            "what can i see on sharepoint",
        ],
    )
    add_concept_phrases(
        "Templates & Documents",
        [
            "templates",
            "document templates",
            "forms",
            "project templates",
            "where do i find templates",
        ],
    )
    add_concept_phrases(
        "Troubleshooting",
        [
            "sharepoint not loading",
            "access denied",
            "permission error",
            "broken link",
            "page not found",
            "sharepoint is slow",
            "vpn issue",
            "sync issue",
            "it support",
            "troubleshooting",
        ],
    )
    add_concept_phrases(
        "Navigation / Where to find",
        [
            "where do i find",
            "where can i find",
            "how do i access",
            "how do i get to",
            "where is the page",
            "where is this on ipa hub",
        ],
    )


# ============================================================
# PARSING TRAINING FILES
# ============================================================

def parse_topic_file(filename: str):
    """Load a .txt training file and create FAQ and block entries."""
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read().strip()

    base_name = os.path.splitext(filename)[0]
    topic_key = normalise_text(base_name)
    topic_title = base_name.strip()

    TOPIC_TEXT[topic_key] = raw
    TOPIC_TITLES[topic_key] = topic_title

    # Build block index
    for block in split_into_blocks(raw):
        BLOCK_INDEX.append(TopicBlock(topic_key, topic_title, block))

    # Extract FAQ-style Q&A pairs inside this file
    blocks = split_into_blocks(raw)
    for block in blocks:
        # We consider blocks that contain at least one "Q:" and one "A:"
        if "Q:" not in block or "A:" not in block:
            continue
        # Some blocks include many Q lines followed by a single A.
        # We keep all Q lines together as one question string.
        q_part, a_part = re.split(r"\bA:", block, maxsplit=1, flags=re.IGNORECASE)
        questions = []
        for line in q_part.splitlines():
            line = line.strip()
            if line.lower().startswith("q:"):
                questions.append(line[2:].strip())
        if not questions:
            continue
        question_text = " ".join(questions)
        answer_text = a_part.strip()
        FAQ_INDEX.append(FAQEntry(topic_key, topic_title, question_text, answer_text))


def load_all_training_files():
    """Discover and parse all .txt files in chatbot_data."""
    if not os.path.isdir(DATA_DIR):
        return

    for filename in os.listdir(DATA_DIR):
        if not filename.lower().endswith(".txt"):
            continue
        parse_topic_file(filename)


# ============================================================
# INTENT & MATCHING
# ============================================================

def detect_concept(message: str) -> Optional[str]:
    """
    Try to map the user message to a high-level concept like 'Annual Leave'
    or 'Troubleshooting'.
    """
    msg_norm = normalise_text(message)
    if not msg_norm:
        return None

    # Direct phrase containment / fuzzy
    best_concept = None
    best_score = 0

    for phrase_norm, concept_norm in PHRASE_TO_CONCEPT.items():
        if not phrase_norm:
            continue
        if phrase_norm in msg_norm:
            score = len(phrase_norm)
        else:
            # Fuzzy match short phrases
            score = fuzz.partial_ratio(msg_norm, phrase_norm)
        if score > best_score:
            best_score = score
            best_concept = concept_norm

    # Small threshold – we always want *something* when user asks a meaningful question
    if best_score < 40:
        return None
    return best_concept


def find_best_faq_answer(message: str) -> Optional[str]:
    """Search all FAQ entries for the best matching question."""
    if not FAQ_INDEX:
        return None

    msg_norm = normalise_text(message)
    best: Optional[Tuple[FAQEntry, float]] = None

    for entry in FAQ_INDEX:
        score = fuzz.token_set_ratio(msg_norm, entry.question_norm)
        # Small bonus if we exactly contain big words
        if entry.question_norm in msg_norm or msg_norm in entry.question_norm:
            score += 5
        if not best or score > best[1]:
            best = (entry, score)

    if not best:
        return None

    entry, score = best
    if score < 55:
        # not confident enough, let topic-based search handle it
        return None

    snippet = build_snippet(entry.answer)
    title = entry.topic_title
    return f"📌 **{title}**\n\n{snippet}"


def find_best_topic_block(message: str) -> Optional[str]:
    """Fallback: search general blocks in all topics and return a short snippet."""
    if not BLOCK_INDEX:
        return None

    msg_norm = normalise_text(message)
    best: Optional[Tuple[TopicBlock, float]] = None

    for block in BLOCK_INDEX:
        score = fuzz.token_set_ratio(msg_norm, block.norm_text)
        if not best or score > best[1]:
            best = (block, score)

    if not best:
        return None

    block, score = best
    if score < 40:
        return None

    snippet = build_snippet(block.block_text)
    title = block.topic_title
    return f"📌 **{title}**\n\n{snippet}"


# ============================================================
# ANSWER BUILDING
# ============================================================

def build_snippet(text: str, max_sentences: int = 6, max_chars: int = 900) -> str:
    """
    Turn a raw training block into a concise, HR-friendly snippet.

    - Prefer the section after 'A:' if present (answer part)
    - Strip leftover 'Q:' labels
    - Limit to a few sentences and characters
    """
    if not text:
        return ""

    # If there's an explicit answer section, keep only that.
    if "A:" in text:
        _, text = re.split(r"\bA:", text, maxsplit=1, flags=re.IGNORECASE)
    # Remove Q: lines if they leaked into the answer
    cleaned_lines: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("q:"):
            continue
        cleaned_lines.append(line)
    cleaned = " ".join(cleaned_lines).strip()

    sentences = split_into_sentences(cleaned)
    if not sentences:
        snippet = cleaned
    else:
        snippet = " ".join(sentences[:max_sentences])

    if len(snippet) > max_chars:
        snippet = snippet[: max_chars - 3].rsplit(" ", 1)[0] + "..."

    return snippet


def answer_for_concept(concept: str, message: str) -> Optional[str]:
    """
    For key concepts like Annual Leave or Troubleshooting, provide a
    hand-crafted, concise answer using the training text as reference.
    """
    concept = concept or ""
    concept = concept.lower()

    # Annual leave / holidays
    if "annual leave" in concept:
        return (
            "🗓️ **Annual Leave / Holiday Entitlement**\n\n"
            "Your exact annual leave allowance depends on your role, location, and contract.\n\n"
            "In general:\n"
            "• Standard entitlement is *around* 28 days per year **including bank holidays**.\n"
            "• The formal rules are set out in the **Working Time Regulations** and your HR policies.\n\n"
            "For an HR-approved answer specific to you, always check:\n"
            "• Your employment contract or offer letter\n"
            "• The official HR / Working Time Regulations policy on the IPA Hub\n"
            "• Your live balance in the HR system (for example **Workday** or **Time@Schneider**)."
        )

    # Bank holidays
    if "bank holiday" in concept:
        return (
            "🏦 **Bank Holidays (UK)**\n\n"
            "Official UK bank holiday dates are published on the GOV.UK website:\n"
            "https://www.gov.uk/bank-holidays\n\n"
            "Use that page to confirm the exact public holidays for England, Scotland, Wales or "
            "Northern Ireland. Your local HR policy explains how bank holidays interact with your "
            "annual leave entitlement."
        )

    # Working time / hours
    if "working time regulations" in concept or "working time" in concept:
        return (
            "⌚ **Working Time / Standard Working Hours**\n\n"
            "Working patterns are governed by Schneider Electric’s **Working Time Regulations** policy.\n\n"
            "It covers:\n"
            "• Your contracted weekly hours and core working times\n"
            "• Rules on daily and weekly rest periods\n"
            "• Night work, overtime and flexible working where applicable\n\n"
            "To see the exact rules for you, review:\n"
            "• Your contract or offer letter\n"
            "• The **Working Time Regulations** section on the IPA Hub\n"
            "• Any local agreements confirmed with your manager or HR."
        )

    # What can I access on SharePoint?
    if "sharepoint access" in concept:
        return (
            "📂 **What can I access on the IPA SharePoint Hub?**\n\n"
            "The IPA Hub is a central place for:\n"
            "• Policies and governance documents\n"
            "• Templates, forms and project packs\n"
            "• Training and learning materials\n"
            "• Collaboration spaces for teams and communities\n"
            "• Troubleshooting guides and IT information\n\n"
            "If you tell me *what you’re trying to do* (for example *find a template*, "
            "*open IT troubleshooting guides* or *view onboarding content*), I can point you "
            "to the right page."
        )

    # Templates
    if "templates" in concept:
        return (
            "📄 **Finding Templates and Forms**\n\n"
            "On the IPA SharePoint Hub you can usually find templates by:\n"
            "1. Using the SharePoint search bar and typing **“template”** plus a keyword "
            "(for example *RAID log*, *governance pack*, *NDA*, *HR form*).\n"
            "2. Browsing the relevant hub area such as **Project Templates**, **Legal**, **HR**, "
            "or **Finance**.\n\n"
            "If you tell me what kind of template you need (project, HR, legal, procurement, etc.), "
            "I can suggest the most likely page to start from."
        )

    # Troubleshooting / IT support
    if "troubleshooting" in concept:
        # Use the Troubleshooting Tips topic if we have it – but only as a short snippet.
        topic_key = normalise_text("Troubleshooting Tips")
        block_answer = None
        if TOPIC_TEXT.get(topic_key):
            block_answer = build_snippet(TOPIC_TEXT[topic_key])
        if block_answer:
            header = "🛠️ **Troubleshooting SharePoint / IPA Hub Issues**\n\n"
            return header + block_answer

        # Fallback generic advice
        return (
            "🛠️ **Troubleshooting SharePoint / IPA Hub Issues**\n\n"
            "Try these quick checks first:\n"
            "1. Make sure you are connected to VPN (if required).\n"
            "2. Refresh the page or open it in a private/incognito window.\n"
            "3. Try another browser (Edge or Chrome are recommended).\n"
            "4. If you see *access denied*, use **Request Access** or contact the site owner.\n\n"
            "If issues continue, please raise an IT ticket or speak to your local IT support team."
        )

    # Navigation / where to find things – concept only gives a light answer;
    # we still rely on FAQ/topic matching for specifics.
    if "navigation" in concept:
        return (
            "🧭 **Finding Content on the IPA Hub**\n\n"
            "You can usually find what you need by:\n"
            "• Using the SharePoint search bar with a few key words (e.g. *onboarding checklist*, *NDA template*).\n"
            "• Browsing via the IPA Hub home page and following the HR, IT, Project, or Governance sections.\n\n"
            "Tell me what you’re looking for (for example *onboarding hub*, *HR policies*, *IT troubleshooting* "
            "or *graduate community*) and I’ll point you to the right page or summary."
        )

    return None


# ============================================================
# MAIN CHAT LOGIC
# ============================================================

def is_greeting(message: str) -> bool:
    msg = normalise_text(message)
    return any(word in msg for word in ["hello", "hi ", "hi", "hey", "good morning", "good afternoon", "good evening"])


def list_main_topics() -> str:
    topics = [
        "Annual Leave & Bank Holidays",
        "Working Time Regulations & Hours",
        "What you can access on the IPA Hub",
        "Navigation – where to find pages, templates and tools",
        "SharePoint best practices & advanced features",
        "Onboarding hub, training and learning",
        "Troubleshooting and IT / access issues",
    ]
    bullet = "\n".join(f"• {t}" for t in topics)
    return (
        "Here are the main areas I can help with:\n\n"
        f"{bullet}\n\n"
        "You can ask in natural language, for example:\n"
        "• *How many annual leave days do I get?*\n"
        "• *Where do I find bank holiday information?*\n"
        "• *What can I access on the IPA SharePoint?*\n"
        "• *Where do I find templates for projects?*\n"
        "• *SharePoint is slow – what can I try?*"
    )


def generate_answer(message: str) -> str:
    message = (message or "").strip()
    if not message:
        return "Please type a question and I’ll do my best to help."

    msg_norm = normalise_text(message)

    # 1) Greetings and main-topics shortcuts
    if "main topics" in msg_norm or "what can you do" in msg_norm:
        return list_main_topics()
    if is_greeting(message):
        return (
            "Hi! I’m your IPA Hub Navigation Assistant 👋\n\n"
            "Ask me about annual leave, working hours, HR policies, SharePoint pages, templates, "
            "training, or troubleshooting issues.\n"
            "You can also type **main topics** to see everything I know."
        )

    # 2) High-level concept detection with curated answers
    concept = detect_concept(message)
    concept_answer = answer_for_concept(concept or "", message) if concept else None
    if concept_answer:
        return concept_answer

    # 3) FAQ-style Q&A matching
    faq_answer = find_best_faq_answer(message)
    if faq_answer:
        return faq_answer

    # 4) Block / topic matching
    block_answer = find_best_topic_block(message)
    if block_answer:
        return block_answer

    # 5) Final fallback – never say "I don't know", always give something useful
    return (
        "I couldn’t perfectly match your question to a specific page or policy, "
        "but I can definitely help.\n\n"
        + list_main_topics()
    )


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(force=True) or {}
    message = data.get("message", "")
    answer = generate_answer(message)
    return jsonify({"answer": answer})


# ============================================================
# APP STARTUP
# ============================================================

def initialise_chatbot():
    load_synonyms_file()
    load_keywords_file()
    register_manual_concepts()
    load_all_training_files()


# Initialise at import time (Render / Gunicorn)
initialise_chatbot()

if __name__ == "__main__":
    app.run(debug=True)

