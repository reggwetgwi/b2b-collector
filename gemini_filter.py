"""
Gemini-фильтр для интеллектуальной очистки результатов SERP
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


class GeminiFilter:
    """Интеллектуальный фильтр SERP результатов через Gemini"""

    def __init__(self, api_keys: List[str]):
        self.keys = [k.strip() for k in api_keys if k.strip()]
        self.current_index = 0
        self.exhausted = set()

        if not self.keys:
            raise RuntimeError("Нет API ключей Gemini для фильтрации")

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

    def filter_serp_results(self, results: List[Dict], business_type: str, city: str, log_callback=None) -> List[Dict]:
        """Фильтровать и очистить результаты SERP через Gemini"""

        if not results:
            return []

        # Формируем промпт для Gemini
        results_text = ""
        for idx, r in enumerate(results, 1):
            results_text += f"{idx}. Название: {r.get('title', '')}\n"
            results_text += f"   URL: {r.get('link', '')}\n\n"

        prompt = f"""Проанализируй результаты поиска "{business_type}" в городе {city}.

Твоя задача: отфильтровать ТОЛЬКО реальные компании, убрать агрегаторы и каталоги.

РЕЗУЛЬТАТЫ:
{results_text}

ИНСТРУКЦИИ:
1. УБЕРИ агрегаторы и каталоги: ПроДокторов, 2ГИС (страницы поиска), Zoon, ДокДок, рейтинги, "лучшие", отзывы
2. ОСТАВЬ только реальные компании с собственными сайтами
3. ИЗВЛЕКИ чистое название компании (убери город, "официальный сайт", лишний текст)
4. Если непонятно — лучше оставь, чем убери

Верни ТОЛЬКО валидный JSON массив без markdown:
[
  {{"position": 1, "name": "Чистое название", "is_real_business": true}},
  {{"position": 2, "name": "Чистое название", "is_real_business": true}}
]

Только JSON, без пояснений."""

        key = self.get_next_key()
        if not key:
            if log_callback:
                log_callback(f"⚠️ Gemini фильтр: все ключи исчерпаны, пропускаем фильтрацию")
            return results

        max_retries = 2
        delay = 10

        for attempt in range(1, max_retries + 1):
            try:
                client = genai.Client(api_key=key)
                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                    ),
                )

                # Парсим JSON из ответа
                text = response.text.strip()
                text = re.sub(r"```json|```", "", text).strip()
                start = text.find("[")
                end = text.rfind("]")

                if start == -1 or end == -1:
                    raise ValueError("JSON массив не найден в ответе")

                filtered_data = json.loads(text[start:end + 1])

                # Применяем фильтр к оригинальным результатам
                filtered_results = []
                for item in filtered_data:
                    if not item.get("is_real_business", False):
                        continue

                    position = item.get("position", 0) - 1
                    if 0 <= position < len(results):
                        original = results[position].copy()
                        # Заменяем название на очищенное от Gemini
                        original["title"] = item.get("name", original["title"])
                        filtered_results.append(original)

                if log_callback:
                    log_callback(f"✓ Gemini отфильтровал: {len(results)} → {len(filtered_results)} компаний")

                return filtered_results

            except Exception as e:
                err_str = str(e).lower()

                if log_callback:
                    log_callback(f"⚠️ Gemini фильтр ошибка (попытка {attempt}/{max_retries}): {str(e)[:100]}")

                is_quota = any(x in err_str for x in ["429", "quota_exceeded", "resource_exhausted", "limit exceeded", "too many requests"])
                is_overload = any(x in err_str for x in ["503", "high demand", "unavailable", "overloaded"])

                if is_quota:
                    self.mark_exhausted(key)
                    if log_callback:
                        log_callback(f"⚠️ КРИТИЧНО: Gemini ключ исчерпан, фильтрация пропущена!")
                    return results
                elif is_overload and attempt < max_retries:
                    if log_callback:
                        log_callback(f"⚠️ Gemini перегружен, жду {delay}с...")
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                else:
                    # Если ошибка — возвращаем оригинальные результаты
                    if log_callback:
                        log_callback(f"⚠️ КРИТИЧНО: Gemini фильтрация провалилась, возвращаем нефильтрованные данные!")
                    return results

        # Если все попытки провалились — возвращаем оригинал
        if log_callback:
            log_callback(f"⚠️ КРИТИЧНО: Gemini фильтр не смог обработать результаты после {max_retries} попыток!")
        return results
