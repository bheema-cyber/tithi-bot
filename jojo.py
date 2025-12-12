import requests
import json
from datetime import datetime
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import sys
import pytz 
import os 

# --- CONFIGURATION ---
# Load secrets from Render Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ASTRO_API_KEY = os.getenv("ASTRO_API_KEY")

# API Endpoint and Constant Location Data 
URL = "https://json.freeastrologyapi.com/tithi-durations"
LATITUDE, LONGITUDE = 10.0079, 77.4735 # Theni, Tamil Nadu
TIMEZONE = 5.5 # IST
LOCAL_TIMEZONE = pytz.timezone('Asia/Kolkata') 

# Render Webhook Configuration
PORT = int(os.environ.get('PORT', 8443))
# Render assigns the URL when the service is created
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'YOUR_RENDER_WEBHOOK_URL_HERE')

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# API AND PARSING FUNCTIONS (No Change)
# ----------------------------------------------------------------------

def build_api_payload(dt_obj):
    """Constructs the JSON payload for the Tithi API request."""
    return json.dumps({
        "year": dt_obj.year, 
        "month": dt_obj.month, 
        "date": dt_obj.day,
        "hours": dt_obj.hour, 
        "minutes": dt_obj.minute, 
        "seconds": dt_obj.second,
        "latitude": LATITUDE, 
        "longitude": LONGITUDE, 
        "timezone": TIMEZONE,
        "config": {"observation_point": "topocentric", "ayanamsha": "lahiri"}
    })

def fetch_tithi_data(payload):
    """Sends the request to the Tithi API and returns the parsed Tithi dictionary."""
    headers = {'Content-Type': 'application/json', 'x-api-key': ASTRO_API_KEY}
    
    try:
        response = requests.request("POST", URL, headers=headers, data=payload, timeout=10)
        response.raise_for_status() 

        main_data = response.json()
        
        # --- Robust Double-Parsing Logic ---
        raw_json_str_quoted = main_data.get("output")
        if not raw_json_str_quoted:
            return None
        
        inner_string_value = json.loads(raw_json_str_quoted)
        tithi_obj = json.loads(inner_string_value)
        return tithi_obj

    except requests.exceptions.RequestException as e:
        logger.error(f"API Request failed: {e}")
        return {"error": f"API request failed: Check network or API service status."}
    except json.JSONDecodeError:
        return {"error": "Failed to decode the Tithi data from the API response."}
    except Exception:
        return {"error": f"An unexpected error occurred during API fetch."}


def format_tithi_table(tithi_data, dt_obj):
    """Formats the Tithi data into a rich-text MarkdownV2 table for Telegram."""
    
    if tithi_data.get("error"):
        return f"❌ *Error:* {tithi_data['error']}"

    # --- Data Extraction ---
    tithi_name = tithi_data.get("name", "N/A").title()
    tithi_number = tithi_data.get("number", "N/A")
    paksha = tithi_data.get("paksha", "N/A").title()
    completes_at = tithi_data.get("completes_at", "N/A")
    left_percentage = tithi_data.get("left_precentage", "N/A")

    # --- Date/Time Formatting ---
    completion_time_str, completion_date_str = "N/A", "N/A"
    if completes_at != "N/A":
        try:
            completion_dt = datetime.strptime(completes_at, '%Y-%m-%d %H:%M:%S')
            completion_time_str = completion_dt.strftime('%I:%M:%S %p')
            completion_date_str = completion_dt.strftime('%A, %B %d, %Y')
        except ValueError:
            pass
    
    query_date_str = dt_obj.strftime("%A, %B %d, %Y")
    query_time_str = dt_obj.strftime("%I:%M:%S %p")
    
    # --- Telegram MarkdownV2 Output Construction ---
    output = f"✨ *Tithi Details for:* `{query_date_str}`\n"
    output += rf"_Time of Calculation: {query_time_str} IST \(Theni, TN\)_ \n\n"
    
    output += f"*Current Tithi:* *_{tithi_name}_*\n\n"
    
    # Use code block formatting for a clean table appearance in Telegram
    output += "```\n"
    output += f"Attribute         | Value\n"
    output += f"------------------|----------------------\n"
    output += f"Tithi Name        | {tithi_name} ({tithi_number})\n"
    
    paksha_desc = "Waning Moon (Krishna)" if paksha == "Krishna" else "Waxing Moon (Shukla)"
    output += f"Paksha            | {paksha_desc}\n"
    
    output += f"Completes Time    | {completion_time_str}\n"
    output += f"Completes Date    | {completion_date_str}\n"
    
    output += f"Remaining         | {left_percentage}%\n"
    output += "```"
    
    return output.replace('.', r'\.')

# ----------------------------------------------------------------------
# TELEGRAM BOT HANDLERS (No Change)
# ----------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message."""
    user = update.effective_user
    await update.message.reply_markdown_v2(
        rf"Hello, {user.mention_markdown_v2()}! I am your Tithi Calendar Bot\. "
        rf"Send me a date with the `/tithi` command in the format `DD-MM-YYYY`\. "
        rf"The calculation will use the exact time you sent the message, converted to IST\. "
        rf"Example: `/tithi 11-12-2025`"
    )

async def tithi_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /tithi command, ensuring the Tithi is calculated for the 
    user-specified date at the current moment in IST.
    """
    
    if not context.args:
        await update.message.reply_text("Please provide a date in the format DD-MM-YYYY. Example: /tithi 11-12-2025")
        return

    date_str = context.args[0]
    
    try:
        # 1. Parse the user's date (DD-MM-YYYY)
        user_date = datetime.strptime(date_str, '%d-%m-%Y')
        
        # 2. Get the local IST time from the message timestamp (UTC -> IST)
        utc_time = update.message.date
        local_time_ist = utc_time.astimezone(LOCAL_TIMEZONE)
        
        # 3. CONSTRUCT THE FINAL DATETIME OBJECT
        input_dt = datetime(
            user_date.year, 
            user_date.month, 
            user_date.day, 
            local_time_ist.hour, 
            local_time_ist.minute, 
            local_time_ist.second
        )
        
    except ValueError:
        await update.message.reply_text(f"❌ Invalid date format: '{date_str}'. Please use DD-MM-YYYY (e.g., 11-12-2025).")
        return

    # 4. Build Payload
    payload = build_api_payload(input_dt)
    
    # 5. Fetch Data
    await update.message.reply_text(f"⏳ Fetching Tithi details for {input_dt.strftime('%d-%m-%Y')} at {input_dt.strftime('%H:%M:%S')} (Theni, IST)...")
    tithi_data = fetch_tithi_data(payload)
    
    # 6. Format and Send
    response_text = format_tithi_table(tithi_data, input_dt)
    
    await update.message.reply_markdown_v2(
        response_text 
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message when the command /help is issued."""
    help_text = (
        r"This bot provides Tithi (Lunar Day) details based on Indian Astrology principles\. \n\n"
        r"Commands:\n"
        r"*/start* \- Start the bot\.\n"
        r"*/tithi DD\-MM\-YYYY* \- Get Tithi details for the specified date\. The calculation uses the exact time the message is received\. \n"
        r"Example: `/tithi 11\-12\-2025`\n\n"
        r"_Calculations are based on Theni, TN coordinates \(IST\) and Lahiri Ayanaamsha\._"
    )
    await update.message.reply_markdown_v2(help_text)

# ----------------------------------------------------------------------
# MAIN BOT RUNNER (Using Webhook)
# ----------------------------------------------------------------------

def main() -> None:
    """Start the bot using the Render webhook."""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("❌ ERROR: TELEGRAM_BOT_TOKEN not found in environment variables.")
        sys.exit(1)
    
    if WEBHOOK_URL == 'YOUR_RENDER_WEBHOOK_URL_HERE':
        logger.warning("⚠️ WARNING: WEBHOOK_URL is still the placeholder. Update it with your live Render URL.")

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("tithi", tithi_command))

    # --- Start the Webhook ---
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        # FIXED: Add '/' to ensure the URL path is properly formatted for Telegram.
        webhook_url=WEBHOOK_URL + '/' + TELEGRAM_BOT_TOKEN,
        drop_pending_updates=True
    )
    logger.info(f"Bot started successfully on webhook URL path: {WEBHOOK_URL + '/' + TELEGRAM_BOT_TOKEN}")


if __name__ == '__main__':
    main()
