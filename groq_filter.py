"""
Groq-фильтр для интеллектуальной очистки результатов SERP.

Бесплатная замена Gemini-фильтра. Использует OpenAI-совместимый эндпоинт Groq
(https://console.groq.com). Модель llama-3.1-8b-instant — самая щедрая на free-tier
(~14400 запросов/день). Интерфейс filter_serp_results совместим с GeminiFilter,
поэтому collector_core_serp.py менять не нужно.
"""

import time
from typing import List, Dict, Optional
import json
import re
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"


class GroqFilter:
    """Интеллектуальный фильтр SERP результатов через Groq"""

    def __init__(self, api_keys: List[str]):
        self.keys = [k.strip() for k in api_keys if k.strip()]
        self.current_index = 0
        self.exhausted = set()

        if not self.keys:
            raise RuntimeError("Нет API ключей Groq для фильтрации")

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

    def filter_serp_results(self, results: List[Dict], business_type: str, city: str, log_callback=None) -> List[Dict]:
        """Фильтровать и очистить результаты SERP через Groq"""

        if not results:
            return []

        # Формируем список результатов для промпта
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
                log_callback(f"⚠️ Groq фильтр: все ключи исчерпаны, пропускаем фильтрацию")
            return results

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
                        log_callback(f"⚠️ КРИТИЧНО: Groq ключ исчерпан (429), фильтрация пропущена!")
                    return results

                if response.status_code == 401:
                    self.mark_exhausted(key)
                    if log_callback:
                        log_callback(f"⚠️ Groq: невалидный ключ, фильтрация пропущена")
                    return results

                response.raise_for_status()
                text = response.json()["choices"][0]["message"]["content"].strip()

                filtered_data = self._parse_json_array(text)

                # Применяем фильтр к оригинальным результатам
                filtered_results = []
                for item in filtered_data:
                    if not item.get("is_real_business", False):
                        continue

                    position = item.get("position", 0) - 1
                    if 0 <= position < len(results):
                        original = results[position].copy()
                        # Заменяем название на очищенное
                        original["title"] = item.get("name", original["title"])
                        filtered_results.append(original)

                if log_callback:
                    log_callback(f"✓ Groq отфильтровал: {len(results)} → {len(filtered_results)} компаний")

                return filtered_results

            except requests.exceptions.RequestException as e:
                if log_callback:
                    log_callback(f"⚠️ Groq фильтр сеть (попытка {attempt}/{max_retries}): {str(e)[:100]}")
                if attempt < max_retries:
                    time.sleep(delay)
                    delay = min(delay * 2, 30)
                else:
                    if log_callback:
                        log_callback(f"⚠️ КРИТИЧНО: Groq фильтрация недоступна, возвращаю нефильтрованные данные!")
                    return results
            except Exception as e:
                if log_callback:
                    log_callback(f"⚠️ КРИТИЧНО: Groq фильтр не разобрал ответ: {str(e)[:100]}")
                return results

        return results

    @staticmethod
    def _parse_json_array(text: str) -> List[Dict]:
        """
        Достать JSON-массив из ответа модели.
        response_format=json_object иногда оборачивает массив в объект
        вида {"results": [...]} — обрабатываем оба случая.
        """
        text = re.sub(r"```json|```", "", text).strip()

        # Прямой массив
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            return json.loads(text[start:end + 1])

        # Объект-обёртка — берём первый встретившийся список внутри
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
        for value in obj.values():
            if isinstance(value, list):
                return value
        raise ValueError("JSON массив не найден в ответе")
