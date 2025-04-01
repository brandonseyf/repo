import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from io import StringIO
from datetime import datetime, timedelta

# === PAGE CONFIG ===
st.set_page_config(page_title="🚛 Press Dashboard", layout="wide")
st.image("Logo.png", width=250)
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

# === GET DRIVE ITEMS ===
drive_url = f"https://graph.microsoft.com/v1.0/me/drive/root:/{folder_path}:/children"
drive_response = requests.get(drive_url, headers=headers).json()
items = drive_response.get("value", [])

# === FILTER CSV FILES ===
csv_files = [item for item in items if item["name"].lower().strip().endswith(".csv")]

if not csv_files:
    st.warning("📂 No CSV files found in OneDrive folder.")
    st.stop()

# === LOAD CSV DATA ===
@st.cache_data
def load_data():
    dfs = []
    skipped = []
    for file in csv_files:
        try:
            url = file["@microsoft.graph.downloadUrl"]
            content = requests.get(url).text
            df = pd.read_csv(StringIO(content))
            df.columns = df.columns.str.strip()
            required = ['Date', 'Heure', 'Cycle de presse(secondes)', 'Épandage(secondes)', 'Arrêt(secondes)']
            if not all(col in df.columns for col in required):
                skipped.append(file["name"])
                continue
            df["source_file"] = file["name"]
            dfs.append(df)
        except Exception as e:
            skipped.append(f"{file['name']}: {e}")
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame(), skipped

with st.spinner("📥 Loading data from OneDrive..."):
    df, skipped_files = load_data()

if skipped_files:
    st.warning(f"⚠️ Skipped {len(skipped_files)} file(s):\n\n" + "\n".join(skipped_files[:5]) + ("..." if len(skipped_files) > 5 else ""))

if df.empty:
    st.error("❌ No valid data to display.")
    st.stop()

# === CLEAN DATA ===
df['Timestamp'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Heure'].astype(str), errors='coerce')
df = df[df['Timestamp'].notna()]
df = df[~((df['Timestamp'].dt.year == 2019) & (df['Timestamp'].dt.month == 11))]  # Remove Nov 2019

df['Hour'] = df['Timestamp'].dt.hour
df['DateOnly'] = df['Timestamp'].dt.date
df['DayName'] = df['Timestamp'].dt.day_name()
df['Machine'] = df['source_file'].str.extract(r'(Presse\d)', expand=False).replace({'Presse1': '400', 'Presse2': '800'})
df['AMPM'] = pd.Categorical(df['Hour'].apply(lambda h: 'AM' if h < 13 else 'PM'), categories=['AM', 'PM'], ordered=True)

for col in ['Épandage(secondes)', 'Cycle de presse(secondes)', 'Arrêt(secondes)']:
    df[col] = pd.to_numeric(df[col], errors='coerce') / 60

# === FILTERS ===
min_date = df['Timestamp'].dt.date.min()
max_date = df['Timestamp'].dt.date.max()
default_start = max_date - timedelta(days=6)

with st.expander("🔍 Filters", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        date_range = st.date_input("📅 Date Range", (default_start, max_date), min_value=min_date, max_value=max_date)
        shift_range = st.slider("🕐 Hour Range", 0, 23, (0, 23))
        machines = st.multiselect("🏭 Machines", ['400', '800'], default=['400', '800'])
    with col2:
        days = st.multiselect("📆 Days", ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
                              default=['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
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
duration_hours = max((end_ts - start_ts).total_seconds() / 3600, 1)

col1, col2, col3 = st.columns(3)
col1.metric("🧮 Total Cycles", f"{len(filtered):,}")
col2.metric("⚡ Cycles/Hour", f"{len(filtered)/duration_hours:.1f}")
col3.metric("⏱ Avg Cycle (min)", f"{filtered['Cycle de presse(secondes)'].mean():.1f}")

# === AM/PM STACKED BAR ===
st.subheader("📊 AM/PM Trend")
if (end_date - start_date).days <= 1:
    grouped = filtered.groupby(['Hour', 'AMPM']).size().reset_index(name='Cycles')
    fig = px.bar(grouped, x='Hour', y='Cycles', color='AMPM', barmode='stack')
else:
    grouped = filtered.groupby([filtered['Timestamp'].dt.date, 'AMPM']).size().reset_index(name='Cycles')
    grouped.columns = ['Date', 'AMPM', 'Cycles']
    fig = px.bar(grouped, x='Date', y='Cycles', color='AMPM', barmode='stack')

st.plotly_chart(fig, use_container_width=True)

# === RAW TABLE ===
if show_raw:
    st.subheader("📄 Filtered Data")
    st.dataframe(filtered)

# === EXPORT ===
st.download_button("⬇️ Download CSV", filtered.to_csv(index=False), file_name="filtered_press_data.csv")
