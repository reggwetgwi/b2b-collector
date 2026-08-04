"""Скачивание архива реестра МСП ФНС (2.1 ГБ) с резюме и прогрессом."""
import os, requests

URL = "https://file.nalog.ru/opendata/7707329152-rsmp/data-10052026-structure-10062025.zip"
DST = "msp.zip"

pos = os.path.getsize(DST) if os.path.exists(DST) else 0
headers = {"Range": f"bytes={pos}-"} if pos else {}
with requests.get(URL, headers=headers, stream=True, timeout=60) as r:
    total = int(r.headers.get("Content-Length", 0)) + pos
    mode = "ab" if pos else "wb"
    done = pos
    nextmark = pos + 100*1024*1024
    with open(DST, mode) as f:
        for chunk in r.iter_content(chunk_size=1024*1024):
            f.write(chunk); done += len(chunk)
            if done >= nextmark:
                print(f"{done/1024/1024:.0f} MB / {total/1024/1024:.0f} MB ({100*done//total}%)", flush=True)
                nextmark += 100*1024*1024
print(f"ГОТОВО: {os.path.getsize(DST)/1024/1024:.0f} MB", flush=True)
