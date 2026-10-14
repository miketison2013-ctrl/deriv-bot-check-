import streamlit as st
import pandas as pd
from datetime import datetime, timezone

from deriv_client import DerivClient, DerivAPIError
from trade_journal import TradeJournal


st.set_page_config(
    page_title="Deriv Trading Bot",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Deriv Trading Bot")
st.caption(
    "Live Deriv connection • Account selection • "
    "Contract proposals • Actual trade monitoring"
)

# --------------------------------------------------
# SESSION STATE
# --------------------------------------------------

DEFAULTS = {
    "markets": [],
    "contract_types": {},
    "proposal": None,
    "proposal_settings": None,
    "bot_running": False,
    "connection_ok": False,
    "last_error": None,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# --------------------------------------------------
# CONNECTION
# --------------------------------------------------

with st.sidebar:
    st.header("Deriv connection")

    app_id = st.text_input(
        "Deriv App ID",
        help="Enter your Deriv application ID.",
    )

    token = st.text_input(
        "Personal Access Token",
        type="password",
        help="Keep this private. Never paste it into GitHub code.",
    )

    st.divider()
    st.header("Account selection")

    account_type = st.radio(
        "Choose the account for trading",
        ["demo", "real"],
        format_func=lambda x: (
            "Demo account" if x == "demo"
            else "REAL MONEY account"
        ),
    )

    if account_type == "real":
        st.warning(
            "REAL MONEY: purchases can lose your stake."
        )
        real_confirm = st.checkbox(
            "I understand that this account uses real money."
        )
    else:
        real_confirm = True

    st.divider()
    st.header("Risk limits")

    stake = st.number_input(
        "Stake per trade",
        min_value=0.35,
        value=1.0,
        step=0.25,
    )

    max_stake = st.number_input(
        "Maximum allowed stake",
        min_value=0.35,
        value=1.0,
        step=0.25,
    )

    daily_loss_limit = st.number_input(
        "Daily loss limit (account currency)",
        min_value=0.0,
        value=5.0,
        step=1.0,
    )

    st.caption(
        "These are dashboard safeguards, not a guarantee "
        "that losses cannot exceed the limit."
    )


def make_client():
    if not app_id.strip():
        raise ValueError("Enter your Deriv App ID.")

    if not token.strip():
        raise ValueError("Enter your API token.")

    return DerivClient(app_id.strip(), token.strip())


@st.cache_resource
def get_journal():
    return TradeJournal("trade_journal.db")


journal = get_journal()


# --------------------------------------------------
# ACCOUNT BALANCES
# --------------------------------------------------

st.header("1. Your account balances")

if st.button("Connect and read BOTH balances", type="primary"):
    try:
        client = make_client()

        demo = client.get_balance("demo")
        real = client.get_balance("real")

        st.session_state.demo_balance = demo
        st.session_state.real_balance = real
        st.session_state.connection_ok = True

        st.success("Both account balances were received from Deriv.")

    except Exception as exc:
        st.session_state.connection_ok = False
        st.error(f"Connection failed: {exc}")


left, right = st.columns(2)

demo_balance = st.session_state.get("demo_balance")
real_balance = st.session_state.get("real_balance")

with left:
    st.subheader("Demo")

    if demo_balance:
        st.metric(
            "Demo balance",
            f"{demo_balance['balance']:.2f} "
            f"{demo_balance['currency']}",
        )
        st.caption(
            f"Account ID: {demo_balance['account_id']}"
        )
    else:
        st.info("Connect to read the demo balance.")

with right:
    st.subheader("Real")

    if real_balance:
        st.metric(
            "Real balance",
            f"{real_balance['balance']:.2f} "
            f"{real_balance['currency']}",
        )
        st.caption(
            f"Account ID: {real_balance['account_id']}"
        )
    else:
        st.info("Connect to read the real balance.")


# --------------------------------------------------
# LOAD MARKETS
# --------------------------------------------------

st.divider()
st.header("2. Choose a market")

if st.button("Load available Deriv markets"):
    try:
        client = make_client()
        st.session_state.markets = client.get_active_symbols()
        st.session_state.proposal = None

        st.success(
            f"Loaded {len(st.session_state.markets)} markets."
        )

    except Exception as exc:
        st.error(f"Could not load markets: {exc}")


markets = st.session_state.markets

if not markets:
    st.info("Load the markets before continuing.")
    st.stop()


market_options = {
    f"{item['display_name']} ({item['symbol']})":
        item["symbol"]
    for item in markets
}

selected_market_label = st.selectbox(
    "Market",
    list(market_options.keys()),
)

symbol = market_options[selected_market_label]


# --------------------------------------------------
# CONTRACT TYPES
# --------------------------------------------------

st.header("3. Choose a contract")

if st.button("Load contracts for this market"):
    try:
        client = make_client()

        st.session_state.contract_types = (
            client.get_contract_types(symbol)
        )

        st.session_state.proposal = None

        if st.session_state.contract_types:
            st.success("Available contracts loaded.")
        else:
            st.warning(
                "No supported contract types were returned "
                "for this market."
            )

    except Exception as exc:
        st.error(f"Could not load contracts: {exc}")


contracts = st.session_state.contract_types

if not contracts:
    st.info(
        "Load the contract types for the selected market."
    )
    st.stop()


contract_label = st.selectbox(
    "Contract type",
    list(contracts.keys()),
)

contract_type = contracts[contract_label]


# --------------------------------------------------
# TRADE SETTINGS
# --------------------------------------------------

st.header("4. Configure the trade")

col1, col2, col3 = st.columns(3)

with col1:
    duration = st.number_input(
        "Duration",
        min_value=1,
        value=1,
        step=1,
    )

with col2:
    duration_unit_label = st.selectbox(
        "Duration unit",
        ["Ticks", "Seconds", "Minutes"],
    )

duration_units = {
    "Ticks": "t",
    "Seconds": "s",
    "Minutes": "m",
}

duration_unit = duration_units[duration_unit_label]

with col3:
    if contract_type in (
        "DIGITOVER",
        "DIGITUNDER",
        "DIGITMATCH",
        "DIGITDIFF",
    ):
        barrier = st.selectbox(
            "Barrier digit",
            list(range(10)),
        )
    else:
        barrier = None
        st.write("Barrier")
        st.write("Not required for this contract")


# --------------------------------------------------
# REQUEST LIVE PROPOSAL
# --------------------------------------------------

st.divider()
st.header("5. Request a live proposal")

st.write(
    "This requests an actual price from Deriv. "
    "It does not buy a contract."
)

if stake > max_stake:
    st.error(
        "Your stake is above the maximum stake you configured."
    )

if st.button("Get live proposal", type="primary"):
    if stake > max_stake:
        st.error("Reduce the stake before requesting a trade.")
    elif account_type == "real" and not real_confirm:
        st.error(
            "Confirm that you understand the real-money risk first."
        )
    else:
        try:
            client = make_client()

            selected_balance = client.get_balance(account_type)

            if stake > selected_balance["balance"]:
                raise ValueError(
                    "The stake exceeds the selected account balance."
                )

            proposal = client.get_proposal(
                account_type=account_type,
                symbol=symbol,
                contract_type=contract_type,
                amount=stake,
                currency=selected_balance["currency"],
                duration=int(duration),
                duration_unit=duration_unit,
                barrier=barrier,
            )

            st.session_state.proposal = proposal

            st.session_state.proposal_settings = {
                "account_type": account_type,
                "symbol": symbol,
                "contract_type": contract_type,
                "contract_label": contract_label,
                "stake": float(stake),
                "currency": selected_balance["currency"],
                "duration": int(duration),
                "duration_unit": duration_unit,
                "barrier": barrier,
            }

            st.success("Deriv returned a live proposal.")

        except Exception as exc:
            st.session_state.proposal = None
            st.error(f"Proposal failed: {exc}")


# --------------------------------------------------
# REVIEW AND BUY
# --------------------------------------------------

proposal = st.session_state.proposal
settings = st.session_state.proposal_settings

if proposal and settings:
    st.subheader("Review before buying")

    a, b, c = st.columns(3)

    a.metric(
        "Purchase price",
        f"{proposal['ask_price']:.2f} {proposal['currency']}",
    )

    b.metric(
        "Potential payout",
        f"{proposal['payout']:.2f} {proposal['currency']}",
    )

    c.metric(
        "Account",
        settings["account_type"].upper(),
    )

    st.write(f"Market: `{settings['symbol']}`")
    st.write(f"Contract: `{settings['contract_label']}`")
    st.write(f"Duration: {settings['duration']} {settings['duration_unit']}")
    st.write(f"Stake: {settings['stake']} {settings['currency']}")

    st.warning(
        "The payout is conditional, not guaranteed profit. "
        "You can lose the stake."
    )

    if settings["account_type"] == "real":
        st.error(
            "REAL-MONEY PURCHASE: check every detail before confirming."
        )

    confirm_purchase = st.checkbox(
        "I have reviewed the details and want to place this trade."
    )

    if st.button("BUY THIS CONTRACT"):
        if not confirm_purchase:
            st.error("Confirm the purchase checkbox first.")
        elif settings["account_type"] == "real" and not real_confirm:
            st.error("Real-account risk confirmation is required.")
        elif settings["stake"] > max_stake:
            st.error("The stake exceeds your configured maximum.")
        else:
            try:
                client = make_client()

                current_balance = client.get_balance(
                    settings["account_type"]
                )

                if settings["stake"] > current_balance["balance"]:
                    raise ValueError(
                        "Insufficient balance for this stake."
                    )

                # Buy the exact proposal displayed above.
                result = client.buy_contract(
                    account_type=settings["account_type"],
                    proposal_id=proposal["proposal_id"],
                    maximum_price=proposal["ask_price"],
                )

                contract_id = result.get("contract_id")

                if not contract_id:
                    raise ValueError(
                        "Deriv did not return a contract ID."
                    )

                # Record only a purchase confirmed by Deriv.
                journal.record_open_trade(
                    contract_id=str(contract_id),
                    account_type=settings["account_type"],
                    account_id=str(result.get("account_id", "")),
                    symbol=settings["symbol"],
                    contract_type=settings["contract_type"],
                    stake=settings["stake"],
                    currency=settings["currency"],
                    transaction_id=str(
                        result.get("transaction_id", "")
                    ) or None,
                    entry_spot=proposal.get("spot"),
                    buy_price=float(
                        result.get(
                            "buy_price",
                            proposal["ask_price"],
                        )
                    ),
                    payout=float(proposal["payout"]),
                    strategy="Manual confirmed purchase",
                    raw_data=result.get("raw"),
                )

                st.success(
                    f"Deriv confirmed the purchase. "
                    f"Contract ID: {contract_id}"
                )

                st.info(
                    "The contract was purchased through Deriv. "
                    "Check your Deriv account's transaction history "
                    "to confirm it appears there."
                )

                st.session_state.proposal = None
                st.session_state.proposal_settings = None

            except Exception as exc:
                st.error(
                    "Purchase or journal recording reported an error: "
                    f"{exc}"
                )
                st.warning(
                    "If the connection failed after a purchase request, "
                    "check Deriv's transaction history before trying "
                    "again, to avoid accidentally buying twice."
                )


# --------------------------------------------------
# OPEN CONTRACT MONITOR
# --------------------------------------------------

st.divider()
st.header("6. Monitor actual open contracts")

st.caption(
    "Refresh a contract to obtain its current status from Deriv. "
    "A position is not marked settled until Deriv reports settlement."
)

open_trades = journal.list_trades(
    limit=100,
    status="OPEN",
    account_type=account_type,
)

if not open_trades:
    st.info(
        f"No locally journaled open contracts for the "
        f"{account_type} account."
    )
else:
    for trade in open_trades:
        contract_id = trade["contract_id"]

        with st.expander(
            f"{trade['symbol']} • {trade['contract_type']} "
            f"• Contract {contract_id}"
        ):
            st.write(f"Stake: {trade['stake']} {trade['currency']}")
            st.write(f"Account: {trade['account_type'].upper()}")

            if st.button(
                f"Refresh contract {contract_id}",
                key=f"refresh_{contract_id}",
            ):
                try:
                    client = make_client()

                    details = client.get_open_contract(
                        account_type=trade["account_type"],
                        contract_id=contract_id,
                    )

                    st.json(details)

                    is_sold = details.get("is_sold")
                    status = str(details.get("status", "")).lower()

                    if is_sold or status in (
                        "won",
                        "lost",
                        "sold",
                    ):
                        profit = details.get("profit")

                        if profit is None:
                            profit = (
                                float(details.get("sell_price", 0))
                                - float(details.get("buy_price", 0))
                            )

                        if float(profit) > 0:
                            final_status = "WON"
                        elif float(profit) < 0:
                            final_status = "LOST"
                        else:
                            final_status = "SOLD"

                        journal.settle_trade(
                            contract_id=contract_id,
                            status=final_status,
                            profit_loss=float(profit),
                            payout=details.get("payout"),
                            exit_spot=details.get("exit_tick"),
                            exit_time=datetime.now(
                                timezone.utc
                            ).isoformat(),
                            raw_data=details,
                        )

                        st.success(
                            f"Settlement recorded: {final_status}; "
                            f"net P/L {float(profit):.2f}"
                        )
                    else:
                        st.info(
                            "Deriv still reports this contract as open."
                        )

                except Exception as exc:
                    st.error(f"Contract refresh failed: {exc}")


# --------------------------------------------------
# JOURNAL
# --------------------------------------------------

st.divider()
st.header("7. Bot trade journal")

st.caption(
    "This is the bot's local journal. Deriv's own transaction "
    "history is separate and remains the source of truth for "
    "actual purchases and settlements."
)

summary = journal.summary(account_type=account_type)

a, b, c, d = st.columns(4)

a.metric("Recorded trades", summary["total_trades"])
b.metric("Open trades", summary["open_trades"])
c.metric("Wins", summary["wins"])
d.metric("Losses", summary["losses"])

st.metric(
    "Recorded net P/L",
    f"{summary['total_profit_loss']:.2f}",
)

if summary["win_rate_percent"] is not None:
    st.metric(
        "Win rate",
        f"{summary['win_rate_percent']:.1f}%",
    )

history = journal.list_trades(
    limit=100,
    account_type=account_type,
)

if history:
    table = pd.DataFrame(history)

    visible_columns = [
        "contract_id",
        "account_type",
        "symbol",
        "contract_type",
        "stake",
        "currency",
        "status",
        "profit_loss",
        "created_at",
    ]

    table = table[
        [column for column in visible_columns if column in table.columns]
    ]

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No trades have been recorded in this local journal yet.")


# --------------------------------------------------
# BOT CONTROL
# --------------------------------------------------

st.divider()
st.header("8. Bot control")

st.warning(
    "Automatic trading is not enabled in this build. "
    "The Start/Stop controls below only change the dashboard's "
    "monitoring state; they do not initiate purchases."
)

left, right = st.columns(2)

with left:
    if st.button("Start monitoring", use_container_width=True):
        st.session_state.bot_running = True

with right:
    if st.button("Stop bot", use_container_width=True):
        st.session_state.bot_running = False

if st.session_state.bot_running:
    st.success(
        "Monitoring mode is ON. No automatic trades will be placed."
    )
else:
    st.info(
        "Monitoring mode is OFF. Existing contracts remain on Deriv "
        "and must still be checked for settlement."
    )

st.caption(
    "Risk reminder: short-duration contracts and volatility indices "
    "can lose money quickly. No indicator or bot can guarantee profits."
)