"""
Configuration module
Loads and manages all environment variables and settings
"""

import os
import ssl
from dotenv import load_dotenv

# Auto-detect OS
IS_WINDOWS = os.name == 'nt'

# Load environment variables from .env file
load_dotenv()

# --- TELEGRAM BOT SETTINGS ---
API_TOKEN = os.getenv("TG_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# --- DATABASE SETTINGS ---
TIDB_HOST = os.getenv("TIDB_HOST")
TIDB_USER = os.getenv("TIDB_USER")
TIDB_PASSWORD = os.getenv("TIDB_PASSWORD")
TIDB_DB_NAME = os.getenv("TIDB_DB_NAME", "test")

# --- MEDIA FILE IDS ---
PHOTO_FILE_ID = os.getenv("PHOTO_FILE_ID")
REQUEST_PHOTO_FILE_ID = os.getenv("REQUEST_PHOTO_FILE_ID")

# Script file IDs
MINE_SCRIPT_BANNER_ID = os.getenv("MINE_SCRIPT_BANNER_ID")
MINE_SCRIPT_FILE_ID = os.getenv("MINE_SCRIPT_FILE_ID")

OSKOLKI_SCRIPT_BANNER_ID = os.getenv("OSKOLKI_SCRIPT_BANNER_ID")
OSKOLKI_SCRIPT_FILE_ID = os.getenv("OSKOLKI_SCRIPT_FILE_ID")

# --- SPAM CONTROL SETTINGS ---
SPAM_SOFT_DELAY = 10.0   # 10 seconds between successful commands
SPAM_HARD_LIMIT = 0.8    # If more frequent than 0.8 sec - ban

# --- SSL CONFIGURATION ---
if IS_WINDOWS:
    # Windows: Use custom certificate if exists
    if os.path.exists("isrgrootx1.pem"):
        ssl_ctx = ssl.create_default_context(cafile="isrgrootx1.pem")
    else:
        # Fallback/Dev without cert
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
else:
    # Linux/Deploy: Use system default SSL (usually True works for TiDB)
    ssl_ctx = True

# --- DATABASE CONFIGURATION ---
DB_CONFIG = {
    'host': TIDB_HOST,
    'port': 4000,
    'user': TIDB_USER,
    'password': TIDB_PASSWORD,
    'db': TIDB_DB_NAME,
    'autocommit': True,
    'ssl': ssl_ctx,
    'pool_recycle': 300,  # Refresh connection every 5 minutes
    'connect_timeout': 10,
    'minsize': 1,
    'maxsize': 2  # Important for TiDB Serverless!
}

# --- ACCESS CACHE SETTINGS ---
ACCESS_CACHE_TTL = 300  # 5 minutes
ACCESS_CACHE_MAX = 5000
