from flask import Flask, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import pytz

app = Flask(__name__)
CORS(app)

# Myanmar Time Zone Setup
MM_TZ = pytz.timezone('Asia/Yangon')

# History Store
history_data = {
    "11": None,
    "12": None,
    "15": None,
    "16": None,
    "date": ""
}

# Web Scraping Function
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
        
        filtered_data = [d for d in stock_data if "SET" in d["Symbol"]]
        return filtered_data
    except Exception as e:
        print("Error fetching SET data:", e)
        return []

# Helper to format 2D String
def format_2d(set_val, val):
    try:
        set_digit = str(set_val)[-1]
        val_front = str(val).split('.')[0].replace(',', '')
        val_digit = val_front[-1]
        
        return {
            "result2D": set_digit + val_digit,
            "setFormatted": str(set_val)[:-1] + f'<span class="highlight-y">{set_digit}</span>',
            "valFormatted": str(val)[:-1] + f'<span class="highlight-y">{val_digit}</span>'
        }
    except Exception as e:
        return None

# Cron Job Function for Saving Slots
def save_time_slot(slot_key):
    now_mm = datetime.now(MM_TZ)
    today_str = now_mm.strftime('%Y-%m-%d')
    
    # New Day Reset
    if history_data["date"] != today_str:
        history_data["11"] = None
        history_data["12"] = None
        history_data["15"] = None
        history_data["16"] = None
        history_data["date"] = today_str

    data = fetch_set_live_data()
    if data:
        set_item = next((item for item in data if item['Symbol'] == 'SET'), None)
        if set_item:
            parsed = format_2d(set_item['Last'], set_item['Value'])
            if parsed:
                history_data[slot_key] = parsed
                print(f"[{now_mm.strftime('%H:%M:%S')}] Saved Slot {slot_key}: {parsed['result2D']}")

# Myanmar Time-based Background Scheduler
scheduler = BackgroundScheduler(timezone=MM_TZ)
scheduler.add_job(save_time_slot, 'cron', hour=11, minute=0, args=['11'])    # 11:00 AM MM
scheduler.add_job(save_time_slot, 'cron', hour=12, minute=1, args=['12'])    # 12:01 PM MM
scheduler.add_job(save_time_slot, 'cron', hour=15, minute=0, args=['15'])    # 03:00 PM MM
scheduler.add_job(save_time_slot, 'cron', hour=16, minute=30, args=['16'])   # 04:30 PM MM
scheduler.start()

# Existing Live Endpoint
@app.route('/live-2d', methods=['GET'])
def get_live_set_data():
    data = fetch_set_live_data()
    if data:
        return jsonify({"status": "success", "data": data})
    else:
        return jsonify({"status": "error", "message": "Failed to fetch data"})

# New Endpoint for History Slots
@app.route('/history-2d', methods=['GET'])
def get_history_2d():
    return jsonify({"status": "success", "history": history_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
