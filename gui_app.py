"""
GUI приложение для сбора базы бизнесов
"""

import sys
import os
import json
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QTextEdit, QProgressBar, QMessageBox, QHeaderView, QSpinBox,
    QGroupBox, QFileDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

from collector_core import KeyRotator, collect_city, save_xlsx


class CollectorThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    finished_signal = pyqtSignal(str, int)
    error_signal = pyqtSignal(str)

    def __init__(self, api_keys, business_type, cities):
        super().__init__()
        self.api_keys = api_keys
        self.business_type = business_type
        self.cities = cities
        self.is_running = True

    def run(self):
        try:
            rotator = KeyRotator(self.api_keys)
            self.log_signal.emit(f"Загружено ключей: {len(rotator.keys)}")
            self.log_signal.emit("Google Search grounding: подключён\n")

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
                        batch_size=5,
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
        self.setWindowTitle("Сборщик базы бизнесов — Gemini 2.5 Flash")
        self.setGeometry(100, 100, 1000, 700)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Заголовок
        title = QLabel("🔍 Сборщик базы бизнесов")
        title_font = QFont("Arial", 16, QFont.Bold)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title)

        # Группа: API ключи
        api_group = QGroupBox("API Ключи Gemini")
        api_layout = QVBoxLayout()

        api_label = QLabel("Введите API ключи (по одному на строку):")
        api_layout.addWidget(api_label)

        self.api_keys_text = QTextEdit()
        self.api_keys_text.setPlaceholderText("AIzaSy...\nAIzaSy...\nAIzaSy...")
        self.api_keys_text.setMaximumHeight(100)
        api_layout.addWidget(self.api_keys_text)

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
        self.cities_table.setMaximumHeight(150)
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
        self.log_text.setMaximumHeight(200)
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
        api_keys = [k.strip() for k in self.api_keys_text.toPlainText().split("\n") if k.strip()]
        business_type = self.business_type_input.text().strip()
        cities = self.get_cities()

        if not api_keys:
            QMessageBox.warning(self, "Ошибка", "Введите хотя бы один API ключ")
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

        self.collector_thread = CollectorThread(api_keys, business_type, cities)
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
            "api_keys": self.api_keys_text.toPlainText(),
            "business_type": self.business_type_input.text(),
            "cities": self.get_cities()
        }

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить настройки",
            "config.json",
            "JSON Files (*.json)"
        )

        if filename:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Успех", f"Настройки сохранены в {filename}")

    def load_settings(self):
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r", encoding="utf-8") as f:
                    settings = json.load(f)

                self.api_keys_text.setPlainText(settings.get("api_keys", ""))
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
