import os
import re
from typing import Dict, List, Tuple, Optional

from flask import Flask, render_template, request, jsonify
from rapidfuzz import fuzz, process

# ============================================================
# CONFIG
# ============================================================

DATA_FOLDER = "chatbot_data"

app = Flask(__name__)

# ============================================================
# GLOBAL STATE
# ============================================================

TOPIC_CONTENT: Dict[str, str] = {}
TOPIC_TITLES: Dict[str, str] = {}
RAW_FILES: Dict[str, str] = {}
FAQ_LIST: List[Dict[str, str]] = []

# phrase (synonym) -> canonical concept
CONCEPT_SYNONYMS: Dict[str, str] = {}
# canonical concept (normalised) -> topic key
CONCEPT_TO_TOPIC: Dict[str, str] = {}

MAINTENANCE_TEXT: Optional[str] = None
NAVIGATION_TEXT: Optional[str] = None


# ============================================================
# HELPERS
# ============================================================

def normalise_text(text: str) -> str:
    """Lowercase and remove extra punctuation/spacing for matching."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def to_topic_key(name: str) -> str:
    """Create a simple key from a filename or title."""
    name = normalise_text(name)
    return name.replace(" ", "_")


def read_file_safely(path: str) -> str:
    """Read a text file with utf-8 then latin-1 fallback."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1") as f:
            return f.read()


def register_topic(title: str, content: str):
    """Store raw topic content but keep it clean (no weird extra whitespace)."""
    key = to_topic_key(title)
    TOPIC_TITLES[key] = title.strip()
    cleaned = re.sub(r"\s+\n", "\n", content.strip())
    cleaned = re.sub(r"\n\s+", "\n", cleaned)
    TOPIC_CONTENT[key] = cleaned


def register_concept(canonical: str, phrases: List[str]):
    """Add canonical concept and all its phrases to the synonym table."""
    canonical_norm = normalise_text(canonical)
    for phrase in phrases:
        p = normalise_text(phrase)
        if not p:
            continue
        existing = CONCEPT_SYNONYMS.get(p)
        if existing:
            # prefer shorter canonical names (more general)
            if len(canonical_norm) < len(existing):
                CONCEPT_SYNONYMS[p] = canonical_norm
        else:
            CONCEPT_SYNONYMS[p] = canonical_norm


# ============================================================
# PARSERS FOR TRAINING FILES
# ============================================================

def parse_faq_file(text: str, base_name: str):
    """
    Parse Q/A style FAQ documents.

    Expected pattern:

        Section Heading (optional)
        Q: question text
        Q: alternative phrasing
        ...
        A: answer text

    All Q: lines above a single A: are treated as alternative phrasings,
    and stored as a single FAQ entry where 'q_norm' is the combined question
    block (good for fuzzy matching).
    """
    base_topic_key = to_topic_key(base_name)

    # Split on Q: but keep blocks that contain an A:
    blocks = re.split(r"\bQ:", text, flags=re.IGNORECASE)
    for block in blocks:
        block = block.strip()
        if not block or "A:" not in block:
            continue

        try:
            q_raw, a_raw = re.split(r"\bA:", block, maxsplit=1, flags=re.IGNORECASE)
        except ValueError:
            continue

        q_raw = q_raw.strip()
        a = a_raw.strip()
        if not a:
            continue

        # Clean up question block – remove any accidental headings like:
        # "Annual Leave Entitlement", etc.
        q_lines = [ln.strip() for ln in q_raw.splitlines() if ln.strip()]
        # Filter out “section header” style lines with no question mark
        question_lines = [ln for ln in q_lines if "?" in ln]

        if not question_lines:
            # fallback: use entire q_raw if no explicit '?' (still better than nothing)
            question_block = q_raw
        else:
            question_block = " ".join(question_lines)

        q_norm = normalise_text(question_block)
        if not q_norm or not a:
            continue

        FAQ_LIST.append(
            {
                "q_raw": question_block,
                "q_norm": q_norm,
                "a": a,
                "topic": base_topic_key,
            }
        )


def parse_keywords_and_concepts(text: str):
    """
    From 'Keywords & Tags.txt' we only need the CANONICAL CONCEPT MAPPINGS section.
    Example:
        - Working Hours → working hours, work schedule, office hours, shift timings, core hours
    """
    in_canonical = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("CANONICAL CONCEPT MAPPINGS"):
            in_canonical = True
            continue
        if not in_canonical:
            continue
        if not line.startswith("-") or "→" not in line:
            continue

        try:
            left, right = line[1:].split("→", 1)
        except ValueError:
            continue
        canonical = left.strip()
        synonyms_str = right.strip()
        phrases = [canonical] + [p.strip() for p in synonyms_str.split(",")]
        register_concept(canonical, phrases)


def parse_synonyms_file(text: str):
    """
    Parse 'Synonyms & Alternative Terms.txt' which uses '→' mappings.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or "→" not in line:
            continue
        if line.lower().startswith("synonyms"):
            continue
        left, right = line.split("→", 1)
        canonical = left.strip()
        phrases = [canonical] + [p.strip() for p in right.split(",")]
        register_concept(canonical, phrases)


# ============================================================
# TRAINING DATA LOADER
# ============================================================

def load_all_training_data():
    """
    Load *all* training .txt files and:
    - register them as topics,
    - parse any Q/A-style content as FAQ entries (not just files named *FAQ*),
    - build concept mappings.
    """
    global MAINTENANCE_TEXT, NAVIGATION_TEXT

    if not os.path.isdir(DATA_FOLDER):
        print(f"[WARN] Training data folder '{DATA_FOLDER}' not found.")
        return

    for filename in os.listdir(DATA_FOLDER):
        if not filename.lower().endswith(".txt"):
            continue

        path = os.path.join(DATA_FOLDER, filename)
        content = read_file_safely(path)
        base = filename[:-4].strip()
        base_lower = base.lower()
        RAW_FILES[base_lower] = content

        # 1) Every file is a topic
        register_topic(base, content)

        # 2) Any file that looks like Q/A is parsed as FAQ,
        #    not just ones containing "faq" in the name.
        has_q = re.search(r"\bQ:", content, flags=re.IGNORECASE) is not None
        has_a = re.search(r"\bA:", content, flags=re.IGNORECASE) is not None

        if "keyword" in base_lower:
            parse_keywords_and_concepts(content)
        elif "synonym" in base_lower:
            parse_synonyms_file(content)
        elif "maintenance" in base_lower:
            MAINTENANCE_TEXT = content.strip()
        elif "navigation" in base_lower:
            NAVIGATION_TEXT = content.strip()

        # FAQ-style entries (Working Time Regulations, Troubleshooting, FAQ, etc.)
        if "faq" in base_lower or (has_q and has_a):
            parse_faq_file(content, base)

    add_manual_concepts()
    build_concept_to_topic_mapping()


def add_manual_concepts():
    """
    Extend concept table with important HR / navigation / IPA Hub concepts.
    These link natural language into your training files.
    """
    manual = {
        # Core HR
        "Annual Leave": [
            "annual leave",
            "annual leave days",
            "how many annual leave days",
            "how many holidays",
            "holiday entitlement",
            "holiday days",
            "vacation days",
            "paid time off",
            "pto",
            "annual holiday",
            "leave allowance",
            "leave entitlements",
            "holiday allowance",
        ],
        "Bank Holidays": [
            "bank holiday",
            "bank holidays",
            "public holiday",
            "public holidays",
            "uk bank holidays",
            "where are bank holidays listed",
            "bank holiday dates",
            "bank holiday information",
        ],
        "Working Hours": [
            "working hours",
            "work hours",
            "working time",
            "working time regulations",
            "normal working hours",
            "core hours",
            "hours per week",
            "shift pattern",
            "shift timings",
            "standard hours",
            "start time",
            "finish time",
        ],
        "HR Policies": [
            "hr policies",
            "hr policy",
            "company policies",
            "hr rules",
            "hr guidance",
            "where are hr policies",
        ],

        # SharePoint core
        "SharePoint Access": [
            "what can i access",
            "what can i access on sharepoint",
            "what can i access on the ipa sharepoint",
            "sharepoint access",
            "access on ipa hub",
            "what is available on sharepoint",
            "what does the sharepoint allow me to access",
            "what can i see on sharepoint",
            "what is on the sharepoint",
        ],
        "SharePoint Purpose": [
            "why do we use a sharepoint",
            "why sharepoint",
            "purpose of sharepoint",
            "what is the purpose of sharepoint",
            "why do we use sharepoint",
            "why does schneider use sharepoint",
            "sharepoint use case reasoning",
        ],
        "SharePoint Navigation": [
            "where do i find",
            "where can i find",
            "where is",
            "navigate to",
            "how do i get to",
            "how do i find",
            "navigation",
            "ipa hub navigation",
            "sharepoint navigation",
            "how to get to page",
        ],
        "SharePoint Use Cases": [
            "sharepoint use cases",
            "what is sharepoint used for",
            "how do we use sharepoint",
            "examples of sharepoint usage",
            "sharepoint scenario",
            "sharepoint business use",
        ],

        # Themed topics from your training data
        "Document Access": [
            "access hr policies",
            "open hr policies",
            "where are policies stored",
            "find templates",
            "project templates",
            "governance packs",
            "open training materials",
            "access e learning",
            "where are finance templates",
            "where are engineering standards",
            "where are legal contracts",
            "where are qa reports",
            "how do i access documents",
            "document access",
        ],
        "Collaboration": [
            "share documents",
            "share files",
            "co author",
            "work together",
            "collaborate",
            "collaboration",
            "shared folders",
            "document approval workflow",
        ],
        "Compliance & Governance": [
            "compliance",
            "governance",
            "audit trail",
            "iso standards",
            "regulatory standards",
            "gdpr",
            "data protection",
            "risk management",
            "hse documentation",
            "safety guidelines",
        ],
        "Advanced Features": [
            "advanced features",
            "version history",
            "metadata tagging",
            "alerts",
            "customise homepage",
            "automated workflows",
            "approvals",
            "multilingual",
        ],
        "Training & Learning": [
            "training",
            "learning hub",
            "mandatory training",
            "onboarding training",
            "graduate programme resources",
            "development plans",
            "compliance training modules",
            "leadership training",
            "technical training",
            "soft skills courses",
        ],
        "Communication & Updates": [
            "company wide announcements",
            "all company group",
            "newsletters",
            "leadership messages",
            "policy updates",
            "system maintenance updates",
            "event calendars",
            "roadmap updates",
        ],
        "Integration": [
            "integrate sharepoint",
            "sharepoint with teams",
            "sharepoint with power bi",
            "sharepoint and servicenow",
            "project tools like ms project",
            "api access",
            "vendor portals",
            "sharepoint integration tips",
        ],

        # Other
        "Troubleshooting": [
            "troubleshooting",
            "problem",
            "issue",
            "error",
            "access denied",
            "page not loading",
            "broken link",
            "link not working",
            "sharepoint not loading",
            "vpn issue",
            "sync issue",
        ],
        "Best Practices": [
            "best practice",
            "best practices",
            "how should i use sharepoint",
            "sharepoint tips",
            "sharepoint guidelines",
            "sharepoint best practices",
        ],
        "Onboarding": [
            "onboarding",
            "new hire",
            "induction",
            "joiner",
            "welcome programme",
            "onboarding hub",
            "onboarding checklist",
            "new starter",
        ],
        "IT Support": [
            "it support",
            "it help",
            "password reset",
            "vpn not working",
            "laptop issue",
            "wifi issue",
            "endpoint setup",
        ],
    }

    for canonical, phrases in manual.items():
        register_concept(canonical, phrases)


def build_concept_to_topic_mapping():
    """Map canonical concepts to the most relevant topic (.txt file)."""
    concepts = sorted(set(CONCEPT_SYNONYMS.values()))
    if not concepts or not TOPIC_TITLES:
        return

    topic_items = list(TOPIC_TITLES.items())

    for concept in concepts:
        c_norm = normalise_text(concept)
        best_topic = None
        best_score = 0

        for key, title in topic_items:
            score = fuzz.token_set_ratio(c_norm, normalise_text(title))
            if score > best_score:
                best_score = score
                best_topic = key

        if best_topic and best_score >= 60:
            CONCEPT_TO_TOPIC[c_norm] = best_topic

    # Helpful manual overrides based on known filenames
    topic_by_name = {normalise_text(v): k for k, v in TOPIC_TITLES.items()}

    wtr_key = topic_by_name.get("working time regulations")
    if wtr_key:
        for c in ("annual leave", "working hours", "bank holidays", "hr policies"):
            CONCEPT_TO_TOPIC[normalise_text(c)] = wtr_key

    why_sp_key = topic_by_name.get("why do we use a sharepoint")
    if why_sp_key:
        for c in ("sharepoint purpose", "sharepoint use cases"):
            CONCEPT_TO_TOPIC[normalise_text(c)] = why_sp_key

    access_key = topic_by_name.get("what does the sharepoint allow me to access")
    if access_key:
        for c in ("sharepoint access", "document access"):
            CONCEPT_TO_TOPIC[normalise_text(c)] = access_key

    nav_key = topic_by_name.get("navigation instructions")
    if nav_key:
        CONCEPT_TO_TOPIC[normalise_text("sharepoint navigation")] = nav_key

    best_practice_key = topic_by_name.get("ipa sharepoint best practices")
    if best_practice_key:
        CONCEPT_TO_TOPIC[normalise_text("best practices")] = best_practice_key

    faq_key = topic_by_name.get("ipa sharepoint faq")
    if faq_key:
        CONCEPT_TO_TOPIC[normalise_text("faq")] = faq_key

    usecases_key = topic_by_name.get("sharepoint usecases")
    if usecases_key:
        CONCEPT_TO_TOPIC[normalise_text("sharepoint use cases")] = usecases_key

    doc_access_key = topic_by_name.get("document access")
    if doc_access_key:
        CONCEPT_TO_TOPIC[normalise_text("document access")] = doc_access_key


# Load data at startup
load_all_training_data()


# ============================================================
# INTENT DETECTION
# ============================================================

def detect_concept(user_message: str) -> Tuple[Optional[str], Optional[str], int]:
    """
    Stronger intent detection:
    - Multi-stage scoring
    - Longer phrase priority
    - Concept weight boosting
    - Hybrid fuzzy and substring matching
    """
    msg_norm = normalise_text(user_message)
    if not msg_norm:
        return None, None, 0

    best_concept = None
    best_score = 0

    # Weight multipliers for certain domains (keys are normalised)
    WEIGHTS = {
        "annual leave": 1.35,
        "bank holidays": 1.35,
        "working hours": 1.30,
        "hr policies": 1.25,
        "sharepoint access": 1.25,
        "sharepoint purpose": 1.25,
        "sharepoint navigation": 1.25,
        "sharepoint use cases": 1.25,
        "document access": 1.22,
        "collaboration": 1.20,
        "compliance governance": 1.20,
        "advanced features": 1.18,
        "training learning": 1.18,
        "communication updates": 1.15,
        "integration": 1.15,
        "troubleshooting": 1.20,
        "best practices": 1.15,
        "onboarding": 1.10,
        "it support": 1.15,
    }

    # 1) Direct phrase detection (prioritise longer phrases)
    for phrase, concept in CONCEPT_SYNONYMS.items():
        phrase_norm = phrase  # already normalised when stored
        concept_norm = normalise_text(concept)
        if phrase_norm and phrase_norm in msg_norm:
            score = len(phrase_norm) * 4
            score *= WEIGHTS.get(concept_norm, 1)
            if score > best_score:
                best_score = score
                best_concept = concept_norm

    # 2) Fuzzy matching against canonical concepts
    concepts = list(set(CONCEPT_SYNONYMS.values()))
    if concepts:
        concepts_norm = [normalise_text(c) for c in concepts]
        fuzzy_best, fuzzy_score, _ = process.extractOne(
            msg_norm, concepts_norm, scorer=fuzz.token_set_ratio
        )
        fuzzy_score *= WEIGHTS.get(fuzzy_best, 1)
        if fuzzy_score > best_score:
            best_score = fuzzy_score
            best_concept = fuzzy_best

    # 3) Semantic fingerprints for very common HR framings
    if any(k in msg_norm for k in ("holiday", "annual leave", "vacation", "holiday days", "leave days")):
        best_concept = "annual leave"
        best_score = max(best_score, 95)

    if "bank holiday" in msg_norm or "public holiday" in msg_norm:
        best_concept = "bank holidays"
        best_score = max(best_score, 95)

    if "working time" in msg_norm or ("hours" in msg_norm and "bank" not in msg_norm):
        best_concept = "working hours"
        best_score = max(best_score, 90)

    if "onboard" in msg_norm or "new starter" in msg_norm or "new joiner" in msg_norm:
        best_concept = "onboarding"
        best_score = max(best_score, 88)

    if not best_concept:
        return None, None, 0

    canonical_norm = normalise_text(best_concept)
    topic_key = CONCEPT_TO_TOPIC.get(canonical_norm)
    return canonical_norm, topic_key, int(best_score)


# ============================================================
# ANSWER BUILDERS FOR KEY CONCEPTS
# ============================================================

def answer_annual_leave() -> str:
    """
    HR-safe high-level answer for annual leave.
    """
    return (
        "🗓️ **Annual Leave / Holiday Entitlement**\n\n"
        "Your exact annual leave entitlement depends on your role, location, and contract.\n\n"
        "For HR-approved information, always refer to:\n"
        "• Your employment contract\n"
        "• The official HR / Working Time Regulations policy\n"
        "• Your time-off balance in the HR system (e.g. Workday / Time@Schneider)\n\n"
        "You can also review the **Working Time Regulations** section on the IPA Hub for detailed guidance."
    )


def answer_bank_holidays(user_message: str) -> str:
    """
    Use FAQ entries (mainly from Working Time Regulations) to give a
    *short* targeted answer about bank holidays – not the whole file.
    """
    # Try direct FAQ retrieval first
    hr_queries = [
        user_message,
        "where can i find official bank holiday dates",
        "where are uk bank holidays listed",
        "where do i find bank holiday information",
        "where are the bank holidays listed",
    ]
    for q in hr_queries:
        ans = search_faq_for_answer(q)
        if ans:
            return ans

    # Fallback, HR-safe
    return (
        "🏦 **Bank Holidays Information**\n\n"
        "Official UK bank holiday dates are published on the UK Government website:\n"
        "https://www.gov.uk/bank-holidays\n\n"
        "Bank holidays may be included in, or in addition to, your annual leave entitlement depending "
        "on your contract and location. For an HR-approved answer, please check the **Working Time "
        "Regulations** policy or your contract."
    )


def answer_working_hours() -> str:
    return (
        "⌚ **Working Time / Standard Working Hours**\n\n"
        "Standard working patterns are defined in Schneider Electric’s **Working Time Regulations**.\n\n"
        "Key points include:\n"
        "• Your contracted weekly hours and core working times\n"
        "• Rules for rest breaks and daily/weekly rest periods\n"
        "• Guidance for night work and flexible working where applicable\n\n"
        "For an HR-proof answer specific to *you*, please check:\n"
        "• Your contract or offer letter\n"
        "• The official Working Time Regulations policy on the IPA Hub\n"
        "• Any local agreements with your manager or HR."
    )


def answer_sharepoint_access() -> str:
    """
    Prefer a focused FAQ-style answer instead of dumping a whole topic file.
    """
    # Try to find the "What can I access on SharePoint" Q/A from the FAQ first
    canonical_queries = [
        "what can i access on sharepoint",
        "what can i access on the ipa sharepoint",
        "what does the sharepoint allow me to access",
        "what can i access on the ipa hub",
    ]
    for q in canonical_queries:
        ans = search_faq_for_answer(q)
        if ans:
            return ans

    # Fallback, concise summary
    return (
        "🔐 **What You Can Access on the IPA SharePoint Hub**\n\n"
        "On the IPA SharePoint Hub you can typically access:\n"
        "• Policies and governance documents\n"
        "• Templates & tools\n"
        "• Training & onboarding materials\n"
        "• Troubleshooting guides\n"
        "• Project and team resources\n\n"
        "Access can vary by role and permissions. If you see **“Access denied”**, please contact "
        "the page owner or IT support."
    )


def answer_sharepoint_purpose() -> str:
    """
    Short, clear explanation of *why* SharePoint is used.
    """
    return (
        "📘 **Why We Use SharePoint**\n\n"
        "SharePoint is used as a central, secure hub for documents, templates, policies, and collaboration.\n"
        "It helps teams to:\n"
        "• Work from a single, trusted source of information\n"
        "• Collaborate on documents with version history and approval workflows\n"
        "• Access content from anywhere with the right permissions\n"
        "• Support governance, compliance, and audit requirements."
    )


def answer_best_practices() -> str:
    """
    If a dedicated Best Practices topic exists, we can still use it;
    otherwise return a short best-practice list.
    """
    for key, title in TOPIC_TITLES.items():
        if "best practice" in title.lower():
            # To avoid dumping *everything*, slice to a reasonable length
            content = TOPIC_CONTENT.get(key, "")
            return content[:3000].strip() or content

    return (
        "✅ **IPA SharePoint Best Practices**\n\n"
        "• Use clear, specific keywords in the search bar\n"
        "• Bookmark or 'Follow' your key pages and hubs\n"
        "• Keep documents up to date and remove duplicates\n"
        "• Use metadata tags and sensible file names to improve search\n"
        "• Follow permission guidelines and avoid oversharing externally\n"
        "• Use version history instead of saving multiple copies of a file\n"
        "• Sync important libraries with OneDrive for offline access."
    )


def answer_troubleshooting(user_message: str) -> str:
    """
    Troubleshooting should be *targeted*:
    - try FAQ-style answer first (e.g. “I found a broken link”)
    - only fall back to long generic guidance when nothing matches.
    """
    # First: try the global FAQ list so we pick a single Q/A, not the full file
    faq_ans = search_faq_for_answer(user_message)
    if faq_ans:
        return faq_ans

    # If that fails, see if there's a dedicated Troubleshooting topic and
    # use only the first part of it so we don't dump the entire training file.
    for key, title in TOPIC_TITLES.items():
        if "troubleshooting" in title.lower():
            content = TOPIC_CONTENT.get(key, "")
            return content[:3000].strip() or content

    # Final fallback: generic trouble-shooting
    return (
        "🛠️ **SharePoint Troubleshooting – Quick Checks**\n\n"
        "If something isn’t working, try these steps:\n"
        "• Check VPN and network connectivity\n"
        "• Try a different browser (e.g. Edge or Chrome) or an Incognito/Private window\n"
        "• Clear your browser cache and cookies\n"
        "• If you see **“Access denied”**, use the Request Access option or contact the page owner\n"
        "• For sync problems, restart OneDrive and confirm you are logged in with your SE account\n\n"
        "If the issue continues, please contact IT support with a screenshot of the error."
    )


def answer_onboarding() -> str:
    return (
        "👋 **Onboarding & New Starter Resources**\n\n"
        "Onboarding content is usually found in the **UK&I Onboarding Hub** on the IPA SharePoint.\n"
        "Look for:\n"
        "• Onboarding checklists\n"
        "• Mandatory training and e-learning\n"
        "• Key links for HR, IT setup, and local processes\n\n"
        "If you’re unsure which hub or page applies to you, please check with your manager or HR."
    )


def answer_maintenance() -> str:
    if MAINTENANCE_TEXT:
        return MAINTENANCE_TEXT

    return (
        "🧩 **Chatbot Maintenance & Updates**\n\n"
        "The chatbot is maintained as a companion to the IPA SharePoint Hub. "
        "Content and logic are reviewed regularly, with updates typically aligned "
        "to monthly SharePoint or process changes."
    )


# ============================================================
# SEARCH HELPERS
# ============================================================

def search_faq_for_answer(msg: str) -> Optional[str]:
    """
    Improved FAQ matching with:
    - strong minimum score
    - multi-pass fuzzy scoring
    - question block matching
    Always returns just the *answer* (A:), not the full training file.
    """
    if not FAQ_LIST:
        return None

    msg_norm = normalise_text(msg)

    questions = [entry["q_norm"] for entry in FAQ_LIST]

    best_norm, score_norm, _ = process.extractOne(
        msg_norm, questions, scorer=fuzz.token_set_ratio
    )
    best_partial, score_partial, _ = process.extractOne(
        msg_norm, questions, scorer=fuzz.partial_ratio
    )

    best_score = max(score_norm, score_partial)
    if best_score < 65:
        return None

    for entry in FAQ_LIST:
        if entry["q_norm"] in (best_norm, best_partial):
            return entry["a"]

    return None


def search_topics_for_answer(msg: str) -> Optional[str]:
    """
    Fuzzy match against topic titles and content.
    Used as a *fallback* when we don't have a clear FAQ/intent match.

    To avoid huge walls of text, we truncate long content responses
    to a sensible size (e.g. 3000 characters).
    """
    if not TOPIC_CONTENT:
        return None

    msg_norm = normalise_text(msg)

    # Match on titles
    titles_norm = [normalise_text(t) for t in TOPIC_TITLES.values()]
    best_title_norm, score_title, _ = process.extractOne(
        msg_norm, titles_norm, scorer=fuzz.token_set_ratio
    )

    chosen_key = None
    if score_title >= 70:
        for key, title in TOPIC_TITLES.items():
            if normalise_text(title) == best_title_norm:
                chosen_key = key
                break

    # If no strong title, match content
    if not chosen_key:
        contents = list(TOPIC_CONTENT.values())
        best_content, score_content, idx = process.extractOne(
            msg_norm, contents, scorer=fuzz.partial_ratio
        )
        if score_content >= 70:
            chosen_key = list(TOPIC_CONTENT.keys())[idx]

    if not chosen_key:
        return None

    content = TOPIC_CONTENT.get(chosen_key, "")
    # Trim over-long content to keep responses readable
    if len(content) > 3000:
        return content[:3000].rstrip() + "\n\n_(Response truncated for readability – open the page on SharePoint for full details.)_"
    return content


def list_all_topics() -> str:
    if not TOPIC_TITLES:
        return "I don't have any topics loaded yet. Please check the training data folder."

    lines = ["Here are the main topics I can help with:\n"]
    for title in sorted(TOPIC_TITLES.values()):
        lines.append(f"• {title}")
    return "\n".join(lines)


def extract_navigation_target(msg: str) -> Optional[str]:
    """
    Pulls out the 'thing' the user wants to find:
    e.g. 'Where is NextGen Framework?' → 'NextGen Framework'
    """
    msg_clean = msg.replace("?", "").strip().lower()

    triggers = [
        "where do i find",
        "where can i find",
        "where is",
        "how do i get to",
        "navigate to",
        "open",
        "access",
    ]
    for t in triggers:
        if msg_clean.startswith(t):
            return msg_clean[len(t):].strip()

    return None


# ============================================================
# MAIN RESPONSE FUNCTION
# ============================================================

def generate_response(user_message: str) -> str:
    msg = user_message.strip()
    msg_norm = normalise_text(msg)

    if not msg_norm:
        return "Please type a question or topic about the IPA Hub or SharePoint, and I’ll do my best to help."

    tokens = msg_norm.split()

    # Greetings / small talk
    if any(t in tokens for t in ("hello", "hi", "hey")) or \
       "good morning" in msg_norm or "good afternoon" in msg_norm or "good evening" in msg_norm:
        return (
            "Hi! I’m your IPA Hub Navigation Assistant 👋\n\n"
            "You can ask me about:\n"
            "• Annual leave and working time policies\n"
            "• Where to find templates, tools, or training\n"
            "• What you can access on the IPA SharePoint Hub\n"
            "• Troubleshooting issues (access, errors, broken links)\n\n"
            "Try something like: *How many annual leave days do I get?* or "
            "*Where do I find onboarding resources?*"
        )

    # Thanks / closing
    if "thank" in msg_norm or "thanks" in msg_norm:
        return (
            "You’re welcome! 😊\n\n"
            "If you have another question about the IPA Hub, SharePoint, HR topics, or navigation, "
            "just type it and I’ll help you again."
        )

    # Capabilities / help
    if "what can you do" in msg_norm or msg_norm in ("help", "help me", "how do you work"):
        return (
            "I can help you navigate the IPA SharePoint Hub and answer common questions.\n\n"
            "You can ask me to:\n"
            "• Explain **why we use SharePoint** or what it allows you to access\n"
            "• Find **templates, governance packs, or training pages**\n"
            "• Clarify **annual leave**, **bank holidays** and **working time** policies (HR-safe guidance)\n"
            "• Provide **troubleshooting tips** if something is not working\n"
            "• Explain **how to use SharePoint effectively** (best practices, collaboration, integrations)\n\n"
            "You can also type **main topics** to see everything I know."
        )

    # Main topics
    if "main topics" in msg_norm or ("what" in msg_norm and "topics" in msg_norm):
        return list_all_topics()

    # Maintenance / updates questions
    if any(k in msg_norm for k in ("maintenance", "updated", "version", "release notes", "changelog")):
        return answer_maintenance()

    # Navigation-specific wording
    if any(k in msg_norm for k in ("where do i find", "where can i find", "where is", "how do i get to", "navigate to")):
        target = extract_navigation_target(msg)
        if target:
            nav_answer = search_topics_for_answer(target)
            if nav_answer:
                return nav_answer

        if NAVIGATION_TEXT:
            # We still trim in case NAVIGATION_TEXT is huge
            nav = NAVIGATION_TEXT
            if len(nav) > 3000:
                nav = nav[:3000].rstrip() + "\n\n_(Response truncated – open the navigation guide on SharePoint for full details.)_"
            return nav

    # Core concept detection
    concept, topic_key, score = detect_concept(msg)

    if concept:
        if concept == normalise_text("annual leave"):
            return answer_annual_leave()
        if concept == normalise_text("bank holidays"):
            return answer_bank_holidays(msg)
        if concept == normalise_text("working hours"):
            return answer_working_hours()
        if concept == normalise_text("sharepoint access"):
            return answer_sharepoint_access()
        if concept == normalise_text("sharepoint purpose") or concept == normalise_text("sharepoint use cases"):
            return answer_sharepoint_purpose()
        if concept == normalise_text("best practices"):
            return answer_best_practices()
        if concept == normalise_text("troubleshooting") or concept == normalise_text("it support"):
            return answer_troubleshooting(msg)
        if concept == normalise_text("onboarding"):
            return answer_onboarding()

        # For all other concepts (document access, collaboration, training, etc.)
        if topic_key and topic_key in TOPIC_CONTENT:
            # Use FAQ first if available (to keep answers short)
            faq_ans = search_faq_for_answer(msg)
            if faq_ans:
                return faq_ans
            return search_topics_for_answer(msg) or TOPIC_CONTENT[topic_key]

    # Global FAQ match
    faq_answer = search_faq_for_answer(msg)
    if faq_answer:
        return faq_answer

    # Topic-based fallback
    topic_answer = search_topics_for_answer(msg)
    if topic_answer:
        return topic_answer

    # Final rich fallback (no more “I don’t know”)
    return (
        "I haven’t found an exact match, but here are the main areas I can help with:\n\n"
        "• **Annual leave**, bank holidays, working hours, HR policies\n"
        "• **Where to find pages**, tools, documents, and training on the IPA Hub\n"
        "• **What SharePoint is used for** and what you can access\n"
        "• **Troubleshooting** issues such as access denied, missing pages, slow loading\n"
        "• **Best practices**, governance, onboarding, collaboration, integrations and navigation\n\n"
        "Try asking for a topic directly — for example: *Working Time Regulations*, *Best Practices*, "
        "or *What can I access on SharePoint?*"
    )


# ============================================================
# FLASK ROUTES
# ============================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def get_reply():
    """
    Expects JSON: { "message": "user question" }
    Returns JSON: { "reply": "bot answer" }
    """
    data = request.get_json(force=True, silent=True) or {}
    user_message = data.get("message", "") or ""
    reply = generate_response(user_message)
    return jsonify({"reply": reply})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

