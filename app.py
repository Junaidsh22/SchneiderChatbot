from flask import Flask, render_template, request, jsonify
import os, re, random

app = Flask(__name__)

# -------------------------
# LOAD TRAINING FILES
# -------------------------
def load_chatbot_data():
    responses = {}
    folder = "chatbot_data"

    if os.path.isdir(folder):
        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                filepath = os.path.join(folder, filename)

                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                except:
                    with open(filepath, "r", encoding="latin-1") as f:
                        content = f.read()

                keyword = filename.replace(".txt", "").lower()
                responses[keyword] = content.strip()

    return responses


# Load your REAL topics from text files
main_topics = load_chatbot_data()

# Manual topics (extra)
side_topics = {
    "wfh policy": "Our WFH policy supports hybrid work up to 3 days a week.",
    "it support": "Need IT help? Contact helpdesk@se.com or dial extension 1234.",
    "benefits": "Benefits include health insurance, paid leave, wellness programs.",
    "office hours": "Standard office hours are 9:00 AM – 5:30 PM.",
    "vacation policy": "Employees receive 20 vacation days annually, plus public holidays."
}

# Combine both
chatbot_knowledge = {**main_topics, **side_topics}

# -------------------------
# SIMPLE INTENTS
# -------------------------
intents = {
    "greetings": ["hello", "hi", "hey"],
    "how_are_you": ["how are you"],
    "joke": ["joke", "funny"],
    "topics": ["main topics", "show topics", "help", "resources"]
}

jokes = [
    "Why did the PLC go to therapy? Because it had too many unresolved inputs!",
    "Why don't electricians get lost? Because they follow the current!",
    "I'm reading a book on anti-gravity… it's impossible to put down."
]


def match_intent(query, intent_key):
    return any(phrase in query for phrase in intents.get(intent_key, []))


# -------------------------
# OLD TOPIC EXTRACTION (Restored)
# -------------------------
def extract_topic(query):
    # Check for exact filename keyword match
    for topic in chatbot_knowledge.keys():
        if topic in query:
            return topic

    # Patterns for: "tell me about X", "what is X"
    patterns = [
        r"tell me about (.+)",
        r"what is (.+)",
        r"show me (.+)",
        r"explain (.+)"
    ]

    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            extracted = match.group(1).strip().lower()
            for topic in chatbot_knowledge.keys():
                if extracted in topic:
                    return topic

    return None


# -------------------------
# MAIN RESPONSE FUNCTION (Restored Old Style)
# -------------------------
def get_bot_response(query):
    query = query.lower().strip()

    # Greetings
    if match_intent(query, "greetings"):
        return random.choice(["Hello! 👋", "Hi there!", "Hey! How can I help?"])

    # How are you?
    if match_intent(query, "how_are_you"):
        return "I'm fully charged and ready to help ⚡"

    # Jokes
    if match_intent(query, "joke"):
        return random.choice(jokes)

    # "Show topics" → old behaviour
    if match_intent(query, "topics"):
        topics = "\n".join(f"• {topic.title()}" for topic in chatbot_knowledge.keys())
        return f"Here are the topics I can help with:\n\n{topics}"

    # Topic extraction from old method
    topic = extract_topic(query)
    if topic and topic in chatbot_knowledge:
        return chatbot_knowledge[topic]

    # Fallback
    return (
        "I'm not sure about that 🤔\n"
        "Try asking about:\n"
        "- WFH policy\n"
        "- IT support\n"
        "- Vacation policy\n"
        "- Benefits\n"
        "Or type 'main topics' to see everything I know."
    )


# -------------------------
# ROUTES
# -------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def chatbot_response():
    user_msg = request.json.get("message")
    reply = get_bot_response(user_msg)
    return jsonify({"reply": reply})


if __name__ == "__main__":
    app.run(debug=True)
