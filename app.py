# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  Garlic Order & Delivery Platform  —  app.py  v9                           ║
# ║  v8 + FIX J: Live location via streamlit-js-eval get_geolocation()         ║
# ║   • Replaces iframe/redirect GPS hack with proper bidirectional component  ║
# ║   • No page reload, no loop — returns coords directly to Python            ║
# ║   • Requires:  pip install streamlit-js-eval                               ║
# ║     (add  streamlit-js-eval  to requirements.txt)                          ║
# ╚══════════════════════════════════════════════════════════════════════════════╝
import os, uuid, textwrap
from datetime import datetime, date

import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# FIX J: streamlit-js-eval for live geolocation (add to requirements.txt)
try:
    from streamlit_js_eval import get_geolocation
    _GEO_AVAILABLE = True
except ImportError:
    _GEO_AVAILABLE = False

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Garlic Order & Delivery",
    page_icon="🧄", layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');
:root{
  --green:#1a7f4b; --amber:#854f0b; --blue:#185fa5;
  --border:#c8e6d4; --bg:#eef5f0; --text:#1a2e22; --muted:#5a7a65;
}
html,body,[class*="css"]{ font-family:'DM Sans',sans-serif; color:var(--text); }
h1,h2,h3{ font-family:'Syne',sans-serif; }
.stApp{ background:var(--bg); }
header[data-testid="stHeader"]{ background:transparent; }
.sl{
  font-family:'Syne',sans-serif; font-weight:700; font-size:.75rem;
  letter-spacing:.8px; text-transform:uppercase; color:var(--green);
  padding-bottom:.4rem; border-bottom:2px solid var(--border); margin-bottom:.9rem;
}
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
  border-radius:10px !important; border-color:var(--border) !important;
}
.stButton>button{
  border-radius:12px !important;
  font-family:'Syne',sans-serif !important;
  font-weight:700 !important;
}
.stButton>button[kind="primary"]{
  background:var(--green) !important; border:none !important; color:#fff !important;
}
/* info box for auto-filled fields */
.autofill-box{
  background:#f0faf4; border:1.5px solid #b5d9c5; border-radius:10px;
  padding:10px 14px; margin:4px 0 8px; font-size:.9rem;
}
.autofill-label{
  font-size:.72rem; font-weight:700; color:var(--muted);
  text-transform:uppercase; letter-spacing:.5px; margin-bottom:2px;
}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  SESSION STATE DEFAULTS
# ═══════════════════════════════════════════════════════════════════════════════
DEFAULTS = {
    "logged_in":   False,  "user":         None,
    "driver_id":   None,   "driver_active": True,
    "active_stop": 0,      "cust_data":    {},
    "task_done":   False,
    # Live location state
    "live_lat": "",  "live_lng": "",  "live_acc": "",
    "live_address": "",          # reverse-geocoded human address
    "loc_fetching": False,
    "rev_fetching": False,       # True while reverse geocode JS is running
    # Address autocomplete state
    "ac_addr_co": "",  "ac_lat_co": "",  "ac_lng_co": "",
}
for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

ADMIN_REGISTER_PASSWORD = st.secrets.get("admin_register_password", "Admin@123")

# ═══════════════════════════════════════════════════════════════════════════════
#  GOOGLE AUTH
# ═══════════════════════════════════════════════════════════════════════════════
SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
SPREADSHEET_NAME = "Garlic_Order & Delivery Project"


def _clean_private_key(raw: str) -> str:
    k = str(raw).strip().strip('"\'')
    for a, b in [("\\r\\n","\n"),("\\r","\n"),("\\n","\n"),("\r\n","\n"),("\r","\n")]:
        k = k.replace(a, b)
    hdr = "-----BEGIN PRIVATE KEY-----"
    ftr = "-----END PRIVATE KEY-----"
    k = k.replace(hdr,"").replace(ftr,"").replace("\n","").replace(" ","").strip()
    if len(k) < 100:
        raise ValueError(f"Private key too short ({len(k)} chars).")
    return f"{hdr}\n" + "\n".join(textwrap.wrap(k, 64)) + f"\n{ftr}\n"


def _get_creds() -> Credentials:
    cp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
    if os.path.exists(cp):
        return Credentials.from_service_account_file(cp, scopes=SCOPES)
    try:
        raw = dict(st.secrets["gcp_service_account"])
        raw["private_key"] = _clean_private_key(str(raw["private_key"]))
        return Credentials.from_service_account_info(raw, scopes=SCOPES)
    except KeyError:
        pass
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


@st.cache_resource(show_spinner=False)
def _cached_client():
    return gspread.authorize(_get_creds())

def get_gspread_client():
    try:
        return _cached_client()
    except Exception:
        _cached_client.clear()
        return gspread.authorize(_get_creds())

def _test_connection():
    try:
        get_gspread_client().list_spreadsheet_files()
        return True, None
    except Exception as e:
        err = str(e)
        if "invalid_grant" in err or "JWT" in err:
            return False, "jwt"
        return False, err

def page_credential_error(err_type):
    st.error("🔑 Google Sheets connection failed. Check secrets configuration.")
    if st.button("🔄 Retry"):
        _cached_client.clear(); st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
#  SHEET HELPERS
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

HEADERS = {
    "base": [
        "Order ID","SOID","City","ORDER DATE","DELIVERED DATE","ORDERED TIME",
        "CustomerId","Customer shop name","Customer Number","Customer_Classification",
        "sales executive","sales executive Number","SKU","SKU Name","WeightType","Price",
        "OrderedQty","OrderTotal","ReturnQty","Reason","return_updated_role",
        "Tripid","Transport","ShopOpeningFrom","ShopReachTime","DeliveryCutOff",
        "Shop Location","Delivery Status","EnteredBy_UID","Timestamp",
        "Latitude","Longitude",
    ],
    "customer_onboard": [
        "CUST-ID","Full Name","Mobile","Email","Shop Name","Shop Address",
        "City","Classification","Onboarded By","Onboard Date","Status",
        "Latitude","Longitude",
    ],
    "driver_onboard": [
        "Driver ID","Full Name","Mobile","Email","Vehicle Type","Vehicle Number",
        "Bank Name","Account Number","IFSC Code","UPI ID",
        "Onboard Date","Active Status","Last Active",
    ],
    "user_registry":   ["UID","Full Name","Phone","Email","Role","Password","Created At","Status"],
    "sales_exec":      ["UID","Full Name","Phone","Email","Role","Password","Created At"],
    "delivery_driver": ["UID","Full Name","Phone","Email","Role","Password","Created At"],
    "admin_log":       ["Log ID","Timestamp","Admin UID","Mail ID","Action Type",
                        "Entity","Entity ID","Old Value","New Value","Notes"],
    "skus":   ["SKU Code","SKU Name","Price","Weight Type","Category","Active","Created By","Created At"],
    "trips":  ["Trip ID","Date","City","Shops","Driver UID","Driver Name","Status","Created By","Created At"],
}


def open_spreadsheet():
    client = get_gspread_client()
    try:
        return client.open(SPREADSHEET_NAME)
    except gspread.SpreadsheetNotFound:
        st.error(f'Google Sheet "{SPREADSHEET_NAME}" not found. Create it and share with service account.')
        st.stop()


def get_ws(key: str):
    sp, name = open_spreadsheet(), TAB[key]
    try:
        ws = sp.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sp.add_worksheet(title=name, rows=2000, cols=40)
        if key in HEADERS:
            ws.append_row(HEADERS[key])
        return ws
    if key in HEADERS:
        expected = HEADERS[key]
        current  = ws.row_values(1)
        if not current:
            ws.append_row(expected)
        else:
            for idx, col in enumerate(expected):
                if col not in current:
                    ws.insert_cols([[col]], col=idx+1)
                    current = ws.row_values(1)
    return ws


def read_sheet(key: str) -> pd.DataFrame:
    try:
        rows = get_ws(key).get_all_records()
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=HEADERS.get(key,[]))
    except Exception as e:
        st.error(f"Sheet read error ({key}): {e}")
        return pd.DataFrame(columns=HEADERS.get(key,[]))


def append_row(key: str, row: list):
    ws = get_ws(key)
    if key not in HEADERS or len(row) != len(HEADERS[key]):
        ws.append_row(row, value_input_option="USER_ENTERED")
        return
    data_dict    = dict(zip(HEADERS[key], row))
    live_headers = ws.row_values(1)
    ws.append_row([data_dict.get(h,"") for h in live_headers], value_input_option="USER_ENTERED")


def update_row(key: str, id_col: str, id_val: str, updates: dict) -> bool:
    ws = get_ws(key)
    headers = ws.row_values(1)
    for i, row in enumerate(ws.get_all_records(), start=2):
        if str(row.get(id_col,"")).strip() == str(id_val).strip():
            for col, val in updates.items():
                if col in headers:
                    ws.update_cell(i, headers.index(col)+1, val)
            return True
    return False


def find_row(key: str, col: str, val: str):
    df = read_sheet(key)
    if df.empty or col not in df.columns: return None
    m = df[df[col].astype(str).str.strip() == str(val).strip()]
    return m.iloc[0].to_dict() if not m.empty else None

def col_exists(key, col, val): return find_row(key, col, val) is not None


@st.cache_data(ttl=120)
def load_customers() -> pd.DataFrame:
    return read_sheet("customer_onboard")

@st.cache_data(ttl=60)
def load_skus() -> pd.DataFrame:
    return read_sheet("skus")

def active_skus():
    df = load_skus()
    return df[df["Active"].astype(str).str.lower()=="true"] if not df.empty else df

def active_drivers():
    df = read_sheet("driver_onboard")
    return df[df["Active Status"].astype(str).str.lower()=="active"] if not df.empty else df

def set_driver_status(driver_id, status):
    update_row("driver_onboard","Driver ID",driver_id,
               {"Active Status":status,"Last Active":datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

def get_driver_trip(driver_uid):
    df = read_sheet("trips")
    if df.empty: return None
    m = df[(df["Driver UID"].astype(str)==str(driver_uid)) &
           (df["Status"].astype(str).str.lower().isin(["assigned","in progress"]))]
    return m.iloc[0].to_dict() if not m.empty else None

def write_admin_log(admin_uid, mail_id, action, entity, entity_id, old="", new="", notes=""):
    append_row("admin_log",[
        "LOG-"+uuid.uuid4().hex[:6].upper(),
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        admin_uid, mail_id, action, entity, str(entity_id), str(old), str(new), notes
    ])

# ═══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ═══════════════════════════════════════════════════════════════════════════════
def gen_uid(role):
    p = {"admin":"ADMIN","sales executive":"SE","delivery Driver":"DD"}.get(role,"USR")
    return f"{p}-{uuid.uuid4().hex[:6].upper()}"
def gen_cust_id():  return f"CUST-{uuid.uuid4().hex[:6].upper()}"
def gen_driver_id():return f"DD-{uuid.uuid4().hex[:6].upper()}"
def gen_order_id(): return f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:4].upper()}"

def register_user(name, phone, email, role, password):
    if col_exists("user_registry","Phone",phone):
        ex = find_row("user_registry","Phone",phone)
        return None, f"Phone already registered. UID: {ex['UID']}"
    if email and col_exists("user_registry","Email",email):
        ex = find_row("user_registry","Email",email)
        return None, f"Email already registered. UID: {ex['UID']}"
    uid = gen_uid(role)
    ts  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    append_row("user_registry",[uid,name,phone,email,role,password,ts,"Active"])
    if role in ("sales executive","delivery Driver"):
        rk = "sales_exec" if role=="sales executive" else "delivery_driver"
        append_row(rk,[uid,name,phone,email,role,password,ts])
    return uid, None

def login_user(email, password):
    user = find_row("user_registry","Email",email)
    if not user:
        return None, "Email not found."
    stored = str(user.get("Password","") or user.get("Password Hash",""))
    if stored != str(password):
        return None, "Incorrect password."
    if str(user.get("Status","")).lower() != "active":
        return None, "Account inactive. Contact admin."
    return {"uid":user["UID"],"name":user["Full Name"],"role":user["Role"],
            "phone":str(user.get("Phone","")),"email":str(user.get("Email",""))}, None

# ═══════════════════════════════════════════════════════════════════════════════
#  UI HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def sl(label, color=""):
    cls = f"sl sl-{color}" if color else "sl"
    return f'<div class="{cls}">{label}</div>'

def pill(text, cls="pill-pend"):
    return f'<span class="pill {cls}">{text}</span>'

def map_embed(address, height=260):
    if not address or not str(address).strip(): return ""
    enc = str(address).strip().replace(" ","+")
    return (f'<div class="map-frame"><iframe width="100%" height="{height}" frameborder="0"'
            f' style="border:0;display:block" allowfullscreen'
            f' src="https://maps.google.com/maps?q={enc}&output=embed&z=15">'
            f'</iframe></div>')

def map_embed_coords(lat, lng, height=260):
    if not lat or not lng or str(lat).strip()=="" or str(lng).strip()=="": return ""
    return (f'<div class="map-frame"><iframe width="100%" height="{height}" frameborder="0"'
            f' style="border:0;display:block" allowfullscreen'
            f' src="https://maps.google.com/maps?q={lat},{lng}&output=embed&z=16">'
            f'</iframe></div>')

def autofill_box(label, value):
    """Styled read-only display box for auto-filled fields."""
    val = str(value) if value else "—"
    return (f'<div class="autofill-box">'
            f'<div class="autofill-label">{label}</div>'
            f'<div style="font-size:.95rem;font-weight:500;color:#1a2e22">{val}</div>'
            f'</div>')

# ─── FIX J + K: Live location + reverse geocode + address autocomplete ────────

def live_location_widget():
    """
    Uses get_geolocation() from streamlit-js-eval.
    On success, also fires a Nominatim reverse-geocode in a sibling JS component
    and stores the human-readable address in session_state.live_address.
    Returns (lat_str, lng_str, accuracy_str).
    """
    if not _GEO_AVAILABLE:
        st.warning("⚠️ `streamlit-js-eval` not installed. Add it to requirements.txt.")
        fb1, fb2 = st.columns(2)
        with fb1:
            fb_lat = st.text_input("Latitude",  placeholder="e.g. 12.9716", key="fb_lat")
        with fb2:
            fb_lng = st.text_input("Longitude", placeholder="e.g. 77.5946", key="fb_lng")
        return fb_lat.strip(), fb_lng.strip(), ""

    already_have = bool(st.session_state.get("live_lat",""))
    btn_label = "🔄 Re-fetch Live Location" if already_have else "📡 Fetch Live Location"

    st.markdown("""
<div style="font-size:.82rem;color:#5a7a65;margin-bottom:6px">
  Tap the button — your browser will request location permission, then pinpoint your position
  and <strong>auto-fill the shop address</strong> via reverse geocoding.
</div>""", unsafe_allow_html=True)

    fetch = st.button(btn_label, key="loc_fetch_btn",
                      help="Uses your device GPS / WiFi for precise coordinates.")
    if fetch:
        st.session_state.live_lat     = ""
        st.session_state.live_lng     = ""
        st.session_state.live_acc     = ""
        st.session_state.live_address = ""
        st.session_state.loc_fetching = True

    # ── Step 1: get coordinates ───────────────────────────────────────────────
    if st.session_state.get("loc_fetching", False):
        with st.spinner("📡 Getting your GPS coordinates…"):
            loc = get_geolocation()
        if loc and isinstance(loc, dict):
            coords = loc.get("coords", {})
            lat = coords.get("latitude")
            lng = coords.get("longitude")
            acc = coords.get("accuracy")
            if lat is not None and lng is not None:
                st.session_state.live_lat     = f"{lat:.7f}"
                st.session_state.live_lng     = f"{lng:.7f}"
                st.session_state.live_acc     = f"{acc:.1f}" if acc else ""
                st.session_state.loc_fetching  = False
                st.session_state.rev_fetching  = True   # trigger reverse geocode
                st.rerun()
            else:
                st.session_state.loc_fetching = False
                st.error("❌ Coordinates missing. Try again.")
        else:
            st.session_state.loc_fetching = False
            st.error("❌ Location unavailable. Allow browser location access and retry.")

    # ── Step 2: reverse geocode via JS component (Nominatim, no API key) ──────
    if st.session_state.get("rev_fetching", False):
        lat_v = st.session_state.get("live_lat","")
        lng_v = st.session_state.get("live_lng","")

        # Check if query params already have the reverse-geocoded address
        qp = st.query_params
        if "rev_addr" in qp:
            addr = str(qp["rev_addr"]).strip()
            st.session_state.live_address = addr
            st.session_state.rev_fetching = False
            del qp["rev_addr"]
            st.rerun()
        else:
            # Render a JS component that calls Nominatim and redirects with result
            rev_html = f"""
<!DOCTYPE html><html><body>
<div id="s" style="font-family:sans-serif;font-size:.8rem;color:#5a7a65">
  🔍 Fetching address from coordinates…
</div>
<script>
(function(){{
  var lat={lat_v}, lng={lng_v};
  fetch('https://nominatim.openstreetmap.org/reverse?lat='+lat+'&lon='+lng+'&format=json',
    {{headers:{{'Accept-Language':'en','User-Agent':'GarlicOrderApp/1.0'}}}})
  .then(function(r){{return r.json();}})
  .then(function(d){{
    var addr = d.display_name || '';
    // Shorten: take first 3 comma-parts (road, suburb, city)
    var parts = addr.split(',').slice(0,4).join(',').trim();
    document.getElementById('s').innerText = '✅ ' + parts;
    var url = new URL(window.parent.location.href);
    url.searchParams.set('rev_addr', parts);
    window.parent.location.href = url.toString();
  }})
  .catch(function(){{
    document.getElementById('s').innerText = '⚠️ Reverse geocode unavailable';
    var url = new URL(window.parent.location.href);
    url.searchParams.set('rev_addr', lat+', '+lng);
    window.parent.location.href = url.toString();
  }});
}})();
</script>
</body></html>
"""
            st.components.v1.html(rev_html, height=40, scrolling=False)

    # ── Show captured result ──────────────────────────────────────────────────
    cur_lat  = st.session_state.get("live_lat",  "")
    cur_lng  = st.session_state.get("live_lng",  "")
    cur_acc  = st.session_state.get("live_acc",  "")
    cur_addr = st.session_state.get("live_address","")

    if cur_lat and cur_lng:
        acc_txt = f" · ±{cur_acc} m" if cur_acc else ""
        st.success(f"✅ **{cur_lat}**, **{cur_lng}**{acc_txt}")
        if cur_addr:
            st.info(f"📍 Detected address: **{cur_addr}**")
        st.markdown(map_embed_coords(cur_lat, cur_lng, 230), unsafe_allow_html=True)
        st.caption("🗺️ Confirm the pin is on the correct shop before saving.")

    return cur_lat, cur_lng, cur_acc


def address_autocomplete_widget(current_value: str = "", key_suffix: str = "co") -> str:
    """
    Renders a Nominatim-powered search-as-you-type address autocomplete
    inside an st.components.v1.html iframe.

    - User types a partial address / shop name
    - Suggestions appear as a dropdown (fetched from Nominatim)
    - Clicking a suggestion:
        1. Fills the address field inside the component
        2. Sets query param addr_{key_suffix} → triggers Streamlit rerun
        3. Also sets addr_{key_suffix}_lat / addr_{key_suffix}_lng so the map
           can update to the chosen place

    Returns the selected address string (or current_value if nothing selected yet).
    """
    qp = st.query_params
    lat_key  = f"addr_{key_suffix}_lat"
    lng_key  = f"addr_{key_suffix}_lng"
    addr_key = f"addr_{key_suffix}"

    # Consume query params written by the JS component
    if addr_key in qp:
        selected = str(qp[addr_key]).strip()
        st.session_state[f"ac_addr_{key_suffix}"] = selected
        if lat_key in qp:
            st.session_state[f"ac_lat_{key_suffix}"]  = str(qp[lat_key])
        if lng_key in qp:
            st.session_state[f"ac_lng_{key_suffix}"]  = str(qp[lng_key])
        # Clean up
        for k in [addr_key, lat_key, lng_key]:
            if k in qp: del qp[k]
        st.rerun()

    resolved = st.session_state.get(f"ac_addr_{key_suffix}", current_value)
    ac_lat   = st.session_state.get(f"ac_lat_{key_suffix}", "")
    ac_lng   = st.session_state.get(f"ac_lng_{key_suffix}", "")

    # The autocomplete HTML component
    safe_val = resolved.replace("'", "\\'").replace('"', '&quot;')
    ac_html = f"""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'DM Sans',sans-serif;background:transparent;padding:2px 0}}
  #wrap{{position:relative;width:100%}}
  #inp{{
    width:100%;padding:9px 12px;font-size:.9rem;
    border:1.5px solid #c8e6d4;border-radius:10px;
    background:#fff;color:#1a2e22;outline:none;
    transition:border-color .2s;
  }}
  #inp:focus{{border-color:#1a7f4b;box-shadow:0 0 0 3px rgba(26,127,75,.12)}}
  #list{{
    position:absolute;top:calc(100% + 4px);left:0;right:0;
    background:#fff;border:1.5px solid #c8e6d4;border-radius:10px;
    box-shadow:0 8px 24px rgba(0,0,0,.12);z-index:9999;
    max-height:220px;overflow-y:auto;display:none;
  }}
  .item{{
    padding:9px 13px;font-size:.82rem;color:#1a2e22;cursor:pointer;
    border-bottom:1px solid #eef5f0;line-height:1.35;
  }}
  .item:last-child{{border-bottom:none}}
  .item:hover,.item.active{{background:#f0faf4;color:#1a7f4b}}
  #status{{font-size:.72rem;color:#5a7a65;margin-top:4px;min-height:1rem;padding-left:2px}}
</style>
</head>
<body>
<div id="wrap">
  <input id="inp" type="text" placeholder="Search shop name or street address…"
         value="{safe_val}" autocomplete="off" spellcheck="false"/>
  <div id="list"></div>
</div>
<div id="status"></div>
<script>
var inp   = document.getElementById('inp');
var list  = document.getElementById('list');
var stat  = document.getElementById('status');
var timer = null;
var items = [];
var sel   = -1;

inp.addEventListener('input', function(){{
  clearTimeout(timer);
  var q = inp.value.trim();
  if(q.length < 3){{ list.style.display='none'; return; }}
  stat.innerText = '🔍 Searching…';
  timer = setTimeout(function(){{ doSearch(q); }}, 350);
}});

inp.addEventListener('keydown', function(e){{
  var rows = list.querySelectorAll('.item');
  if(e.key==='ArrowDown'){{   sel=Math.min(sel+1,rows.length-1); highlight(rows); e.preventDefault(); }}
  else if(e.key==='ArrowUp'){{ sel=Math.max(sel-1,0);           highlight(rows); e.preventDefault(); }}
  else if(e.key==='Enter' && sel>=0){{ rows[sel].click(); e.preventDefault(); }}
  else if(e.key==='Escape'){{ list.style.display='none'; }}
}});

function highlight(rows){{
  rows.forEach(function(r,i){{ r.classList.toggle('active', i===sel); }});
  if(sel>=0) rows[sel].scrollIntoView({{block:'nearest'}});
}}

function doSearch(q){{
  fetch('https://nominatim.openstreetmap.org/search?q='+encodeURIComponent(q)
      +'&format=json&limit=6&addressdetails=1',
      {{headers:{{'Accept-Language':'en','User-Agent':'GarlicOrderApp/1.0'}}}})
  .then(function(r){{return r.json();}})
  .then(function(data){{
    stat.innerText = data.length ? '' : '⚠️ No results — try a different search.';
    items = data;
    sel = -1;
    list.innerHTML = '';
    if(!data.length){{ list.style.display='none'; return; }}
    data.forEach(function(d,i){{
      var div = document.createElement('div');
      div.className = 'item';
      // Show short label (road + city) on first line, full address smaller
      var short = [d.address.road,d.address.suburb,d.address.city||d.address.town||d.address.village]
                   .filter(Boolean).join(', ');
      div.innerHTML = '<strong>'+(short||d.display_name.split(',')[0])+'</strong>'
                    + '<br><span style="font-size:.72rem;color:#5a7a65">'
                    + d.display_name.split(',').slice(0,4).join(',') + '</span>';
      div.addEventListener('click', function(){{
        var chosen = d.display_name.split(',').slice(0,5).join(',').trim();
        inp.value = chosen;
        list.style.display = 'none';
        stat.innerText = '✅ Selected';
        // Send back to Streamlit via parent URL redirect
        var url = new URL(window.parent.location.href);
        url.searchParams.set('{addr_key}', chosen);
        url.searchParams.set('{lat_key}',  d.lat);
        url.searchParams.set('{lng_key}',  d.lon);
        window.parent.location.href = url.toString();
      }});
      list.appendChild(div);
    }});
    list.style.display = 'block';
  }})
  .catch(function(){{
    stat.innerText = '⚠️ Search unavailable — type address manually.';
    list.style.display = 'none';
  }});
}}

// Close dropdown on outside click
document.addEventListener('click', function(e){{
  if(!document.getElementById('wrap').contains(e.target))
    list.style.display='none';
}});
</script>
</body>
</html>
"""
    st.components.v1.html(ac_html, height=62, scrolling=False)

    # If a suggestion was picked, show its coordinates too
    if ac_lat and ac_lng and not st.session_state.get("live_lat",""):
        st.caption(f"📍 From search: {ac_lat}, {ac_lng}")

    return resolved, ac_lat, ac_lng


def topbar(role_label, role_color="#1a7f4b"):
    user = st.session_state.user
    c1,c2,c3 = st.columns([5,3,2])
    with c1:
        st.markdown(
            '<div style="display:flex;align-items:center;gap:10px;padding:6px 0">'
            '<span style="font-size:1.6rem">🧄</span>'
            '<span style="font-family:Syne,sans-serif;font-weight:800;font-size:1.15rem;'
            'color:#1a7f4b">Garlic Order & Delivery</span></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(
            f'<div style="text-align:center;padding-top:8px">'
            f'<span style="background:{role_color};color:#fff;padding:4px 14px;'
            f'border-radius:20px;font-size:.8rem;font-weight:700">{role_label}</span>'
            f'&nbsp;<code style="font-size:.72rem;color:#5a7a65">{user["uid"]}</code>'
            f'</div>', unsafe_allow_html=True)
    with c3:
        if st.session_state.get("task_done",False):
            if st.button("🚪 Logout", key="topbar_logout"):
                if user["role"]=="delivery Driver":
                    dr = find_row("driver_onboard","Mobile",user["phone"])
                    if dr: set_driver_status(dr["Driver ID"],"Offline")
                for k in DEFAULTS: st.session_state[k] = DEFAULTS[k]
                st.rerun()
        else:
            st.markdown('<div style="text-align:right;padding-top:10px">'
                        '<span style="color:#5a7a65;font-size:.8rem">🔒 Complete tasks to logout</span>'
                        '</div>', unsafe_allow_html=True)
    st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: LOGIN / REGISTER
# ═══════════════════════════════════════════════════════════════════════════════
def page_login():
    st.markdown("""
<div style="display:flex;flex-direction:column;align-items:center;margin-top:2.5rem;margin-bottom:1.5rem">
  <div style="width:68px;height:68px;border-radius:18px;background:#1a7f4b;display:flex;
              align-items:center;justify-content:center;font-size:34px;margin-bottom:12px;
              box-shadow:0 8px 24px rgba(26,127,75,.35)">🧄</div>
  <h1 style="font-size:1.8rem;color:#0d1f14;margin:0">Garlic Order & Delivery</h1>
  <p style="color:#5a7a65;font-size:.95rem;margin-top:4px">Field Operations Platform</p>
</div>""", unsafe_allow_html=True)

    col = st.columns([1,2,1])[1]
    with col:
        tab_lg, tab_rg = st.tabs(["🔐  Login","📝  Register"])
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
                        st.session_state.user = user
                        st.session_state.task_done = False
                        if user["role"]=="delivery Driver":
                            dr = find_row("driver_onboard","Mobile",user["phone"])
                            if dr:
                                set_driver_status(dr["Driver ID"],"Active")
                                st.session_state.driver_id = dr["Driver ID"]
                        st.rerun()

        with tab_rg:
            rn   = st.text_input("Full name *",                             key="rg_name")
            rph  = st.text_input("Phone number *",                          key="rg_ph")
            rem  = st.text_input("Email *", placeholder="you@example.com", key="rg_email")
            rrol = st.selectbox("Role *",["sales executive","delivery Driver","admin"], key="rg_role")
            rpw  = st.text_input("Password *",         type="password",     key="rg_pw")
            rpw2 = st.text_input("Confirm password *", type="password",     key="rg_pw2")
            gate = st.text_input("Admin Registration Password *", type="password", key="rg_gate",
                                 help="Contact admin for this password.")
            if st.button("Create account →", type="primary", use_container_width=True, key="rg_btn"):
                if not rn.strip():          st.error("Full name required.")
                elif not rph.strip():       st.error("Phone required.")
                elif "@" not in rem:        st.error("Enter valid email.")
                elif len(rpw) < 6:          st.error("Password min 6 chars.")
                elif rpw != rpw2:           st.error("Passwords don't match.")
                elif not gate:              st.error("Admin Registration Password required.")
                elif gate != ADMIN_REGISTER_PASSWORD:
                    st.error("❌ Invalid Admin Registration Password.")
                else:
                    with st.spinner("Creating…"):
                        uid, err = register_user(rn, rph, rem.strip().lower(), rrol, rpw)
                    if err: st.error(f"❌ {err}")
                    else:
                        st.success("✅ Account created!")
                        st.info(f"UID: **`{uid}`** — login with your email.")

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: ADMIN
# ═══════════════════════════════════════════════════════════════════════════════
def page_admin():
    user = st.session_state.user
    topbar("🛡️ Admin","#185fa5")

    tabs = st.tabs(["📦 SKUs","🗺️ Trips","🚚 Assign Drivers",
                    "👤 Customers","🚗 Driver Onboard","📋 Orders","📝 Audit Log"])

    # ── SKUs ─────────────────────────────────────────────────────────────────
    with tabs[0]:
        st.markdown(sl("📦 SKU Master"), unsafe_allow_html=True)
        df_sku = read_sheet("skus")
        if not df_sku.empty:
            act = len(df_sku[df_sku["Active"].astype(str).str.lower()=="true"])
            avg = df_sku["Price"].apply(lambda x:float(str(x).replace("₹","").replace(",","") or 0)).mean()
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Total SKUs",len(df_sku)); c2.metric("Active",act)
            c3.metric("Disabled",len(df_sku)-act); c4.metric("Avg price",f"₹{avg:,.2f}")
        with st.expander("➕ Add new SKU"):
            sc1,sc2,sc3 = st.columns(3)
            with sc1:
                sk_code = st.text_input("SKU code *",  placeholder="GRLIC-1KG", key="sk_c")
                sk_name = st.text_input("SKU name *",  placeholder="Garlic 1KG", key="sk_n")
            with sc2:
                sk_price = st.number_input("Price ₹ *",min_value=0.0,step=1.0,  key="sk_p")
                sk_wt    = st.selectbox("Weight type",["KG","Gram","Box","Piece","Dozen"],key="sk_w")
            with sc3:
                sk_cat = st.text_input("Category",placeholder="Garlic",          key="sk_cat")
            if st.button("Add SKU",type="primary",key="sk_add"):
                if not sk_code or not sk_name or sk_price<=0: st.error("Code, name and price required.")
                elif col_exists("skus","SKU Code",sk_code):   st.error("SKU code exists.")
                else:
                    append_row("skus",[sk_code,sk_name,sk_price,sk_wt,sk_cat or "General","true",user["uid"],str(date.today())])
                    load_skus.clear()
                    write_admin_log(user["uid"],user.get("email",""),"ADD SKU","SKU",sk_code,"","",sk_name)
                    st.success(f"SKU **{sk_code}** added!")
                    st.session_state.task_done=True; st.rerun()
        df_sku = read_sheet("skus")
        if df_sku.empty:
            st.info("No SKUs yet.")
        else:
            for idx,row in df_sku.iterrows():
                c1,c2,c3,c4,c5 = st.columns([2,2.5,1.5,1,1.5])
                c1.markdown(f"**`{row['SKU Code']}`**"); c2.write(row["SKU Name"])
                new_p = c3.number_input("₹",value=float(str(row["Price"]).replace("₹","").replace(",","") or 0),
                                        step=1.0,key=f"skp{idx}",label_visibility="collapsed")
                is_act = str(row.get("Active","")).lower()=="true"
                c4.markdown(pill("Active","pill-on") if is_act else pill("Off","pill-off"),unsafe_allow_html=True)
                if c5.button("Disable" if is_act else "Enable",key=f"skt{idx}"):
                    update_row("skus","SKU Code",row["SKU Code"],
                               {"Active":"false" if is_act else "true","Price":new_p})
                    write_admin_log(user["uid"],user.get("email",""),
                                    ("Disable" if is_act else "Enable")+" SKU","SKU",row["SKU Code"],row["Price"],new_p)
                    load_skus.clear(); st.session_state.task_done=True; st.rerun()
                st.divider()

    # ── Trips ─────────────────────────────────────────────────────────────────
    with tabs[1]:
        st.markdown(sl("🗺️ Trips & Routes"), unsafe_allow_html=True)
        with st.expander("➕ Create new trip"):
            tc1,tc2 = st.columns(2)
            with tc1:
                tr_id   = st.text_input("Trip ID *",placeholder="TRP-001",key="tr_id")
                tr_date = st.date_input("Date *",value=date.today(),       key="tr_date")
            with tc2:
                tr_city = st.selectbox("City",["Bengaluru","Mysuru","Hubli","Mangaluru"],key="tr_city")
            custs_df = load_customers()
            sel_ids = []
            if not custs_df.empty:
                shop_opts = custs_df.apply(lambda r:f"{r['CUST-ID']} — {r['Shop Name']} ({r['City']})",axis=1).tolist()
                cust_ids  = custs_df["CUST-ID"].tolist()
                sel_shops = st.multiselect("Select shops *",shop_opts,key="tr_shops")
                sel_ids   = [cust_ids[shop_opts.index(s)] for s in sel_shops]
                if sel_ids: st.info(f"✅ {len(sel_ids)} shop(s): {', '.join(sel_ids)}")
            else:
                st.warning("No customers onboarded yet.")
            if st.button("Create trip",type="primary",key="tr_btn"):
                if not tr_id or not sel_ids: st.error("Trip ID and at least one shop required.")
                elif col_exists("trips","Trip ID",tr_id): st.error("Trip ID exists.")
                else:
                    append_row("trips",[tr_id,str(tr_date),tr_city,",".join(sel_ids),"","","Assigned",
                                        user["uid"],datetime.now().strftime("%Y-%m-%d %H:%M:%S")])
                    write_admin_log(user["uid"],user.get("email",""),"CREATE TRIP","Trip",tr_id,"","",f"{len(sel_ids)} shops")
                    st.success(f"Trip **{tr_id}** created!"); st.session_state.task_done=True; st.rerun()
        trips_df = read_sheet("trips")
        if not trips_df.empty:
            td = trips_df.copy()
            td["Shop Count"] = td["Shops"].apply(lambda s:len([x for x in str(s).split(",") if x.strip()]))
            st.dataframe(td,use_container_width=True,hide_index=True)
        else:
            st.info("No trips yet.")

    # ── Assign Drivers ────────────────────────────────────────────────────────
    with tabs[2]:
        st.markdown(sl("🚚 Active Drivers & Assignment"), unsafe_allow_html=True)
        all_d = read_sheet("driver_onboard")
        act_d = active_drivers()
        if all_d.empty:
            st.warning("No drivers onboarded yet.")
        else:
            st.success(f"🟢 {len(act_d)} active · ⚫ {len(all_d)-len(act_d)} offline")
            for _,r in all_d.iterrows():
                is_on = str(r.get("Active Status","")).lower()=="active"
                c1,c2,c3,c4 = st.columns([2,2,2,1])
                c1.markdown(f"**{r['Full Name']}**")
                vn = r.get("Vehicle Number","")
                c2.write(f"`{r['Driver ID']}` · {r.get('Vehicle Type','')} {('· '+vn) if vn else ''}")
                c3.write(f"Last active: {r.get('Last Active','')}")
                c4.markdown(pill("Active","pill-on") if is_on else pill("Offline","pill-off"),unsafe_allow_html=True)
        st.divider()
        trips_df = read_sheet("trips")
        if not trips_df.empty and not all_d.empty:
            st.markdown("#### Assign / Reassign Driver to Trip")
            ac1,ac2 = st.columns(2)
            with ac1:
                sel_trip = st.selectbox("Select trip",trips_df["Trip ID"].tolist(),key="asgn_trip")
                if sel_trip:
                    t = trips_df[trips_df["Trip ID"]==sel_trip].iloc[0]
                    sids = [s.strip() for s in str(t.get("Shops","")).split(",") if s.strip()]
                    st.caption(f"📦 {len(sids)} shops · {t['City']} · {t['Date']} · Driver: **{t.get('Driver Name','None')}**")
            with ac2:
                drv_opts = all_d.apply(lambda r:f"{r['Full Name']} ({r['Driver ID']}) — {r.get('Active Status','')}",axis=1).tolist()
                drv_ids  = all_d["Driver ID"].tolist()
                sel_lbl  = st.selectbox("Select driver",drv_opts,key="asgn_drv")
                sel_id   = drv_ids[drv_opts.index(sel_lbl)] if sel_lbl else ""
                drv_name = all_d[all_d["Driver ID"]==sel_id]["Full Name"].values[0] if sel_id else ""
            if st.button("✅ Assign Driver",type="primary",key="asgn_btn"):
                update_row("trips","Trip ID",sel_trip,{"Driver UID":sel_id,"Driver Name":drv_name,"Status":"Assigned"})
                write_admin_log(user["uid"],user.get("email",""),"ASSIGN DRIVER","Trip",sel_trip,"",sel_id,drv_name)
                st.success(f"**{drv_name}** → **{sel_trip}**"); st.session_state.task_done=True; st.rerun()
        else:
            st.info("Create trips and onboard drivers first.")

    # ── Customers ─────────────────────────────────────────────────────────────
    with tabs[3]:
        st.markdown(sl("👤 Customer Onboard Data"), unsafe_allow_html=True)
        df_c = load_customers()
        if df_c.empty:
            st.info("No customers onboarded yet.")
        else:
            c1,c2,c3 = st.columns(3)
            c1.metric("Total",len(df_c)); c2.metric("Active",len(df_c[df_c["Status"]=="Active"]))
            c3.metric("Cities",df_c["City"].nunique())
            st.dataframe(df_c,use_container_width=True,hide_index=True)

    # ── Driver Onboard ─────────────────────────────────────────────────────────
    with tabs[4]:
        st.markdown(sl("🚗 Driver Onboard","amber"), unsafe_allow_html=True)
        ds1,ds2 = st.columns([3,1])
        with ds1: do_sv = st.text_input("Search by mobile",key="adm_do_search")
        with ds2:
            st.write(""); st.write("")
            do_dos = st.button("🔍 Search",key="adm_do_sb")
        if do_dos and do_sv:
            ex = find_row("driver_onboard","Mobile",do_sv.strip())
            if ex:
                acct = str(ex.get("Account Number",""))
                masked = ("*"*(len(acct)-4)+acct[-4:]) if len(acct)>4 else "****"
                st.success(f"✅ Driver ID: **{ex['Driver ID']}**")
                st.json({"Name":ex.get("Full Name"),"Vehicle":ex.get("Vehicle Type"),
                         "Vehicle No":ex.get("Vehicle Number","—"),"Bank":ex.get("Bank Name"),
                         "Account":masked,"Status":ex.get("Active Status")})
            else:
                st.info("Not found — fill form below.")
        st.divider()
        st.markdown("#### Onboard New Driver")
        dn1,dn2,dn3 = st.columns(3)
        with dn1:
            do_name   = st.text_input("Full name *",   key="adm_do_name")
            do_mob    = st.text_input("Mobile *",      placeholder="10-digit",       key="adm_do_mob")
            do_email  = st.text_input("Email",                                        key="adm_do_email")
        with dn2:
            do_veh    = st.selectbox("Vehicle type",["Bike","Auto","Van","Truck","Mini-Truck"],key="adm_do_veh")
            do_veh_no = st.text_input("Vehicle Number *",placeholder="KA-01-AB-1234",key="adm_do_veh_no")
            do_bank   = st.text_input("Bank name *",                                  key="adm_do_bank")
        with dn3:
            do_acct  = st.text_input("Account number *",key="adm_do_acct")
            do_ifsc  = st.text_input("IFSC code *",     key="adm_do_ifsc")
            do_upi   = st.text_input("UPI ID",          placeholder="mobile@upi",    key="adm_do_upi")
        st.caption("🔒 Bank details visible to admin only.")
        if st.button("✅ Onboard Driver",type="primary",use_container_width=True,key="adm_do_btn"):
            if not all([do_name,do_mob,do_veh_no,do_bank,do_acct,do_ifsc]):
                st.error("Fill all required (*) fields including Vehicle Number.")
            else:
                with st.spinner("Checking…"):
                    ex = find_row("driver_onboard","Mobile",do_mob.strip())
                if ex:
                    st.warning(f"⚠️ Already registered — Driver ID: **{ex['Driver ID']}**")
                else:
                    did = gen_driver_id()
                    append_row("driver_onboard",[did,do_name,do_mob,do_email,do_veh,do_veh_no,
                                                  do_bank,do_acct,do_ifsc,do_upi,str(date.today()),"Offline",""])
                    write_admin_log(user["uid"],user.get("email",""),"ONBOARD DRIVER","Driver",did,"","",do_name)
                    st.success(f"✅ Driver ID: **`{did}`**"); st.session_state.task_done=True; st.balloons()
        st.divider()
        df_d = read_sheet("driver_onboard")
        if not df_d.empty:
            c1,c2,c3 = st.columns(3)
            c1.metric("Total",len(df_d)); c2.metric("Active",len(df_d[df_d["Active Status"]=="Active"]))
            c3.metric("Offline",len(df_d[df_d["Active Status"]!="Active"]))
            disp = df_d.copy()
            if "Account Number" in disp.columns:
                disp["Account Number"] = disp["Account Number"].apply(
                    lambda v:("*"*(len(str(v))-4)+str(v)[-4:]) if len(str(v))>4 else "****")
            st.dataframe(disp,use_container_width=True,hide_index=True)

    # ── Orders (today only) ───────────────────────────────────────────────────
    with tabs[5]:
        st.markdown(sl("📋 Today's Orders"), unsafe_allow_html=True)
        today_str = str(date.today())
        df_o = read_sheet("base")
        if df_o.empty:
            st.info("No orders yet.")
        else:
            df_today = df_o[df_o["ORDER DATE"].astype(str).str.startswith(today_str)] if "ORDER DATE" in df_o.columns else df_o
            st.caption(f"📅 **{today_str}** — {len(df_today)} of {len(df_o)} total")
            if df_today.empty:
                st.info(f"No orders today.")
                if st.checkbox("Show all orders"):
                    st.dataframe(df_o,use_container_width=True,hide_index=True)
            else:
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Today",len(df_today))
                c2.metric("Pending",   len(df_today[df_today["Delivery Status"]=="Pending"]))
                c3.metric("Delivered", len(df_today[df_today["Delivery Status"]=="Delivered"]))
                c4.metric("Failed/Partial",len(df_today[df_today["Delivery Status"].isin(["Failed","Partial"])]))
                st.dataframe(df_today,use_container_width=True,hide_index=True)

    # ── Audit Log ─────────────────────────────────────────────────────────────
    with tabs[6]:
        st.markdown(sl("📝 Admin Audit Log","blue"), unsafe_allow_html=True)
        df_l = read_sheet("admin_log")
        if df_l.empty: st.info("No logs yet.")
        else: st.dataframe(df_l.sort_values("Timestamp",ascending=False),use_container_width=True,hide_index=True)

    st.divider()
    if not st.session_state.get("task_done",False):
        if st.button("✅ Mark All Tasks Done (enables Logout)",key="admin_td"):
            st.session_state.task_done=True; st.rerun()
    else:
        st.success("✅ Tasks complete — Logout active above.")

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: SALES EXECUTIVE
# ═══════════════════════════════════════════════════════════════════════════════
def page_sales():
    user = st.session_state.user
    topbar("🧑‍💼 Sales Executive · T1")
    tabs = st.tabs(["➕ New Order","👤 Onboard Customer","📋 My Orders"])

    # ── New Order ─────────────────────────────────────────────────────────────
    with tabs[0]:
        st.markdown(sl("🔍 Customer Lookup"), unsafe_allow_html=True)
        lc1,lc2,lc3 = st.columns([2,2,1])
        with lc1: lk_id  = st.text_input("Customer ID",placeholder="CUST-XXXXXX",key="lk_id")
        with lc2: lk_mob = st.text_input("OR Mobile",  placeholder="10-digit",   key="lk_mob")
        with lc3:
            st.write(""); st.write("")
            do_lk = st.button("Fetch →",key="lk_btn")

        if do_lk:
            with st.spinner("Looking up…"):
                cust = (find_row("customer_onboard","CUST-ID",lk_id.strip()) if lk_id.strip()
                        else find_row("customer_onboard","Mobile",lk_mob.strip()))
            if cust:
                # FIX E: store entire cust dict in session state clearly
                st.session_state.cust_data = {k: str(v) if v is not None else "" for k, v in cust.items()}
                st.success(f"✅ Found: **{cust.get('Full Name','')}** — {cust.get('Shop Name','')}")
            else:
                st.error("❌ Customer not found. Onboard them first.")
                st.session_state.cust_data = {}

        # FIX E: read cust from session state AFTER potential update above
        cust = st.session_state.get("cust_data", {})
        st.divider()

        # ── Show customer info card if fetched ────────────────────────────────
        if cust.get("CUST-ID"):
            st.markdown(sl("👤 Customer Details"), unsafe_allow_html=True)
            di1,di2,di3 = st.columns(3)
            with di1:
                st.markdown(autofill_box("Customer ID",      cust.get("CUST-ID","")), unsafe_allow_html=True)
                st.markdown(autofill_box("Shop Name",        cust.get("Shop Name","")), unsafe_allow_html=True)
            with di2:
                st.markdown(autofill_box("Mobile",           cust.get("Mobile","")), unsafe_allow_html=True)
                st.markdown(autofill_box("Classification",   cust.get("Classification","")), unsafe_allow_html=True)
            with di3:
                st.markdown(autofill_box("City",             cust.get("City","")), unsafe_allow_html=True)
                st.markdown(autofill_box("Sales Executive",  user["name"]), unsafe_allow_html=True)

            # FIX E+F: show shop location from customer onboard data
            auto_addr = cust.get("Shop Address","")
            auto_lat  = cust.get("Latitude","")
            auto_lng  = cust.get("Longitude","")

            st.markdown(sl("📍 Shop Location (from Customer Onboard)"), unsafe_allow_html=True)
            sl1,sl2,sl3 = st.columns(3)
            with sl1:
                st.markdown(autofill_box("Shop Address", auto_addr), unsafe_allow_html=True)
            with sl2:
                st.markdown(autofill_box("Latitude",  auto_lat), unsafe_allow_html=True)
            with sl3:
                st.markdown(autofill_box("Longitude", auto_lng), unsafe_allow_html=True)

            # Show map using coords if available, else address
            if auto_lat and auto_lng and auto_lat not in ("","0"):
                st.markdown(map_embed_coords(auto_lat, auto_lng, 230), unsafe_allow_html=True)
                st.caption(f"🌐 Pinned at {auto_lat}, {auto_lng}")
            elif auto_addr:
                st.markdown(map_embed(auto_addr, 230), unsafe_allow_html=True)
                st.caption("📍 Map based on address — update customer record with GPS for exact pin.")
            st.divider()

        # ── Order Details ─────────────────────────────────────────────────────
        st.markdown(sl("📦 Order Details"), unsafe_allow_html=True)
        oc1,oc2 = st.columns(2)
        with oc1:
            o_id   = st.text_input("Order ID (auto)",value=gen_order_id(),disabled=True,key="o_id")
            o_date = st.date_input("Order date",value=date.today(),key="o_date")
        with oc2:
            cities = ["Bengaluru","Mysuru","Hubli","Mangaluru","Hassan","Tumkur"]
            # FIX E: city auto-set from customer — use session state key to avoid conflict
            auto_city = cust.get("City","Bengaluru")
            ci = cities.index(auto_city) if auto_city in cities else 0
            o_city = st.selectbox("City *",cities,index=ci,key="o_city",
                                  help="Auto-filled from Customer Onboard Data")
            # FIX G: NO time_input for ordered time — captured at submit moment
            st.info("⏱️ Order time will be auto-captured when you submit.", icon="ℹ️")

        st.markdown(sl("⏰ Delivery Schedule"), unsafe_allow_html=True)
        sc1, sc2 = st.columns(2)
        with sc1: o_sopen = st.time_input("Shop opens at",    key="o_sopen")
        with sc2: o_dcoff = st.time_input("Delivery cut-off", key="o_dcoff")

        # ── SKU ───────────────────────────────────────────────────────────────
        st.markdown(sl("🛒 SKU / Product"), unsafe_allow_html=True)
        df_sku = active_skus()
        if df_sku.empty:
            st.warning("⚠️ No active SKUs. Ask admin to add SKUs first.")
            sel_sku = None; sku_row = None; sku_price = 0; sku_wt = ""; o_qty = 0; o_total = 0
        else:
            kc1,kc2,kc3 = st.columns(3)
            with kc1:
                sku_opts  = df_sku.apply(lambda r:f"{r['SKU Name']}  [{r['SKU Code']}]",axis=1).tolist()
                sku_codes = df_sku["SKU Code"].tolist()
                sel_disp  = st.selectbox("SKU / Product *",sku_opts,key="o_sku_disp")
                sel_sku   = sku_codes[sku_opts.index(sel_disp)]
                sku_row   = df_sku[df_sku["SKU Code"]==sel_sku].iloc[0]
                st.caption(f"SKU Code: `{sel_sku}`")
            with kc2:
                sku_price = float(str(sku_row["Price"]).replace("₹","").replace(",","") or 0)
                sku_wt    = str(sku_row["Weight Type"])
                st.markdown(autofill_box("Unit Price",  f"₹{sku_price:.2f}"), unsafe_allow_html=True)
                st.markdown(autofill_box("Weight Type", sku_wt),              unsafe_allow_html=True)
            with kc3:
                o_qty   = st.number_input("Ordered qty *",min_value=0.0,step=0.5,key="o_qty")
                o_total = sku_price * o_qty
                st.markdown(autofill_box("Order Total ₹", f"₹{o_total:,.2f} ({o_qty} × ₹{sku_price:.2f})"),
                            unsafe_allow_html=True)

        st.divider()
        if st.button("✅ Submit Order",type="primary",use_container_width=True,key="o_submit"):
            if not cust.get("CUST-ID"):
                st.error("Look up a customer first.")
            elif not sel_sku or o_qty <= 0:
                st.error("Select a SKU and enter quantity > 0.")
            elif not cust.get("Shop Address",""):
                st.error("Customer has no shop address — update customer record.")
            else:
                soid = "SO-" + o_id.replace("ORD-","")
                # FIX G: capture time at the exact moment of submit
                ordered_time = datetime.now().strftime("%H:%M:%S")
                # FIX F: lat/lng come from session_state.cust_data (read from sheet)
                save_lat = cust.get("Latitude","")
                save_lng = cust.get("Longitude","")
                append_row("base",[
                    o_id, soid, o_city, str(o_date), "", ordered_time,
                    cust.get("CUST-ID",""),        cust.get("Shop Name",""),
                    cust.get("Mobile",""),          cust.get("Classification",""),
                    user["name"],                   user["uid"],
                    sel_sku, sku_row["SKU Name"],   sku_wt, sku_price, o_qty, o_total,
                    0, "", "", "", "",
                    str(o_sopen), "", str(o_dcoff),
                    cust.get("Shop Address",""),    "Pending", user["uid"],
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    save_lat, save_lng,             # FIX F
                ])
                st.success(f"✅ Order **{o_id}** submitted at **{ordered_time}**! Total: **₹{o_total:,.2f}**")
                st.session_state.cust_data = {}
                st.session_state.task_done = True
                st.balloons()

    # ── Onboard Customer ──────────────────────────────────────────────────────
    with tabs[1]:
        st.markdown(sl("👤 Customer Onboarding"), unsafe_allow_html=True)

        # Search existing
        sc1,sc2 = st.columns([3,1])
        with sc1: co_search = st.text_input("Search existing by mobile",key="co_search")
        with sc2:
            st.write(""); st.write("")
            do_cos = st.button("🔍 Search",key="co_srch_btn")
        if do_cos and co_search:
            ex = find_row("customer_onboard","Mobile",co_search.strip())
            if ex:
                st.success(f"✅ CUST-ID: **{ex['CUST-ID']}**")
                st.json({"Name":ex.get("Full Name"),"Shop":ex.get("Shop Name"),
                         "City":ex.get("City"),"Lat":ex.get("Latitude",""),
                         "Lng":ex.get("Longitude",""),"Status":ex.get("Status")})
            else:
                st.info("Not found — fill form below.")
        st.divider()

        st.markdown("#### New Customer")
        nc1,nc2,nc3 = st.columns(3)
        with nc1:
            co_name  = st.text_input("Full name *",                             key="co_name")
            co_mob   = st.text_input("Mobile *",    placeholder="10-digit",     key="co_mob")
            co_email = st.text_input("Email",                                   key="co_email")
        with nc2:
            co_shop  = st.text_input("Shop name *",                             key="co_shop")
            co_city  = st.selectbox("City *",
                ["Bengaluru","Mysuru","Hubli","Mangaluru","Hassan","Tumkur"],    key="co_city")
            co_cls   = st.selectbox("Classification",
                ["Restaurants","PG","Pubs","Premium Hotels","Wholesale","Retail","Others"],                   key="co_cls")
        with nc3:
            co_addr_label = st.empty()
            co_addr_label.markdown("**Shop address \\***")

        # ── Shop Address: autocomplete search (Nominatim) ─────────────────────
        st.markdown(sl("📍 Shop Address"), unsafe_allow_html=True)
        st.markdown(
            "**Search** by shop name or street — or tap **Fetch Live Location** "
            "to auto-detect address and coordinates from your device GPS:",
            unsafe_allow_html=False)

        # Pre-fill with reverse-geocoded address if GPS was used
        prefill_addr = st.session_state.get("live_address","") or \
                       st.session_state.get("ac_addr_co","")

        # Autocomplete widget — search-as-you-type powered by Nominatim
        st.markdown('<div style="margin-bottom:4px"><span style="font-size:.82rem;'
                    'font-weight:600;color:#1a2e22">Search address / shop name</span></div>',
                    unsafe_allow_html=True)
        ac_addr, ac_lat, ac_lng = address_autocomplete_widget(prefill_addr, "co")

        # Manual text area as fallback / override (also shows what autocomplete picked)
        co_addr = st.text_input(
            "Confirmed shop address *",
            value=ac_addr or prefill_addr,
            key="co_addr",
            placeholder="Full address will appear here after search or GPS fetch",
            help="Edit if needed after selecting from search or fetching GPS location",
        )

        # Show map for the confirmed address
        if co_addr and co_addr.strip():
            if ac_lat and ac_lng and not st.session_state.get("live_lat",""):
                # Use precise coords from autocomplete selection
                st.markdown(map_embed_coords(ac_lat, ac_lng, 200), unsafe_allow_html=True)
            else:
                st.markdown(map_embed(co_addr, 200), unsafe_allow_html=True)
            st.caption("📍 Confirm this is the correct shop location.")

        # ── FIX J: Live Location + Reverse Geocode ────────────────────────────
        st.markdown(sl("📡 Live Location"), unsafe_allow_html=True)

        g1, g2 = st.columns(2)
        with g1:
            co_lat_manual = st.text_input("Latitude (manual override)",
                                          placeholder="e.g. 12.9716", key="co_lat_manual",
                                          help="Auto-filled by GPS button, or type manually")
        with g2:
            co_lng_manual = st.text_input("Longitude (manual override)",
                                          placeholder="e.g. 77.5946", key="co_lng_manual",
                                          help="Auto-filled by GPS button, or type manually")

        # Live location widget — GPS button + reverse geocode + map
        live_lat, live_lng, live_acc = live_location_widget()

        # Merge: GPS > autocomplete coords > manual
        final_lat = live_lat or co_lat_manual.strip() or ac_lat
        final_lng = live_lng or co_lng_manual.strip() or ac_lng

        # If GPS gave an address and the confirmed address is still empty, offer it
        rev_addr = st.session_state.get("live_address","")
        if rev_addr and not co_addr.strip():
            st.info(f"💡 GPS-detected address: **{rev_addr}** — copy it to the address field above if correct.")

        # Show map for manual lat/lng only (GPS map shown inside live_location_widget)
        if co_lat_manual.strip() and co_lng_manual.strip() and not live_lat:
            st.markdown(map_embed_coords(co_lat_manual.strip(), co_lng_manual.strip(), 200),
                        unsafe_allow_html=True)
            st.caption(f"📍 Manual: {co_lat_manual.strip()}, {co_lng_manual.strip()}")

        if st.button("✅ Onboard Customer",type="primary",use_container_width=True,key="co_btn"):
            if not all([co_name.strip(),co_mob.strip(),co_shop.strip(),co_addr.strip()]):
                st.error("Fill all required (*) fields including the confirmed shop address.")
            elif not final_lat or not final_lng:
                st.error("📍 Location required. Tap 'Fetch Live Location' or enter/search an address with coordinates.")
            else:
                with st.spinner("Checking duplicates…"):
                    ex = find_row("customer_onboard","Mobile",co_mob.strip())
                if ex:
                    st.warning(f"⚠️ Mobile already registered — CUST-ID: **{ex['CUST-ID']}**")
                else:
                    cid = gen_cust_id()
                    append_row("customer_onboard",[
                        cid, co_name.strip(), co_mob.strip(), co_email.strip(),
                        co_shop.strip(), co_addr.strip(), co_city, co_cls,
                        user["uid"], str(date.today()), "Active",
                        final_lat, final_lng,
                    ])
                    load_customers.clear()
                    # Clear live location + autocomplete state after save
                    for k in ["live_lat","live_lng","live_acc","live_address",
                              "ac_addr_co","ac_lat_co","ac_lng_co"]:
                        st.session_state[k] = ""
                    st.success(f"✅ Onboarded! CUST-ID: **`{cid}`** · Coords: {final_lat}, {final_lng}")
                    st.session_state.task_done = True
                    st.balloons()

    # ── My Orders (today) ─────────────────────────────────────────────────────
    with tabs[2]:
        st.markdown(sl("📋 My Orders — Today"), unsafe_allow_html=True)
        today_str = str(date.today())
        df_o = read_sheet("base")
        if df_o.empty:
            st.info("No orders yet.")
        else:
            my = df_o[df_o["sales executive Number"].astype(str)==user["uid"]]
            my_today = my[my["ORDER DATE"].astype(str).str.startswith(today_str)] if "ORDER DATE" in my.columns else my
            st.caption(f"📅 **{today_str}** — {len(my_today)} today / {len(my)} total")
            if my_today.empty:
                st.info(f"No orders today.")
                if st.checkbox("Show all my orders",key="se_all"):
                    df_show = my
                else:
                    df_show = pd.DataFrame()
            else:
                df_show = my_today
                tot = df_show["OrderTotal"].apply(lambda x:float(str(x).replace("₹","").replace(",","") or 0)).sum()
                c1,c2,c3,c4 = st.columns(4)
                c1.metric("Today",len(df_show))
                c2.metric("Pending",  len(df_show[df_show["Delivery Status"]=="Pending"]))
                c3.metric("Delivered",len(df_show[df_show["Delivery Status"]=="Delivered"]))
                c4.metric("Value",    f"₹{tot:,.0f}")
            if not df_show.empty if 'df_show' in dir() else False:
                cols_show = [c for c in ["Order ID","Customer shop name","SKU Name","OrderedQty",
                             "OrderTotal","ORDER DATE","ORDERED TIME","Delivery Status",
                             "Shop Location","Latitude","Longitude"] if c in df_show.columns]
                st.dataframe(df_show[cols_show].sort_values("ORDER DATE",ascending=False),
                             use_container_width=True,hide_index=True)

    st.divider()
    if not st.session_state.get("task_done",False):
        if st.button("✅ Mark All Tasks Done (enables Logout)",key="sales_td"):
            st.session_state.task_done=True; st.rerun()
    else:
        st.success("✅ Tasks complete — Logout active above.")

# ═══════════════════════════════════════════════════════════════════════════════
#  PAGE: DELIVERY DRIVER
# ═══════════════════════════════════════════════════════════════════════════════
def page_delivery():
    user = st.session_state.user
    topbar("🚚 Delivery Driver · T2","#854f0b")
    tabs = st.tabs(["🗺️ My Route","📦 History"])

    with tabs[0]:
        st.markdown(sl("🗺️ Route & Deliveries","amber"), unsafe_allow_html=True)
        is_active = st.session_state.get("driver_active",True)
        drv_id    = st.session_state.get("driver_id","")
        tog_lbl   = "🟢 Active — visible to admin" if is_active else "⚫ Offline — tap to go active"
        if st.button(tog_lbl,key="active_tog"):
            is_active = not is_active
            st.session_state.driver_active = is_active
            if drv_id: set_driver_status(drv_id,"Active" if is_active else "Offline")
            st.rerun()
        if not is_active:
            st.warning("You are offline. Tap above to go active.")
            return
        trip = get_driver_trip(user["uid"])
        if not trip:
            st.info("📋 No trip assigned. Contact admin.")
            return
        shop_ids = [s.strip() for s in str(trip.get("Shops","")).split(",") if s.strip()]
        st.info(f"**Trip:** {trip['Trip ID']} · **{trip['City']}** · **{trip['Date']}** · {len(shop_ids)} stops")

        df_orders = read_sheet("base")
        trip_ord  = {}
        if not df_orders.empty:
            for _,r in df_orders[df_orders["Tripid"].astype(str)==str(trip["Trip ID"])].iterrows():
                trip_ord[str(r["CustomerId"])] = r.to_dict()

        if str(trip.get("Status","")).lower()=="assigned":
            st.warning("Trip not started yet.")
            if st.button("▶️ Start Trip",type="primary",key="start_trip"):
                update_row("trips","Trip ID",trip["Trip ID"],{"Status":"In Progress"})
                st.rerun()
            return

        if "active_stop" not in st.session_state:
            st.session_state.active_stop = 0
        done_count = sum(1 for sid in shop_ids if trip_ord.get(sid) and
                         str(trip_ord[sid].get("Delivery Status","")) not in ("Pending",""))
        if done_count > st.session_state.active_stop:
            st.session_state.active_stop = done_count
        active_idx = st.session_state.active_stop

        for i,sid in enumerate(shop_ids):
            shop  = find_row("customer_onboard","CUST-ID",sid)
            order = trip_ord.get(sid)
            is_done = bool(order and str(order.get("Delivery Status","")) not in ("Pending",""))
            is_cur  = (i==active_idx) and not is_done
            icon  = "✅" if is_done else ("📍" if is_cur else "🔒")
            stat  = order.get("Delivery Status","Pending") if order else "No order"
            p_cls = "pill-done" if is_done else ("pill-pend" if is_cur else "pill-off")
            with st.container():
                r1,r2 = st.columns([9,2])
                with r1:
                    st.markdown(f"**{icon} Stop {i+1}** — {shop.get('Shop Name','') if shop else sid}")
                    if shop:
                        addr = shop.get("Shop Address","")
                        lat  = str(shop.get("Latitude","")).strip()
                        lng  = str(shop.get("Longitude","")).strip()
                        if addr: st.caption(f"📍 {addr}")
                        if lat and lng: st.caption(f"🌐 {lat}, {lng}")
                    if order:
                        st.caption(f"SKU: {order.get('SKU','')} · Qty: {order.get('OrderedQty','')} · ₹{order.get('OrderTotal','')}")
                with r2:
                    st.markdown(pill(stat,p_cls),unsafe_allow_html=True)
            if is_cur and i<=active_idx:
                addr = shop.get("Shop Address","") if shop else ""
                lat  = str(shop.get("Latitude","")).strip() if shop else ""
                lng  = str(shop.get("Longitude","")).strip() if shop else ""
                if lat and lng:
                    st.markdown(map_embed_coords(lat,lng,200),unsafe_allow_html=True)
                elif addr:
                    st.markdown(map_embed(addr,200),unsafe_allow_html=True)
                with st.form(key=f"del_form_{i}"):
                    st.markdown("##### Update delivery")
                    df1,df2,df3 = st.columns(3)
                    with df1:
                        d_reach  = st.time_input("Reach time *",value=datetime.now().time())
                        d_ddate  = st.date_input("Delivered date",value=date.today())
                    with df2:
                        d_status = st.selectbox("Status *",["Delivered","Partial","Failed","Rescheduled"])
                    with df3:
                        d_rqty   = st.number_input("Return qty",min_value=0.0,step=0.5)
                        d_reason = st.text_input("Return reason")
                    d_notes = st.text_input("Notes")
                    submitted = st.form_submit_button("✅ Submit & Unlock Next Stop",
                                                      type="primary",use_container_width=True)
                if submitted:
                    if order:
                        update_row("base","Order ID",order["Order ID"],{
                            "Delivery Status":    d_status,
                            "ShopReachTime":      str(d_reach),
                            "DELIVERED DATE":     str(d_ddate),
                            "ReturnQty":          d_rqty,
                            "Reason":             d_reason,
                            "return_updated_role":"delivery Driver",
                        })
                    st.session_state.active_stop = i+1
                    st.session_state.task_done   = True
                    st.success(f"✅ Stop {i+1} marked **{d_status}**. "
                               f"{'Next stop unlocked!' if i+1<len(shop_ids) else 'All stops done!'}")
                    st.rerun()
            st.divider()
        if active_idx >= len(shop_ids):
            st.success("🎉 All stops completed!")
            update_row("trips","Trip ID",trip["Trip ID"],{"Status":"Completed"})
            st.session_state.task_done = True

    with tabs[1]:
        st.markdown(sl("📦 Delivery History","amber"), unsafe_allow_html=True)
        df_h = read_sheet("base")
        if df_h.empty:
            st.info("No records.")
        else:
            my_h = df_h[(df_h["return_updated_role"].astype(str)=="delivery Driver") &
                        (df_h["Delivery Status"]!="Pending")]
            if my_h.empty:
                st.info("No completed deliveries yet.")
            else:
                cols_h = [c for c in ["Order ID","Customer shop name","SKU Name","OrderedQty",
                          "Delivery Status","DELIVERED DATE","ReturnQty","Reason"] if c in my_h.columns]
                st.dataframe(my_h[cols_h].sort_values("DELIVERED DATE",ascending=False),
                             use_container_width=True,hide_index=True)

    st.divider()
    if not st.session_state.get("task_done",False):
        if st.button("✅ Mark All Tasks Done (enables Logout)",key="driver_td"):
            st.session_state.task_done=True; st.rerun()
    else:
        st.success("✅ Tasks complete — Logout active above.")

# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════
_cp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
if not os.path.exists(_cp):
    _ok, _err = _test_connection()
    if not _ok:
        page_credential_error(str(_err))
        st.stop()

if not st.session_state.logged_in:
    page_login()
else:
    role = st.session_state.user["role"]
    if   role=="admin":           page_admin()
    elif role=="sales executive": page_sales()
    elif role=="delivery Driver": page_delivery()
    else:
        st.error(f"Unknown role: '{role}'")
        if st.button("Logout"):
            for k in DEFAULTS: st.session_state[k]=DEFAULTS[k]
            st.rerun()
