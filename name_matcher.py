"""
Улучшенный модуль для сравнения и нормализации названий компаний
"""

import re
from difflib import SequenceMatcher
from typing import List, Tuple


def normalize_name(name: str) -> str:
    """
    Нормализация названия для улучшенного сравнения:
    - Убирает ООО, ИП, ЗАО, ПАО и другие организационные формы
    - Убирает кавычки, скобки, точки, запятые
    - Приводит к нижнему регистру
    - Убирает множественные пробелы
    """
    if not name:
        return ""

    # Приводим к нижнему регистру
    name = name.lower()

    # Убираем организационные формы (русские и английские)
    org_forms = [
        r'\bооо\b', r'\bзао\b', r'\bпао\b', r'\bао\b', r'\bнпо\b', r'\bгуп\b',
        r'\bмуп\b', r'\bчп\b', r'\bип\b', r'\bптс\b', r'\bнко\b',
        r'\bltd\b', r'\bllc\b', r'\binc\b', r'\bcorp\b', r'\bco\b',
        r'\bпубличное акционерное общество\b',
        r'\bобщество с ограниченной ответственностью\b',
        r'\bзакрытое акционерное общество\b',
        r'\bиндивидуальный предприниматель\b',
    ]

    for form in org_forms:
        name = re.sub(form, '', name, flags=re.IGNORECASE)

    # Убираем кавычки всех типов
    name = re.sub(r'[«»"""\'`]', '', name)

    # Убираем скобки и их содержимое
    name = re.sub(r'\([^)]*\)', '', name)
    name = re.sub(r'\[[^\]]*\]', '', name)

    # Убираем знаки препинания (кроме дефиса, который может быть значимым)
    name = re.sub(r'[.,;:!?]', '', name)

    # Заменяем множественные пробелы на один
    name = re.sub(r'\s+', ' ', name)

    # Убираем пробелы в начале и конце
    name = name.strip()

    return name


def extract_words(name: str) -> set:
    """Извлекает значимые слова из названия (длина >= 3 символа)"""
    words = re.findall(r'\b\w{3,}\b', normalize_name(name))
    return set(words)


def word_overlap_score(name1: str, name2: str) -> float:
    """
    Вычисляет коэффициент пересечения слов между названиями
    Возвращает: (количество совпадающих слов) / (количество слов в меньшем названии)
    """
    words1 = extract_words(name1)
    words2 = extract_words(name2)

    if not words1 or not words2:
        return 0.0

    intersection = len(words1 & words2)
    min_count = min(len(words1), len(words2))

    return intersection / min_count if min_count > 0 else 0.0


def sequence_similarity(name1: str, name2: str) -> float:
    """Вычисляет схожесть последовательностей символов (0.0 - 1.0)"""
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)

    if not norm1 or not norm2:
        return 0.0

    return SequenceMatcher(None, norm1, norm2).ratio()


def partial_match_score(name1: str, name2: str) -> float:
    """
    Проверяет частичное вхождение одного названия в другое
    Полезно для случаев типа "Зуб.ру" vs "Стоматологическая клиника Зуб.ру"
    """
    norm1 = normalize_name(name1)
    norm2 = normalize_name(name2)

    if not norm1 or not norm2:
        return 0.0

    shorter = min(norm1, norm2, key=len)
    longer = max(norm1, norm2, key=len)

    if shorter in longer:
        return len(shorter) / len(longer)

    return 0.0


def combined_similarity(name1: str, name2: str, weights: dict = None) -> Tuple[float, dict]:
    """
    Комбинированная оценка схожести с использованием нескольких метрик

    Args:
        name1: Первое название
        name2: Второе название
        weights: Веса для метрик (по умолчанию равные)

    Returns:
        (общий_score, детали_по_метрикам)
    """
    if weights is None:
        weights = {
            'sequence': 0.4,
            'word_overlap': 0.4,
            'partial_match': 0.2,
        }

    scores = {
        'sequence': sequence_similarity(name1, name2),
        'word_overlap': word_overlap_score(name1, name2),
        'partial_match': partial_match_score(name1, name2),
    }

    # Взвешенная сумма
    total_score = sum(scores[key] * weights[key] for key in scores)

    return total_score, scores


def find_best_match(query_name: str, candidates: List[dict],
                    name_field: str = 'name',
                    threshold: float = 0.45) -> Tuple[dict, float, dict]:
    """
    Найти лучшее совпадение из списка кандидатов

    Args:
        query_name: Искомое название
        candidates: Список словарей с данными компаний
        name_field: Название поля с именем компании в словаре
        threshold: Минимальный порог схожести (по умолчанию 0.45)

    Returns:
        (лучший_кандидат, итоговый_score, детали_метрик) или (None, 0, {})
    """
    best_match = None
    best_score = 0.0
    best_details = {}

    for candidate in candidates:
        candidate_name = candidate.get(name_field, "")
        if not candidate_name:
            continue

        score, details = combined_similarity(query_name, candidate_name)

        if score > best_score and score >= threshold:
            best_score = score
            best_match = candidate
            best_details = details

    return best_match, best_score, best_details


# Примеры использования для тестирования
if __name__ == "__main__":
    from transliterate import transliterate_to_russian

    test_cases = [
        ("СМ-Стоматология", "ООО «СМ-Стоматология»"),
        ("Зуб.ру", "Стоматологическая клиника Зуб.ру"),
        ("On Clinic", "ОН КЛИНИК"),
        ("Dental Way", "Дентал Вей"),
        ("Легстом", "ООО Легстом"),
        # Тесты с транслитерацией
        (transliterate_to_russian("On Clinic"), "ОН КЛИНИК"),
        (transliterate_to_russian("Dental Way"), "Дентал Вей"),
    ]

    print("Тесты сравнения названий:\n")
    for name1, name2 in test_cases:
        score, details = combined_similarity(name1, name2)
        print(f"{name1} vs {name2}")
        print(f"  Общий score: {score:.3f}")
        print(f"  Детали: {details}")
        print()
