
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from datetime import datetime
from io import StringIO

st.set_page_config(page_title="🚛 Press Dashboard", layout="wide")
st.title("🚛 Press Cycle Dashboard")

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

# === LOAD CSVs SAFELY ===
@st.cache_data
def load_csv_files():
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

with st.spinner("📥 Loading files from OneDrive..."):
    dfs, skipped = load_csv_files()

if not dfs:
    st.error("❌ No valid data loaded.")
    st.stop()

# === COMBINE AND PROCESS ===
df = pd.concat(dfs, ignore_index=True)
df['Timestamp'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Heure'].astype(str), errors='coerce')
df = df[df['Timestamp'].notna()]
df = df[~((df['Timestamp'].dt.year == 2019) & (df['Timestamp'].dt.month == 11))]

df['Hour'] = df['Timestamp'].dt.hour
df['DateOnly'] = df['Timestamp'].dt.date
df['DayName'] = df['Timestamp'].dt.day_name()
df['Machine'] = df['source_file'].str.extract(r'(Presse\d)', expand=False)
df['Machine'] = df['Machine'].replace({'Presse1': '400', 'Presse2': '800'})
df['AMPM'] = df['Hour'].apply(lambda h: 'AM' if h < 13 else 'PM')

# === SAFELY CONVERT COLUMNS TO MINUTES ===
expected_cols = ['Épandage(secondes)', 'Cycle de presse(secondes)', 'Arrêt(secondes)']
available_cols = [col for col in expected_cols if col in df.columns]

if not available_cols:
    st.error("❌ None of the expected columns found.")
    st.stop()

for col in available_cols:
    df[col] = pd.to_numeric(df[col], errors='coerce') / 60

# === FILTERS ===
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

if (end_date - start_date).days <= 1:
    grouped = filtered.groupby(['Hour', 'AMPM']).size().reset_index(name='Cycles')
    fig = px.bar(grouped, x='Hour', y='Cycles', color='AMPM', barmode='stack')
else:
    grouped = filtered.groupby([filtered['Timestamp'].dt.date, 'AMPM']).size().reset_index(name='Cycles')
    grouped.columns = ['Date', 'AMPM', 'Cycles']
    fig = px.bar(grouped, x='Date', y='Cycles', color='AMPM', barmode='stack')

st.plotly_chart(fig, use_container_width=True)

# === RAW ===
if show_raw:
    st.subheader("📄 Filtered Data")
    st.dataframe(filtered)

# === EXPORT ===
st.download_button("⬇️ Download Filtered CSV", filtered.to_csv(index=False), file_name="filtered_press_data.csv")

# === SKIPPED FILES LOG ===
if skipped:
    st.subheader("⚠️ Skipped Files")
    for name, error in skipped:
        st.warning(f"{name}: {error}")
