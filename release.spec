# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
# только playwright нужен collect_all (ради встроенного chromium); остальное — обычные импорты
d, b, h = collect_all("playwright")
datas += d; binaries += b; hiddenimports += h

# тяжёлые ML/data библиотеки из окружения, которые мы НЕ используем — исключаем,
# иначе PyInstaller пытается их анализировать и падает (onnx.reference нативный краш)
EXCLUDES = [
    "torch", "torchvision", "torchaudio", "onnx", "onnxruntime", "tensorflow",
    "tensorboard", "transformers", "sklearn", "scikit-learn", "scipy", "pandas",
    "matplotlib", "cv2", "numpy", "numba", "sympy", "IPython", "notebook",
    "jupyter", "tornado", "zmq", "PIL",
]

# наши модули
for m in ("release_core.py", "twogis_enricher.py", "transliterate.py", "name_matcher.py", "rkn_enricher.py"):
    if os.path.exists(m):
        datas.append((m, "."))

hiddenimports += [
    "release_core", "twogis_enricher", "transliterate", "name_matcher", "rkn_enricher",
    "PyQt5", "PyQt5.QtCore", "PyQt5.QtGui", "PyQt5.QtWidgets",
    "requests", "openpyxl", "openpyxl.styles", "openpyxl.utils", "pypdf",
    "playwright", "playwright.sync_api",
    "xml.etree.ElementTree", "concurrent.futures", "zipfile", "json", "re", "time",
]

a = Analysis(
    ["gui_release.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BusinessCollectorPro",
    debug=False,
    strip=False,
    upx=False,
    console=True,            # консоль для отладки первого билда
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="BusinessCollectorPro",
)
