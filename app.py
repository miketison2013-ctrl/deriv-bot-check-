
import streamlit as st

st.set_page_config(
    page_title="Deriv Bot Dashboard",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Deriv Volatility Bot")
st.caption("Dashboard preview — demo mode only")

st.warning(
    "This is a dashboard prototype. "
    "It does not connect to Deriv or place trades yet."
)

left, right = st.columns(2)

with left:
    st.subheader("Account")
    st.metric("Balance", "Not connected")
    st.metric("Account mode", "DEMO ONLY")

with right:
    st.subheader("Bot status")
    st.metric("Status", "Stopped")
    st.metric("Trades this session", "0")

st.divider()

st.subheader("Bot settings")

market = st.selectbox(
    "Volatility market",
    [
        "Volatility 10 Index",
        "Volatility 25 Index",
        "Volatility 50 Index",
        "Volatility 75 Index",
        "Volatility 100 Index",
    ],
)

risk = st.number_input(
    "Demo stake per trade",
    min_value=0.35,
    max_value=10.0,
    value=1.0,
    step=0.35,
)

max_trades = st.number_input(
    "Maximum trades per session",
    min_value=1,
    max_value=20,
    value=3,
    step=1,
)

st.write("Selected market:", market)
st.write("Demo stake:", risk)
st.write("Maximum trades:", max_trades)

st.button("Start demo preview", disabled=True)
st.button("Stop bot", disabled=True)

st.info(
    "Trading is disabled in this prototype. "
    "We will test the dashboard before adding any trading connection."
)
