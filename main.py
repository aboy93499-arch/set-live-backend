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
    
    return []

def format_2d(set_val, val):
    try:
        set_str = str(set_val).strip()
        val_str = str(val).strip()
        
        if not set_str or not val_str or set_str == "--" or val_str == "--":
            return {"result2D": "--", "setFormatted": "--", "valFormatted": "--"}

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
    if live_data:
        set_item = live_data[0]
        return format_2d(set_item.get('Last', ''), set_item.get('Value', ''))
    return {"result2D": "--", "setFormatted": "--", "valFormatted": "--"}

def check_day_reset():
    now_mm = datetime.now(MM_TZ)
    today_str = now_mm.strftime('%Y-%m-%d')
    history_data = get_firebase_history()
    
    # Strictly reset only on Monday-Friday when day changes
    if history_data.get("date") != today_str:
        if now_mm.weekday() < 5:
            history_data = {
                "11": None,
                "12": None,
                "15": None,
                "16": None,
                "date": today_str
            }
            save_firebase_history(history_data)

def capture_slot(slot_key):
    now_mm = datetime.now(MM_TZ)
    # Don't capture on Saturday (5) or Sunday (6)
    if now_mm.weekday() in [5, 6]:
        return

    check_day_reset()
    history_data = get_firebase_history()
    snapshot = capture_current_snapshot()
    
    if snapshot["result2D"] != "--":
        history_data[slot_key] = snapshot
        save_firebase_history(history_data)

def is_market_open():
    now_mm = datetime.now(MM_TZ)
    
    # Weekend Closed
    if now_mm.weekday() in [5, 6]:
        return False

    time_mins = now_mm.hour * 60 + now_mm.minute
    
    # Morning: 09:30 AM to 12:01 PM
    # Afternoon: 01:30 PM to 04:30 PM
    session1 = 570 <= time_mins < 721
    session2 = 810 <= time_mins < 990
    
    return session1 or session2

scheduler = BackgroundScheduler(timezone=MM_TZ)

# Exact Time CRON Jobs (Mon-Fri)
scheduler.add_job(capture_slot, 'cron', day_of_week='mon-fri', hour=11, minute=0, second=0, args=['11'])
scheduler.add_job(capture_slot, 'cron', day_of_week='mon-fri', hour=12, minute=1, second=0, args=['12'])
scheduler.add_job(capture_slot, 'cron', day_of_week='mon-fri', hour=15, minute=0, second=0, args=['15'])
scheduler.add_job(capture_slot, 'cron', day_of_week='mon-fri', hour=16, minute=30, second=0, args=['16'])

# Reset Job (Morning 9:00 AM on Weekdays)
scheduler.add_job(check_day_reset, 'cron', day_of_week='mon-fri', hour=9, minute=0, second=0)

scheduler.start()

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Backend Active", "database": "Firebase Connected"})

@app.route('/live-2d', methods=['GET'])
def get_live_set_data():
    market_active = is_market_open()
    history = get_firebase_history()
    
    if market_active:
        data = fetch_set_live_data()
        return jsonify({"status": "success", "live": True, "data": data})
    else:
        # Show last saved valid snapshot when market is closed/break
        now_mm = datetime.now(MM_TZ)
        time_mins = now_mm.hour * 60 + now_mm.minute
        
        frozen_snapshot = None
        if 721 <= time_mins < 810:
            frozen_snapshot = history.get("12")
        elif time_mins >= 990 or time_mins < 570 or now_mm.weekday() in [5, 6]:
            # Priority: 16 -> 15 -> 12 -> 11 (Whatever was recorded last)
            frozen_snapshot = history.get("16") or history.get("15") or history.get("12") or history.get("11")

        return jsonify({
            "status": "success",
            "live": False,
            "data": frozen_snapshot if frozen_snapshot else []
        })

@app.route('/history-2d', methods=['GET'])
def get_history_2d():
    history_data = get_firebase_history()
    return jsonify({"status": "success", "history": history_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
