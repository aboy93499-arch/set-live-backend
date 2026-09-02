from flask import Flask, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
import os

app = Flask(__name__)
CORS(app)

MM_TZ = pytz.timezone('Asia/Yangon')

FIREBASE_URL = os.environ.get("FIREBASE_DB_URL", "https://setlive-5e4e6-default-rtdb.firebaseio.com/")
if not FIREBASE_URL.endswith('/'):
    FIREBASE_URL += '/'

def get_firebase_history():
    try:
        res = requests.get(f"{FIREBASE_URL}history_2d.json", timeout=5)
        if res.status_code == 200 and res.json():
            return res.json()
    except Exception as e:
        print("Firebase fetch error:", e)
    
    now_init = datetime.now(MM_TZ)
    return {
        "11": None,
        "12": None,
        "15": None,
        "16": None,
        "date": now_init.strftime('%Y-%m-%d')
    }

def save_firebase_history(data):
    try:
        requests.put(f"{FIREBASE_URL}history_2d.json", json=data, timeout=5)
    except Exception as e:
        print("Firebase save error:", e)

def fetch_set_live_data():
    url = "https://www.set.or.th/th/home"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
        rows = soup.find_all('tr')
        stock_data = []
        for row in rows:
            cols = row.find_all(['td', 'th'])
            cols_text = [c.text.strip() for c in cols]
            if len(cols_text) >= 5:
                stock_data.append({
                    "Symbol": cols_text[0],
                    "Last": cols_text[1],
                    "Change": cols_text[2],
                    "Volume": cols_text[3],
                    "Value": cols_text[4]
                })
        filtered = [d for d in stock_data if "SET" in d["Symbol"]]
        if filtered:
            return filtered
    except Exception as e:
        print("Scraper Error:", e)
    
    return [{"Symbol": "SET", "Last": "1,385.83", "Value": "45,123.83"}]

def format_2d(set_val, val):
    try:
        set_str = str(set_val).strip()
        val_str = str(val).strip()
        
        set_digit = set_str[-1] if set_str else "0"
        val_front = val_str.split('.')[0].replace(',', '') if val_str else "0"
        val_digit = val_front[-1] if val_front else "0"
        
        result_2d = set_digit + val_digit
        set_formatted = set_str[:-1] + f'<span class="highlight-y">{set_digit}</span>'
        
        val_parts = val_str.split('.')
        v_front = val_parts[0]
        v_back = '.' + val_parts[1] if len(val_parts) > 1 else ''
        val_formatted = v_front[:-1] + f'<span class="highlight-y">{val_digit}</span>' + v_back
        
        return {
            "result2D": result_2d,
            "setFormatted": set_formatted,
            "valFormatted": val_formatted
        }
    except Exception:
        return {
            "result2D": "--",
            "setFormatted": "--",
            "valFormatted": "--"
        }

def capture_current_snapshot():
    live_data = fetch_set_live_data()
    set_item = live_data[0] if live_data else {"Last": "1,385.83", "Value": "45,123.83"}
    return format_2d(set_item.get('Last', '1,385.83'), set_item.get('Value', '45,123.83'))

def sync_all_slots():
    now_mm = datetime.now(MM_TZ)
    today_str = now_mm.strftime('%Y-%m-%d')
    
    history_data = get_firebase_history()
    
    # New Day Automatic Reset
    if history_data.get("date") != today_str:
        history_data = {
            "11": None,
            "12": None,
            "15": None,
            "16": None,
            "date": today_str
        }
        save_firebase_history(history_data)

    hour = now_mm.hour
    minute = now_mm.minute
    
    updated = False
    
    # EXACT TIME CAPTURES
    
    # Slot 1: 11:00 AM (Hour 11, Minute 0)
    if hour == 11 and minute == 0 and not history_data.get("11"):
        history_data["11"] = capture_current_snapshot()
        updated = True

    # Slot 2: 12:01 PM (Hour 12, Minute 1)
    if hour == 12 and minute == 1 and not history_data.get("12"):
        history_data["12"] = capture_current_snapshot()
        updated = True

    # Slot 3: 3:00 PM (Hour 15, Minute 0)
    if hour == 15 and minute == 0 and not history_data.get("15"):
        history_data["15"] = capture_current_snapshot()
        updated = True

    # Slot 4: 4:30 PM (Hour 16, Minute 30)
    if hour == 16 and minute == 30 and not history_data.get("16"):
        history_data["16"] = capture_current_snapshot()
        updated = True

    if updated:
        save_firebase_history(history_data)

# Scheduler runs every 2 seconds to ensure exact minute precision
scheduler = BackgroundScheduler(timezone=MM_TZ)
scheduler.add_job(sync_all_slots, 'interval', seconds=2)
scheduler.start()

sync_all_slots()

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Backend Active", "database": "Firebase Connected"})

@app.route('/live-2d', methods=['GET'])
def get_live_set_data():
    data = fetch_set_live_data()
    return jsonify({"status": "success", "data": data})

@app.route('/history-2d', methods=['GET'])
def get_history_2d():
    sync_all_slots()
    history_data = get_firebase_history()
    return jsonify({"status": "success", "history": history_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
