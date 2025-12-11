"""
Refactored IPA Hub / SharePoint Chatbot
---------------------------------------

Drop this file in as app.py in the same project where you had the old version.

Key improvements vs original:
- Encapsulated in ChatbotEngine (no global mutable dict soup).
- Stronger concept + FAQ + topic matching with local topic weighting.
- Smart answer length limiting via safe_snippet() (no more giant blocks).
- Navigation-aware search and concept-aware FAQ selection.
- Clear configuration section to tweak behaviour without touching core logic.
"""

from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

from flask import Flask, render_template, request, jsonify
from rapidfuzz import fuzz, process

# ============================================================
# CONFIGURATION
# ============================================================

DATA_FOLDER = "chatbot_data"          # Folder with *.txt training files
MAX_ANSWER_CHARS = 1300               # Hard cap for answer length to user
MIN_FAQ_SCORE = 60                    # Min fuzzy score to accept an FAQ hit
MIN_TOPIC_SCORE = 70                  # Min fuzzy score to accept a topic hit
NAV_TRUNC_LIMIT = 1600                # Max chars for navigation responses
DEBUG_LOGGING = False                 # Set True if you want console logging

# Logging setup
logging.basicConfig(
    level=logging.DEBUG if DEBUG_LOGGING else logging.INFO,
    format="[%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class FAQEntry:
    """Represents a single FAQ question/answer block."""
    q_raw: str
    q_norm: str
    a: str
    topic_key: str


@dataclass
class Topic:
    """Represents a training topic (.txt file)."""
    key: str
    title: str
    content: str


@dataclass
class ConceptConfig:
    """Holds synonym and mapping info for a canonical concept."""
    canonical_norm: str
    weight: float = 1.0
    topic_override: Optional[str] = None


# ============================================================
# UTILS
# ============================================================

def normalise_text(text: str) -> str:
    """Lowercase and strip to alphanumeric + spaces for consistent matching."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def to_topic_key(name: str) -> str:
    """Turn a filename/title into an internal topic key."""
    return normalise_text(name).replace(" ", "_")


def read_file_safely(path: str) -> str:
    """Read text file trying UTF-8 then latin-1 as fallback."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, "r", encoding="latin-1") as f:
            return f.read()


def clean_whitespace_block(text: str) -> str:
    """Reduce weird spacing so content looks better in chat."""
    cleaned = re.sub(r"\s+\n", "\n", text.strip())
    cleaned = re.sub(r"\n\s+", "\n", cleaned)
    return cleaned


def safe_snippet(text: str, max_chars: int = MAX_ANSWER_CHARS) -> str:
    """
    Return a readable snippet up to max_chars.
    Aims to cut on paragraph boundaries instead of mid-sentence.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text

    # Split by double newlines (paragraphs)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    result_parts: List[str] = []
    current_len = 0

    for p in paragraphs:
        # If adding this paragraph would exceed the max too much, stop
        if current_len + len(p) + 2 > max_chars:
            break
        result_parts.append(p)
        current_len += len(p) + 2  # account for "\n\n"

    if not result_parts:
        # Fallback: hard cut
        snippet = text[:max_chars].rstrip()
    else:
        snippet = "\n\n".join(result_parts).rstrip()

    return snippet + (
        "\n\n_(Answer shortened for readability – "
        "please open the full page on SharePoint/IPA Hub if you need all details.)_"
    )


def contains_any(msg_norm: str, words: List[str]) -> bool:
    """True if any of the provided (already normalised) words appear in the msg."""
    tokens = msg_norm.split()
    token_set = set(tokens)
    return any(w in token_set for w in words)


# ============================================================
# CHATBOT ENGINE
# ============================================================

class ChatbotEngine:
    """
    Core logic for the IPA Hub / SharePoint chatbot.

    - Loads training data and builds internal indices
    - Performs concept / FAQ / topic matching
    - Generates user-facing responses
    """

    def __init__(self, data_folder: str = DATA_FOLDER):
        self.data_folder = data_folder

        self.topics: Dict[str, Topic] = {}
        self.raw_files: Dict[str, str] = {}
        self.faq_list: List[FAQEntry] = []

        # phrase (synonym normalised) -> canonical concept normalised
        self.concept_synonyms: Dict[str, str] = {}

        # canonical concept normalised -> ConceptConfig
        self.concept_configs: Dict[str, ConceptConfig] = {}

        # canonical concept normalised -> topic key
        self.concept_to_topic: Dict[str, str] = {}

        # Special text blocks
        self.maintenance_text: Optional[str] = None
        self.navigation_text: Optional[str] = None

        logger.info("Initialising ChatbotEngine...")
        self.load_all_training_data()
        logger.info(
            "Loaded %d topics, %d FAQ entries, %d concepts",
            len(self.topics),
            len(self.faq_list),
            len(self.concept_synonyms),
        )

    # --------------------------------------------------------
    # TOPIC & CONCEPT REGISTRATION
    # --------------------------------------------------------

    def register_topic(self, title: str, content: str) -> str:
        """Create and store a Topic from a file or training block."""
        key = to_topic_key(title)
        topic = Topic(
            key=key,
            title=title.strip(),
            content=clean_whitespace_block(content),
        )
        self.topics[key] = topic
        return key

    def register_concept(self, canonical: str, phrases: List[str], weight: float = 1.0):
        """
        Add canonical concept and all its phrases to the synonym table.
        Weight influences scoring priority during intent detection.
        """
        canonical_norm = normalise_text(canonical)
        cfg = self.concept_configs.get(canonical_norm)
        if not cfg:
            cfg = ConceptConfig(canonical_norm=canonical_norm, weight=weight)
            self.concept_configs[canonical_norm] = cfg
        else:
            # keep the highest weight defined
            cfg.weight = max(cfg.weight, weight)

        for phrase in phrases:
            p = normalise_text(phrase)
            if not p:
                continue
            existing = self.concept_synonyms.get(p)
            if existing:
                # Prefer shorter canonical names (more general) if equal weight
                if len(canonical_norm) < len(existing):
                    self.concept_synonyms[p] = canonical_norm
            else:
                self.concept_synonyms[p] = canonical_norm

    # --------------------------------------------------------
    # PARSERS
    # --------------------------------------------------------

    def parse_faq_file(self, text: str, base_name: str):
        """
        Parse Q/A style FAQ documents.

        Pattern:
            Section (optional)
            Q: question text
            Q: alternative phrasing
            ...
            A: answer text
        """
        base_topic_key = to_topic_key(base_name)
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
            a_text = a_raw.strip()
            if not a_text:
                continue

            # Strip non-question headings
            q_lines = [ln.strip() for ln in q_raw.splitlines() if ln.strip()]
            question_lines = [ln for ln in q_lines if "?" in ln]

            question_block = " ".join(question_lines) if question_lines else q_raw
            q_norm = normalise_text(question_block)
            if not q_norm:
                continue

            self.faq_list.append(
                FAQEntry(
                    q_raw=question_block,
                    q_norm=q_norm,
                    a=clean_whitespace_block(a_text),
                    topic_key=base_topic_key,
                )
            )

    def parse_keywords_and_concepts(self, text: str):
        """
        From 'Keywords & Tags.txt' we only need the CANONICAL CONCEPT MAPPINGS section.
        Example:
            - Working Hours → working hours, work schedule, office hours...
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
            self.register_concept(canonical, phrases)

    def parse_synonyms_file(self, text: str):
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
            self.register_concept(canonical, phrases)

    # --------------------------------------------------------
    # LOADER
    # --------------------------------------------------------

    def load_all_training_data(self):
        """Load all training .txt files, topics, FAQ, and concept mappings."""
        if not os.path.isdir(self.data_folder):
            logger.warning("Training data folder '%s' not found.", self.data_folder)
            return

        for filename in os.listdir(self.data_folder):
            if not filename.lower().endswith(".txt"):
                continue

            path = os.path.join(self.data_folder, filename)
            content = read_file_safely(path)
            base = filename[:-4].strip()
            base_lower = base.lower()

            self.raw_files[base_lower] = content

            # Every file becomes a topic
            topic_key = self.register_topic(base, content)

            has_q = re.search(r"\bQ:", content, flags=re.IGNORECASE) is not None
            has_a = re.search(r"\bA:", content, flags=re.IGNORECASE) is not None

            if "keyword" in base_lower:
                self.parse_keywords_and_concepts(content)
            elif "synonym" in base_lower:
                self.parse_synonyms_file(content)
            elif "maintenance" in base_lower:
                self.maintenance_text = clean_whitespace_block(content)
            elif "navigation" in base_lower:
                self.navigation_text = safe_snippet(
                    clean_whitespace_block(content),
                    max_chars=NAV_TRUNC_LIMIT,
                )

            # Parse FAQ-style entries from any Q/A-like file
            if "faq" in base_lower or (has_q and has_a):
                self.parse_faq_file(content, base)

        # After all files are loaded, extend manual concepts and link to topics
        self.add_manual_concepts()
        self.build_concept_to_topic_mapping()

    # --------------------------------------------------------
    # MANUAL CONCEPTS & MAPPING
    # --------------------------------------------------------

    def add_manual_concepts(self):
        """Register important HR and SharePoint concepts manually."""
        manual = {
            # Core HR
            "Annual Leave": (
                [
                    "annual leave",
                    "annual leave days",
                    "how many annual leave days",
                    "how many holidays",
                    "holiday entitlement",
                    "holiday days",
                    "vacation days",
                    "paid time off",
                    "pto",
                    "leave allowance",
                    "holiday allowance",
                ],
                1.4,
            ),
            "Bank Holidays": (
                [
                    "bank holiday",
                    "bank holidays",
                    "public holiday",
                    "public holidays",
                    "uk bank holidays",
                    "bank holiday dates",
                ],
                1.4,
            ),
            "Working Hours": (
                [
                    "working hours",
                    "work hours",
                    "working time",
                    "working time regulations",
                    "normal working hours",
                    "core hours",
                    "hours per week",
                    "shift pattern",
                    "start time",
                    "finish time",
                ],
                1.35,
            ),
            "HR Policies": (
                [
                    "hr policies",
                    "hr policy",
                    "company policies",
                    "hr rules",
                    "hr guidance",
                    "where are hr policies",
                ],
                1.2,
            ),
            # SharePoint core
            "SharePoint Access": (
                [
                    "what can i access on sharepoint",
                    "what can i access on the ipa sharepoint",
                    "sharepoint access",
                    "access on ipa hub",
                    "what is on the sharepoint",
                ],
                1.3,
            ),
            "SharePoint Purpose": (
                [
                    "why do we use a sharepoint",
                    "why sharepoint",
                    "purpose of sharepoint",
                    "why do we use sharepoint",
                ],
                1.25,
            ),
            "SharePoint Navigation": (
                [
                    "where do i find",
                    "where can i find",
                    "where is",
                    "navigate to",
                    "how do i get to",
                    "how do i find",
                    "navigation",
                    "sharepoint navigation",
                ],
                1.25,
            ),
            "SharePoint Use Cases": (
                [
                    "sharepoint use cases",
                    "what is sharepoint used for",
                    "how do we use sharepoint",
                    "examples of sharepoint usage",
                ],
                1.25,
            ),
            # Themed topics
            "Document Access": (
                [
                    "access hr policies",
                    "where are policies stored",
                    "find templates",
                    "project templates",
                    "governance packs",
                    "open training materials",
                    "where are finance templates",
                    "document access",
                ],
                1.22,
            ),
            "Troubleshooting": (
                [
                    "troubleshooting",
                    "problem",
                    "issue",
                    "error",
                    "access denied",
                    "page not loading",
                    "broken link",
                    "sharepoint not loading",
                    "vpn issue",
                    "sync issue",
                ],
                1.25,
            ),
            "Best Practices": (
                [
                    "best practice",
                    "best practices",
                    "sharepoint tips",
                    "sharepoint guidelines",
                    "sharepoint best practices",
                ],
                1.2,
            ),
            "Onboarding": (
                [
                    "onboarding",
                    "new hire",
                    "induction",
                    "joiner",
                    "welcome programme",
                    "onboarding checklist",
                    "new starter",
                ],
                1.15,
            ),
            "IT Support": (
                [
                    "it support",
                    "it help",
                    "password reset",
                    "vpn not working",
                    "laptop issue",
                    "wifi issue",
                ],
                1.15,
            ),
        }

        for canonical, (phrases, weight) in manual.items():
            self.register_concept(canonical, phrases, weight=weight)

    def build_concept_to_topic_mapping(self):
        """Map canonical concepts to the most relevant topic (.txt file)."""
        concepts = sorted(set(self.concept_synonyms.values()))
        if not concepts or not self.topics:
            return

        topic_items = list(self.topics.items())  # (key, Topic)

        # Basic fuzzy matching concept -> topic title
        for concept in concepts:
            c_norm = normalise_text(concept)
            best_topic_key: Optional[str] = None
            best_score = 0

            for key, topic in topic_items:
                score = fuzz.token_set_ratio(c_norm, normalise_text(topic.title))
                if score > best_score:
                    best_score = score
                    best_topic_key = key

            if best_topic_key and best_score >= 60:
                self.concept_to_topic[c_norm] = best_topic_key

        # Helpful manual overrides based on known filenames
        topic_by_name = {normalise_text(t.title): k for k, t in self.topics.items()}

        wtr_key = topic_by_name.get("working time regulations")
        if wtr_key:
            for c in ("annual leave", "working hours", "bank holidays", "hr policies"):
                self.concept_to_topic[normalise_text(c)] = wtr_key

        why_sp_key = topic_by_name.get("why do we use a sharepoint")
        if why_sp_key:
            for c in ("sharepoint purpose", "sharepoint use cases"):
                self.concept_to_topic[normalise_text(c)] = why_sp_key

        access_key = topic_by_name.get("what does the sharepoint allow me to access")
        if access_key:
            for c in ("sharepoint access", "document access"):
                self.concept_to_topic[normalise_text(c)] = access_key

        nav_key = topic_by_name.get("navigation instructions")
        if nav_key:
            self.concept_to_topic[normalise_text("sharepoint navigation")] = nav_key

        best_practice_key = topic_by_name.get("ipa sharepoint best practices")
        if best_practice_key:
            self.concept_to_topic[normalise_text("best practices")] = best_practice_key

        faq_key = topic_by_name.get("ipa sharepoint faq")
        if faq_key:
            self.concept_to_topic[normalise_text("faq")] = faq_key

        usecases_key = topic_by_name.get("sharepoint usecases")
        if usecases_key:
            self.concept_to_topic[normalise_text("sharepoint use cases")] = usecases_key

        doc_access_key = topic_by_name.get("document access")
        if doc_access_key:
            self.concept_to_topic[normalise_text("document access")] = doc_access_key

    # --------------------------------------------------------
    # INTENT DETECTION
    # --------------------------------------------------------

    def detect_concept(self, user_message: str) -> Tuple[Optional[str], Optional[str], int]:
        """
        Stronger intent detection:
        - Direct phrase detection with word-boundary style protection
        - Fuzzy matching against canonical concepts
        - HR-specific heuristic boosts
        """
        msg_norm = normalise_text(user_message)
        if not msg_norm:
            return None, None, 0

        best_concept: Optional[str] = None
        best_score: float = 0.0

        # 1) Direct phrase detection (prioritise longer phrases)
        msg_padded = f" {msg_norm} "
        for phrase_norm, concept_norm in self.concept_synonyms.items():
            # approximate word-boundary check
            if f" {phrase_norm} " in msg_padded:
                length_factor = len(phrase_norm)
                cfg = self.concept_configs.get(concept_norm)
                weight = cfg.weight if cfg else 1.0
                score = length_factor * 4 * weight
                if score > best_score:
                    best_score = score
                    best_concept = concept_norm

        # 2) Fuzzy matching against canonical concepts
        canonical_list = list(self.concept_configs.keys())
        if canonical_list:
            fuzzy_best, fuzzy_score, _ = process.extractOne(
                msg_norm, canonical_list, scorer=fuzz.token_set_ratio
            )
            cfg = self.concept_configs.get(fuzzy_best)
            if cfg:
                fuzzy_score *= cfg.weight
            if fuzzy_score > best_score:
                best_score = fuzzy_score
                best_concept = fuzzy_best

        # 3) Domain heuristics (holidays, onboarding, etc.)
        if any(k in msg_norm for k in ("holiday", "annual leave", "vacation", "leave days")):
            best_concept = normalise_text("annual leave")
            best_score = max(best_score, 95)

        if "bank holiday" in msg_norm or "public holiday" in msg_norm:
            best_concept = normalise_text("bank holidays")
            best_score = max(best_score, 95)

        if "working time" in msg_norm or ("hours" in msg_norm and "bank" not in msg_norm):
            best_concept = normalise_text("working hours")
            best_score = max(best_score, 90)

        if "onboard" in msg_norm or "new starter" in msg_norm or "new joiner" in msg_norm:
            best_concept = normalise_text("onboarding")
            best_score = max(best_score, 88)

        if not best_concept:
            return None, None, 0

        topic_key = self.concept_to_topic.get(best_concept)
        return best_concept, topic_key, int(best_score)

    # --------------------------------------------------------
    # SEARCH HELPERS
    # --------------------------------------------------------

    def search_faq_for_answer(
        self,
        msg: str,
        preferred_topic: Optional[str] = None,
    ) -> Optional[str]:
        """
        Improved FAQ matching:
        - Evaluate each FAQ entry with token_set and partial ratios
        - Small boost if FAQ belongs to preferred_topic
        - Returns a single concise A: block
        """
        if not self.faq_list:
            return None

        msg_norm = normalise_text(msg)
        best_entry: Optional[FAQEntry] = None
        best_score: float = 0.0

        for entry in self.faq_list:
            score1 = fuzz.token_set_ratio(msg_norm, entry.q_norm)
            score2 = fuzz.partial_ratio(msg_norm, entry.q_norm)
            score = max(score1, score2)

            if preferred_topic and entry.topic_key == preferred_topic:
                score += 7  # local topic boost

            if score > best_score:
                best_score = score
                best_entry = entry

        if not best_entry or best_score < MIN_FAQ_SCORE:
            return None

        return safe_snippet(best_entry.a)

    def search_topics_for_answer(
        self,
        msg: str,
        preferred_topic: Optional[str] = None,
    ) -> Optional[str]:
        """
        Fuzzy match against topic titles and content.
        Used as fallback when FAQ/intent isn't enough.

        Returns a snippet, never a giant wall of text.
        """
        if not self.topics:
            return None

        msg_norm = normalise_text(msg)

        # 1) If we already have a strongly suggested topic, use that first
        if preferred_topic and preferred_topic in self.topics:
            content = self.topics[preferred_topic].content
            if content:
                return safe_snippet(content)

        # 2) Fuzzy match on titles
        titles_norm = [normalise_text(t.title) for t in self.topics.values()]
        best_title_norm, score_title, _ = process.extractOne(
            msg_norm, titles_norm, scorer=fuzz.token_set_ratio
        )

        chosen_key: Optional[str] = None
        if score_title >= MIN_TOPIC_SCORE:
            for key, topic in self.topics.items():
                if normalise_text(topic.title) == best_title_norm:
                    chosen_key = key
                    break

        # 3) If no strong title, fuzzy match on content
        if not chosen_key:
            contents = [t.content for t in self.topics.values()]
            best_content, score_content, idx = process.extractOne(
                msg_norm, contents, scorer=fuzz.partial_ratio
            )
            if score_content >= MIN_TOPIC_SCORE:
                chosen_key = list(self.topics.keys())[idx]

        if not chosen_key:
            return None

        return safe_snippet(self.topics[chosen_key].content)

    def list_all_topics(self) -> str:
        if not self.topics:
            return "I don't have any topics loaded yet. Please check the training data folder."

        lines = ["Here are the main topics I can help with:\n"]
        for topic in sorted(self.topics.values(), key=lambda t: t.title.lower()):
            lines.append(f"• {topic.title}")
        return "\n".join(lines)

    @staticmethod
    def extract_navigation_target(msg: str) -> Optional[str]:
        """
        Pull out the 'thing' the user wants to find:
        e.g. 'Where is NextGen Framework?' → 'NextGen Framework'
        """
        msg_strip = msg.strip()
        msg_lower = msg_strip.lower().replace("?", "")

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
            if msg_lower.startswith(t):
                target = msg_strip[len(t):].strip()
                return target or None
        return None

    # --------------------------------------------------------
    # ANSWER TEMPLATES
    # --------------------------------------------------------

    @staticmethod
    def answer_annual_leave() -> str:
        return (
            "🗓️ **Annual Leave / Holiday Entitlement**\n\n"
            "Your exact annual leave entitlement depends on your role, location, and contract.\n\n"
            "For HR-approved information, always refer to:\n"
            "• Your employment contract\n"
            "• The official HR / Working Time Regulations policy\n"
            "• Your time-off balance in the HR system (e.g. Workday / Time@Schneider)\n\n"
            "You can also review the **Working Time Regulations** section on the IPA Hub for detailed guidance."
        )

    def answer_bank_holidays(self, user_message: str) -> str:
        # Try FAQ first
        hr_queries = [
            user_message,
            "where can i find official bank holiday dates",
            "where are uk bank holidays listed",
            "where do i find bank holiday information",
        ]
        for q in hr_queries:
            ans = self.search_faq_for_answer(q)
            if ans:
                return ans

        return (
            "🏦 **Bank Holidays Information**\n\n"
            "Official UK bank holiday dates are published on the UK Government website:\n"
            "https://www.gov.uk/bank-holidays\n\n"
            "Bank holidays may be included in, or in addition to, your annual leave entitlement depending "
            "on your contract and location. For an HR-approved answer, please check the **Working Time "
            "Regulations** policy or your contract."
        )

    @staticmethod
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

    def answer_sharepoint_access(self) -> str:
        canonical_queries = [
            "what can i access on sharepoint",
            "what can i access on the ipa sharepoint",
            "what does the sharepoint allow me to access",
            "what can i access on the ipa hub",
        ]
        for q in canonical_queries:
            ans = self.search_faq_for_answer(q)
            if ans:
                return ans

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

    @staticmethod
    def answer_sharepoint_purpose() -> str:
        return (
            "📘 **Why We Use SharePoint**\n\n"
            "SharePoint is used as a central, secure hub for documents, templates, policies, and collaboration.\n"
            "It helps teams to:\n"
            "• Work from a single, trusted source of information\n"
            "• Collaborate on documents with version history and approval workflows\n"
            "• Access content from anywhere with the right permissions\n"
            "• Support governance, compliance, and audit requirements."
        )

    def answer_best_practices(self) -> str:
        # try dedicated topic if exists
        for topic in self.topics.values():
            if "best practice" in topic.title.lower():
                return safe_snippet(topic.content)

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

    def answer_troubleshooting(self, msg: str) -> str:
        faq_ans = self.search_faq_for_answer(msg)
        if faq_ans:
            return faq_ans

        for topic in self.topics.values():
            if "troubleshooting" in topic.title.lower():
                return safe_snippet(topic.content)

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

    @staticmethod
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

    def answer_maintenance(self) -> str:
        if self.maintenance_text:
            return safe_snippet(self.maintenance_text, max_chars=MAX_ANSWER_CHARS)
        return (
            "🧩 **Chatbot Maintenance & Updates**\n\n"
            "The chatbot is maintained as a companion to the IPA SharePoint Hub. "
            "Content and logic are reviewed regularly, typically aligned to monthly "
            "SharePoint or process changes."
        )

    # --------------------------------------------------------
    # MAIN RESPONSE LOGIC
    # --------------------------------------------------------

    def generate_response(self, user_message: str) -> str:
        msg = user_message.strip()
        msg_norm = normalise_text(msg)

        if not msg_norm:
            return (
                "Please type a question or topic about the IPA Hub or SharePoint, "
                "and I’ll do my best to help."
            )

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

        # Main topics list
        if "main topics" in msg_norm or ("what" in msg_norm and "topics" in msg_norm):
            return self.list_all_topics()

        # Maintenance / updates
        if any(
            k in msg_norm
            for k in ("maintenance", "updated", "version", "release notes", "changelog")
        ):
            return self.answer_maintenance()

        # Navigation-specific wording
        if any(
            k in msg_norm
            for k in ("where do i find", "where can i find", "where is", "how do i get to", "navigate to")
        ):
            target = self.extract_navigation_target(msg)
            # Prefer conceptual/topic-aware search if we can isolate target
            if target:
                nav_ans = self.search_faq_for_answer(target)
                if nav_ans:
                    return nav_ans

                topic_ans = self.search_topics_for_answer(target)
                if topic_ans:
                    return topic_ans

            if self.navigation_text:
                return self.navigation_text

        # --- Core concept detection ---
        concept, topic_key, concept_score = self.detect_concept(msg)
        logger.debug("Concept detected: %s (topic=%s, score=%s)", concept, topic_key, concept_score)

        if concept:
            if concept == normalise_text("annual leave"):
                return self.answer_annual_leave()
            if concept == normalise_text("bank holidays"):
                return self.answer_bank_holidays(msg)
            if concept == normalise_text("working hours"):
                return self.answer_working_hours()
            if concept == normalise_text("sharepoint access"):
                return self.answer_sharepoint_access()
            if concept in (
                normalise_text("sharepoint purpose"),
                normalise_text("sharepoint use cases"),
            ):
                return self.answer_sharepoint_purpose()
            if concept == normalise_text("best practices"):
                return self.answer_best_practices()
            if concept in (
                normalise_text("troubleshooting"),
                normalise_text("it support"),
            ):
                return self.answer_troubleshooting(msg)
            if concept == normalise_text("onboarding"):
                return self.answer_onboarding()

            # All other concepts (document access, collaboration, training, etc.)
            if topic_key and topic_key in self.topics:
                # Prefer FAQ within this topic
                faq_ans = self.search_faq_for_answer(msg, preferred_topic=topic_key)
                if faq_ans:
                    return faq_ans

                topic_ans = self.search_topics_for_answer(msg, preferred_topic=topic_key)
                if topic_ans:
                    return topic_ans

        # Global FAQ match
        faq_answer = self.search_faq_for_answer(msg)
        if faq_answer:
            return faq_answer

        # Topic-based fallback
        topic_answer = self.search_topics_for_answer(msg)
        if topic_answer:
            return topic_answer

        # Final friendly fallback
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
# INITIALISE ENGINE
# ============================================================

engine = ChatbotEngine(DATA_FOLDER)


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
    reply = engine.generate_response(user_message)
    return jsonify({"reply": reply})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    # debug=False is safer for Render / production
    app.run(host="0.0.0.0", port=port, debug=False)
