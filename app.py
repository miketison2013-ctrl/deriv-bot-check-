import time

import pandas as pd
import streamlit as st

from deriv_client import DerivClient
from trade_journal import TradeJournal
from trading_engine import TradingEngine


st.set_page_config(
    page_title="Deriv Digit Bot",
    page_icon="📊",
    layout="wide",
)

st.title("Deriv Volatility Digit Bot")
st.caption("Automatic digit-market scanning · Ranking · Risk controls")

DEFAULTS = {
    "client": None,
    "engine": None,
    "journal": None,
    "connected_account": None,
    "balance": {},
    "connection_error": "",
    "connection_message": "",
    "last_scan_result": None,
    "last_cycle_result": None,
    "session_start_pl": 0.0,
    "session_tp": 5.0,
    "session_sl": 5.0,
    "session_limits": {},
    "config": {
        "stake": 0.35,
        "max_stake": 0.35,
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
        st.session_state[key] = (
            value.copy() if isinstance(value, dict) else value
        )


def stop_bot():
    engine = st.session_state.engine
    if engine is not None:
        engine.running = False


def money(value, currency=""):
    try:
        return f"{float(value):,.2f} {currency}".strip()
    except (TypeError, ValueError):
        return f"Unavailable {currency}".strip()


def reset_connection():
    stop_bot()
    st.session_state.client = None
    st.session_state.engine = None
    st.session_state.journal = None
    st.session_state.connected_account = None
    st.session_state.balance = {}
    st.session_state.last_scan_result = None
    st.session_state.last_cycle_result = None


def session_net_pl(account_type):
    """Calculate realised P/L since the current session started."""
    journal = st.session_state.journal
    if journal is None:
        return 0.0

    summary = journal.summary(account_type=account_type)
    current = float(summary.get("total_profit_loss", 0.0) or 0.0)
    baseline = st.session_state.session_start_pl
    return current - baseline


# --------------------------------------------------
# CONNECTION
# --------------------------------------------------

st.sidebar.header("Deriv connection")

app_id = st.sidebar.text_input(
    "App ID",
    key="app_id_input",
)

token = st.sidebar.text_input(
    "API token",
    type="password",
    key="token_input",
)

account_type = st.sidebar.radio(
    "Trading account",
    ["demo", "real"],
    format_func=lambda x: "Demo account" if x == "demo" else "REAL account",
    key="account_type_input",
)

real_confirm = False
if account_type == "real":
    real_confirm = st.sidebar.checkbox(
        "I understand that real-money trades can lose money."
    )

if (
    st.session_state.client is not None
    and st.session_state.connected_account != account_type
):
    reset_connection()
    st.session_state.connection_message = (
        "Account selection changed. Connect to the selected account again."
    )

if st.sidebar.button("Connect / reconnect", use_container_width=True):
    if not app_id.strip() or not token.strip():
        st.session_state.connection_error = "Enter your App ID and API token."
    elif account_type == "real" and not real_confirm:
        st.session_state.connection_error = (
            "Confirm the Real-account risk warning first."
        )
    else:
        try:
            client = DerivClient(
                api_token=token.strip(),
                app_id=app_id.strip(),
            )

            with st.spinner("Connecting to Deriv..."):
                balance = client.get_balance(account_type)

            journal = TradeJournal("trade_journal.db")
            engine = TradingEngine(client, journal)

            st.session_state.client = client
            st.session_state.engine = engine
            st.session_state.journal = journal
            st.session_state.connected_account = account_type
            st.session_state.balance = balance
            st.session_state.last_scan_result = None
            st.session_state.last_cycle_result = None
            st.session_state.connection_error = ""
            st.session_state.connection_message = (
                f"Connected to {account_type.upper()}."
            )

            summary = journal.summary(account_type=account_type)
            st.session_state.session_start_pl = float(
                summary.get("total_profit_loss", 0.0) or 0.0
            )
            st.session_state.session_limits = {}

            st.rerun()

        except Exception as exc:
            st.session_state.connection_error = str(exc)

if st.session_state.connection_error:
    st.sidebar.error(st.session_state.connection_error)

if st.session_state.connection_message:
    st.sidebar.success(st.session_state.connection_message)

if st.session_state.client is None:
    st.info("Connect to your selected Deriv account to continue.")
    st.stop()

client = st.session_state.client
engine = st.session_state.engine
journal = st.session_state.journal
balance = st.session_state.balance or {}
currency = balance.get("currency", "")

if st.session_state.connected_account != account_type:
    st.warning("Reconnect to the currently selected account.")
    st.stop()

if account_type == "real":
    st.error("REAL ACCOUNT SELECTED — real-money losses are possible.")

# --------------------------------------------------
# ACCOUNT OVERVIEW
# --------------------------------------------------

st.header("Account overview")

left, middle, right = st.columns(3)
left.metric("Selected account", account_type.upper())
middle.metric("Balance", money(balance.get("balance"), currency))
right.metric("Account ID", str(balance.get("account_id", "Unavailable")))

if st.button("Refresh selected balance"):
    try:
        st.session_state.balance = client.get_balance(account_type)
        st.rerun()
    except Exception as exc:
        st.error(f"Balance refresh failed: {exc}")

with st.expander("Check other account balance"):
    other_account = "real" if account_type == "demo" else "demo"
    if st.button(f"Load {other_account.upper()} balance"):
        try:
            other_balance = client.get_balance(other_account)
            st.write(
                f"{other_account.upper()}: "
                f"{money(other_balance.get('balance'), other_balance.get('currency', ''))}"
            )
            st.caption(
                f"Account ID: {other_balance.get('account_id', 'Unavailable')}"
            )
        except Exception as exc:
            st.error(f"Could not load {other_account} balance: {exc}")

st.divider()

# --------------------------------------------------
# TRADE SETTINGS
# --------------------------------------------------

st.header("Trade settings")

cfg = st.session_state.config

with st.form("trade_settings"):
    col1, col2 = st.columns(2)

    with col1:
        stake = st.number_input(
            "Stake per trade",
            min_value=0.35,
            value=float(cfg["stake"]),
            step=0.05,
        )
        max_stake = st.number_input(
            "Maximum purchase price",
            min_value=0.35,
            value=float(cfg["max_stake"]),
            step=0.05,
        )
        duration = st.number_input(
            "Contract duration",
            min_value=1,
            value=int(cfg["duration"]),
            step=1,
        )
        duration_unit = st.selectbox(
            "Duration unit",
            ["t", "s", "m"],
            index=["t", "s", "m"].index(cfg["duration_unit"]),
            format_func=lambda x: {
                "t": "Ticks",
                "s": "Seconds",
                "m": "Minutes",
            }[x],
        )

    with col2:
        take_profit = st.number_input(
            "Session Take Profit",
            min_value=0.01,
            value=float(st.session_state.session_tp),
            step=0.5,
            help="Stop opening new trades when session realised profit reaches this amount.",
        )
        stop_loss = st.number_input(
            "Session Stop Loss",
            min_value=0.01,
            value=float(st.session_state.session_sl),
            step=0.5,
            help="Stop opening new trades when session realised loss reaches this amount.",
        )
        daily_loss_limit = st.number_input(
            "Daily loss limit",
            min_value=0.35,
            value=float(cfg["daily_loss_limit"]),
            step=0.5,
        )
        max_open_trades = st.number_input(
            "Maximum open trades",
            min_value=1,
            max_value=10,
            value=int(cfg["max_open_trades"]),
            step=1,
        )
        cooldown_seconds = st.number_input(
            "Seconds between entries",
            min_value=0,
            value=int(cfg["cooldown_seconds"]),
            step=10,
        )
        loss_cooldown_seconds = st.number_input(
            "Pause after a loss (seconds)",
            min_value=0,
            value=int(cfg["loss_cooldown_seconds"]),
            step=30,
        )

    saved = st.form_submit_button("Save trade settings")

if saved:
    if stake > max_stake:
        st.error("Stake cannot exceed maximum purchase price.")
    else:
        st.session_state.config = {
            "stake": float(stake),
            "max_stake": float(max_stake),
            "duration": int(duration),
            "duration_unit": duration_unit,
            "daily_loss_limit": float(daily_loss_limit),
            "max_open_trades": int(max_open_trades),
            "cooldown_seconds": int(cooldown_seconds),
            "loss_cooldown_seconds": int(loss_cooldown_seconds),
        }
        st.session_state.session_tp = float(take_profit)
        st.session_state.session_sl = float(stop_loss)
        st.success("Trade settings saved.")

cfg = st.session_state.config
st.caption(
    f"Stake: {cfg['stake']:.2f} {currency} · "
    f"TP: {st.session_state.session_tp:.2f} {currency} · "
    f"SL: {st.session_state.session_sl:.2f} {currency}"
)

st.divider()

# --------------------------------------------------
# BOT CONTROLS
# --------------------------------------------------

st.header("Bot controls")

running = bool(engine.running)

start_col, stop_col = st.columns(2)

with start_col:
    start_clicked = st.button(
        "▶ START BOT",
        type="primary",
        disabled=running,
        use_container_width=True,
    )

with stop_col:
    stop_clicked = st.button(
        "■ STOP BOT",
        disabled=not running,
        use_container_width=True,
    )

if stop_clicked:
    stop_bot()
    st.session_state.connection_message = (
        "Bot stopped. New trades will not be initiated. "
        "Check open positions below; some contracts may remain open."
    )
    st.rerun()

if start_clicked:
    if account_type == "real" and not real_confirm:
        st.error("Confirm Real-account risk before starting.")
    elif cfg["stake"] > float(balance.get("balance", 0)):
        st.error("Stake exceeds the available account balance.")
    else:
        engine.running = True
        engine.last_error = ""
        st.session_state.session_limits[account_type] = False
        st.session_state.session_start_pl = float(
            journal.summary(account_type=account_type).get(
                "total_profit_loss", 0.0
            ) or 0.0
        )
        st.session_state.connection_message = "Bot started."
        st.rerun()

# --------------------------------------------------
# CONTINUOUS TRADING CYCLE
# --------------------------------------------------

if engine.running:
    try:
        # Monitor settlements before checking session limits.
        engine.monitor_open_trades(account_type)

        net_pl = session_net_pl(account_type)
        tp = float(st.session_state.session_tp)
        sl = float(st.session_state.session_sl)

        if net_pl >= tp:
            engine.running = False
            st.session_state.session_limits[account_type] = True
            st.warning(
                f"Take Profit reached ({money(net_pl, currency)}). "
                "New trades stopped."
            )

        elif net_pl <= -sl:
            engine.running = False
            st.session_state.session_limits[account_type] = True
            st.warning(
                f"Stop Loss reached ({money(net_pl, currency)}). "
                "New trades stopped."
            )

        elif account_type == "real" and not real_confirm:
            engine.running = False
            st.error("Real-account confirmation is missing. Bot stopped.")

        else:
            cycle_config = {
                **cfg,
                "account_type": account_type,
                "allow_real": account_type == "real" and real_confirm,
                "currency": currency,
                "tick_sample_size": 150,
                "minimum_digit_samples": 80,
                "max_scan_markets": 40,
                "proposal_checks_per_cycle": 8,
                "minimum_observed_probability": 0.0,
                "minimum_estimated_edge": 0.02,
            }

            with st.spinner("Scanning markets and checking ranked setups..."):
                scan_result = engine.scan_markets(cycle_config)
                st.session_state.last_scan_result = scan_result

                # run_cycle scans internally too; this preserves its existing
                # proposal, purchase, journal, and risk-check flow.
                cycle_result = engine.run_cycle(cycle_config)
                st.session_state.last_cycle_result = cycle_result

    except Exception as exc:
        engine.running = False
        engine.last_error = str(exc)
        st.error(f"Bot stopped because of an error: {exc}")

if engine.running:
    st.info(
        "Bot is running. The page refreshes automatically to continue scanning. "
        "Use STOP BOT to prevent further entries."
    )
    time.sleep(3)
    st.rerun()

# --------------------------------------------------
# STATUS
# --------------------------------------------------

st.subheader("Bot status")

status1, status2, status3 = st.columns(3)
status1.metric("Status", "RUNNING" if engine.running else "STOPPED")
status2.metric("Account", account_type.upper())

try:
    summary = journal.summary(account_type=account_type)
    status3.metric("Open trades", summary.get("open_trades", 0))
except Exception:
    status3.metric("Open trades", "Unavailable")

try:
    current_net = session_net_pl(account_type)
    st.metric("Session realised P/L", money(current_net, currency))
except Exception as exc:
    st.warning(f"Could not calculate session P/L: {exc}")

st.write("**Latest action:**", getattr(engine, "last_action", "Ready"))
st.write("**Latest signal:**", getattr(engine, "last_signal", "WAIT"))

if getattr(engine, "last_error", ""):
    st.error(engine.last_error)

cycle_result = st.session_state.last_cycle_result or {}
if cycle_result.get("error"):
    st.error(cycle_result["error"])

st.divider()

# --------------------------------------------------
# MARKET SCAN RESULTS
# --------------------------------------------------

st.header("Market scanner")

scan = st.session_state.last_scan_result

if scan:
    st.caption(
        f"Markets analysed: {scan.get('markets_analysed', 0)} · "
        f"Candidate setups: {scan.get('candidate_count', 0)} · "
        f"Time: {scan.get('scan_time', 'Unknown')}"
    )

    rows = scan.get("results", [])
    if rows:
        st.dataframe(
            pd.DataFrame([
                {
                    "Market": item.get("display_name", item.get("symbol")),
                    "Symbol": item.get("symbol"),
                    "Latest price": item.get("latest_price"),
                    "Samples": item.get("sample_size"),
                    "Momentum": item.get("momentum"),
                    "Contracts": ", ".join(
                        item.get("supported_digit_contracts", [])
                    ),
                }
                for item in rows
            ]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.warning("No markets passed scanner validation.")

    candidates = scan.get("candidates", [])
    if candidates:
        st.subheader("Ranked digit setups")
        st.dataframe(
            pd.DataFrame([
                {
                    "Market": item.get("symbol"),
                    "Setup": item.get("description"),
                    "Contract": item.get("contract_type"),
                    "Barrier": item.get("barrier"),
                    "Observed frequency": item.get("observed_probability"),
                    "Samples": item.get("sample_size"),
                }
                for item in candidates[:100]
            ]),
            use_container_width=True,
            hide_index=True,
        )

    errors = scan.get("errors", {})
    if errors:
        with st.expander(f"Scanner errors ({len(errors)})"):
            st.json(errors)
else:
    st.info("Start the bot to scan and rank markets automatically.")

st.divider()

# --------------------------------------------------
# TRADE HISTORY
# --------------------------------------------------

st.header(f"Trade history — {account_type.upper()}")

try:
    summary = journal.summary(account_type=account_type)
    trades = journal.list_trades(limit=200, account_type=account_type)

    a, b, c, d, e = st.columns(5)
    a.metric("Total trades", summary.get("total_trades", 0))
    b.metric("Open", summary.get("open_trades", 0))
    c.metric("Wins", summary.get("wins", 0))
    d.metric("Losses", summary.get("losses", 0))
    e.metric(
        "Net P/L",
        money(summary.get("total_profit_loss", 0), currency),
    )

    if trades:
        st.dataframe(
            pd.DataFrame(trades),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No trades recorded yet.")

except Exception as exc:
    st.error(f"Could not load trade history: {exc}")

st.caption(
    "Important: TP and SL stop new entries based on realised session P/L. "
    "They do not guarantee that open contracts can be sold at a target price. "
    "Stopping the bot does not automatically close every open Deriv contract. "
    "Verify all behavior on Demo before using a Real account."
)
