"""
Стрим-парсер архива реестра МСП (msp.zip) → фильтр стоматологий Москвы/МО.
Фильтр: ОКВЭД (осн. или доп.) начинается на 86.23, регион ∈ {77, 50}.
Результат: msp_dental_msk.json  [{inn, name, region, okveds, category, is_ip, fio}]
"""
import zipfile, json, sys
import xml.etree.ElementTree as ET

SRC = "msp.zip"
OUT = "msp_dental_msk.json"
OKVED_PREFIX = "86.23"          # стоматологическая практика
REGIONS = {"77", "50"}         # Москва + Московская обл

def ln(tag):
    return tag.split("}")[-1]

def process(doc):
    flat = {}
    okveds = set()
    fam = im = otch = ""
    is_ip = False
    for n in doc.iter():
        name = ln(n.tag)
        if name in ("ОргВклМСП",):
            pass
        if name == "ИПВклМСП":
            is_ip = True
        if name == "Фамилия": fam = (n.text or n.attrib.get("Фамилия", "") or fam)
        if name == "Имя": im = (n.text or n.attrib.get("Имя", "") or im)
        if name == "Отчество": otch = (n.text or n.attrib.get("Отчество", "") or otch)
        # ОКВЭД (и атрибут КодОКВЭД, и возможный элемент)
        if name in ("СвОКВЭДОсн", "СвОКВЭДДоп"):
            c = n.attrib.get("КодОКВЭД")
            if c: okveds.add(c)
        if name == "КодОКВЭД" and n.text:
            okveds.add(n.text.strip())
        # плоский словарь: тег→текст и атрибуты
        if n.text and n.text.strip():
            flat.setdefault(name, n.text.strip())
        for k, v in n.attrib.items():
            flat.setdefault(ln(k), v)
        # ФИО ИП как атрибуты ФИОИП
        if name == "ФИОИП":
            fam = fam or n.attrib.get("Фамилия", "")
            im = im or n.attrib.get("Имя", "")
            otch = otch or n.attrib.get("Отчество", "")

    inn = flat.get("ИННЮЛ") or flat.get("ИННФЛ") or ""
    name = flat.get("НаимОрг") or flat.get("НаимОргСокр") or ""
    region = flat.get("КодРегион") or ""
    cat = flat.get("КатСубМСП") or flat.get("ВидСубМСП") or ""
    fio = " ".join(x for x in (fam, im, otch) if x) if is_ip else ""
    return {"inn": inn, "name": name, "region": region, "okveds": sorted(okveds),
            "category": cat, "is_ip": is_ip, "fio": fio}

def keep(rec):
    return (rec["inn"] and rec["region"] in REGIONS
            and any(o.startswith(OKVED_PREFIX) for o in rec["okveds"]))

def main():
    out = []
    seen = set()
    with zipfile.ZipFile(SRC) as z:
        xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
        print(f"XML-файлов в архиве: {len(xmls)}", flush=True)
        for i, fn in enumerate(xmls, 1):
            try:
                with z.open(fn) as f:
                    for ev, elem in ET.iterparse(f, events=("end",)):
                        if ln(elem.tag) == "Документ":
                            rec = process(elem)
                            if keep(rec) and rec["inn"] not in seen:
                                seen.add(rec["inn"]); out.append(rec)
                            elem.clear()
            except ET.ParseError:
                continue
            if i % 500 == 0:
                print(f"  {i}/{len(xmls)} файлов, найдено стоматологий: {len(out)}", flush=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"ГОТОВО: стоматологий 86.23 в Москве/МО = {len(out)}  → {OUT}", flush=True)

if __name__ == "__main__":
    main()
