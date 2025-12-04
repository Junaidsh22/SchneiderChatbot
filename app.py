import os
import re
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

DATA_FOLDER = "chatbot_data"

# -----------------------------
# Load training data
# -----------------------------
def load_documents(folder=DATA_FOLDER):
    docs = {}
    if not os.path.isdir(folder):
        return docs

    for filename in os.listdir(folder):
        if filename.lower().endswith(".txt"):
            key = filename.replace(".txt", "").lower()
            path = os.path.join(folder, filename)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    docs[key] = f.read()
            except UnicodeDecodeError:
                with open(path, "r", encoding="latin-1") as f:
                    docs[key] = f.read()
    return docs

knowledge_base = load_documents()

# Additional manual topics
side_topics = {
    "wfh policy": "The IPA WFH policy can be found in the IPA Hub → Governance → Ways of Working.",
    "it support": "For IT support, visit the IPA Hub → Support Centre or raise a ticket.",
    "benefits": "Benefits information is available in the IPA Hub → HR → Rewards & Benefits.",
}

knowledge_base.update(side_topics)

# -----------------------------
# Intent helpers
# -----------------------------
INTENTS = {
    "greetings": ["hello", "hi", "hey", "good morning", "good afternoon"],
    "how_are_you": ["how are you", "how’s it going", "how you doing"],
    "topics": ["main topics", "topics", "help", "resources"],
}

def match_intent(msg, intent):
    msg = msg.lower()
    return any(p in msg for p in INTENTS.get(intent, []))

# -----------------------------
# Query → Topic extraction
# -----------------------------
def extract_topic(query):
    query = query.lower()

    # Pattern-based extraction
    patterns = [
        r"tell me about (.+)",
        r"what is (.+)",
        r"show me (.+)",
        r"info on (.+)",
        r"details on (.+)"
    ]

    for p in patterns:
        m = re.search(p, query)
        if m:
            candidate = m.group(1).strip()
            for topic in knowledge_base:
                if topic in candidate or candidate in topic:
                    return topic

    # Keyword match
    for topic in knowledge_base:
        if topic in query:
            return topic

    return None

# -----------------------------
# Bot response logic
# -----------------------------
def generate_response(user_msg):
    msg = user_msg.lower().strip()

    # 1. Greetings
    if match_intent(msg, "greetings"):
        return "Hello 👋 How can I help you navigate the IPA Hub?"

    # 2. How are you?
    if match_intent(msg, "how_are_you"):
        return "I'm running smoothly and ready to guide you around the IPA Hub ⚡"

    # 3. List topics
    if match_intent(msg, "topics"):
        t = "\n".join(f"• {k.title()}" for k in knowledge_base)
        return f"Here are the topics I can help with:\n\n{t}"

    # 4. Find topic based on query
    topic = extract_topic(msg)
    if topic and topic in knowledge_base:
        return f"📘 **{topic.title()}**\n\n{knowledge_base[topic]}"

    # 5. Fallback
    return (
        "I'm not sure about that yet 🤔\n\n"
        "Try asking things like:\n"
        "• 'Where do I find templates?'\n"
        "• 'Show me governance documents'\n"
        "• 'Tell me about IPA training'\n\n"
        "Or type **main topics** to see everything I know."
    )

# -----------------------------
# Flask routes
# -----------------------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/get", methods=["POST"])
def get_response():
    data = request.get_json()
    user_msg = data.get("message", "")
    reply = generate_response(user_msg)
    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(debug=True)
