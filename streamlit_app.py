
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from io import StringIO
from datetime import datetime, timedelta

st.set_page_config(page_title="🚛 Press Dashboard", layout="wide")
st.title("🚛 Press Cycle Dashboard")

# === AUTH ===
client_id = st.secrets["onedrive"]["client_id"]
tenant_id = st.secrets["onedrive"]["tenant_id"]
client_secret = st.secrets["onedrive"]["client_secret"]
user_email = "brandon@presfab.ca"
folder_path = "Press"

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
    st.error("❌ Auth failed.")
    st.stop()
headers = {"Authorization": f"Bearer {access_token}"}

# === GET DRIVE FILES ===
drive_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive"
drive_id = requests.get(drive_url, headers=headers).json().get("id")
if not drive_id:
    st.error("❌ Could not get user drive.")
    st.stop()
folder_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder_path}:/children"
resp = requests.get(folder_url, headers=headers)
items = resp.json().get("value", [])
csv_files = [f for f in items if f["name"].strip().lower().endswith(".csv")]

if not csv_files:
    st.warning("📂 No CSV files found.")
    st.stop()

# === LOAD CSVs WITH VALIDATION ===
@st.cache_data
def load_csvs():
    valid = []
    skipped = []
    for file in csv_files:
        name = file["name"]
        try:
            text = requests.get(file["@microsoft.graph.downloadUrl"]).text
            df = pd.read_csv(StringIO(text))
            df.columns = df.columns.str.strip()

            required = ['Date', 'Heure', 'Cycle de presse(secondes)', 'Épandage(secondes)', 'Arrêt(secondes)']
            missing = [col for col in required if col not in df.columns]
            if missing:
                skipped.append(f"{name} → missing: {', '.join(missing)}")
                continue

            df["source_file"] = name
            df["Timestamp"] = pd.to_datetime(df["Date"].astype(str) + " " + df["Heure"].astype(str), errors='coerce')
            df = df[df["Timestamp"].notna()]
            valid.append(df)
        except Exception as e:
            skipped.append(f"{name} → error: {str(e)}")
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame(), skipped

with st.spinner("📥 Loading data..."):
    df, skipped = load_csvs()

if skipped:
    st.warning(f"⚠️ Skipped {len(skipped)} file(s). See logs below.")
    for s in skipped[:20]:
        st.text(s)
    if len(skipped) > 20:
        st.text("... (more skipped files)")

if df.empty:
    st.error("❌ No usable data.")
    st.stop()

# === CLEAN DATA ===
df = df[~((df['Timestamp'].dt.year == 2019) & (df['Timestamp'].dt.month == 11))]
df['Hour'] = df['Timestamp'].dt.hour
df['DateOnly'] = df['Timestamp'].dt.date
df['DayName'] = df['Timestamp'].dt.day_name()
df['Machine'] = df['source_file'].str.extract(r'(Presse\d)', expand=False).replace({'Presse1': '400', 'Presse2': '800'})
df['AMPM'] = pd.Categorical(df['Hour'].apply(lambda h: 'AM' if h < 13 else 'PM'), categories=['AM', 'PM'], ordered=True)

# === CONVERT DURATIONS SAFELY ===
numeric_cols = ['Épandage(secondes)', 'Cycle de presse(secondes)', 'Arrêt(secondes)']
present_cols = [col for col in numeric_cols if col in df.columns]
for col in present_cols:
    df[col] = pd.to_numeric(df[col], errors='coerce') / 60

# === FILTER PANEL ===
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
        show_raw = st.checkbox("👁 Show Table", False)

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
    st.warning("⚠️ No matching data.")
    st.stop()

# === KPIs ===
start_ts = filtered['Timestamp'].min()
end_ts = filtered['Timestamp'].max()
duration_hours = max((end_ts - start_ts).total_seconds() / 3600, 1)
total_cycles = len(filtered)
avg_per_hour = total_cycles / duration_hours
avg_cycle = filtered['Cycle de presse(secondes)'].mean() if 'Cycle de presse(secondes)' in filtered else 0

col1, col2, col3 = st.columns(3)
col1.metric("🧮 Total Cycles", f"{total_cycles:,}")
col2.metric("⚡ Cycles/Hour", f"{avg_per_hour:.1f}")
col3.metric("⏱ Avg Cycle (min)", f"{avg_cycle:.1f}")

# === CHART ===
st.subheader("📊 AM/PM Trend")
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

st.download_button("⬇️ Download CSV", filtered.to_csv(index=False), file_name="filtered_press_data.csv")
