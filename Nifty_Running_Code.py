import time
import json
import pyotp
import streamlit as st
import urllib.request
import pandas as pd
from SmartApi.smartConnect import SmartConnect
from datetime import datetime
from datetime import datetime, time as dt_time
from datetime import datetime, date
import requests



TELEGRAM_BOT_TOKEN = '7518848638:AAFgr0IPFssEhoZ3wz2raXq99H17vandOd0'
TELEGRAM_CHAT_ID = '1459536971'

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'Markdown'  # Optional
        }
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print("Failed to send Telegram message:", response.text)
    except Exception as e:
        print("Error sending Telegram message:", str(e))

# === Credentials ===
# API_KEY = "fygjVzaM"
# CLIENT_CODE = "S1264837"
# PWD = "3085"
# TOTP_SECRET = "REANIKCS5P4FWTMXS2BGGTN2GQ"

# API_KEY = st.sidebar.text_input("API Key", type="password", value="")
# CLIENT_CODE = st.sidebar.text_input("Client Code", value="")
# PWD = st.sidebar.text_input("Password", type="password", value="")
# TOTP_SECRET = st.sidebar.text_input("TOTP Secret", type="password", value="")


st.set_page_config(page_title="NIFTY Options Trader", layout="wide")
st.title("📈 NIFTY Options Trading with Trailing Stop-Loss")

# === State Variables ===
if 'running' not in st.session_state:
    st.session_state.running = False
if 'order_ids' not in st.session_state:
    st.session_state.order_ids = []
if 'positions' not in st.session_state:
    st.session_state.positions = []

# === Sidebar Inputs ===
st.sidebar.header("⚙️ Trading Config")
offset = st.sidebar.selectbox("Select Strike Offset", ["ATM", "ITM+1", "OTM-1"])
quantity = st.sidebar.number_input("Quantity", value=75, step=25)
trailing_sl_points = st.sidebar.number_input("Trailing Stop-Loss (points)", value=30, step=5)
breakout_buffer = st.sidebar.number_input("Breakout Buffer above Low (₹)", value=30, step=5)
# st.sidebar.header("\ud83d\udd11 Login Credentials")
API_KEY = st.sidebar.text_input("API Key", type="password")
CLIENT_CODE = st.sidebar.text_input("Client Code")
PWD = st.sidebar.text_input("Password", type="password")
TOTP_SECRET = st.sidebar.text_input("TOTP Secret", type="password")


# === Functions ===
def login_smartapi():
    obj = SmartConnect(api_key=API_KEY)
    totp = pyotp.TOTP(TOTP_SECRET).now()
    data = obj.generateSession(CLIENT_CODE, PWD, totp)
    return obj


def get_instrument_list():
    url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
    response = urllib.request.urlopen(url)
    return pd.DataFrame(json.loads(response.read()))


def get_nifty_ltp(obj):
    ltp_data = obj.ltpData("NSE", "NIFTY", "26000")
    return float(ltp_data['data']['ltp'])


def find_option_symbols(df, ltp):
    df = df[(df['name'] == 'NIFTY') & (df['instrumenttype'] == 'OPTIDX')]
    # df['expiry'] = pd.to_datetime(df['expiry'], format="%d%b%Y", errors='coerce')
    df.loc[:, 'expiry'] = pd.to_datetime(df['expiry'], format="%d%b%Y", errors='coerce')

    df = df.dropna(subset=['expiry'])
    expiry = df['expiry'].min()

    strike_step = 50
    atm_strike = int(round(ltp / strike_step) * strike_step)
    if offset == "ITM+1":
        ce_strike = atm_strike - strike_step
        pe_strike = atm_strike + strike_step
    elif offset == "OTM-1":
        ce_strike = atm_strike + strike_step
        pe_strike = atm_strike - strike_step
    else:
        ce_strike = atm_strike
        pe_strike = atm_strike

    ce_row = df[
        (df['expiry'] == expiry) & (df['strike'].astype(float) == ce_strike * 100) & (df['symbol'].str.endswith('CE'))]
    pe_row = df[
        (df['expiry'] == expiry) & (df['strike'].astype(float) == pe_strike * 100) & (df['symbol'].str.endswith('PE'))]

    if ce_row.empty or pe_row.empty:
        return None, None, None
    return ce_row.iloc[0], pe_row.iloc[0], expiry


def get_ltp(obj, symbol, token):
    data = obj.ltpData("NFO", symbol, token)
    return data['data']['ltp'], data['data']['close']


def place_order(obj, symbol, token, qty):
    order_params = {
        "variety": "NORMAL",
        "tradingsymbol": symbol,
        "symboltoken": token,
        "transactiontype": "BUY",
        "exchange": "NFO",
        "ordertype": "MARKET",
        "producttype": "INTRADAY",
        "duration": "DAY",
        "price": "0",
        "quantity": str(qty)
    }
    return obj.placeOrder(order_params)


def place_sell_order(obj, symbol, token, qty):
    order_params = {
        "variety": "NORMAL",
        "tradingsymbol": symbol,
        "symboltoken": token,
        "transactiontype": "SELL",
        "exchange": "NFO",
        "ordertype": "MARKET",
        "producttype": "INTRADAY",
        "duration": "DAY",
        "price": "0",
        "quantity": str(qty)
    }
    return obj.placeOrder(order_params)


def square_off_all(obj):
    try:
        positions = obj.position()
        for pos in positions['data']:
            if float(pos['netqty']) != 0:
                transactiontype = "SELL" if float(pos['netqty']) > 0 else "BUY"
                order_params = {
                    "variety": "NORMAL",
                    "tradingsymbol": pos['tradingsymbol'],
                    "symboltoken": pos['symboltoken'],
                    "transactiontype": transactiontype,
                    "exchange": pos['exchange'],
                    "ordertype": "MARKET",
                    "producttype": pos['producttype'],
                    "duration": "DAY",
                    "price": "0",
                    "quantity": abs(int(pos['netqty']))
                }
                obj.placeOrder(order_params)
    except Exception as e:
        st.error(f"Error squaring off: {e}")


def safe_get_ltp(obj, symbol, token):
    try:
        data = obj.ltpData("NFO", symbol, token)
        return data['data']['ltp'], data['data']['close']
    except Exception as e:
        st.warning(f"Rate limit hit or API error for {symbol}. Retrying in 3s...")
        time.sleep(8)
        try:
            data = obj.ltpData("NFO", symbol, token)
            return data['data']['ltp'], data['data']['close']
        except Exception as e:
            st.error(f"Failed to get LTP for {symbol}: {e}")
            return None, None


def get_ltp_with_low(obj, symbol, token):
    try:
        data = obj.ltpData("NFO", symbol, token)
        ltp = float(data['data']['ltp'])
        close = float(data['data'].get('close', ltp - 50))  # fallback if close missing
        low = float(data['data'].get('low', close - 50))  # fallback if low missing
        return ltp, close, low
    except Exception as e:
        st.error(f"❌ Error fetching LTP/Low for {symbol}: {e}")
        return None, None, None


def wait_until_market_open():
    target_time = dt_time(9, 15, 2)
    placeholder = st.empty()  # 🔄 Creates a placeholder to replace messages

    while True:
        now = datetime.now().time()
        if now >= target_time:
            send_telegram_message(f"✅ Market open time reached: {now.strftime('%H:%M:%S')}")
            placeholder.success(f"✅ Market open time reached: {now.strftime('%H:%M:%S')}")
            break
        remaining = datetime.combine(date.today(), target_time) - datetime.now()
        placeholder.info(f"⏱️ Time now: {now.strftime('%H:%M:%S')} | Starting in {remaining.seconds} seconds...")
        time.sleep(1)


def monitor_loop():
    wait_until_market_open()  # 👈 Add this
    obj = login_smartapi()
    df = get_instrument_list()
    nifty_ltp = get_nifty_ltp(obj)
    ce, pe, expiry = find_option_symbols(df, nifty_ltp)

    if ce is None or pe is None:
        st.error("❌ Could not find matching CE/PE option symbols.")
        return

    st.success(f"🎯 Monitoring CE: {ce['symbol']} | PE: {pe['symbol']}")
    ce_token = ce['token']
    pe_token = pe['token']

    last_ce_ltp, last_pe_ltp = None, None
    ce_triggered, pe_triggered = False, False
    ce_sl, pe_sl = None, None
    ce_sl_sold, pe_sl_sold = None, None

    placeholder = st.empty()

    #Loop start
    while st.session_state.running:
        # ce_ltp, ce_close = safe_get_ltp(obj, ce['symbol'], ce_token)
        # pe_ltp, pe_close = safe_get_ltp(obj, pe['symbol'], pe_token)

        ce_ltp, ce_close, ce_low = get_ltp_with_low(obj, ce['symbol'], ce_token)
        pe_ltp, pe_close, pe_low = get_ltp_with_low(obj, pe['symbol'], pe_token)

        if ce_low is not None and pe_low is not None:
            breakout_ce = ce_low + breakout_buffer
            breakout_pe = pe_low + breakout_buffer

        if ce_ltp is None or pe_ltp is None:
            continue

        current_time = datetime.now().strftime("%H:%M:%S")  # Format: HH:MM:SS

        log_text = f"""
        ### 📊 Live Option Prices (Updated: {current_time})

        - **CE:** `{ce['symbol']}`  
            - LTP: ₹{ce_ltp}  
            - Low: ₹{ce_low} 
            - Low+Buffer: ₹{breakout_ce} 
            - Prev Close: ₹{ce_close}  
            - Last LTP: ₹{last_ce_ltp}  
            - Lat CE Sold:  ₹{ce_sl_sold}
            - trailing sl_points : {trailing_sl_points}
            - CE SL:  ₹{ce_sl}

        - **PE:** `{pe['symbol']}`  
            - LTP: ₹{pe_ltp}  
            - Low: ₹{pe_low} 
            - Low+Buffer: ₹{breakout_pe} 
            - Prev Close: ₹{pe_close}  
            - Last LTP: ₹{last_pe_ltp}
            - Lat PE Sold:  ₹{pe_sl_sold}
            - PE SL:  ₹{pe_sl}
        """

        placeholder.markdown(log_text)

        #--------- last Sl buy---#

        if not ce_triggered and last_ce_ltp is not None and ce_sl_sold is not None:
            if last_ce_ltp <= ce_sl_sold < ce_ltp:
                order_id = place_order(obj, ce['symbol'], ce_token, quantity)
                st.success(f"🚀 CE ce_sl_sold Buy (Crossed last SL +{ce_sl_sold}) - Order ID: {order_id}")
                ce_triggered = True
                ce_peak_price = ce_ltp
                ce_sl = ce_ltp - trailing_sl_points

        # --- CE Breakout BUY Logic ---
        # --- CE Breakout Crossing Buy ---
        if not ce_triggered and last_ce_ltp is not None and ce_low is not None:
            breakout_ce = ce_low + breakout_buffer
            if last_ce_ltp <= breakout_ce < ce_ltp:
                order_id = place_order(obj, ce['symbol'], ce_token, quantity)
                st.success(f"🚀 CE Breakout Buy (Crossed Low+{breakout_buffer}) - Order ID: {order_id}")
                ce_triggered = True
                ce_peak_price = ce_ltp
                ce_sl = ce_ltp - trailing_sl_points

        # --- CE BUY Logic ---
        if not ce_triggered and last_ce_ltp is not None and last_ce_ltp <= ce_close < ce_ltp:
            order_id = place_order(obj, ce['symbol'], ce_token, quantity)
            st.success(f"✅ CE Order last close crossing Placed. ID: {order_id}")
            ce_triggered = True
            ce_sl = ce_ltp - trailing_sl_points
            ce_peak_price = ce_ltp
            st.success(f"✅ CE SL: {ce_sl}")

        # elif ce_triggered and ce_ltp - ce_sl >= trailing_sl_points:
        #     ce_sl += trailing_sl_points
        #     st.success(f"✅ CE SL update: {ce_sl}")

        elif ce_triggered and ce_ltp > ce_peak_price:
            ce_peak_price = ce_ltp
            ce_sl = ce_peak_price - trailing_sl_points

        elif ce_triggered and ce_ltp <= ce_sl:
            st.warning(f"📉 CE TSL Hit. Closing Position: {ce_sl}")
            place_sell_order(obj, ce['symbol'], ce_token, quantity)  # Sell
            ce_triggered = False
            ce_sl_sold = ce_ltp + 1

        # --- PE Breakout Crossing Buy ---
        if not pe_triggered and last_pe_ltp is not None and pe_sl_sold is not None:
            if last_pe_ltp <= pe_sl_sold < pe_ltp:
                order_id = place_order(obj, pe['symbol'], pe_token, quantity)
                st.success(f"🚀 PE pe_sl_sold Buy (Crossed Low+{pe_sl_sold}) - Order ID: {order_id}")
                pe_triggered = True
                pe_sl = pe_ltp - trailing_sl_points
        # --- PE Breakout Crossing Buy ---
        if not pe_triggered and last_pe_ltp is not None and pe_low is not None:
            breakout_pe = pe_low + breakout_buffer
            if last_pe_ltp <= breakout_pe < pe_ltp:
                order_id = place_order(obj, pe['symbol'], pe_token, quantity)
                st.success(f"🚀 PE Breakout Buy (Crossed Low+{breakout_buffer}) - Order ID: {order_id}")
                pe_triggered = True
                pe_peak_price = pe_ltp
                pe_sl = pe_ltp - trailing_sl_points
                st.success(f"✅ PE SL: {pe_sl}, LTP PE {pe_ltp}, Sl Poitns {trailing_sl_points} ")

        # --- PE BUY Logic ---
        if not pe_triggered and last_pe_ltp is not None and last_pe_ltp <= pe_close < pe_ltp:
            order_id = place_order(obj, pe['symbol'], pe_token, quantity)
            st.success(f"✅ PE Order crossing last close Placed. ID: {order_id}")
            pe_triggered = True
            pe_sl = pe_ltp - trailing_sl_points
            pe_peak_price = pe_ltp
            peak_price = pe_ltp
            st.success(f"✅ PE SL {pe_sl}")

        # elif pe_triggered and pe_ltp - pe_sl >= trailing_sl_points:
        #     pe_sl =  pe_sl+ ()
        #     st.success(f"✅ PE SL update: {pe_sl}")

        elif pe_triggered and pe_ltp > pe_peak_price:
            pe_peak_price = pe_ltp
            pe_sl = pe_peak_price - trailing_sl_points

        elif pe_triggered and pe_ltp <= pe_sl:
            st.warning("📉 PE TSL Hit. Closing Position.")
            st.success(f"✅ PE SL triggred {pe_sl}")
            place_sell_order(obj, pe['symbol'], pe_token, quantity)  # Sell
            pe_triggered = False
            pe_sl_sold = pe_ltp + 1

        last_ce_ltp = ce_ltp
        last_pe_ltp = pe_ltp

        time.sleep(4)  # Ensure we're under API rate limit


# === Main Controls ===
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🚀 Start Trading"):
        st.session_state.running = True
        monitor_loop()

with col2:
    if st.button("🛑 Stop & Exit"):
        st.session_state.running = False
        obj = login_smartapi()
        square_off_all(obj)
        st.success("✅ All positions squared off.")
