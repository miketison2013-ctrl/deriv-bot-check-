import streamlit as st
from datetime import datetime, timezone

from deriv_client import DerivClient, DerivAPIError
from strategy import moving_average, crossover_signal


st.set_page_config(
    page_title="Deriv Live Market Dashboard",
    page_icon="📈",
    layout="wide",
)

st.title("Deriv Live Market Dashboard")

st.warning(
    "Connection and analysis dashboard only. "
    "No automatic or real-money trading is enabled."
)

with st.sidebar:
    st.header("Deriv connection")

    app_id = st.text_input(
        "Deriv App ID",
        placeholder="Enter your current App ID",
    )

    token = st.text_input(
        "Personal Access Token",
        type="password",
        help="Keep this private. Never commit it to GitHub.",
    )

    st.caption(
        "Use a token authorized to access your Options accounts."
    )


def make_client():
    if not app_id.strip():
        raise ValueError("Enter your Deriv App ID.")

    if not token.strip():
        raise ValueError("Enter your Personal Access Token.")

    return DerivClient(app_id, token)


st.header("1. Account balances")

left, right = st.columns(2)

with left:
    st.subheader("Demo account")

    if st.button("Read demo balance", use_container_width=True):
        try:
            details = make_client().get_balance("demo")
            st.success(
                f"Account: {details['account_id']}"
            )
            st.metric(
                "Demo balance",
                f"{details['balance']:.2f} "
                f"{details['currency']}",
            )
        except Exception as exc:
            st.error(f"Demo balance failed: {exc}")

with right:
    st.subheader("Real account")

    if st.button("Read real balance", use_container_width=True):
        try:
            details = make_client().get_balance("real")
            st.success(
                f"Account: {details['account_id']}"
            )
            st.metric(
                "Real balance",
                f"{details['balance']:.2f} "
                f"{details['currency']}",
            )
        except Exception as exc:
            st.error(f"Real balance failed: {exc}")


st.divider()
st.header("2. Market selection")

if "markets" not in st.session_state:
    st.session_state.markets = []

if st.button("Load available markets"):
    try:
        st.session_state.markets = (
            make_client().get_active_symbols()
        )
        st.success(
            f"{len(st.session_state.markets)} markets loaded."
        )
    except Exception as exc:
        st.error(f"Market loading failed: {exc}")


markets = st.session_state.markets

if not markets:
    st.info(
        "Load available markets to choose an instrument."
    )
else:
    market_options = {
        f"{item['display_name']} ({item['symbol']})":
        item["symbol"]
        for item in markets
    }

    selected_label = st.selectbox(
        "Choose a market",
        list(market_options.keys()),
    )

    symbol = market_options[selected_label]

    st.divider()
    st.header("3. Live market price")

    st.caption(
        "The panel refreshes every three seconds while open. "
        "A refresh failure will be shown instead of inventing a price."
    )

    @st.fragment(run_every="3s")
    def live_market_panel():
        try:
            client = make_client()
            tick = client.get_latest_tick(symbol)

            st.metric(
                f"Latest price — {symbol}",
                f"{tick['quote']:.5f}",
            )

            if tick.get("epoch"):
                timestamp = datetime.fromtimestamp(
                    int(tick["epoch"]),
                    tz=timezone.utc,
                )
                st.caption(
                    "Last tick time (UTC): "
                    + timestamp.strftime("%Y-%m-%d %H:%M:%S")
                )

            st.success("Received a market tick from Deriv.")

        except Exception as exc:
            st.error(f"Live price unavailable: {exc}")

    live_market_panel()

    st.divider()
    st.header("4. Market analysis")

    if st.button("Analyse recent ticks"):
        try:
            data = make_client().get_recent_ticks(
                symbol,
                count=100,
            )
            prices = data["prices"]

            if len(prices) < 11:
                st.warning(
                    "Not enough historical ticks for analysis."
                )
            else:
                fast = moving_average(prices, 5)
                slow = moving_average(prices, 10)
                signal = crossover_signal(prices, 5, 10)

                a, b, c = st.columns(3)

                a.metric(
                    "Latest historical quote",
                    f"{prices[-1]:.5f}",
                )
                b.metric(
                    "5-tick average",
                    f"{fast:.5f}",
                )
                c.metric(
                    "10-tick average",
                    f"{slow:.5f}",
                )

                if signal == "UP":
                    st.success(
                        "Moving-average crossover: UP"
                    )
                elif signal == "DOWN":
                    st.warning(
                        "Moving-average crossover: DOWN"
                    )
                else:
                    st.info(
                        "Moving-average crossover: WAIT"
                    )

                st.caption(
                    "This indicator is not a guarantee of future "
                    "price movement or profitability."
                )

        except Exception as exc:
            st.error(f"Analysis failed: {exc}")


st.divider()
st.info(
    "Trading is intentionally disabled in this version. "
    "First verify the API token, both account balances, "
    "market list, and live prices."
)