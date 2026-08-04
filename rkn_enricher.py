"""
РКН — реестр операторов ПД (pd.rkn.gov.ru), легальный публичный источник.
rkn_lookup(inn) → {phone, email, resp_name, regn} | None
Покрытие ~80% по Москве (ИНН клиник). 2 запроса на ИНН, таймаут 25с.
"""
import re, requests, warnings
warnings.filterwarnings("ignore")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
BASE = "https://pd.rkn.gov.ru/operators-registry/operators-list/"

def _get(url):
    try:
        r = requests.get(url, headers=UA, timeout=25, verify=False)
        return r.text if r.status_code == 200 else ""
    except requests.exceptions.RequestException:
        return ""

def rkn_lookup(inn):
    s = _get(f"{BASE}?act=search&name_full=&inn={inn}&regn=")
    if not s: return None
    m = re.search(r'id=([0-9\-]{8,})', s)
    if not m: return None
    regn = m.group(1)
    d = _get(f"{BASE}?id={regn}")
    if not d: return {"regn": regn, "resp_name": "", "phone": "", "email": ""}
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", d))
    # имя ответственного
    i = plain.find("ответственных за организацию")
    name = ""
    if i > 0:
        nm = plain[i+40:i+200]
        m2 = re.match(r"\s*([А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+ [А-ЯЁ][а-яё]+)", nm)
        if m2: name = m2.group(1)
    # контакты
    j = plain.find("адреса электронной почты")
    contacts = plain[j:j+300] if j > 0 else ""
    em = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", contacts)
    # Телефон: СТРОГИЙ паттерн, чтобы не слепить с соседним индексом/адресом.
    # Форматы РКН: 8(499)147-67-94, +7 (495) 150-55-04, 89255293121, 8 499 147 67 94
    phone = ""
    pats = [
        # 1) с кодом страны 8/+7: 8(499)147-67-94, +7 (495) 150-55-04, 89255293121
        (r"(?:\+7|8)\s*\(?\d{3,4}\)?\s*\d{3}[\-\s]?\d{2}[\-\s]?\d{2}", 11),
        (r"(?:\+7|8)\d{10}", 11),
        # 2) БЕЗ кода страны, с кодом города: (495) 675-11-11, 495 675-11-11
        #    строго: 3 цифры кода + 3 + 2 + 2 = 10 цифр (индекс 6 цифр НЕ подойдёт под структуру)
        (r"\(?\d{3}\)?\s*\d{3}[\-\s]\d{2}[\-\s]\d{2}", 10),
    ]
    for pat, ln in pats:
        m = re.search(pat, contacts)
        if m:
            dg = re.sub(r"\D", "", m.group(0))
            if ln == 11 and len(dg) == 11 and dg[0] in "78":
                phone = "+7" + dg[1:]
            elif ln == 10 and len(dg) == 10:
                phone = "+7" + dg           # городской без 8 → +7 + 10 цифр
            if phone:
                break
    return {"regn": regn, "resp_name": name, "phone": phone,
            "email": em.group(0).lower() if em else ""}

def enrich_batch(businesses, log_callback=None):
    """Обогатить список бизнесов (поля inn, rkn_phone, rkn_email, rkn_name).
    Только для тех, у кого ещё нет телефона. С паузой 1.2с между запросами."""
    import time
    enriched = 0
    for i, b in enumerate(businesses, 1):
        inn = b.get("inn")
        if not inn or b.get("rkn_phone"): continue
        r = rkn_lookup(inn)
        if r:
            if r.get("phone"): b["rkn_phone"] = r["phone"]; enriched += 1
            if r.get("email"): b["rkn_email"] = r["email"]
            if r.get("resp_name"): b["rkn_name"] = r["resp_name"]
        time.sleep(1.2)
        if log_callback and i % 50 == 0:
            log_callback(f"  РКН: {i}/{len(businesses)}, телефонов: {enriched}")
    if log_callback: log_callback(f"РКН: +{enriched} телефонов")
    return businesses
