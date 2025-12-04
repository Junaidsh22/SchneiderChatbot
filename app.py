import os
import re
import math
import numpy as np
from flask import Flask, render_template, request, jsonify
from openai import AzureOpenAI

app = Flask(__name__)

# -----------------------------
# Azure OpenAI configuration
# -----------------------------
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

# Deployment names (set as env vars in Render)
AZURE_OPENAI_CHAT_DEPLOYMENT = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT")      # e.g. "se-chatbot-gpt"
AZURE_OPENAI_EMBED_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT")    # e.g. "se-chatbot-embed"

client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version=AZURE_OPENAI_API_VERSION,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)

DATA_FOLDER = "chatbot_data"

# This will hold our in-memory vector index
# Each entry: {"topic": str, "chunk": str, "vector": np.ndarray}
vector_index = []


# -----------------------------
# Helper: text loading & chunking
# -----------------------------
def load_documents(folder=DATA_FOLDER):
    docs = []
    if not os.path.isdir(folder):
        return docs

    for filename in os.listdir(folder):
        if filename.lower().endswith(".txt"):
            topic = filename.replace(".txt", "").strip()
            path = os.path.join(folder, filename)

            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                with open(path, "r", encoding="latin-1") as f:
                    content = f.read()

            docs.append((topic, content))
    return docs


def split_into_chunks(text, max_chars=800):
    """
    Simple chunking: split on blank lines, then merge
    until max_chars is reached.
    """
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks = []
    current = ""

    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(current) + len(p) + 2 <= max_chars:
            current = (current + "\n\n" + p).strip()
        else:
            if current:
                chunks.append(current)
            current = p

    if current:
        chunks.append(current)

    return chunks


# -----------------------------
# Helper: embeddings + similarity
# -----------------------------
def get_embedding(text: str) -> np.ndarray:
    resp = client.embeddings.create(
        model=AZURE_OPENAI_EMBED_DEPLOYMENT,
        input=text
    )
    vec = resp.data[0].embedding
    return np.array(vec, dtype="float32")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None:
        return 0.0
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def build_vector_index():
    global vector_index
    vector_index = []

    docs = load_documents()
    for topic, content in docs:
        chunks = split_into_chunks(content)
        for chunk in chunks:
            vec = get_embedding(chunk)
            vector_index.append({
                "topic": topic,
                "chunk": chunk,
                "vector": vec
            })


def retrieve_relevant_chunks(query: str, top_k: int = 4):
    if not vector_index:
        return []

    q_vec = get_embedding(query)
    scored = []
    for entry in vector_index:
        score = cosine_similarity(q_vec, entry["vector"])
        scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [entry for score, entry in scored[:top_k] if score > 0.3]
    return top


# -----------------------------
# Small-talk / intent handling
# -----------------------------
SMALL_TALK = {
    "greetings": ["hello", "hi", "hey", "good morning", "good afternoon", "good evening"],
    "how_are_you": ["how are you", "how's it going", "how you doing"],
    "thanks": ["thanks", "thank you", "cheers", "appreciate it"]
}

def match_intent(text, intent_key):
    q = text.lower()
    return any(phrase in q for phrase in SMALL_TALK.get(intent_key, []))


def handle_small_talk(user_message: str) -> str | None:
    q = user_message.lower()
    if match_intent(q, "greetings"):
        return "Hello! 👋 How can I help you today?"
    if match_intent(q, "how_are_you"):
        return "I'm running smoothly and ready to help ⚡"
    if match_intent(q, "thanks"):
        return "You're very welcome! If you need anything else, just ask. 😊"
    return None


# -----------------------------
# Core RAG + Azure OpenAI answer
# -----------------------------
def answer_with_rag(user_message: str) -> str:
    # 1) Small-talk shortcut
    st = handle_small_talk(user_message)
    if st:
        return st

    # 2) Retrieve relevant document chunks
    relevant = retrieve_relevant_chunks(user_message, top_k=4)

    if not relevant:
        # No context found – still try to be helpful, but admit limitation
        system_msg = (
            "You are Schneider Electric’s internal AI assistant. "
            "If there is no relevant company information, say you don't know and suggest "
            "who they can contact (HR, IT, or their manager)."
        )
        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_message}
        ]
    else:
        # Build a context string from top chunks
        context_blocks = []
        for entry in relevant:
            context_blocks.append(f"[Topic: {entry['topic']}]\n{entry['chunk']}")
        context_text = "\n\n---\n\n".join(context_blocks)

        system_msg = (
            "You are Schneider Electric’s internal AI assistant. "
            "Use ONLY the following company knowledge to answer the question. "
            "If something is not covered, say you don't know and suggest contacting HR, IT, "
            "or the relevant manager.\n\n"
            "Respond clearly and concisely, and where appropriate, list key points."
        )

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "assistant", "content": f"Here is the Schneider Electric reference material:\n\n{context_text}"},
            {"role": "user", "content": user_message}
        ]

    chat_resp = client.chat.completions.create(
        model=AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=messages,
        temperature=0.2
    )

    return chat_resp.choices[0].message.content.strip()


# -----------------------------
# Flask routes
# -----------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/get", methods=["POST"])
def get_response():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"reply": "Please type a message so I can help."})

    try:
        reply = answer_with_rag(user_message)
    except Exception as e:
        # Don't expose internal errors to the user
        print("Error in answer_with_rag:", e)
        reply = (
            "Sorry, I ran into a technical issue while processing that. "
            "Please try again, or contact technical support if the problem continues."
        )

    return jsonify({"reply": reply})


if __name__ == "__main__":
    # Build the in-memory vector index on startup
    if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY and AZURE_OPENAI_EMBED_DEPLOYMENT:
        print("Building vector index from chatbot_data...")
        build_vector_index()
        print(f"Loaded {len(vector_index)} chunks into the index.")
    else:
        print("⚠ Azure OpenAI environment variables not set. Vector index not built.")
    app.run(debug=True)
