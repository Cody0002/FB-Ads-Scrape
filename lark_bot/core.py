import json
import logging
from .state_managers import state_manager
from .command_handlers import command_handler
from .logger import message_logger

logger = logging.getLogger(__name__)

def handle_incoming_message(event_data):
    # Access the nested structure correctly
    message = event_data["event"]["message"]
    chat_id = message["chat_id"]
    message_id = message["message_id"]
    user_id = event_data["event"]["sender"]["sender_id"]["user_id"]
    
    # Parse the JSON content string
    content = json.loads(message["content"])
    text = content.get("text", "").strip().lower()

    logger.debug("Incoming message parsed user_id=%s chat_id=%s text=%s", user_id, chat_id, text)

    # Log incoming message
    message_logger.log_message(user_id= user_id, 
                               message_id= message_id, 
                               chat_id=chat_id, 
                               message=text, 
                               direction="incoming")

    # Store chat_id mapping only if state is None
    current_state = state_manager.get_state(user_id)
    if current_state is None:
        logger.debug("Initializing state mapping for user_id=%s", user_id)
        state_manager.set_state(user_id, None, chat_id, message_id)

    logger.debug("Current state=%s user_id=%s chat_id=%s", current_state, user_id, chat_id)

    # Handle cancel command regardless of state
    if text == "cancel":
        command_handler.handle_command(user_id, text)
        return

    # Process message based on state
    if current_state == "AWAITING_SEARCH_TERM":
        command_handler.handle_search_term(user_id, text)
    elif current_state == "IN_PROGRESS":
        command_handler.lark_api.reply_to_message(
            message_id,
            "🔄 A search is already in progress. Type 'cancel' to stop it and start a new one."
        )
    elif current_state is None:
        command_handler.handle_command(user_id, text)
