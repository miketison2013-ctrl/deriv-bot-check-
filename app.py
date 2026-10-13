
import streamlit as st
from deriv_client import DerivClient, DerivAPIError

st.set_page_config(
    page_title="Deriv Volatility Bot",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Deriv Trading Dashboard")
st.caption("Live account connection and controlled digit-contract orders")

st.warning(
    "Real trading risks losing your stake. This version places a trade "
    "only when you press the purchase button. It does not guarantee profit."
)

with st.sidebar:
    st.header("API connection")

    app_id = st.text_input(
        "Deriv App ID",
        value="",
        help="Enter your registered Deriv application ID.",
    )

    demo_token = st.text_input(
        "Demo API token",
        type="password",
        help="Use a token belonging to your demo account.",
    )

    real_token = st.text_input(
        "Real API token",
        type="password",
        help="Use a token belonging to your real account.",
    )

    account_mode = st.radio(
        "Account to use",
        ["Demo", "Real"],
        index=0,
    )

    st.caption(
        "Tokens are entered in this session only. Never commit them "
        "to GitHub or share them in chat."
    )

selected_token = demo_token if account_mode == "Demo" else real_token

def make_client(token):
    return DerivClient(app_id=app_id, token=token)

def show_error(error):
    st.error(str(error))

if "symbols" not in st.session_state:
    st.session_state.symbols = []

if "contract_types" not in st.session_state:
    st.session_state.contract_types = {}

if "trade_result" not in st.session_state:
    st.session_state.trade_result = None

left, right = st.columns(2)

with left:
    st.subheader("Account balances")

    if st.button("Connect and refresh balances"):
        if not app_id.strip():
            st.error("Enter your Deriv App ID.")
        elif not demo_token.strip() and not real_token.strip():
            st.error("Enter at least one account token.")
        else:
            for label, token in [
                ("Demo", demo_token),
                ("Real", real_token),
            ]:
                if not token.strip():
                    st.info(f"{label}: no token entered.")
                    continue

                try:
                    details = make_client(token).get_balance()
                    st.write(
                        f"{label} account: {details['loginid']} — "
                        f"{details['balance']:.2f} "
                        f"{details['currency']}"
                    )
                except Exception as error:
                    st.error(f"{label} account: {error}")

with right:
    st.subheader("Selected account")

    st.metric("Mode", account_mode.upper())

    if account_mode == "Real":
        st.warning("REAL account selected.")

    st.write(
        "Only the token for the selected account is used for "
        "the purchase request."
    )

st.divider()
st.header("Market and contract settings")

if st.button("Load available markets"):
    if not app_id.strip() or not selected_token.strip():
        st.error("Enter the App ID and token for the selected account.")
    else:
        try:
            client = make_client(selected_token)
            st.session_state.symbols = client.get_active_symbols()
            st.session_state.contract_types = {}
            st.success(
                f"Loaded {len(st.session_state.symbols)} active markets."
            )
        except Exception as error:
            show_error(error)

symbols = st.session_state.symbols

if not symbols:
    st.info("Connect your selected account, then load available markets.")
else:
    symbol_labels = {
        f"{item['display_name']} ({item['symbol']})": item["symbol"]
        for item in symbols
    }

    market_label = st.selectbox(
        "Market",
        list(symbol_labels.keys()),
    )
    symbol = symbol_labels[market_label]

    if st.button("Load supported digit contracts"):
        try:
            client = make_client(selected_token)
            st.session_state.contract_types = (
                client.get_contract_types(symbol)
            )
            st.success("Contract types refreshed for this market.")
        except Exception as error:
            show_error(error)

    types = st.session_state.contract_types

    if types:
        contract_label = st.selectbox(
            "Contract type",
            list(types.keys()),
        )
        contract_code = types[contract_label]

        needs_digit = contract_code in {
            "DIGITOVER", "DIGITUNDER",
            "DIGITMATCH", "DIGITDIFF",
        }

        barrier = None
        if needs_digit:
            barrier = st.number_input(
                "Prediction digit",
                min_value=0,
                max_value=9,
                value=5,
                step=1,
            )

        currency = st.text_input(
            "Account currency",
            value="USD",
            help=(
                "Use the currency shown for your selected Deriv account, "
                "for example USD or EUR."
            ),
        ).strip().upper()

        stake = st.number_input(
            "Stake per trade",
            min_value=0.35,
            max_value=10.0,
            value=0.35,
            step=0.05,
        )

        duration_ticks = st.number_input(
            "Contract duration (ticks)",
            min_value=1,
            max_value=10,
            value=1,
            step=1,
        )

        st.caption(
            "This order uses the selected account, market, contract, "
            "stake and duration. Confirm all settings before buying."
        )

        confirmed = st.checkbox(
            "I have checked the settings and authorize one real order"
            if account_mode == "Real"
            else "I understand this will place an actual demo order"
        )

        if st.button("Buy one contract", type="primary"):
            if not app_id.strip() or not selected_token.strip():
                st.error("Enter the selected account's API details.")
            elif not currency:
                st.error("Enter the account currency.")
            elif not confirmed:
                st.error("Tick the confirmation box before buying.")
            else:
                try:
                    client = make_client(selected_token)
                    result = client.buy_digit_contract(
                        symbol=symbol,
                        contract_type=contract_code,
                        stake=float(stake),
                        currency=currency,
                        duration_ticks=int(duration_ticks),
                        barrier=int(barrier) if needs_digit else None,
                    )

                    st.session_state.trade_result = result
                    st.success("Deriv returned a purchase confirmation.")

                except Exception as error:
                    st.session_state.trade_result = None
                    show_error(error)

if st.session_state.trade_result:
    st.divider()
    st.subheader("Latest purchase confirmation")
    result = st.session_state.trade_result

    st.write("Contract ID:", result["contract_id"])
    st.write("Account:", result["loginid"])
    st.write("Buy price:", result["buy_price"])
    st.write("Potential payout:", result["payout"])

    if result.get("longcode"):
        st.write("Contract details:", result["longcode"])

    st.caption(
        "Keep the contract ID to check the trade in Deriv's own "
        "trade history. A purchase confirmation alone is not a "
        "settlement or proof of profit."
    )
