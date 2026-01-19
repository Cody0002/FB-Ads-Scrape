from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium_stealth import stealth

from lark_bot import LarkAPI
from lark_bot.state_managers import state_manager
from .interactive_card_library import *

import logging
import re
import pandas as pd
import time
import threading
import queue
import os

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CrawlerQueue:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance.queue = queue.Queue()
                cls._instance.active = False
                cls._instance.current_chat_id = None
                cls._instance.queue_list = [] 
        return cls._instance
    
    def add_request(self, crawler):
        with self._lock:
            self.queue.put(crawler)
            self.queue_list.append(crawler.chat_id)
            
            position = len(self.queue_list)
            # Only send queue update if there is already an active process
            if self.active:
                try:
                    crawler.lark_api.update_card_message(crawler.message_id, 
                                            card=queue_card(search_word=crawler.keyword,
                                            position=position))
                except:
                    pass
        
        if not self.active:
            self._process_next()

    def _process_next(self):
        with self._lock:
            if not self.queue.empty():
                self.active = True
                next_crawler = self.queue.get()
                self.current_chat_id = next_crawler.chat_id
                
                if next_crawler.chat_id in self.queue_list:
                    self.queue_list.remove(next_crawler.chat_id)
                
                self._update_queue_positions()
                
                threading.Thread(
                    target=self._run_crawler, 
                    args=(next_crawler,),
                    daemon=True
                ).start()
            else:
                self.active = False
                self.current_chat_id = None
    
    def _update_queue_positions(self):
        # Notify others in queue about their new position
        for i, chat_id in enumerate(self.queue_list, 1):
            temp_queue = list(self.queue.queue)
            for crawler in temp_queue:
                if crawler.chat_id == chat_id:
                    try:
                        crawler.lark_api.update_card_message(crawler.message_id, 
                            card=queue_card(search_word=crawler.keyword, position=i))
                    except:
                        pass
                    break
    
    def _run_crawler(self, crawler):
        try:
            crawler.crawl()
        except Exception as e:
            logger.error(f"Queue execution error: {e}")
            if not crawler.should_stop():
                try:
                    crawler.lark_api.reply_to_message(
                        crawler.message_id, 
                        f"❌ Error during processing: {str(e)}"
                    )
                except:
                    pass
        finally:
            with self._lock:
                self.active = False
                self.current_chat_id = None
            self._process_next()
    
    def get_queue_position(self, chat_id):
        with self._lock:
            if self.current_chat_id == chat_id:
                return 0
            try:
                return self.queue_list.index(chat_id) + 1
            except ValueError:
                return None

class FacebookAdsCrawler:
    _LIBRARY_ID_PATTERN = re.compile(r'Library ID:\s*(\d+)')
    _DATE_PATTERN = re.compile(r'\b\d{1,2}\s\w{3}\s\d{4}\b')

    def __init__(self, keyword, chat_id, message_id=False):
        self.keyword = keyword
        self.ad_card_class = "x1plvlek xryxfnj x1gzqxud x178xt8z x1lun4ml xso031l xpilrb4 xb9moi8 xe76qn7 x21b0me x142aazg x1i5p2am x1whfx0g xr2y4jy x1ihp6rs x1kmqopl x13fuv20 x18b5jzi x1q0q8m5 x1t7ytsu x9f619"
        self.driver = None
        self.ads_data = []
        self.lark_api = LarkAPI()
        self.chat_id = chat_id
        self._stop_event = threading.Event()
        self.queue_manager = CrawlerQueue()
        self.message_id = message_id
        self.df = pd.DataFrame()

    def __del__(self):
        try:
            if self.driver:
                self.driver.quit()
        except:
            pass

    def should_stop(self):
        return self._stop_event.is_set() or state_manager.should_cancel(self.chat_id)
    
    def initialize_driver(self):
        if self.should_stop(): return False

        options = Options()
        # Optimization flags for mini server
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-infobars")
        options.add_argument("--mute-audio")
        
        # Memory savers
        options.add_argument("--renderer-process-limit=2")
        options.add_argument("--window-size=1024,768")

        service = Service()
        try:
            self.driver = webdriver.Chrome(service=service, options=options)
            stealth(self.driver,
                    languages=["en-US", "en"],
                    vendor="Google Inc.",
                    platform="Win32",
                    webgl_vendor="Intel Inc.",
                    renderer="Intel Iris OpenGL Engine",
                    fix_hairline=True)
            return True
        except Exception as e:
            logger.error(f"Driver initialization failed: {e}")
            return False

    def start(self):
        position = self.queue_manager.get_queue_position(self.chat_id)
        if position is not None and position != 0:
            self.lark_api.reply_to_message(
                self.message_id,
                f"⏳ Your request is in waiting list (No #{position})"
            )
            return
        self.queue_manager.add_request(self)

    def fetch_ads_page(self):
        if self.should_stop(): return False
        url = (f"https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=ALL&"
               f"is_targeted_country=false&media_type=all&q={self.keyword}&search_type=keyword_unordered")
        try:
            self.driver.get(url)
            css_selector = "." + self.ad_card_class.replace(" ", ".")
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, css_selector)))
            return True
        except Exception:
            return False

    def get_dim_keyword(self) -> pd.DataFrame:
        csv_path = f"ref_data//dim_keyword_{self.keyword}.csv"
        if os.path.exists(csv_path):
            try:
                return pd.read_csv(csv_path, dtype=str)
            except:
                pass

        try:
            dim_keyword = self.scrape_advertiser_list_from_filters()
            os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            dim_keyword.to_csv(csv_path, index=False)
            return dim_keyword
        except Exception as e:
            logger.error(f"Failed to get dim keyword: {e}")
            return pd.DataFrame(columns=["id", "name", "keyword", "name_clean"])
    
    def scrape_advertiser_list_from_filters(self) -> pd.DataFrame:
        wait = WebDriverWait(self.driver, 5)
        try:
            # Open filter
            filter_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@role='button' and contains(., 'Filters')]")))
            filter_button.click()
            time.sleep(1)

            # Open advertisers
            advertiser_dropdown = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@role='combobox' and .//text()='All advertisers']")))
            advertiser_dropdown.click()
            time.sleep(1)

            scrollable_container = wait.until(EC.presence_of_element_located((By.XPATH, "//div[@role='listbox']")))
            option_locator = (By.XPATH, ".//div[@role='option']")

            seen = set()
            rows = []
            
            # Limit scrolling for safety
            max_scrolls = 20
            scroll_count = 0
            last_count = -1

            while scroll_count < max_scrolls:
                if self.should_stop(): break
                
                options = scrollable_container.find_elements(*option_locator)
                current_batch = []
                for opt in options:
                    opt_id = opt.get_attribute("id")
                    if opt_id:
                        current_batch.append((opt_id, opt))

                for opt_id, opt in current_batch:
                    if opt_id not in seen:
                        opt_name = (opt.get_attribute("textContent") or "").strip()
                        seen.add(opt_id)
                        rows.append([opt_id, opt_name])

                if len(options) == last_count:
                    break
                last_count = len(options)

                try:
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", options[-1])
                    time.sleep(0.8)
                except:
                    break
                scroll_count += 1

            df = pd.DataFrame(rows, columns=["id", "name"])
            df["keyword"] = self.keyword
            df.drop_duplicates(inplace=True)
            return df
        except Exception as e:
            logger.error(f"Error scraping filters: {e}")
            return pd.DataFrame(columns=["id", "name"])

    def fetch_ads_page_by_id(self, page_name: str) -> bool:
        """
        FIXED: Removed the progress update here to prevent progress bar jumping backward.
        """
        if self.should_stop(): return False
        search_word = f"{self.keyword} {page_name}"
        url = (
            "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=ALL&"
            f"is_targeted_country=false&media_type=all&q={search_word}&search_type=keyword_unordered"
        )
        try:
            self.driver.get(url)
            css_selector = "." + self.ad_card_class.replace(" ", ".")
            WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, css_selector)))
            
            # REMOVED: self.lark_api.update_card_message(...) 
            # This was the cause of the glitch
            
            return True
        except TimeoutException:
            return False
        
    def scrape_current_page_ads(self):
        if self.should_stop(): return
        css_selector = "." + self.ad_card_class.replace(" ", ".")
        try:
            elements = self.driver.find_elements(By.CSS_SELECTOR, css_selector)
            for ad in elements:
                if self.should_stop(): break
                ad_data = self.process_ad_element(ad)
                if ad_data:
                    self.ads_data.append(ad_data)
        except Exception as e:
            logger.error(f"Error scraping page ads: {e}")

    def extract_library_id(self, text):
        match = self._LIBRARY_ID_PATTERN.search(text)
        return match.group(1) if match else None
        
    def extract_date(self, text):
        match = self._DATE_PATTERN.search(text)
        return match.group() if match else None
    
    def process_ad_element(self, ad_element):
        # Executes minified JS inside the browser to scrape data from the specific Ad Card
        if self.should_stop(): return None
        try:
            # Minified JS for speed
            ad_data = self.driver.execute_script("""
                const el=arguments[0];const txt=el.innerText;
                let c=null,a=null,i=null,v=null,t=null,d=null,p=null,pt=null,ht=null;
                const imgs=el.querySelectorAll('img');
                for(const img of imgs){
                    if(img.alt&&!c){c=img.alt.trim();a=img.src}
                    else if(!i){i=img.src;t=img.src}
                }
                const vid=el.querySelector('video');
                if(vid){v=vid.src;t=vid.poster||t}
                const as=el.querySelectorAll('a');
                for(const lnk of as){
                    const u=lnk.href;
                    if(u&&u.includes('l.facebook.com')){
                        if(u.includes('pixelId')){p=u.split('pixelId')[1].split('&')[0].replace('%3D','');d=u}
                        else{d=u;break}
                    }
                }
                const e1=el.querySelector("._7jyr._a25-");if(e1)pt=e1.innerText;
                const e2=el.querySelector(".x6s0dn4.x2izyaf.x78zum5.x1qughib.x15mokao.x1ga7v0g.xde0f50.x15x8krk.xexx8yu.xf159sx.xwib8y2.xmzvs34");if(e2)ht=e2.innerText;
                return {txt,c,a,i,v,t,d,p,pt,ht};
            """, ad_element)

            if not ad_data or "Library ID" not in ad_data['txt']: return None

            return {
                "text_snippet": ad_data['txt'][:100].replace("\n", " ") + "...",
                "library_id": self.extract_library_id(ad_data['txt']),
                "ad_start_date": self.extract_date(ad_data['txt']),
                "company": ad_data['c'],
                "avatar_url": ad_data['a'],
                "image_url": ad_data['i'],
                "video_url": ad_data['v'],
                "thumbnail_url": ad_data['t'],
                "destination_url": ad_data['d'],
                "pixel_id": ad_data['p'],
                "primary_text": ad_data['pt'],
                "headline_text": ad_data['ht']
            }
        except:
            return None

    def crawl(self):
        logger.info(f"[{self.chat_id}] Start crawl: {self.keyword}")
        try:
            # Phase 1: Initialize (0-10%)
            if not self.initialize_driver(): return
            if not self.fetch_ads_page():
                raise RuntimeError("Failed load initial page")

            # Phase 2: Get Dimensions (10%)
            dim_keyword = self.get_dim_keyword()
            if dim_keyword is None or dim_keyword.empty:
                raise RuntimeError("Empty advertiser list")

            dim_keyword["name_clean"] = dim_keyword["name"].str.split(" ").str[0].str.strip()
            list_name = dim_keyword["name_clean"].dropna().astype(str).unique().tolist()
            total = len(list_name)

            # Phase 3: Loop Advertisers (10% -> 90%)
            for idx, page_name in enumerate(list_name, start=1):
                if self.should_stop(): break

                # SMOOTH PROGRESS: Map iteration directly to 10-90% range
                pct = int(10 + 80 * idx / max(1, total))
                
                # Update Lark Card periodically (every 3 items or at the end)
                if idx % 3 == 0 or idx == total:
                    try:
                        self.lark_api.update_card_message(
                            self.message_id,
                            card=domain_processing_card(search_word=self.keyword, 
                                                      progress_percent=pct)
                        )
                    except: pass

                page = page_name.split(" ")[0]
                if "All" in page: page = ""

                if self.fetch_ads_page_by_id(page):
                    self.scrape_current_page_ads()
                    
                    if len(self.ads_data) > 500:
                        logger.warning(f"[{self.chat_id}] Reached ad limit (500) for safety.")
                        break

            self.data_to_dataframe()

        except Exception as e:
            logger.exception(f"[{self.chat_id}] Crawl error: {e}")
        finally:
            if self.driver:
                try: self.driver.quit()
                except: pass
                self.driver = None

    def data_to_dataframe(self):  
        if self.should_stop():
            self.df = pd.DataFrame()
            return
            
        # Phase 4: Processing (Set to 95%)
        try:
             self.lark_api.update_card_message(
                self.message_id,
                card=domain_processing_card(search_word=self.keyword, 
                                          progress_percent=95)
            )
        except: pass

        df = pd.DataFrame(self.ads_data)
        if df.empty:
            self.df = df
            return
        
        try:
            filter_conditions = (df["image_url"].notnull() & df["video_url"].notnull()) | (~df["image_url"].notnull() & ~df["video_url"].notnull())
            df_cleaned = df[~filter_conditions].reset_index(drop=True)
            
            df_cleaned["ad_url"] = df_cleaned["image_url"].fillna(df_cleaned["video_url"])
            df_cleaned["ad_type"] = df_cleaned["image_url"].notnull().replace({True: "image", False: "video"})
            if "pixel_id" in df_cleaned.columns:
                df_cleaned["pixel_id"] = df_cleaned["pixel_id"].astype(str).str.replace("%3D", "")

            cols = ["library_id", "ad_start_date", "company", "pixel_id", "destination_url", 
                    "ad_type", "ad_url", "thumbnail_url", "primary_text", "headline_text"]
            
            existing_cols = [c for c in cols if c in df_cleaned.columns]
            df_cleaned = df_cleaned[existing_cols]
            df_cleaned.drop_duplicates(subset=["library_id", "company"], inplace=True)
            self.df = df_cleaned
        except Exception as e:
            logger.error(f"DataFrame conversion error: {e}")
            self.df = df