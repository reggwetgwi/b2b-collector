"""
GUI приложение для сбора базы бизнесов через SERP-сервисы
"""

import sys
import os
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QProgressBar, QMessageBox, QHeaderView, QSpinBox,
    QGroupBox, QFileDialog, QTabWidget
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont

from serp_rotator import SERPRotator
from collector_core_serp import collect_city, save_xlsx
from gemini_enricher import GeminiEnricher
from dadata_enricher import DaDataEnricher
from twogis_enricher import TwoGISEnricher
from gemini_filter import GeminiFilter
from groq_filter import GroqFilter
from groq_enricher import GroqEnricher


class CollectorThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(str, int)
    error_signal = pyqtSignal(str)

    def __init__(self, serper_keys, valueserp_keys, serpapi_keys, xmlriver_keys, dadata_keys, twogis_keys, gemini_keys, groq_keys, business_type, cities):
        super().__init__()
        self.serper_keys = serper_keys
        self.valueserp_keys = valueserp_keys
        self.serpapi_keys = serpapi_keys
        self.xmlriver_keys = xmlriver_keys
        self.dadata_keys = dadata_keys
        self.twogis_keys = twogis_keys
        self.gemini_keys = gemini_keys
        self.groq_keys = groq_keys
        self.business_type = business_type
        self.cities = cities
        self.is_running = True

    def run(self):
        try:
            rotator = SERPRotator(
                self.serper_keys,
                self.valueserp_keys,
                self.serpapi_keys,
                self.xmlriver_keys
            )

            self.log_signal.emit(f"✓ Google сервисов: {len(rotator.google_services)}")
            self.log_signal.emit(f"✓ Яндекс сервисов: {len(rotator.yandex_services)}\n")

            # Инициализируем фильтр SERP-выдачи.
            # Приоритет — Groq (бесплатный); Gemini как запасной вариант.
            gemini_filter = None
            if self.groq_keys:
                try:
                    gemini_filter = GroqFilter(self.groq_keys)
                    self.log_signal.emit(f"✓ Groq фильтр: включен ({len(gemini_filter.keys)} ключей)\n")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Groq фильтр: отключен ({e})\n")
            elif self.gemini_keys:
                try:
                    gemini_filter = GeminiFilter(self.gemini_keys)
                    self.log_signal.emit(f"✓ Gemini фильтр: включен ({len(gemini_filter.keys)} ключей)\n")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Gemini фильтр: отключен ({e})\n")

            # Инициализируем DaData обогащение (если есть ключи)
            dadata_enricher = None
            if self.dadata_keys:
                try:
                    dadata_enricher = DaDataEnricher(self.dadata_keys)
                    self.log_signal.emit(f"✓ DaData обогащение: включено ({len(dadata_enricher.keys)} ключей)\n")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ DaData обогащение: отключено ({e})\n")

            # Инициализируем 2GIS обогащение (если есть ключи)
            twogis_enricher = None
            if self.twogis_keys:
                try:
                    twogis_enricher = TwoGISEnricher(self.twogis_keys)
                    self.log_signal.emit(f"✓ 2GIS обогащение: включено ({len(twogis_enricher.keys)} ключей)\n")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ 2GIS обогащение: отключено ({e})\n")

            # Инициализируем обогащение услугами.
            # Приоритет — Groq (бесплатный, тянет услуги из сниппетов);
            # Gemini как запасной вариант (умеет ещё рейтинги через веб-поиск).
            gemini_enricher = None
            if self.groq_keys:
                try:
                    gemini_enricher = GroqEnricher(self.groq_keys)
                    self.log_signal.emit(f"✓ Groq обогащение: включено ({len(gemini_enricher.keys)} ключей)\n")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Groq обогащение: отключено ({e})\n")
            elif self.gemini_keys:
                try:
                    gemini_enricher = GeminiEnricher(self.gemini_keys)
                    self.log_signal.emit(f"✓ Gemini обогащение: включено ({len(gemini_enricher.keys)} ключей)\n")
                except Exception as e:
                    self.log_signal.emit(f"⚠️ Gemini обогащение: отключено ({e})\n")

            all_businesses = []
            total_limit = sum(city["limit"] for city in self.cities)
            collected = 0

            for city in self.cities:
                if not self.is_running:
                    self.log_signal.emit("\n⚠️ Сбор остановлен пользователем")
                    return

                try:
                    def city_progress(current, limit):
                        self.progress_signal.emit(collected + current, total_limit)

                    businesses = collect_city(
                        rotator,
                        self.business_type,
                        city["name"],
                        city["limit"],
                        gemini_filter=gemini_filter,
                        dadata_enricher=dadata_enricher,
                        twogis_enricher=twogis_enricher,
                        gemini_enricher=gemini_enricher,
                        log_callback=self.log_signal.emit,
                        progress_callback=city_progress
                    )
                    all_businesses.extend(businesses)
                    collected += len(businesses)
                    self.log_signal.emit(f"✓ Итого в базе: {len(all_businesses)} бизнесов\n")

                except Exception as e:
                    self.log_signal.emit(f"❌ ОШИБКА для {city['name']}: {e}\n")

            if not all_businesses:
                self.error_signal.emit("Ничего не собрано. Проверь API ключи и повтори.")
                return

            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            business_slug = self.business_type.replace(" ", "_").lower()
            filename = f"{business_slug}_{timestamp}.xlsx"

            self.log_signal.emit(f"\n💾 Сохраняю в {filename}...")
            save_xlsx(all_businesses, self.business_type, filename)

            self.finished_signal.emit(filename, len(all_businesses))

        except Exception as e:
            self.error_signal.emit(f"Критическая ошибка: {str(e)}")

    def stop(self):
        self.is_running = False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.collector_thread = None
        self.init_ui()
        self.load_settings()

    def init_ui(self):
        self.setWindowTitle("Сборщик базы бизнесов — SERP парсинг")
        self.setGeometry(100, 100, 1100, 750)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Заголовок
        title = QLabel("🔍 Сборщик базы бизнесов (SERP)")
        title_font = QFont("Arial", 16, QFont.Bold)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # Группа: API ключи (табы)
        api_group = QGroupBox("API Ключи SERP-сервисов")
        api_layout = QVBoxLayout()

        self.api_tabs = QTabWidget()

        # Tab 1: Serper.dev
        serper_tab = QWidget()
        serper_layout = QVBoxLayout()
        serper_layout.addWidget(QLabel("Serper.dev ключи (по одному на строку):"))
        self.serper_keys_text = QTextEdit()
        self.serper_keys_text.setPlaceholderText("your-api-key-1\nyour-api-key-2...")
        self.serper_keys_text.setMaximumHeight(80)
        serper_layout.addWidget(self.serper_keys_text)
        serper_tab.setLayout(serper_layout)
        self.api_tabs.addTab(serper_tab, "Google Serper")

        # Tab 2: ValueSERP
        valueserp_tab = QWidget()
        valueserp_layout = QVBoxLayout()
        valueserp_layout.addWidget(QLabel("ValueSERP ключи (по одному на строку):"))
        self.valueserp_keys_text = QTextEdit()
        self.valueserp_keys_text.setPlaceholderText("your-api-key-1\nyour-api-key-2...")
        self.valueserp_keys_text.setMaximumHeight(80)
        valueserp_layout.addWidget(self.valueserp_keys_text)
        valueserp_tab.setLayout(valueserp_layout)
        self.api_tabs.addTab(valueserp_tab, "Google ValueSERP")

        # Tab 3: SerpApi
        serpapi_tab = QWidget()
        serpapi_layout = QVBoxLayout()
        serpapi_layout.addWidget(QLabel("SerpApi ключи (по одному на строку):"))
        self.serpapi_keys_text = QTextEdit()
        self.serpapi_keys_text.setPlaceholderText("your-api-key-1\nyour-api-key-2...")
        self.serpapi_keys_text.setMaximumHeight(80)
        serpapi_layout.addWidget(self.serpapi_keys_text)
        serpapi_tab.setLayout(serpapi_layout)
        self.api_tabs.addTab(serpapi_tab, "Google SerpApi")

        # Tab 4: XMLRiver
        xmlriver_tab = QWidget()
        xmlriver_layout = QVBoxLayout()
        xmlriver_layout.addWidget(QLabel("XMLRiver ключи (формат user:key, по одному на строку):"))
        self.xmlriver_keys_text = QTextEdit()
        self.xmlriver_keys_text.setPlaceholderText("user1:api-key-1\nuser2:api-key-2...")
        self.xmlriver_keys_text.setMaximumHeight(80)
        xmlriver_layout.addWidget(self.xmlriver_keys_text)
        xmlriver_tab.setLayout(xmlriver_layout)
        self.api_tabs.addTab(xmlriver_tab, "Яндекс XMLRiver")

        # Tab 5: DaData (обогащение)
        dadata_tab = QWidget()
        dadata_layout = QVBoxLayout()
        dadata_layout.addWidget(QLabel("DaData API ключи для обогащения (опционально):"))
        self.dadata_keys_text = QTextEdit()
        self.dadata_keys_text.setPlaceholderText("ваш-токен-dadata\nвторой-токен...")
        self.dadata_keys_text.setMaximumHeight(80)
        dadata_layout.addWidget(self.dadata_keys_text)
        dadata_info = QLabel("ℹ️ DaData дополнит: ИНН, адреса, директора из ЕГРЮЛ (~10₽/100)")
        dadata_info.setStyleSheet("color: #666; font-size: 10px;")
        dadata_layout.addWidget(dadata_info)
        dadata_tab.setLayout(dadata_layout)
        self.api_tabs.addTab(dadata_tab, "DaData (обогащение)")

        # Tab 6: 2GIS (обогащение)
        twogis_tab = QWidget()
        twogis_layout = QVBoxLayout()
        twogis_layout.addWidget(QLabel("2GIS API ключи для обогащения (опционально):"))
        self.twogis_keys_text = QTextEdit()
        self.twogis_keys_text.setPlaceholderText("ваш-ключ-2gis\nвторой-ключ...")
        self.twogis_keys_text.setMaximumHeight(80)
        twogis_layout.addWidget(self.twogis_keys_text)
        twogis_info = QLabel("ℹ️ 2GIS дополнит: адреса, телефоны, рейтинги (бесплатно до 25k/день)")
        twogis_info.setStyleSheet("color: #666; font-size: 10px;")
        twogis_layout.addWidget(twogis_info)
        twogis_tab.setLayout(twogis_layout)
        self.api_tabs.addTab(twogis_tab, "2GIS (обогащение)")

        # Tab 7: Gemini (обогащение)
        gemini_tab = QWidget()
        gemini_layout = QVBoxLayout()
        gemini_layout.addWidget(QLabel("Gemini ключи для обогащения данных (опционально):"))
        self.gemini_keys_text = QTextEdit()
        self.gemini_keys_text.setPlaceholderText("AIzaSy...\nAIzaSy...")
        self.gemini_keys_text.setMaximumHeight(80)
        gemini_layout.addWidget(self.gemini_keys_text)
        gemini_info = QLabel("ℹ️ Gemini дополнит: адреса, ИНН, телефоны, рейтинги (~$3/100)")
        gemini_info.setStyleSheet("color: #666; font-size: 10px;")
        gemini_layout.addWidget(gemini_info)
        gemini_tab.setLayout(gemini_layout)
        self.api_tabs.addTab(gemini_tab, "Gemini (обогащение)")

        # Tab 8: Groq (фильтр + обогащение, бесплатно)
        groq_tab = QWidget()
        groq_layout = QVBoxLayout()
        groq_layout.addWidget(QLabel("Groq API ключи (по одному на строку):"))
        self.groq_keys_text = QTextEdit()
        self.groq_keys_text.setPlaceholderText("gsk_...\ngsk_...")
        self.groq_keys_text.setMaximumHeight(80)
        groq_layout.addWidget(self.groq_keys_text)
        groq_info = QLabel("ℹ️ Groq — бесплатная замена Gemini (фильтр выдачи + услуги). Ключ: console.groq.com. Приоритетнее Gemini")
        groq_info.setStyleSheet("color: #666; font-size: 10px;")
        groq_layout.addWidget(groq_info)
        groq_tab.setLayout(groq_layout)
        self.api_tabs.addTab(groq_tab, "Groq (бесплатно)")

        api_layout.addWidget(self.api_tabs)
        api_group.setLayout(api_layout)
        main_layout.addWidget(api_group)

        # Группа: Настройки поиска
        search_group = QGroupBox("Настройки поиска")
        search_layout = QVBoxLayout()

        business_layout = QHBoxLayout()
        business_layout.addWidget(QLabel("Тип бизнеса:"))
        self.business_type_input = QLineEdit()
        self.business_type_input.setPlaceholderText("стоматология, салон красоты, автосервис...")
        business_layout.addWidget(self.business_type_input)
        search_layout.addLayout(business_layout)

        search_group.setLayout(search_layout)
        main_layout.addWidget(search_group)

        # Группа: Города
        cities_group = QGroupBox("Города для сбора")
        cities_layout = QVBoxLayout()

        self.cities_table = QTableWidget()
        self.cities_table.setColumnCount(2)
        self.cities_table.setHorizontalHeaderLabels(["Город", "Лимит"])
        self.cities_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.cities_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.cities_table.setMaximumHeight(120)
        cities_layout.addWidget(self.cities_table)

        cities_buttons = QHBoxLayout()

        city_input_layout = QHBoxLayout()
        self.city_name_input = QLineEdit()
        self.city_name_input.setPlaceholderText("Название города")
        city_input_layout.addWidget(self.city_name_input)

        self.city_limit_input = QSpinBox()
        self.city_limit_input.setMinimum(1)
        self.city_limit_input.setMaximum(500)
        self.city_limit_input.setValue(10)
        self.city_limit_input.setPrefix("Лимит: ")
        city_input_layout.addWidget(self.city_limit_input)

        cities_buttons.addLayout(city_input_layout)

        add_city_btn = QPushButton("➕ Добавить город")
        add_city_btn.clicked.connect(self.add_city)
        cities_buttons.addWidget(add_city_btn)

        remove_city_btn = QPushButton("➖ Удалить выбранный")
        remove_city_btn.clicked.connect(self.remove_city)
        cities_buttons.addWidget(remove_city_btn)

        cities_layout.addLayout(cities_buttons)
        cities_group.setLayout(cities_layout)
        main_layout.addWidget(cities_group)

        # Кнопки управления
        control_layout = QHBoxLayout()

        self.start_btn = QPushButton("▶️ Начать сбор")
        self.start_btn.setStyleSheet("background-color: #4CAF50; color: white; font-size: 14px; padding: 10px;")
        self.start_btn.clicked.connect(self.start_collection)
        control_layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹️ Остановить")
        self.stop_btn.setStyleSheet("background-color: #f44336; color: white; font-size: 14px; padding: 10px;")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_collection)
        control_layout.addWidget(self.stop_btn)

        save_config_btn = QPushButton("💾 Сохранить настройки")
        save_config_btn.clicked.connect(self.save_settings)
        control_layout.addWidget(save_config_btn)

        main_layout.addLayout(control_layout)

        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        # Лог
        log_label = QLabel("📋 Лог работы:")
        main_layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(180)
        main_layout.addWidget(self.log_text)

    def add_city(self):
        city_name = self.city_name_input.text().strip()
        if not city_name:
            QMessageBox.warning(self, "Ошибка", "Введите название города")
            return

        row = self.cities_table.rowCount()
        self.cities_table.insertRow(row)
        self.cities_table.setItem(row, 0, QTableWidgetItem(city_name))
        self.cities_table.setItem(row, 1, QTableWidgetItem(str(self.city_limit_input.value())))

        self.city_name_input.clear()

    def remove_city(self):
        current_row = self.cities_table.currentRow()
        if current_row >= 0:
            self.cities_table.removeRow(current_row)

    def get_cities(self):
        cities = []
        for row in range(self.cities_table.rowCount()):
            name = self.cities_table.item(row, 0).text()
            limit = int(self.cities_table.item(row, 1).text())
            cities.append({"name": name, "limit": limit})
        return cities

    def start_collection(self):
        serper_keys = [k.strip() for k in self.serper_keys_text.toPlainText().split("\n") if k.strip()]
        valueserp_keys = [k.strip() for k in self.valueserp_keys_text.toPlainText().split("\n") if k.strip()]
        serpapi_keys = [k.strip() for k in self.serpapi_keys_text.toPlainText().split("\n") if k.strip()]
        xmlriver_keys = [k.strip() for k in self.xmlriver_keys_text.toPlainText().split("\n") if k.strip()]
        dadata_keys = [k.strip() for k in self.dadata_keys_text.toPlainText().split("\n") if k.strip()]
        twogis_keys = [k.strip() for k in self.twogis_keys_text.toPlainText().split("\n") if k.strip()]
        gemini_keys = [k.strip() for k in self.gemini_keys_text.toPlainText().split("\n") if k.strip()]
        groq_keys = [k.strip() for k in self.groq_keys_text.toPlainText().split("\n") if k.strip()]

        business_type = self.business_type_input.text().strip()
        cities = self.get_cities()

        if not any([serper_keys, valueserp_keys, serpapi_keys, xmlriver_keys]):
            QMessageBox.warning(self, "Ошибка", "Введите хотя бы один API ключ SERP-сервиса")
            return

        if not business_type:
            QMessageBox.warning(self, "Ошибка", "Введите тип бизнеса")
            return

        if not cities:
            QMessageBox.warning(self, "Ошибка", "Добавьте хотя бы один город")
            return

        self.log_text.clear()
        self.progress_bar.setValue(0)
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.collector_thread = CollectorThread(
            serper_keys, valueserp_keys, serpapi_keys, xmlriver_keys, dadata_keys, twogis_keys, gemini_keys, groq_keys,
            business_type, cities
        )
        self.collector_thread.log_signal.connect(self.append_log)
        self.collector_thread.progress_signal.connect(self.update_progress)
        self.collector_thread.finished_signal.connect(self.collection_finished)
        self.collector_thread.error_signal.connect(self.collection_error)
        self.collector_thread.start()

    def stop_collection(self):
        if self.collector_thread:
            self.collector_thread.stop()
            self.stop_btn.setEnabled(False)

    def append_log(self, message):
        self.log_text.append(message)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def update_progress(self, current, total):
        if total > 0:
            percentage = int((current / total) * 100)
            self.progress_bar.setValue(percentage)

    def collection_finished(self, filename, count):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)

        QMessageBox.information(
            self,
            "✅ Готово!",
            f"Сбор завершён!\n\nСобрано бизнесов: {count}\nФайл: {filename}"
        )

    def collection_error(self, error_msg):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        QMessageBox.critical(self, "❌ Ошибка", error_msg)

    def save_settings(self):
        settings = {
            "serper_keys": self.serper_keys_text.toPlainText(),
            "valueserp_keys": self.valueserp_keys_text.toPlainText(),
            "serpapi_keys": self.serpapi_keys_text.toPlainText(),
            "xmlriver_keys": self.xmlriver_keys_text.toPlainText(),
            "dadata_keys": self.dadata_keys_text.toPlainText(),
            "twogis_keys": self.twogis_keys_text.toPlainText(),
            "gemini_keys": self.gemini_keys_text.toPlainText(),
            "groq_keys": self.groq_keys_text.toPlainText(),
            "business_type": self.business_type_input.text(),
            "cities": self.get_cities()
        }

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить настройки",
            "config_serp.json",
            "JSON Files (*.json)"
        )

        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Успех", f"Настройки сохранены в {filename}")

    def load_settings(self):
        if os.path.exists("config_serp.json"):
            try:
                with open("config_serp.json", "r", encoding="utf-8") as f:
                    settings = json.load(f)

                self.serper_keys_text.setPlainText(settings.get("serper_keys", ""))
                self.valueserp_keys_text.setPlainText(settings.get("valueserp_keys", ""))
                self.serpapi_keys_text.setPlainText(settings.get("serpapi_keys", ""))
                self.xmlriver_keys_text.setPlainText(settings.get("xmlriver_keys", ""))
                self.dadata_keys_text.setPlainText(settings.get("dadata_keys", ""))
                self.twogis_keys_text.setPlainText(settings.get("twogis_keys", ""))
                self.gemini_keys_text.setPlainText(settings.get("gemini_keys", ""))
                self.groq_keys_text.setPlainText(settings.get("groq_keys", ""))
                self.business_type_input.setText(settings.get("business_type", ""))

                for city in settings.get("cities", []):
                    row = self.cities_table.rowCount()
                    self.cities_table.insertRow(row)
                    self.cities_table.setItem(row, 0, QTableWidgetItem(city["name"]))
                    self.cities_table.setItem(row, 1, QTableWidgetItem(str(city["limit"])))
            except Exception as e:
                print(f"Не удалось загрузить настройки: {e}")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
