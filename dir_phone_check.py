"""
Анализ последнего столбца — личных мобильных директоров.
Что проверяем (бесплатно, без подтверждения владельца):
  1) отличается ли мобильный директора от телефона организации;
  2) появляется ли он на сайте клиники (=публичный, переклеенный) или нет (=непубличный).
"""

import re
import warnings
import requests
import openpyxl
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings("ignore")
SRC = "Стоматология тест.xlsx"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
PATHS = ["", "/contacts", "/kontakty", "/about"]


def last10(v):
    d = re.sub(r"\D", "", str(v or ""))
    return d[-10:] if len(d) >= 10 else ""


def site_digits(domain):
    for scheme in ("https://", "http://"):
        reached = False
        acc = ""
        for path in PATHS:
            try:
                r = requests.get(f"{scheme}{domain}{path}", headers=UA, timeout=12, verify=False)
                if r.status_code >= 400:
                    continue
                reached = True
                acc += re.sub(r"\D", "", r.text)
            except requests.exceptions.RequestException:
                continue
        if reached:
            return acc
    return None


def check(row):
    org, name, domain, _, _, dirph = row[:6]
    org10, dir10 = last10(org), last10(dirph)
    domain = str(domain or "").strip().strip("/")
    distinct = (dir10 and dir10 != org10)
    digits = site_digits(domain) if domain else None
    if digits is None:
        on_site = "сайт недоступен"
    elif not dir10:
        on_site = "нет номера"
    else:
        on_site = "на сайте" if dir10 in digits else "НЕ на сайте"
    return (name, dir10, "отличается" if distinct else "= тел.орг", on_site)


def main():
    rows = list(openpyxl.load_workbook(SRC).active.iter_rows(min_row=2, values_only=True))
    res = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for f in as_completed([ex.submit(check, r) for r in rows]):
            res.append(f.result())

    distinct = sum(1 for r in res if r[2] == "отличается")
    on_site = sum(1 for r in res if r[3] == "на сайте")
    not_on = sum(1 for r in res if r[3] == "НЕ на сайте")
    down = sum(1 for r in res if r[3] == "сайт недоступен")

    with open("dir_phone_report.txt", "w", encoding="utf-8") as o:
        o.write(f"Анализ личных мобильных директоров ({len(res)} строк)\n" + "=" * 60 + "\n")
        for name, ph, dist, site in sorted(res, key=lambda x: x[3]):
            o.write(f"  [{site:<16}] [{dist:<11}] {name:<26} +7{ph}\n")
        o.write("\n" + "=" * 60 + "\n")
        o.write(f"  мобильный отличается от тел. организации: {distinct}/{len(res)}\n")
        o.write(f"  есть на сайте клиники (публичный):        {on_site}\n")
        o.write(f"  НЕ на сайте (непубличный источник):       {not_on}\n")
        o.write(f"  сайт недоступен:                          {down}\n")


if __name__ == "__main__":
    main()
