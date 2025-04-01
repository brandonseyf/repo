
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import os
import json
import re
from datetime import datetime, timedelta
from io import StringIO
from pytz import timezone

# === SETUP ===
st.set_page_config(page_title="🚛 Press Dashboard", layout="wide")
st.markdown("<h1 style='text-align: center;'>🚛 Press Cycle Insights Dashboard!</h1>", unsafe_allow_html=True)
st.markdown("---")

CACHE_DIR = ".streamlit_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
INDEX_FILE = os.path.join(CACHE_DIR, "file_index.json")
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
    r = requests.post(url, data=data)
    return r.json().get("access_token")

token = get_access_token()
headers = {"Authorization": f"Bearer {token}"} if token else {}

def get_all_files():
    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{folder_path}:/children"
    all_files = []
    while url:
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            break
        data = r.json()
        all_files.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return all_files

def load_index():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE) as f:
            return json.load(f)
    return {}

def save_index(index):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f)

def file_hash(f): return f"{f['size']}_{f['lastModifiedDateTime']}"

def latest_per_machine(files):
    latest = {}
    pattern = re.compile(r'(Presse\d).*?(\d{4}-\d{2}-\d{2})')
    for f in files:
        name = f["name"].strip()
        m = pattern.search(name)
        if m:
            machine, datestr = m.groups()
            try:
                dt = datetime.strptime(datestr, "%Y-%m-%d").date()
                if machine not in latest or dt > latest[machine][0]:
                    latest[machine] = (dt, f)
            except:
                continue
    return {k: v[1] for k, v in latest.items()}

@st.cache_data(show_spinner=True)
def fetch_data():
    files = get_all_files()
    csvs = [f for f in files if f["name"].lower().strip().endswith(".csv")]
    latest_files = latest_per_machine(csvs)
    old_index = load_index()
    new_index = {}
    new_data = []

    force_names = [v["name"].strip() for v in latest_files.values()]

    for f in csvs:
        name = f["name"].strip()
        new_index[name] = file_hash(f)
        is_latest = name in force_names
        changed = name not in old_index or file_hash(f) != old_index[name]

        if changed or is_latest:
            try:
                url = f["@microsoft.graph.downloadUrl"]
                try:
                    df = pd.read_csv(StringIO(requests.get(url).text))
                except:
                    df = pd.read_csv(StringIO(requests.get(url).content.decode("latin1")))
                if "Date" in df.columns and "Heure" in df.columns:
                    df["source_file"] = name
                    new_data.append(df)
            except:
                continue

    if os.path.exists(DATA_FILE):
        base = pd.read_parquet(DATA_FILE)
        base = base[~base["source_file"].isin(force_names)]
        combined = pd.concat([base] + new_data, ignore_index=True)
    else:
        combined = pd.concat(new_data, ignore_index=True) if new_data else pd.DataFrame()

    combined.to_parquet(DATA_FILE, index=False)
    save_index(new_index)
    return combined

with st.spinner("📥 Loading data from OneDrive..."):
    df = fetch_data()

if df.empty:
    st.error("No data found.")
    st.stop()

# === CLEAN ===
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

# === TIMEZONE ===
eastern = timezone("US/Eastern")
today = datetime.now(eastern).date()

min_date = df['DateOnly'].min()
max_date = df['DateOnly'].max()

def get_date_range(option):
    if option == "Today": return today, today
    elif option == "Yesterday": return today - timedelta(days=1), today - timedelta(days=1)
    elif option == "This Week": return today - timedelta(days=today.weekday()), today
    elif option == "Last Week": return today - timedelta(days=today.weekday() + 7), today - timedelta(days=today.weekday() + 1)
    elif option == "This Month": return today.replace(day=1), today
    elif option == "Last Month":
        first = today.replace(day=1)
        last = first - timedelta(days=1)
        return last.replace(day=1), last
    elif option == "This Year": return today.replace(month=1, day=1), today
    return min_date, max_date

# === FILTERS ===
with st.sidebar:
    st.header("🔍 Filters")
    preset = st.selectbox("Preset Date Range", ["Today", "Yesterday", "This Week", "Last Week", "This Month", "Last Month", "This Year", "Custom"], index=0)
    default_start, default_end = get_date_range(preset) if preset != "Custom" else (min_date, max_date)
    date_range = st.date_input("📅 Date Range", (default_start, default_end), min_value=min_date, max_value=max_date)
    shift_range = st.slider("🕐 Hour Range", 0, 23, (0, 23))
    machines = st.multiselect("🏭 Machines", ['400', '800'], default=['400', '800'])
    days = st.multiselect("📆 Days", ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
                          default=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])

start_date, end_date = date_range
filtered = df[
    (df['DateOnly'] >= start_date) &
    (df['DateOnly'] <= end_date) &
    (df['Hour'].between(*shift_range)) &
    (df['Machine'].isin(machines)) &
    (df['DayName'].isin(days))
]

st.markdown(f"### ✅ Showing {len(filtered):,} Cycles from {start_date} to {end_date}")

if filtered.empty:
    st.warning("⚠️ No data matches filters.")
    st.stop()

# === KPIs ===
start_ts = filtered['Timestamp'].min()
end_ts = filtered['Timestamp'].max()
duration_hours = (end_ts - start_ts).total_seconds() / 3600 if start_ts != end_ts else 1

total_cycles = len(filtered)
avg_per_hour = total_cycles / duration_hours
avg_cycle = filtered.get('Cycle de presse(secondes)', pd.Series()).mean()
avg_spread = filtered.get('Épandage(secondes)', pd.Series()).mean()
avg_down = filtered.get('Arrêt(secondes)', pd.Series()).mean()
prod_hours = filtered.groupby('DateOnly')['Timestamp'].agg(lambda x: (x.max() - x.min()).total_seconds() / 3600)
avg_prod = prod_hours.mean()

st.markdown("### 📊 Key Performance Metrics")
k1, k2, k3, k4 = st.columns(4)
k1.metric("🧮 Total Cycles", f"{total_cycles:,}")
k2.metric("⚡ Cycles per Hour", f"{avg_per_hour:.1f}")
k3.metric("🕐 Avg Prod Hours/Day", f"{avg_prod:.1f}")
k4.metric("⏱ Avg Cycle (min)", f"{avg_cycle:.1f}")

# === INSIGHT CHARTS ===
st.markdown("---")
st.subheader("📈 Insights")

c1, c2 = st.columns(2)
with c1:
    dow = filtered['DayName'].value_counts().reindex(
        ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']
    ).fillna(0).reset_index()
    dow.columns = ['Day', 'Cycles']
    fig1 = px.bar(dow, x='Day', y='Cycles', title="Busiest Days of Week")
    st.plotly_chart(fig1, use_container_width=True)

with c2:
    hourly = filtered['Hour'].value_counts().sort_index().reset_index()
    hourly.columns = ['Hour', 'Cycles']
    fig2 = px.bar(hourly, x='Hour', y='Cycles', title="Busiest Hours of Day")
    st.plotly_chart(fig2, use_container_width=True)

# === MACHINE STATS ===
st.subheader("🏭 Machine Breakdown")
totals_cols = [c for c in ['Cycle de presse(secondes)', 'Épandage(secondes)', 'Arrêt(secondes)'] if c in filtered.columns]
if totals_cols:
    machine_totals = filtered.groupby('Machine')[totals_cols].agg(['sum', 'mean'])
    st.dataframe(machine_totals)

# === EXPORT ===
st.download_button("⬇️ Download CSV", filtered.to_csv(index=False), file_name="filtered_press_data.csv")
