
import streamlit as st
import pandas as pd
import plotly.express as px
import os
import json
import requests
from datetime import datetime, timedelta
from io import StringIO
from pytz import timezone

# === CONFIG ===
st.set_page_config(page_title="🚛 Press Dashboard", layout="wide")
st.markdown("<h1 style='text-align:center;'>🚛 Press Cycle Dashboard</h1>", unsafe_allow_html=True)

CACHE_DIR = ".streamlit_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
DATA_FILE = os.path.join(CACHE_DIR, "combined_data.parquet")
INDEX_FILE = os.path.join(CACHE_DIR, "file_index.json")

client_id = st.secrets["onedrive"]["client_id"]
tenant_id = st.secrets["onedrive"]["tenant_id"]
client_secret = st.secrets["onedrive"]["client_secret"]
user_email = "brandon@presfab.ca"
folder_path = "Press"

# === AUTH ===
def get_access_token():
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    return requests.post(url, data=data).json().get("access_token")

def get_drive_files(headers):
    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{folder_path}:/children"
    all_files, next_url = [], url
    while next_url:
        resp = requests.get(next_url, headers=headers).json()
        all_files.extend(resp.get("value", []))
        next_url = resp.get("@odata.nextLink")
    return [f for f in all_files if f["name"].strip().lower().endswith(".csv")]

def load_index():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r") as f:
            return json.load(f)
    return {}

def save_index(index):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f)

@st.cache_data(show_spinner=True)
def load_data():
    token = get_access_token()
    if not token:
        st.error("Auth failed.")
        return pd.DataFrame()

    headers = {"Authorization": f"Bearer {token}"}
    current_files = get_drive_files(headers)
    cached_index = load_index()
    new_index = {}
    files_to_load = []

    for f in current_files:
        name = f["name"]
        modified = f.get("lastModifiedDateTime", "")
        new_index[name] = modified
        if name not in cached_index or cached_index[name] != modified:
            files_to_load.append(f)

    def latest_file(machine):
        candidates = [f for f in current_files if machine in f["name"]]
        return max(candidates, key=lambda x: x.get("name", ""), default=None)

    for machine in ["Presse1", "Presse2"]:
        latest = latest_file(machine)
        if latest and latest not in files_to_load:
            files_to_load.append(latest)

    loaded = []
    for f in files_to_load:
        try:
            csv = requests.get(f["@microsoft.graph.downloadUrl"]).text
            df = pd.read_csv(StringIO(csv))
            if "Date" not in df.columns or "Heure" not in df.columns:
                continue
            df["source_file"] = f["name"]
            loaded.append(df)
        except:
            continue

    existing = pd.read_parquet(DATA_FILE) if os.path.exists(DATA_FILE) else pd.DataFrame()
    combined = pd.concat([existing] + loaded, ignore_index=True).drop_duplicates() if loaded else existing
    if not combined.empty:
        combined.to_parquet(DATA_FILE, index=False)
        save_index(new_index)

    df = combined.copy()
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
    return df

df = load_data()
if df.empty:
    st.warning("No data.")
    st.stop()

# === TIME RANGE ===
eastern = timezone("US/Eastern")
now = datetime.now(eastern)
today = now.date()
this_week = today - timedelta(days=today.weekday())
this_month = today.replace(day=1)

def show_kpis(data, label):
    st.markdown(f"### 📊 {label}")
    total = len(data)
    avg_cycle = data['Cycle de presse(secondes)'].mean()
    avg_spread = data['Épandage(secondes)'].mean()
    avg_down = data['Arrêt(secondes)'].mean()
    hours = data.groupby('DateOnly')['Timestamp'].agg(lambda x: (x.max()-x.min()).total_seconds()/3600)
    avg_prod = hours.mean()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🧮 Total Cycles", f"{total:,}")
    c2.metric("⏱ Avg Cycle (min)", f"{avg_cycle:.1f}")
    c3.metric("⚙️ Avg Spread (min)", f"{avg_spread:.1f}")
    c4.metric("🛑 Avg Downtime (min)", f"{avg_down:.1f}")
    st.markdown(f"🕐 **Avg Prod Hours/Day:** {avg_prod:.1f}")

# === MODULES ===
st.markdown("---")
show_kpis(df[df["DateOnly"] == today], "Today")
st.markdown("---")
show_kpis(df[df["DateOnly"].between(this_week, today)], "This Week")
st.markdown("---")
show_kpis(df[df["DateOnly"].between(this_month, today)], "This Month")

# === CHART: AM/PM ===
st.markdown("---")
st.subheader("🌗 AM/PM Breakdown")
grouped = df.groupby([df['DateOnly'], 'AMPM']).size().reset_index(name='Cycles')
fig = px.bar(grouped, x='DateOnly', y='Cycles', color='AMPM', barmode='stack', title="Cycles by Day (AM/PM)", text='Cycles')
fig.update_traces(textposition='inside')
st.plotly_chart(fig, use_container_width=True)

# === CHART: HOURLY ===
st.subheader("⏰ Busiest Hours")
hourly = df['Hour'].value_counts().sort_index().reset_index()
hourly.columns = ['Hour', 'Cycles']
fig2 = px.bar(hourly, x='Hour', y='Cycles', title="Cycles by Hour", text='Cycles')
fig2.update_traces(textposition='outside')
st.plotly_chart(fig2, use_container_width=True)

# === TABLE: MACHINE ===
st.subheader("🏭 Machine Stats")
totals = df.groupby('Machine')[['Cycle de presse(secondes)', 'Épandage(secondes)', 'Arrêt(secondes)']].agg(['sum', 'mean']).round(1)
st.dataframe(totals)

# === EXPORT ===
st.download_button("⬇️ Download CSV", df.to_csv(index=False), file_name="full_press_data.csv")
