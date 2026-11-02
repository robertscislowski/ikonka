# Shoper / Allegro synchronization

## Raspberry Pi setup

Install Python 3 and Git, clone the repository, then run from its directory:

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env` with the feed URL, API credentials and the `ALLEGRO_USER_AGENT`
value registered for the Allegro application. Keep `.env` private; Git ignores
it. Store the Allegro refresh token in `allegro_token.json`; Git ignores that
file too, and the program saves rotated refresh tokens there. Run the normal
Shoper synchronization at least once so `products_cache.json` exists.

## Allegro stock synchronization

Preview the changes without writing to Allegro or the cache:

```sh
venv/bin/python main.py --allegro-stock-only --dry-run
```

Apply stock changes:

```sh
venv/bin/python main.py --allegro-stock-only
```

This mode reads stock quantities from the configured product XML and product
identifiers from the shared `products_cache.json`. It requests only active
Allegro offers, saves each matching `allegro_offer_id` in that cache, and sends
only `stock.available` when the Allegro quantity differs. It does not update
prices or call Shoper's API.

Example hourly cron entry (adjust the project path and schedule):

```cron
0 * * * * cd /home/pi/ikonka && /home/pi/ikonka/venv/bin/python main.py --allegro-stock-only
```
