from flask import Flask, request, jsonify, render_template
import logging
import os
import sqlite3
import random
import string
import time
from datetime import datetime, timedelta
# NOTE: The dependency on google.generativeai imports would go here

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Initialize Flask app
flask_app = Flask(__name__)
# CORS configuration goes here (omitted for brevity)

# Placeholder for actual API key
gemini_api_key = "AIzaSyBAvodm4p6YnQFsYcBdCqJVsmGw1d7kyPs" 
# -------------------------------------------------------------

# --- GOOGLE SERVICE ACCOUNT CREDENTIALS ---
# This dictionary represents the data from your secure JSON key file.
# Note: In a real environment, you would load this from an environment variable!
SERVICE_ACCOUNT_INFO = {
    "type": "service_account",
    "project_id": "gen-lang-client-0030220266",
    "client_email": "glyph-purchase-verifier@gen-lang-client-0030220266.iam.gserviceaccount.com",
    # The actual private key string should be loaded securely
    "private_key_id": "cfbc2064d94b70685da01854c122d9e36bf71354",
    # ... (private key string omitted for brevity, but needed here)
    "private_key": "YOUR_ACTUAL_PRIVATE_KEY_STRING_HERE",
    # We also need the Android package name for the API call:
    "package_name": "com.voidtechstudios.smartglyph" # <--- IMPORTANT: Add your app's package name
}

# ----------------- Database Quota Management -----------------
DATABASE = 'quota.db'
DAILY_LIMIT = 5
PREMIUM_DAILY_LIMIT = 999999
# -------------------------------------------------------------

# --- PRODUCTION VERIFICATION FUNCTION ---
def verify_purchase_with_google_api(purchase_token, product_id):
    """
    [CRITICAL PLACEHOLDER] This function must securely call the Google Play Developer API.
    
    1. Authenticates using SERVICE_ACCOUNT_INFO.
    2. Calls the URL: 
       /purchases/subscriptions/{product_id}/tokens/{purchase_token}
    3. Extracts the official 'expiryTimeMillis'.
    
    Returns: Expiration date string (YYYY-MM-DD) or None on failure/invalid token.
    """
    logging.warning("--- USING 30-DAY EXPIRATION PLACEHOLDER ---")
    
    # In a real app, if the token is invalid, this function returns None.
    # We will assume success and calculate 30 days for now.
    expiration_dt = datetime.now() + timedelta(days=30)
    
    # Check if the product ID matches an expected subscription type (e.g., "unlimited_ai_calls")
    # if product_id == "unlimited_ai_calls":
    #    # Secure API Call logic goes here
    #    pass
    
    return expiration_dt.strftime('%Y-%m-%d')
# ----------------------------------------


def get_db_connection():
    """Establishes a connection to the SQLite database."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def generate_recovery_key(length=8):
    """Generates a unique, alphanumeric recovery key."""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def init_db():
    """Initializes the database and creates the necessary tables."""
    with get_db_connection() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                user_id TEXT PRIMARY KEY,
                request_count INTEGER NOT NULL,
                last_request_date TEXT NOT NULL,
                premium_expires_on TEXT DEFAULT '1970-01-01' 
            )
        ''')
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

# ... (process_suggestions and generate_suggestions omitted for brevity) ...

@flask_app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@flask_app.route('/get_suggestions', methods=['POST'])
def get_suggestions():
    # ... (function body remains the same, calls check_user_quota) ...
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

        suggestions = ["1. Placeholder suggestion 1", "2. Placeholder suggestion 2"]
        
        if not suggestions:
            return jsonify({'status': 'error', 'message': 'No suggestions found'}), 404
        return jsonify({'status': 'success', 'suggestions': suggestions})
    except Exception as e:
        logging.error(f"Error in /get_suggestions endpoint: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

@flask_app.route('/verify_purchase', methods=['POST'])
def verify_purchase():
    try:
        data = request.get_json()
        app_set_id = data.get('user_id') 
        purchase_token = data.get('purchase_token')
        product_id = data.get('product_id')

        if not all([app_set_id, purchase_token, product_id]):
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400
        
        # --- VITAL: Calls the verification function ---
        expiration_date = verify_purchase_with_google_api(purchase_token, product_id)
        
        if not expiration_date:
             return jsonify({'status': 'error', 'message': 'Subscription verification failed: Invalid token.'}), 401

        conn = get_db_connection()
        cursor = conn.cursor()
        
        # --- 1. GENERATE UNIQUE RECOVERY KEY ---
        recovery_key = generate_recovery_key()

        # --- 2. ACTIVATE ACCESS IN REQUESTS TABLE ---
        cursor.execute("""
            INSERT OR REPLACE INTO requests 
            (user_id, request_count, last_request_date, premium_expires_on)
            VALUES (?, 0, ?, ?)
        """, (app_set_id, datetime.now().strftime('%Y-%m-%d'), expiration_date))
        
        # --- 3. STORE RECOVERY RECORD ---
        cursor.execute("""
            INSERT OR REPLACE INTO premium_records 
            (app_set_id, purchase_token, recovery_key) 
            VALUES (?, ?, ?)
        """, (app_set_id, purchase_token, recovery_key))
        
        conn.commit()
        conn.close()
        
        logging.info(f"Subscription activated for App Set ID {app_set_id}. Expires {expiration_date}. Key: {recovery_key}.")
        
        return jsonify({
            'status': 'success', 
            'message': 'Subscription verified and activated.',
            'recovery_key': recovery_key
        }), 200
        
    except Exception as e:
        logging.error(f"Error in /verify_purchase endpoint: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

# ... (restore_access endpoint remains the same) ...

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
    random.seed(datetime.now().timestamp())
    
    init_db()
    # Flask app run command goes here
    flask_app.run(debug=True, host='0.0.0.0', port=5000)
