from flask import Flask, render_template, request, jsonify
import os
import re
import difflib
import random

app = Flask(__name__)

DATA_FOLDER = "chatbot_data"

# ---------------------------------------------------------
# 1. LOAD TRAINING DATA (TOPICS + Q&A PAIRS)
# ---------------------------------------------------------

def parse_qa_from_content(content: str):
    """
    Parse Q/A blocks from a text file.
    Works with:
      Q: ...
      A: ...
    repeated multiple times.
    Also works if [FAQ] / [DETAIL] markers are present, but they are optional.
    """
    qa_pairs = []

    # If [FAQ] exists, restrict parsing to that section
    faq_match = re.search(r"\[FAQ\](.*?)(\[DETAIL\]|$)", content, flags=re.S | re.I)
    if faq_match:
        raw = faq_match.group(1).strip()
        detail_section = re.search(r"\[DETAIL\](.*)", content, flags=re.S | re.I)
        detail_text = detail_section.group(1).strip() if detail_section else content.strip()
    else:
        raw = content
        detail_text = content.strip()

    blocks = raw.split("Q:")
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        parts = block.split("A:", 1)
        if len(parts) == 2:
            q = parts[0].strip()
            a = parts[1].strip()
            if q and a:
                qa_pairs.append((q, a))

    return qa_pairs, detail_text


def load_training_data():
    """
    Load all .txt files from chatbot_data.
    For each file, store:
      - topic name (from filename)
      - list of (question, answer) pairs
      - full detail text
    """
    topics = {}
    if not os.path.isdir(DATA_FOLDER):
        return topics

    for filename in os.listdir(DATA_FOLDER):
        if filename.lower().endswith(".txt"):
            topic_name = filename.replace(".txt", "").strip()
            filepath = os.path.join(DATA_FOLDER, filename)

            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(filepath, "r", encoding="latin-1") as f:
                    content = f.read()

            qa_pairs, detail_text = parse_qa_from_content(content)

            topics[topic_name] = {
                "qa": qa_pairs,       # list of (Q, A)
                "detail": detail_text # full topic text
            }

    return topics


# Main topics from txt files
main_topics = load_training_data()

# Side topics (manual)
side_topics = {
    "wfh policy": "Our WFH policy supports hybrid work up to 3 days a week. Confirm with your manager for team-specific details.",
    "it support": "Need IT help? Contact helpdesk@se.com or dial extension 1234.",
    "benefits": "Benefits include health insurance, paid leave, wellness programs, and learning budgets.",
    "office hours": "Standard office hours are 9:00 AM – 5:30 PM, Monday to Friday.",
    "vacation policy": "Employees receive 20 vacation days annually, plus public holidays."
}

# All topic names used for listing / keyword fallback
all_topics_text = {**{k: v["detail"] for k, v in main_topics.items()}, **side_topics}

# Build a global list of all Q&A across all topics for "AI-like" matching
global_qa_index = []
for topic_name, data in main_topics.items():
    for q, a in data["qa"]:
        global_qa_index.append({
            "topic": topic_name,
            "question": q,
            "answer": a
        })


# ---------------------------------------------------------
# 2. INTENTS & SIMPLE RESPONSES (FROM YOUR ORIGINAL BOT)
# ---------------------------------------------------------

intents = {
    "greetings": ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"],
    "how_are_you": ["how are you", "how's it going", "how you doing", "what's up"],
    "capabilities": ["what can you do", "how can you help", "your features", "what are you capable of"],
    "identity": ["who are you", "what are you", "introduce yourself"],
    "joke": ["joke", "make me laugh", "funny"],
    "company_info": ["schneider electric", "about schneider", "company info", "what is schneider"],
    "topics": ["main topics", "documents", "training files", "help", "resources", "files"],
    "small_talk": ["thanks", "thank you", "cool", "great", "awesome", "nice", "perfect"]
}

jokes = [
    "Why did the PLC go to therapy? Because it had too many unresolved inputs! 😄",
    "Why don't electricians ever get lost? Because they always follow the current! ⚡",
    "I'm reading a book on anti-gravity... It's impossible to put down. 😆"
]


def match_intent(query, intent_key):
    return any(phrase in query for phrase in intents.get(intent_key, []))


# ---------------------------------------------------------
# 3. TOPIC EXTRACTION (YOUR ORIGINAL PATTERN LOGIC, IMPROVED)
# ---------------------------------------------------------

def normalize_text_for_match(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_topic_from_query(query, topic_keys):
    """
    Re-uses your original pattern approach like:
      - tell me about <topic>
      - show me <topic>
      - what is <topic>
    but now with better cleaning and matching.
    """
    q_norm = normalize_text_for_match(query)

    patterns = [
        r"tell me about (.+)",
        r"show me (.+)",
        r"give info on (.+)",
        r"what is (.+)",
        r"details on (.+)",
        r"info about (.+)",
        r"explain (.+)",
        r"(.+) info"
    ]

    for pattern in patterns:
        m = re.search(pattern, q_norm)
        if not m:
            continue
        candidate = m.group(1).strip()

        # Try best match against known topics
        best_topic = None
        best_score = 0
        for topic in topic_keys:
            t_norm = normalize_text_for_match(topic)
            # Fuzzy similarity between extracted phrase and topic
            sim = difflib.SequenceMatcher(None, candidate, t_norm).ratio()
            if sim > best_score:
                best_score = sim
                best_topic = topic

        if best_topic and best_score > 0.4:
            return best_topic

    return None


def detect_topic(query):
    """
    Multi-strategy topic detection:
      1) Try pattern-based extraction (tell me about X...)
      2) Keyword containment for topic names
      3) Fuzzy topic name similarity
    Works over BOTH main_topics and side_topics.
    """
    q_norm = normalize_text_for_match(query)
    topic_keys = list(main_topics.keys()) + list(side_topics.keys())

    # 1) Pattern-based
    extracted = extract_topic_from_query(query, topic_keys)
    if extracted and extracted in topic_keys:
        return extracted

    # 2) Keyword containment
    for topic in topic_keys:
        t_norm = normalize_text_for_match(topic)
        # any significant token from topic in the query
        topic_tokens = [t for t in t_norm.split() if len(t) > 2]
        if any(tok in q_norm for tok in topic_tokens):
            return topic

    # 3) Fuzzy similarity on whole query vs topic name
    best_topic = None
    best_score = 0
    for topic in topic_keys:
        t_norm = normalize_text_for_match(topic)
        sim = difflib.SequenceMatcher(None, q_norm, t_norm).ratio()
        if sim > best_score:
            best_score = sim
            best_topic = topic

    if best_topic and best_score > 0.40:
        return best_topic

    return None


# ---------------------------------------------------------
# 4. FAQ ANSWERING (WITHIN TOPIC + GLOBAL)
# ---------------------------------------------------------

def find_best_faq_answer_for_topic(topic, user_message):
    """
    Within a single topic, find the best FAQ Q/A match.
    """
    if topic not in main_topics:
        return None

    q_norm = normalize_text_for_match(user_message)
    qa_list = main_topics[topic]["qa"]
    if not qa_list:
        return None

    best_score = 0
    best_answer = None

    for q, a in qa_list:
        q_text = normalize_text_for_match(q)
        # Combined score: token overlap + fuzzy similarity
        overlap = sum(1 for word in q_norm.split() if word in q_text)
        sim = difflib.SequenceMatcher(None, q_norm, q_text).ratio()
        score = overlap * 2.0 + sim * 2.0

        if score > best_score:
            best_score = score
            best_answer = a

    return best_answer if best_score > 2.2 else None  # tuned threshold


def find_best_faq_answer_global(user_message):
    """
    Global FAQ matching across ALL topics.
    This is your "AI-like" layer: if we can't confidently detect a topic,
    we still try to find the best Q/A across everything.
    """
    if not global_qa_index:
        return None

    q_norm = normalize_text_for_match(user_message)
    best_score = 0
    best = None

    for entry in global_qa_index:
        q_text = normalize_text_for_match(entry["question"])
        overlap = sum(1 for word in q_norm.split() if word in q_text)
        sim = difflib.SequenceMatcher(None, q_norm, q_text).ratio()
        score = overlap * 2.0 + sim * 2.0

        if score > best_score:
            best_score = score
            best = entry

    if best and best_score > 2.2:
        # if you want to mention the topic, you could prepend it
        return best["answer"]

    return None


# ---------------------------------------------------------
# 5. MAIN BOT LOGIC (MIX OF YOUR OLD LOGIC + NEW FAQ INTELLIGENCE)
# ---------------------------------------------------------

def get_bot_response(query: str) -> str:
    q = query.lower().strip()

    # 1. Intents (your logic)
    if match_intent(q, "greetings"):
        return random.choice([
            "Hey there! 👋 Ready to explore Schneider Electric together?",
            "Hi! I'm your digital onboarding buddy here to help with all things Schneider ⚡",
            "Hello! How can I assist with your Schneider journey today?"
        ])

    if match_intent(q, "how_are_you"):
        return "I'm fully charged and ready to help ⚡ How can I support you today?"

    if match_intent(q, "capabilities"):
        return (
            "I'm your assistant for all things Schneider Electric! 💼 Here's how I can help:\n"
            "• Onboarding guidance\n"
            "• Company policies & benefits\n"
            "• Training resources & documents\n"
            "• IT & HR support info\n"
            "Try asking: 'What's the WFH policy?' or 'Show me training docs.'"
        )

    if match_intent(q, "identity"):
        return (
            "I'm Schneider Electric’s smart onboarding assistant 🤖.\n"
            "Think of me as your friendly digital teammate here to make your first days smoother."
        )

    if match_intent(q, "joke"):
        return random.choice(jokes)

    if match_intent(q, "company_info"):
        return (
            "Schneider Electric is a global leader in energy management and industrial automation.\n"
            "We're committed to sustainability, innovation, and empowering people to make the most of their energy."
        )

    if match_intent(q, "topics"):
        if all_topics_text:
            topics_list = "\n".join(f"• {key}" for key in all_topics_text.keys())
            return (
                "Here's what I can help you with right now:\n\n"
                f"{topics_list}\n\n"
                "You can ask something like 'Tell me about Working Time Regulations' or "
                "'What is PLC Programming Basics?'."
            )
        else:
            return "I couldn't find any topics yet. Please check back later."

    if match_intent(q, "small_talk"):
        return random.choice([
            "You're most welcome! 😊 Let me know if there's anything else you need.",
            "Anytime! I'm here to help ⚡",
            "Glad I could help! Ask away if you need more info."
        ])

    # 2. Topic detection (your pattern logic + improvements)
    topic = detect_topic(query)

    # 3. If we have a topic with structured Q&A, try topic-level FAQ match
    if topic and topic in main_topics:
        faq_answer = find_best_faq_answer_for_topic(topic, query)
        if faq_answer:
            return faq_answer

        # if no specific FAQ matched, fall back to full topic text
        return main_topics[topic]["detail"]

    # 4. If topic is one of the side topics (manual)
    if topic and topic in side_topics:
        return side_topics[topic]

    # 5. Global FAQ search (AI-like matching across all topics)
    global_answer = find_best_faq_answer_global(query)
    if global_answer:
        return global_answer

    # 6. Keyword fallback (legacy behaviour)
    for keyword, content in all_topics_text.items():
        if keyword.lower() in q:
            return content.strip()

    # 7. Final fallback
    return (
        "I couldn't quite match that to anything I know yet. 🤔\n"
        "Try asking about onboarding, working time, annual leave, PLCs, SCADA, HMI, "
        "IT support, or type 'main topics' to see what I know.\n\n"
        "Example questions:\n"
        "• 'What are the working hours?'\n"
        "• 'How many days of annual leave do I get?'\n"
        "• 'What is a PLC?'\n"
        "• 'How do I book business travel?'"
    )


# ---------------------------------------------------------
# 6. FLASK ROUTES
# ---------------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def get_response():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"reply": "Please type a message so I can help."})
    reply = get_bot_response(user_message)
    return jsonify({"reply": reply})


if __name__ == "__main__":
    app.run(debug=True)
