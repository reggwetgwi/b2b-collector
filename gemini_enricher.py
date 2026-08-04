"""
Gemini обогащение данных из SERP
"""

import time
from typing import List, Dict, Optional
import json
import re

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("Устанавливаю google-genai...")
    import os
    os.system("pip install google-genai")
    from google import genai
    from google.genai import types


class GeminiEnricher:
    """Обогащение данных через Gemini API"""

    def __init__(self, api_keys: List[str]):
        self.keys = [k.strip() for k in api_keys if k.strip()]
        self.current_index = 0
        self.exhausted = set()

        if not self.keys:
            raise RuntimeError("Нет API ключей Gemini для обогащения")

    def get_next_key(self) -> Optional[str]:
        """Получить следующий доступный ключ"""
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
        """Обогатить данные одного бизнеса через Gemini"""

        name = business.get("name", "")
        city = business.get("city", "")
        website = business.get("website", "")

        if not name or not city:
            return business

        prompt = f"""Найди дополнительную информацию о бизнесе "{name}" в городе {city}, Россия.
Сайт (если известен): {website}

Используй Google Search для поиска:
1. Полный адрес (улица, дом)
2. ИНН организации
3. Телефон директора (личный, не общий). Если личного нет, укажи общий с пометкой "(общий)" или "нет в открытом доступе"
4. Рейтинг на Яндекс.Картах (0-5)
5. Рейтинг на 2ГИС (0-5)
6. Рейтинг на Zoon.ru (0-10)
7. Основные услуги (через запятую, кратко)

Верни ТОЛЬКО валидный JSON объект, без markdown, без пояснений:
{{
  "address": "полный адрес или пустая строка",
  "inn": "ИНН или пустая строка",
  "director_phone": "телефон директора, общий с пометкой (общий), или нет в открытом доступе",
  "yandex_rating": "рейтинг 0-5 или пустая строка",
  "twogis_rating": "рейтинг 0-5 или пустая строка",
  "zoon_rating": "рейтинг 0-10 или пустая строка",
  "services": "услуги через запятую или пустая строка"
}}"""

        max_retries = 3
        delay = 10

        for attempt in range(1, max_retries + 1):
            key = self.get_next_key()
            if not key:
                if log_callback:
                    log_callback(f"⚠️ Gemini: все ключи исчерпаны для {name}")
                return business

            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.1,
                    ),
                )

                # Парсим JSON из ответа
                text = response.text.strip()
                text = re.sub(r"```json|```", "", text).strip()
                start = text.find("{")
                end = text.rfind("}")

                if start == -1 or end == -1:
                    raise ValueError("JSON объект не найден в ответе")

                enriched_data = json.loads(text[start:end + 1])

                # Обновляем только пустые поля
                if not business.get("address"):
                    business["address"] = enriched_data.get("address", "")
                if not business.get("inn"):
                    business["inn"] = enriched_data.get("inn", "")
                if not business.get("director_phone"):
                    business["director_phone"] = enriched_data.get("director_phone", "")
                if not business.get("yandex_rating"):
                    business["yandex_rating"] = enriched_data.get("yandex_rating", "")
                if not business.get("twogis_rating"):
                    business["twogis_rating"] = enriched_data.get("twogis_rating", "")
                if not business.get("zoon_rating"):
                    business["zoon_rating"] = enriched_data.get("zoon_rating", "")
                if not business.get("services"):
                    business["services"] = enriched_data.get("services", "")

                if log_callback:
                    log_callback(f"✓ Gemini обогатил: {name}")

                return business

            except Exception as e:
                err_str = str(e).lower()

                if log_callback:
                    log_callback(f"⚠️ Gemini ошибка для {name}: {str(e)[:100]}")

                is_quota = any(x in err_str for x in ["429", "quota_exceeded", "resource_exhausted", "limit exceeded", "too many requests"])
                is_overload = any(x in err_str for x in ["503", "high demand", "unavailable", "overloaded"])

                if is_quota:
                    self.mark_exhausted(key)
                    if log_callback:
                        log_callback(f"⚠️ Gemini ключ исчерпан, переключаюсь...")
                    continue
                elif is_overload and attempt < max_retries:
                    if log_callback:
                        log_callback(f"⚠️ Gemini перегружен, жду {delay}с...")
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                else:
                    break

        return business

    def enrich_batch(self, businesses: List[Dict], log_callback=None) -> List[Dict]:
        """Обогатить батч бизнесов"""
        enriched = []

        for idx, business in enumerate(businesses, 1):
            if log_callback:
                log_callback(f"🔍 Gemini обогащение {idx}/{len(businesses)}: {business.get('name', 'Unknown')}")

            enriched_business = self.enrich_business(business, log_callback=log_callback)
            enriched.append(enriched_business)

            # Пауза между запросами
            if idx < len(businesses):
                time.sleep(3)

        return enriched
