# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, get_package_paths

datas = [
    ('../src/vlt/ui/qml', 'ui/qml'),
    ('../assets', 'assets'),
    ('../LICENSE.txt', '.'),
    ('../THIRD_PARTY_NOTICES.txt', '.'),
]
binaries = []
hiddenimports = ['PySide6.QtNetwork', 'PySide6.QtWidgets', 'vlt.audio.native.process_loopback']

for package in ('faster_whisper', 'sherpa_onnx', 'opencc'):
    datas += collect_data_files(package)
for package in ('ctranslate2', 'sherpa_onnx'):
    binaries += collect_dynamic_libs(package)

pyside_root = Path(get_package_paths('PySide6')[1])
for qml_module in ('QtQuick', 'QtQml'):
    datas.append((str(pyside_root / 'qml' / qml_module), f'PySide6/qml/{qml_module}'))
datas += collect_data_files('PySide6', includes=['Qt/translations/qtbase_*.qm'])

analysis = Analysis(
    ['../src/vlt/app.py'], pathex=['../src'], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[str(Path(SPECPATH) / 'hooks')], hooksconfig={}, runtime_hooks=[],
    excludes=['torch', 'tensorflow', 'matplotlib', 'IPython', 'notebook', 'pytest', '_pytest', 'PIL'], noarchive=False)
# The build host PATH exposes Conda ICU 78 DLLs. Qt 6 links the Windows ICU ABI
# with unsuffixed symbols, so bundling those Conda DLLs makes QtCore fail at startup.
analysis.binaries = [entry for entry in analysis.binaries
                     if Path(entry[0]).name.lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
          name='VtuberLiveTranslator', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=True, console=False, icon='../assets/app.ico',
          version='version_info.txt')
coll = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=True,
               name='VtuberLiveTranslator')
