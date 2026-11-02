import os
import base64
import json
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from config import ALLEGRO_CLIENT_ID as CLIENT_ID, ALLEGRO_CLIENT_SECRET as CLIENT_SECRET
from config import ALLEGRO_TOKEN_FILE, ALLEGRO_USER_AGENT

REDIRECT_URI = "http://localhost:8000/callback"  # Tymczasowy lokalny endpoint

auth_code = None


class OAuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/callback":
            query_params = parse_qs(parsed_path.query)
            if "code" in query_params:
                auth_code = query_params["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<h1>Autoryzacja udana! Mozesz zamknac to okno i wrocic do PyCharma.</h1>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Brak kodu autoryzacyjnego w zapytaniu.")

    def log_message(self, format, *args):
        pass  # Wycisza logi serwera w konsoli


def run_local_server():
    print("1. Otwórz poniższy link w przeglądarce, zaloguj się na Allegro i kliknij 'Zezwól':\n")
    auth_url = (
        f"https://allegro.pl/auth/oauth/authorize"
        f"?response_type=code&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
    )
    print(auth_url)
    print("\nCzekam na przekierowanie z przeglądarki na http://localhost:8000...")

    server = HTTPServer(("localhost", 8000), OAuthHandler)
    while auth_code is None:
        server.handle_request()

    return auth_code


if __name__ == "__main__":
    if not CLIENT_ID or not CLIENT_SECRET:
        print("[BŁĄD] Brak CLIENT_ID lub CLIENT_SECRET w pliku .env!")
        exit(1)

    # 1. Odpalamy mini serwer i czekamy na zgodę w przeglądarce
    code = run_local_server()
    print(f"\n[SUKCES] Otrzymano kod autoryzacyjny!")

    print("2. Wymieniam kod na access_token i refresh_token...")
    auth_header = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    url = "https://allegro.pl/auth/oauth/token"

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": ALLEGRO_USER_AGENT,
    }
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI
    }

    res = requests.post(url, headers=headers, data=data)
    if res.status_code == 200:
        token_data = res.json()
        refresh_token = token_data.get("refresh_token")

        # Refresh token przechowujemy w ignorowanym przez Git pliku tokenu.
        temporary_path = f"{ALLEGRO_TOKEN_FILE}.tmp"
        with open(temporary_path, "w", encoding="utf-8") as token_file:
            json.dump({"refresh_token": refresh_token}, token_file, indent=2)
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, ALLEGRO_TOKEN_FILE)
        print(f"[SUKCES] Nowy refresh token zapisano w {ALLEGRO_TOKEN_FILE}.")
    else:
        print(f"[BŁĄD] Wymiana kodu nie powiodła się [{res.status_code}]: {res.text}")
