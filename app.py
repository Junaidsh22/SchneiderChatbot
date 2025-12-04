from flask import Flask, render_template, request, jsonify
import os
import re
import difflib

app = Flask(__name__)

DATA_FOLDER = "chatbot_data"

# ---------------------------------------------------------
# 1. LOAD ALL TRAINING FILES + SPLIT FAQ / DETAIL SECTIONS
# ---------------------------------------------------------
def load_training_data():
    topics = {}

    for filename in os.listdir(DATA_FOLDER):
        if filename.lower().endswith(".txt"):
            topic_name = filename.replace(".txt", "").strip()

            with open(os.path.join(DATA_FOLDER, filename), "r", encoding="utf-8") as f:
                content = f.read()

            # Extract FAQ block
            faq_match = re.search(r"\[FAQ\](.*?)\[DETAIL\]", content, flags=re.S)
            detail_match = re.search(r"\[DETAIL\](.*)", content, flags=re.S)

            faq_entries = []
            if faq_match:
                raw_faq = faq_match.group(1).strip()
                qa_blocks = raw_faq.split("Q:")

                for block in qa_blocks:
                    block = block.strip()
                    if block:
                        parts = block.split("A:")
                        if len(parts) == 2:
                            question = parts[0].strip()
                            answer = parts[1].strip()
                            faq_entries.append((question, answer))

            details = detail_match.group(1).strip() if detail_match else ""

            topics[topic_name] = {
                "faq": faq_entries,
                "detail": details
            }

    return topics


training_data = load_training_data()


# ---------------------------------------------------------
# 2. TOPIC DETECTION – MULTI-KEYWORD + FUZZY MATCHING
# ---------------------------------------------------------
def detect_topic(user_message):
    user_message = user_message.lower()

    # Direct keyword match
    for topic in training_data.keys():
        clean_topic = topic.lower().replace("_", " ")

        if any(word in user_message for word in clean_topic.split()):
            return topic

    # Secondary fuzzy match
    closest = difflib.get_close_matches(user_message, training_data.keys(), n=1, cutoff=0.4)
    return closest[0] if closest else None


# ---------------------------------------------------------
# 3. INTELLIGENT FAQ MATCHING (Weighted scoring)
# ---------------------------------------------------------
def find_best_faq_answer(topic, user_message):
    user_message = user_message.lower()
    faqs = training_data[topic]["faq"]

    if not faqs:
        return None

    best_score = 0
    best_answer = None

    for q, a in faqs:
        q_low = q.lower()

        # Keyword overlap score
        overlap = sum(word in q_low for word in user_message.split())

        # Fuzzy similarity score
        similarity = difflib.SequenceMatcher(None, user_message, q_low).ratio()

        # Weighted score
        score = (overlap * 2.2) + (similarity * 1.8)

        if score > best_score:
            best_score = score
            best_answer = a

    return best_answer if best_score > 0.50 else None


# ---------------------------------------------------------
# 4. FINAL RESPONSE LOGIC
# ---------------------------------------------------------
def get_bot_response(user_message):
    topic = detect_topic(user_message)

    if not topic:
        return (
            "I'm not fully sure what you mean. Try asking about:\n"
            "• Working Time Regulations\n"
            "• Travel Booking\n"
            "• PLC Basics\n"
            "• Key Employee Tools\n"
            "• SCADA\n"
            "• HMI usage\n\n"
            "Or ask a specific question like:\n"
            "“How many hours rest do I need?”"
        )

    # First attempt: FAQ (specific answer)
    faq_answer = find_best_faq_answer(topic, user_message)
    if faq_answer:
        return faq_answer

    # Fallback: full detailed topic text
    return training_data[topic]["detail"]


# ---------------------------------------------------------
# 5. FLASK ROUTES
# ---------------------------------------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def get_response():
    data = request.get_json()
    user_message = data.get("message", "").strip()

    if not user_message:
        return jsonify({"reply": "Please type a message."})

    reply = get_bot_response(user_message)
    return jsonify({"reply": reply})


# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True)
