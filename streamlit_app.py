
import streamlit as st
import pandas as pd
import requests
import os
import json
from datetime import datetime
from io import StringIO
from hashlib import md5

st.set_page_config(page_title="🚛 Optimized Press Dashboard", layout="wide")
st.title("🚛 Press Dashboard (OneDrive Optimized)")

# === CONFIG ===
CACHE_DIR = ".streamlit_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
INDEX_FILE = os.path.join(CACHE_DIR, "file_index.json")
DATA_FILE = os.path.join(CACHE_DIR, "combined_data.parquet")

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
    r = requests.post(url, data=data)
    return r.json().get("access_token")

token = get_access_token()
if not token:
    st.error("❌ Failed to authenticate with Microsoft Graph.")
    st.stop()

headers = {"Authorization": f"Bearer {token}"}

# === PAGINATED FILE FETCH ===
@st.cache_data(show_spinner=False)
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

# === LOAD FILE INDEX ===
def load_index():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r") as f:
            return json.load(f)
    return {}

# === SAVE FILE INDEX ===
def save_index(index):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f)

# === HASH TO DETECT CHANGES ===
def file_hash(metadata):
    return f"{metadata['size']}_{metadata['lastModifiedDateTime']}"

# === PROCESS NEW OR CHANGED FILES ===
@st.cache_data(show_spinner=False)
def update_data():
    files = get_all_files()
    csvs = [f for f in files if f["name"].strip().lower().endswith(".csv")]
    old_index = load_index()
    new_index = {}
    new_data = []

    for f in csvs:
        fname = f["name"].strip()
        fid = f["id"]
        meta_hash = file_hash(f)
        new_index[fname] = meta_hash
        if fname not in old_index or old_index[fname] != meta_hash:
            download_url = f["@microsoft.graph.downloadUrl"]
            try:
                try:
                    df = pd.read_csv(StringIO(requests.get(download_url).text))
                except:
                    df = pd.read_csv(StringIO(requests.get(download_url).content.decode("latin1")))
                if "Date" in df.columns and "Heure" in df.columns:
                    df["source_file"] = fname
                    new_data.append(df)
            except Exception as e:
                print(f"Failed to load {fname}: {e}")

    if os.path.exists(DATA_FILE):
        base = pd.read_parquet(DATA_FILE)
        combined = pd.concat([base] + new_data, ignore_index=True)
    else:
        combined = pd.concat(new_data, ignore_index=True) if new_data else pd.DataFrame()

    combined.to_parquet(DATA_FILE, index=False)
    save_index(new_index)
    return combined

# === LOAD OR UPDATE DATA ===
with st.spinner("📥 Loading & caching press data..."):
    df = update_data()

if df.empty:
    st.warning("⚠️ No valid data loaded.")
    st.stop()

# === CLEANING ===
df['Timestamp'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Heure'].astype(str), errors='coerce')
df = df[df['Timestamp'].notna()]
df = df[~((df['Timestamp'].dt.year == 2019) & (df['Timestamp'].dt.month == 11))]
df['Hour'] = df['Timestamp'].dt.hour
df['DateOnly'] = df['Timestamp'].dt.date
df['DayName'] = df['Timestamp'].dt.day_name()
df['Machine'] = df['source_file'].str.extract(r'(Presse\d)', expand=False)
df['Machine'] = df['Machine'].replace({'Presse1': '400', 'Presse2': '800'})
df['AMPM'] = df['Hour'].apply(lambda h: 'AM' if h < 13 else 'PM')

for col in ['Épandage(secondes)', 'Cycle de presse(secondes)', 'Arrêt(secondes)']:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce') / 60

# === UI ===
min_date = df['Timestamp'].dt.date.min()
max_date = df['Timestamp'].dt.date.max()
default_start = max_date - pd.Timedelta(days=7)

with st.expander("🔍 Filters", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        date_range = st.date_input("📅 Date Range", (default_start, max_date), min_value=min_date, max_value=max_date)
        shift_range = st.slider("🕐 Hour Range", 0, 23, (0, 23))
        machines = st.multiselect("🏭 Machines", ['400', '800'], default=['400', '800'])
    with col2:
        days = st.multiselect("📆 Days", ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
                              default=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])
        show_raw = st.checkbox("👁 Show Raw Table", value=False)

start_date, end_date = date_range
filtered = df[
    (df['Timestamp'].dt.date >= start_date) &
    (df['Timestamp'].dt.date <= end_date) &
    (df['Hour'].between(*shift_range)) &
    (df['Machine'].isin(machines)) &
    (df['DayName'].isin(days))
]

st.markdown(f"### ✅ {len(filtered)} Cycles from {start_date} to {end_date}")
if filtered.empty:
    st.warning("⚠️ No data matches filters.")
    st.stop()

# === KPIs ===
start_ts = filtered['Timestamp'].min()
end_ts = filtered['Timestamp'].max()
duration_hours = (end_ts - start_ts).total_seconds() / 3600 if start_ts != end_ts else 1

total_cycles = len(filtered)
avg_per_hour = total_cycles / duration_hours
avg_cycle = filtered['Cycle de presse(secondes)'].mean() if 'Cycle de presse(secondes)' in filtered.columns else 0

col1, col2, col3 = st.columns(3)
col1.metric("🧮 Total Cycles", f"{total_cycles:,}")
col2.metric("⚡ Cycles/Hour", f"{avg_per_hour:.1f}")
col3.metric("⏱ Avg Cycle (min)", f"{avg_cycle:.1f}")

# === CHART ===
st.subheader("📊 AM/PM Breakdown")
filtered['AMPM'] = pd.Categorical(filtered['AMPM'], categories=['AM', 'PM'], ordered=True)

grouped = filtered.groupby([filtered['Timestamp'].dt.date, 'AMPM']).size().reset_index(name='Cycles')
grouped.columns = ['Date', 'AMPM', 'Cycles']
fig = px.bar(grouped, x='Date', y='Cycles', color='AMPM', barmode='stack')
st.plotly_chart(fig, use_container_width=True)

if show_raw:
    st.subheader("📄 Filtered Data")
    st.dataframe(filtered)

st.download_button("⬇️ Download Filtered CSV", filtered.to_csv(index=False), file_name="filtered_press_data.csv")
