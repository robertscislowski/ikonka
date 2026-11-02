import io
import os
import requests
import xml.etree.ElementTree as ET
from config import XML_URL, REQUEST_TIMEOUT, log

def download_xml_stream(session: requests.Session):
    if XML_URL.startswith("http://") or XML_URL.startswith("https://"):
        resp = session.get(XML_URL, stream=True, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        content = resp.content.lstrip()
        if content.startswith(b'\xef\xbb\xbf'):
            content = content[3:].lstrip()
        return io.BytesIO(content)
    else:
        if not os.path.isfile(XML_URL):
            raise FileNotFoundError(f"Nie znaleziono pliku XML: {XML_URL}")
        with open(XML_URL, "rb") as f:
            content = f.read().lstrip()
            if content.startswith(b'\xef\xbb\xbf'):
                content = content[3:].lstrip()
        return io.BytesIO(content)

def parse_full_product(elem) -> dict:
    kod_kreskowy = (elem.findtext("kod_kreskowy") or "").strip()
    kod = (elem.findtext("kod") or kod_kreskowy).strip()
    nazwa = (elem.findtext("nazwa") or "").strip()

    sug_cena_det = elem.findtext("sugerowana_cena_detaliczna")
    cena_zakupu_raw = elem.findtext("cena")
    stan_raw = elem.findtext("stan")
    vat_raw = elem.findtext("vat")

    try:
        sug_cena_det_float = float(sug_cena_det) if sug_cena_det else 0.0
        vat_rate = (float(vat_raw) / 100) if vat_raw else 0.23
        cena_brutto = round(sug_cena_det_float * (1 + vat_rate), 2)

        cena_zakupu_netto = float(cena_zakupu_raw) if cena_zakupu_raw else 0.0
        cena_zakupu_brutto = round(cena_zakupu_netto * (1 + vat_rate), 2)

        ilosc = int(float(stan_raw)) if stan_raw else 0
        vat_int = int(float(vat_raw)) if vat_raw else 23
    except ValueError:
        return None

    zdjecia = []
    zdjecia_node = elem.find("zdjecia")
    if zdjecia_node is not None:
        for z in zdjecia_node.findall("zdjecie"):
            if z.text:
                zdjecia.append(z.text.strip())

    return {
        "kod": kod,
        "kod_kreskowy": kod_kreskowy,
        "nazwa": nazwa,
        "cena_brutto": cena_brutto,
        "cena_zakupu_netto": cena_zakupu_netto,
        "cena_zakupu_brutto": cena_zakupu_brutto,
        "stan": ilosc,
        "vat": vat_int,
        "opis": (elem.findtext("opis") or "").strip(),
        "opis_krotki": (elem.findtext("opis_krotki") or "").strip(),
        "waga": float(elem.findtext("waga") or 0.0),
        "producer_id": (elem.findtext("producer_id") or "").strip(),
        "zdjecia": zdjecia,
    }

def stream_products(xml_stream):
    context = ET.iterparse(xml_stream, events=("end",))
    for _event, elem in context:
        if elem.tag == "produkt":
            parsed = parse_full_product(elem)
            if parsed:
                yield parsed
            elem.clear()