from flask import Flask, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
import os
import time

app = Flask(__name__)
CORS(app)

MM_TZ = pytz.timezone('Asia/Yangon')

FIREBASE_URL = os.environ.get("FIREBASE_DB_URL", "https://aungkyaw2d-f6faf-default-rtdb.firebaseio.com/")
if not FIREBASE_URL.endswith('/'):
    FIREBASE_URL += '/'

def get_firebase_node(node_name):
    try:
        res = requests.get(f"{FIREBASE_URL}{node_name}.json", timeout=5)
        if res.status_code == 200 and res.json():
            return res.json()
    except Exception as e:
        print(f"Firebase fetch error ({node_name}):", e)
    return {}

def save_firebase_node(node_name, data):
    try:
        requests.put(f"{FIREBASE_URL}{node_name}.json", json=data, timeout=5)
    except Exception as e:
        print(f"Firebase save error ({node_name}):", e)

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
        return {"result2D": "--", "setFormatted": "--", "valFormatted": "--"}

def capture_current_snapshot():
    live_data = fetch_set_live_data()
    if live_data:
        set_item = live_data[0]
        return format_2d(set_item.get('Last', ''), set_item.get('Value', ''))
    return {"result2D": "--", "setFormatted": "--", "valFormatted": "--"}

def check_day_reset():
    now_mm = datetime.now(MM_TZ)
    today_str = now_mm.strftime('%Y-%m-%d')
    history_data = get_firebase_node("history_2d") or {}
    
    if history_data.get("date") != today_str:
        if now_mm.weekday() < 5:
            history_data = {
                "11": None,
                "12": None,
                "15": None,
                "16": None,
                "date": today_str
            }
            save_firebase_node("history_2d", history_data)

def capture_slot(slot_key):
    now_mm = datetime.now(MM_TZ)
    if now_mm.weekday() in [5, 6]:
        return

    check_day_reset()

    # Dynamic check: Valid data already locked hai toh skip karo
    history_data = get_firebase_node("history_2d") or {}
    if history_data.get(slot_key) and history_data[slot_key].get("result2D") not in ["--", None, ""]:
        print(f"[{slot_key}] Already locked. Skipping.")
        return

    print(f"[{slot_key}] Target time buffer recording started...")

    buffer_data = []

    # Target minute (:00) se 20 seconds tak continuously capture karega
    for _ in range(20):
        capture_time = datetime.now(MM_TZ).strftime('%H:%M:%S')
        snapshot = capture_current_snapshot()
        buffer_data.append({
            "timestamp": capture_time,
            "snapshot": snapshot
        })
        time.sleep(1.0)

    # Pehle non-empty snapshot ko lock karo
    selected_snapshot = None
    winning_time = None

    for item in buffer_data:
        res_2d = item["snapshot"].get("result2D")
        if res_2d not in ["--", None, ""]:
            selected_snapshot = item["snapshot"]
            winning_time = item["timestamp"]
            break 

    if selected_snapshot:
        history_data = get_firebase_node("history_2d") or {}
        history_data[slot_key] = selected_snapshot
        save_firebase_node("history_2d", history_data)

        if slot_key in ["12", "16"]:
            date_key = now_mm.strftime('%Y-%m-%d')
            calendar_records = get_firebase_node("calendar_history") or {}

            if date_key not in calendar_records:
                calendar_records[date_key] = {"res12": "--", "res16": "--", "closed": False}

            if slot_key == "12":
                calendar_records[date_key]["res12"] = selected_snapshot["result2D"]
            elif slot_key == "16":
                calendar_records[date_key]["res16"] = selected_snapshot["result2D"]

            save_firebase_node("calendar_history", calendar_records)

        print(f"[{slot_key}] SUCCESS LOCKED: '{selected_snapshot['result2D']}' at {winning_time}.")
    else:
        print(f"[{slot_key}] No valid result captured.")

def is_market_open():
    now_mm = datetime.now(MM_TZ)
    if now_mm.weekday() in [5, 6]:
        return False

    time_mins = now_mm.hour * 60 + now_mm.minute
    session1 = 570 <= time_mins < 721
    session2 = 810 <= time_mins < 990
    return session1 or session2

scheduler = BackgroundScheduler(timezone=MM_TZ)

# FIXED: Exact :00 seconds trigger to eliminate pre-minute frame capture
scheduler.add_job(capture_slot, 'cron', day_of_week='mon-fri', hour=11, minute=0, second=0, args=['11'])
scheduler.add_job(capture_slot, 'cron', day_of_week='mon-fri', hour=12, minute=1, second=0, args=['12'])
scheduler.add_job(capture_slot, 'cron', day_of_week='mon-fri', hour=15, minute=0, second=0, args=['15'])
scheduler.add_job(capture_slot, 'cron', day_of_week='mon-fri', hour=16, minute=30, second=0, args=['16'])

scheduler.add_job(check_day_reset, 'cron', day_of_week='mon-fri', hour=9, minute=0, second=0)

scheduler.start()

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Backend Active", "database": "Firebase Connected"})

@app.route('/live-2d', methods=['GET'])
def get_live_set_data():
    market_active = is_market_open()
    history = get_firebase_node("history_2d") or {}
    now_mm = datetime.now(MM_TZ)
    
    if market_active:
        data = fetch_set_live_data()
        return jsonify({
            "status": "success", 
            "live": True, 
            "time": now_mm.strftime('%Y-%m-%d %H:%M:%S'),
            "data": data
        })
    else:
        time_mins = now_mm.hour * 60 + now_mm.minute
        frozen_snapshot = None
        
        if 721 <= time_mins < 810:
            frozen_snapshot = history.get("12")
            pause_time = f"{history.get('date', now_mm.strftime('%Y-%m-%d'))} 12:01:00"
        else:
            frozen_snapshot = history.get("16") or history.get("15") or history.get("12") or history.get("11")
            pause_time = f"{history.get('date', now_mm.strftime('%Y-%m-%d'))} 16:30:00"

        return jsonify({
            "status": "success",
            "live": False,
            "time": pause_time,
            "frozenData": frozen_snapshot
        })

@app.route('/history-2d', methods=['GET'])
def get_history_2d():
    history_data = get_firebase_node("history_2d") or {}
    return jsonify({"status": "success", "history": history_data})

@app.route('/calendar-history', methods=['GET'])
def get_calendar_history():
    records = get_firebase_node("calendar_history") or {}
    return jsonify({"status": "success", "records": records})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
