"""
DaData API обогащение данных
"""

import time
from typing import List, Dict, Optional
import requests
from transliterate import generate_name_variants
from name_matcher import find_best_match, combined_similarity


class DaDataEnricher:
    """Обогащение данных через DaData API"""

    def __init__(self, api_keys: List[str]):
        self.keys = [k.strip() for k in api_keys if k.strip()]
        self.current_index = 0
        self.exhausted = set()

        if not self.keys:
            raise RuntimeError("Нет API ключей DaData для обогащения")

        self.base_url = "https://suggestions.dadata.ru/suggestions/api/4_1/rs"

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

    def find_company(self, name: str, city: str, domain: str = "", log_callback=None) -> Optional[Dict]:
        """Найти компанию через DaData API"""
        key = self.get_next_key()
        if not key:
            if log_callback:
                log_callback(f"⚠️ DaData: все ключи исчерпаны")
            return None

        # Генерируем варианты названия (оригинал + транслитерация)
        name_variants = generate_name_variants(name)

        for variant_idx, variant in enumerate(name_variants):
            try:
                # Формируем запрос
                request_body = {
                    "query": variant,
                    "count": 10,  # Увеличили до 10 для лучшего выбора
                    "status": ["ACTIVE"]  # Только активные компании
                }

                # Добавляем фильтр по городу если есть КЛАДР
                kladr = self._get_city_kladr(city)
                if kladr:
                    request_body["locations"] = [{"kladr_id": kladr}]

                if log_callback:
                    log_callback(f"🔍 DaData запрос вариант {variant_idx + 1}/{len(name_variants)}: '{variant}' (город: {city})")

                # Ищем по названию через suggest/party
                response = requests.post(
                    f"{self.base_url}/suggest/party",
                    headers={
                        "Authorization": f"Token {key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                    timeout=10
                )

                if log_callback:
                    log_callback(f"📡 DaData ответ: status={response.status_code}")

                if response.status_code == 403:
                    self.mark_exhausted(key)
                    if log_callback:
                        log_callback(f"⚠️ DaData: ключ исчерпан или невалидный")
                    return None

                if response.status_code != 200:
                    if log_callback:
                        log_callback(f"⚠️ DaData: неожиданный код {response.status_code}")
                    continue  # Пробуем следующий вариант

                data = response.json()
                suggestions = data.get("suggestions", [])

                if log_callback:
                    log_callback(f"📊 DaData вернул {len(suggestions)} компаний")

                if not suggestions:
                    continue

                # Преобразуем suggestions в формат для find_best_match
                candidates = []
                for sugg in suggestions:
                    candidates.append({
                        'name': sugg.get("value", ""),
                        'data': sugg.get("data", {})
                    })

                # Используем улучшенный алгоритм поиска
                best_match, best_score, details = find_best_match(
                    variant,
                    candidates,
                    name_field='name',
                    threshold=0.45  # Снизили порог до 45%
                )

                if best_match:
                    if log_callback:
                        log_callback(f"✓ DaData нашёл совпадение: '{best_match['name']}' (score: {best_score:.2f}, детали: {details})")

                    company_data = best_match.get('data', {})
                    return self._extract_company_data(company_data)
                else:
                    if log_callback and suggestions:
                        # Покажем лучших кандидатов для отладки
                        top_names = [s.get("value", "")[:50] for s in suggestions[:3]]
                        log_callback(f"⚠️ DaData: нет совпадений выше порога. Топ кандидаты: {top_names}")

            except requests.exceptions.RequestException as e:
                if log_callback:
                    log_callback(f"⚠️ DaData ошибка: {str(e)[:100]}")

                if "403" in str(e):
                    self.mark_exhausted(key)
                    return None

        return None

    def _extract_company_data(self, company_data: Dict) -> Dict:
        """Извлечь нужные поля из данных DaData"""
        result = {
            "inn": company_data.get("inn", ""),
            "address": company_data.get("address", {}).get("value", ""),
            "director_name": company_data.get("management", {}).get("name", "") if company_data.get("management") else "",
            "phone": company_data.get("phones", [{}])[0].get("data", {}).get("value", "") if company_data.get("phones") else "",
            "ogrn": company_data.get("ogrn", ""),
            "status": company_data.get("state", {}).get("status", ""),
        }
        return result

    def _get_city_kladr(self, city: str) -> str:
        """Получить КЛАДР код города (упрощённая версия)"""
        # Основные города (можно расширить)
        city_map = {
            "москва": "7700000000000",
            "санкт-петербург": "7800000000000",
            "новосибирск": "5400000100000",
            "екатеринбург": "6600000100000",
            "казань": "1600000100000",
            "нижний новгород": "5200000100000",
            "красноярск": "2400000100000",
            "челябинск": "7400000100000",
            "самара": "6300000100000",
            "уфа": "0200000100000",
        }
        return city_map.get(city.lower(), "")

    def enrich_business(self, business: Dict, log_callback=None) -> Dict:
        """Обогатить данные одного бизнеса через DaData"""

        name = business.get("name", "")
        city = business.get("city", "")
        domain = business.get("domain", "")

        if not name:
            return business

        company_data = self.find_company(name, city, domain, log_callback=log_callback)

        if company_data:
            # Обновляем только пустые поля
            if not business.get("inn"):
                business["inn"] = company_data.get("inn", "")
            if not business.get("address"):
                business["address"] = company_data.get("address", "")
            if not business.get("director_phone") and company_data.get("phone"):
                business["director_phone"] = company_data.get("phone", "")

            # Имя директора — в отдельное поле (НЕ в услуги!)
            if company_data.get("director_name") and not business.get("director_name"):
                business["director_name"] = company_data.get("director_name", "")

            if log_callback:
                log_callback(f"✓ DaData обогатил: {name}")
        else:
            if log_callback:
                log_callback(f"⚠️ DaData не нашёл: {name}")

        return business

    def enrich_batch(self, businesses: List[Dict], log_callback=None) -> List[Dict]:
        """Обогатить батч бизнесов"""
        enriched = []

        for idx, business in enumerate(businesses, 1):
            if log_callback:
                log_callback(f"🔍 DaData обогащение {idx}/{len(businesses)}: {business.get('name', 'Unknown')}")

            enriched_business = self.enrich_business(business, log_callback=log_callback)
            enriched.append(enriched_business)

            # Пауза между запросами (DaData рекомендует не более 20 RPS)
            if idx < len(businesses):
                time.sleep(0.1)

        return enriched
