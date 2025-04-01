
import streamlit as st
import requests

# === CONFIG ===
st.set_page_config(page_title="📁 OneDrive Debugger", layout="wide")
st.title("📁 OneDrive Debug: List Files from /Press")

# === LOAD SECRETS ===
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
    st.error("❌ Authentication failed. Check credentials.")
    st.stop()

headers = {"Authorization": f"Bearer {access_token}"}

# === GET USER DRIVE ID ===
drive_url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive"
drive_resp = requests.get(drive_url, headers=headers)
drive_id = drive_resp.json().get("id")

if not drive_id:
    st.error("❌ Could not get user drive ID.")
    st.stop()

# === GET FILES FROM /Press ===
press_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder_path}:/children"
resp = requests.get(press_url, headers=headers)

if resp.status_code != 200:
    st.error(f"❌ Failed to list /{folder_path}. Response: {resp.text}")
    st.stop()

files = resp.json().get("value", [])
file_names = [item["name"] for item in files]

st.subheader(f"📂 Files in /{folder_path}:")
if not file_names:
    st.warning("❌ No files found in /Press.")
else:
    st.write(file_names)
