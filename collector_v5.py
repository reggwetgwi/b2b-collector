"""
СБОРЩИК БАЗЫ БИЗНЕСОВ v5 — комплексный, легальный, под тысячи.

Источник данных РФ:
  • Яндекс-органика (XMLRiver) с ГЛУБОКОЙ выгрузкой: рубрика × районы × синонимы, пагинация
  • Сайт компании: бренд, телефоны, email, мессенджеры/соцсети, ИНН/ОГРН
      - статический фетч + Playwright (JS-футеры) + PDF-реквизиты + JSON-LD
  • DaData findById по ИНН/ОГРН (со сверкой города) → директор, юр.адрес, ОКВЭД
  • 2ГИС: рейтинг, отзывы, фактический адрес
  • Чекпойнт/resume, дедуп по домену и ИНН, источники/достоверность по полям

Запуск: python collector_v5.py
Ключи: dist/config_serp.json
"""

import os, re, json, time, html as _htmllib, warnings
import requests, openpyxl
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

warnings.filterwarnings("ignore")

# ─────────────────────────── НАСТРОЙКИ ПРОГОНА ───────────────────────────
BUSINESS = "стоматология"
CITY = "Москва"
LR = 213                              # регион Яндекса: Москва=213, СПб=2, Новосибирск=65, Казань=43
DADATA_KLADR = "7700000000000"
CITY_ADDR_GUARD = ["москва", "московск"]
# Нужен ГЛОБАЛЬНЫЙ ТОП по популярности (ранжирование Яндекса по головному запросу),
# от самых популярных вниз. Районы не используем — они ломают порядок популярности.
# Головной запрос идёт первым и задаёт ранг; синонимы лишь удлиняют хвост.
SYNONYMS = ["стоматология", "стоматологическая клиника", "стоматолог"]
TARGET = 350                          # верхняя граница уникальных бизнесов
MAX_PAGES = 20                        # глубина пагинации (Яндекс ~до 250 позиций)
PLAYWRIGHT_CAP = 220                  # макс. сайтов под JS-рендер (ограничение времени)

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

BLOCKED_DOMAINS = [
    "2gis.ru", "gis.ru", "mos.ru", "gosuslugi.ru", "6750000.ru", "sravni.ru", "32top.ru",
    "prodoctorov.ru", "napopravku.ru", "docdoc.ru", "sberhealth.ru", "topdent.ru",
    "zoon.ru", "yell.ru", "spr.ru", "blizko.ru", "orgpage.ru", "firmika.ru", "doctu.ru",
    "irecommend.ru", "otzovik.com", "flamp.ru", "otzyvru.com", "gidmed.com", "medbooking.com",
    "avito.ru", "youla.ru", "yandex.ru", "ya.ru", "google.com", "infodoctor.ru", "medportal.ru",
    "vk.com", "ok.ru", "t.me", "instagram.com", "facebook.com", "stom-firms.ru", "expomap.ru",
    "wikipedia.org", "rusprofile.ru", "list-org.com", "zachestnyibiznes.ru", "doktornarabote.ru",
    "dzen.ru", "vc.ru", "rbc.ru", "kp.ru", "youtube.com",
]
BLOCKED_PATH = ["/articles/", "/article/", "/blog/", "/news/", "/search", "/rating"]
SPAM_TITLE = re.compile(r"(\d+\s*(лучш|клиник|стоматолог)|рейтинг|лучши|топ[\s\-]?\d|подборк|"
                        r"обзор|сравнен|каталог|справочник|где\s+сделать|как\s+выбрать)", re.I)
OTHER_CITIES = ["омск", "новосибир", "екатеринбург", "казан", "самар", "челябин", "красноярск",
                "пермь", "ростов", "воронеж", "краснодар", "волгоград", "саратов", "тюмень",
                "сочи", "санкт-петер", "спб", "нижн", "уфа"]
ALLOWED_INN_REGIONS = {"77", "50"}

CKPT = f"v5_ckpt_{BUSINESS}_{CITY}.json"
OUT_XLSX = f"БАЗА_{BUSINESS}_{CITY}.xlsx"
LOGF = open(f"v5_log_{CITY}.txt", "w", encoding="utf-8")
def log(m=""):
    LOGF.write(str(m) + "\n"); LOGF.flush()


def load_keys():
    for p in ("dist/config_serp.json", "config_serp.json"):
        if os.path.exists(p):
            c = json.load(open(p, encoding="utf-8"))
            xr = (c.get("xmlriver_keys") or "").strip().splitlines()[0]
            u, k = xr.split(":", 1)
            f = lambda n: ((c.get(n) or "").strip().splitlines() or [""])[0]
            return u.strip(), k.strip(), f("dadata_keys"), f("serper_keys"), f("twogis_keys")
    raise RuntimeError("config_serp.json не найден")
XR_USER, XR_KEY, DADATA_KEY, SERPER_KEY, TWOGIS_KEY = load_keys()


# ─────────────────────────── УТИЛИТЫ ───────────────────────────
def domain_of(url):
    try:
        return urlparse(url).netloc.replace("www.", "").lower()
    except Exception:
        return ""

def inn_checksum_ok(inn):
    if not inn or not inn.isdigit():
        return False
    d = [int(x) for x in inn]
    if len(inn) == 10:
        c = [2, 4, 10, 3, 5, 9, 4, 6, 8]
        return (sum(c[i]*d[i] for i in range(9)) % 11) % 10 == d[9]
    if len(inn) == 12:
        c1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        c2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]
        return ((sum(c1[i]*d[i] for i in range(10)) % 11) % 10 == d[10] and
                (sum(c2[i]*d[i] for i in range(11)) % 11) % 10 == d[11])
    return False

def ogrn_ok(ogrn):
    if not ogrn or not ogrn.isdigit() or len(ogrn) not in (13, 15):
        return False
    if len(ogrn) == 13:
        return int(ogrn[:12]) % 11 % 10 == int(ogrn[12])
    return int(ogrn[:14]) % 13 % 10 == int(ogrn[14])

def _no_scripts(raw):
    raw = re.sub(r"<script\b[^>]*>.*?</script>", " ", raw, flags=re.S | re.I)
    raw = re.sub(r"<style\b[^>]*>.*?</style>", " ", raw, flags=re.S | re.I)
    return raw

def strip_tags(raw):
    t = _htmllib.unescape(re.sub(r"<[^>]+>", " ", _no_scripts(raw))).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t)

def find_inns(raw):
    text = strip_tags(raw)
    out = []
    for m in re.finditer(r"ИНН[^0-9]{0,6}([0-9][0-9 ]{8,16}[0-9])", text, re.I):
        d = re.sub(r"\D", "", m.group(1))
        if len(d) in (10, 12) and inn_checksum_ok(d):
            out.append(d)
    return out

def find_ogrns(raw):
    text = strip_tags(raw)
    out = []
    for m in re.finditer(r"ОГРН[ИП]?[^0-9]{0,6}([0-9][0-9 ]{11,18}[0-9])", text, re.I):
        d = re.sub(r"\D", "", m.group(1))
        if ogrn_ok(d):
            out.append(d)
    return out

GOOD_TLD = {"ru", "com", "su", "net", "org", "moscow", "online", "info", "pro",
            "bio", "me", "clinic", "dental", "site", "store", "shop", "rus"}

def find_emails(raw):
    raw = _no_scripts(raw)  # без JS/CSS — иначе ловятся куски кода
    emails = set(re.findall(r"mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", raw, re.I))
    text = strip_tags(raw)
    emails |= set(re.findall(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,8}\b", text))
    # деобфускация ТОЛЬКО с явными скобками/словами (без голой точки и «at» внутри слов)
    for m in re.finditer(r"([A-Za-z0-9._%+\-]+)\s*[\[(]\s*(?:at|собака)\s*[\])]\s*"
                         r"([A-Za-z0-9.\-]+)\s*[\[(]\s*(?:dot|точка)\s*[\])]\s*([A-Za-z]{2,8})", text, re.I):
        emails.add(f"{m.group(1)}@{m.group(2)}.{m.group(3)}")
    bad = ("example.", "sentry", "wixpress", "@2x", ".png", ".jpg", ".gif", "domain.",
           "@sentry", "your@", "mail@mail", "@example")
    out = []
    for e in emails:
        e = e.lower().strip(".")
        if any(b in e for b in bad):
            continue
        if e.rsplit(".", 1)[-1] not in GOOD_TLD:  # отсекает .js/.random/.href/.index/...
            continue
        out.append(e)
    return sorted(set(out))

def find_socials(raw):
    s = set()
    for m in re.findall(r'https?://(?:wa\.me|api\.whatsapp\.com)/[^\s"\'<>]+', raw):
        s.add(m.split("&")[0])
    for m in re.findall(r'https?://t\.me/[^\s"\'<>]+', raw): s.add(m)
    for m in re.findall(r'https?://(?:vk\.com|vk\.ru)/[^\s"\'<>]+', raw): s.add(m.split("?")[0])
    return list(s)[:4]

def find_phones(raw):
    text = strip_tags(raw)
    phones = []
    for m in re.findall(r"\+7[\s\-\(\)]*\d{3}[\s\-\(\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}", text):
        p = re.sub(r"[^\d+]", "", m)
        if p not in phones:
            phones.append(p)
    return phones[:5]

def jsonld_legal(raw):
    """Из JSON-LD достать legalName и ИНН (taxID/vatID)."""
    name = inn = ""
    for blk in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', raw, re.S | re.I):
        try:
            data = json.loads(blk.strip())
        except Exception:
            for m in re.findall(r'"(?:taxID|vatID|inn)"\s*:\s*"?(\d{10}|\d{12})', blk):
                if inn_checksum_ok(m): inn = m
            continue
        for obj in (data if isinstance(data, list) else [data]):
            if not isinstance(obj, dict): continue
            for k in ("taxID", "vatID", "inn"):
                v = re.sub(r"\D", "", str(obj.get(k, "")))
                if inn_checksum_ok(v): inn = v
            if not name:
                name = obj.get("legalName") or obj.get("name") or ""
    return name, inn


# ─────────────────────────── 1. DISCOVERY (Яндекс) ───────────────────────────
def yandex_page(query, page):
    url = (f"https://xmlriver.com/search_yandex/xml?user={XR_USER}&key={XR_KEY}"
           f"&query={requests.utils.quote(query)}&groupby=10&lr={LR}&domain=ru&page={page}")
    for _ in range(3):
        try:
            r = requests.get(url, timeout=60)
            if 'code="15"' in r.text or 'code="200"' in r.text:
                return []
            root = ET.fromstring(r.content)
            out = []
            for idx, g in enumerate(root.findall(".//group")):
                doc = g.find(".//doc")
                if doc is None: continue
                u = doc.find(".//url"); t = doc.find(".//title")
                out.append({"url": u.text.strip() if u is not None and u.text else "",
                            "title": "".join(t.itertext()).strip() if t is not None else "",
                            "position": page*10 + idx + 1})
            return out
        except (requests.exceptions.RequestException, ET.ParseError):
            time.sleep(6)
    return []

def blocked(url, domain, title):
    low = url.lower()
    if any(domain == b or domain.endswith("." + b) for b in BLOCKED_DOMAINS): return True
    if any(m in low for m in BLOCKED_PATH): return True
    tl = (title or "").lower()
    if SPAM_TITLE.search(tl): return True
    if CITY.lower() not in tl and any(c in tl for c in OTHER_CITIES): return True
    return False

def discover():
    seen = {}
    queries = 0
    # Головной запрос первым — он задаёт ранг популярности; синонимы добирают хвост.
    seeds = [f"{syn} {CITY}" for syn in SYNONYMS]
    log(f"=== DISCOVERY: топ по популярности, {len(seeds)} запросов, до {MAX_PAGES} стр. ===")
    rank = 0
    for si, seed in enumerate(seeds):
        if len(seen) >= TARGET: break
        empty_streak = 0
        for page in range(MAX_PAGES):
            docs = yandex_page(seed, page); queries += 1
            if not docs:
                break
            new = 0
            for d in docs:
                dom = domain_of(d["url"])
                if not dom or dom in seen or blocked(d["url"], dom, d["title"]): continue
                rank += 1
                seen[dom] = {"domain": dom, "url": d["url"], "yandex_pos": d["position"],
                             "rank": rank, "title": d["title"], "seed": seed}
                new += 1
            # на головном запросе идём вглубь до конца; на синонимах рано выходим, если нет новизны
            empty_streak = empty_streak + 1 if new == 0 else 0
            if empty_streak >= (3 if si == 0 else 1):
                break
            if len(seen) >= TARGET: break
            time.sleep(0.2)
        log(f"  «{seed}» → всего уникальных: {len(seen)}")
    log(f"Запросов к Яндексу: {queries} (~{queries*0.025:.2f}₽), уникальных: {len(seen)}")
    return list(seen.values())


# ─────────────────────────── 2. ENRICH: сайт ───────────────────────────
PAGE_CACHE = {}
LEGAL_PATHS = ["/contacts", "/kontakty", "/policy", "/privacy", "/politika-konfidencialnosti",
               "/politika", "/rekvizity", "/personalnye-dannye", "/about", "/o-klinike"]
LEGAL_HINT = re.compile(r"(polit|privacy|konfiden|personal|persdata|rekvizit|soglas|policy|/about|/o-)", re.I)

def get_html(url):
    if url in PAGE_CACHE: return PAGE_CACHE[url]
    try:
        r = requests.get(url, headers=UA, timeout=12, verify=False)
        out = None
        if r.status_code < 400:
            r.encoding = r.apparent_encoding or r.encoding
            out = r.text
    except requests.exceptions.RequestException:
        out = None
    PAGE_CACHE[url] = out
    return out

def get_pdf_inns(url):
    try:
        import pypdf, io
        r = requests.get(url, headers=UA, timeout=15, verify=False)
        if r.status_code >= 400: return [], []
        reader = pypdf.PdfReader(io.BytesIO(r.content))
        text = " ".join((pg.extract_text() or "") for pg in reader.pages[:6])
        return find_inns(text), find_ogrns(text)
    except Exception:
        return [], []

def brand_from(raw):
    for pat in (r'<meta[^>]+og:site_name[^>]+content=["\']([^"\']+)',
                r'<meta[^>]+name=["\']application-name["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(pat, raw, re.I)
        if m and len(m.group(1).strip()) > 1: return m.group(1).strip()
    nm, _ = jsonld_legal(raw)
    if nm and len(nm) > 1 and len(nm) < 70: return nm.strip()
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
    if m:
        t = re.sub(r"\s+", " ", m.group(1)).strip()
        for sep in [" — ", " - ", " | ", ": ", " – "]:
            if sep in t: return t.split(sep)[0].strip()
        return t[:60]
    return ""

def pick_inn(inns):
    pref = [i for i in inns if i[:2] in ALLOWED_INN_REGIONS]
    return (pref or inns)[0] if inns else ""

def enrich_site(b):
    dom = b["domain"]
    b.update({"site_brand": "", "phones": [], "emails": [], "socials": [], "inn": "", "ogrn": ""})
    base = home = None
    for sch in ("https://", "http://"):
        home = get_html(f"{sch}{dom}/")
        if home is not None: base = f"{sch}{dom}"; break
    if home is None:
        return b
    b["site_brand"] = brand_from(home)
    inns, ogrns = list(find_inns(home)), list(find_ogrns(home))
    _, jinn = jsonld_legal(home)
    if jinn: inns.append(jinn)
    b["phones"] = find_phones(home); b["emails"] = find_emails(home); b["socials"] = find_socials(home)

    # легальные страницы (по ссылкам с главной + типовые слаги), включая PDF
    legal = []
    for href in re.findall(r'href=["\']([^"\']+)["\']', home):
        if LEGAL_HINT.search(href): legal.append(urljoin(base + "/", href))
    legal += [base + p for p in LEGAL_PATHS]
    seen = set()
    for url in legal:
        if inns and b["emails"] and b["phones"]: break
        if url in seen: continue
        seen.add(url)
        if url.lower().endswith(".pdf"):
            pi, po = get_pdf_inns(url); inns += pi; ogrns += po; continue
        h = get_html(url)
        if not h: continue
        inns += find_inns(h); ogrns += find_ogrns(h)
        if not b["emails"]: b["emails"] = find_emails(h)
        if not b["phones"]: b["phones"] = find_phones(h)
        if not b["socials"]: b["socials"] = find_socials(h)
    b["inn"] = pick_inn(inns); b["ogrn"] = (ogrns or [""])[0]
    return b


# ─────────────────── 2b. Playwright — JS-футеры для остатка ───────────────────
def playwright_pass(businesses):
    todo = [b for b in businesses if not b.get("inn") and not b.get("ogrn")][:PLAYWRIGHT_CAP]
    if not todo:
        return
    log(f"=== Playwright (JS-рендер) для {len(todo)} сайтов без ИНН ===")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        log(f"  Playwright недоступен: {e}"); return
    done = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for b in todo:
            for sch in ("https://", "http://"):
                try:
                    page = browser.new_page(user_agent=UA["User-Agent"])
                    page.goto(f"{sch}{b['domain']}/", timeout=15000, wait_until="domcontentloaded")
                    page.wait_for_timeout(1500)
                    html = page.content()
                    page.close()
                except Exception:
                    try: page.close()
                    except Exception: pass
                    continue
                inns, ogrns = find_inns(html), find_ogrns(html)
                if not b["emails"]: b["emails"] = find_emails(html)
                if not b["site_brand"]: b["site_brand"] = brand_from(html)
                if inns or ogrns:
                    b["inn"] = pick_inn(inns); b["ogrn"] = (ogrns or [""])[0]; done += 1
                break
        browser.close()
    log(f"  Playwright добыл ИНН/ОГРН ещё для {done} сайтов")


# ─────────────────────────── 3. DaData + 2ГИС ───────────────────────────
def dadata_find(id_):
    try:
        r = requests.post("https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party",
                          headers={"Authorization": f"Token {DADATA_KEY}"}, json={"query": id_}, timeout=15)
        s = r.json().get("suggestions", [])
        if s:
            d = s[0]["data"]
            return {"name": s[0]["value"], "director": (d.get("management") or {}).get("name", ""),
                    "address": (d.get("address") or {}).get("value", ""),
                    "status": (d.get("state") or {}).get("status", ""),
                    "okved": d.get("okved", ""), "inn": d.get("inn", ""), "ogrn": d.get("ogrn", "")}
    except requests.exceptions.RequestException:
        pass
    return None

def dadata_suggest(name):
    try:
        r = requests.post("https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/party",
                          headers={"Authorization": f"Token {DADATA_KEY}"},
                          json={"query": name, "count": 5, "status": ["ACTIVE"],
                                "locations": [{"kladr_id": DADATA_KLADR}]}, timeout=15)
        return r.json().get("suggestions", [])
    except requests.exceptions.RequestException:
        return []

_STOP = {"медицина","медицинский","медицинская","стоматология","стоматологическая","стоматологический",
         "клиника","клиник","клиники","центр","дентал","дент","стом","смайл","smile","dental","clinic",
         "ооо","ао","зао","фгбу","гауз","фирма","группа","групп","сеть","москва","москве"}
def _tok(s):
    s = re.sub(r'[«»"\'`.,;:!?/\\\-]', " ", (s or "").lower())
    return {w for w in re.findall(r"[a-zа-я0-9]{3,}", s) if w not in _STOP}
def name_ok(brand, title, domain, egrul):
    from transliterate import transliterate_to_russian
    et = _tok(egrul)
    if not et: return False
    if (_tok(brand) | _tok(title)) & et: return True
    root = domain.split(".")[0].lower(); root_ru = transliterate_to_russian(root).lower()
    return any(root in t or root_ru in t or t in root_ru for t in et if len(t) >= 3)

def city_ok(addr):
    return any(g in (addr or "").lower() for g in CITY_ADDR_GUARD)

def resolve_egrul(b):
    d = None; src = ""
    for ident in (b.get("inn"), b.get("ogrn")):
        if ident:
            cand = dadata_find(ident)
            if cand and city_ok(cand["address"]):
                d = cand; src = "ИНН/ОГРН с сайта"; break
            elif cand and not d:
                d = None  # чужой город — не берём
    if not d:
        for s in dadata_suggest(b.get("site_brand") or b.get("title", "")):
            dd = s["data"]
            if city_ok((dd.get("address") or {}).get("value", "")) and \
               name_ok(b.get("site_brand", ""), b.get("title", ""), b["domain"], s["value"]):
                d = {"name": s["value"], "director": (dd.get("management") or {}).get("name", ""),
                     "address": (dd.get("address") or {}).get("value", ""),
                     "status": (dd.get("state") or {}).get("status", ""),
                     "okved": dd.get("okved", ""), "inn": dd.get("inn", ""), "ogrn": dd.get("ogrn", "")}
                src = "по названию"; break
    if d:
        b["egrul_name"] = d["name"]; b["director"] = d["director"]; b["reg_address"] = d["address"]
        b["status"] = d["status"]; b["okved"] = d["okved"]
        b["inn"] = b.get("inn") or d["inn"]; b["ogrn"] = b.get("ogrn") or d["ogrn"]
        b["src_inn"] = src
    else:
        for k in ("egrul_name", "director", "reg_address", "status", "okved"): b[k] = b.get(k, "")
        b["src_inn"] = "не найдено в ЕГРЮЛ"
    return b

def twogis_pass(businesses):
    if not TWOGIS_KEY:
        return
    try:
        from twogis_enricher import TwoGISEnricher
        en = TwoGISEnricher([TWOGIS_KEY])
    except Exception as e:
        log(f"2ГИС недоступен: {e}"); return
    log(f"=== 2ГИС рейтинги для {len(businesses)} ===")
    def one(b):
        name = b.get("egrul_name") or b.get("site_brand") or b.get("title", "")
        name = re.sub(r'^(ООО|АО|ЗАО|ПАО)\s+', "", name).strip(' "«»')
        pd = en.search_place(name, CITY)
        if pd:
            b["twogis_rating"] = pd.get("rating", ""); b["twogis_reviews"] = pd.get("reviews_count", "")
            b["twogis_address"] = pd.get("address", "")
            if not b.get("phones") and pd.get("phones"): b["phones"] = pd["phones"]
        return b
    with ThreadPoolExecutor(max_workers=6) as ex:
        list(as_completed([ex.submit(one, b) for b in businesses]))


# ─────────────────────────── checkpoint ───────────────────────────
def save_ckpt(businesses, phase):
    json.dump({"phase": phase, "business": BUSINESS, "city": CITY, "data": businesses},
              open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
def load_ckpt():
    if os.path.exists(CKPT):
        try:
            c = json.load(open(CKPT, encoding="utf-8"))
            if c.get("business") == BUSINESS and c.get("city") == CITY:
                return c
        except Exception:
            pass
    return None


# ─────────────────────────── Excel ───────────────────────────
def save_xlsx(businesses):
    # дедуп по ИНН
    inn_count = {}
    for b in businesses:
        if b.get("inn"): inn_count[b["inn"]] = inn_count.get(b["inn"], 0) + 1

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Бизнесы"
    headers = ["№", "Бренд", "Название ЕГРЮЛ", "Юр.адрес (ЕГРЮЛ)", "Адрес 2ГИС", "Телефоны",
               "Email", "Мессенджеры", "ИНН", "ОГРН", "Директор", "ОКВЭД",
               "Яндекс↑", "Google↑", "Рейтинг 2ГИС", "Отзывы 2ГИС", "Сайт",
               "Источник ИНН", "Статус ЮЛ", "Дубль ИНН"]
    widths = [5,26,34,42,40,26,28,24,14,16,28,10,8,8,11,11,26,16,12,9]
    hf = Font(bold=True, color="FFFFFF"); hfill = PatternFill("solid", start_color="1F4E79")
    for c, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(1, c, h); cell.font = hf; cell.fill = hfill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.row_dimensions[1].height = 30

    for i, b in enumerate(sorted(businesses, key=lambda x: x.get("rank", 9999)), 1):
        dup = "ДА" if b.get("inn") and inn_count.get(b["inn"], 0) > 1 else ""
        row = [i, b.get("site_brand",""), b.get("egrul_name",""), b.get("reg_address",""),
               b.get("twogis_address",""), ", ".join(b.get("phones",[])),
               ", ".join(b.get("emails",[])[:3]), ", ".join(b.get("socials",[])),
               b.get("inn",""), b.get("ogrn",""), b.get("director",""), str(b.get("okved","")),
               b.get("yandex_pos",""), b.get("google_pos",""), b.get("twogis_rating",""),
               b.get("twogis_reviews",""), "https://"+b["domain"], b.get("src_inn",""),
               b.get("status",""), dup]
        ws.append(row)
        c = ws.cell(i+1, 17)
        c.hyperlink = row[16]; c.font = Font(color="1F4E79", underline="single")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(businesses)+1}"

    # лист статистики
    st = wb.create_sheet("Статистика")
    tot = len(businesses)
    def share(pred): return sum(1 for b in businesses if pred(b))
    rows = [
        ("Всего бизнесов", tot),
        ("С сайтом и позицией Яндекса", tot),
        ("С телефоном", share(lambda b: b.get("phones"))),
        ("С email", share(lambda b: b.get("emails"))),
        ("С мессенджером/соцсетью", share(lambda b: b.get("socials"))),
        ("С ИНН", share(lambda b: b.get("inn"))),
        ("С директором (ЕГРЮЛ)", share(lambda b: b.get("director"))),
        ("  из них ИНН/ОГРН с сайта", share(lambda b: b.get("src_inn")=="ИНН/ОГРН с сайта")),
        ("  из них по названию", share(lambda b: b.get("src_inn")=="по названию")),
        ("С рейтингом 2ГИС", share(lambda b: b.get("twogis_rating"))),
        ("Уникальных ИНН", len(inn_count)),
    ]
    for r, (k, v) in enumerate(rows, 1):
        st.cell(r, 1, k); st.cell(r, 2, v)
        pct = f"{100*v//tot}%" if isinstance(v, int) and tot and "ИНН" not in k[:5] and k != "Всего бизнесов" else ""
        st.cell(r, 3, pct)
    st.column_dimensions["A"].width = 34; st.column_dimensions["B"].width = 10
    wb.save(OUT_XLSX)
    log(f"\n💾 Сохранено: {OUT_XLSX}")
    return rows


# ─────────────────────────── MAIN ───────────────────────────
def main():
    ck = load_ckpt()
    if ck and ck.get("phase") == "enriched":
        businesses = ck["data"]; log("Возобновляю с чекпойнта (enriched)")
    else:
        if ck and ck.get("phase") == "discovered":
            businesses = ck["data"]; log("Возобновляю с чекпойнта (discovered)")
        else:
            businesses = discover(); save_ckpt(businesses, "discovered")

        log(f"=== ENRICH сайтов: {len(businesses)} ===")
        with ThreadPoolExecutor(max_workers=12) as ex:
            list(as_completed([ex.submit(enrich_site, b) for b in businesses]))
        playwright_pass(businesses)
        save_ckpt(businesses, "enriched")

    # Google-позиции (по головному запросу)
    try:
        gp = {}
        r = requests.post("https://google.serper.dev/search",
                          headers={"X-API-Key": SERPER_KEY, "Content-Type": "application/json"},
                          json={"q": f"{BUSINESS} {CITY}", "gl": "ru", "hl": "ru", "num": 100}, timeout=30)
        for i, o in enumerate(r.json().get("organic", []), 1): gp[domain_of(o.get("link",""))] = i
        for b in businesses: b["google_pos"] = gp.get(b["domain"], "")
    except requests.exceptions.RequestException:
        pass

    log(f"=== DaData ({len(businesses)}) ===")
    for i, b in enumerate(businesses, 1):
        resolve_egrul(b); time.sleep(0.1)
        if i % 40 == 0: log(f"  DaData {i}/{len(businesses)}"); save_ckpt(businesses, "enriched")

    twogis_pass(businesses)
    save_ckpt(businesses, "enriched")

    stats = save_xlsx(businesses)
    log("\n" + "=" * 50 + "\nИТОГ:")
    for k, v in stats: log(f"  {k}: {v}")


if __name__ == "__main__":
    main()
    LOGF.close()
