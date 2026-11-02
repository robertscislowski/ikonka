import os
import sys
import logging
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ENV_FILE = os.path.join(BASE_DIR, ".env")
# Wspieraj dotychczasową lokalizację na komputerze deweloperskim, ale na
# Raspberry Pi i innych urządzeniach preferuj .env obok kodu projektu.
LEGACY_ENV_FILE = "/Users/robertscislowski/secrets/.env"
ALLEGRO_ENV_FILE = PROJECT_ENV_FILE if os.path.isfile(PROJECT_ENV_FILE) else LEGACY_ENV_FILE
load_dotenv(ALLEGRO_ENV_FILE)

XML_URL = os.environ.get("XML_URL") or os.environ.get("XML_FILE", "")
SHOPER_API_URL = (os.environ.get("SHOPER_API_URL") or os.environ.get("SHOPER_URL", "")).rstrip("/")
SHOPER_USER = os.environ.get("SHOPER_USER") or os.environ.get("SHOPER_LOGIN", "")
SHOPER_PASSWORD = os.environ.get("SHOPER_PASSWORD", "")
ADMIN_IP_VERIFY = os.environ.get("ADMIN_IP_VERIFY", "")

ALLEGRO_CLIENT_ID = os.getenv("ALLEGRO_CLIENT_ID")
ALLEGRO_CLIENT_SECRET = os.getenv("ALLEGRO_CLIENT_SECRET")
ALLEGRO_REFRESH_TOKEN = os.getenv("ALLEGRO_REFRESH_TOKEN")
ALLEGRO_TOKEN_FILE = os.path.join(BASE_DIR, "allegro_token.json")
# Środowisko: https://api.allegro.pl (produkcja) lub https://api.allegro.pl.allegrosandbox.pl (testy)
ALLEGRO_API_URL = os.getenv("ALLEGRO_API_URL", "https://api.allegro.pl")
ALLEGRO_USER_AGENT = os.getenv("ALLEGRO_USER_AGENT")

CACHE_FILE = os.environ.get("CACHE_FILE", "products_cache.json")
LOG_FILE = os.environ.get("LOG_FILE", "shoper-sync.log")
TEMP_XML_FILE = "temp_hurtownia.xml"
SLEEP_BETWEEN_REQUESTS = float(os.environ.get("SLEEP_BETWEEN_REQUESTS", "0.2"))
REQUEST_TIMEOUT = 30

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("product-sync")
