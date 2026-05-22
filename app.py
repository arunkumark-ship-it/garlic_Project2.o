# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Garlic Order & Delivery Platform  —  app.py  v6                           ║
# ║  All 11 fixes applied                                                       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
import os, uuid, hashlib, textwrap
from datetime import datetime, date

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from google.auth.exceptions import RefreshError

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG  (must be first st.* call)
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Garlic Order & Delivery",
    page_icon="🧄", layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');
:root{ --green:#1a7f4b; --amber:#854f0b; --blue:#185fa5;
       --border:#c8e6d4; --bg:#eef5f0; --text:#1a2e22; --muted:#5a7a65; }
html,body,[class*="css"]{ font-family:'DM Sans',sans-serif; color:var(--text); }
h1,h2,h3{ font-family:'Syne',sans-serif; }
.stApp{ background:var(--bg); }
header[data-testid="stHeader"]{ background:transparent; }
.sl{ font-family:'Syne',sans-serif; font-weight:700; font-size:.75rem;
     letter-spacing:.8px; text-transform:uppercase; color:var(--green);
     padding-bottom:.4rem; border-bottom:2px solid var(--border); margin-bottom:.9rem; }
.sl-amber{ color:var(--amber); border-color:#f5d6a7; }
.sl-blue { color:var(--blue);  border-color:#b5d4f4; }
.pill{ display:inline-block; font-size:.75rem; padding:3px 12px; border-radius:20px; font-weight:600; }
.pill-pend{ background:#fff3cd; color:#856404; }
.pill-done{ background:#d4edda; color:#1a7f4b; }
.pill-fail{ background:#f8d7da; color:#842029; }
.pill-part{ background:#cce5ff; color:#004085; }
.pill-on  { background:#d4edda; color:#1a7f4b; }
.pill-off { background:#e2e3e5; color:#383d41; }
.map-frame{ border-radius:12px; overflow:hidden; border:2px solid var(--border); margin-top:.5rem; }
div[data-testid="stTextInput"] input,
div[data-testid="stSelectbox"] select,
div[data-testid="stNumberInput"] input,
div[data-testid="stTextArea"] textarea{
  border-radius:10px !important; border-color:var(--border) !important; }
.stButton>button{ border-radius:12px !important; font-family:'Syne',sans-serif !important; font-weight:700 !important; }
.stButton>button[kind="primary"]{ background:var(--green) !important; border:none !important; color:#fff !important; }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  SESSION STATE DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════
DEFAULTS = {
    "logged_in": False, "user": None,
    "driver_id": None,  "driver_active": True,
    "active_stop": 0,   "cust_data": {},
    "task_done": False,   # FIX #11: track if all tasks completed before logout
}
for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN REGISTER PASSWORD  — FIX #5
# ═══════════════════════════════════════════════════════════════════════════════
ADMIN_REGISTER_PASSWORD = st.secrets.get("admin_register_password", "NinjaGarlic@2026")

# ═══════════════════════════════════════════════════════════════════════════════
#  GOOGLE AUTH
# ═══════════════════════════════════════════════════════════════════════════════
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
SPREADSHEET_NAME = "Garlic_Order & Delivery Project"


def _clean_private_key(raw_key: str) -> str:
    k = str(raw_key).strip()
    if (k.startswith('"') and k.endswith('"')) or \
       (k.startswith("'") and k.endswith("'")):
        k = k[1:-1]
    k = k.replace("\\r\\n", "\n")
    k = k.replace("\\r",    "\n")
    k = k.replace("\\n",    "\n")
    k = k.replace("\r\n",   "\n")
    k = k.replace("\r",     "\n")
    header = "-----BEGIN PRIVATE KEY-----"
    footer = "-----END PRIVATE KEY-----"
    k = k.replace(header, "")
    k = k.replace(footer,  "")
    k = k.replace("\n", "")
    k = k.replace(" ",  "")
    k = k.strip()
    if len(k) < 100:
        raise ValueError(f"Private key body too short ({len(k)} chars).")
    body = "\n".join(textwrap.wrap(k, 64))
    return f"{header}\n{body}\n{footer}\n"


def _get_creds() -> Credentials:
    creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
    if os.path.exists(creds_path):
        return Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    try:
        raw = dict(st.secrets["gcp_service_account"])
        raw["private_key"] = _clean_private_key(str(raw["private_key"]))
        required = ["type","project_id","private_key_id","private_key",
                    "client_email","client_id","token_uri"]
        missing = [f for f in required if not raw.get(f)]
        if missing:
            raise ValueError(f"Missing fields in secrets: {missing}")
        return Credentials.from_service_account_info(raw, scopes=SCOPES)
    except KeyError:
        pass
    except Exception as e:
        raise ValueError(f"Method 2 (secrets dict) failed: {e}")
    try:
        info = {
            "type":                        str(st.secrets.get("type","service_account")),
            "project_id":                  str(st.secrets["project_id"]),
            "private_key_id":              str(st.secrets["private_key_id"]),
            "private_key":                 _clean_private_key(str(st.secrets["private_key"])),
            "client_email":                str(st.secrets["client_email"]),
            "client_id":                   str(st.secrets["client_id"]),
            "auth_uri":                    str(st.secrets.get("auth_uri","https://accounts.google.com/o/oauth2/auth")),
            "token_uri":                   str(st.secrets.get("token_uri","https://oauth2.googleapis.com/token")),
            "auth_provider_x509_cert_url": str(st.secrets.get("auth_provider_x509_cert_url","https://www.googleapis.com/oauth2/v1/certs")),
            "client_x509_cert_url":        str(st.secrets.get("client_x509_cert_url","")),
        }
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    except KeyError as e:
        raise ValueError(f"Could not find credentials. Missing key: {e}")


@st.cache_resource(show_spinner=False)
def _cached_client():
    creds = _get_creds()
    return gspread.authorize(creds)


def get_gspread_client():
    try:
        return _cached_client()
    except Exception:
        _cached_client.clear()
        creds = _get_creds()
        return gspread.authorize(creds)


def _test_connection():
    try:
        client = get_gspread_client()
        client.list_spreadsheet_files()
        return True, None
    except Exception as e:
        err = str(e)
        if "invalid_grant" in err or "JWT" in err or "RefreshError" in err:
            return False, "jwt"
        if "credentials" in err.lower() or "secret" in err.lower():
            return False, "missing"
        return False, err


def page_credential_error(err_type: str):
    st.markdown("""
    <div style="background:#fff3cd;border:2px solid #e8a020;border-radius:14px;
                padding:20px;margin-bottom:16px">
      <h2 style="color:#854f0b;margin:0 0 8px">🔑 Google Sheets connection failed</h2>
      <p style="color:#5a4010;margin:0">The app cannot authenticate with Google.</p>
    </div>""", unsafe_allow_html=True)
    st.markdown("### Fix in 4 steps")
    with st.expander("Step 1 — Create a fresh Google key", expanded=True):
        st.markdown("""
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. **IAM & Admin → Service Accounts** → click your service account
3. **Keys tab → Delete** any existing keys
4. **Add Key → Create new key → JSON** → Download the file
5. Enable **Google Sheets API** and **Google Drive API**
        """)
    with st.expander("Step 2 — Share your Google Sheet", expanded=True):
        st.markdown("""
1. Open your Google Sheet named **"Garlic_Order & Delivery Project"**
2. Click **Share** → Paste `client_email` → set **Editor** → Send
        """)
    with st.expander("Step 3 — Paste secrets correctly", expanded=True):
        st.code("""[gcp_service_account]
type                        = "service_account"
project_id                  = "YOUR_PROJECT_ID"
private_key_id              = "YOUR_KEY_ID"
private_key                 = "-----BEGIN PRIVATE KEY-----\\nYOUR_KEY_BODY\\n-----END PRIVATE KEY-----\\n"
client_email                = "YOUR_BOT@YOUR_PROJECT.iam.gserviceaccount.com"
client_id                   = "YOUR_CLIENT_ID"
auth_uri                    = "https://accounts.google.com/o/oauth2/auth"
token_uri                   = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url        = "https://www.googleapis.com/robot/v1/metadata/x509/YOUR_BOT%40YOUR_PROJECT.iam.gserviceaccount.com"
universe_domain             = "googleapis.com"

# FIX #5 — Admin register page password
admin_register_password     = "YourSecureAdminPassword"
""", language="toml")
    with st.expander("Step 4 — Redeploy", expanded=True):
        st.markdown("After saving Secrets, click **Reboot app** and wait ~30 seconds.")
    if st.button("🔄 Retry connection now", type="primary"):
        _cached_client.clear()
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
#  GOOGLE SHEETS HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
TAB = {
    "base":             "Base",
    "customer_onboard": "Customer Onboard Data",
    "driver_onboard":   "Driver Onboard Data",
    "sales_exec":       "sales executive",
    "delivery_driver":  "delivery Driver",
    "user_registry":    "UserRegistry",
    "admin_log":        "Admin Log",
    "skus":             "SKU Master",
    "trips":            "Trips",
}

# FIX #1: Added "Email" to user_registry headers
# FIX #6: Added "Mail ID" to admin_log headers
# FIX #3: Added "Latitude" and "Longitude" to customer_onboard headers
HEADERS = {
    "base": [
        "Order ID","SOID","City","ORDER DATE","DELIVERED DATE","ORDERED TIME",
        "CustomerId","Customer shop name","Customer Number","Customer_Classification",
        "sales executive","sales executive Number","SKU","SKU Name","WeightType","Price",
        "OrderedQty","OrderTotal","ReturnQty","Reason","return_updated_role",
        "Tripid","Transport","ShopOpeningFrom","ShopReachTime","DeliveryCutOff",
        "Shop Location","Delivery Status","EnteredBy_UID","Timestamp",
    ],
    "customer_onboard": [
        "CUST-ID","Full Name","Mobile","Email","Shop Name","Shop Address",
        "City","Classification","Onboarded By","Onboard Date","Status",
        "Latitude","Longitude",  # FIX #3
    ],
    "driver_onboard": [
        "Driver ID","Full Name","Mobile","Email","Vehicle Type",
        "Bank Name","Account Number","IFSC Code","UPI ID",
        "Onboard Date","Active Status","Last Active",
    ],
    # FIX #1: Added "Email" and "Mail ID" columns; plain password (no hash label)
    "user_registry": ["UID","Full Name","Phone","Email","Role","Password","Created At","Status"],
    "sales_exec":    ["UID","Full Name","Phone","Email","Role","Password","Created At"],
    "delivery_driver":["UID","Full Name","Phone","Email","Role","Password","Created At"],
    # FIX #6: Added "Mail ID" to admin_log
    "admin_log": ["Log ID","Timestamp","Admin UID","Mail ID","Action Type",
                  "Entity","Entity ID","Old Value","New Value","Notes"],
    "skus":  ["SKU Code","SKU Name","Price","Weight Type","Category","Active","Created By","Created At"],
    "trips": ["Trip ID","Date","City","Shops","Driver UID","Driver Name","Status","Created By","Created At"],
}


def open_spreadsheet():
    client = get_gspread_client()
    try:
        return client.open(SPREADSHEET_NAME)
    except gspread.SpreadsheetNotFound:
        st.markdown(f"""
<div style="background:#fff3cd;border:2px solid #e8a020;border-radius:14px;padding:20px;margin:10px 0">
<h3 style="color:#854f0b;margin:0 0 10px">📋 Google Sheet Not Found</h3>
<p style="color:#5a4010;margin:0 0 12px">
Create a sheet named <strong>"{SPREADSHEET_NAME}"</strong> and share it with your service account as Editor.
</p>
</div>
""", unsafe_allow_html=True)
        st.stop()


def get_ws(key: str):
    """
    Open (or create) a worksheet. If the sheet already exists but is missing
    columns that are in HEADERS[key], insert the missing columns at the correct
    position so existing data is never shifted. This handles schema migrations
    automatically (e.g. adding 'Email' to UserRegistry that was created before
    the Email column existed).
    """
    sp   = open_spreadsheet()
    name = TAB[key]
    try:
        ws = sp.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sp.add_worksheet(title=name, rows=2000, cols=40)
        if key in HEADERS:
            ws.append_row(HEADERS[key])
        return ws

    # ── Auto-migrate: add any missing columns ────────────────────────────────
    if key in HEADERS:
        expected = HEADERS[key]
        current  = ws.row_values(1)   # existing header row (may be empty)

        if not current:
            # Sheet exists but is completely empty — write headers now
            ws.append_row(expected)
        else:
            # Find columns present in expected but absent in current headers
            missing_cols = [(i, col) for i, col in enumerate(expected)
                            if col not in current]
            for expected_idx, col_name in missing_cols:
                # Insert column at the correct position (1-based for gspread)
                insert_pos = expected_idx + 1
                ws.insert_cols([[col_name]], col=insert_pos)
                # After insertion the live header row has shifted; re-read it
                current = ws.row_values(1)

    return ws


def read_sheet(key: str) -> pd.DataFrame:
    try:
        rows = get_ws(key).get_all_records()
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=HEADERS.get(key, []))
    except Exception as e:
        st.error(f"Sheet read error ({key}): {e}")
        return pd.DataFrame(columns=HEADERS.get(key, []))


def append_row(key: str, row: list):
    """
    Write a row using COLUMN NAMES (dict) so the data always lands in the
    right cell regardless of what order the sheet's header columns are in.
    Falls back to positional append if the key has no HEADERS definition.
    """
    ws = get_ws(key)
    if key not in HEADERS:
        ws.append_row(row, value_input_option="USER_ENTERED")
        return

    expected_headers = HEADERS[key]
    if len(row) != len(expected_headers):
        # Length mismatch — fall back to positional to avoid silent data loss
        ws.append_row(row, value_input_option="USER_ENTERED")
        return

    # Build a dict {col_name: value} then write into correct column positions
    data_dict   = dict(zip(expected_headers, row))
    live_headers = ws.row_values(1)
    ordered_row  = [data_dict.get(h, "") for h in live_headers]
    ws.append_row(ordered_row, value_input_option="USER_ENTERED")


def update_row(key: str, id_col: str, id_val: str, updates: dict) -> bool:
    ws      = get_ws(key)
    headers = ws.row_values(1)
    for i, row in enumerate(ws.get_all_records(), start=2):
        if str(row.get(id_col, "")).strip() == str(id_val).strip():
            for col, val in updates.items():
                if col in headers:
                    ws.update_cell(i, headers.index(col) + 1, val)
            return True
    return False


def find_row(key: str, col: str, val: str):
    df = read_sheet(key)
    if df.empty or col not in df.columns:
        return None
    m = df[df[col].astype(str).str.strip() == str(val).strip()]
    return m.iloc[0].to_dict() if not m.empty else None


def col_exists(key: str, col: str, val: str) -> bool:
    return find_row(key, col, val) is not None


@st.cache_data(ttl=120)
def load_customers() -> pd.DataFrame:
    return read_sheet("customer_onboard")

@st.cache_data(ttl=60)
def load_skus() -> pd.DataFrame:
    return read_sheet("skus")

def active_skus() -> pd.DataFrame:
    df = load_skus()
    if df.empty: return df
    return df[df["Active"].astype(str).str.lower() == "true"]

def active_drivers() -> pd.DataFrame:
    df = read_sheet("driver_onboard")
    if df.empty: return df
    return df[df["Active Status"].astype(str).str.lower() == "active"]

def set_driver_status(driver_id: str, status: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_row("driver_onboard","Driver ID", driver_id,
               {"Active Status": status, "Last Active": ts})

def get_driver_trip(driver_uid: str):
    df = read_sheet("trips")
    if df.empty: return None
    m = df[(df["Driver UID"].astype(str) == str(driver_uid)) &
           (df["Status"].astype(str).str.lower().isin(["assigned","in progress"]))]
    return m.iloc[0].to_dict() if not m.empty else None

# FIX #6: write_admin_log now accepts and stores mail_id
def write_admin_log(admin_uid, mail_id, action, entity, entity_id, old="", new="", notes=""):
    lid = "LOG-" + uuid.uuid4().hex[:6].upper()
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    append_row("admin_log", [lid, ts, admin_uid, mail_id, action, entity,
                              str(entity_id), str(old), str(new), notes])

# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH  — FIX #1: password stored plain text, login by email (mail id)
# ═══════════════════════════════════════════════════════════════════════════════
def gen_uid(role):
    p = {"admin":"ADMIN","sales executive":"SE","delivery Driver":"DD"}.get(role,"USR")
    return f"{p}-{uuid.uuid4().hex[:6].upper()}"
def gen_cust_id():  return f"CUST-{uuid.uuid4().hex[:6].upper()}"
def gen_driver_id():return f"DD-{uuid.uuid4().hex[:6].upper()}"
def gen_order_id(): return f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"

# FIX #1: register stores email; password stored as plain text (no hashing)
def register_user(name, phone, email, role, password):
    if col_exists("user_registry","Phone", phone):
        ex = find_row("user_registry","Phone", phone)
        return None, f"Phone already registered. UID: {ex['UID']}"
    if email and col_exists("user_registry","Email", email):
        ex = find_row("user_registry","Email", email)
        return None, f"Email already registered. UID: {ex['UID']}"
    uid  = gen_uid(role)
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Store password as plain text per requirement
    append_row("user_registry",[uid, name, phone, email, role, password, ts, "Active"])
    if role in ("sales executive","delivery Driver"):
        rk = "sales_exec" if role == "sales executive" else "delivery_driver"
        append_row(rk,[uid, name, phone, email, role, password, ts])
    return uid, None

# FIX #1: login_user uses Email (mail id) as login identifier
# Also handles old sheets with "Password Hash" column name
def login_user(email, password):
    user = find_row("user_registry","Email", email)
    if not user:
        return None, "Email not found. If you registered before this update, contact admin."
    # Support both old column "Password Hash" and new "Password"
    stored_pw = str(user.get("Password","") or user.get("Password Hash",""))
    if stored_pw != str(password):
        return None, "Incorrect password."
    if str(user.get("Status","")).lower() != "active":
        return None, "Account inactive. Contact admin."
    return {"uid":user["UID"],"name":user["Full Name"],
            "role":user["Role"],"phone":str(user.get("Phone","")),
            "email":str(user.get("Email",""))}, None

# ═══════════════════════════════════════════════════════════════════════════════
#  UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def sl(label, color=""):
    cls = f"sl sl-{color}" if color else "sl"
    return f'<div class="{cls}">{label}</div>'

def pill(text, cls="pill-pend"):
    return f'<span class="pill {cls}">{text}</span>'

def map_embed(address, height=260):
    if not address or not address.strip(): return ""
    enc = address.strip().replace(" ","+")
    return (f'<div class="map-frame"><iframe width="100%" height="{height}"'
            f' frameborder="0" style="border:0;display:block" allowfullscreen'
            f' src="https://maps.google.com/maps?q={enc}&output=embed&z=15">'
            f'</iframe></div>')

# FIX #11: Logout only allowed after tasks done (task_done flag)
def topbar(role_label, role_color="#1a7f4b"):
    user = st.session_state.user
    c1,c2,c3 = st.columns([5,3,2])
    with c1:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:10px;padding:6px 0">'
            '<span style="font-size:1.6rem">🧄</span>'
            '<span style="font-family:Syne,sans-serif;font-weight:800;'
            'font-size:1.15rem;color:#1a7f4b">Garlic Order & Delivery</span>'
            '</div>', unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div style="text-align:center;padding-top:8px">'
            f'<span style="background:{role_color};color:#fff;padding:4px 14px;'
            f'border-radius:20px;font-size:.8rem;font-weight:700">{role_label}</span>'
            f'&nbsp;<code style="font-size:.72rem;color:#5a7a65">{user["uid"]}</code>'
            f'</div>', unsafe_allow_html=True)
    with c3:
        # FIX #11: only show logout when task_done is True
        if st.session_state.get("task_done", False):
            if st.button("🚪 Logout", key="topbar_logout"):
                if user["role"] == "delivery Driver":
                    dr = find_row("driver_onboard","Mobile", user["phone"])
                    if dr: set_driver_status(dr["Driver ID"],"Offline")
                for k in DEFAULTS: st.session_state[k] = DEFAULTS[k]
                st.rerun()
        else:
            st.markdown(
                '<div style="text-align:right;padding-top:10px">'
                '<span style="color:#5a7a65;font-size:.8rem">🔒 Complete tasks to logout</span>'
                '</div>', unsafe_allow_html=True)
    st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: LOGIN & REGISTER — FIX #1 (email login) + FIX #5 (admin register gate)
# ═══════════════════════════════════════════════════════════════════════════════
def page_login():
    st.markdown("""
    <div style="display:flex;flex-direction:column;align-items:center;
                margin-top:2.5rem;margin-bottom:1.5rem">
      <div style="width:68px;height:68px;border-radius:18px;background:#1a7f4b;
                  display:flex;align-items:center;justify-content:center;
                  font-size:34px;margin-bottom:12px;
                  box-shadow:0 8px 24px rgba(26,127,75,.35)">🧄</div>
      <h1 style="font-size:1.8rem;color:#0d1f14;margin:0">Garlic Order & Delivery</h1>
      <p style="color:#5a7a65;font-size:.95rem;margin-top:4px">Field Operations Platform</p>
    </div>""", unsafe_allow_html=True)

    col = st.columns([1,2,1])[1]
    with col:
        tab_lg, tab_rg = st.tabs(["🔐  Login","📝  Register"])

        # FIX #1: Login by email (mail id)
        with tab_lg:
            email = st.text_input("Email (Login ID)", placeholder="you@example.com", key="lg_email")
            pw    = st.text_input("Password", type="password", key="lg_pw")
            if st.button("Login →", type="primary", use_container_width=True, key="lg_btn"):
                if not email or not pw:
                    st.error("Enter email and password.")
                else:
                    with st.spinner("Verifying…"):
                        user, err = login_user(email.strip().lower(), pw)
                    if err:
                        st.error(f"❌ {err}")
                    else:
                        st.session_state.logged_in = True
                        st.session_state.user      = user
                        st.session_state.task_done = False  # FIX #11
                        if user["role"] == "delivery Driver":
                            dr = find_row("driver_onboard","Mobile", user["phone"])
                            if dr:
                                set_driver_status(dr["Driver ID"],"Active")
                                st.session_state.driver_id = dr["Driver ID"]
                        st.rerun()

        # ALL roles require Admin Registration Password to register
        with tab_rg:
            rn   = st.text_input("Full name *", key="rg_name")
            rph  = st.text_input("Phone number *", key="rg_ph")
            rem  = st.text_input("Email (Login ID) *", placeholder="you@example.com", key="rg_email")
            rrol = st.selectbox("Role *", ["sales executive","delivery Driver","admin"], key="rg_role")
            rpw  = st.text_input("Password *", type="password", key="rg_pw")
            rpw2 = st.text_input("Confirm password *", type="password", key="rg_pw2")
            # ALL roles must enter admin gate password — no exceptions
            admin_gate = st.text_input(
                "Admin Registration Password *",
                type="password", key="rg_admin_gate",
                help="Required for all roles. Contact system admin for this password."
            )

            if st.button("Create account →", type="primary", use_container_width=True, key="rg_btn"):
                if not all([rn, rph, rem, rpw, rpw2, admin_gate]):
                    st.error("Fill in all fields including the Admin Registration Password.")
                elif rpw != rpw2:
                    st.error("Passwords do not match.")
                elif len(rpw) < 6:
                    st.error("Password min 6 characters.")
                elif "@" not in rem:
                    st.error("Enter a valid email address.")
                elif admin_gate != ADMIN_REGISTER_PASSWORD:
                    st.error("❌ Invalid Admin Registration Password. Contact system admin.")
                else:
                    with st.spinner("Creating account…"):
                        uid, err = register_user(rn, rph, rem.strip().lower(), rrol, rpw)
                    if err:
                        st.error(f"❌ {err}")
                    else:
                        st.success("✅ Account created!")
                        st.info(f"Your UID: **`{uid}`** — save this. Login with your email.")

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: ADMIN — All fixes: #6 (log mail id), #7 (shop loc auto), #8 (driver onboard tab),
#                            #9 (multi-shop trips), #10 (assign driver fix), #11 (task done)
# ═══════════════════════════════════════════════════════════════════════════════
def page_admin():
    user = st.session_state.user
    topbar("🛡️ Admin","#185fa5")

    # FIX #8: Added "🚗 Driver Onboard" tab in admin page
    tabs = st.tabs(["📦 SKUs","🗺️ Trips","🚚 Assign Drivers",
                    "👤 Customers","🚗 Driver Onboard","📋 Orders","📝 Audit Log"])

    with tabs[0]:   # SKU management
        st.markdown(sl("📦 SKU Master"), unsafe_allow_html=True)
        df_sku = read_sheet("skus")
        if not df_sku.empty:
            act = len(df_sku[df_sku["Active"].astype(str).str.lower()=="true"])
            avg = df_sku["Price"].apply(lambda x: float(str(x).replace("₹","").replace(",","") or 0)).mean()
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total SKUs", len(df_sku))
            c2.metric("Active",     act)
            c3.metric("Disabled",   len(df_sku)-act)
            c4.metric("Avg price",  f"₹{avg:,.2f}")

        with st.expander("➕ Add new SKU"):
            sc1,sc2,sc3 = st.columns(3)
            with sc1:
                sk_code  = st.text_input("SKU code *",  placeholder="GRLIC-1KG",       key="sk_c")
                sk_name  = st.text_input("SKU name *",  placeholder="Garlic 1KG Pack",  key="sk_n")
            with sc2:
                sk_price = st.number_input("Price ₹ *", min_value=0.0, step=1.0,        key="sk_p")
                sk_wt    = st.selectbox("Weight type",  ["KG","Gram","Box","Piece","Dozen"], key="sk_w")
            with sc3:
                sk_cat   = st.text_input("Category",    placeholder="Garlic",           key="sk_cat")
            if st.button("Add SKU", type="primary", key="sk_add"):
                if not sk_code or not sk_name or sk_price <= 0:
                    st.error("Code, name and price required.")
                elif col_exists("skus","SKU Code", sk_code):
                    st.error("SKU code already exists.")
                else:
                    append_row("skus",[sk_code,sk_name,sk_price,sk_wt,
                                       sk_cat or "General","true",
                                       user["uid"],str(date.today())])
                    load_skus.clear()
                    # FIX #6: pass email to write_admin_log
                    write_admin_log(user["uid"],user.get("email",""),"ADD SKU","SKU",sk_code,"","",sk_name)
                    st.success(f"SKU **{sk_code}** added!")
                    st.session_state.task_done = True  # FIX #11
                    st.rerun()

        st.markdown("#### All SKUs")
        df_sku = read_sheet("skus")
        if df_sku.empty:
            st.info("No SKUs yet.")
        else:
            for idx, row in df_sku.iterrows():
                c1,c2,c3,c4,c5 = st.columns([2,2.5,1.5,1,1.5])
                c1.markdown(f"**`{row['SKU Code']}`**")
                c2.write(row["SKU Name"])
                new_p = c3.number_input("₹",
                    value=float(str(row["Price"]).replace("₹","").replace(",","") or 0),
                    step=1.0, key=f"skp{idx}", label_visibility="collapsed")
                is_act = str(row.get("Active","")).lower()=="true"
                c4.markdown(pill("Active","pill-on") if is_act else pill("Off","pill-off"),
                            unsafe_allow_html=True)
                if c5.button("Disable" if is_act else "Enable", key=f"skt{idx}"):
                    update_row("skus","SKU Code",row["SKU Code"],
                               {"Active":"false" if is_act else "true","Price":new_p})
                    write_admin_log(user["uid"],user.get("email",""),
                                    ("Disable" if is_act else "Enable")+" SKU",
                                    "SKU",row["SKU Code"],row["Price"],new_p)
                    load_skus.clear()
                    st.session_state.task_done = True  # FIX #11
                    st.rerun()
                st.divider()

    with tabs[1]:   # Trips — FIX #9: multi-shop assignment with Trip ID
        st.markdown(sl("🗺️ Trips & Routes"), unsafe_allow_html=True)
        with st.expander("➕ Create new trip"):
            tc1,tc2 = st.columns(2)
            with tc1:
                tr_id   = st.text_input("Trip ID *", placeholder="TRP-001", key="tr_id")
                tr_date = st.date_input("Date *", value=date.today(), key="tr_date")
            with tc2:
                tr_city = st.selectbox("City",["Bengaluru","Mysuru","Hubli","Mangaluru"], key="tr_city")
            custs_df = load_customers()
            if not custs_df.empty:
                # FIX #9: multiselect allows many shops per trip
                shop_opts = custs_df.apply(
                    lambda r: f"{r['CUST-ID']} — {r['Shop Name']} ({r['City']})", axis=1).tolist()
                cust_ids  = custs_df["CUST-ID"].tolist()
                sel_shops = st.multiselect(
                    "Select shops * (you can add multiple shops to one trip)",
                    shop_opts, key="tr_shops",
                    help="Select as many shops as needed for this trip")
                sel_ids = [cust_ids[shop_opts.index(s)] for s in sel_shops]
                if sel_ids:
                    st.info(f"✅ {len(sel_ids)} shop(s) selected for this trip: {', '.join(sel_ids)}")
            else:
                st.warning("No customers onboarded yet.")
                sel_ids = []
            if st.button("Create trip", type="primary", key="tr_btn"):
                if not tr_id or not sel_ids:
                    st.error("Trip ID and at least one shop required.")
                elif col_exists("trips","Trip ID", tr_id):
                    st.error("Trip ID already exists.")
                else:
                    # FIX #9: store all shop IDs comma-separated
                    append_row("trips",[tr_id,str(tr_date),tr_city,",".join(sel_ids),
                                        "","","Assigned",user["uid"],
                                        datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                    write_admin_log(user["uid"],user.get("email",""),
                                    "CREATE TRIP","Trip",tr_id,"","",f"{len(sel_ids)} shops")
                    st.success(f"Trip **{tr_id}** created with {len(sel_ids)} shop(s)!")
                    st.session_state.task_done = True  # FIX #11
                    st.rerun()

        trips_df = read_sheet("trips")
        if not trips_df.empty:
            # Show shop count per trip for clarity
            def shop_count(shops_str):
                ids = [s.strip() for s in str(shops_str).split(",") if s.strip()]
                return len(ids)
            trips_disp = trips_df.copy()
            trips_disp["Shop Count"] = trips_disp["Shops"].apply(shop_count)
            st.dataframe(trips_disp, use_container_width=True, hide_index=True)
        else:
            st.info("No trips yet.")

    with tabs[2]:   # Assign drivers — FIX #10: show ALL trips (not just unassigned)
        st.markdown(sl("🚚 Active Drivers & Assignment"), unsafe_allow_html=True)

        # Show ALL drivers (active + offline) — FIX #10
        all_drivers_df = read_sheet("driver_onboard")
        act_df = active_drivers()

        if all_drivers_df.empty:
            st.warning("No drivers onboarded yet. Onboard drivers in the 'Driver Onboard' tab.")
        else:
            st.success(f"🟢 {len(act_df)} active · ⚫ {len(all_drivers_df)-len(act_df)} offline")
            for _,r in all_drivers_df.iterrows():
                is_on = str(r.get("Active Status","")).lower() == "active"
                c1,c2,c3,c4 = st.columns([2,2,2,1])
                c1.markdown(f"**{r['Full Name']}**")
                c2.write(f"`{r['Driver ID']}` · {r.get('Vehicle Type','')}")
                c3.write(f"Last active: {r.get('Last Active','')}")
                c4.markdown(pill("Active","pill-on") if is_on else pill("Offline","pill-off"),
                            unsafe_allow_html=True)

        st.divider()
        trips_df = read_sheet("trips")
        if trips_df.empty:
            st.info("No trips created yet.")
        elif all_drivers_df.empty:
            st.info("No drivers available to assign.")
        else:
            # FIX #10: show ALL trips, not just unassigned
            st.markdown("#### Assign / Reassign Driver to Trip")
            ac1,ac2 = st.columns(2)
            with ac1:
                sel_trip = st.selectbox("Select trip", trips_df["Trip ID"].tolist(), key="asgn_trip")
                if sel_trip:
                    t = trips_df[trips_df["Trip ID"]==sel_trip].iloc[0]
                    shop_ids_t = [s.strip() for s in str(t.get("Shops","")).split(",") if s.strip()]
                    current_drv = t.get("Driver Name","") or "None"
                    st.caption(f"📦 {len(shop_ids_t)} shops · {t['City']} · {t['Date']} · Current driver: **{current_drv}**")
            with ac2:
                # FIX #10: use ALL drivers for assignment, not just active
                drv_opts = all_drivers_df.apply(
                    lambda r: f"{r['Full Name']} ({r['Driver ID']}) — {r.get('Active Status','')}", axis=1).tolist()
                drv_ids  = all_drivers_df["Driver ID"].tolist()
                sel_lbl  = st.selectbox("Select driver", drv_opts, key="asgn_drv")
                sel_id   = drv_ids[drv_opts.index(sel_lbl)] if sel_lbl else ""
                drv_name = all_drivers_df[all_drivers_df["Driver ID"]==sel_id]["Full Name"].values[0] if sel_id else ""
            if st.button("✅ Assign Driver", type="primary", key="asgn_btn"):
                update_row("trips","Trip ID",sel_trip,
                           {"Driver UID":sel_id,"Driver Name":drv_name,"Status":"Assigned"})
                write_admin_log(user["uid"],user.get("email",""),
                                "ASSIGN DRIVER","Trip",sel_trip,"",sel_id,drv_name)
                st.success(f"**{drv_name}** assigned to **{sel_trip}**!")
                st.session_state.task_done = True  # FIX #11
                st.rerun()

    with tabs[3]:   # Customers
        st.markdown(sl("👤 Customer Onboard Data"), unsafe_allow_html=True)
        df_c = load_customers()
        if df_c.empty:
            st.info("No customers onboarded yet.")
        else:
            c1,c2,c3 = st.columns(3)
            c1.metric("Total",  len(df_c))
            c2.metric("Active", len(df_c[df_c["Status"]=="Active"]))
            c3.metric("Cities", df_c["City"].nunique())
            st.dataframe(df_c, use_container_width=True, hide_index=True)

    # FIX #8: Driver Onboard tab moved to admin page
    with tabs[4]:
        st.markdown(sl("🚗 Driver Onboard","amber"), unsafe_allow_html=True)
        # Search existing
        ds1,ds2 = st.columns([3,1])
        with ds1: do_sv = st.text_input("Search existing driver by mobile", key="adm_do_search")
        with ds2:
            st.write(""); st.write("")
            do_dos = st.button("🔍 Search", key="adm_do_search_btn")
        if do_dos and do_sv:
            ex = find_row("driver_onboard","Mobile", do_sv.strip())
            if ex:
                acct = str(ex.get("Account Number",""))
                masked = ("*"*(len(acct)-4)+acct[-4:]) if len(acct)>4 else "****"
                st.success(f"✅ Already onboarded — Driver ID: **{ex['Driver ID']}**")
                st.json({"Name":ex.get("Full Name"),"Vehicle":ex.get("Vehicle Type"),
                         "Bank":ex.get("Bank Name"),"Account":masked,
                         "Status":ex.get("Active Status")})
            else:
                st.info("Not found — fill form below.")
        st.divider()
        st.markdown("#### Onboard New Driver")
        dn1,dn2,dn3 = st.columns(3)
        with dn1:
            do_name  = st.text_input("Full name *",       key="adm_do_name")
            do_mob   = st.text_input("Mobile *",          placeholder="10-digit", key="adm_do_mob")
            do_email = st.text_input("Email",             key="adm_do_email")
        with dn2:
            do_veh   = st.selectbox("Vehicle type",["Bike","Auto","Van","Truck","Mini-Truck"], key="adm_do_veh")
            do_bank  = st.text_input("Bank name *",       key="adm_do_bank")
            do_acct  = st.text_input("Account number *",  key="adm_do_acct")
        with dn3:
            do_ifsc  = st.text_input("IFSC code *",       key="adm_do_ifsc")
            do_upi   = st.text_input("UPI ID",            placeholder="mobile@upi", key="adm_do_upi")
        st.caption("🔒 Bank details stored securely, visible to admin only.")
        if st.button("✅ Onboard Driver", type="primary", use_container_width=True, key="adm_do_btn"):
            if not all([do_name,do_mob,do_bank,do_acct,do_ifsc]):
                st.error("Fill all required (*) fields.")
            else:
                with st.spinner("Checking duplicates…"):
                    ex = find_row("driver_onboard","Mobile", do_mob.strip())
                if ex:
                    st.warning(f"⚠️ Mobile already registered — Driver ID: **{ex['Driver ID']}**")
                else:
                    did = gen_driver_id()
                    append_row("driver_onboard",[
                        did,do_name,do_mob,do_email,do_veh,
                        do_bank,do_acct,do_ifsc,do_upi,
                        str(date.today()),"Offline","",
                    ])
                    write_admin_log(user["uid"],user.get("email",""),
                                    "ONBOARD DRIVER","Driver",did,"","",do_name)
                    st.success(f"✅ Driver onboarded! Driver ID: **`{did}`**")
                    st.session_state.task_done = True  # FIX #11
                    st.balloons()

        st.divider()
        st.markdown("#### All Drivers")
        df_d = read_sheet("driver_onboard")
        if df_d.empty:
            st.info("No drivers onboarded yet.")
        else:
            c1,c2,c3 = st.columns(3)
            c1.metric("Total",   len(df_d))
            c2.metric("Active",  len(df_d[df_d["Active Status"]=="Active"]))
            c3.metric("Offline", len(df_d[df_d["Active Status"]!="Active"]))
            disp = df_d.copy()
            if "Account Number" in disp.columns:
                disp["Account Number"] = disp["Account Number"].apply(
                    lambda v: ("*"*(len(str(v))-4)+str(v)[-4:]) if len(str(v))>4 else "****")
            st.dataframe(disp, use_container_width=True, hide_index=True)

    with tabs[5]:   # Orders
        st.markdown(sl("📋 All Orders"), unsafe_allow_html=True)
        df_o = read_sheet("base")
        if df_o.empty:
            st.info("No orders yet.")
        else:
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total",          len(df_o))
            c2.metric("Pending",        len(df_o[df_o["Delivery Status"]=="Pending"]))
            c3.metric("Delivered",      len(df_o[df_o["Delivery Status"]=="Delivered"]))
            c4.metric("Failed/Partial", len(df_o[df_o["Delivery Status"].isin(["Failed","Partial"])]))
            st.dataframe(df_o, use_container_width=True, hide_index=True)

    with tabs[6]:   # Audit log — FIX #6: mail id column visible
        st.markdown(sl("📝 Admin Audit Log","blue"), unsafe_allow_html=True)
        df_l = read_sheet("admin_log")
        if df_l.empty:
            st.info("No admin actions logged yet.")
        else:
            st.dataframe(df_l.sort_values("Timestamp",ascending=False),
                         use_container_width=True, hide_index=True)

    # FIX #11: Admin can mark tasks done to enable logout
    st.divider()
    if not st.session_state.get("task_done", False):
        if st.button("✅ Mark All Tasks Done (enables Logout)", key="admin_tasks_done"):
            st.session_state.task_done = True
            st.rerun()
    else:
        st.success("✅ Tasks marked complete — Logout button is now active above.")

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: SALES EXECUTIVE — FIX #2 (auto order time), #3 (lat/long),
#                           #4 (SKU name dropdown + order total), #7 (shop loc auto)
# ═══════════════════════════════════════════════════════════════════════════════
def page_sales():
    user = st.session_state.user
    topbar("🧑‍💼 Sales Executive · T1")
    tabs = st.tabs(["➕ New Order","👤 Onboard Customer","📋 My Orders"])

    with tabs[0]:
        st.markdown(sl("🔍 Customer Lookup"), unsafe_allow_html=True)
        lc1,lc2,lc3 = st.columns([2,2,1])
        with lc1: lk_id  = st.text_input("Customer ID", placeholder="CUST-XXXXXX", key="lk_id")
        with lc2: lk_mob = st.text_input("OR mobile",   placeholder="10-digit",    key="lk_mob")
        with lc3:
            st.write(""); st.write("")
            do_lk = st.button("Fetch →", key="lk_btn")
        if do_lk:
            with st.spinner("Looking up…"):
                cust = (find_row("customer_onboard","CUST-ID", lk_id.strip()) if lk_id
                        else find_row("customer_onboard","Mobile", lk_mob.strip()))
            if cust:
                st.session_state.cust_data = cust
                st.success(f"✅ Found: {cust.get('Full Name')} — {cust.get('Shop Name')}")
            else:
                st.error("❌ Customer not found. Onboard them first.")
                st.session_state.cust_data = {}
        cust = st.session_state.get("cust_data", {})
        st.divider()

        st.markdown(sl("📦 Order Details"), unsafe_allow_html=True)
        oc1,oc2,oc3 = st.columns(3)
        with oc1:
            o_id   = st.text_input("Order ID (auto)", value=gen_order_id(), disabled=True, key="o_id")
            o_date = st.date_input("Order date", value=date.today(), key="o_date")
        with oc2:
            cities = ["Bengaluru","Mysuru","Hubli","Mangaluru","Hassan","Tumkur"]
            ci = cities.index(cust.get("City","Bengaluru")) if cust.get("City") in cities else 0
            o_city  = st.selectbox("City *", cities, index=ci, key="o_city")
            # FIX #2: Order time auto-populates with current time
            o_time  = st.time_input("Ordered time (auto)", value=datetime.now().time(), key="o_time")
        with oc3:
            o_dcoff = st.time_input("Delivery cut-off", key="o_dcoff")
            o_sopen = st.time_input("Shop opens at",    key="o_sopen")

        st.markdown(sl("👤 Customer Details"), unsafe_allow_html=True)
        cc1,cc2,cc3 = st.columns(3)
        with cc1:
            st.text_input("Customer ID",    value=cust.get("CUST-ID",""),        disabled=True, key="c_id")
            st.text_input("Shop name",      value=cust.get("Shop Name",""),      disabled=True, key="c_shop")
        with cc2:
            st.text_input("Mobile",         value=cust.get("Mobile",""),         disabled=True, key="c_mob")
            st.text_input("Classification", value=cust.get("Classification",""), disabled=True, key="c_cls")
        with cc3:
            st.text_input("Sales executive",value=user["name"], disabled=True, key="c_se")
            st.text_input("SE UID",         value=user["uid"],  disabled=True, key="c_seuid")

        st.markdown(sl("🛒 SKU / Product"), unsafe_allow_html=True)
        df_sku = active_skus()
        if df_sku.empty:
            st.warning("⚠️ No active SKUs. Ask admin to add SKUs first.")
        else:
            sc1,sc2,sc3 = st.columns(3)
            with sc1:
                # FIX #4: Show "SKU NAME — SKU Code" in dropdown
                sku_display_opts = df_sku.apply(
                    lambda r: f"{r['SKU Name']}  [{r['SKU Code']}]", axis=1).tolist()
                sku_codes = df_sku["SKU Code"].tolist()
                sel_disp = st.selectbox("SKU / Product *", sku_display_opts, key="o_sku_disp")
                sel_sku  = sku_codes[sku_display_opts.index(sel_disp)]
                sku_row  = df_sku[df_sku["SKU Code"]==sel_sku].iloc[0]
                st.caption(f"SKU Code: `{sel_sku}`")
            with sc2:
                sku_price = float(str(sku_row["Price"]).replace("₹","").replace(",","") or 0)
                sku_wt    = str(sku_row["Weight Type"])
                st.text_input("Unit price (admin rate)", value=f"₹{sku_price:.2f}", disabled=True, key="o_price")
                st.text_input("Weight type", value=sku_wt, disabled=True, key="o_wt")
            with sc3:
                o_qty   = st.number_input("Ordered qty *", min_value=0.0, step=0.5, key="o_qty")
                # FIX #4: Order total calculated live = qty * unit price
                o_total = sku_price * o_qty
                st.text_input("Order total ₹ (Qty × Price)", value=f"₹{o_total:,.2f}",
                              disabled=True, key="o_total",
                              help="Auto-calculated: Ordered Qty × Unit Price (admin rate)")
                if o_qty > 0:
                    st.caption(f"📊 {o_qty} × ₹{sku_price:.2f} = **₹{o_total:,.2f}**")

            st.markdown(sl("📍 Shop Location"), unsafe_allow_html=True)
            # FIX #7: Auto-populate shop address from Customer Onboard Data
            auto_addr = cust.get("Shop Address","")
            o_addr = st.text_input("Shop address *", value=auto_addr, key="o_addr",
                                   help="Auto-filled from Customer Onboard Data based on Customer ID")
            if auto_addr and o_addr == auto_addr:
                st.caption("📍 Address auto-loaded from Customer Onboard Data")
            if o_addr:
                st.markdown(map_embed(o_addr, 240), unsafe_allow_html=True)
                st.caption("📍 Verify the pin matches the shop before submitting.")
            st.divider()

            if st.button("✅ Submit Order", type="primary", use_container_width=True, key="o_submit"):
                if not cust:
                    st.error("Look up a customer first.")
                elif not sel_sku or o_qty <= 0:
                    st.error("Select SKU and enter quantity.")
                elif not o_addr:
                    st.error("Shop address required.")
                else:
                    soid = "SO-" + o_id.replace("ORD-","")
                    # FIX #2: capture ordered time automatically at submission moment
                    ordered_time = datetime.now().strftime("%H:%M:%S")
                    append_row("base",[
                        o_id, soid, o_city, str(o_date),"",ordered_time,
                        cust.get("CUST-ID",""), cust.get("Shop Name",""),
                        cust.get("Mobile",""),  cust.get("Classification",""),
                        user["name"], user["uid"],
                        sel_sku, sku_row["SKU Name"], sku_wt, sku_price, o_qty, o_total,
                        0,"","","","",
                        str(o_sopen),"",str(o_dcoff),
                        o_addr,"Pending",user["uid"],
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ])
                    st.success(f"✅ Order **{o_id}** submitted! Total: **₹{o_total:,.2f}**")
                    st.session_state.cust_data = {}
                    st.session_state.task_done = True  # FIX #11
                    st.balloons()

    with tabs[1]:
        st.markdown(sl("👤 Customer Onboarding"), unsafe_allow_html=True)
        sc1,sc2 = st.columns([3,1])
        with sc1: co_search = st.text_input("Search existing by mobile", key="co_search")
        with sc2:
            st.write(""); st.write("")
            do_cos = st.button("🔍 Search", key="co_search_btn")
        if do_cos and co_search:
            ex = find_row("customer_onboard","Mobile", co_search.strip())
            if ex:
                st.success(f"✅ Already onboarded — CUST-ID: **{ex['CUST-ID']}**")
                st.json({"Name":ex.get("Full Name"),"Shop":ex.get("Shop Name"),
                         "City":ex.get("City"),"Status":ex.get("Status")})
            else:
                st.info("Not found — fill form below to onboard.")
        st.divider()
        st.markdown("#### New customer")
        nc1,nc2,nc3 = st.columns(3)
        with nc1:
            co_name  = st.text_input("Full name *", key="co_name")
            co_mob   = st.text_input("Mobile *", placeholder="10-digit", key="co_mob")
            co_email = st.text_input("Email", key="co_email")
        with nc2:
            co_shop  = st.text_input("Shop name *", key="co_shop")
            co_city  = st.selectbox("City *",
                ["Bengaluru","Mysuru","Hubli","Mangaluru","Hassan","Tumkur"], key="co_city")
            co_cls   = st.selectbox("Classification",
                ["A","B","C","Premium","Wholesale","Retail"], key="co_cls")
        with nc3:
            co_addr  = st.text_input("Shop address *", placeholder="House/street/landmark…", key="co_addr")
            # FIX #3: Latitude & Longitude fields for customer onboard
            co_lat   = st.text_input("Latitude *", placeholder="e.g. 12.9716", key="co_lat",
                                     help="GPS latitude of the shop location")
            co_lng   = st.text_input("Longitude *", placeholder="e.g. 77.5946", key="co_lng",
                                     help="GPS longitude of the shop location")

        if co_addr:
            st.markdown(map_embed(co_addr, 220), unsafe_allow_html=True)
            if co_lat and co_lng:
                st.caption(f"📍 Coordinates: {co_lat}, {co_lng}")

        if st.button("✅ Onboard Customer", type="primary", use_container_width=True, key="co_btn"):
            if not all([co_name,co_mob,co_shop,co_addr]):
                st.error("Fill all required (*) fields.")
            elif not co_lat or not co_lng:
                st.error("Latitude and Longitude are required for customer onboarding.")
            else:
                with st.spinner("Checking duplicates…"):
                    ex = find_row("customer_onboard","Mobile", co_mob.strip())
                if ex:
                    st.warning(f"⚠️ Mobile already registered — CUST-ID: **{ex['CUST-ID']}**")
                else:
                    cid = gen_cust_id()
                    # FIX #3: store lat and long
                    append_row("customer_onboard",[
                        cid,co_name,co_mob,co_email,co_shop,
                        co_addr,co_city,co_cls,
                        user["uid"],str(date.today()),"Active",
                        co_lat, co_lng,
                    ])
                    load_customers.clear()
                    st.success(f"✅ Onboarded! Permanent CUST-ID: **`{cid}`**")
                    st.session_state.task_done = True  # FIX #11
                    st.balloons()

    with tabs[2]:
        st.markdown(sl("📋 My Orders"), unsafe_allow_html=True)
        df_o = read_sheet("base")
        if df_o.empty:
            st.info("No orders yet.")
        else:
            my = df_o[df_o["sales executive Number"].astype(str)==user["uid"]]
            if my.empty:
                st.info("You haven't submitted any orders yet.")
            else:
                tot_val = my["OrderTotal"].apply(
                    lambda x: float(str(x).replace("₹","").replace(",","") or 0)).sum()
                mc1,mc2,mc3,mc4 = st.columns(4)
                mc1.metric("Total",     len(my))
                mc2.metric("Pending",   len(my[my["Delivery Status"]=="Pending"]))
                mc3.metric("Delivered", len(my[my["Delivery Status"]=="Delivered"]))
                mc4.metric("Value",     f"₹{tot_val:,.0f}")
                cols_show = [c for c in ["Order ID","Customer shop name","SKU","SKU Name",
                             "OrderedQty","OrderTotal","ORDER DATE","Delivery Status"] if c in my.columns]
                st.dataframe(
                    my[cols_show].sort_values("ORDER DATE",ascending=False),
                    use_container_width=True, hide_index=True)

    # FIX #11: allow logout after tasks
    st.divider()
    if not st.session_state.get("task_done", False):
        if st.button("✅ Mark All Tasks Done (enables Logout)", key="sales_tasks_done"):
            st.session_state.task_done = True
            st.rerun()
    else:
        st.success("✅ Tasks marked complete — Logout button is now active above.")

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: DELIVERY DRIVER — FIX #8 (removed Driver Onboard tab), #11 (task done)
#                           FIX #7 (shop location auto from Customer Onboard Data)
# ═══════════════════════════════════════════════════════════════════════════════
def page_delivery():
    user = st.session_state.user
    topbar("🚚 Delivery Driver · T2","#854f0b")
    # FIX #8: Removed "Driver Onboard" tab from driver login page
    tabs = st.tabs(["🗺️ My Route","📦 History"])

    with tabs[0]:
        st.markdown(sl("🗺️ Route & Deliveries","amber"), unsafe_allow_html=True)
        is_active = st.session_state.get("driver_active", True)
        drv_id    = st.session_state.get("driver_id","")
        tog_lbl   = "🟢 Active — visible to admin" if is_active else "⚫ Offline — tap to go active"
        if st.button(tog_lbl, key="active_tog"):
            is_active = not is_active
            st.session_state.driver_active = is_active
            if drv_id: set_driver_status(drv_id,"Active" if is_active else "Offline")
            st.rerun()
        if not is_active:
            st.warning("You are offline. Tap the button above to go active.")
            return
        trip = get_driver_trip(user["uid"])
        if not trip:
            st.info("📋 No trip assigned. Contact admin to assign your route.")
            return
        # FIX #9: parse all shops (comma-separated) in trip
        shop_ids = [s.strip() for s in str(trip.get("Shops","")).split(",") if s.strip()]
        st.info(f"**Trip:** {trip['Trip ID']} · **{trip['City']}** · **{trip['Date']}** · {len(shop_ids)} stops")

        df_orders = read_sheet("base")
        trip_ord  = {}
        if not df_orders.empty:
            for _,r in df_orders[df_orders["Tripid"].astype(str)==str(trip["Trip ID"])].iterrows():
                trip_ord[str(r["CustomerId"])] = r.to_dict()

        if str(trip.get("Status","")).lower() == "assigned":
            st.warning("Trip not started yet.")
            if st.button("▶️ Start Trip", type="primary", key="start_trip"):
                update_row("trips","Trip ID",trip["Trip ID"],{"Status":"In Progress"})
                st.rerun()
            return

        if "active_stop" not in st.session_state:
            st.session_state.active_stop = 0
        done_count = sum(1 for sid in shop_ids
                         if trip_ord.get(sid) and
                            str(trip_ord[sid].get("Delivery Status","")) not in ("Pending",""))
        if done_count > st.session_state.active_stop:
            st.session_state.active_stop = done_count
        active_idx = st.session_state.active_stop

        for i, sid in enumerate(shop_ids):
            shop  = find_row("customer_onboard","CUST-ID", sid)
            order = trip_ord.get(sid)
            is_done = bool(order and str(order.get("Delivery Status","")) not in ("Pending",""))
            is_cur  = (i == active_idx) and not is_done
            icon    = "✅" if is_done else ("📍" if is_cur else "🔒")
            stat    = order.get("Delivery Status","Pending") if order else "No order"
            p_cls   = "pill-done" if is_done else ("pill-pend" if is_cur else "pill-off")
            with st.container():
                r1,r2 = st.columns([9,2])
                with r1:
                    st.markdown(f"**{icon} Stop {i+1}** — {shop.get('Shop Name','') if shop else sid}")
                    # FIX #7: show auto-loaded shop location from Customer Onboard Data
                    if shop:
                        addr = shop.get("Shop Address","")
                        lat  = shop.get("Latitude","")
                        lng  = shop.get("Longitude","")
                        st.caption(f"📍 {addr}")
                        if lat and lng:
                            st.caption(f"🌐 Lat: {lat}, Lng: {lng}")
                    if order:
                        st.caption(f"SKU: {order.get('SKU','')} · Qty: {order.get('OrderedQty','')} · ₹{order.get('OrderTotal','')}")
                with r2:
                    st.markdown(pill(stat,p_cls), unsafe_allow_html=True)
            if is_cur and i <= active_idx:
                # FIX #7: show map using address from Customer Onboard Data
                addr = shop.get("Shop Address","") if shop else ""
                if addr: st.markdown(map_embed(addr,200), unsafe_allow_html=True)
                with st.form(key=f"del_form_{i}"):
                    st.markdown("##### Update delivery")
                    df1,df2,df3 = st.columns(3)
                    with df1:
                        d_reach  = st.time_input("Reach time *", value=datetime.now().time())
                        d_ddate  = st.date_input("Delivered date", value=date.today())
                    with df2:
                        d_status = st.selectbox("Status *",["Delivered","Partial","Failed","Rescheduled"])
                    with df3:
                        d_rqty   = st.number_input("Return qty", min_value=0.0, step=0.5)
                        d_rreason= st.text_input("Return reason")
                    d_notes = st.text_input("Notes")
                    submitted = st.form_submit_button("✅ Submit & Unlock Next Stop",
                                                       type="primary", use_container_width=True)
                if submitted:
                    if order:
                        update_row("base","Order ID",order["Order ID"],{
                            "Delivery Status":    d_status,
                            "ShopReachTime":      str(d_reach),
                            "DELIVERED DATE":     str(d_ddate),
                            "ReturnQty":          d_rqty,
                            "Reason":             d_rreason,
                            "return_updated_role":"delivery Driver",
                        })
                    st.session_state.active_stop = i + 1
                    st.session_state.task_done = True  # FIX #11
                    st.success(f"✅ Stop {i+1} marked **{d_status}**. "
                               f"{'Next stop unlocked!' if i+1<len(shop_ids) else 'All stops done!'}")
                    st.rerun()
            st.divider()
        if active_idx >= len(shop_ids):
            st.success("🎉 All stops completed! Trip finished.")
            update_row("trips","Trip ID",trip["Trip ID"],{"Status":"Completed"})
            st.session_state.task_done = True  # FIX #11

    with tabs[1]:
        st.markdown(sl("📦 Delivery History","amber"), unsafe_allow_html=True)
        df_h = read_sheet("base")
        if df_h.empty:
            st.info("No records.")
        else:
            my_h = df_h[df_h["return_updated_role"].astype(str)=="delivery Driver"]
            my_h = my_h[my_h["Delivery Status"] != "Pending"]
            if my_h.empty:
                st.info("No completed deliveries yet.")
            else:
                cols_h = [c for c in ["Order ID","Customer shop name","SKU","SKU Name",
                           "OrderedQty","Delivery Status","DELIVERED DATE","ReturnQty","Reason"]
                          if c in my_h.columns]
                st.dataframe(
                    my_h[cols_h].sort_values("DELIVERED DATE",ascending=False),
                    use_container_width=True, hide_index=True)

    # FIX #11: task done / logout control
    st.divider()
    if not st.session_state.get("task_done", False):
        if st.button("✅ Mark All Tasks Done (enables Logout)", key="driver_tasks_done"):
            st.session_state.task_done = True
            st.rerun()
    else:
        st.success("✅ Tasks marked complete — Logout button is now active above.")

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
_using_local_creds = os.path.exists(creds_path)

if not _using_local_creds:
    _ok, _err = _test_connection()
    if not _ok:
        page_credential_error(str(_err))
        st.stop()

if not st.session_state.logged_in:
    page_login()
else:
    role = st.session_state.user["role"]
    if   role == "admin":           page_admin()
    elif role == "sales executive": page_sales()
    elif role == "delivery Driver": page_delivery()
    else:
        st.error(f"Unknown role: '{role}'")
        if st.button("Logout"):
            for k in DEFAULTS: st.session_state[k] = DEFAULTS[k]
            st.rerun()
