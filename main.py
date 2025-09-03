import telebot
import json
import os
import time
import traceback
import logging
import queue
import threading
from datetime import timedelta, datetime

TOKEN = '7342961553:AAFS1Md0ggLJcOsDrgjcrdiapP69x6wEV-4'
CHANNEL_ID = -1002563535507
bot = telebot.TeleBot(TOKEN)

# Setup logging to file
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("bot.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Faster processing settings
SEND_DELAY = 0.5  # Reduced delay for faster processing
MAX_RETRIES = 3
MAX_QUEUE_SIZE = 100  # Maximum queue size to prevent memory issues

# Queue system for processing files
file_queue = queue.Queue()
processing_active = False
queue_processor_thread = None

# caption data store ke liye
if not os.path.exists("captions.json"):
    with open("captions.json", "w") as f:
        json.dump({}, f)

# Queue status tracking
queue_status = {
    "total_processed": 0,
    "failed_attempts": 0,
    "last_processed": None,
    "queue_size": 0,
    "processing_speed": 0
}

def get_caption(user_id):
    with open("captions.json", "r") as f:
        data = json.load(f)
    return data.get(str(user_id), None)

def set_caption(user_id, caption):
    with open("captions.json", "r") as f:
        data = json.load(f)
    data[str(user_id)] = caption
    with open("captions.json", "w") as f:
        json.dump(data, f)

def clear_caption(user_id):
    with open("captions.json", "r") as f:
        data = json.load(f)
    data.pop(str(user_id), None)
    with open("captions.json", "w") as f:
        json.dump(data, f)

def format_size(size):
    """Convert file size to human readable format"""
    if size is None:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} TB"

def send_with_retry(chat_id, media_type, file_id, caption, parse_mode):
    """Send media with retry logic for rate limiting"""
    for attempt in range(MAX_RETRIES):
        try:
            if media_type == 'photo':
                return bot.send_photo(chat_id, file_id, caption=caption, parse_mode=parse_mode)
            elif media_type == 'video':
                return bot.send_video(chat_id, file_id, caption=caption, parse_mode=parse_mode)
            elif media_type == 'document':
                return bot.send_document(chat_id, file_id, caption=caption, parse_mode=parse_mode)
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Attempt {attempt + 1} failed: {error_msg}")
            
            if "retry after" in error_msg:
                # Extract wait time from error message
                try:
                    wait_time = int(error_msg.split("retry after ")[1])
                    logger.info(f"Rate limited. Waiting {wait_time} seconds...")
                    time.sleep(wait_time + 0.5)  # Reduced buffer
                except:
                    logger.warning("Rate limited. Waiting 15 seconds...")
                    time.sleep(15)
            elif "timed out" in error_msg.lower():
                logger.warning("Timeout error, waiting 2 seconds...")
                time.sleep(2)
            else:
                wait_time = attempt + 1
                logger.warning(f"Waiting {wait_time} seconds before retry...")
                time.sleep(wait_time)
    
    # If all retries failed
    raise Exception(f"Failed to send after {MAX_RETRIES} attempts")

def process_queue():
    """Process files from the queue one by one - FAST VERSION"""
    global processing_active, queue_status
    
    processed_count = 0
    start_time = time.time()
    
    while processing_active or not file_queue.empty():
        try:
            if file_queue.empty():
                time.sleep(0.1)  # Reduced sleep time
                continue
                
            # Get file data from queue
            file_data = file_queue.get()
            user_id = file_data['user_id']
            message = file_data['message']
            caption = get_caption(user_id)
            
            if not caption:
                try:
                    bot.send_message(user_id, "❗Set caption first using /setcaption")
                except:
                    pass
                file_queue.task_done()
                continue
            
            try:
                # Get file details quickly
                file_name = ""
                file_size = 0
                duration = ""
                resolution = ""
                media_type = ""
                file_id = ""
                
                if message.photo:
                    file_size = message.photo[-1].file_size
                    file_name = f"photo_{message.photo[-1].file_id}.jpg"
                    media_type = "photo"
                    file_id = message.photo[-1].file_id
                elif message.video:
                    file_size = message.video.file_size
                    file_name = message.video.file_name if message.video.file_name else f"video_{message.video.file_id}.mp4"
                    duration = str(timedelta(seconds=message.video.duration))
                    resolution = f"{message.video.width}x{message.video.height}"
                    media_type = "video"
                    file_id = message.video.file_id
                elif message.document:
                    file_size = message.document.file_size
                    file_name = message.document.file_name if message.document.file_name else f"document_{message.document.file_id}"
                    media_type = "document"
                    file_id = message.document.file_id

                # Fast caption formatting
                full_caption = (
                    "━━━━━━━━◆━━━━━━━━\n"
                    "📌 <b>FILE DETAILS</b>\n"
                    f"📝 <i>Name:</i> <code>{file_name}</code>\n"
                    f"📦 <i>Size:</i> <code>{format_size(file_size)}</code>\n"
                    f"⏱ <i>Duration:</i> <code>{duration if duration else 'N/A'}</code>\n"
                    f"🖥 <i>Quality:</i> <code>{resolution if resolution else 'N/A'}</code>\n"
                    "━━━━━━━━◆━━━━━━━━\n\n"
                    f"✨ <b><i>{caption}</i></b> ✨\n"
                    "━━━━━━━━◆━━━━━━━━"
                )

                # Minimal delay
                time.sleep(SEND_DELAY)
                
                # Send with retry logic
                send_with_retry(CHANNEL_ID, media_type, file_id, full_caption, 'HTML')
                
                # Update status
                processed_count += 1
                queue_status["total_processed"] += 1
                queue_status["last_processed"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                queue_status["queue_size"] = file_queue.qsize()
                
                # Calculate processing speed
                if processed_count > 0:
                    elapsed_time = time.time() - start_time
                    queue_status["processing_speed"] = processed_count / elapsed_time
                
                # Send success message (non-blocking)
                try:
                    bot.send_message(user_id, "✅ Media forwarded to channel with details!")
                except:
                    pass
                
                logger.info(f"Successfully processed file for user {user_id}")
                
            except Exception as e:
                error_msg = f"❌ Error processing media: {str(e)}"
                if "Failed to send after" in str(e):
                    error_msg = "❌ Failed to send media after multiple attempts due to Telegram restrictions. Please try again later."
                
                try:
                    bot.send_message(user_id, error_msg)
                except:
                    pass
                
                logger.error(f"Error processing media for user {user_id}: {traceback.format_exc()}")
                queue_status["failed_attempts"] += 1
            
            # IMMEDIATELY mark task as done and remove from queue
            file_queue.task_done()
            
        except Exception as e:
            logger.error(f"Error in queue processor: {traceback.format_exc()}")
            time.sleep(1)

def start_queue_processor():
    """Start the queue processing thread"""
    global processing_active, queue_processor_thread
    
    if queue_processor_thread and queue_processor_thread.is_alive():
        return
    
    processing_active = True
    queue_processor_thread = threading.Thread(target=process_queue, daemon=True)
    queue_processor_thread.start()
    logger.info("Queue processor started")

def stop_queue_processor():
    """Stop the queue processing thread"""
    global processing_active
    processing_active = False
    logger.info("Queue processor stopping")

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "👋 Welcome! Use /setcaption to set your custom caption\n/clearcaption to clear caption\n/status to check processing status")

@bot.message_handler(commands=['setcaption'])
def set_user_caption(message):
    try:
        caption = message.text.split(' ', 1)[1]
        set_caption(message.from_user.id, caption)
        bot.send_message(message.chat.id, "✅ Caption saved!")
        logger.info(f"User {message.from_user.id} set caption: {caption}")
    except IndexError:
        bot.send_message(message.chat.id, "❗Please provide caption text.\nExample:\n/setcaption Your text here")

@bot.message_handler(commands=['clearcaption'])
def clear_user_caption(message):
    clear_caption(message.from_user.id)
    bot.send_message(message.chat.id, "🧹 Caption cleared!")
    logger.info(f"User {message.from_user.id} cleared caption")

@bot.message_handler(commands=['status'])
def check_status(message):
    """Check the current processing status"""
    status_text = (
        "📊 **Bot Status**\n"
        f"✅ Total Processed: {queue_status['total_processed']}\n"
        f"❌ Failed Attempts: {queue_status['failed_attempts']}\n"
        f"📦 Queue Size: {queue_status['queue_size']}\n"
        f"⏰ Last Processed: {queue_status['last_processed'] or 'Never'}\n"
        f"🚀 Processing Speed: {queue_status['processing_speed']:.2f} files/sec\n"
        f"🔧 Queue Processor: {'Active' if processing_active else 'Inactive'}"
    )
    bot.send_message(message.chat.id, status_text, parse_mode='Markdown')
    logger.info(f"Status checked by user {message.from_user.id}")

@bot.message_handler(commands=['clearqueue'])
def clear_queue(message):
    """Clear all files from queue"""
    global file_queue
    
    # Empty the queue
    while not file_queue.empty():
        try:
            file_queue.get_nowait()
            file_queue.task_done()
        except:
            break
    
    queue_status["queue_size"] = 0
    bot.send_message(message.chat.id, "🧹 Queue cleared successfully!")
    logger.info(f"Queue cleared by user {message.from_user.id}")

@bot.message_handler(content_types=['photo', 'video', 'document'])
def media_handler(message):
    """Add media files to processing queue"""
    user_id = message.from_user.id
    caption = get_caption(user_id)
    
    if not caption:
        bot.send_message(user_id, "❗Set caption first using /setcaption")
        return
    
    # Check queue size limit
    if file_queue.qsize() >= MAX_QUEUE_SIZE:
        bot.send_message(user_id, "⚠️ Queue is full! Please wait before sending more files.")
        return
    
    # Add to queue
    file_data = {
        'user_id': user_id,
        'message': message,
        'timestamp': datetime.now()
    }
    file_queue.put(file_data)
    queue_status["queue_size"] = file_queue.qsize()
    
    # Start processor if not running
    start_queue_processor()
    
    # Send immediate confirmation
    queue_position = file_queue.qsize()
    bot.send_message(user_id, f"📥 File added to processing queue. Position: {queue_position}")
    logger.info(f"File added to queue by user {user_id}, queue size: {file_queue.qsize()}")

# ========== INITIALIZATION ==============
if __name__ == "__main__":
    logger.info("🤖 Bot starting...")
    print("🤖 Bot started polling...")
    
    # Start queue processor
    start_queue_processor()
    
    # Main polling loop with auto-restart
    while True:
        try:
            bot.polling(none_stop=True, timeout=90, skip_pending=True)
        except Exception as e:
            logger.error(f"Polling error: {traceback.format_exc()}")
            print("❌ Error occurred:")
            traceback.print_exc()
            print("🔁 Restarting bot in 5 seconds...")
            time.sleep(5)
        finally:
            # Ensure clean shutdown
            stop_queue_processor()
