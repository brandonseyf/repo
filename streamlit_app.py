
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from datetime import datetime, timedelta
from io import StringIO

st.set_page_config(page_title="🚛 Press Dashboard", layout="wide")
try:
    st.image("Logo.png", width=200)
except Exception:
    st.info("ℹ️ Logo not found, skipping logo.")
st.title("🚛 Press Cycle Dashboard")

# === LOAD SECRETS ===
client_id = st.secrets["onedrive"]["client_id"]
tenant_id = st.secrets["onedrive"]["tenant_id"]
client_secret = st.secrets["onedrive"]["client_secret"]
folder_path = st.secrets["onedrive"]["folder_path"]

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

# === GET FILES ===
drive_url = "https://graph.microsoft.com/v1.0/me/drive/root:/Press:/children"
resp = requests.get(drive_url, headers=headers)
items = resp.json().get("value", [])
csv_files = [f for f in items if f['name'].lower().endswith(".csv")]

if not csv_files:
    st.warning("📂 No CSV files found.")
    st.stop()

# === LOAD CSVs ===
valid_dfs = []
skipped = []

with st.spinner("📥 Loading CSVs..."):
    for file in csv_files:
        name = file["name"]
        try:
            url = file["@microsoft.graph.downloadUrl"]
            csv_text = requests.get(url).text
            df = pd.read_csv(StringIO(csv_text))
            df.columns = df.columns.str.strip()

            if not {"Date", "Heure"}.issubset(df.columns):
                skipped.append(f"{name} ❌ Missing Date or Heure")
                continue

            df["source_file"] = name
            df["Timestamp"] = pd.to_datetime(df["Date"].astype(str) + " " + df["Heure"].astype(str), errors='coerce')
            df = df[df["Timestamp"].notna()]
            df["Missing"] = ", ".join([col for col in ['Arrêt(secondes)', 'Épandage(secondes)', 'Cycle de presse(secondes)'] if col not in df.columns])
            valid_dfs.append(df)

        except Exception as e:
            skipped.append(f"{name} ❌ {e}")

if not valid_dfs:
    st.error("❌ No usable data.")
    st.stop()

df = pd.concat(valid_dfs, ignore_index=True)

# === Process Data ===
df = df[~((df["Timestamp"].dt.year == 2019) & (df["Timestamp"].dt.month == 11))]
df["Hour"] = df["Timestamp"].dt.hour
df["DateOnly"] = df["Timestamp"].dt.date
df["DayName"] = df["Timestamp"].dt.day_name()
df["Machine"] = df["source_file"].str.extract(r'(Presse\d)', expand=False).replace({"Presse1": "400", "Presse2": "800"})
df["AMPM"] = pd.Categorical(df["Hour"].apply(lambda h: "AM" if h < 13 else "PM"), categories=["AM", "PM"], ordered=True)

for col in ['Arrêt(secondes)', 'Épandage(secondes)', 'Cycle de presse(secondes)']:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce") / 60

# === Filters ===
min_date = df["Timestamp"].dt.date.min()
max_date = df["Timestamp"].dt.date.max()
default_start = max_date - timedelta(days=6)

with st.expander("🔍 Filters", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        date_range = st.date_input("📅 Date Range", (default_start, max_date), min_value=min_date, max_value=max_date)
        shift_range = st.slider("🕐 Hour Range", 0, 23, (0, 23))
        machines = st.multiselect("🏭 Machines", ['400', '800'], default=['400', '800'])
    with col2:
        days = st.multiselect("📆 Days", ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'],
                              default=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])
        show_raw = st.checkbox("👁 Show Raw Table", False)

start_date, end_date = date_range
filtered = df[
    (df["Timestamp"].dt.date >= start_date) &
    (df["Timestamp"].dt.date <= end_date) &
    (df["Hour"].between(*shift_range)) &
    (df["Machine"].isin(machines)) &
    (df["DayName"].isin(days))
]

st.markdown(f"### ✅ {len(filtered)} Cycles from {start_date} to {end_date}")
if filtered.empty:
    st.warning("⚠️ No data matches filters.")
    st.stop()

# === KPIs ===
start_ts = filtered["Timestamp"].min()
end_ts = filtered["Timestamp"].max()
duration_hours = max((end_ts - start_ts).total_seconds() / 3600, 1)
total_cycles = len(filtered)
avg_per_hour = total_cycles / duration_hours
avg_cycle = filtered['Cycle de presse(secondes)'].mean() if 'Cycle de presse(secondes)' in filtered else 0

col1, col2, col3 = st.columns(3)
col1.metric("🧮 Total Cycles", f"{total_cycles:,}")
col2.metric("⚡ Cycles/Hour", f"{avg_per_hour:.1f}")
col3.metric("⏱ Avg Cycle (min)", f"{avg_cycle:.1f}")

# === Charts ===
st.subheader("📊 AM/PM Breakdown")
if (end_date - start_date).days <= 1:
    grouped = filtered.groupby(['Hour', 'AMPM']).size().reset_index(name='Cycles')
    fig = px.bar(grouped, x='Hour', y='Cycles', color='AMPM', barmode='stack')
else:
    grouped = filtered.groupby([filtered['Timestamp'].dt.date, 'AMPM']).size().reset_index(name='Cycles')
    grouped.columns = ['Date', 'AMPM', 'Cycles']
    fig = px.bar(grouped, x='Date', y='Cycles', color='AMPM', barmode='stack')
st.plotly_chart(fig, use_container_width=True)

if show_raw:
    st.subheader("📄 Raw Data")
    st.dataframe(filtered)

st.download_button("⬇️ Download Filtered CSV", filtered.to_csv(index=False), file_name="filtered_press_data.csv")

if skipped:
    with st.expander("⚠️ Skipped Files", expanded=False):
        for s in skipped:
            st.write("-", s)
