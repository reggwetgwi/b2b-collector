"""
GUI релизного сборщика — современный интерфейс.
Тёмная тема, карточки, чистые формы, прогресс-полоса в стиле 2026.
"""
import sys, os, json
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QProgressBar,
    QMessageBox, QGroupBox, QCheckBox, QSpinBox, QScrollArea,
    QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QPalette, QColor

from release_core import Engine

CONFIG = "config_release.json"

# ── Тема ──────────────────────────────────────────────────────
STYLE = """
* { font-family: "Segoe UI", system-ui, sans-serif; }

QMainWindow, QWidget#central {
    background-color: #0f1117;
    color: #e1e4e8;
}

QGroupBox {
    border: 1px solid #21262d;
    border-radius: 8px;
    margin-top: 14px;
    padding: 18px 12px 12px 12px;
    font-size: 12px;
    font-weight: 600;
    color: #8b949e;
    background: #161b22;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #58a6ff;
}

QLabel { color: #c9d1d9; font-size: 12px; }
QLabel#title { font-size: 18px; font-weight: 700; color: #f0f6fc; }
QLabel#subtitle { font-size: 11px; color: #8b949e; }
QLabel#stat { font-size: 11px; color: #58a6ff; margin-right: 10px; }

QLineEdit, QSpinBox {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #c9d1d9;
    font-size: 12px;
    min-height: 20px;
}
QLineEdit:focus, QSpinBox:focus { border-color: #58a6ff; }

QSpinBox::up-button, QSpinBox::down-button {
    background: #21262d; border-radius: 3px; width: 16px;
}

QPushButton {
    border-radius: 6px;
    padding: 8px 18px;
    font-size: 12px;
    font-weight: 600;
    border: 1px solid #30363d;
    background: #21262d;
    color: #c9d1d9;
}
QPushButton:hover { background: #30363d; border-color: #58a6ff; }
QPushButton#primary {
    background: #238636; color: white; border-color: #2ea043;
}
QPushButton#primary:hover { background: #2ea043; }
QPushButton#primary:disabled { background: #1a2e24; color: #555; }
QPushButton#danger {
    background: #da3633; color: white; border-color: #f85149;
}
QPushButton#danger:hover { background: #f85149; }

QCheckBox { color: #c9d1d9; font-size: 12px; spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid #30363d; background: #0d1117;
}
QCheckBox::indicator:checked { background: #58a6ff; border-color: #58a6ff; }

QTextEdit {
    background: #0d1117; border: 1px solid #30363d; border-radius: 6px;
    color: #7ee787; font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 11px; padding: 10px; selection-background-color: #1f364d;
}

QProgressBar {
    background: #161b22; border: none; border-radius: 10px;
    height: 6px; text-align: center; font-size: 10px; color: #58a6ff;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1f6feb, stop:1 #58a6ff);
    border-radius: 10px;
}

QTabWidget::pane { border: 1px solid #30363d; border-radius: 6px; background: #161b22; }
QTabBar::tab {
    background: #0d1117; border: 1px solid #30363d; border-bottom: none;
    padding: 7px 16px; font-size: 11px; color: #8b949e;
    border-top-left-radius: 6px; border-top-right-radius: 6px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background: #161b22; color: #58a6ff; border-bottom: 1px solid #161b22;
}
QTabBar::tab:hover:!selected { color: #c9d1d9; }

QScrollBar:vertical {
    background: #0d1117; width: 8px; border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #30363d; border-radius: 4px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #58a6ff; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QToolTip {
    background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
    border-radius: 4px; padding: 4px 8px; font-size: 11px;
}
"""


class Worker(QThread):
    log_s = pyqtSignal(str)
    prog_s = pyqtSignal(int, int)
    done_s = pyqtSignal(str, int)
    fail_s = pyqtSignal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            eng = Engine(self.cfg, log=self.log_s.emit,
                         progress=lambda a, b: self.prog_s.emit(a, b),
                         should_stop=lambda: self._stop)
            path, n = eng.run()
            self.done_s.emit(path, n)
        except Exception as e:
            self.fail_s.emit(str(e))


class Main(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker = None
        self._build_ui()
        self._load()

    def _card(self, title):
        g = QGroupBox(title)
        g.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        return g, QVBoxLayout(g)

    def _build_ui(self):
        self.setWindowTitle("BusinessCollector Pro")
        self.setGeometry(160, 80, 1120, 780)
        self.setMinimumSize(880, 600)

        # центральный контейнер с отступами
        root = QWidget()
        root.setObjectName("central")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(28, 20, 28, 20)
        outer.setSpacing(16)

        # заголовок + статус
        hdr = QHBoxLayout()
        t = QLabel("BusinessCollector Pro")
        t.setObjectName("title")
        hdr.addWidget(t)
        hdr.addStretch()
        self.stat = QLabel("Готов к запуску")
        self.stat.setObjectName("stat")
        hdr.addWidget(self.stat)
        outer.addLayout(hdr)

        # ── тело: левая колонка (настройки) + правая (лог) ──
        body = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(14)

        # карточка: поиск
        gc_s, lc_s = self._card("Поиск")
        r1 = QHBoxLayout()
        r1.addWidget(QLabel("Тип бизнеса"))
        self.biz = QLineEdit("стоматология"); r1.addWidget(self.biz)
        r1.addWidget(QLabel("ОКВЭД"))
        self.okved = QLineEdit("86.23"); self.okved.setMaximumWidth(85); r1.addWidget(self.okved)
        lc_s.addLayout(r1)

        r1b = QHBoxLayout()
        r1b.addWidget(QLabel("Города"))
        self.cities = QLineEdit("Москва:100, Санкт-Петербург:50")
        self.cities.setToolTip("Формат: Город:лимит через запятую.\nНапр.: Москва:100, Санкт-Петербург:50\nБез двоеточия — берётся лимит по умолчанию справа.")
        r1b.addWidget(self.cities)
        r1b.addWidget(QLabel("Лимит по умолч."))
        self.limit = QSpinBox(); self.limit.setRange(10, 1000); self.limit.setValue(150); self.limit.setMaximumWidth(90)
        r1b.addWidget(self.limit)
        lc_s.addLayout(r1b)
        left.addWidget(gc_s)

        # карточка: слои
        gc_l, lc_l = self._card("Слои данных")
        rl1, rl2 = QHBoxLayout(), QHBoxLayout()
        self.cb_reg = QCheckBox("Реестр ФНС (100% ИНН, качает 2 ГБ)"); self.cb_reg.setChecked(True)
        self.cb_pw = QCheckBox("Playwright (JS-футеры)"); self.cb_pw.setChecked(True)
        self.cb_2g = QCheckBox("Рейтинг 2ГИС"); self.cb_2g.setChecked(True)
        self.cb_rkn = QCheckBox("РКН — контакты отв. за ПД"); self.cb_rkn.setChecked(True)
        rl1.addWidget(self.cb_reg); rl1.addWidget(self.cb_pw)
        rl2.addWidget(self.cb_2g); rl2.addWidget(self.cb_rkn)
        lc_l.addLayout(rl1); lc_l.addLayout(rl2)
        left.addWidget(gc_l)

        # карточка: ключи
        gc_k, lc_k = self._card("API ключи")
        self.k_xmlriver = QTextEdit(); self.k_xmlriver.setPlaceholderText("user:key — XMLRiver Яндекс")
        self.k_xmlriver.setMaximumHeight(56)
        self.k_dadata = QTextEdit(); self.k_dadata.setPlaceholderText("токен DaData"); self.k_dadata.setMaximumHeight(56)
        self.k_twogis = QTextEdit(); self.k_twogis.setPlaceholderText("ключ 2ГИС"); self.k_twogis.setMaximumHeight(56)
        rk = QHBoxLayout()
        for lbl, w in [("XMLRiver", self.k_xmlriver), ("DaData", self.k_dadata), ("2ГИС", self.k_twogis)]:
            kv = QVBoxLayout()
            kv.addWidget(QLabel(lbl))
            kv.addWidget(w)
            rk.addLayout(kv)
        lc_k.addLayout(rk)
        left.addWidget(gc_k)

        left.addStretch()
        # вставляем левую панель в тело
        lw = QWidget(); lw.setLayout(left); lw.setMaximumWidth(640)
        body.addWidget(lw)

        # ── правая панель: кнопки + прогресс + лог ──
        right = QVBoxLayout()
        right.setSpacing(10)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("Начать сбор")
        self.start_btn.setObjectName("primary"); self.start_btn.clicked.connect(self._start)
        btns.addWidget(self.start_btn)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setObjectName("danger"); self.stop_btn.setEnabled(False); self.stop_btn.clicked.connect(self._stop)
        btns.addWidget(self.stop_btn)
        btns.addStretch()
        save_btn = QPushButton("Сохранить настройки"); save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        right.addLayout(btns)

        self.bar = QProgressBar()
        self.bar.setValue(0); self.bar.setMaximumHeight(8)
        self.bar.setTextVisible(False)
        right.addWidget(self.bar)

        right.addWidget(QLabel("Лог"))
        self.logbox = QTextEdit(); self.logbox.setReadOnly(True)
        right.addWidget(self.logbox, 1)

        body.addLayout(right, 1)
        outer.addLayout(body, 1)

    def _keys(self, te):
        return [x.strip() for x in te.toPlainText().splitlines() if x.strip()]

    def _start(self):
        xr = self._keys(self.k_xmlriver)
        if not xr or ":" not in xr[0]:
            QMessageBox.warning(self, "Ошибка", "Нужен ключ XMLRiver в формате user:key"); return
        u, k = xr[0].split(":", 1)
        # парсим "Москва:100, Санкт-Петербург:50" → [{name, limit}]
        cities = []
        for part in self.cities.text().split(","):
            part = part.strip()
            if not part: continue
            if ":" in part:
                nm, lim = part.rsplit(":", 1)
                try: cities.append({"name": nm.strip(), "limit": int(lim.strip())})
                except ValueError: cities.append({"name": part, "limit": self.limit.value()})
            else:
                cities.append({"name": part, "limit": self.limit.value()})
        if not cities or not self.biz.text().strip():
            QMessageBox.warning(self, "Ошибка", "Укажите тип бизнеса и хотя бы один город"); return
        cfg = {
            "business": self.biz.text().strip(),
            "okved_prefix": self.okved.text().strip() or "86.23",
            "cities": cities,
            "xr_user": u.strip(), "xr_key": k.strip(),
            "dadata": (self._keys(self.k_dadata) or [""])[0],
            "twogis": (self._keys(self.k_twogis) or [""])[0] if self.cb_2g.isChecked() else "",
            "registry": self.cb_reg.isChecked(),
            "playwright": self.cb_pw.isChecked(),
            "rkn": self.cb_rkn.isChecked(),
            "target": self.limit.value(), "max_pages": 20,
            "synonyms": ["стоматологическая клиника", "стоматолог"],
        }
        self.logbox.clear(); self.bar.setValue(0)
        self.stat.setText("Идёт сбор...")
        self.start_btn.setEnabled(False); self.stop_btn.setEnabled(True)
        self.worker = Worker(cfg)
        self.worker.log_s.connect(self._log)
        self.worker.prog_s.connect(self._prog)
        self.worker.done_s.connect(self._done)
        self.worker.fail_s.connect(self._fail)
        self.worker.start()

    def _stop(self):
        if self.worker: self.worker.stop(); self.stop_btn.setEnabled(False); self._log("Останавливаю...")

    def _log(self, m):
        self.logbox.append(m)
        sb = self.logbox.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _prog(self, a, b):
        if b: self.bar.setValue(min(100, int(a * 100 / b)))

    def _done(self, path, n):
        self.start_btn.setEnabled(True); self.stop_btn.setEnabled(False); self.bar.setValue(100)
        self.stat.setText(f"Готово: {n} записей")
        QMessageBox.information(self, "Готово", f"Собрано: {n}\nФайл: {path}")

    def _fail(self, e):
        self.start_btn.setEnabled(True); self.stop_btn.setEnabled(False)
        self.stat.setText("Ошибка")
        QMessageBox.critical(self, "Ошибка", e)

    def _save(self):
        d = {"business": self.biz.text(), "okved": self.okved.text(), "cities": self.cities.text(),
             "limit": self.limit.value(), "xmlriver": self.k_xmlriver.toPlainText(),
             "dadata": self.k_dadata.toPlainText(), "twogis": self.k_twogis.toPlainText(),
             "registry": self.cb_reg.isChecked(), "pw": self.cb_pw.isChecked(),
             "g2": self.cb_2g.isChecked(), "rkn": self.cb_rkn.isChecked()}
        json.dump(d, open(CONFIG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        QMessageBox.information(self, "OK", "Настройки сохранены")

    def _load(self):
        if os.path.exists("config_serp.json") and not os.path.exists(CONFIG):
            try:
                c = json.load(open("config_serp.json", encoding="utf-8"))
                self.k_xmlriver.setPlainText(c.get("xmlriver_keys", ""))
                self.k_dadata.setPlainText(c.get("dadata_keys", ""))
                self.k_twogis.setPlainText(c.get("twogis_keys", ""))
            except Exception:
                pass
        if os.path.exists(CONFIG):
            try:
                d = json.load(open(CONFIG, encoding="utf-8"))
                for attr, key, default in [
                    (self.biz, "business", "стоматология"), (self.okved, "okved", "86.23"),
                    (self.cities, "cities", "Москва"), (self.limit, "limit", 150),
                ]:
                    attr.setText(d.get(key, default)) if hasattr(attr, "setText") else attr.setValue(d.get(key, default))
                self.k_xmlriver.setPlainText(d.get("xmlriver", ""))
                self.k_dadata.setPlainText(d.get("dadata", ""))
                self.k_twogis.setPlainText(d.get("twogis", ""))
                self.cb_reg.setChecked(d.get("registry", True))
                self.cb_pw.setChecked(d.get("pw", True))
                self.cb_2g.setChecked(d.get("g2", True))
                self.cb_rkn.setChecked(d.get("rkn", True))
            except Exception:
                pass


def selftest():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    try:
        import release_core
        print("SELFTEST core import: OK")
    except Exception as e:
        print("SELFTEST core import: FAIL", repr(e)); return
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); b.new_page().goto("about:blank")
            print("SELFTEST chromium launch: OK"); b.close()
    except Exception as e:
        print("SELFTEST chromium launch: FAIL", repr(e))


def main():
    if "--selftest" in sys.argv:
        selftest(); return
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    w = Main(); w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
