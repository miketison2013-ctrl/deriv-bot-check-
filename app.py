import streamlit as st
from deriv_client import DerivClient
from strategy import moving_average, crossover_signal

st.set_page_config(
    page_title="Deriv Trading Dashboard",
    page_icon="📈",
    layout="wide",
)

st.title("Deriv Trading Dashboard")
st.warning(
    "Trading is risky. Use demo mode first. "
    "Market analysis is informational and does not guarantee profit."
)

# ---------------- ACCOUNT CONNECTION ----------------

with st.sidebar:
    st.header("Account connection")
    app_id = st.text_input("Deriv App ID")

    demo_token = st.text_input(
        "Demo API token",
        type="password",
    )
    real_token = st.text_input(
        "Real API token",
        type="password",
    )

    account_mode = st.radio(
        "Account used for trading",
        ["Demo", "Real"],
        index=0,
    )

    st.caption(
        "Keep tokens private. Never commit tokens to GitHub."
    )

selected_token = (
    demo_token.strip()
    if account_mode == "Demo"
    else real_token.strip()
)


def client_for(token):
    if not app_id.strip():
        raise ValueError("Enter your Deriv App ID.")
    if not token.strip():
        raise ValueError("Enter the API token for this account.")
    return DerivClient(app_id, token)


def selected_client():
    return client_for(selected_token)


def show_error(label, error):
    st.error(f"{label}: {error}")


# ---------------- SESSION DATA ----------------

defaults = {
    "markets": [],
    "contracts": {},
    "loaded_market": "",
    "last_trade": None,
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# Do not store the token in session state keys.
account_fingerprint = (
    account_mode,
    app_id.strip(),
    bool(selected_token),
)

if st.session_state.get("account_fingerprint") != account_fingerprint:
    st.session_state.account_fingerprint = account_fingerprint
    st.session_state.markets = []
    st.session_state.contracts = {}
    st.session_state.loaded_market = ""
    st.session_state.last_trade = None


# ---------------- BALANCES ----------------

st.header("1. Account balances")
left, right = st.columns(2)

with left:
    st.subheader("Demo account")
    if st.button("Check demo balance"):
        try:
            details = client_for(demo_token).get_balance()
            st.success(f'Account: {details["loginid"]}')
            st.metric(
                "Demo balance",
                f'{details["balance"]:.2f} {details["currency"]}',
            )
        except Exception as error:
            show_error("Demo balance failed", error)

with right:
    st.subheader("Real account")
    if st.button("Check real balance"):
        try:
            details = client_for(real_token).get_balance()
            st.success(f'Account: {details["loginid"]}')
            st.metric(
                "Real balance",
                f'{details["balance"]:.2f} {details["currency"]}',
            )
        except Exception as error:
            show_error("Real balance failed", error)

st.info(f"Selected trading account: {account_mode.upper()}")

if account_mode == "Real":
    st.error(
        "REAL ACCOUNT SELECTED. Any confirmed purchase may risk real money."
    )


# ---------------- MARKETS ----------------

st.divider()
st.header("2. Available markets")

if st.button("Refresh market list"):
    try:
        st.session_state.markets = selected_client().get_active_symbols()
        st.session_state.contracts = {}
        st.session_state.loaded_market = ""
        st.success(
            f'{len(st.session_state.markets)} markets loaded.'
        )
    except Exception as error:
        show_error("Market loading failed", error)

markets = st.session_state.markets

if markets:
    options = {
        f'{m["display_name"]} ({m["symbol"]})': m["symbol"]
        for m in markets
    }

    market_label = st.selectbox(
        "Choose market",
        list(options.keys()),
    )
    symbol = options[market_label]

    if symbol != st.session_state.loaded_market:
        st.session_state.loaded_market = symbol
        st.session_state.contracts = {}

    if st.button("Load supported digit contracts"):
        try:
            st.session_state.contracts = (
                selected_client().get_contract_types(symbol)
            )
            if st.session_state.contracts:
                st.success("Contract types loaded.")
            else:
                st.warning(
                    "No supported digit contracts were returned for this market."
                )
        except Exception as error:
            show_error("Contract loading failed", error)

    # ---------------- MARKET ANALYSIS ----------------

    st.subheader("Market analysis")

    if st.button("Analyse recent ticks"):
        try:
            data = selected_client().get_recent_ticks(symbol, 100)
            prices = data["prices"]

            if len(prices) < 11:
                st.warning("Not enough tick history for this analysis.")
            else:
                fast_ma = moving_average(prices, 5)
                slow_ma = moving_average(prices, 10)
                signal = crossover_signal(prices, 5, 10)

                a, b, c = st.columns(3)
                a.metric("Latest quote", f"{prices[-1]:.5f}")
                b.metric("5-tick average", f"{fast_ma:.5f}")
                c.metric("10-tick average", f"{slow_ma:.5f}")

                if signal == "UP":
                    st.success("Moving-average crossover: UP")
                elif signal == "DOWN":
                    st.warning("Moving-average crossover: DOWN")
                else:
                    st.info("Moving-average crossover: WAIT")

                st.caption(
                    "This is a simple indicator, not a prediction "
                    "or a recommendation to place a trade."
                )
        except Exception as error:
            show_error("Analysis failed", error)

    # ---------------- ORDER SETTINGS ----------------

    contracts = st.session_state.contracts

    if contracts:
        st.divider()
        st.header("3. Manual order")

        contract_label = st.selectbox(
            "Contract type",
            list(contracts.keys()),
        )
        contract_code = contracts[contract_label]

        needs_digit = contract_code in {
            "DIGITOVER",
            "DIGITUNDER",
            "DIGITMATCH",
            "DIGITDIFF",
        }

        digit = None
        if needs_digit:
            digit = st.number_input(
                "Prediction digit",
                min_value=0,
                max_value=9,
                value=5,
                step=1,
            )

        currency = st.text_input(
            "Account currency",
            value="USD",
        ).strip().upper()

        stake = st.number_input(
            "Stake",
            min_value=0.35,
            max_value=10.0,
            value=0.35,
            step=0.05,
        )

        duration = st.number_input(
            "Duration in ticks",
            min_value=1,
            max_value=10,
            value=1,
            step=1,
        )

        st.write("Market:", symbol)
        st.write("Contract:", contract_label)
        st.write("Account:", account_mode.upper())
        st.write("Stake:", f"{stake:.2f} {currency}")

        if account_mode == "Real":
            st.error(
                "Real trading is selected. Verify account, market, "
                "contract, stake and duration before buying."
            )

        confirm = st.checkbox(
            f"I confirm ONE {account_mode.upper()} purchase "
            "with the settings above."
        )

        if st.button("Buy ONE contract", type="primary"):
            if not confirm:
                st.error("Confirm the order before buying.")
            else:
                try:
                    result = selected_client().buy_digit_contract(
                        symbol=symbol,
                        contract_type=contract_code,
                        stake=float(stake),
                        currency=currency,
                        duration_ticks=int(duration),
                        barrier=int(digit) if needs_digit else None,
                    )
                    st.session_state.last_trade = result
                    st.success("Deriv confirmed the purchase.")
                except Exception as error:
                    show_error("Purchase failed", error)

if st.session_state.last_trade:
    st.divider()
    st.header("Latest purchase")
    trade = st.session_state.last_trade
    st.write("Contract ID:", trade["contract_id"])
    st.write("Account ID:", trade["loginid"])
    st.write("Purchase price:", trade["buy_price"])
    st.write("Potential payout:", trade["payout"])
    st.write("Details:", trade.get("longcode", ""))


# ---------------- OPEN POSITIONS ----------------

st.divider()
st.header("4. Open positions")

if st.button("Refresh open positions"):
    try:
        positions = selected_client().get_open_positions()
        st.session_state.open_positions = positions

        if positions:
            st.success(f"{len(positions)} open position(s).")
        else:
            st.info("No open positions were returned.")
    except Exception as error:
        show_error("Position request failed", error)

positions = st.session_state.get("open_positions", [])

if positions:
    st.dataframe(positions, use_container_width=True)

    ids = [
        str(p.get("contract_id"))
        for p in positions
        if p.get("contract_id") is not None
    ]

    if ids:
        selected_id = st.selectbox(
            "Check a contract",
            ids,
        )

        if st.button("Check contract status"):
            try:
                status = selected_client().get_contract_status(
                    selected_id
                )
                st.json(status)
            except Exception as error:
                show_error("Contract status failed", error)


# ---------------- TRANSACTION HISTORY ----------------

st.divider()
st.header("5. Account transaction history")

if st.button("Load recent transactions"):
    try:
        transactions = selected_client().get_statement(25)
        st.session_state.transactions = transactions

        if transactions:
            st.dataframe(transactions, use_container_width=True)
        else:
            st.info("No transactions were returned.")
    except Exception as error:
        show_error("Transaction history failed", error)

if st.session_state.get("transactions"):
    st.dataframe(
        st.session_state.transactions,
        use_container_width=True,
    )

st.caption(
    "Open positions and transaction history are fetched on request. "
    "This dashboard does not run continuously in the background."
)