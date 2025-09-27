from flask import Flask, request, jsonify, render_template
import logging
import os
import google.generativeai as genai
from flask_cors import CORS
from google.generativeai.types import GenerationConfig
import sqlite3
import random
import string
from datetime import datetime, timedelta
import os

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

flask_app = Flask(__name__)
CORS(flask_app)

# Ensure GEMINI_API_KEY is set (omitted for brevity)
# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# MODEL_NAME = "gemini-2.5-flash-lite"
# -------------------------------------------------------------

# ----------------- Database Quota Management -----------------
DATABASE = 'quota.db'
DAILY_LIMIT = 5
PREMIUM_DAILY_LIMIT = 999999 # Effectively unlimited

def get_db_connection():
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
                -- CRITICAL FIX: Tracks when access EXPIRES (closes the loophole)
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

        # --- 1. PREMIUM ACCESS CHECK (EXPIRATION LOOPHOLE CLOSED) ---
        if record and record['premium_expires_on'] and record['premium_expires_on'] != '1970-01-01':
            expires_on_date = datetime.strptime(record['premium_expires_on'], '%Y-%m-%d')
            
            # If the expiration date is in the future, grant premium access
            if expires_on_date >= datetime.now():
                logging.info(f"Premium access granted for user {user_id}.")
                return True 
            else:
                logging.info(f"Subscription expired for user {user_id}. Reverting to free limit.")

        # --- 2. FREE USER / EXPIRED USER LOGIC (RATE LIMITING) ---
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

# ... (process_suggestions and generate_suggestions remain the same) ...

@flask_app.route('/get_suggestions', methods=['POST'])
def get_suggestions():
    try:
        data = request.get_json()
        app_name = data.get('app_name', '')
        user_id = data.get('user_id', None) # This is the App Set ID

        if not app_name:
            return jsonify({'status': 'error', 'message': 'App name is required'}), 400
        
        if not user_id:
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

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

@flask_app.route('/verify_purchase', methods=['POST'])
def verify_purchase():
    try:
        data = request.get_json()
        app_set_id = data.get('user_id') 
        purchase_token = data.get('purchase_token')
        product_id = data.get('product_id')

        if not all([app_set_id, purchase_token, product_id]):
            return jsonify({'status': 'error', 'message': 'Missing data'}), 400
        
        # VITAL: In a REAL app, you would verify the purchase_token with Google Play Billing API here
        is_valid = True 
        
        if is_valid:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # --- 1. EXPIRATION DATE CALCULATION (e.g., 30 days from now) ---
            expiration_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            
            # --- 2. GENERATE UNIQUE RECOVERY KEY ---
            recovery_key = generate_recovery_key()

            # --- 3. ACTIVATE ACCESS IN REQUESTS TABLE (App Set ID) ---
            cursor.execute("""
                INSERT OR REPLACE INTO requests 
                (user_id, request_count, last_request_date, premium_expires_on)
                VALUES (?, 0, ?, ?)
            """, (app_set_id, datetime.now().strftime('%Y-%m-%d'), expiration_date))
            
            # --- 4. STORE RECOVERY RECORD (Purchase Token & Key) ---
            cursor.execute("""
                INSERT OR REPLACE INTO premium_records 
                (app_set_id, purchase_token, recovery_key) 
                VALUES (?, ?, ?)
            """, (app_set_id, purchase_token, recovery_key))
            
            conn.commit()
            conn.close()
            
            logging.info(f"Subscription activated for App Set ID {app_set_id}. Key: {recovery_key}.")
            
            # CRITICAL: Return the UNIQUE recovery key to the client 
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

        # 1. Look up the subscription record using the user's recovery key
        cursor.execute("SELECT purchase_token, app_set_id FROM premium_records WHERE recovery_key = ?", (recovery_key,))
        record = cursor.fetchone()

        if not record:
            conn.close()
            return jsonify({'status': 'error', 'message': 'Invalid recovery key.'}), 404

        purchase_token = record['purchase_token']
        
        # 2. Re-verify the current status based on the Purchase Token
        # A REAL app would call the Google API with the purchase_token here.
        
        # --- PLACEHOLDER LOGIC ---
        # Instead of calling Google, we search the requests table for the EXPIRATION DATE 
        # linked to the purchase_token's OLD App Set ID. This is a compromise.
        cursor.execute("SELECT premium_expires_on FROM requests WHERE user_id = ?", (record['app_set_id'],))
        old_status_record = cursor.fetchone()
        
        if not old_status_record:
            # Should not happen if tables are consistent, but handles edge case
            return jsonify({'status': 'error', 'message': 'No purchase record found for this key.'}), 404
        
        expires_on_date = datetime.strptime(old_status_record['premium_expires_on'], '%Y-%m-%d')
        
        if expires_on_date < datetime.now():
            conn.close()
            return jsonify({'status': 'error', 'message': 'Subscription Expired. Please resubscribe.'}), 403
        
        # 3. GRANT PREMIUM STATUS to the *new* App Set ID
        # Calculate the remaining access time based on the old expiration date
        time_left = expires_on_date - datetime.now()
        new_expiration_date = (datetime.now() + time_left).strftime('%Y-%m-%d')
        
        cursor.execute("""
            INSERT OR REPLACE INTO requests 
            (user_id, request_count, last_request_date, premium_expires_on) 
            VALUES (?, 0, ?, ?)
        """, (new_app_set_id, datetime.now().strftime('%Y-%m-%d'), new_expiration_date))

        # 4. UPDATE the recovery_keys table to link the key to the new App Set ID 
        cursor.execute("UPDATE premium_records SET app_set_id = ? WHERE recovery_key = ?", 
                       (new_app_set_id, recovery_key))


        conn.commit()
        conn.close()
        logging.info(f"Access restored. New App Set ID {new_app_set_id} linked to key {recovery_key}.")
        return jsonify({'status': 'success', 'message': 'Subscription restored.'}), 200

    except Exception as e:
        logging.error(f"Error in /restore_access endpoint: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500


init_db()

if __name__ == '__main__':
    import random
    random.seed(datetime.now())
    
    flask_app.run(debug=True, host='0.0.0.0', port=5000)
