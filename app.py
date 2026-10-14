import streamlit as st
import pandas as pd

from deriv_client import DerivClient
from trade_journal import TradeJournal
from trading_engine import TradingEngine


st.set_page_config(
    page_title="Deriv Trading Bot",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Deriv Trading Bot")
st.caption("Market signals, automated trading, risk controls and trade journal")

# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

defaults = {
    "client": None,
    "engine": None,
    "journal": None,
    "connected_account": None,
    "account_balance": None,
    "markets": [],
    "last_cycle": {},
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------
# CONNECTION AND ACCOUNT SELECTION
# --------------------------------------------------

st.sidebar.header("Deriv Connection")

app_id = st.sidebar.text_input(
    "Deriv App ID",
    key="app_id_input",
)

token = st.sidebar.text_input(
    "Personal Access Token",
    type="password",
    key="token_input",
)

account_type = st.sidebar.radio(
    "Select ONE account",
    ["demo", "real"],
    format_func=lambda value: (
        "Demo account" if value == "demo"
        else "REAL MONEY account"
    ),
    key="account_type_input",
)

real_confirm = False

if account_type == "real":
    real_confirm = st.sidebar.checkbox(
        "I understand that real trades can lose money.",
        key="real_trading_confirmation",
    )

connected = (
    st.session_state.client is not None
    and st.session_state.connected_account == account_type
)

if (
    st.session_state.client is not None
    and st.session_state.connected_account != account_type
):
    st.session_state.engine.stop()
    st.warning(
        "Your selected account has changed. Automation has been "
        "stopped. Connect again to use the newly selected account."
    )

if st.sidebar.button("Connect to selected account", type="primary"):
    if not app_id.strip() or not token.strip():
        st.sidebar.error("Enter your App ID and personal access token.")
    elif account_type == "real" and not real_confirm:
        st.sidebar.error("Confirm the real-account risk warning.")
    else:
        try:
            client = DerivClient(app_id.strip(), token.strip())

            # Verify access to the selected account only.
            balance = client.get_balance(account_type)

            journal = TradeJournal("trade_journal.db")
            engine = TradingEngine(client, journal)

            st.session_state.client = client
            st.session_state.journal = journal
            st.session_state.engine = engine
            st.session_state.connected_account = account_type
            st.session_state.account_balance = balance
            st.session_state.markets = []
            st.session_state.last_cycle = {}

            st.sidebar.success(
                f"Connected to the selected {account_type.upper()} account."
            )

        except Exception as exc:
            st.sidebar.error(f"Connection failed: {exc}")


# --------------------------------------------------
# MAIN DASHBOARD
# --------------------------------------------------

if not connected:
    st.info(
        "Choose Demo or Real, enter your Deriv credentials, "
        "and connect to that account."
    )
    st.caption(
        "Your personal access token is entered in the password field. "
        "Never paste it into your source code or commit it to GitHub."
    )
    st.stop()


client = st.session_state.client
engine = st.session_state.engine
journal = st.session_state.journal

st.subheader("Selected Account")

balance = st.session_state.account_balance

if balance:
    col1, col2, col3 = st.columns(3)

    col1.metric("Account", account_type.upper())
    col2.metric(
        "Balance",
        f"{balance['balance']:.2f} {balance['currency']}",
    )
    col3.metric("Account ID", str(balance["account_id"]))

if st.button("Refresh selected account balance"):
    try:
        balance = client.get_balance(account_type)
        st.session_state.account_balance = balance
        st.rerun()
    except Exception as exc:
        st.error(f"Balance refresh failed: {exc}")


# --------------------------------------------------
# MARKETS
# --------------------------------------------------

st.divider()
st.subheader("Market Selection")

if st.button("Load available markets"):
    try:
        st.session_state.markets = client.get_active_symbols()
    except Exception as exc:
        st.error(f"Could not load markets: {exc}")

markets = st.session_state.markets

if not markets:
    st.info("Load markets to choose a trading symbol.")
    st.stop()

market_labels = {
    f"{market['display_name']} ({market['symbol']})": market["symbol"]
    for market in markets
}

selected_label = st.selectbox(
    "Market",
    options=list(market_labels.keys()),
)

selected_symbol = market_labels[selected_label]


# --------------------------------------------------
# TRADING SETTINGS
# --------------------------------------------------

st.divider()
st.subheader("Trading Settings")

col1, col2 = st.columns(2)

with col1:
    contract_type = st.selectbox(
        "Trade direction",
        ["CALL", "PUT"],
        format_func=lambda value: (
            "Rise (CALL)" if value == "CALL"
            else "Fall (PUT)"
        ),
    )

    stake = st.number_input(
        "Stake per trade",
        min_value=0.35,
        value=1.0,
        step=0.25,
        format="%.2f",
    )

    max_stake = st.number_input(
        "Maximum purchase price",
        min_value=0.35,
        value=1.0,
        step=0.25,
        format="%.2f",
    )

    duration = st.number_input(
        "Contract duration",
        min_value=1,
        value=5,
        step=1,
    )

    duration_unit = st.selectbox(
        "Duration unit",
        ["t", "s", "m"],
        format_func=lambda value: {
            "t": "Ticks",
            "s": "Seconds",
            "m": "Minutes",
        }[value],
    )

with col2:
    daily_loss_limit = st.number_input(
        "Daily loss limit",
        min_value=0.35,
        value=5.0,
        step=0.5,
        format="%.2f",
        help="Automation stops opening new trades after this daily net loss.",
    )

    max_open_trades = st.number_input(
        "Maximum open trades",
        min_value=1,
        max_value=10,
        value=1,
        step=1,
    )

    cooldown_seconds = st.number_input(
        "Seconds between entries",
        min_value=0,
        value=60,
        step=10,
    )

    loss_cooldown_seconds = st.number_input(
        "Pause after a loss (seconds)",
        min_value=0,
        value=300,
        step=30,
    )

    st.text_input(
        "Account currency",
        value=balance["currency"],
        disabled=True,
    )


# --------------------------------------------------
# AUTOMATION CONTROLS
# --------------------------------------------------

st.divider()
st.subheader("Automation")

if account_type == "real":
    st.warning(
        "REAL ACCOUNT: enabling automation can purchase contracts "
        "using real money. Losses are possible."
    )

start_col, stop_col = st.columns(2)

with start_col:
    if st.button("▶ Start automation", type="primary"):
        if stake > max_stake:
            st.error("Stake cannot exceed the maximum purchase price.")
        elif stake > balance["balance"]:
            st.error("Stake exceeds the selected account balance.")
        elif account_type == "real" and not real_confirm:
            st.error("Confirm the real-account risk warning first.")
        else:
            engine.start()
            st.success("Automation enabled for the selected account.")
            st.rerun()

with stop_col:
    if st.button("■ Stop automation"):
        engine.stop()
        st.info(
            "New entries stopped. The bot can still monitor and record "
            "settlements for open trades."
        )
        st.rerun()


# --------------------------------------------------
# AUTOMATED MONITORING
# --------------------------------------------------

config = {
    "account_type": account_type,
    "allow_real": (
        account_type == "real" and real_confirm
    ),
    "symbol": selected_symbol,
    "currency": balance["currency"],
    "contract_type": contract_type,
    "stake": stake,
    "max_stake": max_stake,
    "daily_loss_limit": daily_loss_limit,
    "max_open_trades": int(max_open_trades),
    "cooldown_seconds": int(cooldown_seconds),
    "loss_cooldown_seconds": int(loss_cooldown_seconds),
    "duration": int(duration),
    "duration_unit": duration_unit,
}

@st.fragment(run_every="5s")
def monitor_bot():
    current_engine = st.session_state.engine

    if current_engine is None:
        st.info("Connect to an account to begin.")
        return

    # Never run cycles against an account other than the connected one.
    if st.session_state.connected_account != account_type:
        current_engine.stop()
        st.error("Account selection changed. Reconnect before continuing.")
        return

    result = current_engine.run_cycle(config)
    st.session_state.last_cycle = result

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Automation",
        "RUNNING" if current_engine.running else "STOPPED",
    )
    col2.metric(
        "Current signal",
        current_engine.last_signal,
    )
    col3.metric(
        "Open trades",
        len(current_engine._open_trades(account_type)),
    )

    st.write("**Latest action:**", current_engine.last_action)

    if current_engine.last_error:
        st.error(current_engine.last_error)

    if result.get("contract_id"):
        st.success(
            f"Deriv confirmed contract ID: {result['contract_id']}"
        )

monitor_bot()


# --------------------------------------------------
# TRADE JOURNAL
# --------------------------------------------------

st.divider()
st.subheader(f"Trade Journal — {account_type.upper()}")

try:
    trades = journal.list_trades(
        limit=100,
        account_type=account_type,
    )

    summary = journal.summary(account_type=account_type)

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total trades", summary["total_trades"] or 0)
    col2.metric("Wins", summary["wins"] or 0)
    col3.metric("Losses", summary["losses"] or 0)
    col4.metric(
        "Net profit/loss",
        f"{summary['total_profit_loss']:.2f}",
    )

    if trades:
        st.dataframe(
            pd.DataFrame(trades),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No trades recorded for this account yet.")

except Exception as exc:
    st.error(f"Could not load the trade journal: {exc}")


st.caption(
    "Signals use a moving-average crossover. This is not a guarantee "
    "of profitable entries. Keep the app running to maintain its "
    "automatic monitoring cycle. Existing open contracts may continue "
    "until they settle, even after new entries are stopped."
)