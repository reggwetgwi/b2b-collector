"""
Groq-обогащение данных из SERP.

Бесплатная замена Gemini-обогащения. У Groq НЕТ веб-поиска, поэтому он работает
только с теми данными, что уже есть в выдаче (название + сниппет + сайт).
Безопасно извлекает «услуги» из текста сниппета. Рейтинги Яндекс/Zoon НЕ заполняет —
без веб-поиска модель их выдумает, поэтому они остаются за DaData/2ГИС/ручным вводом.

Интерфейс enrich_batch совместим с GeminiEnricher, поэтому collector_core_serp.py
менять не нужно.
"""

import time
from typing import List, Dict, Optional
import json
import re
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"


class GroqEnricher:
    """Обогащение данных через Groq (только из имеющихся сниппетов SERP)"""

    def __init__(self, api_keys: List[str]):
        self.keys = [k.strip() for k in api_keys if k.strip()]
        self.current_index = 0
        self.exhausted = set()

        if not self.keys:
            raise RuntimeError("Нет API ключей Groq для обогащения")

    def get_next_key(self) -> Optional[str]:
        """Получить следующий доступный ключ (round-robin)"""
        if len(self.exhausted) >= len(self.keys):
            return None

        attempts = 0
        while attempts < len(self.keys):
            key = self.keys[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.keys)

            if key not in self.exhausted:
                return key

            attempts += 1

        return None

    def mark_exhausted(self, key: str):
        """Пометить ключ как исчерпанный"""
        self.exhausted.add(key)

    def enrich_business(self, business: Dict, log_callback=None) -> Dict:
        """Извлечь услуги для одного бизнеса из его сниппета SERP"""

        name = business.get("name", "")
        snippet = business.get("snippet", "")

        # Если услуги уже есть или нет исходного текста — пропускаем
        if business.get("services") or not snippet:
            return business

        prompt = f"""Из текста ниже извлеки основные услуги компании "{name}".

ТЕКСТ:
{snippet}

ИНСТРУКЦИИ:
1. Перечисли услуги кратко, через запятую (например: "лечение кариеса, имплантация, протезирование")
2. Бери ТОЛЬКО то, что прямо упомянуто в тексте. НИЧЕГО не выдумывай.
3. Если услуг в тексте нет — верни пустую строку.

Верни ТОЛЬКО валидный JSON без markdown:
{{"services": "услуги через запятую или пустая строка"}}"""

        key = self.get_next_key()
        if not key:
            if log_callback:
                log_callback(f"⚠️ Groq: все ключи исчерпаны для {name}")
            return business

        max_retries = 2
        delay = 5

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(
                    GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": GROQ_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=30,
                )

                if response.status_code == 429:
                    self.mark_exhausted(key)
                    if log_callback:
                        log_callback(f"⚠️ Groq ключ исчерпан (429), переключаюсь...")
                    key = self.get_next_key()
                    if not key:
                        return business
                    continue

                if response.status_code == 401:
                    self.mark_exhausted(key)
                    if log_callback:
                        log_callback(f"⚠️ Groq: невалидный ключ для {name}")
                    return business

                response.raise_for_status()
                text = response.json()["choices"][0]["message"]["content"].strip()
                text = re.sub(r"```json|```", "", text).strip()
                start = text.find("{")
                end = text.rfind("}")
                if start == -1 or end == -1:
                    raise ValueError("JSON объект не найден в ответе")

                enriched = json.loads(text[start:end + 1])
                services = (enriched.get("services") or "").strip()
                if services:
                    business["services"] = services

                if log_callback:
                    log_callback(f"✓ Groq обогатил: {name}")
                return business

            except requests.exceptions.RequestException as e:
                if log_callback:
                    log_callback(f"⚠️ Groq сеть для {name} (попытка {attempt}/{max_retries}): {str(e)[:80]}")
                if attempt < max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 30)
                else:
                    return business
            except Exception as e:
                if log_callback:
                    log_callback(f"⚠️ Groq ошибка разбора для {name}: {str(e)[:80]}")
                return business

        return business

    def enrich_batch(self, businesses: List[Dict], log_callback=None) -> List[Dict]:
        """Обогатить батч бизнесов"""
        enriched = []

        for idx, business in enumerate(businesses, 1):
            if log_callback:
                log_callback(f"🔍 Groq обогащение {idx}/{len(businesses)}: {business.get('name', 'Unknown')}")

            enriched_business = self.enrich_business(business, log_callback=log_callback)
            enriched.append(enriched_business)

            # Пауза для соблюдения лимита 30 запросов/мин на free-tier
            if idx < len(businesses):
                time.sleep(2.1)

        return enriched
