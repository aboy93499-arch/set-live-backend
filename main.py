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

# Helper to format 2D String with Highlighting
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
        print("Formatting error:", e)
        return None

# Cron Job & Save Engine
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

    # Stop duplicate overwriting if already captured
    if history_data[slot_key] is not None:
        return

    data = fetch_set_live_data()
    if data:
        set_item = next((item for item in data if item['Symbol'] == 'SET'), None)
        if set_item:
            parsed = format_2d(set_item['Last'], set_item['Value'])
            if parsed:
                history_data[slot_key] = parsed
                print(f"[{now_mm.strftime('%H:%M:%S')}] Saved Slot {slot_key}: {parsed['result2D']}")

# Smart Auto Sync (Guye hue time windows ke slots ko instant lock karega)
def auto_sync_check():
    now_mm = datetime.now(MM_TZ)
    today_str = now_mm.strftime('%Y-%m-%d')
    
    if history_data["date"] != today_str:
        history_data["11"] = None
        history_data["12"] = None
        history_data["15"] = None
        history_data["16"] = None
        history_data["date"] = today_str

    time_mins = now_mm.hour * 60 + now_mm.minute

    # Agar slot ka timing ho chuka hai aur wo khali hai, toh latest market value se fill kar do
    if time_mins >= 660 and not history_data["11"]:    # 11:00 AM MM (660 mins)
        save_time_slot("11")
    if time_mins >= 721 and not history_data["12"]:    # 12:01 PM MM (721 mins)
        save_time_slot("12")
    if time_mins >= 900 and not history_data["15"]:    # 03:00 PM MM (900 mins)
        save_time_slot("15")
    if time_mins >= 990 and not history_data["16"]:    # 04:30 PM MM (990 mins)
        save_time_slot("16")

# Scheduler Setup
scheduler = BackgroundScheduler(timezone=MM_TZ)

# Exact Cron Slots
scheduler.add_job(save_time_slot, 'cron', hour=11, minute=0, args=['11'])
scheduler.add_job(save_time_slot, 'cron', hour=12, minute=1, args=['12'])
scheduler.add_job(save_time_slot, 'cron', hour=15, minute=0, args=['15'])
scheduler.add_job(save_time_slot, 'cron', hour=16, minute=30, args=['16'])

# Auto sync checker runs every 1 minute
scheduler.add_job(auto_sync_check, 'interval', minutes=1)

scheduler.start()

@app.route('/live-2d', methods=['GET'])
def get_live_set_data():
    data = fetch_set_live_data()
    if data:
        return jsonify({"status": "success", "data": data})
    else:
        return jsonify({"status": "error", "message": "Failed to fetch data"})

@app.route('/history-2d', methods=['GET'])
def get_history_2d():
    return jsonify({"status": "success", "history": history_data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
