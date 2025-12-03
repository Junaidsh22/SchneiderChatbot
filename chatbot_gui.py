import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog
import csv
import os
from PIL import Image, ImageTk
import hashlib
import re
import random

# --- Utility Functions ---

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def load_chatbot_data():
    """Load main chatbot topics from chatbot_data folder."""
    responses = {}
    data_folder = "chatbot_data"
    if os.path.isdir(data_folder):
        for filename in os.listdir(data_folder):
            if filename.endswith(".txt"):
                filepath = os.path.join(data_folder, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as file:
                        content = file.read()
                except UnicodeDecodeError:
                    with open(filepath, 'r', encoding='latin-1') as file:
                        content = file.read()
                keyword = filename.replace(".txt", "").lower()
                responses[keyword] = content
    return responses

# --- Knowledge Base ---

# Load main topics from text files
main_topics = load_chatbot_data()

# Add side topics manually
side_topics = {
    "wfh policy": "Our WFH policy supports hybrid work up to 3 days a week. Confirm with your manager for team-specific details.",
    "it support": "Need IT help? Contact helpdesk@se.com or dial extension 1234.",
    "benefits": "Benefits include health insurance, paid leave, wellness programs, and learning budgets.",
    "office hours": "Standard office hours are 9:00 AM – 5:30 PM, Monday to Friday.",
    "vacation policy": "Employees receive 20 vacation days annually, plus public holidays."
}

# Combine both
chatbot_knowledge = {**main_topics, **side_topics}

# --- Intents ---

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

# --- Jokes ---

jokes = [
    "Why did the PLC go to therapy? Because it had too many unresolved inputs! 😄",
    "Why don't electricians ever get lost? Because they always follow the current! ⚡",
    "I'm reading a book on anti-gravity... It's impossible to put down. 😆"
]

# --- Helper Functions ---

def match_intent(query, intent_key):
    return any(phrase in query for phrase in intents.get(intent_key, []))

def extract_topic_from_query(query):
    """
    Tries to intelligently extract a topic keyword from user queries that
    include patterns like:
    - "tell me about <topic>"
    - "show me <topic>"
    - "give info on <topic>"
    - "what is <topic>"
    - "details on <topic>"
    - "<topic> info"
    Returns the matched topic keyword if found, else None.
    """
    # Patterns for extracting topic after common phrases
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
            # Try to find a best matching topic from chatbot_knowledge
            for topic in chatbot_knowledge.keys():
                if topic in candidate or candidate in topic:
                    return topic
    return None

# --- Chatbot Logic ---

def get_bot_response(query: str) -> str:
    query = query.lower().strip()

    # 1. Greetings
    if match_intent(query, "greetings"):
        return random.choice([
            "Hey there! 👋 Ready to explore Schneider Electric together?",
            "Hi! I'm your digital onboarding buddy here to help with all things Schneider ⚡",
            "Hello! How can I assist with your Schneider journey today?"
        ])

    # 2. How are you?
    if match_intent(query, "how_are_you"):
        return "I'm fully charged and ready to help ⚡ How can I support you today?"

    # 3. What can you do?
    if match_intent(query, "capabilities"):
        return (
            "I'm your assistant for all things Schneider Electric! 💼 Here's how I can help:\n"
            "• Onboarding guidance\n"
            "• Company policies & benefits\n"
            "• Training resources & documents\n"
            "• IT & HR support info\n"
            "Try asking: 'What's the WFH policy?' or 'Show me training docs.'"
        )

    # 4. Who are you?
    if match_intent(query, "identity"):
        return (
            "I'm Schneider Electric’s smart onboarding assistant 🤖.\n"
            "Think of me as your friendly digital teammate here to make your first days smoother."
        )

    # 5. Tell a joke
    if match_intent(query, "joke"):
        return random.choice(jokes)

    # 6. What is Schneider Electric?
    if match_intent(query, "company_info"):
        return (
            "🌍 Schneider Electric is a global leader in energy management and industrial automation.\n"
            "We're committed to sustainability, innovation, and empowering people to make the most of their energy.\n"
            "Visit us at [www.se.com](https://www.se.com) to learn more."
        )

    # 7. Show available topics (main + side)
    if match_intent(query, "topics"):
        if chatbot_knowledge:
            topics = "\n".join(f"• {key.title()}" for key in chatbot_knowledge)
            return (
                "📚 Here's what I can help you with:\n\n"
                f"{topics}\n\n"
                "Just type a topic name or ask me about it like 'Tell me about office hours'."
            )
        else:
            return "Hmm... I couldn't find any topics right now. Please check back later."

    # 8. Try to extract topic from natural queries like 'tell me about ...'
    extracted_topic = extract_topic_from_query(query)
    if extracted_topic and extracted_topic in chatbot_knowledge:
        return f"📘 Here's what I found on **{extracted_topic.title()}**:\n\n{chatbot_knowledge[extracted_topic].strip()}"

    # 9. Match known keywords anywhere in the query (keyword lookup)
    for keyword, content in chatbot_knowledge.items():
        if keyword in query:
            return f"📘 Here's what I found on **{keyword.title()}**:\n\n{content.strip()}"

    # 10. Small talk / gratitude
    if match_intent(query, "small_talk"):
        return random.choice([
            "You're most welcome! 😊 Let me know if there's anything else you need.",
            "Anytime! I'm here to help ⚡",
            "Glad I could help! Ask away if you need more info."
        ])

    # 11. Fallback — no match
    return (
        "🤔 I couldn’t quite catch that.\n"
        "Try asking me about onboarding, training, company policies, or type 'main topics' to see what I know.\n"
        "For example, you can say:\n"
        "• 'Tell me about IT support'\n"
        "• 'What's the vacation policy?'\n"
        "• 'Give me a joke!'\n"
        "If you're unsure, just type 'help' to see available topics."
    )

# --- Feedback Functions ---
def load_feedback():
    feedback_file = "feedback.csv"
    if not os.path.isfile(feedback_file):
        return []
    with open(feedback_file, mode='r', encoding='utf-8') as file:
        return [row for row in csv.reader(file)]

def save_feedback(comment):
    with open("feedback.csv", mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([comment, ""])  # Empty reply field initially

def update_feedback(index, reply):
    feedbacks = load_feedback()
    if 0 <= index < len(feedbacks):
        feedbacks[index][1] = reply
        with open("feedback.csv", mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerows(feedbacks)

# --- User Profile Functions ---
def load_user_profile(username):
    if not os.path.isfile("Chatbotdata.csv"):
        return None
    with open("Chatbotdata.csv", mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['Username'] == username:
                return row
    return None

def update_user_profile(username, updated_data):
    rows = []
    with open("Chatbotdata.csv", mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row['Username'] == username:
                row.update(updated_data)
            rows.append(row)
    if rows:
        with open("Chatbotdata.csv", mode='w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

# --- Save Registration Data ---
def save_registration_data(name, sesa, email, branch, wfh, username, password):
    chatbot_file = "Chatbotdata.csv"
    chatbot_exists = os.path.isfile(chatbot_file)
    with open(chatbot_file, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not chatbot_exists:
            writer.writerow(["Name", "SESA Number", "Email", "Office Branch", "Work From Home", "Username", "Password Hash"])
        writer.writerow([name, sesa, email, branch, wfh, username, hash_password(password)])

# --- Save Credentials ---
def save_credentials(username, password):
    password_file = "passwords.csv"
    password_exists = os.path.isfile(password_file)
    with open(password_file, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not password_exists:
            writer.writerow(["Username", "Password Hash"])
        writer.writerow([username, hash_password(password)])

# --- Validate Credentials ---
def validate_credentials(username, password):
    password_file = "passwords.csv"
    if not os.path.isfile(password_file):
        return False
    with open(password_file, mode='r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            if row["Username"] == username and row["Password Hash"] == hash_password(password):
                return True
    return False

def open_chatbot_host():
    chatbot_window = tk.Toplevel()
    chatbot_window.title("Chatbot Host")
    chatbot_window.geometry("1250x500")
    chatbot_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\333.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        # Background label
        bg_label = tk.Label(chatbot_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        chatbot_window.configure(bg="#ccffcc")

    # Chat display (absolute position)
    chat_display = scrolledtext.ScrolledText(
        chatbot_window,
        wrap=tk.WORD,
        width=130,
        height=13,
        font=("Arial", 12),
        bg="white"
    )
    chat_display.place(x=30, y=110)
    chat_display.insert(tk.END, "Chatbot is ready. Ask me anything about onboarding, training, or Schneider Electric!\n\n")

    # User input (absolute position)
    user_input = tk.Entry(chatbot_window, font=("Arial", 12), width=100)
    user_input.place(x=170, y=360)

    # Send query function
    def send_query():
        query = user_input.get().strip()
        if query:
            chat_display.insert(tk.END, f"You: {query}\n", "user")
            response = get_bot_response(query)
            chat_display.insert(tk.END, f"Bot: {response}\n\n", "bot")
            chat_display.yview(tk.END)
            user_input.delete(0, tk.END)

    # Tag configurations
    chat_display.tag_config("user", foreground="blue", font=("Arial", 12, "bold"))
    chat_display.tag_config("bot", foreground="green", font=("Arial", 12))

    # Send button (absolute position)
    tk.Button(chatbot_window, text="Send", font=("Arial", 12), command=send_query).place(x=620, y=390)
    tk.Button(chatbot_window, text="Back Button", font=("Arial, bold", 12), command=open_main_intro_window).place(x=1120, y=360)


# --- FAQ Window (normal user) ---
def open_faq_window():
    faq_window = tk.Toplevel()
    faq_window.title("Frequently Asked Questions")
    faq_window.geometry("1250x500")
    faq_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\UU.png"
    try:
        # Make sure you imported at the top of your file:
        # from PIL import Image, ImageTk
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(faq_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        faq_window.configure(bg="#ccffcc")

    # --- Foreground widgets (transparent look) ---
    faq_text = """Q: What are the office hours?
A: 9 AM to 5 PM, Monday to Friday.

Q: How do I reset my password?
A: Use the self-service portal or contact IT support.

Q: What is the WFH policy?
A: Work from home is allowed with manager approval.

Q: How do I contact regular support?
A: Use the 'Support@Schneider' tool to contact repersentatives from both: HR & IT technical support

Q: How do I know what type of contract appointment I have?
A: Types of appointments will be clearly stated in a employees contract fe: Fixed role / Travelling Appointment (Please speak to your line manager for more details)

Q: Are there any available sites through which extra learning can be completed?
A: The company offers a range of free courses ranging from quick 20 minute courses thorugh to 6hr+ courses available on: MyLearningLink & Coursera
"""

    # Text area
    text_area = scrolledtext.ScrolledText(
        faq_window, wrap=tk.WORD, width=140, height=16, font=("Arial", 12)
    )
    text_area.pack(pady=120)
    text_area.insert(tk.END, faq_text)
    text_area.config(state='disabled')


# --- Help Window ---
def open_help_window():
    help_window = tk.Toplevel()
    help_window.title("Help")
    help_window.geometry("1250x500")
    help_window.resizable(False, False)

    # --- Load and display background image (same as main intro) ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\u.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        # Background label
        bg_label = tk.Label(help_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        help_window.configure(bg="#ccffcc")


def open_feedback_window(staff_mode=False):
    feedback_window = tk.Toplevel()
    feedback_window.title("Feedback" if not staff_mode else "Staff Feedback Manager")
    feedback_window.geometry("1250x500")
    feedback_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\re.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)
        bg_label = tk.Label(feedback_window, image=bg_photo)
        bg_label.image = bg_photo
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        feedback_window.configure(bg="#ccffcc")

    # --- Feedback display area ---
    feedback_display = scrolledtext.ScrolledText(feedback_window, wrap=tk.WORD, width=110, height=13, font=("Arial", 12))
    feedback_display.place(x=80, y=120)

    def load_feedback():
        feedbacks = []
        if os.path.isfile("feedback.csv"):
            with open("feedback.csv", mode='r', encoding='utf-8') as file:
                reader = csv.reader(file)
                for row in reader:
                    if len(row) == 1:
                        feedbacks.append([row[0], ""])
                    elif len(row) >= 2:
                        feedbacks.append([row[0], row[1]])
        return feedbacks

    def save_feedback(comment):
        with open("feedback.csv", mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([comment, ""])

    def update_feedback(index, reply):
        feedbacks = load_feedback()
        if 0 <= index < len(feedbacks):
            feedbacks[index][1] = f"Staff Entry: {reply}"
            with open("feedback.csv", mode='w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerows(feedbacks)

    def refresh_feedback_display():
        feedback_display.config(state='normal')
        feedback_display.delete("1.0", tk.END)
        for i, (comment, reply) in enumerate(load_feedback()):
            feedback_display.insert(tk.END, f"#{i+1} Feedback: {comment}\n")
            if reply.strip():
                feedback_display.insert(tk.END, f"    ↳ {reply}\n")
            feedback_display.insert(tk.END, "\n")
        feedback_display.config(state='disabled')

    refresh_feedback_display()

    # --- User feedback entry ---
    if not staff_mode:
        tk.Label(feedback_window, text="Submit your feedback:", font=("Arial", 14), bg="#ccffcc").place(x=20, y=90)
        feedback_entry = tk.Entry(feedback_window, font=("Arial", 12), width=100)
        feedback_entry.place(x=220, y=90)

        def submit_feedback():
            comment = feedback_entry.get().strip()
            if comment:
                save_feedback(comment)
                feedback_entry.delete(0, tk.END)
                refresh_feedback_display()

        tk.Button(feedback_window, text="Submit", font=("Arial", 12), command=submit_feedback).place(x=1130, y=86)

    # --- Staff reply and delete controls ---
    if staff_mode:
        # Reply controls
        tk.Label(feedback_window, text="Reply to Feedback #:", bg="#ccffcc").place(x=80, y=370)
        reply_index_entry = tk.Entry(feedback_window, width=5)
        reply_index_entry.place(x=220, y=370)

        reply_text_entry = tk.Entry(feedback_window, font=("Arial", 12), width=80)
        reply_text_entry.place(x=280, y=370)

        def reply_to_feedback():
            try:
                index = int(reply_index_entry.get()) - 1
                reply_text = reply_text_entry.get().strip()
                if reply_text:
                    update_feedback(index, reply_text)
                    refresh_feedback_display()
                    reply_index_entry.delete(0, tk.END)
                    reply_text_entry.delete(0, tk.END)
            except Exception:
                messagebox.showerror("Error", "Invalid feedback number.")

        tk.Button(feedback_window, text="Reply", font=("Arial", 12), command=reply_to_feedback).place(x=1010, y=365)


        # Delete controls
        tk.Label(feedback_window, text="Delete Feedback #:", bg="#ccffcc").place(x=80, y=410)
        delete_index_entry = tk.Entry(feedback_window, width=5)
        delete_index_entry.place(x=220, y=410)

        def delete_feedback():
            try:
                index = int(delete_index_entry.get()) - 1
                feedbacks = load_feedback()
                if 0 <= index < len(feedbacks):
                    del feedbacks[index]
                    with open("feedback.csv", mode='w', newline='', encoding='utf-8') as file:
                        writer = csv.writer(file)
                        writer.writerows(feedbacks)
                    refresh_feedback_display()
                    delete_index_entry.delete(0, tk.END)
            except:
                messagebox.showerror("Error", "Invalid index to delete.")

        tk.Button(feedback_window, text="Delete", font=("Arial", 12), command=delete_feedback).place(x=200, y=402)

# --- User Profile Window ---
def open_user_profile_window():
    profile_window = tk.Toplevel()
    profile_window.title("Edit User Profile")
    profile_window.geometry("1250x500")
    profile_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\v.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(profile_window, image=bg_photo)
        bg_label.image = bg_photo
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        profile_window.configure(bg="#ccffcc")

    # --- Username entry and Load button ---
    top_frame = tk.Frame(profile_window, bg="white")
    top_frame.pack(pady=20)

    tk.Label(top_frame, text="Username:", font=("Arial", 12), bg="white").pack(side="left", padx=5)
    username_entry = tk.Entry(top_frame)
    username_entry.pack(side="left", padx=5)

    fields = {}
    form_frame = tk.Frame(profile_window, bg="white")
    form_frame.pack(pady=20)

    # --- Load profile data into form ---
    def load_profile():
        username = username_entry.get().strip()
        profile = load_user_profile(username)
        if profile:
            for widget in form_frame.winfo_children():
                widget.destroy()
            for key in ["Name", "SESA Number", "Email", "Office Branch", "Work From Home"]:
                tk.Label(form_frame, text=f"{key}:", font=("Arial", 11), bg="white").pack(pady=2)
                entry = tk.Entry(form_frame)
                entry.insert(0, profile[key])
                entry.pack()
                fields[key] = entry
            tk.Button(form_frame, text="Update Profile", font=("Arial", 12),
                      command=lambda: update_profile(username)).pack(pady=10)
        else:
            messagebox.showerror("Error", "Username not found.")

    def update_profile(username):
        updated_data = {key: entry.get().strip() for key, entry in fields.items()}
        update_user_profile(username, updated_data)
        messagebox.showinfo("Success", "Profile updated successfully!")
        profile_window.destroy()

    tk.Button(top_frame, text="Load Profile", font=("Arial", 12), command=load_profile).pack(side="left", padx=10)

def open_passwords_window():
    passwords_window = tk.Toplevel()
    passwords_window.title("Passwords - Backup View")
    passwords_window.geometry("1250x500")
    passwords_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\yz.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(passwords_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        passwords_window.configure(bg="#ccffcc")

    # Text area (absolute position)
    text_area = scrolledtext.ScrolledText(passwords_window, wrap=tk.WORD, width=120, height=13, font=("Arial", 12))
    text_area.place(x=65, y=80)

    if os.path.isfile("passwords.csv"):
        with open("passwords.csv", mode='r', encoding='utf-8') as file:
            content = file.read()
            text_area.insert(tk.END, content)
    else:
        text_area.insert(tk.END, "No passwords file found.")

    text_area.config(state='disabled')

    if os.path.isfile("passwords.csv"):
        with open("passwords.csv", mode='r', encoding='utf-8') as file:
            content = file.read()
            text_area.insert(tk.END, content)
    else:
        text_area.insert(tk.END, "No passwords file found.")

    text_area.config(state='disabled')

def open_create_account_window():
    create_window = tk.Toplevel()
    create_window.title("Create an Account")
    create_window.geometry("1250x500")
    create_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\aa.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        # Background label
        bg_label = tk.Label(create_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        create_window.configure(bg="#ccffcc")

    # --- Form fields (moved far right) ---
    form_frame = tk.Frame(create_window, bg="white")  # white so fields are readable
    # Position near far-right edge (adjust x=1000 if needed)
    form_frame.place(x=940, y=220, anchor="center")

    labels = [
        "Name", "SESA Number", "Email", "Office Branch",
        "Work From Home (Yes/No)", "Username", "Password", "Confirm Password"
    ]
    entries = {}

    for label in labels:
        tk.Label(form_frame, text=label + ":", font=("Arial", 11), bg="white").pack(pady=2, anchor="w")
        entry = tk.Entry(form_frame, show="*" if "Password" in label else "")
        entry.pack(fill="x", padx=5)
        entries[label] = entry

    # --- Submit button ---
    def submit_registration():
        name = entries["Name"].get().strip()
        sesa = entries["SESA Number"].get().strip()
        email = entries["Email"].get().strip()
        branch = entries["Office Branch"].get().strip()
        wfh = entries["Work From Home (Yes/No)"].get().strip()
        username = entries["Username"].get().strip()
        password = entries["Password"].get()
        confirm_password = entries["Confirm Password"].get()

        # Validation
        if not all([name, sesa, email, branch, wfh, username, password, confirm_password]):
            messagebox.showerror("Error", "All fields are required.")
            return
        if not is_valid_email(email):
            messagebox.showerror("Error", "Invalid email format.")
            return
        if password != confirm_password:
            messagebox.showerror("Error", "Passwords do not match.")
            return
        # Check if username already exists
        if load_user_profile(username) is not None:
            messagebox.showerror("Error", "Username already exists.")
            return

        save_registration_data(name, sesa, email, branch, wfh, username, password)
        save_credentials(username, password)

        messagebox.showinfo("Success", "Account created successfully!")

    tk.Button(form_frame, text="Submit", font=("Arial", 12), command=submit_registration).pack(pady=10)

# --- Staff FAQ Window (editable) ---
def open_staff_faq_window():
    staff_faq_window = tk.Toplevel()
    staff_faq_window.title("Staff FAQ (Editable)")
    staff_faq_window.geometry("1250x500")
    staff_faq_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\dc.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(staff_faq_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        staff_faq_window.configure(bg="#ccffcc")

    # --- Load existing FAQ ---
    faq_file = "staff_faq.txt"
    if os.path.isfile(faq_file):
        with open(faq_file, 'r', encoding='utf-8') as f:
            content = f.read()
    else:
        content = """Q: What are the office hours?
A: 9 AM to 5 PM, Monday to Friday.

Q: How do I reset my password?
A: Use the self-service portal or contact IT support.

Q: What is the WFH policy?
A: Work from home is allowed with manager approval.

Q: How do I contact regular support?
A: Use the 'Support@Schneider' tool to contact representatives from both HR & IT technical support.

Q: How do I know what type of contract appointment I have?
A: Types of appointments will be clearly stated in an employee's contract (e.g. Fixed role / Travelling Appointment). Please speak to your line manager for more details.

Q: Are there any available sites through which extra learning can be completed?
A: The company offers a range of free courses, from quick 20-minute sessions to 6hr+ courses on MyLearningLink & Coursera.
"""

    text_area = scrolledtext.ScrolledText(staff_faq_window, wrap=tk.WORD, width=140, height=20, font=("Arial", 12))
    text_area.place(x=20, y=62)
    text_area.insert(tk.END, content)

    def save_faq():
        new_content = text_area.get(1.0, tk.END).strip()
        with open(faq_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        messagebox.showinfo("Saved", "FAQ updated successfully!")


    tk.Button(staff_faq_window, text="Save FAQ", font=("Arial", 12), command=save_faq).place(x=20, y=450)

def open_ticket_manager_window():
    manager_win = tk.Toplevel()
    manager_win.title("Ticket Manager")
    manager_win.geometry("1250x500")  # Updated to match other windows
    manager_win.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\qw.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(manager_win, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        manager_win.configure(bg="#ccffcc")

    ticket_list = scrolledtext.ScrolledText(manager_win, font=("Arial", 12), width=120, height=18)
    ticket_list.place(x=20, y=75)

    def load_tickets():
        ticket_list.delete("1.0", tk.END)
        if not os.path.isfile("tickets.csv"):
            ticket_list.insert(tk.END, "No tickets found.")
            return
        with open("tickets.csv", 'r', newline='', encoding='utf-8') as file:
            reader = list(csv.reader(file))
            if len(reader) <= 1:
                ticket_list.insert(tk.END, "No tickets found.")
                return
            for row in reader[1:]:
                ticket_list.insert(tk.END, f"Ticket: {row[0]}\nSubject: {row[1]}\nMessage: {row[2]}\n{'-'*50}\n")

    def delete_ticket():
        ticket_id = simpledialog.askstring("Delete Ticket", "Enter Ticket ID to delete (e.g., FE1):")
        if not ticket_id:
            return
        if not os.path.isfile("tickets.csv"):
            messagebox.showerror("Error", "No ticket file found.")
            return

        with open("tickets.csv", 'r', encoding='utf-8') as file:
            reader = list(csv.reader(file))

        new_data = [reader[0]]  # Keep header
        deleted = False
        for row in reader[1:]:
            if row[0] != ticket_id:
                new_data.append(row)
            else:
                deleted = True

        if deleted:
            with open("tickets.csv", 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerows(new_data)
            messagebox.showinfo("Deleted", f"Ticket {ticket_id} deleted.")
            load_tickets()
        else:
            messagebox.showerror("Error", f"Ticket ID {ticket_id} not found.")

    tk.Button(manager_win, text="Refresh Tickets", font=("Arial", 12), command=load_tickets).place(x=1125, y=100)
    tk.Button(manager_win, text="Delete Ticket", font=("Arial", 12), command=delete_ticket).place(x=1130, y=220)

    load_tickets()

def open_staff_accounts_window():
    accounts_window = tk.Toplevel()
    accounts_window.title("Staff - Chatbot Accounts")
    accounts_window.geometry("1250x500")
    accounts_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\abc.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(accounts_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        accounts_window.configure(bg="#ccffcc")

    # Text area (absolute position)
    text_area = scrolledtext.ScrolledText(accounts_window, wrap=tk.WORD, width=120, height=13, font=("Arial", 12))
    text_area.place(x=55, y=70)

    if os.path.isfile("Chatbotdata.csv"):
        with open("Chatbotdata.csv", mode='r', encoding='utf-8') as file:
            content = file.read()
            text_area.insert(tk.END, content)
    else:
        text_area.insert(tk.END, "No accounts found.")

    text_area.config(state='disabled')

# --- Staff Feedback Window (with replies) ---
def open_staff_feedback_window():
    staff_feedback_window = tk.Toplevel()
    staff_feedback_window.title("Staff - Feedback Chat")
    staff_feedback_window.geometry("1250x500")
    staff_feedback_window.configure(bg="#ccffcc")

    tk.Label(staff_feedback_window, text="Staff Feedback Chat", font=("Arial", 16, "bold"), bg="#ccffcc").pack(pady=10)

    chat_display = scrolledtext.ScrolledText(staff_feedback_window, wrap=tk.WORD, width=140, height=20, font=("Arial", 12))
    chat_display.pack(pady=10)
    chat_display.tag_config("staff_label", font=("Arial", 12, "bold"))

    # Load existing feedback and show
    feedbacks = load_feedback()
    for comment, reply in feedbacks:
        chat_display.insert(tk.END, f"User Feedback: {comment}\n")
        if reply.strip():
            chat_display.insert(tk.END, f"Staff Reply: {reply}\n\n")
        else:
            chat_display.insert(tk.END, "\n")
    chat_display.config(state='disabled')

    input_frame = tk.Frame(staff_feedback_window, bg="#ccffcc")
    input_frame.pack(fill=tk.X, pady=10)

    entry = tk.Entry(input_frame, font=("Arial", 12), width=100)
    entry.pack(side=tk.LEFT, padx=5)

    def submit_staff_entry():
        text = entry.get().strip()
        if not text:
            return
        # Append to chat display with bold "Staff Entry:"
        chat_display.config(state='normal')
        chat_display.insert(tk.END, "Staff Entry: ", "staff_label")
        chat_display.insert(tk.END, f"{text}\n\n")
        chat_display.config(state='disabled')
        chat_display.yview(tk.END)
        entry.delete(0, tk.END)

    submit_btn = tk.Button(input_frame, text="Send", font=("Arial", 12), command=submit_staff_entry)
    submit_btn.pack(side=tk.LEFT, padx=5)

# --- Staff Window (after login) ---
def open_staff_window():
    staff_window = tk.Toplevel()
    staff_window.title("Staff Window")
    staff_window.geometry("1250x500")
    staff_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\ccc.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(staff_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        staff_window.configure(bg="#ccffcc")

    # --- Buttons with x & y placement ---
    tk.Button(staff_window, text="FAQ", width=10, font=("Arial", 14), command=open_staff_faq_window).place(x=100, y=373)
    tk.Button(staff_window, text="Accounts", width=10, font=("Arial", 14), command=open_staff_accounts_window).place(x=350, y=373)
    tk.Button(staff_window, text="Feedback", width=10, font=("Arial", 14), command=lambda: open_feedback_window(staff_mode=True)).place(x=600, y=373)
    tk.Button(staff_window, text="Passwords", width=10, font=("Arial", 14), command=open_passwords_window).place(x=850, y=373)
    tk.Button(staff_window, text="Tickets", width=10, font=("Arial", 14), command=open_ticket_manager_window).place(x=1100, y=373)
    tk.Button(staff_window, text="Main Window", width=10, font=("Arial, bold", 12), command=open_main_intro_window).place(x=1135, y=120)

def open_ticket_window():
    ticket_win = tk.Toplevel()
    ticket_win.title("Submit Ticket")
    ticket_win.geometry("1200x500")
    ticket_win.resizable(False, False)

    # Load and display background image
    bg_image_path = r"C:\\Users\\SESA813386\\Documents\\Codinmg\\cc.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1200, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(ticket_win, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        ticket_win.configure(bg="#ccffcc")

    # Foreground widgets
    tk.Label(ticket_win, text="Enter Subject:", font=("Arial", 12), bg="white").pack(pady=11)
    subject_entry = tk.Entry(ticket_win, font=("Arial", 12), width=50)
    subject_entry.pack(pady=11)

    tk.Label(ticket_win, text="Enter Message:", font=("Arial", 12), bg="white").pack(pady=7)
    message_box = scrolledtext.ScrolledText(ticket_win, font=("Arial", 12), width=60, height=10)
    message_box.pack(pady=12)

    def submit_ticket():
        subject = subject_entry.get().strip()
        message = message_box.get("1.0", tk.END).strip()
        if not subject or not message:
            messagebox.showerror("Error", "Subject and message cannot be empty.")
            return

        ticket_file = "tickets.csv"
        ticket_id = 1
        if os.path.isfile(ticket_file):
            with open(ticket_file, 'r', newline='', encoding='utf-8') as file:
                reader = list(csv.reader(file))
                ticket_id = len(reader) + 1

        with open(ticket_file, 'a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            if ticket_id == 1:
                writer.writerow(["Ticket ID", "Subject", "Message"])
            writer.writerow([f"FE{ticket_id}", subject, message])
        
        messagebox.showinfo("Submitted", f"Ticket FE{ticket_id} submitted successfully.")
        ticket_win.destroy()

    tk.Button(ticket_win, text="Submit Ticket", command=submit_ticket).pack(pady=1)


# --- Security Window ---
def open_security_window():
    security_window = tk.Toplevel()
    security_window.title("Staff Security Login")
    security_window.geometry("1250x500")
    security_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\bb.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(security_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        security_window.configure(bg="#ccffcc")

    # --- Login form (centered on page) ---
    form_frame = tk.Frame(security_window, bg="white")  # white background for readability
    form_frame.place(relx=0.52, rely=0.43, anchor="center")

    tk.Label(form_frame, text="Staff Login", font=("Arial", 16), bg="white").pack(pady=10)

    tk.Label(form_frame, text="Username:", font=("Arial", 12), bg="white").pack()
    username_entry = tk.Entry(form_frame, font=("Arial", 12))
    username_entry.pack(pady=5)

    tk.Label(form_frame, text="Password:", font=("Arial", 12), bg="white").pack()
    password_entry = tk.Entry(form_frame, font=("Arial", 12), show="*")
    password_entry.pack(pady=5)

    valid_users = {"1": "a", "2": "b", "3": "c"}

    def attempt_login():
        username = username_entry.get().strip()
        password = password_entry.get().strip()
        if username in valid_users and valid_users[username] == password:
            messagebox.showinfo("Success", "Login successful!")
            security_window.destroy()
            open_staff_window()
        else:
            messagebox.showerror("Error", "Invalid username or password.")

    tk.Button(form_frame, text="Login", font=("Arial", 12), command=attempt_login).pack(pady=15)

def open_main_intro_window():
    main_window = tk.Tk()
    main_window.title("Main Intro Window")
    main_window.geometry("1250x500")
    main_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\c.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        bg_label = tk.Label(main_window, image=bg_photo)
        bg_label.image = bg_photo  # Keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        main_window.configure(bg="#ccffcc")

    # --- Vertically centered Help and Ticket buttons (moved down by 50) ---
    button_y = (500 // 2 - 20) + 50
    help_button = tk.Button(
        main_window, text="Help", font=("Arial", 12), width=10,
        command=open_help_window, relief="flat", bg="SystemButtonFace", bd=0
    )
    help_button.place(x=75, y=button_y)

    ticket_button = tk.Button(
        main_window, text="Ticket", font=("Arial", 12), width=10,
        command=open_ticket_window, relief="flat", bg="SystemButtonFace", bd=0
    )
    ticket_button.place(x=1075, y=button_y)

    # --- Bottom navigation buttons (absolute positioning) ---
    y_pos = 385
    x_start = 50
    x_gap = 205

    tk.Button(main_window, text="Create an Account", font=("Arial", 12), width=16,
              command=open_create_account_window, relief="flat", bg="SystemButtonFace", bd=0).place(x=x_start, y=y_pos)

    tk.Button(main_window, text="FAQ", font=("Arial", 12), width=16,
              command=open_faq_window, relief="flat", bg="SystemButtonFace", bd=0).place(x=x_start + x_gap, y=y_pos)

    tk.Button(main_window, text="Feedback", font=("Arial", 12), width=16,
              command=open_feedback_window, relief="flat", bg="SystemButtonFace", bd=0).place(x=x_start + x_gap * 2, y=y_pos)

    tk.Button(main_window, text="Edit Profile", font=("Arial", 12), width=16,
              command=open_user_profile_window, relief="flat", bg="SystemButtonFace", bd=0).place(x=x_start + x_gap * 3, y=y_pos)

    tk.Button(main_window, text="Launch Chatbot", font=("Arial", 12), width=16,
              command=open_chatbot_host, relief="flat", bg="SystemButtonFace", bd=0).place(x=x_start + x_gap * 4, y=y_pos)

    tk.Button(main_window, text="Staff Entry", font=("Arial", 12), width=16,
              command=open_security_window, relief="flat", bg="SystemButtonFace", bd=0).place(x=x_start + x_gap * 5, y=y_pos)

    main_window.mainloop()


def open_entry_window():
    entry_window = tk.Tk()
    entry_window.title("Entry Window")
    entry_window.geometry("1250x500")
    entry_window.resizable(False, False)

    # --- Load and display background image ---
    bg_image_path = r"C:\Users\SESA813386\Documents\Codinmg\a.png"
    try:
        bg_image = Image.open(bg_image_path)
        bg_image = bg_image.resize((1250, 500), Image.Resampling.LANCZOS)
        bg_photo = ImageTk.PhotoImage(bg_image)

        # Background label
        bg_label = tk.Label(entry_window, image=bg_photo)
        bg_label.image = bg_photo  # keep reference
        bg_label.place(x=0, y=0, relwidth=1, relheight=1)
    except Exception as e:
        messagebox.showerror("Image Error", f"Failed to load background image:\n{e}")
        entry_window.configure(bg="#ccffcc")

    # --- Next button slightly higher ---
    def next_button_clicked():
        entry_window.destroy()  # Close entry window
        open_main_intro_window()  # Open main intro window

    tk.Button(entry_window, text="Next", font=("Arial", 16), command=next_button_clicked).place(relx=0.52, rely=0.64, anchor="center")

    entry_window.mainloop()

# --- Run the application ---
if __name__ == "__main__":
    open_entry_window()
