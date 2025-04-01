
# ✅ SMART STREAMLIT DASHBOARD with ONEDRIVE CSV CACHE
import streamlit as st
import pandas as pd
import plotly.express as px
import os, json, requests
from datetime import datetime
from io import StringIO

# === CONFIG ===
st.set_page_config(page_title="🚛 Press Dashboard", layout="wide")
st.title("🚛 Press Cycle Dashboard (Smart Cache)")

client_id = st.secrets["onedrive"]["client_id"]
tenant_id = st.secrets["onedrive"]["tenant_id"]
client_secret = st.secrets["onedrive"]["client_secret"]
user_email = "brandon@presfab.ca"
folder_path = "Press"

CACHE_DIR = ".streamlit_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_FILE = os.path.join(CACHE_DIR, "combined_data.parquet")
INDEX_FILE = os.path.join(CACHE_DIR, "file_index.json")

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

def list_files(headers):
    url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{folder_path}:/children"
    files, next_url = [], url
    while next_url:
        r = requests.get(next_url, headers=headers).json()
        files += r.get("value", [])
        next_url = r.get("@odata.nextLink")
    return [f for f in files if f["name"].strip().lower().endswith(".csv")]

def load_cached_index():
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r") as f:
            return json.load(f)
    return {}

def save_index(index):
    with open(INDEX_FILE, "w") as f:
        json.dump(index, f)

def fetch_and_process(files, headers, previous_index):
    combined = []
    new_index = {}
    press_latest = {"Presse1": None, "Presse2": None}

    for f in files:
        name = f["name"]
        modified = f["lastModifiedDateTime"]
        machine = "Presse1" if "Presse1" in name else "Presse2" if "Presse2" in name else None
        new_index[name] = modified

        is_new = name not in previous_index or previous_index[name] != modified
        if is_new or (
            machine and (
                not press_latest[machine] or name > press_latest[machine]["name"]
            )
        ):
            if machine:
                press_latest[machine] = f
            else:
                r = requests.get(f["@microsoft.graph.downloadUrl"])
                df = pd.read_csv(StringIO(r.text))
                df["source_file"] = name
                combined.append(df)

    for machine in ["Presse1", "Presse2"]:
        f = press_latest[machine]
        if f:
            r = requests.get(f["@microsoft.graph.downloadUrl"])
            df = pd.read_csv(StringIO(r.text))
            df["source_file"] = f["name"]
            combined.append(df)

    return combined, new_index

@st.cache_data(show_spinner="📦 Loading OneDrive CSV files...")
def load_data():
    token = get_access_token()
    if not token:
        st.error("Auth failed.")
        return pd.DataFrame()
    headers = {"Authorization": f"Bearer {token}"}
    files = list_files(headers)
    previous_index = load_cached_index()
    new_data, new_index = fetch_and_process(files, headers, previous_index)

    if os.path.exists(CACHE_FILE):
        df = pd.read_parquet(CACHE_FILE)
    else:
        df = pd.DataFrame()

    if new_data:
        df_new = pd.concat(new_data, ignore_index=True)
        df = pd.concat([df, df_new], ignore_index=True)
        df.drop_duplicates(inplace=True)
        df.to_parquet(CACHE_FILE, index=False)
        save_index(new_index)

    return df

# === PROCESS DATA ===
df = load_data()
if df.empty:
    st.warning("No data loaded.")
    st.stop()

st.success(f"✅ Loaded {len(df):,} rows.")
st.dataframe(df.head(20))
