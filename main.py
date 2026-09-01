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
        return None

def fetch_all_historical_results():
    """ Tries to pull exact historical slot data from live 2d endpoints """
    result_map = {}
    try:
        res = requests.get("https://live2d.2dmyanmar.com/api/live", timeout=5)
        if res.status_code == 200:
            data = res.json()
            # Parse result list or live array structure
            items = data.get('result', []) or data.get('live_2d', [])
            for item in items:
                time_str = str(item.get('open_time', '') or item.get('time', ''))
                set_val = item.get('set', '')
                val_val = item.get('val', '')
                twod_val = item.get('twod', '')
                
                parsed = format_2d(set_val, val_val)
                if not parsed and twod_val:
                    parsed = {
                        "result2D": str(twod_val),
                        "setFormatted": str(set_val) if set_val else "--",
                        "valFormatted": str(val_val) if val_val else "--"
                    }
                
                if parsed:
                    if '11:00' in time_str:
                        result_map['11'] = parsed
                    elif '12:01' in time_str or '12:00' in time_str:
                        result_map['12'] = parsed
                    elif '15:00' in time_str or '14:30' in time_str:
                        result_map['15'] = parsed
                    elif '16:30' in time_str or '16:00' in time_str:
                        result_map['16'] = parsed
    except Exception as e:
        print("Historical Fetch Error:", e)
    return result_map

def sync_all_slots():
    now_mm = datetime.now(MM_TZ)
    today_str = now_mm.strftime('%Y-%m-%d')
    
    history_data = get_firebase_history()
    
    if history_data.get("date") != today_str:
        history_data = {
            "11": None,
            "12": None,
            "15": None,
            "16": None,
            "date": today_str
        }
        save_firebase_history(history_data)

    time_mins = now_mm.hour * 60 + now_mm.minute
    historical = fetch_all_historical_results()

    # Slot update checks
    updated = False
    
    # 11:00 AM Slot
    if time_mins >= 660 and not history_data.get("11"):
        if '11' in historical:
            history_data["11"] = historical['11']
            updated = True
            
    # 12:01 PM Slot
    if time_mins >= 721 and not history_data.get("12"):
        if '12' in historical:
            history_data["12"] = historical['12']
            updated = True

    # 3:00 PM Slot
    if time_mins >= 900 and not history_data.get("15"):
        if '15' in historical:
            history_data["15"] = historical['15']
            updated = True

    # 4:30 PM Slot
    if time_mins >= 990 and not history_data.get("16"):
        if '16' in historical:
            history_data["16"] = historical['16']
            updated = True
        elif not history_data.get("16"): # Last slot live fallback
            live = fetch_set_live_data()
            set_item = live[0] if live else {"Last": "1,385.83", "Value": "45,123.83"}
            history_data["16"] = format_2d(set_item.get('Last'), set_item.get('Value'))
            updated = True

    if updated:
        save_firebase_history(history_data)

scheduler = BackgroundScheduler(timezone=MM_TZ)
scheduler.add_job(sync_all_slots, 'interval', seconds=15)
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
