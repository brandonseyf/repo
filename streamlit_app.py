
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from datetime import datetime
from io import StringIO

st.set_page_config(page_title="🚛 Press Debug Dashboard", layout="wide")
st.title("🛠️ Press Debug Dashboard")

# === SECRETS ===
client_id = st.secrets["onedrive"]["client_id"]
tenant_id = st.secrets["onedrive"]["tenant_id"]
client_secret = st.secrets["onedrive"]["client_secret"]
user_email = "brandon@presfab.ca"
folder_path = "Press"

# === AUTH ===
auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
auth_data = {
    "grant_type": "client_credentials",
    "client_id": client_id,
    "client_secret": client_secret,
    "scope": "https://graph.microsoft.com/.default"
}
auth_response = requests.post(auth_url, data=auth_data)
access_token = auth_response.json().get("access_token")

if not access_token:
    st.error("❌ Authentication failed.")
    st.stop()

headers = {"Authorization": f"Bearer {access_token}"}

# === DRIVE ID ===
drive_resp = requests.get(f"https://graph.microsoft.com/v1.0/users/{user_email}/drive", headers=headers)
drive_id = drive_resp.json().get("id")
if not drive_id:
    st.error("❌ Could not get user drive ID.")
    st.stop()

# === FILE LISTING ===
press_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder_path}:/children"
resp = requests.get(press_url, headers=headers)
files = resp.json().get("value", [])
csv_files = [f for f in files if f["name"].strip().lower().endswith(".csv")]

if not csv_files:
    st.warning("📂 No CSV files found.")
    st.stop()

# === LOAD CSVs WITH DEBUG ===
@st.cache_data
def load_debug_csvs():
    dfs = []
    skipped = []
    for file in csv_files:
        download_url = file["@microsoft.graph.downloadUrl"]
        try:
            csv_resp = requests.get(download_url)
            try:
                df = pd.read_csv(StringIO(csv_resp.text))
            except UnicodeDecodeError:
                df = pd.read_csv(StringIO(csv_resp.content.decode("ISO-8859-1")))
            df["source_file"] = file["name"]
            dfs.append(df)
        except Exception as e:
            skipped.append((file["name"], str(e)))
    return dfs, skipped

with st.spinner("🔍 Loading all CSV files with debug..."):
    dfs, skipped_files = load_debug_csvs()

if not dfs:
    st.error("No valid data loaded.")
    st.stop()

# Combine and parse
df = pd.concat(dfs, ignore_index=True)
df['Timestamp'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Heure'].astype(str), errors='coerce')
df = df[df['Timestamp'].notna()]
df['source_file'] = df['source_file'].str.strip()

# Show file summary
st.subheader("📄 Parsed Files Summary")
summary = df.groupby("source_file")["Timestamp"].agg(["min", "max", "count"]).reset_index()
summary.columns = ["File", "Earliest Timestamp", "Latest Timestamp", "Cycle Count"]
st.dataframe(summary.sort_values("Earliest Timestamp"))

# Show skipped files
if skipped_files:
    st.subheader("⚠️ Skipped Files")
    for name, reason in skipped_files:
        st.warning(f"{name}: {reason}")
