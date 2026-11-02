import base64
import csv
import json
import os
import time
from decimal import Decimal
import requests
from urllib.parse import urljoin, urlparse
from config import (
    ALLEGRO_CLIENT_ID, ALLEGRO_CLIENT_SECRET, ALLEGRO_REFRESH_TOKEN, ALLEGRO_USER_AGENT,
    ALLEGRO_API_URL, ALLEGRO_TOKEN_FILE, REQUEST_TIMEOUT, SLEEP_BETWEEN_REQUESTS, log
)


def get_active_allegro_offers(session: requests.Session, token: str) -> list:
    """Pobiera aktywne oferty sprzedawcy stronicowane po maksymalnie 1000."""
    url = f"{ALLEGRO_API_URL}/sale/offers"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }
    offers = []
    offset = 0
    limit = 1000

    while True:
        response = session.get(
            url,
            headers=headers,
            params={"publication.status": "ACTIVE", "limit": limit, "offset": offset},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        page = response.json()
        page_offers = page.get("offers", [])
        offers.extend(page_offers)
        total_count = page.get("totalCount")
        if len(page_offers) < limit or (total_count is not None and len(offers) >= total_count):
            break
        offset += len(page_offers)

    return offers


def update_allegro_offer_stock(session: requests.Session, token: str, offer_id: str,
                               quantity: int, dry_run: bool = False) -> bool:
    """Zmienia wyłącznie stock.available w pojedynczej ofercie Allegro."""
    if dry_run:
        log.info("[DRY-RUN] [ALLEGRO] Oferta %s: ustawiłbym stan=%s", offer_id, quantity)
        return True

    url = f"{ALLEGRO_API_URL}/sale/product-offers/{offer_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }
    try:
        response = session.patch(
            url,
            headers=headers,
            json={"stock": {"available": int(quantity)}},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        log.error("[ALLEGRO] Błąd połączenia podczas aktualizacji stanu oferty %s: %s",
                  offer_id, exc)
        return False
    if response.status_code == 200:
        return True
    if response.status_code != 202:
        log.error("[ALLEGRO] Błąd aktualizacji stanu oferty %s [%s]: %s",
                  offer_id, response.status_code, response.text)
        return False

    operation_url = response.headers.get("Location")
    if not operation_url:
        log.error("[ALLEGRO] Oferta %s: brak Location dla asynchronicznej aktualizacji", offer_id)
        return False
    operation_url = urljoin(url, operation_url)
    if urlparse(operation_url).netloc != urlparse(ALLEGRO_API_URL).netloc:
        log.error("[ALLEGRO] Oferta %s: nieoczekiwany adres statusu operacji", offer_id)
        return False

    operation_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }
    for _attempt in range(30):
        try:
            delay = int(response.headers.get("Retry-After", "1"))
        except ValueError:
            delay = 1
        time.sleep(max(1, delay))
        try:
            operation_response = session.get(
                operation_url, headers=operation_headers, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as exc:
            log.error("[ALLEGRO] Błąd sprawdzania operacji oferty %s: %s", offer_id, exc)
            return False

        if operation_response.status_code == 202:
            response = operation_response
            continue
        if operation_response.status_code in (200, 303):
            return True
        log.error("[ALLEGRO] Operacja oferty %s nie powiodła się [%s]: %s",
                  offer_id, operation_response.status_code, operation_response.text)
        return False

    log.error("[ALLEGRO] Przekroczono czas oczekiwania na aktualizację oferty %s", offer_id)
    return False


def sync_allegro_offer_stocks(session: requests.Session, token: str, cache: dict,
                              stock_by_key: dict, dry_run: bool = False) -> int:
    """Synchronizuje stany z mapy EAN/kod -> ilość wyłącznie dla aktywnych ofert.

    ID oferty zapisuje w tym samym cache JSON co dane Shopera. Pole `stock`
    należące do synchronizacji Shopera nie jest tu zmieniane.
    """
    offers = get_active_allegro_offers(session, token)
    cache_key_by_offer_id = {
        str(item.get("allegro_offer_id")): key
        for key, item in cache.items()
        if item.get("allegro_offer_id")
    }
    updated = 0
    matched = 0
    not_in_feed = 0
    without_cache = 0

    for offer in offers:
        if (offer.get("publication") or {}).get("status") != "ACTIVE":
            continue

        offer_id = str(offer.get("id", ""))
        external_id = str((offer.get("external") or {}).get("id", ""))
        cache_key = external_id if external_id in cache else cache_key_by_offer_id.get(offer_id)
        if not offer_id:
            continue
        if cache_key is None:
            without_cache += 1
            continue

        cached_item = cache[cache_key]
        cached_item["allegro_offer_id"] = offer_id
        desired_stock = stock_by_key.get(cache_key)
        if desired_stock is None:
            not_in_feed += 1
            continue
        matched += 1

        current_stock = (offer.get("stock") or {}).get("available")
        if current_stock is not None:
            current_stock = int(current_stock)
        if current_stock == desired_stock:
            cached_item["allegro_stock"] = desired_stock
            log.info("[ALLEGRO] Oferta %s ma już stan %s", offer_id, desired_stock)
            continue

        if update_allegro_offer_stock(session, token, offer_id, desired_stock, dry_run):
            updated += 1
            if not dry_run:
                cached_item["allegro_stock"] = desired_stock
                log.info("[ALLEGRO] Zaktualizowano stan oferty %s: %s -> %s",
                         offer_id, current_stock, desired_stock)
        if SLEEP_BETWEEN_REQUESTS > 0 and not dry_run:
            time.sleep(SLEEP_BETWEEN_REQUESTS)

    log.info(
        "[ALLEGRO] Aktywne oferty: %s, dopasowane do XML: %s, poza XML: %s, "
        "bez produktu w cache: %s, zmienione stany: %s",
        len(offers), matched, not_in_feed, without_cache, updated,
    )
    return updated


def get_all_allegro_offers(session: requests.Session, token: str,
                           output_path: str = "allegro_offers.json") -> list:
    """Pobiera wszystkie oferty sprzedawcy (stronicowanie limit=1000) i zapisuje je do JSON."""
    url = f"{ALLEGRO_API_URL}/sale/offers"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }
    offers = []
    offset = 0
    limit = 1000  # maksymalny limit obsługiwany przez Allegro

    while True:
        res = session.get(url, headers=headers, params={"limit": limit, "offset": offset},
                          timeout=REQUEST_TIMEOUT)
        res.raise_for_status()
        page = res.json()
        page_offers = page.get("offers", [])
        offers.extend(page_offers)
        total_count = page.get("totalCount")
        if len(page_offers) < limit or (total_count is not None and len(offers) >= total_count):
            break
        offset += len(page_offers)

    with open(output_path, "w", encoding="utf-8") as output:
        json.dump({"offers": offers}, output, ensure_ascii=False, indent=2)
    log.info("Zapisano %s ofert Allegro do %s", len(offers), output_path)
    return offers


def _offer_ean(offer: dict):
    """Znajduje EAN w danych oferty, jeśli lista ofert go zawiera."""
    external_id = (offer.get("external") or {}).get("id")
    if external_id:
        return external_id
    parameter_sets = [offer.get("parameters", [])]
    for product_entry in offer.get("productSet", []) or []:
        product_sets = product_entry.get("product", {})
        parameter_sets.append(product_sets.get("parameters", []))
    for parameters in parameter_sets:
        for parameter in parameters or []:
            name = str(parameter.get("name", "")).lower()
            if str(parameter.get("id")) == "225693" or "ean" in name or "gtin" in name:
                values = parameter.get("values") or parameter.get("valuesIds") or []
                if values:
                    return values[0]
    return ""


def export_allegro_offer_fees(session: requests.Session, token: str,
                              offers_path: str = "allegro_offers.json",
                              output_path: str = "allegro_offer_fees.csv") -> list:
    """Wylicza prowizję każdej oferty z JSON i zapisuje płaski raport CSV.

    Endpoint fee-preview przyjmuje pojedynczą ofertę, więc potrzeba jednego POST
    na ofertę. Wysyłamy tylko pola wpływające na kalkulację.
    """
    with open(offers_path, "r", encoding="utf-8") as source:
        data = json.load(source)
    offers = data if isinstance(data, list) else data.get("offers", [])
    url = f"{ALLEGRO_API_URL}/pricing/offer-fee-preview"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }
    rows = []
    for offer in offers:
        offer_id = offer.get("id", "")
        details = offer
        if offer_id:
            try:
                details_response = session.get(
                    f"{ALLEGRO_API_URL}/sale/product-offers/{offer_id}",
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                details_response.raise_for_status()
                details = details_response.json()
            except requests.RequestException as exc:
                log.error("Nie udało się pobrać szczegółów oferty %s: %s", offer_id, exc)

        category_id = (details.get("category") or offer.get("category") or {}).get("id", "")
        selling_mode = details.get("sellingMode") or offer.get("sellingMode") or {}
        price = selling_mode.get("price") or {}
        pricing_offer = {"category": {"id": category_id}} if category_id else {}
        if details.get("parameters"):
            pricing_offer["parameters"] = details["parameters"]
        if details.get("fundraisingCampaign"):
            pricing_offer["fundraisingCampaign"] = details["fundraisingCampaign"]
        publication = details.get("publication") or {}
        if "duration" in publication:
            # Oferta bez ustawionego czasu trwania (np. nieaktywna) jest liczona
            # jak standardowa publikacja 30-dniowa; prowizja sprzedażowa pozostaje
            # wyliczana na podstawie ceny i kategorii.
            pricing_offer["publication"] = {
                "duration": publication.get("duration") or "PT720H"
            }
        if selling_mode:
            pricing_offer["sellingMode"] = {
                key: selling_mode[key] for key in ("format", "price") if key in selling_mode
            }
        payload = {"offer": pricing_offer}
        if offer_id:
            pricing_offer["id"] = offer_id

        commission_fee = ""
        try:
            res = session.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            res.raise_for_status()
            response = res.json()
            fees = [item.get("fee", {}).get("amount") for item in response.get("commissions", [])
                    if item.get("type") == "commissionFee" and item.get("fee", {}).get("amount") is not None]
            commission_fee = str(sum((Decimal(fee) for fee in fees), Decimal("0.00"))) if fees else "0"
        except requests.RequestException as exc:
            error_body = getattr(getattr(exc, "response", None), "text", "")
            log.error("Błąd kalkulacji prowizji oferty %s: %s %s", offer_id, exc, error_body)
        except (ValueError, TypeError) as exc:
            log.error("Nieprawidłowa odpowiedź fee-preview dla oferty %s: %s", offer_id, exc)

        rows.append({
            "offer_id": offer_id,
            "ean": _offer_ean(offer),
            "category_id": category_id,
            "product price": price.get("amount", ""),
            "commision_fee": commission_fee,
        })

    with open(output_path, "w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=[
            "offer_id", "ean", "category_id", "product price", "commision_fee"
        ])
        writer.writeheader()
        writer.writerows(rows)
    log.info("Zapisano prowizje %s ofert Allegro do %s", len(rows), output_path)
    return rows


def get_allegro_token(session: requests.Session, refresh_token: str = None) -> str:
    """Pobiera access token przy użyciu refresh tokenu z allegro_token.json.

    Można przekazać refresh_token jawnie dla zgodności ze starszymi wywołaniami.
    Jeśli Allegro zwróci rotowany refresh token, aktualizujemy plik tokenu.
    """
    if not refresh_token and os.path.exists(ALLEGRO_TOKEN_FILE):
        with open(ALLEGRO_TOKEN_FILE, "r", encoding="utf-8") as token_file:
            token_data = json.load(token_file)
        refresh_token = token_data.get("refresh_token")
    refresh_token = refresh_token or os.environ.get("ALLEGRO_REFRESH_TOKEN") or ALLEGRO_REFRESH_TOKEN
    if not ALLEGRO_CLIENT_ID or not ALLEGRO_CLIENT_SECRET:
        raise RuntimeError("Brak ALLEGRO_CLIENT_ID lub ALLEGRO_CLIENT_SECRET w .env")
    if not refresh_token:
        raise RuntimeError("Brak ALLEGRO_REFRESH_TOKEN w .env")
    if not ALLEGRO_USER_AGENT:
        raise RuntimeError("Brak ALLEGRO_USER_AGENT w .env")

    auth_header = base64.b64encode(f"{ALLEGRO_CLIENT_ID}:{ALLEGRO_CLIENT_SECRET}".encode()).decode()
    url = "https://allegro.pl/auth/oauth/token"

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": ALLEGRO_USER_AGENT
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }

    res = session.post(url, headers=headers, data=data, timeout=REQUEST_TIMEOUT)
    res.raise_for_status()
    token_data = res.json()

    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError(f"Brak access_token w odpowiedzi od Allegro: {token_data}")

    rotated_refresh_token = token_data.get("refresh_token")
    if rotated_refresh_token:
        try:
            token_data_to_save = {}
            if os.path.exists(ALLEGRO_TOKEN_FILE):
                with open(ALLEGRO_TOKEN_FILE, "r", encoding="utf-8") as token_file:
                    token_data_to_save = json.load(token_file)
            token_data_to_save["refresh_token"] = rotated_refresh_token
            temporary_path = f"{ALLEGRO_TOKEN_FILE}.tmp"
            with open(temporary_path, "w", encoding="utf-8") as token_file:
                json.dump(token_data_to_save, token_file, ensure_ascii=False, indent=2)
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, ALLEGRO_TOKEN_FILE)
        except (OSError, IOError, ValueError) as exc:
            raise RuntimeError(
                f"Nie udało się bezpiecznie zapisać nowego refresh tokenu do {ALLEGRO_TOKEN_FILE}"
            ) from exc
    return access_token


def search_allegro_offer_by_ean(session: requests.Session, token: str, ean: str):
    """Wyszukuje ofertę na Allegro na podstawie kodu EAN."""
    url = f"{ALLEGRO_API_URL}/sale/offers"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }
    params = {"ean": ean}

    res = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    if res.status_code != 200:
        log.error(f"Błąd wyszukiwania oferty Allegro dla EAN {ean} [{res.status_code}]: {res.text}")
        return None

    offers = res.json().get("offers", [])
    if offers:
        return offers[0].get("id")  # Zwraca ID pierwszej znalezionej oferty
    return None


def update_allegro_stock_and_price(session: requests.Session, token: str, offer_id: str, produkt: dict,
                                   dry_run: bool = False):
    """Aktualizuje cenę i stany magazynowe w istniejącej ofercie Allegro."""
    if dry_run:
        log.info(
            f"[DRY-RUN] [ALLEGRO] Aktualizacja oferty ID {offer_id}: cena={produkt['cena_brutto']}, stan={produkt['stan']}")
        return True

    url = f"{ALLEGRO_API_URL}/sale/offer-price-changes"  # Lub odpowiedni endpoint command / stock change
    # Allegro wymaga konkretnej struktury JSON dla zmian w ofercie (Command API)
    # Przykładowy szkielet command API dla zmiany ceny/stanu:
    payload = {
        "input": {
            "buyNowPrice": {
                "amount": str(produkt["cena_brutto"]),
                "currency": "PLN"
            }
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.allegro.public.v1+json",
        "Content-Type": "application/vnd.allegro.public.v1+json",
        "User-Agent": ALLEGRO_USER_AGENT,
    }

    # Przykładowy endpoint dla modyfikacji parametrów logistyczno-cenowych w Allegro
    # (warto dostosować do aktualnej dokumentacji Allegro Command API dla ofert)
    res = session.put(f"{ALLEGRO_API_URL}/sale/offers/{offer_id}", json=payload, headers=headers,
                      timeout=REQUEST_TIMEOUT)
    # Uwaga: Allegro często używa endpointów asynchronicznych (Command API) typu /sale/product-offers / commands
    if res.status_code not in [200, 201, 202]:
        log.error(f"[ALLEGRO] Błąd aktualizacji oferty {offer_id} [{res.status_code}]: {res.text}")
        return False

    log.info(f"[ALLEGRO] Zaktualizowano ofertę ID {offer_id}")
    return True


def add_to_allegro(session: requests.Session, token: str, produkt: dict, dry_run: bool = False):
    """Tworzy nową ofertę na Allegro (wymaga pełnego szablonu produktu i powiązania z productization)."""
    if dry_run:
        log.info(f"[DRY-RUN] [ALLEGRO] Utworzyłbym ofertę dla kod={produkt['kod']} (EAN: {produkt['kod_kreskowy']})")
        return "MOCK_ALLEGRO_OFFER_ID"

    # Tworzenie oferty na Allegro wymaga m.in. kategorii, standardów i powiązania z katalogiems Allegro (produktem)
    # Tutaj wstawiasz logikę budującą payload zgodny z wymaganiami /sale/offers

    return None
