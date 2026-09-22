from PyInstaller.utils.hooks.qt import add_qt6_dependencies

# The stock hook copies every installed QML module, including 200+ MB WebEngine.
# The spec explicitly includes only the Qt Quick modules used by this product.
hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

