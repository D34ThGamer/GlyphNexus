from flask import Flask, request, jsonify
import logging
import os
import sqlite3
import random
import string
from datetime import datetime, timedelta

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Initialize Flask app
flask_app = Flask(__name__)
# CORS configuration goes here (omitted for brevity)

# NOTE: Replace 'os.getenv("GEMINI_API_KEY")' with your actual setup
# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# MODEL_NAME = "gemini-2.5-flash-lite" 
# -------------------------------------------------------------

# ----------------- Database Quota Management -----------------
DATABASE = 'quota.db'
DAILY_LIMIT = 5
# -------------------------------------------------------------

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def generate_recovery_key(length=8):
    """Generates a unique, alphanumeric recovery key."""
    # Use upper case letters and digits for easy typing by the user
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def init_db():
    """Initializes the database and creates the necessary tables."""
    with get_db_connection() as conn:
        # 1. Primary table for Quota and Status
        conn.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                user_id TEXT PRIMARY KEY,
                request_count INTEGER NOT NULL,
                last_request_date TEXT NOT NULL,
                premium_expires_on TEXT DEFAULT '1970-01-01' 
            )
        ''')
        # 2. Table for Recovery (links purchase details to the short Key)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS premium_records (
                app_set_id TEXT NOT NULL,
                purchase_token TEXT PRIMARY KEY,
                recovery_key TEXT UNIQUE NOT NULL
            )
        ''')
        conn.commit()

def check_user_quota(user_id):
    """
    Checks and updates a user's daily request quota based on App Set ID and Expiration Date.
    """
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT request_count, last_request_date, premium_expires_on FROM requests WHERE user_id = ?", (user_id,))
        record = cursor.fetchone()

        # 1. PREMIUM ACCESS CHECK (Expiration Loophole Fix)
        if record and record['premium_expires_on'] and record['premium_expires_on'] != '1970-01-01':
            expires_on_date = datetime.strptime(record['premium_expires_on'], '%Y-%m-%d')
            
            # Grant premium access if the expiration date is today or in the future
            if expires_on_date >= datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
                logging.info(f"Premium access granted for user {user_id}.")
                conn.close()
                return True 
            else:
                logging.info(f"Subscription expired for user {user_id}. Reverting to free limit.")

        # 2. FREE USER / EXPIRED USER LOGIC (Rate Limiting)
        user_limit = DAILY_LIMIT
        
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
            # New user: insert free entry
            cursor.execute("INSERT INTO requests (user_id, request_count, last_request_date) VALUES (?, ?, ?)", (user_id, 1, today))

        conn.commit()
        return True
    
    except Exception as e:
        logging.error(f"Database error while checking quota for user {user_id}: {e}")
        return False
    finally:
        conn.close()

# ... (process_suggestions and generate_suggestions omitted for brevity, assume they are correct) ...

@flask_app.route('/get_suggestions', methods=['POST'])
def get_suggestions():
    try:
        data = request.get_json()
        app_name = data.get('app_name', '')
        user_id = data.get('user_id', None) # App Set ID

        if not app_name or not user_id:
            return jsonify({'status': 'error', 'message': 'IDs are required'}), 400

        if not check_user_quota(user_id):
            return jsonify({
                'status': 'error', 
                'message': f'You have exceeded your daily limit of {DAILY_LIMIT} requests. Please try again tomorrow.'
            }), 429

        # Assume generate_suggestions() and process_suggestions() are defined elsewhere
        # suggestions = generate_suggestions(app_name) 
        suggestions = ["1. Placeholder suggestion 1", "2. Placeholder suggestion 2"] # Placeholder for running without Gemini API
        
        if not suggestions:
            return jsonify({'status': 'error', 'message': 'No suggestions found'}), 404
        return jsonify({'status': 'success', 'suggestions': suggestions})
    except Exception as e:
        logging.error(f"Error in /get_suggestions endpoint: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

# --- VITAL: THE CORRECTED VERIFY_PURCHASE ENDPOINT ---
@flask_app.route('/verify_purchase', methods=['POST'])
def verify_purchase():
    try:
        data = request.get_json()
        app_set_id = data.get('user_id') 
        purchase_token = data.get('purchase_token')
        product_id = data.get('product_id')

        if not all([app_set_id, purchase_token, product_id]):
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400
        
        # VITAL: In a REAL app, verify the purchase_token with Google Play Billing API here
        # For demonstration, we assume verification succeeded:
        is_valid = True 
        
        if is_valid:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # --- 1. EXPIRATION DATE CALCULATION ---
            # In a real scenario, this date comes from Google's API, not a hardcode.
            # We use 30 days as a standard monthly placeholder.
            expiration_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            
            # --- 2. GENERATE UNIQUE RECOVERY KEY ---
            recovery_key = generate_recovery_key()

            # --- 3. ACTIVATE ACCESS IN REQUESTS TABLE ---
            # This sets the premium status using the calculated expiration date.
            cursor.execute("""
                INSERT OR REPLACE INTO requests 
                (user_id, request_count, last_request_date, premium_expires_on)
                VALUES (?, 0, ?, ?)
            """, (app_set_id, datetime.now().strftime('%Y-%m-%d'), expiration_date))
            
            # --- 4. STORE RECOVERY RECORD ---
            # Links the App Set ID, Purchase Token, and Recovery Key.
            cursor.execute("""
                INSERT OR REPLACE INTO premium_records 
                (app_set_id, purchase_token, recovery_key) 
                VALUES (?, ?, ?)
            """, (app_set_id, purchase_token, recovery_key))
            
            conn.commit()
            conn.close()
            
            logging.info(f"Subscription activated for App Set ID {app_set_id}. Expires {expiration_date}. Key: {recovery_key}.")
            
            # CRITICAL: Return the UNIQUE recovery key to the client for the user to save!
            return jsonify({
                'status': 'success', 
                'message': 'Subscription verified and activated.',
                'recovery_key': recovery_key
            }), 200
        else:
            return jsonify({'status': 'error', 'message': 'Subscription verification failed'}), 401
    except Exception as e:
        logging.error(f"Error in /verify_purchase endpoint: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

# --- NEW: Endpoint for manual restoration after factory reset (requires user input) ---
@flask_app.route('/restore_access', methods=['POST'])
def restore_access():
    try:
        data = request.get_json()
        new_app_set_id = data.get('new_user_id')      
        recovery_key = data.get('recovery_key')   

        if not all([new_app_set_id, recovery_key]):
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Look up the purchase record using the recovery key
        cursor.execute("SELECT purchase_token, app_set_id FROM premium_records WHERE recovery_key = ?", (recovery_key,))
        record = cursor.fetchone()

        if not record:
            conn.close()
            return jsonify({'status': 'error', 'message': 'Invalid recovery key.'}), 404

        # 2. Fetch the current expiration status based on the OLD App Set ID
        old_app_set_id = record['app_set_id']
        cursor.execute("SELECT premium_expires_on FROM requests WHERE user_id = ?", (old_app_set_id,))
        old_status_record = cursor.fetchone()
        
        if not old_status_record:
            return jsonify({'status': 'error', 'message': 'No purchase record found for this key.'}), 404
        
        # Check if the subscription is still valid
        expires_on_date = datetime.strptime(old_status_record['premium_expires_on'], '%Y-%m-%d')
        
        if expires_on_date < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0):
            conn.close()
            return jsonify({'status': 'error', 'message': 'Subscription Expired. Please resubscribe.'}), 403
        
        # 3. Calculate remaining time and apply to the NEW App Set ID
        time_left = expires_on_date - datetime.now()
        new_expiration_date = (datetime.now() + time_left).strftime('%Y-%m-%d')
        
        # Insert/Update the new App Set ID with the remaining time
        cursor.execute("""
            INSERT OR REPLACE INTO requests 
            (user_id, request_count, last_request_date, premium_expires_on) 
            VALUES (?, 0, ?, ?)
        """, (new_app_set_id, datetime.now().strftime('%Y-%m-%d'), new_expiration_date))

        # 4. UPDATE the recovery record to link the key to the new App Set ID 
        cursor.execute("UPDATE premium_records SET app_set_id = ? WHERE recovery_key = ?", 
                       (new_app_set_id, recovery_key))


        conn.commit()
        conn.close()
        logging.info(f"Access restored. New App Set ID {new_app_set_id} linked to key {recovery_key}.")
        return jsonify({'status': 'success', 'message': 'Subscription restored.'}), 200

    except Exception as e:
        logging.error(f"Error in /restore_access endpoint: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500


if __name__ == '__main__':
    # Initialize random seed for Key generation
    import random
    random.seed(datetime.now())
    
    init_db()
    # Flask app run command goes here
    flask_app.run(debug=True, host='0.0.0.0', port=5000)
