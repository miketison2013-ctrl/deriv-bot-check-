
import streamlit as st
import pandas as pd

from deriv_client import DerivClient
from trade_journal import TradeJournal
from trading_engine import TradingEngine


st.set_page_config(
    page_title="Deriv Volatility Digit Bot",
    page_icon="📊",
    layout="wide",
)

st.title("📊 Deriv Volatility Digit Bot")
st.caption("Digit contracts · Market scanner · Risk controls · Trade journal")

DEFAULTS = {
    "client": None,
    "engine": None,
    "journal": None,
    "connected_account": None,
    "balance": {},
    "account_balances": {},
    "connection_error": "",
    "connection_message": "",
    "last_scan_result": None,
    "last_cycle_result": None,
    "digit_config": {
        "stake": 1.0,
        "max_stake": 1.0,
        "duration": 1,
        "duration_unit": "t",
        "daily_loss_limit": 5.0,
        "max_open_trades": 1,
        "cooldown_seconds": 60,
        "loss_cooldown_seconds": 300,
    },
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value.copy() if isinstance(value, dict) else value


def stop_engine():
    engine = st.session_state.get("engine")
    if engine is not None:
        engine.running = False


def reset_connection():
    stop_engine()
    st.session_state.client = None
    st.session_state.engine = None
    st.session_state.journal = None
    st.session_state.connected_account = None
    st.session_state.balance = {}
    st.session_state.account_balances = {}
    st.session_state.last_scan_result = None
    st.session_state.last_cycle_result = None


def money(value, currency=""):
    try:
        return f"{float(value):,.2f} {currency}".strip()
    except (TypeError, ValueError):
        return f"Unavailable {currency}".strip()


def show_error(prefix, exc):
    st.error(f"{prefix}: {exc}")


# --------------------------------------------------
# SIDEBAR: CONNECTION
# --------------------------------------------------

st.sidebar.header("Deriv connection")

app_id = st.sidebar.text_input(
    "App ID",
    key="app_id_input",
    help="Enter your Deriv application ID.",
)

token = st.sidebar.text_input(
    "Personal Access Token",
    type="password",
    key="token_input",
    help="Never share or commit your token.",
)

account_type = st.sidebar.radio(
    "Account used for trading",
    ["demo", "real"],
    format_func=lambda x: "Demo account" if x == "demo" else "REAL account",
    key="account_type_input",
)

real_confirm = False
if account_type == "real":
    real_confirm = st.sidebar.checkbox(
        "I understand real-money trades can lose money.",
        key="real_trading_confirmation",
    )

if (
    st.session_state.client is not None
    and st.session_state.connected_account != account_type
):
    reset_connection()
    st.session_state.connection_message = (
        "Account selection changed. Connect again to the selected account."
    )

if st.sidebar.button("Connect / reconnect", type="primary", use_container_width=True):
    if not app_id.strip() or not token.strip():
        st.session_state.connection_error = "Enter both App ID and token."
    elif account_type == "real" and not real_confirm:
        st.session_state.connection_error = "Confirm the Real-account risk warning."
    else:
        try:
            # Constructor order: API token first, App ID second.
            client = DerivClient(
                api_token=token.strip(),
                app_id=app_id.strip(),
            )

            with st.spinner("Checking selected Deriv account..."):
                balance = client.get_balance(account_type)

            journal = TradeJournal("trade_journal.db")
            engine = TradingEngine(client, journal)

            st.session_state.client = client
            st.session_state.engine = engine
            st.session_state.journal = journal
            st.session_state.connected_account = account_type
            st.session_state.balance = balance
            st.session_state.account_balances = {
                account_type: balance,
            }
            st.session_state.last_scan_result = None
            st.session_state.last_cycle_result = None
            st.session_state.connection_error = ""
            st.session_state.connection_message = (
                f"Connected to {account_type.upper()} account."
            )
            st.rerun()

        except Exception as exc:
            st.session_state.connection_error = str(exc)

if st.session_state.connection_error:
    st.sidebar.error(st.session_state.connection_error)

if st.session_state.connection_message:
    st.sidebar.success(st.session_state.connection_message)

st.sidebar.caption(
    "Your token stays in the password field. Do not put it in GitHub code."
)

connected = (
    st.session_state.client is not None
    and st.session_state.engine is not None
    and st.session_state.journal is not None
    and st.session_state.connected_account == account_type
)

if not connected:
    st.warning("Connect to your selected account to load balances and market data.")
    st.info(
        "The bot focuses on digit contracts: Over, Under, Matches, "
        "Differs, Even and Odd, where supported."
    )
    st.stop()

client = st.session_state.client
engine = st.session_state.engine
journal = st.session_state.journal


# --------------------------------------------------
# ACCOUNT BALANCES
# --------------------------------------------------

st.header("Account overview")

if account_type == "real":
    st.warning("REAL ACCOUNT SELECTED — real-money losses are possible.")

balance_col, refresh_col = st.columns([3, 1])

with refresh_col:
    if st.button("Refresh selected balance", use_container_width=True):
        try:
            new_balance = client.get_balance(account_type)
            st.session_state.balance = new_balance
            st.session_state.account_balances[account_type] = new_balance
            st.rerun()
        except Exception as exc:
            show_error("Balance refresh failed", exc)

balance = st.session_state.balance or {}
currency = balance.get("currency", "")

with balance_col:
    a, b, c = st.columns(3)
    a.metric("Selected account", account_type.upper())
    b.metric("Balance", money(balance.get("balance"), currency))
    c.metric(
        "Account ID",
        str(balance.get("account_id", "Unavailable")),
    )

with st.expander("Check Demo and Real balances"):
    st.caption(
        "Each balance request uses the token currently entered. "
        "The token must have access to the account being checked."
    )

    demo_col, real_col = st.columns(2)

    with demo_col:
        if st.button("Load Demo balance", use_container_width=True):
            try:
                result = client.get_balance("demo")
                st.session_state.account_balances["demo"] = result
            except Exception as exc:
                show_error("Demo balance failed", exc)

        demo_balance = st.session_state.account_balances.get("demo")
        if demo_balance:
            st.metric(
                "Demo balance",
                money(
                    demo_balance.get("balance"),
                    demo_balance.get("currency", ""),
                ),
            )
            st.caption(
                f"Account ID: {demo_balance.get('account_id', 'Unavailable')}"
            )

    with real_col:
        if st.button("Load Real balance", use_container_width=True):
            try:
                result = client.get_balance("real")
                st.session_state.account_balances["real"] = result
            except Exception as exc:
                show_error("Real balance failed", exc)

        real_balance = st.session_state.account_balances.get("real")
        if real_balance:
            st.metric(
                "Real balance",
                money(
                    real_balance.get("balance"),
                    real_balance.get("currency", ""),
                ),
            )
            st.caption(
                f"Account ID: {real_balance.get('account_id', 'Unavailable')}"
            )

st.divider()


# --------------------------------------------------
# MARKET SCANNER
# --------------------------------------------------

st.header("Volatility digit market scanner")
st.write(
    "Scan available Volatility markets, recent prices, digit frequencies "
    "and supported digit contracts. Scanning does not place a trade."
)

scan_col, scan_help_col = st.columns([1, 3])

with scan_col:
    scan_clicked = st.button(
        "🔎 Scan markets",
        type="primary",
        use_container_width=True,
    )

with scan_help_col:
    st.caption(
        "A scan requests recent ticks and checks available digit contracts. "
        "It may take time depending on the number of markets."
    )

scan_config = {
    "tick_sample_size": 150,
    "minimum_digit_samples": 80,
    "max_scan_markets": 40,
}

if scan_clicked:
    try:
        with st.spinner("Scanning Volatility markets..."):
            st.session_state.last_scan_result = engine.scan_markets(scan_config)
        st.session_state.last_cycle_result = None
    except Exception as exc:
        show_error("Market scan failed", exc)

scan_result = st.session_state.last_scan_result

if scan_result:
    st.caption(
        f"Scan time: {scan_result.get('scan_time', 'Unknown')} · "
        f"Markets analysed: {scan_result.get('markets_analysed', 0)} · "
        f"Candidate setups: {scan_result.get('candidate_count', 0)}"
    )

    market_rows = scan_result.get("results", [])

    if market_rows:
        market_frame = pd.DataFrame([
            {
                "Rank": index + 1,
                "Market": market.get(
                    "display_name", market.get("symbol", "")
                ),
                "Symbol": market.get("symbol"),
                "Latest price": market.get("latest_price"),
                "Samples": market.get("sample_size"),
                "Momentum": market.get("momentum"),
                "Supported digit contracts": ", ".join(
                    market.get("supported_digit_contracts", [])
                ),
            }
            for index, market in enumerate(market_rows)
        ])

        st.subheader("Ranked scan results")
        st.dataframe(
            market_frame,
            use_container_width=True,
            hide_index=True,
        )

        symbols = [
            market.get("symbol")
            for market in market_rows
            if market.get("symbol")
        ]

        if symbols:
            selected_symbol = st.selectbox(
                "Inspect last-digit frequencies",
                symbols,
                format_func=lambda symbol: next(
                    (
                        f"{market.get('display_name', symbol)} ({symbol})"
                        for market in market_rows
                        if market.get("symbol") == symbol
                    ),
                    symbol,
                ),
            )

            selected_market = next(
                (
                    market for market in market_rows
                    if market.get("symbol") == selected_symbol
                ),
                {},
            )

            digit_rows = selected_market.get("digit_counts", [])
            if digit_rows:
                st.dataframe(
                    pd.DataFrame(digit_rows),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No digit-frequency data for this market.")

    candidate_rows = scan_result.get("candidates", [])

    st.subheader("Candidate digit setups")
    if candidate_rows:
        candidate_frame = pd.DataFrame([
            {
                "Market": row.get("symbol"),
                "Setup": row.get("description"),
                "Contract type": row.get("contract_type"),
                "Barrier": row.get("barrier"),
                "Observed frequency": row.get("observed_probability"),
                "Samples": row.get("sample_size"),
            }
            for row in candidate_rows[:100]
        ])
        st.dataframe(
            candidate_frame,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No eligible candidate setups were returned.")

    errors = scan_result.get("errors", {})
    if errors:
        with st.expander(f"Scan errors ({len(errors)})"):
            st.json(errors)

    st.caption(
        "Historical frequencies are not guarantees of future outcomes "
        "and do not establish that a setup is profitable."
    )
else:
    st.info("Scan markets to view current analysis.")

st.divider()


# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

st.header("Trading settings")

with st.form("digit_settings"):
    left, right = st.columns(2)

    with left:
        stake = st.number_input(
            "Stake per trade",
            min_value=0.35,
            value=float(st.session_state.digit_config["stake"]),
            step=0.25,
            format="%.2f",
        )
        max_price = st.number_input(
            "Maximum purchase price",
            min_value=0.35,
            value=float(st.session_state.digit_config["max_stake"]),
            step=0.25,
            format="%.2f",
        )
        duration = st.number_input(
            "Contract duration",
            min_value=1,
            value=int(st.session_state.digit_config["duration"]),
            step=1,
        )
        duration_unit = st.selectbox(
            "Duration unit",
            ["t", "s", "m"],
            index=["t", "s", "m"].index(
                st.session_state.digit_config["duration_unit"]
                if st.session_state.digit_config["duration_unit"] in ("t", "s", "m")
                else "t"
            ),
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
            value=float(st.session_state.digit_config["daily_loss_limit"]),
            step=0.5,
            format="%.2f",
        )
        max_open_trades = st.number_input(
            "Maximum open trades",
            min_value=1,
            max_value=10,
            value=int(st.session_state.digit_config["max_open_trades"]),
            step=1,
        )
        cooldown_seconds = st.number_input(
            "Seconds between entries",
            min_value=0,
            value=int(st.session_state.digit_config["cooldown_seconds"]),
            step=10,
        )
        loss_cooldown_seconds = st.number_input(
            "Pause after a loss (seconds)",
            min_value=0,
            value=int(st.session_state.digit_config["loss_cooldown_seconds"]),
            step=30,
        )

    settings_saved = st.form_submit_button("Apply settings")

if settings_saved:
    st.session_state.digit_config = {
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

settings = st.session_state.digit_config

st.caption(
    f"Stake: {settings['stake']:.2f} {currency} · "
    f"Max purchase price: {settings['max_stake']:.2f} {currency} · "
    f"Duration: {settings['duration']} {settings['duration_unit']}"
)

st.divider()


# --------------------------------------------------
# AUTOMATION
# --------------------------------------------------

st.header("Bot controls")

if account_type == "real":
    st.error(
        "REAL ACCOUNT: only enable trading after successful Demo testing "
        "and checking every risk setting."
    )

start_col, stop_col, cycle_col = st.columns(3)

with start_col:
    start_clicked = st.button(
        "▶ Start bot",
        type="primary",
        use_container_width=True,
    )

with stop_col:
    stop_clicked = st.button(
        "■ Stop bot",
        use_container_width=True,
    )

with cycle_col:
    cycle_clicked = st.button(
        "Run one cycle",
        use_container_width=True,
    )

if stop_clicked:
    engine.running = False
    st.session_state.connection_message = (
        "Bot stopped. Already purchased contracts may remain open."
    )
    st.rerun()

if start_clicked:
    if account_type == "real" and not real_confirm:
        st.error("Confirm the Real-account warning first.")
    elif not scan_result:
        st.error("Scan markets before enabling the bot.")
    elif settings["stake"] > settings["max_stake"]:
        st.error("Stake cannot exceed maximum purchase price.")
    elif settings["stake"] > float(balance.get("balance", 0)):
        st.error("Stake exceeds the selected account balance.")
    else:
        engine.running = True
        engine.last_error = ""
        st.session_state.connection_message = (
            "Bot enabled. Use Run one cycle to execute one engine cycle."
        )
        st.rerun()

if cycle_clicked:
    if not engine.running:
        st.warning("The bot is stopped. Start it before running a cycle.")
    elif account_type == "real" and not real_confirm:
        st.error("Real-account confirmation is required.")
    elif settings["stake"] > settings["max_stake"]:
        st.error("Stake cannot exceed maximum purchase price.")
    else:
        cycle_config = {
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
        try:
            with st.spinner("Running one engine cycle..."):
                st.session_state.last_cycle_result = engine.run_cycle(
                    cycle_config
                )
        except Exception as exc:
            engine.running = False
            engine.last_error = str(exc)
            st.session_state.last_cycle_result = {"error": str(exc)}

status_a, status_b, status_c = st.columns(3)
status_a.metric(
    "Bot status",
    "RUNNING / ENABLED" if engine.running else "STOPPED",
)
status_b.metric("Trading account", account_type.upper())

try:
    open_count = journal.summary(account_type=account_type).get(
        "open_trades", 0
    )
except Exception:
    open_count = "Unavailable"

status_c.metric("Recorded open trades", open_count)

st.write("**Latest action:**", getattr(engine, "last_action", "Unavailable"))
st.write("**Latest signal:**", getattr(engine, "last_signal", "Unavailable"))

last_error = getattr(engine, "last_error", "")
if last_error:
    st.error(last_error)

cycle_result = st.session_state.last_cycle_result or {}
if cycle_result.get("error"):
    st.error(cycle_result["error"])

trade = cycle_result.get("trade")
if isinstance(trade, dict) and trade.get("contract_id"):
    st.success(
        f"Engine reported contract ID: {trade['contract_id']}"
    )

st.info(
    "This dashboard does not run a continuous background trading loop. "
    "Start enables the engine; Run one cycle performs a single cycle. "
    "Stop prevents further cycles initiated here."
)

st.divider()


# --------------------------------------------------
# TRADE HISTORY
# --------------------------------------------------

st.header(f"Trade history — {account_type.upper()}")

try:
    summary = journal.summary(account_type=account_type)
    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric("Total trades", summary.get("total_trades", 0))
    c2.metric("Open", summary.get("open_trades", 0))
    c3.metric("Wins", summary.get("wins", 0))
    c4.metric("Losses", summary.get("losses", 0))

    net_pl = summary.get("total_profit_loss", 0.0)
    try:
        net_pl_display = f"{float(net_pl):,.2f} {currency}".strip()
    except (TypeError, ValueError):
        net_pl_display = "Unavailable"

    c5.metric("Net P/L", net_pl_display)

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
        st.info("No recorded trades for this account yet.")

except Exception as exc:
    show_error("Could not load trade history", exc)

st.caption(
    "Trading involves risk. Historical digit statistics do not guarantee "
    "future outcomes. Keep the bot stopped until Demo connection, proposals, "
    "purchases, contract settlement, and risk controls have been verified."
)
