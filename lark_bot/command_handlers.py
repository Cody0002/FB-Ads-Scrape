from .state_managers import state_manager
from .lark_api import LarkAPI
from .file_processor import generate_excel_report, build_media_zip
from tools import *
import threading
import logging
import re
import urllib.parse  # Import the specific submodule

# from .state_managers import state_manager
# from .lark_api import LarkAPI
# from .file_processor import generate_excel_report
# import threading
# import re
# import urllib.parse
# from functools import lru_cache

# @lru_cache(maxsize=128)
from datetime import time as dtime
from zoneinfo import ZoneInfo

TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?:\s*(?:GMT)?([+\-]\d{1,2}))?\s*$", re.I)
DOMAIN_RE = re.compile(r"^([a-zA-Z0-9-]{2,}\.)+[a-zA-Z]{2,}$")
DEFAULT_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # GMT+7
logger = logging.getLogger(__name__)

def clean_url(url):
    """Optimized URL cleaning with caching"""
    if "[" in url:
        match = re.search(r'\[(.*?)\]', url)
        if match:
            url = match.group(1)

    parsed = urllib.parse.urlparse(url)
    return parsed.netloc if parsed.scheme else url

from datetime import datetime, timezone, timedelta

def now_str(tz_offset_hours: int | None = None) -> str:
    """
    Current time as 'YYYY-MM-DD HH:MM GMT+/-H'.
    - Default: Asia/Ho_Chi_Minh (GMT+7)
    - Or pass tz_offset_hours to use a different offset
    """
    if tz_offset_hours is None:
        dt = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        return dt.strftime("%Y-%m-%d %H:%M") + " GMT+7"
    tz = timezone(timedelta(hours=tz_offset_hours))
    dt = datetime.now(tz)
    return dt.strftime("%Y-%m-%d %H:%M") + f" GMT{tz_offset_hours:+d}"

class CommandHandler:
    def __init__(self):
        self.lark_api = LarkAPI()
        self.start_reponse = {
            "help": self.show_help_menu,
            "hi": self.show_help_menu,
            "menu": self.show_help_menu,
            "start": self.show_help_menu,
            "hello": self.show_help_menu
        }
    
    def handle_command(self, user_id, text):
        text = text.strip().lower()
        message_info = state_manager.get_message_info(user_id)
        message_id = message_info["message_id"]
        chat_id = state_manager.get_chat_id(user_id)
        
        if not chat_id:
            logger.warning("No chat_id found for user_id=%s", user_id)
            return
        
        # Handle known commands
        if handler := self.start_reponse.get(text):
            handler(chat_id)
        elif text.startswith("add_domain "):  # /add_domain foo.com
            domain = text[len("add_domain "):].strip()
            self.handle_add_domain(chat_id, message_id, domain)

        elif text == "list":
            self.handle_list_crawl(chat_id, message_id)

        elif text.startswith("add_schedule "):   # e.g. add_schedule 18:00GMT+7
            when = text[len("add_schedule "):].strip()
            self.handle_add_schedule(chat_id, message_id, when)

        elif text.startswith("remove_schedule "):  # e.g. remove_schedule 18:00GMT+7
            when = text[len("remove_schedule "):].strip()
            self.handle_remove_schedule(chat_id, message_id, when)

        elif text.startswith("remove_domain "):  # e.g. remove_domain a.com, b.com
            domains_str = text[len("remove_domain "):].strip()
            self.handle_remove_domain(chat_id, message_id, domains_str)

        
        elif text.startswith("search "):
            domain = text[7:].strip()  # More efficient slicing
            self.handle_search_term(user_id, domain)
        elif text == "search":
            self.lark_api.reply_to_message(message_id, 
                "Please provide a domain to search.\n\nExample: 'search chatbuypro.com'")
        elif text == "cancel":
            if state_manager.request_cancel(user_id):
                self.lark_api.reply_to_message(message_id, "Canceling...")
            else:
                self.lark_api.reply_to_message(message_id, "No active process to cancel.")
        else:
            self.lark_api.reply_to_message(message_id, 
                "Sorry, I didn't understand. Type 'help' for options")
    

    def handle_add_domain(self, chat_id, message_id, domains_str: str):
        # Split, normalize, de-dupe within this command
        tokens = [t.strip() for t in (domains_str or "").split(",")]
        raw_items = [t for t in tokens if t]
        seen = set()
        candidates = []
        for item in raw_items:
            d = clean_url(item).strip().lower().rstrip("/.")
            if d and d not in seen:
                seen.add(d)
                candidates.append(d)

        if not candidates:
            card = {
                "config": {"wide_screen_mode": True},
                "elements": [{
                    "tag": "div",
                    "text": {"tag": "lark_md",
                            "content": "Please provide at least one valid domain.\n\n**Example:** `/add_domain a.com, b.com`"}
                }]
            }
            self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)
            return

        added, skipped = [], []
        for domain in candidates:
            if not self.is_valid_domain(message_id, domain):
                skipped.append(domain)
                continue
            if state_manager.add_domain(chat_id, domain):
                added.append(domain)
            else:
                skipped.append(domain)  # duplicate in storage

        current_list_md = self._format_domains_md(chat_id)

        # Build body
        lines = []
        if added:
            lines.append("Added:")
            lines.extend(f"- {d}" for d in added)
            lines.append("")
        if skipped:
            lines.append("Skipped (invalid or duplicate):")
            lines.extend(f"- {d}" for d in skipped)
            lines.append("")
        lines.append("**Current domains:**")
        lines.append(current_list_md)

        # Header style
        if added and skipped:
            header_title = "Domains updated (some added, some skipped)"
            header_template = "turquoise"
        elif added:
            header_title = "Domains added successfully"
            header_template = "green"
        else:
            header_title = "No new domains added"
            header_template = "gray"

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": header_template,
                "title": {"content": header_title, "tag": "plain_text"}
            },
            "elements": [{
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n".join(lines)}
            }]
        }

        self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)


    def _parse_when(self, when_str, message_id):
        m = TIME_RE.match(when_str)
        if not m:
            self.lark_api.reply_to_message(
                message_id,
                text="Invalid time. Use `HH:MM` (e.g: 18:58)."
            )
            return None
        hh, mm, tzoff = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (0 <= hh < 24 and 0 <= mm < 60):
            self.lark_api.reply_to_message(message_id, text="Hour/Minute out of range.")
            return None
        tz_offset_hours = int(tzoff) if tzoff is not None else 7
        if tz_offset_hours < -12 or tz_offset_hours > 14:
            self.lark_api.reply_to_message(message_id, text="Timezone offset out of range (-12..+14).")
            return None
        return hh, mm, tz_offset_hours
    
    def _format_domains_md(self, chat_id: str) -> str:
        domains = sorted(state_manager.get_domains(chat_id))
        if not domains:
            return "(none)"
        lines, i = [], 0
        for d in domains:
            i += 1
            lines.append(f"{i}. {d}")
        return "\n".join(lines)
        
    def _format_schedules_md(self, chat_id: str) -> str:
        """Build lark_md list of all schedules for this chat."""
        schedules = state_manager.get_schedules(chat_id)  # always a list (possibly empty)
        if not schedules:
            return "(no schedules set)"
        # sort for stable output
        schedules = sorted(
            schedules,
            key=lambda s: (int(s.get("tz_offset", 0)), int(s.get("hour", 0)), int(s.get("minute", 0)))
        )
        lines, i = [], 0
        for s in schedules:
            i += 1
            lines.append(f"{i}. {int(s['hour']):02d}:{int(s['minute']):02d}")
        # i = 0
        # lines = [
        #     f"{i+1} **{int(s['hour']):02d}:{int(s['minute']):02d} GMT{int(s['tz_offset']):+d}**"
        #     for s in schedules
        # ]
        return "\n".join(lines)

    def handle_add_schedule(self, chat_id, message_id, when_str: str):
        tokens = [t.strip() for t in (when_str or "").split(",") if t.strip()]

        added_list, skipped_list = [], []
        for tok in tokens:
            parsed = self._parse_when(tok, message_id)
            if not parsed:
                skipped_list.append(tok)
                continue
            hh, mm, tz_offset_hours = parsed
            if state_manager.add_schedule(chat_id, dtime(hour=hh, minute=mm), tz_offset_hours):
                added_list.append(f"{hh:02d}:{mm:02d} GMT{tz_offset_hours:+d}")
            else:
                skipped_list.append(f"{hh:02d}:{mm:02d} GMT{tz_offset_hours:+d}")

        current_list_md = self._format_schedules_md(chat_id)

        # Build body
        lines = []
        if added_list:
            lines.append("Added schedules:")
            lines.extend(f"- {s}" for s in added_list)
            lines.append("")
        if skipped_list:
            lines.append("Skipped (invalid or duplicate):")
            lines.extend(f"- {s}" for s in skipped_list)
            lines.append("")
        lines.append("**Current schedules:**")
        lines.append(current_list_md)

        # Header style
        if added_list and skipped_list:
            header_title = "Schedules updated (some added, some skipped)"
            header_template = "turquoise"
        elif added_list:
            header_title = "Schedules added successfully"
            header_template = "green"
        else:
            header_title = "No new schedules added"
            header_template = "gray"

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": header_template,
                "title": {"content": header_title, "tag": "plain_text"}
            },
            "elements": [{
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n".join(lines)}
            }]
        }

        self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)



    def handle_remove_schedule(self, chat_id, message_id, when_str):
        token = (when_str or "").strip().lower()
        if token in {"a", "all", "*"}:
            # remove ALL schedules for this chat
            scheds = state_manager.get_schedules(chat_id)
            if not scheds:
                status = "No schedules to remove."
            else:
                removed = 0
                for s in list(scheds):
                    if state_manager.remove_schedule(
                        chat_id,
                        int(s.get("hour", 0)),
                        int(s.get("minute", 0)),
                        int(s.get("tz_offset", 0))
                    ):
                        removed += 1
                        
                result = ",".join([f"{s['hour']:02d}:{s['minute']:02d}" for s in scheds]) 
                status = f"Removed **all {removed}** schedules:{result}"
                
            current_list_md = self._format_schedules_md(chat_id)
            card = {
                "config": {"wide_screen_mode": True},
                "elements": [{
                    "tag": "div",
                    "text": {"tag": "lark_md",
                            "content": f"{status}\n\n**Current schedules (GMT+7):**\n{current_list_md}"}
                }]
            }
            self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)
            return
    
        parsed = self._parse_when(when_str, message_id)
        if not parsed:
            return
        hh, mm, tz_offset_hours = parsed

        ok = state_manager.remove_schedule(chat_id, hh, mm, tz_offset_hours)
        status = (f"Removed schedule **{hh:02d}:{mm:02d} GMT{tz_offset_hours:+d}**."
                if ok else "Schedule not found.")

        current_list_md = self._format_schedules_md(chat_id)
        card = {
            "config": {"wide_screen_mode": True},
            "elements": [{
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"{status}\n\n"
                        f"**Current schedules:**\n{current_list_md}"
                    )
                }
            }]
        }
        self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)



    def handle_remove_domain(self, chat_id, message_id, domains_str: str):
        token = (domains_str or "").strip().lower()
        if token in {"a", "all", "*"}:
            domains = state_manager.get_domains(chat_id)
            if not domains:
                parts = ["No domains to remove.", "", "**Current domains:**", "(none)"]
            else:
                removed = 0
                for d in list(domains):
                    if state_manager.remove_domain(chat_id, d):
                        removed += 1
                parts = [
                    f"Removed **all {removed}** domains.", "",
                    "**Current domains:**",
                    self._format_domains_md(chat_id)
                ]
            card = {
                "config": {"wide_screen_mode": True},
                "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(parts)}}]
            }
            self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)
            return

        # Guard: require at least one token
        tokens = [t.strip() for t in (domains_str or "").split(",")]
        raw_items = [t for t in tokens if t]
        if not raw_items:
            card = {
                "config": {"wide_screen_mode": True},
                "elements": [{
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            "Please provide at least one domain to remove.\n\n"
                            "**Example:** `/remove_domain foo.com, bar.com`"
                        )
                    }
                }]
            }
            self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)
            return

        # Normalize inputs and dedupe within the command
        seen = set()
        candidates = []
        for item in raw_items:
            d = clean_url(item).strip().lower().rstrip("/.")
            if d and d not in seen:
                seen.add(d)
                candidates.append(d)

        removed, missing = [], []
        for d in candidates:
            if state_manager.remove_domain(chat_id, d):
                removed.append(d)
            else:
                missing.append(d)

        current_list_md = self._format_domains_md(chat_id)

        # Build response card
        parts = ["**Domain update**", ""]
        if removed:
            parts.append("Removed:")
            parts.extend(f"- {d}" for d in removed)
            parts.append("")
        if missing:
            parts.append("Not found:")
            parts.extend(f"- {d}" for d in missing)
            parts.append("")
        parts.append("**Current domains:**")
        parts.append(current_list_md)

        card = {
            "config": {"wide_screen_mode": True},
            "elements": [{
                "tag": "div",
                "text": {"tag": "lark_md", "content": "\n".join(parts)}
            }], 
        }
        
        self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)

    def handle_list_crawl(self, chat_id, message_id):
        # domains_text = ("\n- " + "\n- ".join(sorted(domains))) if domains else "\n(no domains added)"
        domains_text = self._format_domains_md(chat_id)
        schedules_text = self._format_schedules_md(chat_id)

        # if schedules:
        #     sched_lines = []
        #     for s in sorted(schedules, key=lambda x: (int(x.get("tz_offset", 0)), int(x.get("hour", 0)), int(x.get("minute", 0)))):
        #         sched_lines.append(f"- {int(s['hour']):02d}:{int(s['minute']):02d} GMT{int(s['tz_offset']):+d}")
        #     schedules_text = "\n".join(sched_lines)
        # else:
        #     schedules_text = "(no schedules set)"

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "indigo",
                    "title": {
                        "content": "Daily Crawl Configuration",
                        "tag": "plain_text"
                    }
            },
            "elements": [{
                "tag": "div",
                "text": {"tag": "lark_md",
                        "content": (f"**Domains:**\n{domains_text}\n\n"
                                    f"**Daily Schedules (GMT+7):**\n{schedules_text}")}}]
        }
        self.lark_api.reply_to_message(message_id=message_id, card=card, reply_in_thread=True)

    def handle_search_term(self, user_id, search_term):
        message_info = state_manager.get_message_info(user_id)
        message_id = message_info["message_id"]
        chat_id = state_manager.get_chat_id(user_id)
        
        if not chat_id:
            logger.warning("No chat_id found for user_id=%s", user_id)
            return
        
        # Check if search already in progress
        if state_manager.get_state(user_id) == "IN_PROGRESS":
            self.lark_api.reply_to_message(
                message_id,
                "A search is already in progress. Type 'cancel' to stop it and start a new one."
            )
            return

        search_term = clean_url(search_term)
        logger.debug("Cleaned search term: %s", search_term)

        if not self.is_valid_domain(message_id, search_term):
            return

        logger.info("Starting search user_id=%s term=%s", user_id, search_term)
        state_manager.set_state(user_id, "IN_PROGRESS", chat_id)

        # Create processing card
        card = domain_processing_card(search_word=search_term, progress_percent=0)
        reply_message_id = self.lark_api.reply_to_message(
            message_id=message_id,
            card=card,
            reply_in_thread=True
        )
        
        # Start background thread
        threading.Thread(
            target=self.process_search_async,
            args=(user_id, search_term, reply_message_id),
            daemon=True
        ).start()
    
    def process_search_async(self, user_id, search_term, bot_reply_id):
        message_info = state_manager.get_message_info(user_id)
        message_id = message_info["message_id"]
        chat_id = state_manager.get_chat_id(user_id)
        
        if not chat_id:
            logger.warning("No chat_id found for user_id=%s", user_id)
            return
        
        try:
            crawler = FacebookAdsCrawler(search_term, chat_id, bot_reply_id)
            state_manager.register_process(user_id, crawler, chat_id)
            
            # Check cancellation before starting
            if state_manager.should_cancel(user_id):
                self.lark_api.reply_to_message(message_id, "Process cancelled before starting!")
                return
                    
            file_buffer, filename, df = generate_excel_report(crawler)
            encoded_term = urllib.parse.quote(search_term)
            link = f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=ALL&is_targeted_country=false&media_type=all&q={encoded_term}&search_type=keyword_unordered"
            
            # Handle results if not cancelled
            if not state_manager.should_cancel(user_id):
                if df.empty:
                    card = search_no_result_card(search_word=search_term, href=link)
                    self.lark_api.update_card_message(bot_reply_id, card=card)
                else:
                    card = search_complete_card(
                        search_word=search_term,
                        num_results=df.shape[0],
                        href=link
                    )
                    self.lark_api.update_card_message(message_id=bot_reply_id, card=card)
                    self.lark_api.send_file(message_id, file_buffer, filename, content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

                    base = search_term.replace(".", "-").replace(" ", "_") or "results"

                    # After ensuring crawler.df is not empty
                    crawler.df = crawler.df.reset_index(drop=True)
                    if "No" not in crawler.df.columns:
                        crawler.df.insert(0, "No", range(1, len(crawler.df) + 1))

                    # 1) ad_url packs
                    for zip_name, zip_buf in build_media_zip(
                        df=crawler.df,
                        col="ad_url",
                        zip_basename_prefix=base,
                        max_workers=2,
                        max_zip_bytes= 28 * 1024 * 1024,
                    ):
                        self.lark_api.send_file(
                            message_id=message_id,
                            file_buffer=zip_buf,
                            filename=zip_name,
                            content_type="application/zip",
                        )

                    # 2) thumbnail_url packs
                    for zip_name, zip_buf in build_media_zip(
                        df=crawler.df,
                        col="thumbnail_url",
                        zip_basename_prefix=base,
                        max_workers=2,
                        max_zip_bytes= 28 * 1024 * 1024,
                    ):
                        self.lark_api.send_file(
                            message_id=message_id,
                            file_buffer=zip_buf,
                            filename=zip_name,
                            content_type="application/zip",
                        )

            else:
                self.lark_api.reply_to_message(message_id, "Process cancelled successfully!")
        except Exception as e:
            if not state_manager.should_cancel(user_id):
                self.lark_api.reply_to_message(message_id, f"Error processing request: {str(e)}")
            else:
                self.lark_api.reply_to_message(message_id, "Process cancelled due to error!")
        finally:
            # Cleanup resources
            if 'file_buffer' in locals() and file_buffer:
                try:
                    file_buffer.close()
                except:
                    pass
            state_manager.clear_state(user_id)

    def show_help_menu(self, chat_id):
        self.lark_api.send_interactive_card(chat_id)

    def is_valid_domain(self, message_id, domain):
        logger.debug("Validating domain=%s", domain)
        
        # Quick checks first for efficiency
        if '@' in domain or len(domain) < 4:
            self.lark_api.reply_to_message(message_id, 
                "Invalid domain format. Please provide a valid domain [e.g., chatbuypro.com]:")
            return False

        if not DOMAIN_RE.fullmatch(domain):
            self.lark_api.reply_to_message(message_id, 
                "Invalid domain or domain is too short.\nPlease provide a valid domain [e.g., chatbuypro.com]:")
            return False

        return True

    def run_scheduled_crawl(self, chat_id: str, hour: int | None = None, minute: int | None = None, tz_offset: int = 7):
        """
        Run all domains for this chat sequentially. When called by the scheduler,
        we also announce a single header with the schedule time that just fired,
        then visibly post '/search domain' lines for each domain before running them.
        """
        import time as _t

        domains = state_manager.get_domains(chat_id)
        if not domains:
            return

        # 1) Header: "Start searching for schedule at HH:MM GMT+/-X"
        if hour is not None and minute is not None:
            stamp = f"{hour:02d}:{minute:02d} GMT{tz_offset:+d}"
        else:
            # fall back to your helper (defaults to GMT+7)
            stamp = now_str()
        self.lark_api.send_text(chat_id, f"Start searching for schedule at {stamp}")

        # 2) For each domain: post "/search domain" then run it in that thread
        for domain in sorted(domains):
            # show the command visibly
            search_cmd_text = f"/search {domain}"
            root_id = self.lark_api.send_text(chat_id, search_cmd_text)
            if not root_id:
                # if we failed to create the message to anchor the thread, skip cleanly
                continue

            # 2) Create a synthetic user id so state/threads are isolated per domain
            synthetic_user = f"schedule:{chat_id}:{domain}"
            # Map state so handlers know which chat/message to reply on
            state_manager.set_state(synthetic_user, None, chat_id, root_id, root_id)

            # 3) Reuse the same flow as interactive command
            #    (this creates the processing card and spawns the worker thread)
            self.handle_search_term(synthetic_user, domain)

            _t.sleep(60)  # tiny gap for safety



command_handler = CommandHandler()

