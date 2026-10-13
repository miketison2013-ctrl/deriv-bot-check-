import streamlit as st
from deriv_client import DerivClient

st.set_page_config(
    page_title="Deriv Trading Dashboard",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Deriv Trading Dashboard")
st.caption("Account connection and controlled contract purchases")

st.warning(
    "Trading involves risk. Start with a demo account. "
    "This version does not automatically analyse markets or guarantee profits."
)

# ---------------- ACCOUNT SETTINGS ----------------

with st.sidebar:
    st.header("Deriv connection")

    app_id = st.text_input("Deriv App ID")

    account_mode = st.radio(
        "Select ONE account to use",
        ["Demo", "Real"],
        index=0,
    )

    demo_token = st.text_input(
        "Demo API token",
        type="password",
    )

    real_token = st.text_input(
        "Real API token",
        type="password",
    )

    st.caption(
        "Never save API tokens in GitHub files or share them in chat."
    )

token = demo_token.strip() if account_mode == "Demo" else real_token.strip()


def get_client():
    if not app_id.strip():
        raise ValueError("Enter your Deriv App ID.")

    if not token:
        raise ValueError(
            f"Enter the API token for your selected {account_mode} account."
        )

    return DerivClient(app_id=app_id, token=token)


def display_error(label, error):
    st.error(f"{label}: {error}")


# ---------------- SESSION STATE ----------------

if "markets" not in st.session_state:
    st.session_state.markets = []

if "contracts" not in st.session_state:
    st.session_state.contracts = {}

if "loaded_market" not in st.session_state:
    st.session_state.loaded_market = ""

if "last_trade" not in st.session_state:
    st.session_state.last_trade = None

# Reset market data when the selected account changes.
account_key = f"{account_mode}:{app_id.strip()}:{token}"

if st.session_state.get("account_key") != account_key:
    st.session_state.account_key = account_key
    st.session_state.markets = []
    st.session_state.contracts = {}
    st.session_state.loaded_market = ""
    st.session_state.last_trade = None


# ---------------- BALANCE ----------------

st.header("1. Account balance")

st.write("Selected account:", f"**{account_mode.upper()}**")

if account_mode == "Real":
    st.error("REAL ACCOUNT: purchases can use real money.")

if st.button("Connect and check balance"):
    try:
        details = get_client().get_balance()

        st.success("Account connection successful.")

        col1, col2, col3 = st.columns(3)

        col1.metric("Account ID", details["loginid"])
        col2.metric(
            "Balance",
            f'{details["balance"]:.2f}',
        )
        col3.metric("Currency", details["currency"] or "Unknown")

    except Exception as error:
        display_error("Balance request failed", error)


# ---------------- MARKETS ----------------

st.divider()
st.header("2. Available markets")

if st.button("Load markets"):
    try:
        client = get_client()
        markets = client.get_active_symbols()

        st.session_state.markets = markets
        st.session_state.contracts = {}
        st.session_state.loaded_market = ""

        if markets:
            st.success(f"Loaded {len(markets)} available markets.")
        else:
            st.warning(
                "No markets were returned. Check the API response "
                "and account connection."
            )

    except Exception as error:
        display_error("Market loading failed", error)


markets = st.session_state.markets

if markets:
    market_options = {
        f'{market["display_name"]} ({market["symbol"]})':
        market["symbol"]
        for market in markets
    }

    market_label = st.selectbox(
        "Choose a market",
        list(market_options.keys()),
    )

    symbol = market_options[market_label]

    if symbol != st.session_state.loaded_market:
        st.session_state.contracts = {}
        st.session_state.loaded_market = symbol

    if st.button("Load available digit contracts"):
        try:
            st.session_state.contracts = (
                get_client().get_contract_types(symbol)
            )

            if st.session_state.contracts:
                st.success("Available contract types loaded.")
            else:
                st.warning(
                    "This market returned no supported digit contracts."
                )

        except Exception as error:
            display_error("Contract loading failed", error)

    # ---------------- CONTRACT SETTINGS ----------------

    contracts = st.session_state.contracts

    if contracts:
        st.divider()
        st.header("3. Order settings")

        contract_label = st.selectbox(
            "Contract type",
            list(contracts.keys()),
        )

        contract_code = contracts[contract_label]

        requires_digit = contract_code in {
            "DIGITOVER",
            "DIGITUNDER",
            "DIGITMATCH",
            "DIGITDIFF",
        }

        digit = None

        if requires_digit:
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
        st.write("Stake:", stake, currency)

        if account_mode == "Real":
            st.error(
                "You selected REAL trading. Check every setting "
                "before continuing."
            )

        confirmation = st.checkbox(
            f"I confirm one {account_mode.upper()} purchase "
            "using the settings shown above."
        )

        if st.button("Buy ONE contract", type="primary"):
            if not confirmation:
                st.error("Confirm the order first.")

            elif not currency:
                st.error("Enter your account currency.")

            else:
                try:
                    result = get_client().buy_digit_contract(
                        symbol=symbol,
                        contract_type=contract_code,
                        stake=float(stake),
                        currency=currency,
                        duration_ticks=int(duration),
                        barrier=int(digit) if requires_digit else None,
                    )

                    st.session_state.last_trade = result

                    st.success(
                        "Deriv returned a purchase confirmation."
                    )

                except Exception as error:
                    display_error("Purchase failed", error)


# ---------------- LAST PURCHASE ----------------

if st.session_state.last_trade:
    st.divider()
    st.header("Latest purchase confirmation")

    trade = st.session_state.last_trade

    st.write("Contract ID:", trade["contract_id"])
    st.write("Account ID:", trade["loginid"])
    st.write("Purchase price:", trade["buy_price"])
    st.write("Potential payout:", trade["payout"])

    if trade.get("longcode"):
        st.write("Contract details:", trade["longcode"])

    st.info(
        "A purchase confirmation does not mean the contract has settled "
        "or made a profit. Check the contract in Deriv's trade history."
    )

else:
    st.caption("No purchase confirmation in this session.")