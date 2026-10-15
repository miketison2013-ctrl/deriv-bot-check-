import streamlit as st
import pandas as pd

from deriv_client import DerivClient
from trade_journal import TradeJournal
from trading_engine import TradingEngine


st.set_page_config(
    page_title="Deriv Adaptive Trading Bot",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Deriv Adaptive Trading Bot")
st.caption(
    "Account monitoring, volatility markets, digit analysis, "
    "automated trading, learning and trade history"
)

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
    "connection_message": "",
    "connection_error": "",
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------
# CONNECTION
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
    "Select one account",
    ["demo", "real"],
    format_func=lambda value: (
        "Demo account"
        if value == "demo"
        else "REAL MONEY account"
    ),
    key="account_type_input",
)

real_confirm = False

if account_type == "real":
    real_confirm = st.sidebar.checkbox(
        "I understand real trades can lose money",
        key="real_trading_confirmation",
    )

if (
    st.session_state.client is not None
    and st.session_state.connected_account != account_type
):
    if st.session_state.engine is not None:
        st.session_state.engine.stop()

    st.session_state.client = None
    st.session_state.engine = None
    st.session_state.journal = None
    st.session_state.connected_account = None
    st.session_state.account_balance = None
    st.session_state.markets = []

    st.warning(
        "The account selection changed. Connect again to use "
        "the newly selected account."
    )

if st.sidebar.button(
    "Connect to selected account",
    type="primary",
):
    if not app_id.strip() or not token.strip():
        st.session_state.connection_error = (
            "Enter your App ID and personal access token."
        )
    elif account_type == "real" and not real_confirm:
        st.session_state.connection_error = (
            "Confirm the real-account risk warning first."
        )
    else:
        try:
            client = DerivClient(
                app_id.strip(),
                token.strip(),
            )

            balance = client.get_balance(account_type)

            journal = TradeJournal("trade_journal.db")
            engine = TradingEngine(client, journal)

            st.session_state.client = client
            st.session_state.journal = journal
            st.session_state.engine = engine
            st.session_state.connected_account = account_type
            st.session_state.account_balance = balance
            st.session_state.markets = []
            st.session_state.connection_error = ""
            st.session_state.connection_message = (
                f"Connected to the selected "
                f"{account_type.upper()} account."
            )

            st.rerun()

        except Exception as exc:
            st.session_state.connection_error = (
                f"Connection failed: {exc}"
            )

if st.session_state.connection_error:
    st.sidebar.error(st.session_state.connection_error)

if st.session_state.connection_message:
    st.sidebar.success(st.session_state.connection_message)

st.sidebar.caption(
    "Never paste your personal access token into source code "
    "or commit it to GitHub."
)


# --------------------------------------------------
# CONNECTION STATUS
# --------------------------------------------------

connected = (
    st.session_state.client is not None
    and st.session_state.engine is not None
    and st.session_state.journal is not None
    and st.session_state.connected_account == account_type
)

if not connected:
    st.warning(
        "Not connected. Choose an account in the sidebar and "
        "connect before loading live account data."
    )

    st.subheader("Tool modules")

    st.markdown(
        "- Account balance and connection status\n"
        "- Volatility market scanner\n"
        "- Live tick and last-digit statistics\n"
        "- Market and strategy rankings\n"
        "- Automated trading with risk controls\n"
        "- Trade history and performance learning"
    )

    st.info(
        "The modules listed here describe the planned system. "
        "Some require implementation in the supporting files "
        "before they can produce live results."
    )

    st.stop()


client = st.session_state.client
engine = st.session_state.engine
journal = st.session_state.journal
balance = st.session_state.account_balance


# --------------------------------------------------
# ACCOUNT OVERVIEW
# --------------------------------------------------

st.header("Account Overview")

refresh_col, account_col = st.columns([1, 2])

with refresh_col:
    if st.button("Refresh balance"):
        try:
            st.session_state.account_balance = (
                client.get_balance(account_type)
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Balance refresh failed: {exc}")

balance = st.session_state.account_balance or {}

col1, col2, col3 = st.columns(3)

col1.metric("Selected account", account_type.upper())

if balance:
    col2.metric(
        "Balance",
        "{} {}".format(
            balance.get("balance", "Unavailable"),
            balance.get("currency", ""),
        ),
    )
    col3.metric(
        "Account ID",
        str(balance.get("account_id", "Unavailable")),
    )
else:
    col2.metric("Balance", "Unavailable")
    col3.metric("Account ID", "Unavailable")


# --------------------------------------------------
# MARKET SCANNER
# --------------------------------------------------

st.divider()
st.header("Volatility Market Scanner")

st.write(
    "Load the symbols returned by Deriv. The complete scanner "
    "will analyse each eligible market independently."
)

if st.button("Load or refresh available markets"):
    try:
        st.session_state.markets = client.get_active_symbols()
        if not st.session_state.markets:
            st.warning("Deriv returned no available markets.")
    except Exception as exc:
        st.error(f"Market loading failed: {exc}")

markets = st.session_state.markets or []

if markets:
    market_frame = pd.DataFrame(markets)

    if "symbol" in market_frame.columns:
        market_frame = market_frame.drop_duplicates(
            subset=["symbol"]
        )

    st.metric("Markets returned by Deriv", len(market_frame))

    st.dataframe(
        market_frame,
        use_container_width=True,
        hide_index=True,
    )

    symbol_options = [
        market["symbol"]
        for market in markets
        if market.get("symbol")
    ]

    if symbol_options:
        selected_symbol = st.selectbox(
            "Current strategy market",
            symbol_options,
        )
    else:
        selected_symbol = None

else:
    selected_symbol = None
    st.info(
        "No markets loaded yet. Use the button above. "
        "The rest of the dashboard remains available."
    )


# --------------------------------------------------
# ANALYSIS DASHBOARD
# --------------------------------------------------

st.divider()
st.header("Market Analysis")

analysis_tabs = st.tabs(
    [
        "Last digits",
        "Digit rankings",
        "Volatility rankings",
        "Strategy performance",
    ]
)

with analysis_tabs[0]:
    st.info(
        "Live tick collection and rolling last-digit frequencies "
        "must be connected to the market-data module."
    )

with analysis_tabs[1]:
    st.info(
        "Digit rankings require collected tick samples, sample "
        "sizes, frequency percentages and statistical validation."
    )

with analysis_tabs[2]:
    st.info(
        "Volatility-market rankings require comparable live "
        "statistics for each eligible symbol."
    )

with analysis_tabs[3]:
    st.info(
        "Learning scores must be calculated from recorded and "
        "confirmed trade outcomes, not assumed results."
    )


# --------------------------------------------------
# TRADING SETTINGS
# --------------------------------------------------

st.divider()
st.header("Trading Settings")

col1, col2 = st.columns(2)

with col1:
    contract_type = st.selectbox(
        "Trade direction",
        ["CALL", "PUT"],
        format_func=lambda value: (
            "Rise (CALL)"
            if value == "CALL"
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

    if balance.get("currency"):
        st.text_input(
            "Account currency",
            value=str(balance["currency"]),
            disabled=True,
        )


# --------------------------------------------------
# START AND STOP
# --------------------------------------------------

st.divider()
st.header("Automation Controls")

if account_type == "real":
    st.warning(
        "REAL MONEY ACCOUNT: starting automation can purchase "
        "contracts with real money. Losses are possible."
    )

start_col, stop_col = st.columns(2)

with start_col:
    if st.button(
        "▶ Start automation",
        type="primary",
        use_container_width=True,
    ):
        if selected_symbol is None:
            st.error("Load markets and select a market first.")
        elif stake > max_stake:
            st.error(
                "Stake cannot exceed the maximum purchase price."
            )
        elif stake > float(balance.get("balance", 0)):
            st.error("Stake exceeds the available balance.")
        elif account_type == "real" and not real_confirm:
            st.error("Confirm the real-account risk warning.")
        else:
            engine.start()
            st.success(
                "Automation enabled. The current engine still "
                "uses its implemented strategy; multi-market "
                "selection will be added in the next steps."
            )
            st.rerun()

with stop_col:
    if st.button(
        "■ Stop automation",
        use_container_width=True,
    ):
        engine.stop()
        st.warning(
            "New entries stopped. Already purchased contracts "
            "may remain open until settled."
        )
        st.rerun()

config = {
    "account_type": account_type,
    "allow_real": account_type == "real" and real_confirm,
    "symbol": selected_symbol,
    "currency": balance.get("currency"),
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

st.subheader("Live Bot Status")

status_col1, status_col2, status_col3 = st.columns(3)

status_col1.metric(
    "Automation",
    "RUNNING" if engine.running else "STOPPED",
)
status_col2.metric(
    "Selected market",
    selected_symbol or "None",
)
status_col3.metric(
    "Selected account",
    account_type.upper(),
)

if selected_symbol:
    try:
        result = engine.run_cycle(config)

        st.write(
            "**Latest action:**",
            engine.last_action,
        )

        st.write(
            "**Current signal:**",
            engine.last_signal,
        )

        if engine.last_error:
            st.error(engine.last_error)

        if result.get("contract_id"):
            st.success(
                "Confirmed contract ID: "
                + str(result["contract_id"])
            )

    except Exception as exc:
        st.error(f"Bot monitoring error: {exc}")
else:
    st.info(
        "The engine is waiting for a market to be selected. "
        "No new trade can be placed without a selected market."
    )


# --------------------------------------------------
# TRADE HISTORY
# --------------------------------------------------

st.divider()
st.header(f"Trade History — {account_type.upper()}")

try:
    summary = journal.summary(account_type=account_type)

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Total trades",
        summary.get("total_trades") or 0,
    )
    col2.metric(
        "Wins",
        summary.get("wins") or 0,
    )
    col3.metric(
        "Losses",
        summary.get("losses") or 0,
    )
    col4.metric(
        "Net profit/loss",
        "{:.2f}".format(
            summary.get("total_profit_loss") or 0
        ),
    )

    trades = journal.list_trades(
        limit=200,
        account_type=account_type,
    )

    if trades:
        st.dataframe(
            pd.DataFrame(trades),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No recorded trades for this account yet."
        )

except Exception as exc:
    st.error(f"Could not load trade history: {exc}")


st.caption(
    "This dashboard does not guarantee profitable trades. "
    "The app must remain active for its current monitoring cycle. "
    "The multi-market scanner, digit analysis and learning system "
    "will be implemented and tested in the supporting modules."
)