import sys
import os
import shutil
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QTabWidget, QListWidget, QListWidgetItem,
                               QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QFormLayout,
                               QLineEdit, QTextEdit, QMessageBox, QGroupBox, QDialog,
                               QTreeWidget, QTreeWidgetItem)
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtCore import Qt, QProcess, QUrl, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtNetwork import QLocalServer, QLocalSocket
def get_base_dir():
    """获取程序所在的绝对根目录（兼容打包和源码运行）"""
    if getattr(sys, 'frozen', False):
        # 如果被打包成了 exe，返回 exe 所在的目录
        return os.path.dirname(sys.executable)
    else:
        # 如果是源码运行，返回当前脚本所在目录
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
os.chdir(BASE_DIR) # 👈 新增：强制把工作目录锁定在程序根目录
# 🎯 修复 1：拦截无控制台模式下的 print 编码崩溃
class SafeStream:
    def __init__(self, original_stream):
        self.original_stream = original_stream
    def write(self, text):
        if self.original_stream:
            try:
                safe_text = text.encode('gbk', errors='ignore').decode('gbk')
                self.original_stream.write(safe_text)
                self.original_stream.flush() # 👈 核心修复：强制立刻冲刷输出
            except Exception:
                pass
    def flush(self):
        if self.original_stream:
            try: self.original_stream.flush()
            except Exception: pass
sys.stdout = SafeStream(sys.stdout)
sys.stderr = SafeStream(sys.stderr)
# 屏蔽 Chromium 报错
PREF_FILE = "preference.txt"
CHAR_DIR = "characters"


# ================= 独立弹窗：查看语音与动作 =================
class DetailDialog(QDialog):
    def __init__(self, char_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{char_name} - 语音与动作详情")
        self.resize(500, 600)
        self.char_dir = os.path.join(CHAR_DIR, char_name)

        # 音频播放器
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(0.8)

        layout = QVBoxLayout(self)

        # 树状列表
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["类别 / 文件", "操作"])
        layout.addWidget(self.tree)

        # 播放控制
        self.lbl_playing = QLabel("未播放任何音频")
        self.lbl_playing.setStyleSheet("color: #00FF00;")
        layout.addWidget(self.lbl_playing)

        self.load_details()
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)

    def load_details(self):
        config_path = os.path.join(self.char_dir, "config.json")
        if not os.path.exists(config_path):
            return

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 1. 加载作战动作
        actions_root = QTreeWidgetItem(self.tree, ["作战动作", ""])
        action_sounds = config.get("action_sounds", {})
        for action, sounds in action_sounds.items():
            act_item = QTreeWidgetItem(actions_root, [action, ""])
            for snd in sounds:
                QTreeWidgetItem(act_item, [snd, "双击播放"])

        # 2. 加载闲聊
        chats_root = QTreeWidgetItem(self.tree, ["闲聊", ""])
        idle_chats = config.get("idle_chats", {})
        for time_key, sounds in idle_chats.items():
            time_item = QTreeWidgetItem(chats_root, [time_key, ""])
            for snd in sounds:
                QTreeWidgetItem(time_item, [snd, "双击播放"])

        self.tree.expandAll()

    def on_item_double_clicked(self, item, column):
        # 如果双击的是音频文件节点
        if item.parent() and item.text(1) == "双击播放":
            audio_file = item.text(0)
            audio_path = os.path.join(self.char_dir, "sounds", audio_file)
            if os.path.exists(audio_path):
                self.player.setSource(QUrl.fromLocalFile(os.path.abspath(audio_path)))
                self.player.play()
                self.lbl_playing.setText(f"正在播放: {audio_file}")
            else:
                self.lbl_playing.setText(f"❌ 找不到文件: {audio_file}")

# ================= 主面板 =================
class PanelWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # 🎯 核心：动态加载图标
        icon_path = os.path.join(BASE_DIR, "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            print("✅ 窗口图标加载成功")
        else:
            print("⚠️ 找不到图标文件 icon.png")
        self.setWindowTitle("重返未来 1999 - 桌宠控制面板")
        self.resize(800, 600)

        self.tabs = QTabWidget()

        # 🎯 新增：顶部布局，左边是启动按钮，右边是致谢按钮
        top_layout = QHBoxLayout()

        self.btn_launch = QPushButton("✨ 启动桌宠 ✨")
        self.btn_launch.setFixedHeight(50)
        self.btn_launch.setStyleSheet("background-color: #2E8B57; color: white; font-size: 18px; font-weight: bold;")
        self.btn_launch.clicked.connect(self.launch_pet)
        top_layout.addWidget(self.btn_launch)

        # 🎯 新增的关于按钮
        self.btn_about = QPushButton("ℹ️ 关于与致谢")
        self.btn_about.setFixedHeight(50)
        self.btn_about.setFixedWidth(120)
        self.btn_about.setStyleSheet("background-color: #444; color: white; font-size: 14px;")
        self.btn_about.clicked.connect(self.show_about_dialog)
        top_layout.addWidget(self.btn_about)

        # 把原来的 main_layout 改成加入 top_layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(top_layout)  # 👈 这里替换
        main_layout.addWidget(self.tabs)
        self.setCentralWidget(main_widget)

        self.init_character_tab()
        self.init_settings_tab()
        self.init_installer_tab()

        self.load_settings_to_ui()
        self.refresh_character_list()
        self.setStyleSheet("""
            QWidget { background-color: #2b2b2b; color: #eee; }
            QListWidget, QTreeWidget { background-color: #1e1e1e; border: 1px solid #444; }
            QListWidget::item:selected { background-color: #555; }
            QPushButton { background-color: #444; border: 1px solid #666; padding: 5px; border-radius: 3px; }
            QPushButton:hover { background-color: #555; }
            QTabBar::tab { background: #333; padding: 10px; }
            QTabBar::tab:selected { background: #555; }
        """)

        self.setup_ipc_server()  # 👈 启动本地通讯服务

    def setup_ipc_server(self):
        """监听来自桌宠进程的信号"""
        # 如果已经有一个实例在运行了，发个信号让它显示，然后自己退出
        socket = QLocalSocket()
        socket.connectToServer("Reverse1999PetPanel_IPC")
        if socket.waitForConnected(500):
            socket.write(b"SHOW")
            socket.flush()
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            sys.exit(0)  # 当前进程自杀，防止多开

        # 作为第一个实例，启动服务端
        self.server = QLocalServer(self)
        self.server.removeServer("Reverse1999PetPanel_IPC")  # 清理可能残留的僵尸服务
        self.server.listen("Reverse1999PetPanel_IPC")
        self.server.newConnection.connect(self.handle_ipc_connection)

    def handle_ipc_connection(self):
        """处理来自桌宠的指令"""
        client = self.server.nextPendingConnection()
        client.readyRead.connect(lambda: self.process_ipc_msg(client))

    def process_ipc_msg(self, client):
        data = client.readAll().data()
        if data == b"SHOW":
            self.showNormal()
            self.raise_()
            self.activateWindow()
        elif data == b"QUIT":
            self.quit_application()
        client.disconnectFromServer()

    def quit_application(self):
        """彻底退出程序"""
        QApplication.quit()

    def closeEvent(self, event):
        """拦截右上角的 X 按钮，智能判断是否彻底退出"""
        # 检查桌宠是否在运行状态
        if hasattr(self, 'pet_process') and self.pet_process and self.pet_process.state() == QProcess.Running:
            # 桌宠正在运行，拦截关闭，隐藏自己
            event.ignore()
            self.hide()
            # 可选：在右下角弹个提示（如果你没加过托盘，可以删掉这行）
            print("面板已缩回后台，可通过桌宠托盘唤出。")
        else:
            # 桌宠没运行，直接关闭整个程序
            event.accept()
            QApplication.quit()

    def show_about_dialog(self):
        about_text = """
        <h2>🦋 重返未来 1999 - 桌面宠物</h2>
        <p><b>制作人：</b> Micropuppy （GitHub主页：https://github.com/MicropuppyGoForward/）</p>
        <p><b>版本：</b> v1.2.4</p>

        <h3>💡 项目简介</h3>
        <p>这是一个基于 PySide6 + Playwright + Spine Runtimes 开发的开源同人桌宠项目。</p>
        <p>支持自动抓取资源、Live2D/Spine 动画渲染、智能技能盘交互、语音及智能字幕同步等功能。</p>

        <h3>🙏 特别致谢</h3>
        <ul>
            <li><b>游戏原厂：</b> 深蓝互动 (Bluepoch) 《重返未来：1999》</li>
            <li><b>数据资源支持：</b> UTTU 资料站 (uttu.merui.net)</li>
            <li><b>开源引擎：</b> PySide6, Pygame, Playwright, Spine Runtimes</li>
        </ul>

        <h3>⚠️ 免责声明</h3>
        <p style="color: #ff6b6b;"><b>本软件为个人学习与交流使用的非盈利同人作品，严禁用于任何商业用途。</b></p>
        <p>软件中涉及的所有游戏模型、语音、图片、文本等版权均归 <b>深蓝互动 (Bluepoch)</b> 所有。</p>
        <p>请于下载后 24 小时内删除，若喜欢本游戏，请支持官方正版。</p>
        """

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("关于与致谢")
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setText(about_text)

        # 🎯 核心修改：加载自定义 webp 图标
        icon_path = os.path.join(BASE_DIR, "about_icon.webp")  # 替换成你的图片文件名
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            # 建议缩放一下，因为 QMessageBox 左侧的图标区域比较小，太大的图会显示得很挤
            # 这里设为 128x128 像素，保持比例，平滑缩放
            pixmap = pixmap.scaled(404, 404, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            msg_box.setIconPixmap(pixmap)
        else:
            # 如果找不到图片，用系统默认的兜底
            msg_box.setIcon(QMessageBox.Information)
            print(f"⚠️ 找不到自定义图标: {icon_path}")

        # 设置一个好看点的样式
        msg_box.setStyleSheet("""
                    QMessageBox { background-color: #2b2b2b; }
                    QLabel { color: #eee; min-width: 500px; }
                """)
        msg_box.exec()
    # ================= 1. 角色库 =================
    def init_character_tab(self):
        self.tab_char = QWidget()
        layout = QHBoxLayout(self.tab_char)

        self.list_chars = QListWidget()
        self.list_chars.setFixedWidth(250)
        self.list_chars.currentItemChanged.connect(self.on_char_selected)
        layout.addWidget(self.list_chars)

        # 右侧布局
        detail_layout = QVBoxLayout()

        # 头像缩小为 150x150
        self.lbl_avatar = QLabel("请选择角色")
        self.lbl_avatar.setAlignment(Qt.AlignCenter)
        self.lbl_avatar.setFixedSize(150, 150)
        self.lbl_avatar.setStyleSheet("border: 1px solid #555; background: #222;")
        detail_layout.addWidget(self.lbl_avatar, alignment=Qt.AlignCenter)

        # 角色名称
        self.lbl_char_name = QLabel("未选择")
        self.lbl_char_name.setStyleSheet("font-size: 20px; font-weight: bold; color: white;")
        self.lbl_char_name.setAlignment(Qt.AlignCenter)
        detail_layout.addWidget(self.lbl_char_name)

        # 👇 新增：中间空出来的缩放调节区域
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(QLabel("模型缩放比例:"))
        self.spin_scale = QDoubleSpinBox()
        self.spin_scale.setRange(0.1, 2.0)
        self.spin_scale.setSingleStep(0.05)
        self.spin_scale.setEnabled(False)
        scale_layout.addWidget(self.spin_scale)

        self.btn_save_scale = QPushButton("保存缩放")
        self.btn_save_scale.clicked.connect(self.save_scale)
        self.btn_save_scale.setEnabled(False)
        scale_layout.addWidget(self.btn_save_scale)

        scale_container = QWidget()
        scale_container.setLayout(scale_layout)
        detail_layout.addWidget(scale_container)

        # 👇 新增：查看动作与语音
        self.btn_view_details = QPushButton("🔍 查看语音与动作")
        self.btn_view_details.clicked.connect(self.show_details)
        self.btn_view_details.setEnabled(False)
        detail_layout.addWidget(self.btn_view_details)

        detail_layout.addStretch()

        # 底部按钮
        btn_layout = QHBoxLayout()
        self.btn_set_default = QPushButton("设为默认启动")
        self.btn_set_default.clicked.connect(self.set_default_character)
        self.btn_set_default.setEnabled(False)

        self.btn_delete_char = QPushButton("删除角色")
        self.btn_delete_char.setStyleSheet("background-color: #8B0000; color: white;")
        self.btn_delete_char.clicked.connect(self.delete_character)
        self.btn_delete_char.setEnabled(False)

        btn_layout.addWidget(self.btn_set_default)
        btn_layout.addWidget(self.btn_delete_char)
        detail_layout.addLayout(btn_layout)

        layout.addLayout(detail_layout)
        self.tabs.addTab(self.tab_char, "📦 角色库")

    def refresh_character_list(self):
        self.list_chars.clear()
        if not os.path.exists(CHAR_DIR): return
        dirs = [d for d in os.listdir(CHAR_DIR) if os.path.isdir(os.path.join(CHAR_DIR, d))]
        for d in dirs:
            self.list_chars.addItem(QListWidgetItem(d))

    def on_char_selected(self, current, previous):
        if not current: return
        char_name = current.text()
        self.lbl_char_name.setText(char_name)

        # 启用按钮
        self.btn_set_default.setEnabled(True)
        self.btn_delete_char.setEnabled(True)
        self.spin_scale.setEnabled(True)
        self.btn_save_scale.setEnabled(True)
        self.btn_view_details.setEnabled(True)

        # 加载头像
        icon_path = os.path.join(CHAR_DIR, char_name, "headicon.webp")
        if os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
            self.lbl_avatar.setPixmap(pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.lbl_avatar.setText("无头像")
            self.lbl_avatar.setPixmap(QPixmap())

        # 加载缩放
        config_path = os.path.join(CHAR_DIR, char_name, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.spin_scale.setValue(config.get("scale", 0.45))
            except Exception:
                pass

    def save_scale(self):
        current = self.list_chars.currentItem()
        if not current: return
        char_name = current.text()
        config_path = os.path.join(CHAR_DIR, char_name, "config.json")

        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                config["scale"] = self.spin_scale.value()
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=4, ensure_ascii=False)
                QMessageBox.information(self, "成功", f"{char_name} 的缩放已保存！\n重启桌宠后生效。")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存失败: {e}")

    def show_details(self):
        current = self.list_chars.currentItem()
        if not current: return
        dialog = DetailDialog(current.text(), self)
        dialog.exec()

    def set_default_character(self):
        current = self.list_chars.currentItem()
        if not current: return
        char_name = current.text()

        url_line = ""
        if os.path.exists('setting.txt'):
            with open('setting.txt', 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > 1: url_line = lines[1].strip()
                # 第一行可能不存在或格式不对
                arg = lines[0].strip().split(',') if lines else []
        else:
            arg = []

        # 补齐参数并替换第5个
        while len(arg) < 4: arg.append("30")
        if len(arg) >= 5:
            arg[4] = char_name
        else:
            arg.append(char_name)
        while len(arg) < 7:
            # 如果老版本只有 5 个参数，补上默认的宽高
            arg.append("200" if len(arg) == 5 else "320")

        arg[4] = char_name  # 替换角色名
        with open('setting.txt', 'w', encoding='utf-8') as f:
            f.write(f"{','.join(arg)}\n{url_line}\n")

        QMessageBox.information(self, "成功", f"已将 {char_name} 设为默认角色。\n重启桌宠后生效！")
    def delete_character(self):
        current = self.list_chars.currentItem()
        if not current: return
        char_name = current.text()
        reply = QMessageBox.question(self, '确认删除', f'确定要删除角色 {char_name} 的所有文件吗？此操作不可恢复！',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            try:
                shutil.rmtree(os.path.join(CHAR_DIR, char_name))
                self.refresh_character_list()
                self.lbl_avatar.clear()
                self.lbl_char_name.setText("未选择")
                self.spin_scale.setEnabled(False)
                self.btn_save_scale.setEnabled(False)
                self.btn_view_details.setEnabled(False)
                self.btn_set_default.setEnabled(False)
                self.btn_delete_char.setEnabled(False)
            except Exception as e:
                QMessageBox.critical(self, "错误", f"删除失败: {e}")

    # ================= 2. 偏好设置 =================
    def init_settings_tab(self):
        self.tab_settings = QWidget()
        layout = QVBoxLayout(self.tab_settings)
        group = QGroupBox("运行参数设置")
        form_layout = QFormLayout()

        self.spin_sleep = QSpinBox()
        self.spin_sleep.setRange(10, 3600)
        self.spin_sleep.setSuffix(" 秒")
        form_layout.addRow("闲置进入睡眠时间:", self.spin_sleep)

        self.spin_longpress = QSpinBox()
        self.spin_longpress.setRange(200, 2000)
        self.spin_longpress.setSuffix(" 毫秒")
        form_layout.addRow("长按唤出技能盘时间:", self.spin_longpress)

        self.spin_chat = QSpinBox()
        self.spin_chat.setRange(5, 300)
        self.spin_chat.setSuffix(" 秒")
        form_layout.addRow("闲聊触发判定间隔:", self.spin_chat)

        self.spin_action = QSpinBox()
        self.spin_action.setRange(5, 300)
        self.spin_action.setSuffix(" 秒")
        form_layout.addRow("随机小动作判定间隔:", self.spin_action)

        # 👇 新增：窗口大小设置
        self.spin_width = QSpinBox()
        self.spin_width.setRange(100, 1000)
        self.spin_width.setSuffix(" px")
        form_layout.addRow("桌宠窗口宽度:", self.spin_width)

        self.spin_height = QSpinBox()
        self.spin_height.setRange(100, 1000)
        self.spin_height.setSuffix(" px")
        form_layout.addRow("桌宠窗口高度:", self.spin_height)

        group.setLayout(form_layout)
        layout.addWidget(group)

        self.btn_save_settings = QPushButton("保存配置")
        self.btn_save_settings.setFixedHeight(40)
        self.btn_save_settings.clicked.connect(self.save_settings_from_ui)
        layout.addWidget(self.btn_save_settings)
        layout.addStretch()
        self.tabs.addTab(self.tab_settings, "⚙️ 偏好设置")

    def load_settings_to_ui(self):
        if not os.path.exists('setting.txt'): return
        with open('setting.txt', 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if lines:
                arg = lines[0].strip().split(',')
                try:
                    if len(arg) > 0: self.spin_sleep.setValue(int(arg[0]))
                    if len(arg) > 1: self.spin_longpress.setValue(int(arg[1]))
                    if len(arg) > 2: self.spin_chat.setValue(int(arg[2]))
                    if len(arg) > 3: self.spin_action.setValue(int(arg[3]))
                    # 👇 新增：加载宽高
                    if len(arg) > 5: self.spin_width.setValue(int(arg[5]))
                    if len(arg) > 6: self.spin_height.setValue(int(arg[6]))
                except Exception: pass

    def save_settings_from_ui(self):
        default_char = ""
        url_line = "https://uttu.merui.net/profiles/regulus/"

        if os.path.exists('setting.txt'):
            with open('setting.txt', 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > 0:
                    arg = lines[0].strip().split(',')
                    if len(arg) > 4: default_char = arg[4]
                if len(lines) > 1:
                    url_line = lines[1].strip()

                    # 👇 新增：获取宽高
        w = str(self.spin_width.value())
        h = str(self.spin_height.value())

        # 组合新的第一行（加入宽高）
        new_args = [str(self.spin_sleep.value()), str(self.spin_longpress.value()),
                    str(self.spin_chat.value()), str(self.spin_action.value()),
                    default_char, w, h]
        line1 = ','.join(new_args)

        with open('setting.txt', 'w', encoding='utf-8') as f:
            f.write(f"{line1}\n{url_line}\n")
        QMessageBox.information(self, "成功", "配置已保存！\n重启桌宠后生效。")
    # ================= 3. 安装向导 =================
    def install_playwright_engine(self):
        self.log_output.append("\n正在准备外部安装脚本...\n")
        import subprocess
        import playwright
        import pathlib

        pw_dir = os.path.dirname(playwright.__file__)
        node_exe = os.path.join(pw_dir, "driver", "node.exe")
        cli_js = os.path.join(pw_dir, "driver", "package", "cli.js")

        if not os.path.exists(node_exe):
            self.log_output.append(f"❌ 找不到 node.exe，打包可能缺失驱动文件。\n")
            return

        driver_dir = os.path.dirname(node_exe)
        bat_path = os.path.join(BASE_DIR, "install_playwright.bat")

        # 🎯 核心修复：在 bat 里指定 PLAYWRIGHT_BROWSERS_PATH 到 C 盘用户目录
        # 这样就不会受到 _internal 目录权限的限制了
        global_browsers_path = os.path.join(os.environ.get("USERPROFILE", str(pathlib.Path.home())), "AppData",
                                            "Local", "ms-playwright")

        bat_content = f"""@echo off
chcp 65001 >nul
title 安装 Playwright 内核
echo ========================================================
echo 正在下载浏览器内核到您的本地 AppData 目录...
echo ========================================================
cd /d "{driver_dir}"
set PLAYWRIGHT_BROWSERS_PATH={global_browsers_path}
echo 当前目标目录: %PLAYWRIGHT_BROWSERS_PATH%
echo 正在执行下载命令，请稍候（约100MB）...
"{node_exe}" "{cli_js}" install chromium
echo.
echo ========================================================
echo 执行结束，返回值: %errorlevel% (0代表成功)
echo ========================================================
pause
"""
        try:
            with open(bat_path, 'w', encoding='utf-8') as f:
                f.write(bat_content)

            subprocess.Popen(["cmd.exe", "/c", "start", "", bat_path], creationflags=0x00000010)
            self.log_output.append("✅ 外部安装窗口已启动，请查看黑窗中的下载进度。\n")
        except Exception as e:
            self.log_output.append(f"❌ 启动安装失败: {e}\n")
    def init_installer_tab(self):
        self.tab_installer = QWidget()
        layout = QVBoxLayout(self.tab_installer)

        form_layout = QFormLayout()
        self.input_url = QLineEdit()
        # 提示用户直接填入角色主页即可
        self.input_url.setPlaceholderText("例如: https://uttu.merui.net/profiles/regulus/")

        form_layout.addRow("角色主页 URL:", self.input_url)
        layout.addLayout(form_layout)
        # self.btn_install_engine = QPushButton("🌐 环境检测与安装 (首次使用必点)")
        # self.btn_install_engine.setFixedHeight(35)
        # self.btn_install_engine.setStyleSheet("background-color: #D2691E; color: white; font-weight: bold;")
        # self.btn_install_engine.clicked.connect(self.install_playwright_engine)
        # layout.addWidget(self.btn_install_engine)
        self.btn_start_spider = QPushButton("🚀 一键抓取并安装")
        self.btn_start_spider.setFixedHeight(40)
        self.btn_start_spider.setStyleSheet("background-color: #005A9E; color: white; font-weight: bold;")
        self.btn_start_spider.clicked.connect(self.run_spider)
        layout.addWidget(self.btn_start_spider)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: #1e1e1e; color: #00FF00; font-family: Consolas;")
        layout.addWidget(self.log_output)

        self.tabs.addTab(self.tab_installer, "🛠️ 安装向导")
        self.spider_process = None

    def kill_spider_if_running(self):
        if self.spider_process and self.spider_process.state() == QProcess.Running:
            self.log_output.append("\n⚠️ 爬虫运行超过 25 分钟，疑似卡死，已强制终止！请检查网络。\n")
            self.spider_process.kill()
    def run_spider(self):
        url = self.input_url.text().strip()
        if not url:
            QMessageBox.warning(self, "警告", "请填写角色主页 URL！")
            return

        self.btn_start_spider.setEnabled(False)
        self.log_output.clear()

        # 保留第一行
        line1 = "120,500,45,30,"
        if os.path.exists('setting.txt'):
            with open('setting.txt', 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if lines: line1 = lines[0].strip()

        # 写入两行 (第一行旧配置，第二行新URL)
        with open('setting.txt', 'w', encoding='utf-8') as f:
            f.write(f"{line1}\n{url}\n")

        self.log_output.append("正在启动爬虫进程...\n")

        self.spider_process = QProcess()

        # 🎯 核心修复 1：通过环境变量强制禁用 Python 的输出缓冲
        from PySide6.QtCore import QProcessEnvironment
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")  # 关键：禁用缓冲
        env.insert("PYTHONIOENCODING", "utf-8")  # 关键：强制 UTF-8 编码，解决乱码
        # env.insert("DEBUG", "pw:api")  # 👈 新增：打印 Playwright 底层网络日志
        self.spider_process.setProcessEnvironment(env)

        self.spider_process.setProcessChannelMode(QProcess.MergedChannels)
        self.spider_process.readyReadStandardOutput.connect(self.read_spider_output)
        self.spider_process.finished.connect(self.spider_finished)

        if getattr(sys, 'frozen', False):
            self.spider_process.start(sys.executable, ["--run-spider"])
        else:
            # 🎯 核心修复 2：源码运行加 "-u" 参数，强制无缓冲
            self.spider_process.start(sys.executable, ["-u", os.path.join(BASE_DIR, "spider.py")])
        # 启动一个强行终止的定时器
        self.spider_timeout_timer = QTimer()
        self.spider_timeout_timer.setSingleShot(True)
        self.spider_timeout_timer.timeout.connect(self.kill_spider_if_running)
        # 25分钟（1500000毫秒）后如果还没抓完，强制杀掉
        self.spider_timeout_timer.start(1500000)

    def read_spider_output(self):
        data = self.spider_process.readAllStandardOutput()
        if not data:
            return
        try:
            # 优先尝试 UTF-8 解码
            text = bytes(data).decode('utf-8')
        except UnicodeDecodeError:
            # 失败则用 GBK 解码，防止 Windows CMD 环境导致的乱码
            text = bytes(data).decode('gbk', errors='replace')
        self.log_output.append(text)

    def spider_finished(self):
        if hasattr(self, 'spider_timeout_timer'):
            self.spider_timeout_timer.stop()
        self.log_output.append("\n✅ 爬虫进程执行完毕！")
        self.btn_start_spider.setEnabled(True)
        self.refresh_character_list()
        QMessageBox.information(self, "完成", "抓取任务结束，请检查日志和角色库。")

    # ================= 启动桌宠 =================
    def launch_pet(self):
        self.btn_launch.setEnabled(False)
        self.btn_launch.setText("⏳ 桌宠正在运行中...")
        self.pet_process = QProcess()
        self.pet_process.finished.connect(self.on_pet_closed)
        self.pet_process.errorOccurred.connect(self.on_pet_error)
        # 🎯 修改：如果是 exe 运行，直接启动自己；如果是源码，启动 python main.py
        if getattr(sys, 'frozen', False):
            self.pet_process.start(sys.executable, ["--run-pet"])
        else:
            self.pet_process.start(sys.executable, [os.path.join(BASE_DIR, "main.py")])

    def on_pet_closed(self):
        self.btn_launch.setEnabled(True)
        self.btn_launch.setText("✨ 启动桌宠 ✨")
        # 🎯 新增：如果桌宠被关了（无论是托盘退出还是崩溃），自动把面板弹出来
        if not self.isVisible():
            self.showNormal()
            self.raise_()
            self.activateWindow()
            QMessageBox.warning(self, "提示", "桌宠已退出。")

    def on_pet_error(self, error):
        """桌宠进程发生崩溃时触发"""
        print(f"桌宠进程发生错误: {error}")
if __name__ == '__main__':
    # 🎯 拦截安装指令
    if len(sys.argv) > 1 and sys.argv[1] == "--install-playwright":
        print("========== 开始安装 Playwright 内核 ==========")
        import traceback
        try:
            from playwright.__main__ import main as pw_main
            sys.argv = ["playwright", "install", "chromium"]
            pw_main()
            print("\n✅ 浏览器内核安装成功！")
        except SystemExit:
            print("\n安装流程结束。")
        except Exception as e:
            print(f"\n❌ 安装失败！具体错误: {e}")
            traceback.print_exc() # 打印详细报错
        print("========== 安装窗口即将挂起，请查看上方输出 ==========")
        # 强制挂起，哪怕内部报错也绝对不让窗口关掉！
        import subprocess
        subprocess.run("pause", shell=True)
        sys.exit(0)

    elif len(sys.argv) > 1 and sys.argv[1] == "--run-pet":
        import main

        main.start_pet()
        sys.exit(0)

    elif len(sys.argv) > 1 and sys.argv[1] == "--run-spider":
        import spider

        spider.main()
        sys.exit(0)

    # 正常启动面板
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = PanelWindow()
    window.show()
    sys.exit(app.exec())