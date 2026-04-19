# FB Ads Scraper Bot Flow Playbook

## Purpose
This file is a working map of the bot so future "improve/fix/change" requests can be done quickly and safely.

## High-Level Architecture
1. `main_app.py`: Flask webhook entrypoint + scheduler loop.
2. `lark_bot/core.py`: Parses inbound Lark message and routes by state.
3. `lark_bot/command_handlers.py`: Command logic, async search orchestration, scheduled crawl orchestration.
4. `tools/fb_scrape_bot.py`: Selenium crawler + in-memory queue manager.
5. `lark_bot/file_processor.py`: Excel generation + media ZIP building.
6. `lark_bot/lark_api.py`: Lark API wrapper (send text, cards, files, updates).
7. `lark_bot/state_managers.py`: In-memory state + persisted domains/schedules JSON.

## End-to-End Request Flow
1. Lark sends event to `POST /webhook` in `main_app.py`.
2. Bot verifies token (`verify_token`).
3. For message events (`im.message.receive_v1`), bot starts a background thread: `process_message_async`.
4. `process_message_async` only forwards messages starting with `/`:
   - strips `/`
   - rewrites message content
   - calls `handle_incoming_message(...)`.
5. `handle_incoming_message` in `lark_bot/core.py`:
   - parses text to lowercase
   - logs incoming message
   - maps `user_id -> chat_id/message_id`
   - routes by user state:
     - `IN_PROGRESS`: reject new search
     - `None`: command parsing
     - `cancel`: immediate cancel path.
6. `CommandHandler.handle_command` dispatches:
   - help/menu/start
   - `search`
   - `cancel`
   - domain and schedule CRUD (`add_domain`, `remove_domain`, `add_schedule`, `remove_schedule`, `list`).
7. `handle_search_term`:
   - validates domain
   - sets state `IN_PROGRESS`
   - posts processing card
   - starts thread `process_search_async`.
8. `process_search_async`:
   - creates `FacebookAdsCrawler`
   - registers process in state manager
   - runs `generate_excel_report(crawler)`
   - updates card result
   - uploads Excel and ZIP media files
   - clears state in `finally`.

## Crawler and Report Flow
1. `FacebookAdsCrawler.start()` enqueues crawler into singleton `CrawlerQueue`.
2. `CrawlerQueue` runs one crawler at a time; queued jobs get queue cards.
3. `FacebookAdsCrawler.crawl()`:
   - starts headless Chrome
   - opens FB Ads Library search URL
   - loads advertiser dimension list (cache in `ref_data/dim_keyword_<keyword>.csv`)
   - iterates advertisers and scrapes ad cards
   - updates progress card (10% -> 90%)
   - converts raw rows to cleaned DataFrame (`data_to_dataframe`).
4. `generate_excel_report` waits until queue item is complete, then:
   - exports DataFrame to Excel with images
   - returns `(BytesIO, filename, df)`.
5. If results exist, bot also builds and sends ZIP packs from:
   - `ad_url`
   - `thumbnail_url`.

## Scheduler Flow
1. `main_app.py` starts `scheduler_thread` at module load.
2. `scheduler_loop` checks every 10 seconds.
3. Reads `state_manager.chat_schedules`.
4. Computes local time by `tz_offset`.
5. Debounces each schedule by `last_run_key`.
6. Calls `command_handler.run_scheduled_crawl(chat_id, hour, minute, tz)`.
7. Scheduled crawl posts visible `/search <domain>` messages and reuses normal search pipeline.

## Persistent Data and Logs
1. `logs/domains.json`: chat -> domains list.
2. `logs/schedules.json`: chat -> schedule objects.
3. `logs/chat_logs_YYYY-MM.json`: compact message logs.
4. `logs/bot.log`: rotating app log from `main_app.py`.
5. `ref_data/dim_keyword_<keyword>.csv`: advertiser cache.

## Command Surface (Current)
1. `/help`, `/hi`, `/menu`, `/start`, `/hello`
2. `/search <domain>`
3. `/cancel`
4. `/add_domain a.com, b.com`
5. `/remove_domain a.com` or `/remove_domain all`
6. `/add_schedule HH:MM[, HH:MM]` (default GMT+7 if not provided)
7. `/remove_schedule HH:MM` or `/remove_schedule all`
8. `/list`

## File Ownership Guide (Where to Edit)
1. Webhook behavior and scheduler timing:
   - `main_app.py`
2. Message parsing/state routing:
   - `lark_bot/core.py`
3. Command syntax/business rules:
   - `lark_bot/command_handlers.py`
4. Lark message/card/file APIs:
   - `lark_bot/lark_api.py`
5. State persistence and cancellation bookkeeping:
   - `lark_bot/state_managers.py`
6. Scraping logic/selectors/queue:
   - `tools/fb_scrape_bot.py`
7. Excel layout/image handling/ZIP chunking:
   - `lark_bot/file_processor.py`
8. Card UI copy/layout:
   - `tools/interactive_card_library.py`

## Known Hotspots to Check First
1. `handle_search_term` appears duplicated in `lark_bot/command_handlers.py` (same method defined twice).
2. Cancel path calls `process.force_stop()` in `state_managers.py`, but crawler class currently has no `force_stop` method.
3. Crawler cancellation check uses `state_manager.should_cancel(self.chat_id)` while cancel events are keyed by `user_id`.
4. `process_message_async` currently only handles messages starting with `/`; p2p non-command handling is commented out.
5. Several files contain duplicated imports/comments and mixed debug `print` statements; cleanups should keep behavior unchanged.

## Safe Workflow For Any Future Change
1. Confirm target flow:
   - manual command flow, scheduler flow, or crawler/output flow.
2. Locate exact function first (using `rg -n "<function_or_command>"`).
3. Patch smallest owning module first (avoid cross-file edits unless needed).
4. Preserve state lifecycle:
   - set state -> process -> clear state in `finally`.
5. Preserve messaging contract:
   - initial processing card
   - progress/queue updates
   - completion or error message.
6. For crawler/report edits:
   - verify cancel behavior
   - verify queue behavior
   - verify empty-result path vs non-empty path.
7. Recheck persisted JSON compatibility:
   - keep schedule/domain schema backward compatible.
8. Smoke-test critical commands:
   - `/help`
   - `/search <domain>`
   - `/cancel`
   - `/add_domain` + `/list`
   - `/add_schedule` + `/list`.

## Quick Debug Checklist
1. Webhook not receiving events:
   - check `/health`
   - check token validation and Lark event type.
2. Bot not replying:
   - check Lark token refresh (`lark_api.py`)
   - inspect `logs/bot.log`.
3. Search stuck:
   - inspect queue state in `CrawlerQueue`
   - inspect Selenium startup/load failures.
4. No files delivered:
   - verify `df.empty` path vs non-empty path
   - verify Lark file upload response.
5. Schedule not firing:
   - inspect `logs/schedules.json`
   - verify `tz_offset` and debounce key.

## Suggested Future Improvements (Priority Order)
1. Fix cancel architecture (`force_stop` + consistent cancel key).
2. Remove duplicate `handle_search_term` definition.
3. Add minimal automated tests for:
   - command parsing
   - schedule parsing
   - state transitions.
4. Replace debug `print` with structured logging.
5. Add a single source of truth for command help text to prevent drift.

