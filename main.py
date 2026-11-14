import sys
import os

def get_base_dir():
    """获取程序所在的绝对根目录（兼容打包和源码运行）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()
os.chdir(BASE_DIR) # 锁定工作目录

# 🎯 修复 1：拦截无控制台模式下的 print 编码崩溃
class SafeStream:
    def __init__(self, original_stream):
        self.original_stream = original_stream
    def write(self, text):
        if self.original_stream:
            try:
                # 强行把 emoji 转换成 GBK 能识别的字符，把 emoji 过滤掉
                safe_text = text.encode('gbk', errors='ignore').decode('gbk')
                self.original_stream.write(safe_text)
            except Exception:
                pass
    def flush(self):
        if self.original_stream:
            try: self.original_stream.flush()
            except Exception: pass

sys.stdout = SafeStream(sys.stdout)
sys.stderr = SafeStream(sys.stderr)

import threading
import http.server
import socketserver
import re
import random
import json
import time
import pygame
from datetime import datetime
from PySide6.QtCore import Qt, QUrl, QPoint, QTimer
from PySide6.QtGui import QColor, QAction, QIcon
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QMainWindow, QMenu, QWidget, QVBoxLayout,
                               QSystemTrayIcon, QStyle)

PORT = 8000
SLEEP_THRESHOLD, LONG_PRESS_MS, IDLE_CHAT_INTERVAL, ACTION_INTERVAL, DEFAULT_CHAR = 120, 500, 45, 30, ""
WINDOW_WIDTH, WINDOW_HEIGHT = 200, 320 # 👈 新增：默认大小兜底

# 🎯 修复 2：如果 setting.txt 不存在，自动生成默认文件，防止闪退
setting_path = os.path.join(BASE_DIR, 'setting.txt')
try:
    if os.path.exists(setting_path):
        with open(os.path.join(BASE_DIR, 'setting.txt'), 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if lines:
                arg = lines[0].strip().split(',')
                SLEEP_THRESHOLD = int(arg[0]) if len(arg) > 0 else 120
                LONG_PRESS_MS = int(arg[1]) if len(arg) > 1 else 500
                IDLE_CHAT_INTERVAL = int(arg[2]) if len(arg) > 2 else 45
                ACTION_INTERVAL = int(arg[3]) if len(arg) > 3 else 30
                DEFAULT_CHAR = arg[4].strip() if len(arg) > 4 else ""

                # 👇 新增：读取窗口大小
                if len(arg) > 5: WINDOW_WIDTH = int(arg[5])
                if len(arg) > 6: WINDOW_HEIGHT = int(arg[6])
    else:
        print("未找到 setting.txt，自动生成默认配置。")
        with open(setting_path, 'w', encoding='utf-8') as f:
            f.write("120,500,45,30,voyager,200,320\nhttps://uttu.merui.net/profiles/regulus/\n")
except Exception as e:
    print(f"读取 setting.txt 失败，使用默认配置: {e}")
class SafeHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_GET(self):
        try:
            super().do_GET()
        except Exception:
            self.send_error(500, "Internal Server Error")


def start_server():
    os.chdir(BASE_DIR) # 确保 HTTP 服务器在根目录启动
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), SafeHTTPRequestHandler) as httpd:
        httpd.serve_forever()


# ================= 技能盘悬浮窗 =================
class SkillBoardWindow(QWidget):
    def __init__(self, parent):
        super().__init__()
        self.parent_pet = parent
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(1200, 1250)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web_view = QWebEngineView(self)
        layout.addWidget(self.web_view)

        self.web_view.page().setBackgroundColor(Qt.transparent)
        self.web_view.page().settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.web_view.titleChanged.connect(self.on_title_changed)
        self.web_view.load(QUrl(f"http://localhost:{PORT}/skill_ui.html"))
        self.web_view.loadFinished.connect(self.on_first_load_finished)
        self.is_loaded = False

    def on_first_load_finished(self, ok):
        if ok:
            self.is_loaded = True
            self.web_view.page().runJavaScript("""
                document.body.style.backgroundColor = 'transparent';
                document.body.style.padding = '0';
                document.body.style.alignItems = 'center';
                document.body.style.overflow = 'visible';
            """)

    def update_and_show(self, skills_data):
        num_skills = len(skills_data)
        win_width = max(300, num_skills * 200 + 80)
        win_height = 400
        self.resize(win_width, win_height)

        pet_geo = self.parent_pet.frameGeometry()
        target_x = pet_geo.center().x() - win_width // 2
        target_y = pet_geo.top() - win_height + 80
        if target_y < 0: target_y = 10
        self.move(target_x, target_y)

        if self.is_loaded:
            self.web_view.page().runJavaScript(f"window.renderSkills({json.dumps(skills_data)});")
        else:
            self.web_view.loadFinished.connect(
                lambda: self.web_view.page().runJavaScript(f"window.renderSkills({json.dumps(skills_data)});"))

        self.show()
        self.raise_()
        self.activateWindow()
        self.show_time = time.time()

    def on_title_changed(self, title):
        if title.startswith("SKILL_HOVER:"):
            if hasattr(self, 'show_time') and (time.time() - self.show_time < 0.5): return
            parts = title.split(":")
            if len(parts) >= 2: self.parent_pet.play_select_voice(parts[1])
        elif title.startswith("SKILL_SELECTED:"):
            parts = title.split(":")
            if len(parts) >= 2:
                self.parent_pet.execute_skill_from_board(parts[1])
                self.hide()

    def mousePressEvent(self, event):
        self.hide()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.hide()


# ================= 桌宠主窗口 =================
class DesktopPet(QMainWindow):
    def __init__(self):
        super().__init__()
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        self.sound_cache = {}
        self.current_char = ""
        self.char_config = {}
        self.available_animations = []
        self.skills_data = []
        self.is_switching = False
        self.long_press_triggered = False

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self.web_view = QWebEngineView(self)
        self.setCentralWidget(self.web_view)
        self.web_view.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.web_view.page().settings().setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        self.web_view.page().setBackgroundColor(QColor(Qt.transparent))

        # 👇 监听网页 READY 信号
        self.web_view.titleChanged.connect(self.on_page_ready)

        self.drag_position = QPoint()
        self.is_dragging = False
        self.press_pos = QPoint()
        self.is_sleeping = False
        self.idle_seconds = 0

        self.long_press_timer = QTimer(self)
        self.long_press_timer.setSingleShot(True)
        self.long_press_timer.timeout.connect(self.show_skill_board)

        self.tick_timer = QTimer(self)
        self.tick_timer.timeout.connect(self.update_idle_state)
        self.tick_timer.start(1000)

        self.action_timer = QTimer(self)
        self.action_timer.timeout.connect(self.random_action)
        self.action_timer.start(ACTION_INTERVAL*1000)

        self.chat_timer = QTimer(self)
        self.chat_timer.timeout.connect(self.trigger_idle_chat)
        self.chat_timer.start(IDLE_CHAT_INTERVAL * 1000)
        self.action_cooldown = 0  # 👈 新增：动作冷却倒计时（秒）
        # 👇 只创建一次悬浮窗
        self.skill_board = SkillBoardWindow(self)

        self.scan_and_load_first_char()
        self.setup_tray()

    def setup_tray(self):
        """初始化系统托盘"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            print("⚠️ 当前系统不支持系统托盘")
            return

        self.tray_icon = QSystemTrayIcon(self)

        # 1. 尝试加载当前角色的头像作为托盘图标
        headicon_path = os.path.join("characters", self.current_char, "headicon.webp")
        if os.path.exists(headicon_path):
            self.tray_icon.setIcon(QIcon(headicon_path))
        else:
            # 如果没有头像，就用系统默认的电脑图标兜底
            self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ComputerIcon))

        # 2. 设置提示文字
        self.tray_icon.setToolTip(f"桌宠运行中 - {self.current_char}")

        # 3. 创建托盘右键菜单
        self.tray_menu = QMenu()
        self.tray_menu.setStyleSheet(
            "QMenu { background-color: #333; color: white; border: 1px solid #555; } QMenu::item:selected { background-color: #555; }")

        # 动作：显示/隐藏桌宠
        self.action_toggle_show = QAction("👁️ 显示/隐藏桌宠", self)
        self.action_toggle_show.triggered.connect(self.toggle_pet_visibility)
        self.tray_menu.addAction(self.action_toggle_show)

        self.tray_menu.addSeparator()

        # 动作：完全退出
        self.action_quit = QAction("❌ 彻底退出", self)
        self.action_quit.triggered.connect(QApplication.quit)
        self.tray_menu.addAction(self.action_quit)

        # 绑定菜单并显示托盘
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

        # 双击托盘图标也能切换显示/隐藏
        self.tray_icon.activated.connect(self.on_tray_activated)

    def toggle_pet_visibility(self):
        """切换桌宠显示/隐藏"""
        if self.isVisible():
            self.hide()
            self.action_toggle_show.setText("👁️ 显示桌宠")
        else:
            self.show()
            self.raise_()  # 强制置顶
            self.action_toggle_show.setText("👁️ 隐藏桌宠")

    def on_tray_activated(self, reason):
        """双击托盘图标时响应"""
        if reason == QSystemTrayIcon.DoubleClick:
            self.toggle_pet_visibility()

    def on_page_ready(self, title):
        if title == "READY":
            self.fetch_animations()

    def scan_and_load_first_char(self):
        char_root = "characters"
        if not os.path.exists(char_root): return

        # 👇 核心修改：如果指定了默认角色，且文件夹存在，就优先加载
        if DEFAULT_CHAR:
            char_dir = os.path.join(char_root, DEFAULT_CHAR)
            if os.path.exists(char_dir) and os.path.isdir(char_dir):
                print(f"⭐ 加载偏好设置中的默认角色: {DEFAULT_CHAR}")
                self.load_character(DEFAULT_CHAR)
                return
            else:
                print(f"⚠️ 偏好设置中的角色 {DEFAULT_CHAR} 不存在，将加载第一个可用角色。")

        # 否则，加载列表里的第一个角色
        dirs = [d for d in os.listdir(char_root) if os.path.isdir(os.path.join(char_root, d))]
        if dirs:
            self.load_character(dirs[0])

    def load_character(self, char_name):
        self.current_char = char_name
        char_dir = os.path.join("characters", char_name)

        config_path = os.path.join(char_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    self.char_config = json.load(f)
            except Exception:
                self.char_config = {}
        else:
            self.char_config = {}

        skel_file, atlas_file = "", ""
        if os.path.exists(char_dir):
            for f in os.listdir(char_dir):
                if f.endswith(".skel"):
                    skel_file = f
                elif f.endswith(".atlas"):
                    atlas_file = f

        if skel_file and atlas_file:
            skel_url = f"characters/{char_name}/{skel_file}"
            atlas_url = f"characters/{char_name}/{atlas_file}"
            char_scale = self.char_config.get("scale", 0.45)
            self.web_view.load(
                QUrl(f"http://localhost:{PORT}/index.html?skel={skel_url}&atlas={atlas_url}&scale={char_scale}"))
        else:
            self.is_switching = False
            return

        self.sound_cache.clear()
        self.sound_dir = os.path.join(char_dir, "sounds")
        if os.path.exists(self.sound_dir):
            for file in os.listdir(self.sound_dir):
                if file.endswith((".wav", ".ogg", ".mp3")):
                    name = os.path.splitext(file)[0]
                    path = os.path.join(self.sound_dir, file)
                    try:
                        self.sound_cache[name] = pygame.mixer.Sound(path)
                        self.sound_cache[name].set_volume(0.8)
                    except Exception:
                        pass
        # 👇 新增：加载字幕
        self.subtitle_cache = {}
        subtitle_path = os.path.join(char_dir, "subtitles.json")
        if os.path.exists(subtitle_path):
            try:
                with open(subtitle_path, 'r', encoding='utf-8') as f:
                    self.subtitle_cache = json.load(f)
            except Exception as e:
                print(f"⚠️ 读取字幕文件失败: {e}")
        self.is_sleeping = False
        self.idle_seconds = 0
        # 👇 新增：如果托盘已经存在，动态更新它的图标和提示文字
        if hasattr(self, 'tray_icon'):
            headicon_path = os.path.join(char_dir, "headicon.webp")
            if os.path.exists(headicon_path):
                self.tray_icon.setIcon(QIcon(headicon_path))
            self.tray_icon.setToolTip(f"桌宠运行中 - {char_name}")

    def fetch_animations(self):
        self.web_view.page().runJavaScript("JSON.stringify(window.availableAnimations || [])",
                                           self.on_animations_fetched)

    def on_animations_fetched(self, result):
        if result:
            try:
                anims = json.loads(result)
                if anims:
                    self.available_animations = anims
                    self.build_skills_data()
                    self.is_switching = False
                    print(f"✅ 成功同步动作列表！共 {len(anims)} 个动作。")
                    self.play_action_voice("born")
                    return
            except Exception:
                pass

        self.available_animations = ["born", "idle", "hit", "giddy", "posture", "sleep", "skill1", "die"]
        self.build_skills_data()
        self.is_switching = False
        print("⚠️ 网页未返回有效动作，使用兜底动作列表")
        self.play_action_voice("born")

    def build_skills_data(self):
        self.skills_data = []
        icon_dir = f"characters/{self.current_char}/icons/"

        if "skills" in self.char_config and isinstance(self.char_config["skills"], list):
            for s in self.char_config["skills"]:
                if not s["icon"].startswith("http"):
                    s["icon"] = icon_dir + s["icon"].split("/")[-1]
                self.skills_data.append(s)
            return

        skill_groups = {}
        unique_anims = []
        for a in self.available_animations:
            if a.startswith("skill"):
                match = re.match(r'^(skill\d+)', a)
                if match: skill_groups.setdefault(match.group(1), []).append(a)
            elif a.startswith("unique"):
                unique_anims.append(a)

        for i, (sid, seq) in enumerate(skill_groups.items()):
            self.skills_data.append({
                "id": sid, "icon": f"{icon_dir}{sid}.webp", "type": "attack" if i % 2 == 0 else "debuff",
                "star": (i % 3) + 1, "sequence": seq
            })
        if unique_anims:
            self.skills_data.append({
                "id": "unique", "icon": f"{icon_dir}unique.webp", "type": "ultimate", "star": 3,
                "sequence": unique_anims
            })

    def trigger_idle_chat(self):
        if self.is_sleeping or self.is_dragging or self.is_switching: return
        if self.action_cooldown > 0:  # 👈 核心：冷却中直接跳过，不许动！
            return
        chats = self.char_config.get("idle_chats", {})
        if not chats: return
        hour = datetime.now().hour
        if 5 <= hour < 12:
            if random.random() < 0.3:
                time_key = "default"
            else:
                time_key = "morning"
        elif 18 <= hour < 24:
            if random.random() < 0.3:
                time_key = "default"
            else:
                time_key = "night"
        else:
            time_key = "default"
        pool = chats.get(time_key, [])
        if not pool: pool = chats.get("default", [])
        if pool and random.random() < 0.3:
            voice = random.choice(pool)
            self.play_sound(os.path.splitext(voice)[0])
            self.play_js("window.playAction('posture')")

    def show_skill_board(self):
        if self.is_sleeping or self.is_switching: return
        self.wake_up()
        pygame.mixer.stop()
        self.long_press_triggered = True
        self.play_action_voice("pre_battle")
        self.skill_board.update_and_show(self.skills_data)

    def execute_skill_from_board(self, skill_id):
        print(f"【UI】释放技能: {skill_id}")

        # 🎯 核心修复：如果是大招，无视 config 里的死板序列，直接动态抓取全套 unique 连招！
        if skill_id == "unique":
            dynamic_uniques = sorted(
                [a for a in self.available_animations if a.startswith("unique")],
                key=lambda x: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', x)]
            )
            if dynamic_uniques:
                self.play_sequence(dynamic_uniques)
                self.play_action_voice("unique")
                return

        # 普通技能逻辑
        dynamic_seq = sorted(
            [a for a in self.available_animations if a == skill_id or a.startswith(f"{skill_id}_")],
            key=lambda x: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', x)]
        )

        if dynamic_seq:
            self.play_sequence(dynamic_seq)
        else:
            seq = [skill_id]
            for s in self.skills_data:
                if s["id"] == skill_id:
                    seq = s.get("sequence", [skill_id])
                    break
            self.play_sequence(seq)

        self.play_action_voice(skill_id)

    def play_select_voice(self, skill_id):
        if skill_id == "unique":
            self.play_action_voice("select_unique")
        else:
            self.play_action_voice("select_skill")

    def play_action_voice(self, action_name):
        sounds_map = self.char_config.get("action_sounds", {})
        if action_name in sounds_map:
            pool = sounds_map[action_name]
            if pool: self.play_sound(os.path.splitext(random.choice(pool))[0])
        else:
            self.play_sound(action_name)

    def play_sequence(self, seq_list):
        self.action_cooldown = max(3, len(seq_list) * 1.5)
        self.play_js(f"window.playComboList({json.dumps(seq_list)})")

    def switch_character(self, new_char):
        if new_char == self.current_char or self.is_switching: return
        self.is_switching = True
        self.wake_up()
        pygame.mixer.stop()
        if "giddy" in self.available_animations:
            self.play_js("window.playAction('giddy')")
            QTimer.singleShot(2000, lambda: self.load_character(new_char))
        else:
            self.load_character(new_char)

    def play_sound(self, sound_name):
        if sound_name in self.sound_cache:
            pygame.mixer.stop()

            sound = self.sound_cache[sound_name]
            sound.play()

            # 👇 获取音频的真实时长（秒）
            duration = sound.get_length()

            # 👇 查找并显示字幕
            subtitle_text = self.subtitle_cache.get(f"{sound_name}.ogg")
            if subtitle_text:
                # 使用 json.dumps 完美处理换行和引号
                safe_js_string = json.dumps(subtitle_text)
                # 把文本和时长一起传给 JS
                self.play_js(f"window.showSubtitle({safe_js_string}, {duration})")
        else:
            print(f"⚠️ 找不到音频: {sound_name}")
            self.play_js("window.hideSubtitle()")

    def update_idle_state(self):
        if self.action_cooldown > 0:
            self.action_cooldown -= 1
            return
        if not self.is_sleeping and not self.is_switching:
            self.idle_seconds += 1
            if self.idle_seconds >= SLEEP_THRESHOLD: self.sleep()

    def sleep(self):
        self.is_sleeping = True
        self.play_js("window.playAction('sleep')")
        self.play_action_voice("sleep")

    def wake_up(self):
        if self.is_sleeping:
            self.is_sleeping = False
            pygame.mixer.stop()
        self.idle_seconds = 0

    def random_action(self):
        if self.is_sleeping or self.is_dragging or self.is_switching: return
        if self.action_cooldown > 0:  # 👈 核心：冷却中直接跳过，不许动！
            return
        self.idle_seconds = self.idle_seconds // 2
        # 15% 概率放个技能或大招（动作幅度大）
        if random.random() < 0.15 and self.skills_data:
            skill = random.choice(self.skills_data)
            self.execute_skill_from_board(skill["id"])
            return

        # 85% 概率放日常小动作（把 idle 删掉，换成会动的小动作）
        # 如果模型没有这些动作，网页里会自动 fallback 到 idle
        action = random.choice(["posture", "giddy","born"])
        self.play_js(f"window.playAction('{action}')")

    def play_js(self, js_code):
        self.web_view.page().runJavaScript(js_code)

    def closeEvent(self, event):
        """当触发退出时，确保托盘图标也一起清理掉"""
        if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
            self.tray_icon.hide()
        event.accept()
        QApplication.quit()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.wake_up()
            self.press_pos = event.globalPosition().toPoint()
            self.drag_position = self.press_pos - self.frameGeometry().topLeft()
            self.is_dragging = False
            self.long_press_triggered = False
            self.long_press_timer.start(LONG_PRESS_MS)
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            if (event.globalPosition().toPoint() - self.press_pos).manhattanLength() > 5:
                self.is_dragging = True
                self.long_press_timer.stop()
                self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.long_press_timer.stop()
            self.wake_up()

            if not self.is_dragging and not self.long_press_triggered:
                action = random.choice(["posture", "giddy"])
                self.action_cooldown = 2.5
                self.play_js(f"window.playAction('{action}')")
                self.play_action_voice(action)
            event.accept()

    def contextMenuEvent(self, event):
        print("【UI】触发右键菜单")
        self.wake_up()
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #333; color: white; border: 1px solid #555; } QMenu::item:selected { background-color: #555; } QMenu::separator { height: 1px; background: #555; margin: 5px 0; }")

        # 1. 切换角色
        switch_menu = menu.addMenu("切换角色")
        char_root = "characters"
        if os.path.exists(char_root):
            dirs = [d for d in os.listdir(char_root) if os.path.isdir(os.path.join(char_root, d))]
            for d in dirs:
                action = QAction(d, self)
                if d == self.current_char:
                    action.setCheckable(True)
                    action.setChecked(True)
                action.triggered.connect(lambda checked, name=d: self.switch_character(name))
                switch_menu.addAction(action)

        menu.addSeparator()

        # 2. 播放动作（包含普通动作和连招）
        if self.available_animations:
            anim_menu = menu.addMenu("播放动作")

            uniques = sorted([a for a in self.available_animations if a.startswith("unique")],
                             key=lambda x: [int(c) if c.isdigit() else c for c in re.split(r'(\d+)', x)])
            other_anims = [a for a in self.available_animations if a not in uniques]

            for a in other_anims:
                act = QAction(a, self)
                act.triggered.connect(lambda checked, name=a: self.play_js(f"window.playAction('{name}')"))
                anim_menu.addAction(act)

            if uniques:
                anim_menu.addSeparator()
                combo_act = QAction(f"🔥 释放连招 ({len(uniques)}段)", self)
                combo_act.triggered.connect(lambda: self.play_sequence(uniques))
                anim_menu.addAction(combo_act)

        # 3. 闲聊分类
        chats = self.char_config.get("idle_chats", {})
        if chats:
            chat_menu = menu.addMenu("闲聊分类")
            for key, pool in chats.items():
                act = QAction(key, self)
                act.triggered.connect(lambda checked, p=pool: self.play_sound(os.path.splitext(random.choice(p))[0]))
                chat_menu.addAction(act)

        # 4. 播放所有语音
        if self.sound_cache:
            sound_menu = menu.addMenu("播放所有语音")
            for s_name in sorted(self.sound_cache.keys()):
                act = QAction(s_name, self)
                act.triggered.connect(lambda checked, name=s_name: self.play_sound(name))
                sound_menu.addAction(act)

        menu.addSeparator()
        exit_action = QAction("退出桌宠", self)
        exit_action.triggered.connect(QApplication.quit)
        menu.addAction(exit_action)

        menu.exec(event.globalPos())


def start_pet():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    app = QApplication(sys.argv)
    pet = DesktopPet()
    pet.show()
    app.exec()

if __name__ == '__main__':
    start_pet()