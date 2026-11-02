from modules.shoper_api import build_session
from modules.allegro_api import get_allegro_token, search_allegro_offer_by_ean
from config import log


def run_test():
    session = build_session()

    print("-> Próba pobrania access_token z Allegro przy użyciu refresh_token...")
    try:
        # 2. Test autoryzacji
        access_token = get_allegro_token(session)
        print(f"[SUKCES] Pobrano access_token! (początek: {access_token[:20]}...)")

        # 3. Opcjonalny test zapytania do API (np. wyszukanie testowego EAN)
        test_ean = "5900000000000"  # Możesz wpisać dowolny EAN do testu
        print(f"-> Test wyszukiwania oferty dla EAN: {test_ean}...")
        offer_id = search_allegro_offer_by_ean(session, access_token, test_ean)

        if offer_id:
            print(f"[SUKCES] Znaleziono ofertę o ID: {offer_id}")
        else:
            print(
                "[INFO] Brak oferty dla podanego EAN (co jest normalne, jeśli produkt nie jest wystawiony, ale samo zapytanie przeszło pomyślnie).")

    except Exception as e:
        print(f"[BŁĄD] Test zakończył się niepowodzeniem: {e}")


if __name__ == "__main__":
    run_test()
