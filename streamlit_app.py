
import streamlit as st
import pandas as pd
import plotly.express as px
import os
import json
import re
from datetime import datetime, timedelta
from io import StringIO
import requests
from pytz import timezone

st.set_page_config(page_title="🚛 Press Dashboard", layout="wide")
st.title("🚛 Press Cycle Dashboard")

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

# === UTILS ===
def get_access_token():
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default"
    }
    return requests.post(url, data=data).json().get("access_token")

def get_files(headers):
    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{folder_path}:/children"
    all_files = []
    while url:
        resp = requests.get(url, headers=headers).json()
        all_files.extend(resp.get("value", []))
        url = resp.get("@odata.nextLink")
    return [f for f in all_files if f["name"].strip().lower().endswith(".csv")]

def file_hash(f): return f"{f['size']}_{f['lastModifiedDateTime']}"

def load_index():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE) as f:
            return json.load(f)
    return {}

def save_index(index):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f)

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

# === MAIN LOAD FUNCTION ===
@st.cache_data(show_spinner=False)
def load_data(force=False):
    token = get_access_token()
    if not token:
        st.error("❌ Authentication failed.")
        return pd.DataFrame()
    headers = {"Authorization": f"Bearer {token}"}

    files = get_files(headers)
    latest_files = latest_per_machine(files)
    old_index = load_index()
    new_index = {}
    new_data = []
    total = len(files)

    with st.spinner(f"📦 Checking {total} files..."):
        for f in files:
            name = f["name"].strip()
            is_latest = name in [v["name"].strip() for v in latest_files.values()]
            changed = name not in old_index or file_hash(f) != old_index[name]

            new_index[name] = file_hash(f)
            if not changed and not is_latest and not force:
                continue
            try:
                r = requests.get(f["@microsoft.graph.downloadUrl"])
                try:
                    df = pd.read_csv(StringIO(r.text))
                except:
                    df = pd.read_csv(StringIO(r.content.decode("latin1")))
                if "Date" in df and "Heure" in df:
                    df["source_file"] = name
                    new_data.append(df)
            except Exception as e:
                continue

    if os.path.exists(DATA_FILE) and not force:
        base = pd.read_parquet(DATA_FILE)
        base = base[~base["source_file"].isin([d["name"] for d in latest_files.values()])]
        combined = pd.concat([base] + new_data, ignore_index=True) if new_data else base
    else:
        combined = pd.concat(new_data, ignore_index=True) if new_data else pd.DataFrame()

    combined.to_parquet(DATA_FILE, index=False)
    save_index(new_index)

    st.success(f"✅ Loaded {len(combined):,} rows from {len(new_data)} new/updated file(s).")
    return combined

# === LOAD ===
force_reload = st.sidebar.checkbox("🔄 Force Full Reload", value=False)
df = load_data(force=force_reload)

if df.empty:
    st.warning("⚠️ No data available.")
    st.stop()

# === CLEAN ===
df['Timestamp'] = pd.to_datetime(df['Date'] + " " + df['Heure'], errors='coerce')
df = df[df['Timestamp'].notna()]
df['DateOnly'] = df['Timestamp'].dt.date
min_date, max_date = df['DateOnly'].min(), df['DateOnly'].max()
st.success(f"📅 Date Range: {min_date} → {max_date}")
