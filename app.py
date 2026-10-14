
import streamlit as st
import pandas as pd

from deriv_client import DerivClient
from trade_journal import TradeJournal


st.set_page_config(
    page_title="Deriv Trading Bot",
    page_icon="📈",
    layout="wide",
)

st.title("Deriv Trading Bot")
st.caption("Account connection, market data and trade journal")

if "client" not in st.session_state:
    st.session_state.client = None

if "markets" not in st.session_state:
    st.session_state.markets = []

if "balances" not in st.session_state:
    st.session_state.balances = {}

st.sidebar.header("Deriv Connection")

app_id = st.sidebar.text_input("App ID")
token = st.sidebar.text_input("Personal Access Token", type="password")

account_type = st.sidebar.radio(
    "Account",
    ["demo", "real"],
    format_func=lambda value: (
        "Demo account" if value == "demo"
        else "REAL MONEY account"
    ),
)

real_confirm = False

if account_type == "real":
    real_confirm = st.sidebar.checkbox(
        "I understand real trades can lose money."
    )

if st.sidebar.button("Connect to Deriv"):
    if not app_id.strip() or not token.strip():
        st.sidebar.error("Enter your App ID and token.")
    elif account_type == "real" and not real_confirm:
        st.sidebar.error("Confirm the real-account warning.")
    else:
        try:
            client = DerivClient(app_id.strip(), token.strip())
            st.session_state.client = client
            st.session_state.markets = []
            st.session_state.balances = {}
            st.sidebar.success("Connection details accepted.")
        except Exception as exc:
            st.sidebar.error(str(exc))

client = st.session_state.client

if client is None:
    st.info("Enter your Deriv App ID and token, then connect.")
    st.warning(
        "Use Demo first. Never put your personal access token "
        "inside this code or commit it to GitHub."
    )
else:
    st.header("Account Balances")

    col1, col2 = st.columns(2)

    for account, column in [
        ("demo", col1),
        ("real", col2),
    ]:
        with column:
            st.subheader(account.capitalize())

            if st.button(
                f"Refresh {account} balance",
                key=f"balance_{account}",
            ):
                try:
                    result = client.get_balance(account)
                    st.session_state.balances[account] = result
                except Exception as exc:
                    st.error(f"Could not read {account} balance: {exc}")

            balance = st.session_state.balances.get(account)

            if balance:
                st.metric(
                    "Balance",
                    f"{balance['balance']:.2f} {balance['currency']}",
                )
                st.caption(f"Account ID: {balance['account_id']}")
            else:
                st.caption("Balance not loaded yet.")

    st.divider()
    st.header("Available Markets")

    if st.button("Load markets"):
        try:
            st.session_state.markets = client.get_active_symbols()
        except Exception as exc:
            st.error(f"Could not load markets: {exc}")

    markets = st.session_state.markets

    if markets:
        st.dataframe(
            pd.DataFrame(markets),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Tap Load markets to retrieve available markets.")

st.divider()
st.header("Trade Journal")

try:
    journal = TradeJournal("trade_journal.db")
    trades = journal.list_trades(limit=100)

    if trades:
        st.dataframe(
            pd.DataFrame(trades),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No recorded trades yet.")
except Exception as exc:
    st.error(f"Could not load the trade journal: {exc}")

st.caption(
    "This version does not place trades automatically. "
    "We will add and test the next feature after verifying this file."
)
