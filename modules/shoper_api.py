import time
import requests
from requests.auth import HTTPBasicAuth
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import (
    SHOPER_API_URL, SHOPER_USER, SHOPER_PASSWORD, ADMIN_IP_VERIFY,
    REQUEST_TIMEOUT, SLEEP_BETWEEN_REQUESTS, log
)


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    if ADMIN_IP_VERIFY:
        session.cookies.set("admin_ip_verify", ADMIN_IP_VERIFY)
    return session


def get_shoper_token(session: requests.Session) -> str:
    auth_url = f"{SHOPER_API_URL}/auth/login" if "/auth" not in SHOPER_API_URL else SHOPER_API_URL
    auth = HTTPBasicAuth(SHOPER_USER, SHOPER_PASSWORD) if (SHOPER_USER and SHOPER_PASSWORD) else None

    headers = {}
    if ADMIN_IP_VERIFY:
        headers["Cookie"] = f"admin_ip_verify={ADMIN_IP_VERIFY}"

    res = session.post(auth_url, auth=auth, headers=headers, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    token = res.json().get("access_token")
    if not token:
        raise RuntimeError(f"Brak access_token w odpowiedzi API: {res.json()}")
    return token

def create_product(session: requests.Session, token: str, produkt: dict, dry_run: bool = False):
    if dry_run:
        log.info(f"[DRY-RUN] Utworzyłbym nowy produkt {produkt['kod']}: {produkt['nazwa']}")
        return "MOCK_ID"

    payload = {
        "translations": {
            "pl_PL": {
                "name": produkt["nazwa"],
                "short_description": produkt["opis_krotki"],
                "description": produkt["opis"],
            }
        },
        "stock": {
            "code": produkt["kod"],
            "ean": produkt["kod_kreskowy"],
            "price": produkt["cena_brutto"],
            "stock": produkt["stan"],
            "weight": produkt["waga"],
            "price_buying_net": produkt["cena_zakupu_netto"],
            "price_buying": produkt["cena_zakupu_brutto"],
        },
        "vat": produkt["vat"],
        "producer_id": produkt.get("producer_id"),  # Właściwe pole w Shoper API
        "images": [{"url": u} for u in produkt["zdjecia"]],
        "active": 1 if produkt["stan"] > 0 else 0,
    }

    url = f"{SHOPER_API_URL}/products"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res = session.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    new_id = res.json().get("product_id")
    log.info(f"Utworzono nowy produkt {produkt['kod']} (id={new_id})")
    return new_id


def update_stock_and_price(session: requests.Session, token: str, shoper_id: str, produkt: dict, dry_run: bool = False):
    if dry_run:
        log.info(f"[DRY-RUN] Aktualizacja ID {shoper_id}: cena={produkt['cena_brutto']} stan={produkt['stan']}")
        return True

    payload = {
        "stock": {
            "price": produkt["cena_brutto"],
            "stock": produkt["stan"],
            "price_buying_net": produkt["cena_zakupu_netto"],
            "price_buying": produkt["cena_zakupu_brutto"]
        }
    }

    url = f"{SHOPER_API_URL}/products/{shoper_id}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    res = session.put(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    return True


def update_product_active_statuses(session: requests.Session, token: str, dry_run: bool = False):
    if dry_run:
        log.info("[DRY-RUN] Weryfikacja statusów active pominięta")
        return

    log.info("Rozpoczęcie weryfikacji i aktualizacji statusów 'active' w Shoper API...")
    base_url = SHOPER_API_URL.rstrip('/')
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    tasks = [
        {
            "query_params": {
                "filters[translations.pl_PL.active][=]": 0,
                "filters[stock.stock][>]": 0
            },
            "new_active": 1,
            "label": "Aktywacja produktów ze stanem > 0"
        },
        {
            "query_params": {
                "filters[translations.pl_PL.active][=]": 1,
                "filters[stock.stock][=]": 0
            },
            "new_active": 0,
            "label": "Dezaktywacja produktów ze stanem 0"
        }
    ]

    for task in tasks:
        page = 1
        log.info(f"Rozpoczęto: {task['label']}")

        while True:
            params = task["query_params"].copy()
            params["page"] = page
            params["limit"] = 50

            try:
                res = session.get(f"{base_url}/products", params=params, headers=headers, timeout=15)
                if res.status_code != 200:
                    log.error(f"Błąd pobierania produktów [{res.status_code}]: {res.text}")
                    break

                data = res.json()
                items = data.get("list", [])
                if not items:
                    break

                for item in items:
                    product_id = item.get("product_id")
                    payload = {"translations": {"pl_PL": {"active": str(task["new_active"])}}}
                    put_res = session.put(f"{base_url}/products/{product_id}", json=payload, headers=headers,
                                          timeout=10)

                    if put_res.status_code == 200:
                        log.info(f"Produkt ID {product_id}: Zmieniono status active na -> {task['new_active']}")
                    else:
                        log.error(f"Produkt ID {product_id}: Błąd zmiany statusu active [{put_res.status_code}]")

                    if SLEEP_BETWEEN_REQUESTS > 0:
                        time.sleep(SLEEP_BETWEEN_REQUESTS)

                total_pages = data.get("pages", 1)
                if page >= total_pages:
                    break
                page += 1

            except Exception as e:
                log.error(f"Wyjątek podczas aktualizacji statusów active: {str(e)}")
                break

    log.info("Zakończono weryfikację i aktualizację statusów 'active'.")
