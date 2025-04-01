
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import json
import re
from datetime import datetime, timedelta
from io import StringIO
from pytz import timezone
import requests

# === PAGE CONFIG ===
st.set_page_config(page_title="🚛 Press Cycle Insights", layout="wide")

# === TITLE ===
st.markdown("<h1 style='text-align:center;'>🚛 Press Cycle Dashboard</h1>", unsafe_allow_html=True)

# === UTILS ===
CACHE_DIR = ".streamlit_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
DATA_FILE = os.path.join(CACHE_DIR, "combined_data.parquet")

client_id = st.secrets["onedrive"]["client_id"]
tenant_id = st.secrets["onedrive"]["tenant_id"]
client_secret = st.secrets["onedrive"]["client_secret"]
user_email = "brandon@presfab.ca"
folder_path = "Press"

def get_access_token():
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    return requests.post(url, data=data).json().get("access_token")

def get_latest_files(headers):
    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{folder_path}:/children"
    files, next_url = [], url
    while next_url:
        resp = requests.get(next_url, headers=headers).json()
        files += resp.get("value", [])
        next_url = resp.get("@odata.nextLink")
    return [f for f in files if f["name"].strip().lower().endswith(".csv")]

@st.cache_data(show_spinner=True)
def load_data():
    token = get_access_token()
    if not token:
        st.error("Auth failed")
        return pd.DataFrame()
    headers = {"Authorization": f"Bearer {token}"}
    files = get_latest_files(headers)
    combined = []
    for f in files:
        try:
            r = requests.get(f["@microsoft.graph.downloadUrl"])
            df = pd.read_csv(StringIO(r.text))
            if "Date" not in df or "Heure" not in df:
                continue
            df["source_file"] = f["name"]
            combined.append(df)
        except:
            continue
    if not combined:
        return pd.DataFrame()
    df = pd.concat(combined, ignore_index=True)
    df['Timestamp'] = pd.to_datetime(df['Date'] + " " + df['Heure'], errors='coerce')
    df = df[df['Timestamp'].notna()]
    df = df[~((df['Timestamp'].dt.year == 2019) & (df['Timestamp'].dt.month == 11))]
    df['Hour'] = df['Timestamp'].dt.hour
    df['DateOnly'] = df['Timestamp'].dt.date
    df['DayName'] = df['Timestamp'].dt.day_name()
    df['Machine'] = df['source_file'].str.extract(r'(Presse\d)', expand=False).replace({'Presse1': '400', 'Presse2': '800'})
    df['AMPM'] = df['Hour'].apply(lambda h: 'AM' if h < 13 else 'PM')
    df['Month'] = df['Timestamp'].dt.to_period('M').astype(str)
    for col in ['Épandage(secondes)', 'Cycle de presse(secondes)', 'Arrêt(secondes)']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce') / 60
    df.to_parquet(DATA_FILE, index=False)
    return df

df = load_data()
if df.empty:
    st.warning("No data.")
    st.stop()

# === DATE LOGIC ===
eastern = timezone("US/Eastern")
now = datetime.now(eastern)
today = now.date()
this_week_start = today - timedelta(days=today.weekday())
this_month_start = today.replace(day=1)

# === FILTER DATA ===
def filter_range(df, start, end):
    return df[(df['DateOnly'] >= start) & (df['DateOnly'] <= end)]

def kpi_block(data, label):
    total = len(data)
    avg_cycle = data['Cycle de presse(secondes)'].mean()
    avg_spread = data['Épandage(secondes)'].mean()
    avg_down = data['Arrêt(secondes)'].mean()
    hours = data.groupby('DateOnly')['Timestamp'].agg(lambda x: (x.max()-x.min()).total_seconds()/3600)
    avg_prod = hours.mean()
    st.markdown(f"### 📊 {label}")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🧮 Total Cycles", f"{total:,}")
    col2.metric("⏱ Avg Cycle (min)", f"{avg_cycle:.1f}")
    col3.metric("⚙️ Avg Spread (min)", f"{avg_spread:.1f}")
    col4.metric("🛑 Avg Downtime (min)", f"{avg_down:.1f}")
    st.markdown(f"🕐 **Avg Prod Hours/Day:** {avg_prod:.1f}")

# === MODULE: TODAY ===
st.markdown("---")
today_df = filter_range(df, today, today)
kpi_block(today_df, "Today")

# === MODULE: THIS WEEK ===
st.markdown("---")
week_df = filter_range(df, this_week_start, today)
kpi_block(week_df, "This Week")

# === MODULE: THIS MONTH ===
st.markdown("---")
month_df = filter_range(df, this_month_start, today)
kpi_block(month_df, "This Month")

# === AM/PM STACKED CHART ===
st.markdown("---")
st.subheader("🌗 AM/PM Breakdown")
grouped = df.groupby([df['Timestamp'].dt.date, 'AMPM']).size().reset_index(name='Cycles')
grouped.columns = ['Date', 'AMPM', 'Cycles']
fig = px.bar(grouped, x='Date', y='Cycles', color='AMPM', barmode='stack', title="Cycles by Day (AM/PM)", text='Cycles')
fig.update_traces(textposition='inside')
st.plotly_chart(fig, use_container_width=True)

# === HOURLY CHART ===
st.subheader("⏰ Busiest Hours of the Day")
hourly = df['Hour'].value_counts().sort_index().reset_index()
hourly.columns = ['Hour', 'Cycles']
fig2 = px.bar(hourly, x='Hour', y='Cycles', title="Cycles by Hour", text='Cycles')
fig2.update_traces(textposition='outside')
st.plotly_chart(fig2, use_container_width=True)

# === PER MACHINE ===
st.subheader("🏭 Machine Stats")
totals = df.groupby('Machine')[['Cycle de presse(secondes)', 'Épandage(secondes)', 'Arrêt(secondes)']].agg(['sum', 'mean']).round(1)
st.dataframe(totals)

# === EXPORT ===
st.download_button("⬇️ Download CSV", df.to_csv(index=False), file_name="full_press_data.csv")
