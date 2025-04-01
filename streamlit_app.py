
import streamlit as st
import requests

# === CONFIG ===
st.set_page_config(page_title="📁 OneDrive File Explorer", layout="wide")
st.title("📁 OneDrive: List All Files in /Press")

# === LOAD SECRETS ===
client_id = st.secrets["onedrive"]["client_id"]
tenant_id = st.secrets["onedrive"]["tenant_id"]
client_secret = st.secrets["onedrive"]["client_secret"]
folder_path = st.secrets["onedrive"]["folder_path"]
user_email = "brandon@presfab.ca"

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

# === MANUAL RECURSIVE FILE COLLECTION ===
def list_all_files_recursively(folder_path):
    all_files = []

    def traverse(path):
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/drive/root:/{path}:/children"
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            return
        items = resp.json().get("value", [])
        for item in items:
            name = item["name"]
            if "folder" in item:
                traverse(f"{path}/{name}")
            else:
                all_files.append(name)

    traverse(folder_path)
    return all_files

with st.spinner("🔍 Scanning OneDrive /Press folder..."):
    found_files = list_all_files_recursively(folder_path)

st.subheader("📄 All files found in /Press and subfolders:")
if not found_files:
    st.error("❌ No files found.")
else:
    st.write(found_files)
