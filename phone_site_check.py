"""
Сверка телефонов организаций (из файла подрядчика) с их живыми сайтами.
Если номер найден на сайте клиники — он настоящий и актуальный.
"""

import re
import warnings
import requests
import openpyxl
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")  # глушим SSL warnings

SRC = "Стоматология тест.xlsx"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
CONTACT_PATHS = ["", "/contacts", "/kontakty", "/contact", "/about"]


def last10(v):
    d = re.sub(r"\D", "", str(v or ""))
    return d[-10:] if len(d) >= 10 else ""


def fetch_digits(url):
    try:
        r = requests.get(url, headers=UA, timeout=12, verify=False, allow_redirects=True)
        if r.status_code >= 400:
            return None
        return re.sub(r"\D", "", r.text)
    except requests.exceptions.RequestException:
        return None


def check_row(row):
    org_phone, name, domain = row[0], row[1], row[2]
    phone = last10(org_phone)
    domain = str(domain or "").strip().strip("/")
    if not domain or not phone:
        return (name, domain, phone, "нет данных")

    reached = False
    for scheme in ("https://", "http://"):
        for path in CONTACT_PATHS:
            digits = fetch_digits(f"{scheme}{domain}{path}")
            if digits is None:
                continue
            reached = True
            if phone in digits:
                return (name, domain, phone, "НАЙДЕН")
        if reached:
            break  # сайт открылся, страницы проверены — второй scheme не нужен

    return (name, domain, phone, "не найден" if reached else "сайт недоступен")


def main():
    wb = openpyxl.load_workbook(SRC)
    rows = list(wb.active.iter_rows(min_row=2, values_only=True))

    results = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(check_row, r): r for r in rows}
        for f in as_completed(futs):
            results.append(f.result())

    found = sum(1 for r in results if r[3] == "НАЙДЕН")
    notfound = sum(1 for r in results if r[3] == "не найден")
    down = sum(1 for r in results if r[3] == "сайт недоступен")

    with open("phone_site_report.txt", "w", encoding="utf-8") as out:
        out.write(f"Сверка телефонов организаций с сайтами ({len(results)} строк)\n")
        out.write("=" * 64 + "\n")
        for name, domain, phone, status in sorted(results, key=lambda x: x[3]):
            out.write(f"  [{status:<16}] {name:<26} {domain:<28} +7{phone}\n")
        out.write("\n" + "=" * 64 + "\n")
        out.write(f"  телефон найден на сайте:  {found}\n")
        out.write(f"  не найден на сайте:       {notfound}\n")
        out.write(f"  сайт недоступен:          {down}\n")
        reachable = found + notfound
        if reachable:
            out.write(f"  совпадение среди доступных сайтов: {100*found//reachable}%\n")


if __name__ == "__main__":
    main()
