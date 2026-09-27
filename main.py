import argparse
import logging


def parse_arguments():
    parser = argparse.ArgumentParser(description="Synchronizacja nowości XML z Shoper i Allegro.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Uruchomienie w trybie testowym: brak zapisu do JSON oraz brak wysyłki do API."
    )
    return parser.parse_args()


def main():
    args = parse_arguments()

    # Konfiguracja logowania
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    if args.dry_run:
        logging.info("=== TRYB DRY-RUN WŁĄCZONY ===")
        logging.info("Żadne dane nie zostaną zmodyfikowane w pliku JSON ani wysłane przez API.")

    # 1. Odczyt bazy JSON
    # 2. Strumieniowe czytanie XML
    # 3. Wykrywanie nowości (Diff Engine)
    # 4. Wysyłka do Shoper / Allegro (pomijane lub mockowane przy args.dry_run)
    # 5. Atomowy zapis JSON (pomijany przy args.dry_run)

    logging.info("Proces zakończony powodzeniem.")


if __name__ == "__main__":
    main()