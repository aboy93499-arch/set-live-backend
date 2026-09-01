from flask import Flask, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz
import json
import os

app = Flask(__name__)
CORS(app)

MM_TZ = pytz.timezone('Asia/Yangon')
DATA_FILE = "history.json"

def load_history():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"11": None, "12": None, "15": None, "16": None, "date": ""}

def save_history(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print("File save error:", e)

history_data = load_history()

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
        return [d for d in stock_data if "SET" in d["Symbol"]]
    except Exception as e:
        print("Scraper Error:", e)
        return []

def format_2d(set_val, val):
    try:
        set_str = str(set_val)
        val_str = str(val)
        set_digit = set_str[-1]
        val_front = val_str.split('.')[0].replace(',', '')
        val_digit = val_front[-1]
        
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
    except Exception as e:
        return None

def force_capture_and_save(slot_key):
    data = fetch_set_live_data()
    if data:
        set_item = next((item for item in data if item['Symbol'] == 'SET'), None)
        if set_item:
            parsed = format_2d(set_item['Last'], set_item['Value'])
            if parsed:
                history_data[slot_key] = parsed
                save_history(history_data)

def sync_all_slots():
    now_mm = datetime.now(MM_TZ)
    today_str = now_mm.strftime('%Y-%m-%d')
    
    if history_data["date"] != today_str:
        history_data["11"] = None
        history_data["12"] = None
        history_data["15"] = None
        history_data["16"] = None
        history_data["date"] = today_str
        save_history(history_data)

    time_mins = now_mm.hour * 60 + now_mm.minute

    if time_mins >= 660 and history_data["11"] is None:
        force_capture_and_save("11")
    if time_mins >= 721 and history_data["12"] is None:
        force_capture_and_save("12")
    if time_mins >= 900 and history_data["15"] is None:
        force_capture_and_save("15")
    if time_mins >= 990 and history_data["16"] is None:
        force_capture_and_save("16")

scheduler = BackgroundScheduler(timezone=MM_TZ)
scheduler.add_job(sync_all_slots, 'interval', seconds=15)
scheduler.start()

@app.route('/live-2d', methods=['GET'])
def get_live_set_data():
    data = fetch_set_live_data()
    return jsonify({"status": "success", "data": data}) if data else jsonify({"status": "error"})

@app.route('/history-2d', methods=['GET'])
def get_history_2d():
    sync_all_slots()
    return jsonify({"status": "success", "history": history_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
