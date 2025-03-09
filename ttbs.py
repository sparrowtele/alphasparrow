import os
from dotenv import load_dotenv

load_dotenv("tbs.env")  # Make sure to specify your file name if not .env
import os
import json
import random
import requests
import datetime
import logging
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ------------------------- Logging Configuration -------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------- Bot Credentials -------------------------
API_ID = os.environ.get("API_ID")  
API_HASH = os.environ.get("API_HASH")  
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# ------------------------- External API Settings -------------------------
CRYPTOPANIC_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY")

# ------------------------- Admin & Channel Settings -------------------------
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
CHANNEL_CHAT_ID = os.environ.get("CHANNEL_CHAT_ID")

# ------------------------- Global Variables -------------------------
user_portfolios = {}   # In-memory storage for user portfolios
user_states = {}       # For tracking interactive states

# For some functions, we use a preset list of top 5 coins
TOP_COINS = ["BTC", "ETH", "BNB", "ADA", "XRP"]

# Local file for recording 30-minute updates (for daily summary)
DATA_FILENAME = "crypto_data.json"

# ------------------------- Helper Functions -------------------------
def fetch_binance_price(symbol):
    """Fetch live price from Binance public API for a specific symbol (e.g., BTCUSDT)."""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        response = requests.get(url, timeout=5)
        data = response.json()
        if "price" in data:
            return float(data["price"])
        return None
    except Exception as e:
        logger.error(f"Error fetching price for {symbol}: {e}")
        return None

def fetch_binance_ticker(symbol):
    """Fetch 24hr ticker data from Binance for the given symbol (e.g., BTCUSDT)."""
    try:
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}"
        response = requests.get(url, timeout=5)
        return response.json()
    except Exception as e:
        logger.error(f"Error fetching ticker for {symbol}: {e}")
        return None

def fetch_cryptopanic_news(api_key, limit=3):
    """Fetch latest crypto news from Cryptopanic."""
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&public=true"
        response = requests.get(url, timeout=5)
        data = response.json()
        return data.get("results", [])[:limit]
    except Exception as e:
        logger.error(f"Error fetching Cryptopanic news: {e}")
        return []

def get_live_trading_signal(symbol):
    """
    Generate a trading signal based on Binance's 24hr price change percent.
    If change > 2% -> Strong Buy; if change < -2% -> Strong Sell; else Hold.
    """
    ticker = fetch_binance_ticker(f"{symbol.upper()}USDT")
    if ticker and "priceChangePercent" in ticker:
        try:
            change = float(ticker.get("priceChangePercent", "0"))
            if change > 2:
                signal = "📈 Strong Buy"
            elif change < -2:
                signal = "📉 Strong Sell"
            else:
                signal = "🔄 Hold"
            return f"{symbol.upper()} Signal: {signal} (Change: {change:.2f}%)"
        except Exception as e:
            logger.error(f"Error generating signal for {symbol}: {e}")
            return "Error generating signal."
    return "Data unavailable for signal."

def get_market_trends():
    """Return market trends for top coins using Binance data."""
    trends = "<b>Market Trends (Binance Data)</b>\n\n"
    for coin in TOP_COINS:
        ticker = fetch_binance_ticker(f"{coin}USDT")
        if ticker and "priceChangePercent" in ticker:
            try:
                change = float(ticker.get("priceChangePercent", "0"))
                trends += f"{coin}: {change:.2f}%\n"
            except Exception:
                trends += f"{coin}: Data error\n"
        else:
            trends += f"{coin}: N/A\n"
    return trends

def get_top_gainers_losers():
    """
    Fetch all USDT tickers from Binance, sort them by price change percent,
    and return two modern tables: one for the top 5 gainers and one for the top 5 losers.
    """
    try:
        tickers = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=5).json()
        usdt_tickers = [t for t in tickers if t.get("symbol", "").endswith("USDT")]
        usdt_tickers.sort(key=lambda t: float(t.get("priceChangePercent", "0")))
        top5_losers = usdt_tickers[:5]
        top5_gainers = sorted(usdt_tickers[-5:], key=lambda t: float(t.get("priceChangePercent", "0")), reverse=True)
        
        table_gainers  = "┌────────┬────────────┬─────────┐\n"
        table_gainers += "│ Coin   │ Price      │ Change% │\n"
        table_gainers += "├────────┼────────────┼─────────┤\n"
        for t in top5_gainers:
            coin = t["symbol"].replace("USDT", "")
            price = float(t.get("lastPrice", 0))
            change = float(t.get("priceChangePercent", "0"))
            table_gainers += f"│ {coin:<6} │ ${price:<10.2f} │ {change:>6.2f}% │\n"
        table_gainers += "└────────┴────────────┴─────────┘"
        
        table_losers  = "┌────────┬────────────┬─────────┐\n"
        table_losers += "│ Coin   │ Price      │ Change% │\n"
        table_losers += "├────────┼────────────┼─────────┤\n"
        for t in top5_losers:
            coin = t["symbol"].replace("USDT", "")
            price = float(t.get("lastPrice", 0))
            change = float(t.get("priceChangePercent", "0"))
            table_losers += f"│ {coin:<6} │ ${price:<10.2f} │ {change:>6.2f}% │\n"
        table_losers += "└────────┴────────────┴─────────┘"
        
        message = f"<b>Top 5 Gainers</b>\n<pre>{table_gainers}</pre>\n<b>Top 5 Losers</b>\n<pre>{table_losers}</pre>"
        return message
    except Exception as e:
        logger.error(f"Error in get_top_gainers_losers: {e}")
        return "Error fetching gainers/losers data."

def get_crypto_news_text():
    """Return formatted crypto news from Cryptopanic."""
    posts = fetch_cryptopanic_news(CRYPTOPANIC_API_KEY)
    if posts:
        news_text = "<b>Latest Crypto News</b>\n\n"
        for post in posts:
            title = post.get("title", "No Title")
            url = post.get("url", "#")
            news_text += f"- <a href='{url}'>{title}</a>\n\n"
        return news_text
    return "No news available at the moment."

def get_dummy_portfolio():
    """Return default portfolio message if not set."""
    return "<b>Your Portfolio</b>\nNo portfolio set. Use 'Update Portfolio' to set yours."

def get_technical_analysis():
    """Return a simple technical analysis explanation."""
    return ("<b>Technical Analysis</b>\n\nCharts and indicators forecast price trends. "
            "For example, if Bitcoin increased from $10,000 to $30,000, it might indicate a bullish trend. "
            "Past performance does not guarantee future results.")

def get_crypto_basics():
    """Return a basic explanation about cryptocurrency."""
    return ("<b>Crypto Basics</b>\n\nCryptocurrency is a digital asset secured by cryptography. "
            "Welcome to Alpha Sparrow Channel, your reliable source for top crypto updates, live prices, news, polls, and insights. "
            "<b>Developed by Nitin Chauhan</b>")

def get_trading_strategies():
    """Return details on popular trading strategies."""
    return ("<b>Trading Strategies</b>\n\n"
            "1. Day Trading: Short-term trades based on intraday movements.\n"
            "2. Swing Trading: Capturing short to medium term trends.\n"
            "3. HODLing: Long-term investment strategy.\n\n"
            "Always do your own research before applying any strategy.")

def get_scams_alert():
    """Return tips to avoid crypto scams."""
    return ("<b>Scams Alert</b>\n\nBeware of phishing and fake ICOs. Always verify your sources and never share your private keys.")

def get_buy_sell_crypto_text():
    """Return guide text for buying/selling crypto."""
    return ("<b>Buy/Sell Crypto</b>\n\nUse reputable exchanges like Binance, Coinbase, or Kraken. "
            "Follow KYC and security protocols. For personalized help, contact the admin.")

def get_vip_signals_text():
    """Return VIP signals info and auto-send a message to admin."""
    try:
        admin_message = "User is interested in VIP signals for crypto trading."
        app.send_message(ADMIN_CHAT_ID, admin_message)
    except Exception as e:
        logger.error(f"Error sending VIP message: {e}")
    return "<b>VIP Signals</b>\n\nFor premium signals, please contact the admin."

def get_ai_predictions():
    """
    Fetch all USDT tickers from Binance, sort them by priceChangePercent,
    and return a modern table for the top 5 coins.
    """
    try:
        tickers = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=5).json()
        usdt_tickers = [t for t in tickers if t.get("symbol", "").endswith("USDT")]
        usdt_tickers = [t for t in usdt_tickers if "priceChangePercent" in t]
        usdt_tickers.sort(key=lambda t: float(t.get("priceChangePercent", "0")), reverse=True)
        top5 = usdt_tickers[:5]
        table  = "┌────────┬────────────┬─────────┐\n"
        table += "│ Coin   │ Price      │ Change% │\n"
        table += "├────────┼────────────┼─────────┤\n"
        for t in top5:
            coin = t["symbol"].replace("USDT", "")
            price = float(t.get("lastPrice", 0))
            change = float(t.get("priceChangePercent", "0"))
            table += f"│ {coin:<6} │ ${price:<10.2f} │ {change:>6.2f}% │\n"
        table += "└────────┴────────────┴─────────┘"
        return f"<pre>{table}</pre>"
    except Exception as e:
        logger.error(f"Error in AI predictions: {e}")
        return "Error fetching AI predictions."

def get_rewards_bonuses():
    """Return information about rewards and bonuses."""
    return ("<b>Rewards</b>\n\nPremium membership is available! Subscribe now to receive exclusive signals.")

def get_developer_info():
    """Return developer information."""
    return ("<b>Developer Info</b>\n\nDeveloped by Nitin Chauhan. For collaborations or feedback, contact the developer.")

def get_about_bot():
    """Return information about the bot."""
    return ("<b>About Bot</b>\n\nThis bot provides real-time crypto prices, live signals, news, and reports "
            "to keep you updated in the fast-paced crypto market.\n\n<i>Developed by Nitin Chauhan</i>")

def get_settings_info():
    """Return placeholder settings info."""
    return ("<b>Settings</b>\n\nConfigure your preferences:\n- Notification Preferences\n- Portfolio Update Frequency\n"
            "- Alert Thresholds\n- Language & Display Settings\n\nThese settings are currently placeholders.")

def get_all_coins_data():
    """
    Fetch all USDT pair coin data from Binance and return as a text string.
    """
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        response = requests.get(url, timeout=5)
        data = response.json()
        usdt_pairs = [item for item in data if item.get("symbol", "").endswith("USDT")]
        result = "<b>All USDT Pairs (Binance)</b>\n\n"
        for item in usdt_pairs:
            result += f"{item['symbol']}: {item['price']}\n"
        return result
    except Exception as e:
        logger.error(f"Error fetching all coins data: {e}")
        return "Error fetching all coins data."

def search_coin_price(query):
    """
    Search for a coin's live price from Binance using the full ticker list.
    Query is the coin symbol (e.g., BTC).
    """
    try:
        query = query.upper()
        tickers = requests.get("https://api.binance.com/api/v3/ticker/price", timeout=5).json()
        for t in tickers:
            if t.get("symbol", "").upper() == f"{query}USDT":
                return t["price"]
        return None
    except Exception as e:
        logger.error(f"Error in coin search for {query}: {e}")
        return None

# ------------------------- New Scheduled Functions -------------------------
def post_top5_update():
    """Post live update for top 5 coins every 30 minutes in modern table format."""
    try:
        header = "Top 5 Coins Live Update"
        table  = "┌────────┬────────────┬─────────┐\n"
        table += "│ Coin   │ Price      │ Change% │\n"
        table += "├────────┼────────────┼─────────┤\n"
        for coin in TOP_COINS:
            ticker = fetch_binance_ticker(f"{coin}USDT")
            price = fetch_binance_price(f"{coin}USDT")
            if ticker and price is not None and "priceChangePercent" in ticker:
                try:
                    change = float(ticker.get("priceChangePercent", "0"))
                    table += f"│ {coin:<6} │ ${price:<10.2f} │ {change:>6.2f}% │\n"
                except Exception:
                    table += f"│ {coin:<6} │ {'Data err':<10} │ {'':>7} │\n"
            else:
                table += f"│ {coin:<6} │ {'N/A':<10} │ {'N/A':>6} │\n"
        table += "└────────┴────────────┴─────────┘"
        message = f"<b>{header}</b>\n<pre>{table}</pre>"
        app.send_message(CHANNEL_CHAT_ID, message, parse_mode=ParseMode.HTML)
        logger.info("Top 5 update posted to channel.")
    except Exception as e:
        logger.error(f"Error posting top 5 update: {e}")

def post_crypto_news():
    """Post fresh crypto news every 1 hour."""
    news_text = get_crypto_news_text()
    try:
        app.send_message(CHANNEL_CHAT_ID, news_text, parse_mode=ParseMode.HTML)
        logger.info("Crypto news posted to channel.")
    except Exception as e:
        logger.error(f"Error posting crypto news: {e}")

def post_poll():
    """Post a random crypto-related poll every 2 hours."""
    try:
        poll = random.choice(POLL_LIST)
        app.send_poll(CHANNEL_CHAT_ID, question=poll["question"], options=poll["options"], is_anonymous=False)
        logger.info("Poll posted to channel.")
    except Exception as e:
        logger.error(f"Error posting poll: {e}")

def post_daily_summary():
    """
    At 9 PM daily, post a summary report for the top 5 coins from the past 9 hours in modern table format.
    """
    try:
        if os.path.exists(DATA_FILENAME):
            with open(DATA_FILENAME, "r") as f:
                data_records = json.load(f)
            now = datetime.datetime.utcnow()
            nine_hours_ago = now - datetime.timedelta(hours=9)
            recent_records = [r for r in data_records if datetime.datetime.fromisoformat(r["timestamp"]) >= nine_hours_ago]
            if not recent_records:
                summary_text = "No data available for daily summary."
            else:
                header = "Daily Summary Report (Last 9 Hours)"
                table  = "┌──────┬────────┬────────┬────────┬────────┬──────────┐\n"
                table += "│ Coin │ Start  │ End    │ High   │ Low    │ % Change │\n"
                table += "├──────┼────────┼────────┼────────┼────────┼──────────┤\n"
                for coin in TOP_COINS:
                    prices = [r["data"].get(coin) for r in recent_records if isinstance(r["data"].get(coin), (int, float))]
                    if prices:
                        start_price = prices[0]
                        end_price = prices[-1]
                        high = max(prices)
                        low = min(prices)
                        change_percent = ((end_price - start_price) / start_price * 100) if start_price != 0 else 0
                        table += f"│ {coin:<4} │ {start_price:>6.2f} │ {end_price:>6.2f} │ {high:>6.2f} │ {low:>6.2f} │ {change_percent:>8.2f}% │\n"
                    else:
                        table += f"│ {coin:<4} │ {'N/A':>6} │ {'N/A':>6} │ {'N/A':>6} │ {'N/A':>6} │ {'N/A':>8} │\n"
                table += "└──────┴────────┴────────┴────────┴────────┴──────────┘"
                summary_text = f"<b>{header}</b>\n<pre>{table}</pre>"
            app.send_message(CHANNEL_CHAT_ID, summary_text, parse_mode=ParseMode.HTML)
            logger.info("Daily summary posted to channel.")
        else:
            logger.info("No data file found for daily summary.")
    except Exception as e:
        logger.error(f"Error posting daily summary: {e}")

def record_crypto_data():
    """Record top 5 coins' live prices every 30 minutes for daily summary."""
    timestamp = datetime.datetime.utcnow().isoformat()
    record = {"timestamp": timestamp, "data": {}}
    for coin in TOP_COINS:
        price = fetch_binance_price(f"{coin}USDT")
        record["data"][coin] = price if isinstance(price, float) else "N/A"
    try:
        if os.path.exists(DATA_FILENAME):
            with open(DATA_FILENAME, "r") as f:
                existing_data = json.load(f)
        else:
            existing_data = []
    except Exception as e:
        logger.error(f"Error reading {DATA_FILENAME}: {e}")
        existing_data = []
    existing_data.append(record)
    try:
        with open(DATA_FILENAME, "w") as f:
            json.dump(existing_data, f, indent=4)
        logger.info(f"Data recorded at {timestamp}")
    except Exception as e:
        logger.error(f"Error writing {DATA_FILENAME}: {e}")

def post_good_morning():
    """Send Good Morning message at 7 AM with a crypto tip/quote and update JSON file."""
    message = ("<b>Good Morning!</b>\n"
               "\"Every morning is a new opportunity in crypto! Stay curious and trade smart.\"")
    try:
        app.send_message(CHANNEL_CHAT_ID, message, parse_mode=ParseMode.HTML)
        with open("good_morning.json", "w") as f:
            json.dump({"message": message, "timestamp": datetime.datetime.utcnow().isoformat()}, f, indent=4)
        logger.info("Good Morning message posted.")
    except Exception as e:
        logger.error(f"Error posting Good Morning message: {e}")

def post_ai_prediction():
    """Post AI prediction at 10 AM in modern table format showing top 5 coins by positive change."""
    prediction = get_ai_predictions()
    try:
        app.send_message(CHANNEL_CHAT_ID, prediction, parse_mode=ParseMode.HTML)
        logger.info("AI prediction posted to channel.")
    except Exception as e:
        logger.error(f"Error posting AI prediction: {e}")

def post_fear_greed_index():
    """Post Fear & Greed Index at 6 PM in modern table format."""
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url, timeout=5)
        data = response.json()
        if data and "data" in data and len(data["data"]) > 0:
            index = data["data"][0]["value"]
            classification = data["data"][0]["value_classification"]
            header = "Fear & Greed Index"
            line = "─" * 33
            table  = f"┌{line}┐\n"
            table += f"│ {header:^33} │\n"
            table += f"├{line}┤\n"
            table += f"│ Sentiment: {classification:<16} │\n"
            table += f"│ Index:     {index:^16} │\n"
            table += f"└{line}┘\n"
            message = f"<pre>{table}</pre>"
        else:
            message = "<b>Fear & Greed Index</b>\nData unavailable."
        app.send_message(CHANNEL_CHAT_ID, message, parse_mode=ParseMode.HTML)
        logger.info("Fear & Greed Index posted to channel.")
    except Exception as e:
        logger.error(f"Error posting Fear & Greed Index: {e}")

def post_risk_meter():
    """
    Post Risk Meter update every 15 minutes in modern table format along with live signal.
    Computes risk level using the Fear & Greed Index value and appends the AI prediction table (top 5 coins).
    """
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url, timeout=5)
        data = response.json()
        if data and "data" in data and len(data["data"]) > 0:
            value = int(data["data"][0]["value"])
            if value < 25:
                risk_level = "High Risk"
            elif 25 <= value < 50:
                risk_level = "Medium Risk"
            else:
                risk_level = "Low Risk"
        else:
            risk_level = "N/A"
            value = "N/A"
        header_rm = "Risk Meter"
        line_rm = "─" * 29
        risk_table  = f"┌{line_rm}┐\n"
        risk_table += f"│ {header_rm:^29} │\n"
        risk_table += f"├{line_rm}┤\n"
        risk_table += f"│ Risk Level: {risk_level:<10} │\n"
        risk_table += f"│ F&G Index:  {value:^10} │\n"
        risk_table += f"└{line_rm}┘\n"
        
        # Get live signal info from AI Prediction function (top 5 coins)
        live_signal = get_ai_predictions()
        
        combined_message = f"<pre>{risk_table}</pre>\n<b>Live Signal</b>\n{live_signal}"
        app.send_message(CHANNEL_CHAT_ID, combined_message, parse_mode=ParseMode.HTML)
        logger.info("Risk Meter with Live Signal update posted to channel.")
        
        risk_data = {"timestamp": datetime.datetime.utcnow().isoformat(), "risk_message": combined_message}
        if os.path.exists("risk_meter.json"):
            with open("risk_meter.json", "r") as f:
                existing_risk = json.load(f)
        else:
            existing_risk = []
        existing_risk.append(risk_data)
        with open("risk_meter.json", "w") as f:
            json.dump(existing_risk, f, indent=4)
        logger.info("Risk meter data updated in JSON file.")
    except Exception as e:
        logger.error(f"Error posting risk meter: {e}")

# ------------------------- Inline Keyboards for Bot Interface -------------------------
def main_menu_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton("📊 Market Overview", callback_data="market_trends"),
             InlineKeyboardButton("💲 Live Prices", callback_data="live_prices")],
            [InlineKeyboardButton("📋 Portfolio", callback_data="my_portfolio"),
             InlineKeyboardButton("📰 Crypto News", callback_data="crypto_news")],
            [InlineKeyboardButton("🔎 Coin Search", callback_data="coin_search"),
             InlineKeyboardButton("📂 All Coins Data", callback_data="all_coins")],
            [InlineKeyboardButton("📑 Trading Signals", callback_data="trading_signals")],
            [InlineKeyboardButton("💹 Buy/Sell", callback_data="buy_sell_crypto"),
             InlineKeyboardButton("📈 Technical Analysis", callback_data="technical_analysis")],
            [InlineKeyboardButton("📉 Market Trends", callback_data="market_trends"),
             InlineKeyboardButton("⚡ Top Gainers/Losers", callback_data="top_gainers_losers")],
            [InlineKeyboardButton("📖 Crypto Basics", callback_data="crypto_basics"),
             InlineKeyboardButton("🛠 Trading Strategies", callback_data="trading_strategies")],
            [InlineKeyboardButton("🚫 Scams Alert", callback_data="scams_alert"),
             InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
            [InlineKeyboardButton("🚀 VIP Signals", callback_data="vip_signals"),
             InlineKeyboardButton("🔮 AI Predictions", callback_data="ai_predictions")],
            [InlineKeyboardButton("🎁 Rewards", callback_data="rewards_bonuses"),
             InlineKeyboardButton("👨‍💻 Developer Info", callback_data="developer_info")],
            [InlineKeyboardButton("ℹ️ About Bot", callback_data="about_bot")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
        ]
    )

def live_prices_keyboard():
    buttons = [[InlineKeyboardButton(f"💲 {coin}", callback_data=f"price_{coin}")] for coin in TOP_COINS]
    buttons.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

def trading_signals_keyboard():
    buttons = [[InlineKeyboardButton(f"📈 {coin}", callback_data=f"signal_{coin}")] for coin in TOP_COINS]
    buttons.append([InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)

def portfolio_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Update Portfolio", callback_data="update_portfolio")],
        [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
    ])

# ------------------------- Telegram Bot Handlers -------------------------
app = Client("CryptoHighLevelBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(filters.command("start"))
def start(client, message):
    try:
        bot_info = client.get_me()
        bot_name = bot_info.first_name
        photo_path = r"C:\Users\admin\Desktop\tbs\badges\welcome.png"  # Adjust if needed
        welcome_text = (
            "Welcome to Alpha Sparrow Channel – your reliable source for top crypto updates, live coin prices, news, polls, and insights.\n\n"
            "<b>Developed by Nitin Chauhan</b>"
        )
        client.send_photo(message.chat.id, photo=photo_path, caption=welcome_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
    except Exception as e:
        logger.error(f"Error in /start: {e}")
        client.send_message(message.chat.id, f"Error: {str(e)}")

@app.on_message(filters.command("menu"))
def menu(client, message):
    try:
        menu_text = "<b>Main Crypto Menu</b>\nSelect an option below.\n\n<b>Developed by Nitin Chauhan</b>"
        client.send_message(message.chat.id, menu_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
    except Exception as e:
        logger.error(f"Error in /menu: {e}")
        client.send_message(message.chat.id, f"Error: {str(e)}")

@app.on_message(filters.command("portfolio"))
def portfolio(client, message):
    try:
        chat_id = message.chat.id
        text = user_portfolios.get(chat_id, get_dummy_portfolio())
        client.send_message(message.chat.id, text, parse_mode=ParseMode.HTML, reply_markup=portfolio_keyboard())
    except Exception as e:
        logger.error(f"Error in /portfolio: {e}")
        client.send_message(message.chat.id, f"Error: {str(e)}")

@app.on_message(filters.command("news"))
def news(client, message):
    try:
        news_text = get_crypto_news_text()
        client.send_message(message.chat.id, news_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"Error in /news: {e}")
        client.send_message(message.chat.id, "Failed to fetch news.")

@app.on_message(filters.text & ~filters.command(["start", "menu", "portfolio", "news"]))
def handle_text(client, message):
    chat_id = message.chat.id
    if user_states.get(chat_id) == "awaiting_portfolio_update":
        user_portfolios[chat_id] = message.text.strip()
        client.send_message(chat_id, "Your portfolio has been updated.", parse_mode=ParseMode.HTML, reply_markup=portfolio_keyboard())
        user_states.pop(chat_id, None)
    elif user_states.get(chat_id) == "awaiting_coin_search":
        query = message.text.strip()
        price = search_coin_price(query)
        if price is not None:
            response = f"{query.upper()} live price: ${price}"
        else:
            response = "Live price not available. Please try again."
        client.send_message(chat_id, response, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]]
        ))
        user_states.pop(chat_id, None)

@app.on_callback_query()
def callback_handler(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    text = ""
    keyboard = main_menu_keyboard()
    
    if data == "back_to_menu":
        text = "<b>Main Crypto Menu</b>\nSelect an option below.\n\n<b>Developed by Nitin Chauhan</b>"
    elif data == "live_prices":
        text = "<b>Live Prices</b>\nSelect a coin:"
        keyboard = live_prices_keyboard()
    elif data.startswith("price_"):
        symbol = data.split("_", 1)[1]
        price = fetch_binance_price(f"{symbol}USDT")
        if price is None:
            text = f"Error: Live price not available for {symbol}."
        else:
            text = f"{symbol} live price: ${price}"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "my_portfolio":
        text = user_portfolios.get(chat_id, get_dummy_portfolio())
        keyboard = portfolio_keyboard()
    elif data == "update_portfolio":
        text = "<b>Update Portfolio</b>\nPlease enter your portfolio details (e.g., BTC:2, ETH:5)."
        user_states[chat_id] = "awaiting_portfolio_update"
    elif data == "crypto_news":
        text = get_crypto_news_text()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "coin_search":
        text = "<b>Coin Search</b>\nEnter a coin symbol (e.g., BTC) to get the live price."
        user_states[chat_id] = "awaiting_coin_search"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "trading_signals":
        text = "<b>Trading Signals</b>\nSelect a coin:"
        keyboard = trading_signals_keyboard()
    elif data.startswith("signal_"):
        symbol = data.split("_", 1)[1]
        text = get_live_trading_signal(symbol)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "technical_analysis":
        text = get_technical_analysis()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "market_trends":
        text = get_market_trends()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "top_gainers_losers":
        text = get_top_gainers_losers()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "crypto_basics":
        text = get_crypto_basics()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "trading_strategies":
        text = get_trading_strategies()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "scams_alert":
        text = get_scams_alert()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "settings":
        text = get_settings_info()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "vip_signals":
        text = get_vip_signals_text()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📞 Contact Admin", url="https://t.me/alphasparrow")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
        ])
    elif data == "ai_predictions":
        text = get_ai_predictions()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "rewards_bonuses":
        text = get_rewards_bonuses()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "developer_info":
        text = get_developer_info()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "about_bot":
        text = get_about_bot()
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    elif data == "buy_sell_crypto":
        text = get_buy_sell_crypto_text()
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📞 Contact Admin", url="https://t.me/alphasparrow")],
            [InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]
        ])
    elif data == "all_coins":
        all_data = get_all_coins_data()
        with open("all_coins.txt", "w", encoding="utf-8") as f:
            f.write(all_data)
        client.send_document(chat_id, document="all_coins.txt", caption="All USDT Pair Data from Binance")
        return
    else:
        text = "Unknown option!"
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Menu", callback_data="back_to_menu")]])
    
    try:
        client.edit_message_text(
            chat_id=chat_id,
            message_id=callback_query.message.id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    except Exception as e:
        logger.error(f"Error editing callback message: {e}")

# ------------------------- Background Scheduler -------------------------
def record_crypto_data():
    """Record top 5 coins' live prices every 30 minutes for daily summary."""
    timestamp = datetime.datetime.utcnow().isoformat()
    record = {"timestamp": timestamp, "data": {}}
    for coin in TOP_COINS:
        price = fetch_binance_price(f"{coin}USDT")
        record["data"][coin] = price if isinstance(price, float) else "N/A"
    try:
        if os.path.exists(DATA_FILENAME):
            with open(DATA_FILENAME, "r") as f:
                existing_data = json.load(f)
        else:
            existing_data = []
    except Exception as e:
        logger.error(f"Error reading {DATA_FILENAME}: {e}")
        existing_data = []
    existing_data.append(record)
    try:
        with open(DATA_FILENAME, "w") as f:
            json.dump(existing_data, f, indent=4)
        logger.info(f"Data recorded at {timestamp}")
    except Exception as e:
        logger.error(f"Error writing {DATA_FILENAME}: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    # Post top 5 update every 30 minutes
    scheduler.add_job(post_top5_update, 'interval', minutes=30)
    # Post crypto news every 1 hour
    scheduler.add_job(post_crypto_news, 'interval', minutes=60)
    # Post a random poll every 2 hours
    scheduler.add_job(post_poll, 'interval', minutes=120)
    # Post daily summary every day at 9 PM UTC
    scheduler.add_job(post_daily_summary, CronTrigger(hour=21, minute=0))
    # Record data every 30 minutes
    scheduler.add_job(record_crypto_data, 'interval', minutes=30)
    # Post Good Morning message every day at 7 AM UTC
    scheduler.add_job(post_good_morning, CronTrigger(hour=7, minute=0))
    # Post Risk Meter with Live Signal every 15 minutes
    scheduler.add_job(post_risk_meter, 'interval', minutes=15)
    # Post AI Prediction every day at 10 AM UTC
    scheduler.add_job(post_ai_prediction, CronTrigger(hour=10, minute=0))
    # Post Fear & Greed Index every day at 6 PM UTC
    scheduler.add_job(post_fear_greed_index, CronTrigger(hour=18, minute=0))
    scheduler.start()
    logger.info("Scheduler started: Top 5 update every 30 min, news every 1 hr, poll every 2 hrs, daily summary at 9 PM, Good Morning at 7 AM, Risk Meter every 15 min (with Live Signal), AI Prediction at 10 AM, Fear & Greed Index at 6 PM.")

# ------------------------- Main -------------------------
if __name__ == "__main__":
    # Start scheduler in a separate thread and run the bot
    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
    scheduler_thread.start()
    logger.info("Starting Telegram Bot...")
    app.run()
