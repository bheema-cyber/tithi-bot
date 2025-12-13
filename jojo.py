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
# UPDATED URL to use the complete-panchang endpoint based on user's confirmation
URL = "https://json.freeastrologyapi.com/complete-panchang"
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
# API AND PARSING FUNCTIONS
# ----------------------------------------------------------------------

def build_api_payload(dt_obj):
    """Constructs the JSON payload for the Complete Panchang API request."""
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

def fetch_panchang_data(payload):
    """Sends the request to the Panchang API and returns the parsed data dictionary."""
    headers = {'Content-Type': 'application/json', 'x-api-key': ASTRO_API_KEY}
    
    try:
        response = requests.request("POST", URL, headers=headers, data=payload, timeout=10)
        response.raise_for_status() 

        panchang_data = response.json()
        
        # REMOVED double-parsing logic as complete-panchang returns clean JSON
        
        # Check if the API returned an error (e.g., if API key is invalid)
        if "error" in panchang_data:
            return {"error": panchang_data["error"]}
        
        # If no explicit error key, return the data
        return panchang_data

    except requests.exceptions.RequestException as e:
        logger.error(f"API Request failed: {e}")
        return {"error": f"API request failed: Check network or API service status."}
    except json.JSONDecodeError:
        return {"error": "Failed to decode the Panchang data from the API response."}
    except Exception:
        return {"error": f"An unexpected error occurred during API fetch."}


def format_panchang_table(panchang_data, dt_obj):
    """Formats the Complete Panchang data into a rich-text MarkdownV2 message for Telegram."""
    
    if panchang_data.get("error"):
        return f"❌ *Error:* {panchang_data['error']}"

    # --- Helper to format completion time ---
    def format_completion_time(iso_time):
        if not iso_time: return "N/A"
        try:
            # The API returns time in YYYY-MM-DD HH:MM:SS format
            dt = datetime.strptime(iso_time, '%Y-%m-%d %H:%M:%S')
            return dt.strftime('%I:%M:%S %p, %b %d')
        except ValueError:
            return "N/A"

    # --- Extract Major Panchang Components ---
    tithi = panchang_data.get("tithi", {})
    nakshatra = panchang_data.get("nakshatra", {})
    yoga1 = panchang_data.get("yoga", {}).get("1", {})
    karana1 = panchang_data.get("karana", {}).get("1", {})
    
    # --- Date/Time & Location Info ---
    query_date_str = dt_obj.strftime("%A, %B %d, %Y")
    query_time_str = dt_obj.strftime("%I:%M:%S %p")
    sun_rise = panchang_data.get("sun_rise", "N/A")
    sun_set = panchang_data.get("sun_set", "N/A")

    # --- MarkdownV2 Output Construction ---
    output = f"🕉️ *Panchang Details for:* `{query_date_str}`\n"
    output += rf"_Time of Calculation: {query_time_str} IST \(Theni, TN\)_ \n"
    output += rf"_Sunrise: {sun_rise} | Sunset: {sun_set}_\n\n"
    
    # --- TITHI SECTION ---
    output += "*🌙 Tithi \(Lunar Day\):*\n"
    output += "```\n"
    output += f"Name: {tithi.get('name', 'N/A').title()} ({tithi.get('number', 'N/A')})\n"
    output += f"Paksha: {tithi.get('paksha', 'N/A').title()}\n"
    output += f"Completes: {format_completion_time(tithi.get('completes_at'))}\n"
    output += f"Remaining: {tithi.get('left_precentage', 'N/A')}%\n"
    output += "```\n"

    # --- NAKSHATRA SECTION ---
    output += "*⭐ Nakshatra \(Lunar Mansion\):*\n"
    output += "```\n"
    output += f"Name: {nakshatra.get('name', 'N/A').title()} ({nakshatra.get('number', 'N/A')})\n"
    output += f"Starts: {format_completion_time(nakshatra.get('starts_at'))}\n"
    output += f"Ends: {format_completion_time(nakshatra.get('ends_at'))}\n"
    output += f"Remaining: {nakshatra.get('left_percentage', 'N/A')}%\n"
    output += "```\n"
    
    # --- YOGA & KARANA SECTION ---
    output += "*🧘 Yoga & Karana:*\n"
    output += "```\n"
    output += f"Yoga: {yoga1.get('name', 'N/A').title()} ({yoga1.get('number', 'N/A')})\n"
    output += f"Yoga Completion: {format_completion_time(yoga1.get('completion'))}\n"
    output += f"Karana: {karana1.get('name', 'N/A').title()} ({karana1.get('number', 'N/A')})\n"
    output += f"Karana Completion: {format_completion_time(karana1.get('completion'))}\n"
    output += "```"

    # FINAL STEP: Escape MarkdownV2 special characters 
    return output.replace('.', r'\.').replace('-', r'\-')

# ----------------------------------------------------------------------
# TELEGRAM BOT HANDLERS
# ----------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message."""
    user = update.effective_user
    await update.message.reply_markdown_v2(
        rf"Hello, {user.mention_markdown_v2()}! I am your Panchang Bot\. "
        rf"Send me a date with the `/panchang` command in the format `DD-MM-YYYY`\. "
        rf"The calculation will use the exact time you sent the message, converted to IST\. "
        rf"Example: `/panchang 13-12-2025`"
    )

async def panchang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handles the /panchang command, fetching and displaying complete Panchang details.
    """
    
    if not context.args:
        await update.message.reply_text("Please provide a date in the format DD-MM-YYYY. Example: /panchang 13-12-2025")
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
        await update.message.reply_text(f"❌ Invalid date format: '{date_str}'. Please use DD-MM-YYYY (e.g., 13-12-2025).")
        return

    # 4. Build Payload
    payload = build_api_payload(input_dt)
    
    # 5. Fetch Data
    await update.message.reply_text(f"⏳ Fetching Full Panchang details for {input_dt.strftime('%d-%m-%Y')} at {input_dt.strftime('%H:%M:%S')} (Theni, IST)...")
    panchang_data = fetch_panchang_data(payload)
    
    # 6. Format and Send
    response_text = format_panchang_table(panchang_data, input_dt)
    
    await update.message.reply_markdown_v2(
        response_text 
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a message when the command /help is issued."""
    help_text = (
        r"This bot provides Full Panchang \(Tithi, Nakshatra, Yoga, Karana\) details\. \n\n"
        r"Commands:\n"
        r"*/start* \- Start the bot\.\n"
        r"*/panchang DD\-MM\-YYYY* \- Get Full Panchang details for the specified date\. \n"
        r"Example: `/panchang 13\-12\-2025`\n\n"
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
    application.add_handler(CommandHandler("panchang", panchang_command))

    # --- Start the Webhook ---
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TELEGRAM_BOT_TOKEN,
        webhook_url=WEBHOOK_URL + '/' + TELEGRAM_BOT_TOKEN, 
        drop_pending_updates=True
    )
    logger.info(f"Bot started successfully on webhook URL path: {WEBHOOK_URL + '/' + TELEGRAM_BOT_TOKEN}")


if __name__ == '__main__':
    main()
