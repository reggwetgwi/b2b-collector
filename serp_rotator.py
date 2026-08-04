"""
Ротатор SERP-сервисов для парсинга позиций в Google и Яндекс
"""

import requests
import time
from typing import List, Dict, Optional


class SERPService:
    """Базовый класс для SERP-сервиса"""
    def __init__(self, name: str, keys: List[str]):
        self.name = name
        self.keys = [k.strip() for k in keys if k.strip()]
        self.current_index = 0
        self.exhausted = set()

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

    def search(self, query: str) -> Dict:
        """Выполнить поиск (переопределяется в подклассах)"""
        raise NotImplementedError


class SerperService(SERPService):
    """Serper.dev для Google"""
    def __init__(self, keys: List[str]):
        super().__init__("Serper.dev", keys)

    def search(self, query: str) -> Dict:
        key = self.get_next_key()
        if not key:
            raise RuntimeError(f"{self.name}: все ключи исчерпаны")

        try:
            response = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-Key": key, "Content-Type": "application/json"},
                json={"q": query, "gl": "ru", "hl": "ru", "location": "Russia"},
                timeout=30
            )

            if response.status_code == 429:
                self.mark_exhausted(key)
                raise RuntimeError(f"{self.name}: ключ исчерпан (429)")

            response.raise_for_status()
            data = response.json()

            results = []
            for idx, result in enumerate(data.get("organic", []), 1):
                results.append({
                    "position": idx,
                    "title": result.get("title", ""),
                    "link": result.get("link", ""),
                    "snippet": result.get("snippet", ""),
                })

            return {"service": self.name, "engine": "google", "results": results}

        except requests.exceptions.RequestException as e:
            if "429" in str(e):
                self.mark_exhausted(key)
            raise RuntimeError(f"{self.name}: ошибка запроса - {e}")


class ValueSERPService(SERPService):
    """ValueSERP для Google"""
    def __init__(self, keys: List[str]):
        super().__init__("ValueSERP", keys)

    def search(self, query: str) -> Dict:
        key = self.get_next_key()
        if not key:
            raise RuntimeError(f"{self.name}: все ключи исчерпаны")

        try:
            response = requests.get(
                "https://api.valueserp.com/search",
                params={"api_key": key, "q": query, "num": 100, "location": "Russia", "gl": "ru", "hl": "ru"},
                timeout=30
            )

            if response.status_code == 429:
                self.mark_exhausted(key)
                raise RuntimeError(f"{self.name}: ключ исчерпан (429)")

            response.raise_for_status()
            data = response.json()

            results = []
            for idx, result in enumerate(data.get("organic_results", []), 1):
                results.append({
                    "position": idx,
                    "title": result.get("title", ""),
                    "link": result.get("link", ""),
                    "snippet": result.get("snippet", ""),
                })

            return {"service": self.name, "engine": "google", "results": results}

        except requests.exceptions.RequestException as e:
            if "429" in str(e):
                self.mark_exhausted(key)
            raise RuntimeError(f"{self.name}: ошибка запроса - {e}")


class SerpApiService(SERPService):
    """SerpApi для Google"""
    def __init__(self, keys: List[str]):
        super().__init__("SerpApi", keys)

    def search(self, query: str) -> Dict:
        key = self.get_next_key()
        if not key:
            raise RuntimeError(f"{self.name}: все ключи исчерпаны")

        try:
            response = requests.get(
                "https://serpapi.com/search",
                params={"api_key": key, "q": query, "engine": "google", "num": 100, "gl": "ru"},
                timeout=30
            )

            if response.status_code == 429:
                self.mark_exhausted(key)
                raise RuntimeError(f"{self.name}: ключ исчерпан (429)")

            response.raise_for_status()
            data = response.json()

            results = []
            for idx, result in enumerate(data.get("organic_results", []), 1):
                results.append({
                    "position": idx,
                    "title": result.get("title", ""),
                    "link": result.get("link", ""),
                    "snippet": result.get("snippet", ""),
                })

            return {"service": self.name, "engine": "google", "results": results}

        except requests.exceptions.RequestException as e:
            if "429" in str(e):
                self.mark_exhausted(key)
            raise RuntimeError(f"{self.name}: ошибка запроса - {e}")


class XMLRiverService(SERPService):
    """XMLRiver для Яндекс"""
    def __init__(self, keys: List[str]):
        super().__init__("XMLRiver", keys)
        self.users = []
        for key in self.keys:
            if ":" in key:
                user, api_key = key.split(":", 1)
                self.users.append({"user": user.strip(), "key": api_key.strip()})

    def search(self, query: str, limit: int = 10, lr: int = None) -> Dict:
        if not self.users:
            raise RuntimeError(f"{self.name}: нет валидных ключей (формат user:key)")

        key_str = self.get_next_key()
        if not key_str:
            raise RuntimeError(f"{self.name}: все ключи исчерпаны")

        user_data = None
        for u in self.users:
            if f"{u['user']}:{u['key']}" == key_str:
                user_data = u
                break

        if not user_data:
            raise RuntimeError(f"{self.name}: не найден user для ключа")

        import xml.etree.ElementTree as ET

        # Яндекс отдаёт максимум 10 результатов на страницу.
        # Чтобы собрать больше — листаем страницы page=0,1,2,... (нумерация с нуля).
        limit = max(1, int(limit or 10))
        pages_needed = (limit + 9) // 10

        results = []
        for page in range(pages_needed):
            page_results = self._fetch_page(user_data, key_str, query, page, lr, ET)
            if not page_results:
                break  # пустая страница — дальше выдачи нет
            results.extend(page_results)
            if len(results) >= limit:
                break

        return {"service": self.name, "engine": "yandex", "results": results[:limit]}

    def _fetch_page(self, user_data, key_str, query, page, lr, ET):
        """Запросить одну страницу Яндекс-выдачи (до 10 позиций) с ретраями.

        Возвращает список результатов. Бросает RuntimeError при неустранимой ошибке.
        Ошибки 111 (нет каналов) и 5xx считаются временными — пауза и повтор.
        """
        params = {
            "user": user_data["user"],
            "key": user_data["key"],
            "query": query,
            "groupby": "10",       # для Яндекса groupby — число (10 на странице)
            "domain": "ru",
            "lang": "ru",
            "device": "desktop",
            "page": str(page),
        }
        if lr is not None:
            params["lr"] = str(lr)

        last_err = None
        # До 4 попыток с нарастающей паузой (backoff).
        for attempt in range(4):
            try:
                response = requests.get(
                    "https://xmlriver.com/search_yandex/xml",
                    params=params,
                    timeout=60,
                )

                if response.status_code == 429:
                    self.mark_exhausted(key_str)
                    raise RuntimeError(f"{self.name}: ключ исчерпан (429)")

                if response.status_code >= 500:
                    last_err = f"HTTP {response.status_code}"
                    time.sleep(3 * (2 ** attempt))
                    continue

                response.raise_for_status()

                try:
                    root = ET.fromstring(response.content)
                except ET.ParseError as parse_err:
                    last_err = f"невалидный XML - {parse_err}. Превью: {response.text[:300]}"
                    time.sleep(3 * (2 ** attempt))
                    continue

                # КЛЮЧЕВОЕ: ошибки приходят с HTTP 200 в теле XML:
                #   <response><error code="...">текст</error></response>
                error_elem = root.find(".//error")
                if error_elem is not None:
                    code = (error_elem.get("code") or "").strip()
                    msg = (error_elem.text or "").strip()

                    if code == "15":
                        return []  # «По запросу ничего не найдено» — это не ошибка

                    if code == "111":
                        # Нет свободных каналов — временно. Ждём и повторяем.
                        last_err = f"нет свободных каналов (111)"
                        time.sleep(5 * (2 ** attempt))  # 5, 10, 20, 40 c
                        continue

                    # Прочие коды (неверный ключ, исчерпан баланс и т.п.) — неустранимо.
                    raise RuntimeError(f"{self.name}: ошибка API code={code} — {msg}")

                return self._parse_groups(root, page)

            except requests.exceptions.RequestException as e:
                if "429" in str(e):
                    self.mark_exhausted(key_str)
                    raise RuntimeError(f"{self.name}: ключ исчерпан (429)")
                last_err = str(e)
                time.sleep(3 * (2 ** attempt))

        raise RuntimeError(
            f"{self.name}: страница {page} не получена после ретраев — {last_err}"
        )

    @staticmethod
    def _parse_groups(root, page):
        """Извлечь результаты из XML одной страницы. Позиция — сквозная по страницам."""
        results = []

        def _add(idx, doc, snippet_path):
            url_elem = doc.find(".//url")
            url_text = url_elem.text.strip() if url_elem is not None and url_elem.text else ""
            # Фильтруем внутренние страницы Яндекса
            if "yandex.ru/maps" in url_text or "yandex.ru/search" in url_text:
                return
            title_elem = doc.find(".//title")
            title_text = ''.join(title_elem.itertext()).strip() if title_elem is not None else ""
            snippet_elem = doc.find(snippet_path)
            snippet_text = ''.join(snippet_elem.itertext()).strip() if snippet_elem is not None else ""
            results.append({
                "position": page * 10 + idx + 1,
                "title": title_text,
                "link": url_text,
                "snippet": snippet_text,
            })

        # Вариант 1: стандартный Яндекс XML формат (group → doc)
        groups = root.findall(".//group")
        if groups:
            for idx, group in enumerate(groups):
                doc = group.find(".//doc")
                if doc is not None:
                    _add(idx, doc, ".//passages/passage")
        else:
            # Вариант 2: прямые doc элементы
            for idx, doc in enumerate(root.findall(".//doc")):
                _add(idx, doc, ".//snippet")

        return results


class SERPRotator:
    """Главный ротатор всех SERP-сервисов"""
    def __init__(self, serper_keys: List[str], valueserp_keys: List[str],
                 serpapi_keys: List[str], xmlriver_keys: List[str]):
        self.google_services = []
        self.yandex_services = []

        if serper_keys:
            self.google_services.append(SerperService(serper_keys))
        if valueserp_keys:
            self.google_services.append(ValueSERPService(valueserp_keys))
        if serpapi_keys:
            self.google_services.append(SerpApiService(serpapi_keys))
        if xmlriver_keys:
            self.yandex_services.append(XMLRiverService(xmlriver_keys))

        self.google_index = 0
        self.yandex_index = 0

    def search_google(self, query: str, log_callback=None) -> Dict:
        """Поиск в Google с ротацией сервисов"""
        if not self.google_services:
            raise RuntimeError("Нет доступных Google SERP-сервисов")

        attempts = 0
        while attempts < len(self.google_services):
            service = self.google_services[self.google_index]
            self.google_index = (self.google_index + 1) % len(self.google_services)

            try:
                if log_callback:
                    log_callback(f"🔍 Google поиск через {service.name}")
                result = service.search(query)
                return result
            except RuntimeError as e:
                if log_callback:
                    log_callback(f"⚠️ {e}")
                attempts += 1
                time.sleep(2)

        raise RuntimeError("Все Google SERP-сервисы исчерпаны")

    def search_yandex(self, query: str, limit: int = 10, lr: int = None, log_callback=None) -> Dict:
        """Поиск в Яндекс с ротацией сервисов.

        limit — сколько позиций собрать (Яндекс листается по 10 на страницу).
        lr — id региона Яндекса (опционально); если не задан, используется домен по умолчанию.
        """
        if not self.yandex_services:
            raise RuntimeError("Нет доступных Яндекс SERP-сервисов")

        attempts = 0
        while attempts < len(self.yandex_services):
            service = self.yandex_services[self.yandex_index]
            self.yandex_index = (self.yandex_index + 1) % len(self.yandex_services)

            try:
                if log_callback:
                    log_callback(f"🔍 Яндекс поиск через {service.name}")
                result = service.search(query, limit=limit, lr=lr)
                return result
            except RuntimeError as e:
                if log_callback:
                    log_callback(f"⚠️ {e}")
                attempts += 1
                time.sleep(2)

        raise RuntimeError("Все Яндекс SERP-сервисы исчерпаны")
