import os
import json
import time
from config import CACHE_FILE, SLEEP_BETWEEN_REQUESTS, log


def initialize_cache_from_shoper(session, base_url: str, token: str = None) -> dict:
    log.info("Brak pliku cache lub plik jest pusty. Inicjalizacja bufora z Shoper API...")
    cache = {}
    page = 1

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    while True:
        try:
            res = session.get(
                f"{base_url}/products",
                headers=headers,
                params={"page": page, "limit": 50},
                timeout=15
            )
            if res.status_code != 200:
                log.error(f"Nie udało się pobrać produktów do cache [Kod {res.status_code}]")
                break

            data = res.json()
            items = data.get("list", [])
            if not items:
                break

            for item in items:
                shoper_id = item.get("product_id")
                code = item.get("ean") or item.get("code")

                if code:
                    cache[str(code)] = {
                        "shoper_id": shoper_id,
                        "price": 0.0,
                        "price_buying_net": 0.0,
                        "price_buying": 0.0,
                        "stock": 0
                    }

            total_pages = data.get("pages", 1)
            if page >= total_pages:
                break
            page += 1

            if SLEEP_BETWEEN_REQUESTS > 0:
                time.sleep(SLEEP_BETWEEN_REQUESTS)

        except Exception as e:
            log.error(f"Błąd podczas pobierania produktów do cache: {str(e)}")
            break

    save_cache(cache)
    log.info(f"Utworzono nowy plik cache ({CACHE_FILE}) zawierający {len(cache)} produktów.")
    return cache


def load_cache(session, base_url: str, token: str = None) -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return initialize_cache_from_shoper(session, base_url, token)
                return json.loads(content)
        except Exception as e:
            log.warning(f"Plik cache jest uszkodzony ({e}). Ponowna inicjalizacja z Shoper API...")
            return initialize_cache_from_shoper(session, base_url, token)
    else:
        return initialize_cache_from_shoper(session, base_url, token)


def load_existing_cache() -> dict:
    """Wczytuje wspólny cache bez inicjalizacji lub żądań do Shoper API."""
    if not os.path.exists(CACHE_FILE):
        raise FileNotFoundError(
            f"Nie znaleziono {CACHE_FILE}. Najpierw uruchom zwykłą synchronizację Shoper."
        )
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        cache = json.load(f)
    if not isinstance(cache, dict):
        raise ValueError(f"Plik {CACHE_FILE} musi zawierać obiekt JSON produktów.")
    return cache


def save_cache(cache: dict):
    tmp_file = f"{CACHE_FILE}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)
    os.replace(tmp_file, CACHE_FILE)
