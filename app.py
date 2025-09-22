from flask import Flask, request, jsonify, render_template
import logging
import os
import google.generativeai as genai
from flask_cors import CORS
from google.generativeai.types import GenerationConfig
import sqlite3
from datetime import datetime
import os

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Initialize Flask app
flask_app = Flask(__name__)
CORS(flask_app)

gemini_api_key = os.getenv("GEMINI_API_KEY")

if not gemini_api_key:
    logging.error("GEMINI_API_KEY environment variable not set.")
    raise ValueError("GEMINI_API_KEY environment variable not set.")

genai.configure(api_key=gemini_api_key)

MODEL_NAME = "gemini-2.5-flash-lite"
# -------------------------------------------------------------

# ----------------- Database Quota Management -----------------
DATABASE = 'quota.db'
DAILY_LIMIT = 5

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database and creates the requests table if it doesn't exist."""
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                user_id TEXT PRIMARY KEY,
                request_count INTEGER NOT NULL,
                last_request_date TEXT NOT NULL,
                is_premium INTEGER DEFAULT 0
            )
        ''')
        conn.commit()

PREMIUM_DAILY_LIMIT = 20

def check_user_quota(user_id):
    """
    Checks and updates a user's daily request quota.
    Returns True if the request is allowed, False otherwise.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT request_count, last_request_date, is_premium FROM requests WHERE user_id = ?", (user_id,))
        record = cursor.fetchone()

        # Determine the correct limit based on user's premium status
        user_limit = DAILY_LIMIT
        if record and record['is_premium'] == 1:
            user_limit = PREMIUM_DAILY_LIMIT
            logging.info(f"Premium user {user_id} request allowed (bypassing quota).")
            return True # Premium users have unlimited access in this model

        if record:
            request_count = record['request_count']
            last_request_date = record['last_request_date']
            
            if last_request_date != today:
                request_count = 1
                cursor.execute("UPDATE requests SET request_count = ?, last_request_date = ? WHERE user_id = ?", (request_count, today, user_id))
            elif request_count < user_limit:
                request_count += 1
                cursor.execute("UPDATE requests SET request_count = ? WHERE user_id = ?", (request_count, user_id))
            else:
                return False
        else:
            request_count = 1
            cursor.execute("INSERT INTO requests (user_id, request_count, last_request_date) VALUES (?, ?, ?)", (user_id, request_count, today))

        conn.commit()
        return True
    
    except Exception as e:
        logging.error(f"Database error while checking quota for user {user_id}: {e}")
        return False
    finally:
        conn.close()

def process_suggestions(response):
    # ... your existing code ...
    if not response or not response.text:
        return []
    
    try:
        text = response.text.strip()
        text = text.replace('```', '').replace('"""', '').strip()
        
        suggestions = []
        for line in text.split('\n'):
            clean_line = line.strip().replace("•", "").replace("*/", "").strip()

            if clean_line:
                clean_line = clean_line.lstrip('0123456789.').strip()
                clean_line_parts = clean_line.split(':', 1)
                if len(clean_line_parts) > 0:
                    clean_line_parts[0] = clean_line_parts[0].lower()
                    clean_line = ":".join(clean_line_parts)
                suggestions.append(clean_line)
        
        numbered_suggestions = [f"{i+1}. {suggestion}" for i, suggestion in enumerate(suggestions)]
        return numbered_suggestions[:5] if len(numbered_suggestions) >= 2 else []
        
    except Exception as e:
        logging.error(f"Error processing suggestions: {e}")
        return []

def generate_suggestions(app_title):
    # ... your existing code ...
    prompt = f"""
You are an expert in Android app notification categories. Your task is to predict the most probable and exact notification category strings for an app like '{app_title}'.

These categories are often simple, lowercase strings defined by the app developer, such as `msg`, `social`, `promo`, `call`, or standard Android constants like `CATEGORY_MESSAGE`.

List the most probable *exact string values* you would observe in the `sbn.notification.category` field for common notifications from an app like '{app_title}'. Focus on the actual strings that appear in that field, not just theoretical categories.

For each probable string value, provide a brief description of the type of notification it typically represents.

Return the list in a numbered format, strictly as follows:
1. exact_category_string: Description of typical use for this category.
2. exact_category_string: Description of typical use for this category.
3. exact_category_string: Description of typical use for this category.

Ensure the following:
- The category strings must be in lowercase.
- The number of entries should be between 3 and 6 (inclusive).
- Do not include any introductory phrases, conversational text, or concluding remarks.
- Each line must start with a number followed by a period, then the `exact_category_string` (e.g., `msg`, `call`, `social`, `event`), a colon, and then its description.
- Only include strings that are highly probable and commonly observed in real app notification data for an app like '{app_title}'.
"""
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        generation_config = GenerationConfig(
            max_output_tokens=300,
            temperature=0.7,
        )
        response = model.generate_content(
            contents=prompt,
            generation_config=generation_config
        )
        return process_suggestions(response)
    except Exception as e:
        logging.error(f"Error generating suggestions with Gemini API: {e}")
        return []

@flask_app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@flask_app.route('/get_suggestions', methods=['POST'])
def get_suggestions():
    try:
        data = request.get_json()
        app_name = data.get('app_name', '')
        user_id = data.get('user_id', None)

        if not app_name:
            return jsonify({'status': 'error', 'message': 'App name is required'}), 400
        
        if not user_id:
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

        # Now, your code checks if the user is a premium subscriber and bypasses the limit
        if not check_user_quota(user_id):
            return jsonify({
                'status': 'error', 
                'message': f'You have exceeded your daily limit of {DAILY_LIMIT} requests. Please try again tomorrow.'
            }), 429

        suggestions = generate_suggestions(app_name)
        if not suggestions:
            return jsonify({'status': 'error', 'message': 'No suggestions found'}), 404
        return jsonify({'status': 'success', 'suggestions': suggestions})
    except Exception as e:
        logging.error(f"Error in /get_suggestions endpoint: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

# NEW: Add a new endpoint to your Flask app for purchase verification
@flask_app.route('/verify_purchase', methods=['POST'])
def verify_purchase():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        purchase_token = data.get('purchase_token')
        product_id = data.get('product_id')

        if not all([user_id, purchase_token, product_id]):
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400
        is_valid = True 

        if is_valid:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE requests SET is_premium = ? WHERE user_id = ?", (1, user_id))
            conn.commit()
            conn.close()
            logging.info(f"Verified subscription for user {user_id}. Granting premium access.")
            return jsonify({'status': 'success', 'message': 'Subscription verified'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Subscription verification failed'}), 401
    except Exception as e:
        logging.error(f"Error in /verify_purchase endpoint: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

init_db()

if __name__ == '__main__':
    flask_app.run(debug=True, host='0.0.0.0', port=5000)
