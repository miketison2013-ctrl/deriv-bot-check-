
import streamlit as st
import pandas as pd

from deriv_client import DerivClient
from trade_journal import TradeJournal
from trading_engine import TradingEngine


st.set_page_config(
    page_title="Deriv Digit Bot",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Deriv Volatility Digit Bot")
st.caption(
    "Digit contracts only · Market analysis · Risk controls · Trade journal"
)

DEFAULTS = {
    "client": None,
    "engine": None,
    "journal": None,
    "connected_account": None,
    "balance": None,
    "markets": [],
    "connection_error": "",
    "connection_message": "",
    "last_scan_result": None,
    "last_cycle_result": None,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------
# ACCOUNT CONNECTION
# --------------------------------------------------

st.sidebar.header("Deriv account")

app_id = st.sidebar.text_input(
    "App ID",
    key="app_id_input",
)

token = st.sidebar.text_input(
    "Personal Access Token",
    type="password",
    key="token_input",
)

account_type = st.sidebar.radio(
    "Choose the account to use",
    ["demo", "real"],
    format_func=lambda value: (
        "Demo account" if value == "demo" else "REAL account"
    ),
    key="account_type_input",
)

real_confirm = False
if account_type == "real":
    real_confirm = st.sidebar.checkbox(
        "I understand real-money trades can lose money",
        key="real_trading_confirmation",
    )

if (
    st.session_state.client is not None
    and st.session_state.connected_account != account_type
):
    st.session_state.engine.running = False
    st.session_state.client = None
    st.session_state.engine = None
    st.session_state.journal = None
    st.session_state.connected_account = None
    st.session_state.balance = None
    st.session_state.last_scan_result = None
    st.session_state.last_cycle_result = None
    st.warning("Account selection changed. Connect to the selected account again.")

if st.sidebar.button("Connect to selected account", type="primary"):
    if not app_id.strip() or not token.strip():
        st.session_state.connection_error = "Enter your App ID and token."
    elif account_type == "real" and not real_confirm:
        st.session_state.connection_error = "Confirm the Real-account risk warning."
    else:
        try:
            client = DerivClient(app_id.strip(), token.strip())
            balance = client.get_balance(account_type)
            journal = TradeJournal("trade_journal.db")
            engine = TradingEngine(client, journal)

            st.session_state.client = client
            st.session_state.balance = balance
            st.session_state.journal = journal
            st.session_state.engine = engine
            st.session_state.connected_account = account_type
            st.session_state.markets = []
            st.session_state.last_scan_result = None
            st.session_state.last_cycle_result = None
            st.session_state.connection_error = ""
            st.session_state.connection_message = (
                f"Connected to the selected {account_type.upper()} account."
            )
            st.rerun()
        except Exception as exc:
            st.session_state.connection_error = str(exc)

if st.session_state.connection_error:
    st.sidebar.error(st.session_state.connection_error)
if st.session_state.connection_message:
    st.sidebar.success(st.session_state.connection_message)

st.sidebar.caption(
    "Keep your token private. Never place it in source code or GitHub."
)

connected = (
    st.session_state.client is not None
    and st.session_state.engine is not None
    and st.session_state.journal is not None
    and st.session_state.connected_account == account_type
)

if not connected:
    st.warning("Connect to your selected account to load live information.")
    st.info(
        "This dashboard supports digit contracts: Over, Under, Matches, "
        "Differs, Even and Odd, where available for a market."
    )
    st.stop()

client = st.session_state.client
engine = st.session_state.engine
journal = st.session_state.journal
balance = st.session_state.balance or {}


# --------------------------------------------------
# ACCOUNT OVERVIEW
# --------------------------------------------------

st.header("Account overview")

if account_type == "real":
    st.warning("REAL ACCOUNT SELECTED — trades can lose real money.")

refresh_col, account_col = st.columns([1, 3])

with refresh_col:
    if st.button("Refresh balance"):
        try:
            st.session_state.balance = client.get_balance(account_type)
            st.rerun()
        except Exception as exc:
            st.error(f"Balance refresh failed: {exc}")

balance = st.session_state.balance or {}
a, b, c = st.columns(3)
a.metric("Selected account", account_type.upper())
b.metric(
    "Balance",
    f"{balance.get('balance', 'Unavailable')} {balance.get('currency', '')}",
)
c.metric("Account ID", str(balance.get("account_id", "Unavailable")))

st.divider()


# --------------------------------------------------
# MARKET SCAN
# --------------------------------------------------

st.header("Volatility market scanner")
st.write(
    "Scan supported Volatility markets and inspect digit frequencies. "
    "A scan alone does not purchase a contract."
)

scan_col, scan_info_col = st.columns([1, 3])

with scan_col:
    scan_clicked = st.button(
        "🔎 Scan digit markets",
        use_container_width=True,
    )

with scan_info_col:
    st.caption(
        "Scanning requests recent ticks and checks which digit contracts "
        "are available. It may take time depending on API response speed."
    )

scan_config = {
    "tick_sample_size": 150,
    "minimum_digit_samples": 80,
    "max_scan_markets": 40,
}

if scan_clicked:
    try:
        with st.spinner("Scanning available Volatility markets..."):
            st.session_state.last_scan_result = engine.scan_markets(scan_config)
        st.session_state.last_cycle_result = None
    except Exception as exc:
        st.error(f"Scan failed: {exc}")

scan_result = st.session_state.last_scan_result

if scan_result:
    st.caption(
        f"Scan time (UTC): {scan_result.get('scan_time', 'Unknown')} · "
        f"Markets analysed: {scan_result.get('markets_analysed', 0)} · "
        f"Candidate setups: {scan_result.get('candidate_count', 0)}"
    )

    market_rows = scan_result.get("results", [])
    if market_rows:
        display_rows = []
        for market in market_rows:
            display_rows.append({
                "Market": market.get("display_name", market.get("symbol")),
                "Symbol": market.get("symbol"),
                "Market type": market.get("market_category"),
                "Latest price": market.get("latest_price"),
                "Samples": market.get("sample_size"),
                "Momentum": market.get("momentum"),
                "Digit contracts available": ", ".join(
                    market.get("supported_digit_contracts", [])
                ),
            })

        st.subheader("Scanned markets")
        st.dataframe(
            pd.DataFrame(display_rows),
            use_container_width=True,
            hide_index=True,
        )

        selected_market_symbol = st.selectbox(
            "Inspect digit frequencies for a market",
            options=[m["symbol"] for m in market_rows],
            format_func=lambda symbol: next(
                (
                    f"{m.get('display_name', symbol)} ({symbol})"
                    for m in market_rows if m["symbol"] == symbol
                ),
                symbol,
            ),
        )

        selected_market = next(
            m for m in market_rows if m["symbol"] == selected_market_symbol
        )
        digit_rows = selected_market.get("digit_counts", [])

        st.subheader(f"Last-digit frequencies — {selected_market_symbol}")
        if digit_rows:
            digit_frame = pd.DataFrame(digit_rows)
            st.dataframe(
                digit_frame,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No digit-frequency rows were returned for this market.")

    candidate_rows = scan_result.get("candidates", [])
    if candidate_rows:
        st.subheader("Candidate setups")
        candidate_frame = pd.DataFrame([
            {
                "Market": row.get("symbol"),
                "Contract": row.get("description"),
                "Type": row.get("contract_type"),
                "Barrier": row.get("barrier"),
                "Observed frequency": round(
                    float(row.get("observed_probability", 0)), 4
                ),
                "Samples": row.get("sample_size"),
            }
            for row in candidate_rows[:100]
        ])
        st.dataframe(
            candidate_frame,
            use_container_width=True,
            hide_index=True,
        )
        st.caption(
            "These are historical sample frequencies, not reliable predictions "
            "or proof of a profitable trade."
        )
    else:
        st.info("No candidate setups were returned by the scan.")

    scan_errors = scan_result.get("errors", {})
    if scan_errors:
        with st.expander(f"Scan issues ({len(scan_errors)})"):
            st.json(scan_errors)
else:
    st.info("Run a scan to load digit-market statistics.")


# --------------------------------------------------
# TRADING CONTROLS
# --------------------------------------------------

st.divider()
st.header("Digit trading settings")

with st.form("digit_settings"):
    left, right = st.columns(2)

    with left:
        stake = st.number_input(
            "Stake per trade",
            min_value=0.35,
            value=1.0,
            step=0.25,
            format="%.2f",
        )
        max_price = st.number_input(
            "Maximum purchase price",
            min_value=0.35,
            value=1.0,
            step=0.25,
            format="%.2f",
        )
        duration = st.number_input(
            "Contract duration",
            min_value=1,
            value=1,
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

    with right:
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

    save_settings = st.form_submit_button("Apply settings")

    if save_settings:
        st.session_state["digit_config"] = {
            "stake": float(stake),
            "max_stake": float(max_price),
            "duration": int(duration),
            "duration_unit": duration_unit,
            "daily_loss_limit": float(daily_loss_limit),
            "max_open_trades": int(max_open_trades),
            "cooldown_seconds": int(cooldown_seconds),
            "loss_cooldown_seconds": int(loss_cooldown_seconds),
        }
        st.success("Settings applied.")

settings = st.session_state.get("digit_config", {
    "stake": 1.0,
    "max_stake": 1.0,
    "duration": 1,
    "duration_unit": "t",
    "daily_loss_limit": 5.0,
    "max_open_trades": 1,
    "cooldown_seconds": 60,
    "loss_cooldown_seconds": 300,
})

st.caption(
    f"Current settings: stake {settings['stake']:.2f}, maximum purchase "
    f"{settings['max_stake']:.2f}, duration {settings['duration']} "
    f"{settings['duration_unit']}."
)


# --------------------------------------------------
# AUTOMATION
# --------------------------------------------------

st.divider()
st.header("Automation controls")

if account_type == "real":
    st.error(
        "Real-account mode can spend real money. Verify the selected "
        "account, stake and risk limits before enabling it."
    )

start_col, stop_col, cycle_col = st.columns(3)

with start_col:
    if st.button("▶ Enable automation", type="primary", use_container_width=True):
        if account_type == "real" and not real_confirm:
            st.error("Confirm the Real-account risk warning first.")
        elif settings["stake"] > settings["max_stake"]:
            st.error("Stake cannot exceed maximum purchase price.")
        elif settings["stake"] > float(balance.get("balance", 0)):
            st.error("Stake exceeds the displayed account balance.")
        elif not scan_result:
            st.error("Scan markets first so the bot has current market data.")
        else:
            engine.running = True
            st.success(
                "Automation enabled. The engine runs only when a cycle is "
                "explicitly triggered; this page does not run continuously "
                "in the background."
            )
            st.rerun()

with stop_col:
    if st.button("■ Stop automation", use_container_width=True):
        engine.running = False
        st.warning(
            "New purchases are disabled. Already purchased contracts may "
            "remain open until settled."
        )
        st.rerun()

with cycle_col:
    run_cycle_clicked = st.button(
        "Run one bot cycle",
        use_container_width=True,
    )

if run_cycle_clicked:
    config = {
        **settings,
        "account_type": account_type,
        "allow_real": account_type == "real" and real_confirm,
        "currency": balance.get("currency"),
        "tick_sample_size": 150,
        "minimum_digit_samples": 80,
        "max_scan_markets": 40,
        "proposal_checks_per_cycle": 8,
        "minimum_observed_probability": 0.0,
        "minimum_estimated_edge": 0.02,
    }

    if not engine.running:
        st.warning("Automation is stopped. No new trade will be attempted.")
    elif account_type == "real" and not real_confirm:
        st.error("Real-account confirmation is required.")
    else:
        with st.spinner("Running one engine cycle..."):
            st.session_state.last_cycle_result = engine.run_cycle(config)

cycle_result = st.session_state.last_cycle_result or {}

status_col1, status_col2, status_col3 = st.columns(3)
status_col1.metric(
    "Automation",
    "ENABLED" if engine.running else "STOPPED",
)
status_col2.metric("Selected account", account_type.upper())
status_col3.metric(
    "Open recorded trades",
    journal.summary(account_type=account_type).get("open_trades", 0),
)

st.write("**Latest action:**", engine.last_action)
st.write("**Latest signal:**", engine.last_signal)

if engine.last_error:
    st.error(engine.last_error)

trade = cycle_result.get("trade")
if trade and trade.get("contract_id"):
    st.success(
        f"Purchase confirmed by the engine: contract {trade['contract_id']}"
    )

if cycle_result.get("error"):
    st.error(cycle_result["error"])


# --------------------------------------------------
# TRADE HISTORY
# --------------------------------------------------

st.divider()
st.header(f"Trade history — {account_type.upper()}")

try:
    summary = journal.summary(account_type=account_type)
    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric("Total trades", summary.get("total_trades", 0))
    c2.metric("Open", summary.get("open_trades", 0))
    c3.metric("Wins", summary.get("wins", 0))
    c4.metric("Losses", summary.get("losses", 0))
    c5.metric(
        "Net P/L",
        f"{summary.get('total_profit_loss', 0.0):.2f}",
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
        st.info("No trades have been recorded for this account.")
except Exception as exc:
    st.error(f"Could not load trade history: {exc}")


st.caption(
    "Historical digit frequencies do not guarantee future outcomes. "
    "This interface does not guarantee profitability. Do not use Real "
    "money until the code, API compatibility, risk controls and settlement "
    "tracking have been tested on Demo."
)
