"""
ФИНАЛ: реестр МСП (100% ИНН) + DaData (директор/адрес) + веб-слой v5 (сайт/тел/email/рейтинг).

Вход:
  msp_dental_msk.json        — все 11872 записи с ОКВЭД 86.23 (Москва/МО)
  v5_ckpt_*.json (опц.)       — веб-слой: сайт/телефоны/email/2ГИС/позиция по ИНН и названию

Особенности:
  • чекпойнт enrich_ckpt.json — при упоре в лимит DaData (10к/сутки) продолжает завтра
  • ИП: директор=ФИО из реестра (DaData не тратим)
  • ЮЛ: DaData findById по ИНН → директор, адрес, статус
  • джойн с вебом по ИНН (точно), иначе по нормализованному названию
Выход: БАЗА_РЕЕСТР_стоматология_Москва.xlsx
"""
import os, re, json, time, requests, openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

SRC = "msp_dental_msk.json"
CKPT = "enrich_ckpt.json"
OUT = "БАЗА_РЕЕСТР_стоматология_Москва.xlsx"

def load_keys():
    for p in ("dist/config_serp.json", "config_serp.json"):
        if os.path.exists(p):
            c = json.load(open(p, encoding="utf-8"))
            return ((c.get("dadata_keys") or "").strip().splitlines() or [""])[0]
    return ""
DADATA_KEY = load_keys()

def norm(s):
    s = (s or "").lower()
    s = re.sub(r'(ооо|оао|зао|пао|ао|общество с ограниченной ответственностью|'
               r'индивидуальный предприниматель|ип)\b', " ", s)
    s = re.sub(r'[«»"\'`.,\-]', " ", s)
    return re.sub(r"\s+", " ", s).strip()

# ─── веб-слой из v5: индекс по ИНН и по нормализованному названию ───
def load_web():
    by_inn, by_name = {}, {}
    for f in os.listdir("."):
        if f.startswith("v5_ckpt_") and f.endswith(".json"):
            try:
                data = json.load(open(f, encoding="utf-8")).get("data", [])
            except Exception:
                continue
            for b in data:
                rec = {"domain": b.get("domain", ""), "phones": b.get("phones", []),
                       "emails": b.get("emails", []), "socials": b.get("socials", []),
                       "twogis_rating": b.get("twogis_rating", ""), "twogis_reviews": b.get("twogis_reviews", ""),
                       "yandex_pos": b.get("yandex_pos", ""), "rank": b.get("rank", ""),
                       "brand": b.get("site_brand", "")}
                if b.get("inn"):
                    by_inn[b["inn"]] = rec
                nm = norm(b.get("egrul_name") or b.get("site_brand") or b.get("title", ""))
                if nm:
                    by_name.setdefault(nm, rec)
    return by_inn, by_name
WEB_INN, WEB_NAME = load_web()

def dadata(inn):
    try:
        r = requests.post("https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party",
                          headers={"Authorization": f"Token {DADATA_KEY}"}, json={"query": inn}, timeout=15)
        if r.status_code in (403, 429):
            return "LIMIT"
        s = r.json().get("suggestions", [])
        if s:
            d = s[0]["data"]
            return {"director": (d.get("management") or {}).get("name", ""),
                    "address": (d.get("address") or {}).get("value", ""),
                    "status": (d.get("state") or {}).get("status", ""),
                    "name": s[0]["value"]}
    except requests.exceptions.RequestException:
        return None
    return None

def main():
    records = json.load(open(SRC, encoding="utf-8"))
    done = {}
    if os.path.exists(CKPT):
        done = json.load(open(CKPT, encoding="utf-8"))
    print(f"Всего записей: {len(records)}, уже обработано: {len(done)}", flush=True)

    limit_hit = False
    processed = 0
    for i, r in enumerate(records, 1):
        inn = r["inn"]
        if inn in done:
            continue
        enr = {"director": r["fio"] if r["is_ip"] else "", "address": "", "status": "", "egrul_name": r["name"]}
        if not r["is_ip"] and DADATA_KEY and not limit_hit:
            res = dadata(inn)
            if res == "LIMIT":
                limit_hit = True
                print(f"Лимит DaData достигнут на {i}/{len(records)}. Сохраняю чекпойнт.", flush=True)
            elif res:
                enr.update({"director": res["director"], "address": res["address"],
                            "status": res["status"], "egrul_name": res["name"] or r["name"]})
            time.sleep(0.05)
        done[inn] = enr
        processed += 1
        if processed % 200 == 0:
            json.dump(done, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  {i}/{len(records)} (обработано в этой сессии: {processed})", flush=True)
        if limit_hit and r["is_ip"] is False:
            # при лимите ЮЛ оставляем без директора, но продолжаем (ИП всё равно заполняем)
            pass
    json.dump(done, open(CKPT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"Сессия завершена. Обработано всего: {len(done)}/{len(records)}", flush=True)

    build_xlsx(records, done)

def build_xlsx(records, done):
    rows = []
    for r in records:
        inn = r["inn"]
        e = done.get(inn, {})
        web = WEB_INN.get(inn) or WEB_NAME.get(norm(r["name"])) or {}
        rows.append({
            "inn": inn, "is_ip": r["is_ip"],
            "name": e.get("egrul_name") or r["name"] or r["fio"],
            "director": e.get("director", ""),
            "reg_address": e.get("address", ""),
            "status": e.get("status", ""),
            "region": r["region"],
            "domain": web.get("domain", ""),
            "phones": ", ".join(web.get("phones", [])),
            "emails": ", ".join(web.get("emails", [])[:3]),
            "socials": ", ".join(web.get("socials", [])),
            "twogis_rating": web.get("twogis_rating", ""),
            "yandex_pos": web.get("yandex_pos", ""),
            "rank": web.get("rank", 99999) or 99999,
            "okveds": ", ".join(r["okveds"][:6]),
        })
    # популярные (с веб-присутствием) — сверху по рангу, остальные ниже
    rows.sort(key=lambda x: (x["rank"], x["name"]))

    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Стоматологии"
    H = ["№", "ИНН", "Тип", "Название", "Директор/ИП", "Юр.адрес", "Статус ЮЛ", "Регион",
         "Сайт", "Телефоны", "Email", "Мессенджеры", "Рейтинг 2ГИС", "Яндекс↑", "ОКВЭД"]
    W = [5, 14, 6, 40, 30, 44, 12, 7, 24, 24, 26, 22, 11, 8, 30]
    hf = Font(bold=True, color="FFFFFF"); hfill = PatternFill("solid", start_color="1F4E79")
    for c, (h, w) in enumerate(zip(H, W), 1):
        cell = ws.cell(1, c, h); cell.font = hf; cell.fill = hfill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(c)].width = w
    for i, r in enumerate(rows, 1):
        ws.append([i, r["inn"], "ИП" if r["is_ip"] else "ЮЛ", r["name"], r["director"],
                   r["reg_address"], r["status"], r["region"], "https://"+r["domain"] if r["domain"] else "",
                   r["phones"], r["emails"], r["socials"], r["twogis_rating"],
                   r["yandex_pos"] if r["yandex_pos"] else "", r["okveds"]])
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(H))}{len(rows)+1}"

    st = wb.create_sheet("Статистика")
    tot = len(rows)
    with_dir = sum(1 for r in rows if r["director"])
    with_site = sum(1 for r in rows if r["domain"])
    with_phone = sum(1 for r in rows if r["phones"])
    with_email = sum(1 for r in rows if r["emails"])
    for ri, (k, v) in enumerate([
        ("Всего стоматологий (реестр)", tot),
        ("ИНН (по построению)", f"{tot} (100%)"),
        ("С директором/ИП", f"{with_dir} ({100*with_dir//tot}%)"),
        ("С сайтом (веб-слой)", f"{with_site} ({100*with_site//tot}%)"),
        ("С телефоном", f"{with_phone} ({100*with_phone//tot}%)"),
        ("С email", f"{with_email} ({100*with_email//tot}%)"),
        ("ЮЛ / ИП", f"{sum(1 for r in rows if not r['is_ip'])} / {sum(1 for r in rows if r['is_ip'])}"),
    ], 1):
        st.cell(ri, 1, k); st.cell(ri, 2, v)
    st.column_dimensions["A"].width = 32; st.column_dimensions["B"].width = 16
    wb.save(OUT)
    print(f"СОХРАНЕНО: {OUT}  ({len(rows)} строк)", flush=True)
    print(f"  директоров: {with_dir}, сайтов: {with_site}, телефонов: {with_phone}", flush=True)

if __name__ == "__main__":
    main()
