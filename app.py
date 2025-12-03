
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    user_msg = data.get('message', '')
    # Simple response logic (replace with your chatbot logic later)
    return jsonify({"response": f"You said: {user_msg}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
