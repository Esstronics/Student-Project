import os
import time

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(page_title="Vitals Dashboard", page_icon="⌚", layout="wide")

TZ_OFFSET_HOURS = 1
LIVE_WINDOW_S = 120
FIELDS = ["temp", "bpm", "spo2", "steps", "speed", "dist", "sats",
          "battery", "signal_bars", "lat", "lon"]


def secret(name, default):
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


DEFAULT_SERVER  = secret("VITALS_SERVER", "http://127.0.0.1:8000")
DEFAULT_DEVICE  = secret("VITALS_DEVICE", "watch01")
DEFAULT_APP_KEY = secret("VITALS_APP_KEY", "change-me-app")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; }
.card {
  background: #ffffff; border-radius: 16px; padding: 16px 18px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 14px;
}
.card-label { color: #6b7280; font-size: 0.8rem; text-transform: uppercase;
              letter-spacing: 0.05em; font-weight: 600; }
.card-value { color: #111827; font-size: 2rem; font-weight: 700; line-height: 1.2; }
.card-unit  { color: #6b7280; font-size: 0.95rem; font-weight: 500; margin-left: 4px; }
.card-icon  { font-size: 1.1rem; margin-right: 6px; }
.badge-live { background: #dcfce7; color: #166534; padding: 6px 14px; border-radius: 999px;
              font-weight: 600; font-size: 0.85rem; display: inline-block; }
.badge-off  { background: #f3f4f6; color: #4b5563; padding: 6px 14px; border-radius: 999px;
              font-weight: 600; font-size: 0.85rem; display: inline-block; }
.section    { font-size: 1.15rem; font-weight: 700; margin: 6px 0 4px 0; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=5)
def fetch_history(server: str, device: str, app_key: str, limit: int) -> pd.DataFrame:
    res = requests.get(
        f"{server.rstrip('/')}/api/history",
        params={"device": device, "limit": limit},
        headers={"x-api-key": app_key, "ngrok-skip-browser-warning": "true"},
        timeout=10,
    )
    res.raise_for_status()
    return pd.DataFrame(res.json())


def prepare(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    for col in FIELDS + ["received_at"]:
        if col not in df:
            df[col] = None
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["time"] = pd.to_datetime(df["received_at"], unit="ms") + pd.Timedelta(hours=TZ_OFFSET_HOURS)
    df["dist_km"] = df["dist"] / 1000
    return df.sort_values("time").reset_index(drop=True)


def val(v, spec=".0f", unit=""):
    if v is None or pd.isna(v):
        return "--"
    return f"{v:{spec}}{unit}"


def card(label, value, unit, icon, color):
    return f"""
    <div class="card" style="border-left: 6px solid {color};">
      <div class="card-label"><span class="card-icon">{icon}</span>{label}</div>
      <div><span class="card-value">{value}</span><span class="card-unit">{unit}</span></div>
    </div>
    """


def gauge(title, value, vmin, vmax, suffix, color, steps):
    if value is None or pd.isna(value):
        st.markdown(card(title, "--", "", "◌", "#9ca3af"), unsafe_allow_html=True)
        return
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": suffix, "font": {"size": 26}},
        title={"text": title, "font": {"size": 14}},
        gauge={
            "axis": {"range": [vmin, vmax]},
            "bar": {"color": color},
            "steps": steps,
        },
    ))
    fig.update_layout(height=220, margin=dict(l=16, r=16, t=40, b=8), template="plotly_white")
    st.plotly_chart(fig, use_container_width=True)


def trend(df: pd.DataFrame, col: str, unit: str, color: str, area: bool = False):
    data = df.dropna(subset=[col])
    if data.empty:
        st.info("No data yet for this reading.")
        return
    if area:
        fig = px.area(data, x="time", y=col, template="plotly_white")
    else:
        fig = px.line(data, x="time", y=col, markers=True, template="plotly_white")
    fig.update_traces(line_color=color, marker_color=color)
    fig.update_layout(height=340, xaxis_title="", yaxis_title=unit, margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, use_container_width=True)


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

    age = time.time() - latest["received_at"] / 1000
    live = age <= LIVE_WINDOW_S

    h1, h2 = st.columns([3, 1])
    with h1:
        st.title(f"⌚ {device}")
        st.caption(f"Last update {latest['time'].strftime('%d %b %Y, %H:%M:%S')} (UTC+{TZ_OFFSET_HOURS})")
    with h2:
        st.write("")
        if live:
            st.markdown('<span class="badge-live">● Live</span>', unsafe_allow_html=True)
        else:
            mins = int(age // 60)
            st.markdown(f'<span class="badge-off">● Offline · last seen {mins} min ago</span>',
                        unsafe_allow_html=True)

    temp_color = "#ef4444" if (not pd.isna(latest["temp"]) and latest["temp"] >= 38) else "#f97316"

    r1 = st.columns(4)
    r1[0].markdown(card("Temperature", val(latest["temp"], ".1f"), "°C", "🌡️", temp_color),
                   unsafe_allow_html=True)
    r1[1].markdown(card("Heart rate", val(latest["bpm"]), "BPM", "❤️", "#ef4444"),
                   unsafe_allow_html=True)
    r1[2].markdown(card("Blood oxygen", val(latest["spo2"]), "%", "🫁", "#3b82f6"),
                   unsafe_allow_html=True)
    r1[3].markdown(card("Steps today", val(latest["steps"], ",.0f"), "steps", "👣", "#22c55e"),
                   unsafe_allow_html=True)

    r2 = st.columns(4)
    r2[0].markdown(card("Distance today", val(latest["dist_km"], ".2f"), "km", "📍", "#8b5cf6"),
                   unsafe_allow_html=True)
    r2[1].markdown(card("Speed", val(latest["speed"], ".1f"), "km/h", "🚗", "#f59e0b"),
                   unsafe_allow_html=True)
    r2[2].markdown(card("Satellites", val(latest["sats"]), "in view", "🛰️", "#14b8a6"),
                   unsafe_allow_html=True)
    r2[3].markdown(card("Network", val(latest["signal_bars"]), "of 4 bars", "📶", "#6366f1"),
                   unsafe_allow_html=True)

    st.markdown('<div class="section">Device status</div>', unsafe_allow_html=True)
    g1, g2, g3, g4 = st.columns(4)
    with g1:
        gauge("Battery", latest["battery"], 0, 100, "%", "#22c55e",
              [{"range": [0, 20], "color": "#fee2e2"}, {"range": [20, 50], "color": "#fef3c7"},
               {"range": [50, 100], "color": "#dcfce7"}])
    with g2:
        gauge("Blood oxygen", latest["spo2"], 70, 100, "%", "#3b82f6",
              [{"range": [70, 90], "color": "#fee2e2"}, {"range": [90, 95], "color": "#fef3c7"},
               {"range": [95, 100], "color": "#dbeafe"}])
    with g3:
        gauge("Heart rate", latest["bpm"], 40, 180, " BPM", "#ef4444",
              [{"range": [40, 60], "color": "#dbeafe"}, {"range": [60, 100], "color": "#dcfce7"},
               {"range": [100, 180], "color": "#fee2e2"}])
    with g4:
        gauge("Signal", latest["signal_bars"], 0, 4, " / 4", "#6366f1",
              [{"range": [0, 2], "color": "#fee2e2"}, {"range": [2, 3], "color": "#fef3c7"},
               {"range": [3, 4], "color": "#dcfce7"}])

    st.divider()
    st.markdown('<div class="section">Trends</div>', unsafe_allow_html=True)
    tabs = st.tabs(["🌡️ Temperature", "❤️ Heart rate", "🫁 SpO2", "👣 Steps",
                    "📍 Distance", "🚗 Speed"])
    with tabs[0]:
        trend(df, "temp", "°C", "#f97316")
    with tabs[1]:
        trend(df, "bpm", "BPM", "#ef4444")
    with tabs[2]:
        trend(df, "spo2", "%", "#3b82f6")
    with tabs[3]:
        trend(df, "steps", "steps", "#22c55e", area=True)
    with tabs[4]:
        trend(df, "dist_km", "km", "#8b5cf6", area=True)
    with tabs[5]:
        trend(df, "speed", "km/h", "#f59e0b")

    st.divider()
    st.markdown('<div class="section">Location</div>', unsafe_allow_html=True)
    gps = df.dropna(subset=["lat", "lon"])
    gps = gps[(gps["lat"] != 0) & (gps["lon"] != 0)]
    if gps.empty:
        st.info("No GPS fix yet.")
    else:
        st.map(gps[["lat", "lon"]])

    with st.expander("Raw readings"):
        st.dataframe(df.iloc[::-1], use_container_width=True)


st.fragment(run_every=refresh_secs if auto_refresh else None)(live_view)()
