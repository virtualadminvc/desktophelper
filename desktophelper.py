import sys
import os
import json
import subprocess
import re
import time
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QSystemTrayIcon, QMenu, QMessageBox,
    QLabel, QSlider, QMainWindow, QSpinBox,
    QFrame, QColorDialog
)
from PyQt6.QtCore import Qt, QTimer, QRect, QSharedMemory
from PyQt6.QtGui import (
    QFont, QColor, QPainter, QBrush, QPen, QIcon, QPixmap,
    QTextDocument, QAction
)

# ================== 配置管理 ==================
CONFIG_DIR = Path(os.environ.get('APPDATA', '.')) / 'DesktopReminder'
CONFIG_FILE = CONFIG_DIR / 'config.json'
TIMER_DATA_FILE = CONFIG_DIR / 'timer_start.txt'
OLD_TIMER_FILE = Path.home() / '.my_timer_start.txt'
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_CONFIG = {
    "text": "📌 待办事项\n• 写周报\n• 下午3点开会\n• 记得取快递",
    "unified_geometry": [800, 300, 240, 350],
    "editor_geometry": [100, 100, 700, 600],
    "auto_start": False,
    "bg_color": "#000000",
    "bg_opacity": 180,
    "timer_text_color": "#FFFFFF",
    "timer_font_size": 14,
    "timer_font_family": "Consolas, Microsoft YaHei, monospace",
    "text_color": "#FFFFFF",
    "font_size": 12,
    "font_family": "SimSun, Times New Roman, serif"
}

def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                if k not in data:
                    data[k] = v
            return data
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def get_timer_start_time():
    if OLD_TIMER_FILE.exists() and not TIMER_DATA_FILE.exists():
        try:
            with open(OLD_TIMER_FILE, 'r') as f:
                ts = float(f.read().strip())
            with open(TIMER_DATA_FILE, 'w') as f:
                f.write(str(ts))
            OLD_TIMER_FILE.rename(OLD_TIMER_FILE.with_suffix('.bak'))
        except:
            pass
    if TIMER_DATA_FILE.exists():
        with open(TIMER_DATA_FILE, 'r') as f:
            return float(f.read().strip())
    else:
        now = time.time()
        with open(TIMER_DATA_FILE, 'w') as f:
            f.write(str(now))
        return now

def format_seconds(seconds):
    return f"{int(seconds):,} 秒"

# ================== 桌面显示窗口 ==================
class UnifiedDisplayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.start_ts = get_timer_start_time()
        self.drag_pos = None
        self.resizing = False
        self.resize_edge = None
        self.init_ui()
        self.apply_style()
        self.update_text(self.config["text"])
        self.load_geometry()

        self.timer_update = QTimer(self)
        self.timer_update.timeout.connect(self.update_timer_display)
        self.timer_update.start(1000)

        self.resize_timer = QTimer()
        self.resize_timer.setSingleShot(True)
        self.resize_timer.timeout.connect(self.adjust_window_height)

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.container = QWidget()
        self.container.setObjectName("container")
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        top_bar = QHBoxLayout()
        top_bar.addStretch()
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(24, 24)
        self.min_btn.setToolTip("最小化到托盘")
        self.min_btn.clicked.connect(self.hide_window)
        self.min_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self.min_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(100,100,100,180);
                border: none;
                border-radius: 12px;
                font-weight: bold;
                font-size: 16px;
                color: white;
            }
            QPushButton:hover {
                background-color: rgba(150,150,150,200);
            }
        """)
        top_bar.addWidget(self.min_btn)
        layout.addLayout(top_bar)

        self.timer_label = QLabel()
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.timer_label.setMaximumHeight(30)
        layout.addWidget(self.timer_label)

        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.Shape.HLine)
        self.separator.setStyleSheet("background-color: rgba(255,255,255,80); border: none; max-height: 1px;")
        layout.addWidget(self.separator)

        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(self.text_label)

        self.setMinimumSize(160, 140)

    def moveEvent(self, event):
        super().moveEvent(event)
        # 实时更新配置里的坐标，但不一定要立刻写磁盘（减少IO）
        self.config["unified_geometry"] = [self.x(), self.y(), self.width(), self.height()]

    def save_geometry(self):
        # 确保保存的是当前最新的坐标
        self.config["unified_geometry"] = [self.x(), self.y(), self.width(), self.height()]
        save_config(self.config)
    def apply_style(self):
        bg_color = self.config['bg_color']
        bg_opacity = self.config['bg_opacity']
        bg_rgba = f"rgba({int(bg_color[1:3],16)}, {int(bg_color[3:5],16)}, {int(bg_color[5:7],16)}, {bg_opacity/255})"
        self.container.setStyleSheet(f"""
            QWidget#container {{
                background-color: {bg_rgba};
                border-radius: 12px;
            }}
        """)
        timer_color = self.config['timer_text_color']
        timer_font_size = self.config['timer_font_size']
        timer_font_family = self.config['timer_font_family']
        self.timer_label.setStyleSheet(f"""
            QLabel {{
                color: {timer_color};
                font-size: {timer_font_size}px;
                font-family: "{timer_font_family}";
                font-weight: bold;
                padding: 0px;
            }}
        """)
        text_color = self.config['text_color']
        text_font_size = self.config['font_size']
        text_font_family = self.config['font_family']
        self.text_label.setStyleSheet(f"""
            QLabel {{
                color: {text_color};
                font-size: {text_font_size}px;
                font-family: "{text_font_family}";
                padding: 2px;
            }}
        """)

    def update_timer_display(self):
        elapsed = time.time() - self.start_ts
        self.timer_label.setText(format_seconds(elapsed))

    def update_text(self, text):
        html = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        html = html.replace('\n', '<br>')
        html = re.sub(r'^([•\-*])\s+(.*)$', r' <span style="color:#FFD966;">\1</span> \2', html, flags=re.MULTILINE)
        self.text_label.setText(f'<div style="line-height:1.4;">{html}</div>')
        self.adjust_window_height()

    def adjust_window_height(self):
        if self.resizing:
            return
        available_width = self.container.width() - 24
        if available_width <= 0:
            available_width = 200
        doc = QTextDocument()
        doc.setHtml(self.text_label.text())
        font = QFont(self.config['font_family'])
        font.setPointSize(self.config['font_size'])
        doc.setDefaultFont(font)
        doc.setTextWidth(available_width)
        text_height = doc.size().height()

        timer_height = self.timer_label.sizeHint().height()
        sep_height = self.separator.sizeHint().height()
        top_bar_height = self.min_btn.height() + 12
        margins = 20
        total_height = top_bar_height + timer_height + sep_height + text_height + margins

        screen = QApplication.primaryScreen().availableGeometry()
        max_height = int(screen.height() * 0.8)
        new_height = min(int(total_height), max_height)
        new_height = max(self.minimumHeight(), new_height)

        if new_height != self.height():
            self.resize(self.width(), new_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.resizing:
            self.resize_timer.start(100)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(50, self.adjust_window_height)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.pos())
            if child == self.min_btn or self.min_btn.isAncestorOf(child):
                event.ignore()
                return
            edge = self.get_edge(event.pos())
            if edge:
                self.resizing = True
                self.resize_edge = edge
                self.drag_pos = event.globalPosition().toPoint()
                event.accept()
                return
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self.resizing:
            edge = self.get_edge(event.pos())
            if edge:
                self.setCursor(self.get_cursor_for_edge(edge))
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

        if self.resizing and self.resize_edge:
            global_pos = event.globalPosition().toPoint()
            delta = global_pos - self.drag_pos
            new_rect = self.frameGeometry()
            if 'left' in self.resize_edge:
                new_rect.setLeft(new_rect.left() + delta.x())
            if 'right' in self.resize_edge:
                new_rect.setRight(new_rect.right() + delta.x())
            if 'top' in self.resize_edge:
                new_rect.setTop(new_rect.top() + delta.y())
            if 'bottom' in self.resize_edge:
                new_rect.setBottom(new_rect.bottom() + delta.y())
            if new_rect.width() < self.minimumWidth():
                if 'left' in self.resize_edge:
                    new_rect.setLeft(new_rect.right() - self.minimumWidth())
                else:
                    new_rect.setRight(new_rect.left() + self.minimumWidth())
            if new_rect.height() < self.minimumHeight():
                if 'top' in self.resize_edge:
                    new_rect.setTop(new_rect.bottom() - self.minimumHeight())
                else:
                    new_rect.setBottom(new_rect.top() + self.minimumHeight())
            self.setGeometry(new_rect)
            self.drag_pos = global_pos
            event.accept()
            return

        if self.drag_pos is not None and not self.resizing:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.resizing:
                self.resizing = False
                self.resize_edge = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.save_geometry()
                self.adjust_window_height()
                event.accept()
            elif self.drag_pos is not None:
                self.drag_pos = None
                self.save_geometry()
                event.accept()

    def get_edge(self, pos):
        margin = 8
        rect = self.rect()
        x, y = pos.x(), pos.y()
        on_left = x <= margin
        on_right = x >= rect.width() - margin
        on_top = y <= margin
        on_bottom = y >= rect.height() - margin
        if on_top and on_left: return 'top-left'
        if on_top and on_right: return 'top-right'
        if on_bottom and on_left: return 'bottom-left'
        if on_bottom and on_right: return 'bottom-right'
        if on_top: return 'top'
        if on_bottom: return 'bottom'
        if on_left: return 'left'
        if on_right: return 'right'
        return None

    def get_cursor_for_edge(self, edge):
        mapping = {
            'top': Qt.CursorShape.SizeVerCursor,
            'bottom': Qt.CursorShape.SizeVerCursor,
            'left': Qt.CursorShape.SizeHorCursor,
            'right': Qt.CursorShape.SizeHorCursor,
            'top-left': Qt.CursorShape.SizeFDiagCursor,
            'top-right': Qt.CursorShape.SizeBDiagCursor,
            'bottom-left': Qt.CursorShape.SizeBDiagCursor,
            'bottom-right': Qt.CursorShape.SizeFDiagCursor,
        }
        return mapping.get(edge, Qt.CursorShape.ArrowCursor)

    def closeEvent(self, event):
        self.hide()
        event.ignore()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    def hide_window(self):
        self.hide()

    def save_geometry(self):
        self.config["unified_geometry"] = [self.x(), self.y(), self.width(), self.height()]
        save_config(self.config)

    def load_geometry(self):
        geom = self.config.get("unified_geometry")
        if geom and len(geom) == 4:
            # 关键：先取消掉可能的自动调整，直接设置绝对坐标
            x, y, w, h = geom
            self.move(x, y)
            self.resize(w, h)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.setGeometry(screen.width() - 260, 100, 240, 350)

    def refresh_style(self):
        self.apply_style()
        self.update_text(self.config["text"])
        self.update_timer_display()
        self.adjust_window_height()


# ================== 编辑窗口 ==================
class EditorWindow(QMainWindow):
    def __init__(self, display_window):
        super().__init__()
        self.display = display_window
        self.config = load_config()
        self.init_ui()
        self.load_geometry()

    def init_ui(self):
        self.setWindowTitle("桌面提醒 + 计时器 - 编辑设置")
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        layout.addWidget(QLabel("📝 桌面提醒内容："))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(self.config["text"])
        self.text_edit.setFont(QFont("微软雅黑", 10))
        layout.addWidget(self.text_edit)

        bg_group = QWidget()
        bg_layout = QHBoxLayout(bg_group)
        bg_layout.setContentsMargins(0, 0, 0, 0)

        self.bg_color_btn = QPushButton("窗口背景颜色")
        self.bg_color_btn.clicked.connect(lambda: self.choose_color('bg_color'))
        bg_layout.addWidget(self.bg_color_btn)

        bg_layout.addWidget(QLabel("背景透明度"))
        self.bg_opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.bg_opacity_slider.setRange(0, 255)
        self.bg_opacity_slider.setValue(self.config["bg_opacity"])
        self.bg_opacity_slider.valueChanged.connect(lambda v: self.update_style('bg_opacity', v))
        bg_layout.addWidget(self.bg_opacity_slider)

        layout.addWidget(QLabel("🎨 窗口外观（背景颜色和透明度）"))
        layout.addWidget(bg_group)

        timer_group = QWidget()
        timer_layout = QHBoxLayout(timer_group)
        timer_layout.setContentsMargins(0, 0, 0, 0)

        self.timer_color_btn = QPushButton("计时器文字颜色")
        self.timer_color_btn.clicked.connect(lambda: self.choose_color('timer_text_color'))
        timer_layout.addWidget(self.timer_color_btn)

        timer_layout.addWidget(QLabel("计时器字体大小"))
        self.timer_font_spin = QSpinBox()
        self.timer_font_spin.setRange(10, 48)
        self.timer_font_spin.setValue(self.config["timer_font_size"])
        self.timer_font_spin.valueChanged.connect(lambda v: self.update_style('timer_font_size', v))
        timer_layout.addWidget(self.timer_font_spin)

        layout.addWidget(QLabel("⏱️ 计时器样式（文字颜色和大小）"))
        layout.addWidget(timer_group)

        text_group = QWidget()
        text_layout = QHBoxLayout(text_group)
        text_layout.setContentsMargins(0, 0, 0, 0)

        self.text_color_btn = QPushButton("提醒文字颜色")
        self.text_color_btn.clicked.connect(lambda: self.choose_color('text_color'))
        text_layout.addWidget(self.text_color_btn)

        text_layout.addWidget(QLabel("提醒字体大小"))
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 30)
        self.font_spin.setValue(self.config["font_size"])
        self.font_spin.valueChanged.connect(lambda v: self.update_style('font_size', v))
        text_layout.addWidget(self.font_spin)

        layout.addWidget(QLabel("📝 提醒文本样式（文字颜色和大小）"))
        layout.addWidget(text_group)

        btn_layout = QHBoxLayout()
        self.sync_btn = QPushButton("立即同步到桌面")
        self.sync_btn.clicked.connect(self.sync_to_display)
        btn_layout.addWidget(self.sync_btn)

        self.hide_btn = QPushButton("隐藏桌面窗口")
        self.hide_btn.clicked.connect(self.display.hide_window)
        btn_layout.addWidget(self.hide_btn)

        self.show_btn = QPushButton("显示桌面窗口")
        self.show_btn.clicked.connect(self.display.show)
        btn_layout.addWidget(self.show_btn)

        layout.addLayout(btn_layout)

        hint = QLabel("提示：\n"
                      "• 编辑提醒内容后点击「立即同步到桌面」即可更新（无弹窗）。\n"
                      "• 桌面窗口可拖拽边缘调整大小，内容自动换行，无滚动条。\n"
                      "• 背景颜色和透明度统一控制整个窗口。\n"
                      "• 计时器和提醒文本的字体大小可分别调节，调节流畅不卡顿。\n"
                      "• 右上角「—」按钮最小化到托盘，右键托盘图标可显示/隐藏窗口、开关开机自启、退出程序。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 9pt; padding: 8px;")
        layout.addWidget(hint)

    def sync_to_display(self):
        new_text = self.text_edit.toPlainText()
        self.config["text"] = new_text
        self.display.config["text"] = new_text
        self.display.update_text(new_text)
        save_config(self.config)

    def choose_color(self, key):
        color = QColorDialog.getColor(QColor(self.config[key]), self, f"选择{key}")
        if color.isValid():
            self.config[key] = color.name()
            self.display.config[key] = color.name()
            self.display.refresh_style()
            save_config(self.config)

    def update_style(self, key, value):
        self.config[key] = value
        self.display.config[key] = value
        if key in ('font_size', 'text_color', 'font_family'):
            self.display.update_text(self.display.config['text'])
        elif key == 'timer_font_size':
            self.display.apply_style()
            self.display.adjust_window_height()
        else:
            self.display.refresh_style()
        save_config(self.config)

    def load_geometry(self):
        geom = self.config.get("editor_geometry")
        if geom and len(geom) == 4:
            self.setGeometry(*geom)
        else:
            # 使用 DEFAULT_CONFIG 中的宽高（700x600）
            self.resize(700, 600)

    def closeEvent(self, event):
        self.config["editor_geometry"] = [self.x(), self.y(), self.width(), self.height()]
        save_config(self.config)
        self.hide()
        event.ignore()
        # 确保应用不会退出
        QApplication.instance().setQuitOnLastWindowClosed(False)


# ================== 系统托盘管理 ==================
# ================== 系统托盘管理 ==================
class TrayManager:
    def __init__(self, app, editor, display):
        self.app = app
        self.editor = editor
        self.display = display
        # 初始化托盘
        self.tray = QSystemTrayIcon(self.display)
        self.setup_tray()



    def setup_tray(self):
        def resource_path(relative_path):
            try:
                base_path = sys._MEIPASS
            except AttributeError:
                base_path = os.path.abspath(".")
            return os.path.join(base_path, relative_path)
        icon_path = resource_path("myicon.ico")
        if os.path.exists(icon_path):
            icon = QIcon(icon_path)
        else:
            # 如果文件不存在，回退到默认图标（深色方块）
            icon = QIcon()
            pix = QPixmap(64, 64)
            pix.fill(QColor("#2C3E50"))
            icon.addPixmap(pix)
        self.tray.setIcon(icon)
        self.tray.setToolTip("桌面提醒计时器")

        # 2. 创建菜单并设为成员变量，防止被析构
        self.menu = QMenu()

        # 3. 创建各项动作，并明确指定父对象为 self.menu
        self.act_edit = QAction("✏️ 显示编辑窗口", self.menu)
        self.act_edit.triggered.connect(self.editor.show)

        self.act_display = QAction("🖥️ 显示桌面窗口", self.menu)
        self.act_display.triggered.connect(self.display.show)

        self.act_sync = QAction("🔄 立即同步内容", self.menu)
        self.act_sync.triggered.connect(self.sync_now)

        self.auto_action = QAction("🔁 开机自启", self.menu)
        self.auto_action.setCheckable(True)
        self.auto_action.setChecked(is_auto_start_enabled())
        self.auto_action.triggered.connect(self.toggle_auto_start)

        self.act_quit = QAction("❌ 退出程序", self.menu)
        self.act_quit.triggered.connect(self.quit_app)

        # 4. 将动作添加到菜单
        self.menu.addAction(self.act_edit)
        self.menu.addAction(self.act_display)
        self.menu.addAction(self.act_sync)
        self.menu.addSeparator()
        self.menu.addAction(self.auto_action)
        self.menu.addSeparator()
        self.menu.addAction(self.act_quit)

        # 5. 关联菜单并显示
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self.on_tray_click)
        self.tray.show()

    def sync_now(self):
        """同步编辑框内容到桌面窗口"""
        new_text = self.editor.text_edit.toPlainText()
        self.editor.config["text"] = new_text
        self.display.config["text"] = new_text
        self.display.update_text(new_text)
        save_config(self.editor.config)

    def toggle_auto_start(self, checked):
        """处理自启逻辑"""
        if set_auto_start(checked):
            self.editor.config["auto_start"] = checked
            save_config(self.editor.config)
        else:
            QMessageBox.warning(None, "错误", "设置开机自启失败，请检查权限")
            self.auto_action.setChecked(not checked)

    def quit_app(self):
        """安全退出"""
        # 退出前最后保存一次位置和配置
        self.editor.config["editor_geometry"] = [self.editor.x(), self.editor.y(), self.editor.width(),
                                                 self.editor.height()]
        self.display.config["unified_geometry"] = [self.display.x(), self.display.y(), self.display.width(),
                                                   self.display.height()]
        save_config(self.editor.config)

        self.tray.hide()  # 隐藏托盘图标，避免图标残留
        self.app.quit()

    def on_tray_click(self, reason):
        """点击图标的反馈"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.editor.isHidden():
                self.editor.show()
            else:
                self.editor.raise_()
                self.editor.activateWindow()

def set_auto_start(enabled):
    if getattr(sys, 'frozen', False):
        app_path = sys.executable
    else:
        app_path = sys.argv[0]
    startup_dir = Path(os.environ.get('APPDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'
    shortcut_path = startup_dir / 'DesktopReminder.lnk'
    if enabled:
        # 强制删除旧的快捷方式（如果存在）
        if shortcut_path.exists():
            try:
                shortcut_path.unlink()
            except:
                pass
        # 创建新的快捷方式
        ps_cmd = f'''
        $WScriptShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WScriptShell.CreateShortcut("{shortcut_path}")
        $Shortcut.TargetPath = "{app_path}"
        $Shortcut.WorkingDirectory = "{Path(app_path).parent}"
        $Shortcut.Save()
        '''
        try:
            subprocess.run(['powershell', '-Command', ps_cmd], check=True, capture_output=True)
            return True
        except:
            return False
    else:
        if shortcut_path.exists():
            try:
                shortcut_path.unlink()
                return True
            except:
                return False
    return False

def is_auto_start_enabled():
    startup_dir = Path(os.environ.get('APPDATA', '')) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup'
    shortcut_path = startup_dir / 'DesktopReminder.lnk'
    return shortcut_path.exists()

# ================== 单实例检查（使用 QSharedMemory，更可靠） ==================
def check_single_instance():
    shared_mem = QSharedMemory("DesktopReminder_UniqueKey")
    if shared_mem.attach():
        # 已有实例运行
        return False
    shared_mem.create(1)
    return True


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not check_single_instance():
        return

    display = UnifiedDisplayWindow()
    editor = EditorWindow(display)

    # 将托盘管理器绑定到 app，防止被垃圾回收
    app.tray_manager = TrayManager(app, editor, display)

    display.show()
    display.load_geometry()
    editor.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()