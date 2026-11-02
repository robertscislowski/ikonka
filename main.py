#!/usr/bin/env python3
import time
import argparse

from config import SLEEP_BETWEEN_REQUESTS, SHOPER_API_URL, log
from storage import load_cache, load_existing_cache, save_cache
from modules.xml_parser import download_xml_stream, stream_products
from modules.shoper_api import (
    build_session,
    get_shoper_token,
    create_product,
    update_stock_and_price,
    update_product_active_statuses
)
from modules.allegro_api import get_allegro_token, sync_allegro_offer_stocks


def run_allegro_stock_sync(dry_run: bool = False):
    """Uruchamia wyłącznie synchronizację stanów aktywnych ofert Allegro."""
    session = build_session()
    cache = load_existing_cache()

    stock_by_key = {}
    xml_stream = download_xml_stream(session)
    for produkt in stream_products(xml_stream):
        for product_key in (produkt.get("kod_kreskowy"), produkt.get("kod")):
            key = str(product_key).strip() if product_key else ""
            if key and key in cache:
                stock_by_key[key] = produkt["stan"]

    log.info("Dane stanów z XML dopasowano do %s produktów z cache.", len(stock_by_key))
    token = get_allegro_token(session)
    sync_allegro_offer_stocks(session, token, cache, stock_by_key, dry_run=dry_run)

    if not dry_run:
        save_cache(cache)


def main():
    parser = argparse.ArgumentParser(description="Synchronizacja XML -> Shoper & Allegro")
    parser.add_argument("--dry-run", action="store_true", help="Uruchomienie testowe na sucho")
    parser.add_argument("--update-only", action="store_true", help="Tylko aktualizacja cen i stanów (co godzinę)")
    parser.add_argument(
        "--allegro-stock-only",
        action="store_true",
        help="Synchronizuj wyłącznie stany aktywnych ofert Allegro (bez aktualizacji cen i Shopera)",
    )
    args = parser.parse_args()

    if args.allegro_stock_only:
        run_allegro_stock_sync(dry_run=args.dry_run)
        log.info("Synchronizacja stanów Allegro zakończona.")
        return

    session = build_session()

    token = None
    if not args.dry_run:
        token = get_shoper_token(session)

    # Przekazujemy pobrany token do pobrania cache z API
    cache = load_cache(session, SHOPER_API_URL, token)
    xml_stream = download_xml_stream(session)

    for produkt in stream_products(xml_stream):
        key = produkt["kod_kreskowy"] or produkt["kod"]
        if not key:
            continue

        cached_item = cache.get(key)

        if not cached_item:
            if args.update_only:
                continue

            try:
                shoper_id = create_product(session, token, produkt, args.dry_run)
                if shoper_id:
                    cache[key] = {
                        "shoper_id": shoper_id,
                        "price": produkt["cena_brutto"],
                        "price_buying_net": produkt["cena_zakupu_netto"],
                        "price_buying": produkt["cena_zakupu_brutto"],
                        "stock": produkt["stan"]
                    }
            except Exception as e:
                log.error(f"Błąd tworzenia produktu {key}: {e}")
            continue

        if (
                cached_item.get("price") == produkt["cena_brutto"]
                and cached_item.get("stock") == produkt["stan"]
                and cached_item.get("price_buying_net") == produkt["cena_zakupu_netto"]
                and cached_item.get("price_buying") == produkt["cena_zakupu_brutto"]
        ):
            continue

        shoper_id = cached_item.get("shoper_id")
        if shoper_id:
            try:
                update_stock_and_price(session, token, shoper_id, produkt, args.dry_run)
                cache[key]["price"] = produkt["cena_brutto"]
                cache[key]["price_buying_net"] = produkt["cena_zakupu_netto"]
                cache[key]["price_buying"] = produkt["cena_zakupu_brutto"]
                cache[key]["stock"] = produkt["stan"]
            except Exception as e:
                log.error(f"Błąd aktualizacji produktu {key}: {e}")

        if SLEEP_BETWEEN_REQUESTS > 0 and not args.dry_run:
            time.sleep(SLEEP_BETWEEN_REQUESTS)

    if not args.dry_run:
        save_cache(cache)

    if token and not args.dry_run:
        update_product_active_statuses(session, token, args.dry_run)

    log.info("Synchronizacja została całkowicie zakończona.")


if __name__ == "__main__":
    main()
