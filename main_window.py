from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QMainWindow, QAction   # ← 关键修改
from i18n import tr

VERSION = "1.0.0"

class MainWindow(QMainWindow):
    MSG_DURATION = 5000

    def __init__(self, widget, app):
        QMainWindow.__init__(self)
        self.app = app
        self.widget = widget
        self.current_lang = 'en'
        self.setCentralWidget(widget)

        self.menu = self.menuBar()

        self.file_menu = self.menu.addMenu('File')
        self.exit_action = QAction('Exit', self)
        self.exit_action.setShortcut(QKeySequence.Quit)
        self.exit_action.triggered.connect(self.end_window)
        self.file_menu.addAction(self.exit_action)

        self.lang_menu = self.menu.addMenu('Language')
        self.lang_en = QAction('English', self, checkable=True)
        self.lang_zh = QAction('中文', self, checkable=True)
        self.lang_en.setChecked(True)
        self.lang_en.triggered.connect(lambda: self.set_language('en'))
        self.lang_zh.triggered.connect(lambda: self.set_language('zh'))
        self.lang_menu.addAction(self.lang_en)
        self.lang_menu.addAction(self.lang_zh)

        self.status = self.statusBar()
        self.retranslate()

    def retranslate(self):
        lang = self.current_lang
        base_title = tr('USB-Camera', lang)
        self.setWindowTitle(f"{base_title} v{VERSION}")
        self.file_menu.setTitle(tr('File', lang))
        self.exit_action.setText(tr('Exit', lang))
        self.lang_menu.setTitle(tr('Language', lang))
        self.lang_en.setText(tr('English', lang))
        self.lang_zh.setText(tr('中文', lang))
        self.lang_en.setChecked(lang == 'en')
        self.lang_zh.setChecked(lang == 'zh')

    def set_language(self, lang):
        if lang == self.current_lang:
            return
        self.current_lang = lang
        self.widget.set_language(lang)
        self.retranslate()

    def show_message(self, msg):
        self.status.showMessage(msg, self.MSG_DURATION)
        self.app.processEvents()

    def end_window(self):
        self.widget.end_widget()
        self.close()
