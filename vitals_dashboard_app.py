"""
Vitals Dashboard
----------------
Run with:
    pip install -r requirements.txt
    streamlit run vitals_dashboard_app.py

Or double-click run_vitals_dashboard.bat on Windows.

Reads readings from the Vitals backend through /api/history and shows the
latest values, trend charts, GPS points, and a raw data table. Refreshes
automatically while the page is open.
"""

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# =============================================================================
# CONFIG
# =============================================================================
TZ_OFFSET_HOURS = 1                       # UTC+1 = Africa/Lagos (WAT)
DEFAULT_SERVER  = os.environ.get("VITALS_SERVER", "http://127.0.0.1:8000")
DEFAULT_DEVICE  = os.environ.get("VITALS_DEVICE", "watch01")
DEFAULT_APP_KEY = os.environ.get("VITALS_APP_KEY", "change-me-app")

st.set_page_config(page_title="Vitals Dashboard", layout="wide")


# =============================================================================
# DATA
# =============================================================================
@st.cache_data(ttl=5)
def fetch_history(server: str, device: str, app_key: str, limit: int) -> pd.DataFrame:
    res = requests.get(
        f"{server.rstrip('/')}/api/history",
        params={"device": device, "limit": limit},
        headers={"x-api-key": app_key},
        timeout=10,
    )
    res.raise_for_status()
    return pd.DataFrame(res.json())


def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df["time"] = pd.to_datetime(df["received_at"], unit="ms") + pd.Timedelta(hours=TZ_OFFSET_HOURS)
    return df.sort_values("time").reset_index(drop=True)


def fmt(value, spec=".0f", unit=""):
    """Shows '--' when the value is missing."""
    if value is None or pd.isna(value):
        return "--"
    return f"{value:{spec}}{unit}"


# =============================================================================
# SIDEBAR
# =============================================================================
st.sidebar.header("⌚ Connection")
server  = st.sidebar.text_input("Server URL", DEFAULT_SERVER)
device  = st.sidebar.text_input("Device ID", DEFAULT_DEVICE)
app_key = st.sidebar.text_input("App key", DEFAULT_APP_KEY, type="password")
limit   = st.sidebar.slider("Readings to load", 20, 1000, 300, 20)

st.sidebar.divider()
auto_refresh = st.sidebar.checkbox("Auto refresh", value=True)
refresh_secs = st.sidebar.slider("Refresh every (seconds)", 5, 60, 10)

if st.sidebar.button("🔄 Refresh now"):
    st.cache_data.clear()


# =============================================================================
# PAGE
# =============================================================================
st.title("⌚ Vitals Dashboard")
st.caption(f"Device: **{device}**  •  Times shown in local time (UTC+{TZ_OFFSET_HOURS})")


def trend(df: pd.DataFrame, col: str, unit: str):
    data = df.dropna(subset=[col])
    if data.empty:
        st.info("No data yet for this reading.")
        return
    fig = px.line(data, x="time", y=col, markers=True)
    fig.update_layout(height=380, xaxis_title="Time", yaxis_title=unit, margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)


def live_view():
    try:
        raw = fetch_history(server, device, app_key, limit)
    except requests.RequestException as e:
        st.error(f"Could not reach the server: {e}")
        return

    if raw.empty:
        st.info("No readings yet for this device. Send one from the watch or the test sketch.")
        return

    df = prepare(raw)
    latest = df.iloc[-1]

    st.caption(f"Last update: {latest['time'].strftime('%d %b %Y, %H:%M:%S')}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Temperature", fmt(latest["temp"], ".1f", " °C"))
    c2.metric("Heart rate", fmt(latest["bpm"], ".0f", " BPM"))
    c3.metric("Blood oxygen", fmt(latest["spo2"], ".0f", " %"))
    c4.metric("Steps", fmt(latest["steps"], ",.0f"))

    c5, c6, c7 = st.columns(3)
    c5.metric("Speed", fmt(latest["speed"], ".1f", " km/h"))
    c6.metric("Battery", fmt(latest["battery"], ".0f", " %"))
    c7.metric("Network", fmt(latest["signal_bars"], ".0f", " / 4"))

    st.divider()

    tab_temp, tab_bpm, tab_spo2, tab_steps = st.tabs(["Temperature", "Heart rate", "SpO2", "Steps"])
    with tab_temp:
        trend(df, "temp", "°C")
    with tab_bpm:
        trend(df, "bpm", "BPM")
    with tab_spo2:
        trend(df, "spo2", "%")
    with tab_steps:
        trend(df, "steps", "steps")

    st.divider()

    st.subheader("📍 Location")
    gps = df.dropna(subset=["lat", "lon"])
    gps = gps[(gps["lat"] != 0) & (gps["lon"] != 0)]
    if gps.empty:
        st.info("No GPS fix yet.")
    else:
        st.map(gps[["lat", "lon"]])

    with st.expander("Raw readings"):
        st.dataframe(df.iloc[::-1], use_container_width=True)


# Only this part refreshes automatically, so the sidebar and title stay still.
st.fragment(run_every=refresh_secs if auto_refresh else None)(live_view)()
