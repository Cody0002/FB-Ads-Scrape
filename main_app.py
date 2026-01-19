from flask import Flask, request, jsonify
import json
from lark_bot.core import handle_incoming_message
from lark_bot.config import VERIFICATION_TOKEN
import logging
import threading

from lark_bot.command_handlers import command_handler
from lark_bot.state_managers import state_manager
import datetime
import time

# Setup logging
from logging.handlers import RotatingFileHandler
import os

# Create logs directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Configure logging with rotation
# This keeps 5 backup files, each max 10MB
handler = RotatingFileHandler('logs/bot.log', maxBytes=10*1024*1024, backupCount=5)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)

logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

logger = logging.getLogger(__name__)
app = Flask(__name__)

def verify_token(data):
    """Verify the incoming request token"""
    received_token = data.get('header', {}).get('token')
    return received_token == VERIFICATION_TOKEN

def process_message_async(data, chat_type):
    """Xử lý tin nhắn trong luồng riêng"""
    try:
        # Extract message content
        message_content = data.get('event', {}).get('message', {}).get('content', {})
        message_json = json.loads(message_content)
        text = message_json.get('text', '').strip()
        
        logger.info(f"Processing message: {text}, chat_type: {chat_type}")
        
        # Group chat logic - only respond to commands starting with /
        # if chat_type == "group":
        if text.startswith('/'):
            # Remove the / prefix from the text
            modified_text = text[1:]  # Remove first character (/)
            logger.info(f"Group command detected, modified: '{text}' -> '{modified_text}'")
            
            # Modify the data to remove the / prefix
            message_json['text'] = modified_text
            data['event']['message']['content'] = json.dumps(message_json)
            
            # Process the command in group
            handle_incoming_message(data)
        else:
            logger.warning("No command in group")
        
        # P2P chat logic - respond to all messages
        # elif chat_type == "p2p":
            # logger.info("Processing P2P message")
            # handle_incoming_message(data)
        
        # else:
        #     logger.warning(f"Unknown chat type: {chat_type}")
            
    except Exception as e:
        logger.error(f"Message processing error: {e}")
        
@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint"""
    return jsonify({"status": "ok", "message": "Bot is running"})

@app.route('/webhook', methods=['POST'])
def webhook():
    # ENHANCED DEBUG: Show all event types and details
    print("HIII")
    data = request.json
    chat_type = data.get("event", {}).get("message", {}).get("chat_type")

    print("Received event:", json.dumps(data, indent=2))
    # URL verification
    if data.get('type') == 'url_verification':
        return jsonify({'challenge': data.get('challenge')})
    
    # 1. Verify the token first
    if not verify_token(data):
        return jsonify({'error': 'Invalid token'}), 403
    
    # 3. Xử lý sự kiện tin nhắn không đồng bộ
    if data.get("header", {}).get("event_type") == "im.message.receive_v1":
        threading.Thread(target=process_message_async, args=(data, chat_type)).start()
        return jsonify({"code": 0})
    
    return jsonify({"code": 0, "message": "Event ignored"})



def _should_fire(now_local, hour, minute):
    return now_local.hour == hour and now_local.minute == minute

def scheduler_loop():
    logger.info("Scheduler thread has started successfully.")
    while True:
        try:
            now_utc = datetime.datetime.utcnow()

            # Log the current UTC time for debugging
            print(f"[Scheduler] Tick! Current UTC time: {now_utc.isoformat()}")

            # Iterate all chats that have at least one schedule
            for cid, schedules in list(state_manager.chat_schedules.items()):
                if not schedules:
                    continue
                for s in schedules:
                    h = int(s.get("hour", 0))
                    m = int(s.get("minute", 0))
                    tz = int(s.get("tz_offset", 0))

                    # Compute local time for this schedule
                    now_local = now_utc + datetime.timedelta(hours=tz)

                    # Debounce key (per chat + schedule + minute)
                    key = f"{cid}:{h:02d}:{m:02d}:tz{tz}:{now_local.strftime('%Y%m%d%H%M')}"
                    if _should_fire(now_local, h, m) and state_manager.last_run_key.get(cid) != key:
                        logger.info(f"[Scheduler] FIRING! chat_id={cid}, schedule={h:02d}:{m:02d}, tz={tz}, calculated_local_time={now_local.isoformat()}")
                        # ... rest of the firing logic ...
                        state_manager.last_run_key[cid] = key
                        # Fire the scheduled run
                        command_handler.run_scheduled_crawl(cid, h, m, tz)
        except Exception as e:
            logger.error(f"Scheduler error: {e}")
        finally:
            time.sleep(10)  # check every 5s to be resilient to clock drifts

# Start the scheduler thread when the module is loaded
# This will be executed by Gunicorn
scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
scheduler_thread.start()

if __name__ == "__main__":
    
    app.run(port=5000, debug=True)