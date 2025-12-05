
from flask import Flask, request, jsonify, render_template
from chatbot_gui import get_bot_response  # Import chatbot logic from your existing file

app = Flask(__name__)

# Homepage route
@app.route('/')
def home():
    return render_template('index.html')  # Will create this file next

# Chat API route
@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    response = get_bot_response(user_message)
    return jsonify({"response": response})

if __name__ == '__main__':
    app.run(debug=True)
