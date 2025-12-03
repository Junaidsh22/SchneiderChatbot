
from flask import Flask, render_template, request, jsonify
import os, re, random

app = Flask(__name__)

# Load chatbot data
def load_chatbot_data():
    responses = {}
    folder = "chatbot_data"
    if os.path.isdir(folder):
        for filename in os.listdir(folder):
            if filename.endswith(".txt"):
                filepath = os.path.join(folder, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as file:
                        content = file.read()
                except UnicodeDecodeError:
                    with open(filepath, 'r', encoding='latin-1') as file:
                        content = file.read()
                keyword = filename.replace(".txt", "").lower()
                responses[keyword] = content
    return responses

main_topics = load_chatbot_data()
side_topics = {
    "wfh policy": "Our WFH policy supports hybrid work up to 3 days a week.",
    "it support": "Need IT help? Contact helpdesk@se.com or dial extension 1234.",
    "benefits": "Benefits include health insurance, paid leave, wellness programs.",
    "office hours": "Standard office hours are 9:00 AM – 5:30 PM, Monday to Friday.",
    "vacation policy": "Employees receive 20 vacation days annually, plus public holidays."
}
chatbot_knowledge = {**main_topics, **side_topics}

intents = {
    "greetings": ["hello", "hi", "hey", "good morning", "good afternoon"],
    "how_are_you": ["how are you", "how's it going", "what's up"],
    "capabilities": ["what can you do", "your features"],
    "identity": ["who are you", "introduce yourself"],
    "joke": ["joke", "make me laugh"],
    "company_info": ["schneider electric", "about schneider"],
    "topics": ["main topics", "help", "resources"],
    "small_talk": ["thanks", "thank you", "great", "awesome"]
}

jokes = [
    "Why did the PLC go to therapy? Because it had too many unresolved inputs!",
    "Why don't electricians ever get lost? Because they always follow the current!",
    "I'm reading a book on anti-gravity... It's impossible to put down."
]

def match_intent(query, intent_key):
    return any(phrase in query for phrase in intents.get(intent_key, []))

def extract_topic_from_query(query):
    patterns = [
        r"tell me about (.+)",
        r"show me (.+)",
        r"give info on (.+)",
        r"what is (.+)",
        r"details on (.+)",
        r"(.+) info",
        r"info about (.+)",
        r"explain (.+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, query)
        if match:
            candidate = match.group(1).strip().lower()
            for topic in chatbot_knowledge.keys():
                if topic in candidate or candidate in topic:
                    return topic
    return None

def get_bot_response(query):
    query = query.lower().strip()
    if match_intent(query, "greetings"):
        return random.choice(["Hey there! 👋", "Hi! How can I help?", "Hello! Ready to assist!"])
    if match_intent(query, "how_are_you"):
        return "I'm fully charged and ready to help ⚡"
    if match_intent(query, "capabilities"):
        return "I can help with onboarding, policies, IT support, and more!"
    if match_intent(query, "identity"):
        return "I'm Schneider Electric’s smart assistant 🤖"
    if match_intent(query, "joke"):
        return random.choice(jokes)
    if match_intent(query, "company_info"):
        return "Schneider Electric is a global leader in energy management and automation."
    if match_intent(query, "topics"):
        topics = "\n".join(f"• {key.title()}" for key in chatbot_knowledge)
        return f"Here are topics I know:\n{topics}"
    extracted_topic = extract_topic_from_query(query)
    if extracted_topic and extracted_topic in chatbot_knowledge:
        return f"Here's what I found on {extracted_topic.title()}:\n{chatbot_knowledge[extracted_topic].strip()}"
    for keyword, content in chatbot_knowledge.items():
        if keyword in query:
            return f"Here's what I found on {keyword.title()}:\n{content.strip()}"
    if match_intent(query, "small_talk"):
        return random.choice(["You're welcome! 😊", "Anytime! I'm here to help ⚡", "Glad I could help!"])
    return "🤔 I couldn’t catch that. Try asking about policies, IT support, or type 'help'."

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/get", methods=["POST"])
def chatbot_response():
    user_text = request.json.get("message")
    response = get_bot_response(user_text)
    return jsonify({"reply": response})

if __name__ == "__main__":
    app.run(debug=True)
