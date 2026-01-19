import json
import threading
import time  # Added time
from datetime import datetime, timedelta # Added timedelta
from pathlib import Path

class OptimizedLogger:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, log_dir="logs"):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.__initialized = False
            return cls._instance
            
    def __init__(self, log_dir="logs"):
        if not self.__initialized:
            self.log_dir = Path(log_dir)
            self.current_log_file = None
            self.current_month = None
            self.__initialized = True
            
            # Ensure log directory exists
            self.log_dir.mkdir(parents=True, exist_ok=True)

            # --- NEW: Run cleanup on startup ---
            # Run in a separate thread so it doesn't slow down bot startup
            threading.Thread(target=self.cleanup_old_logs, args=(60,), daemon=True).start()
    
    def cleanup_old_logs(self, days_to_keep=60):
        """
        Deletes chat_logs_*.json files older than 'days_to_keep'.
        Default is 60 days (2 months).
        """
        try:
            cutoff_time = time.time() - (days_to_keep * 86400) # Current time minus days in seconds
            
            # Iterate only through chat_logs json files
            for log_file in self.log_dir.glob("chat_logs_*.json"):
                try:
                    # Get the file's modification time
                    file_mod_time = log_file.stat().st_mtime
                    
                    if file_mod_time < cutoff_time:
                        log_file.unlink() # Delete the file
                        print(f"[Logger] Deleted old log file: {log_file.name}")
                        
                except Exception as e:
                    print(f"[Logger] Error deleting {log_file.name}: {e}")
                    
        except Exception as e:
            print(f"[Logger] Cleanup failed: {e}")

    def _get_log_file(self):
        """Determine current log file by month"""
        current_month = datetime.now().strftime("%Y-%m")
        
        if self.current_month != current_month:
            log_file = self.log_dir / f"chat_logs_{current_month}.json"
            
            # Create file if not exists
            if not log_file.exists():
                log_file.touch()
            
            self.current_log_file = log_file
            self.current_month = current_month
        
        return self.current_log_file
    
    def log_message(self, user_id, message_id, chat_id, message, direction="incoming"):
        """Log message with optimized format"""
        log_file = self._get_log_file()
        timestamp = datetime.now().isoformat()
        
        msg_content = (
            message if direction == "incoming"
            else (message[:10] + "..." if len(message) > 10 else message)
        )

        log_entry = {
            "uid": user_id,
            "mid": message_id,
            "ts": timestamp,
            "cid": str(chat_id),
            "dir": direction[:1],
            "msg": msg_content
        }
        
        with threading.Lock():
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

# Global instance
message_logger = OptimizedLogger()