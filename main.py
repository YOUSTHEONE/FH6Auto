import sys
import os
import json
import time
import shutil
import ctypes
import threading
import subprocess
import webbrowser

# 【极其关键】：必须在任何 UI 库导入之前设置 DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Win 8.1+
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()  # Win Vista+
    except Exception:
        pass

import customtkinter as ctk
ctk.deactivate_automatic_dpi_awareness()
ctk.set_widget_scaling(1.0)
ctk.set_window_scaling(1.0)
import cv2
import numpy as np
import pyautogui
import pydirectinput
import requests
from pynput import keyboard
from PIL import Image
import win32gui


# ==========================================
# --- 路径与资源策略 ---
# assets: 只读内置，禁止本地覆盖
# images: 打包进 exe，启动时若外部无 images 则自动释放；识图优先读外部 images
# ==========================================
def get_app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_internal_dir():
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return get_app_dir()


APP_DIR = get_app_dir()
INTERNAL_DIR = get_internal_dir()
CONFIG_FILE = os.path.join(APP_DIR, "bot_config.json")
LOG_FILE = os.path.join(APP_DIR, "bot_log.txt")
CURRENT_VERSION = "1.0.0"


def auto_extract_images(folder_name="images"):
    internal_dir = os.path.join(INTERNAL_DIR, folder_name)
    external_dir = os.path.join(APP_DIR, folder_name)

    if not os.path.isdir(internal_dir):
        print(f"[auto_extract_images] 内置目录不存在: {internal_dir}")
        return

    try:
        os.makedirs(external_dir, exist_ok=True)

        for root, dirs, files in os.walk(internal_dir):
            rel_path = os.path.relpath(root, internal_dir)
            target_root = external_dir if rel_path == "." else os.path.join(external_dir, rel_path)
            os.makedirs(target_root, exist_ok=True)

            for file in files:
                src_file = os.path.join(root, file)
                dst_file = os.path.join(target_root, file)

                # 只在外部不存在时释放，保留用户自定义替换
                if not os.path.exists(dst_file):
                    shutil.copy2(src_file, dst_file)

    except Exception as e:
        print(f"[auto_extract_images] 释放 images 失败: {e}")


def get_img_path(filename):
    basename = os.path.basename(filename)

    # 优先读取程序目录外部 images（允许用户替换）
    ext_path = os.path.join(APP_DIR, "images", basename)
    if os.path.exists(ext_path):
        return ext_path

    # 外部没有则读取内置 images
    int_path = os.path.join(INTERNAL_DIR, "images", basename)
    if os.path.exists(int_path):
        return int_path

    return filename


def get_asset_path(*parts):
    """
    assets 只允许读取内置资源：
    - 打包后：_MEIPASS/assets
    - 开发环境：项目目录/assets
    """
    asset_path = os.path.join(INTERNAL_DIR, "assets", *parts)
    if os.path.exists(asset_path):
        return asset_path

    dev_asset_path = os.path.join(get_app_dir(), "assets", *parts)
    if os.path.exists(dev_asset_path):
        return dev_asset_path

    return None


def parse_version(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except Exception:
        return (0, 0, 0)


auto_extract_images()

# ==========================================
# --- Ctypes 硬件级键盘模拟结构体定义 ---
# ==========================================
SendInput = ctypes.windll.user32.SendInput
PUL = ctypes.POINTER(ctypes.c_ulong)


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class Input_I(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput),
    ]


class Input(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", Input_I),
    ]


# --- 硬件扫描码 (Scan Codes) 包含数字 0-9 ---
DIK_CODES = {
    "esc": (0x01, False),
    "enter": (0x1C, False),
    "space": (0x39, False),
    "backspace": (0x0E, False),
    "w": (0x11, False),
    "e": (0x12, False),
    "x": (0x2D, False),
    "up": (0xC8, True),
    "down": (0xD0, True),
    "left": (0xCB, True),
    "right": (0xCD, True),
    "pageup": (0xC9, True),
    "pagedown": (0xD1, True),
    "1": (0x02, False),
    "2": (0x03, False),
    "3": (0x04, False),
    "4": (0x05, False),
    "5": (0x06, False),
    "6": (0x07, False),
    "7": (0x08, False),
    "8": (0x09, False),
    "9": (0x0A, False),
    "0": (0x0B, False),
}

# --- 全局配置 ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
MATCH_THRESHOLD = 0.8
pyautogui.FAILSAFE = False


class FH_UltimateBot(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("FH6Auto by YSTO")
        self.geometry("1080x560")
        #self.minsize(980, 560)
        self.attributes("-topmost", False)
        self.attributes("-alpha", 0.98)
        self.resizable(False, False)

        try:
            icon_path = get_asset_path("icon.ico")
            if icon_path:
                self.iconbitmap(icon_path)
        except Exception:
            pass

        self.is_running = False
        self.current_thread = None

        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.global_loop_current = 0

        self.template_cache = {}
        self.support_win = None

        self.init_regions()

        self.config = {
            "race_count": 99,
            "buy_count": 30,
            "cj_count": 30,
            "chk_1": True,
            "chk_2": True,
            "chk_3": True,
            "global_loops": 10,
            "skill_dirs": ["right", "up", "up", "up", "left"],
            "share_code": "175882167",
            "base_width": 1920,
            "auto_restart": False,
            "restart_cmd": "start steam://run/2483190",
        }
        self.load_config()

        self.setup_ui()
        self.start_hotkey_listener()
        self.update_skill_grid()
        self.center_window()
        self.log("免责声明：本脚本仅供 Python 自动化技术交流与学习使用。请勿用于商业盈利或破坏游戏平衡，因使用本脚本造成的账号封禁等损失，由使用者自行承担。")
        self.log("启动前先将键盘设置为【英文键盘】")
        self.log("游戏设置为【自动转向】")
        self.log("大部分以图像识别作为引导，减少机器盲目操作的风险，但仍无法完全避免，使用前请做好准备")

    # ==========================================
    # --- UI 安全调度 ---
    # ==========================================
    def ui_call(self, func, *args, **kwargs):
        try:
            self.after(0, lambda: func(*args, **kwargs))
        except Exception:
            pass

    def center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ==========================================
    # --- 初始化全局 Region ---
    # ==========================================
    def init_regions(self):
        sw, sh = pyautogui.size()
        self.update_regions_by_window(0, 0, sw, sh)

    def update_regions_by_window(self, x, y, w, h):
        self.regions = {
            "全界面": (x, y, w, h),
            "左上": (x, y, w // 2, h // 2),
            "右上": (x + w // 2, y, w // 2, h // 2),
            "左下": (x, y + h // 2, w // 2, h // 2),
            "右下": (x + w // 2, y + h // 2, w // 2, h // 2),
            "上": (x, y, w, h // 2),
            "下": (x, y + h // 2, w, h // 2),
            "左": (x, y, w // 2, h),
            "右": (x + w // 2, y, w // 2, h),
            "中间": (x + w // 4, y + h // 4, w // 2, h // 2),
        }

    # ==========================================
    # --- 配置管理 ---
    # ==========================================
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.config.update(data)
            except Exception:
                pass

    def save_config(self):
        try:
            self.config["race_count"] = int(self.entry_race.get())
            self.config["buy_count"] = int(self.entry_car.get())
            self.config["cj_count"] = int(self.entry_cj.get())
            self.config["global_loops"] = int(self.entry_global_loop.get())
            self.config["share_code"] = "".join(c for c in self.entry_share.get() if c.isdigit())
            self.config["base_width"] = int(self.entry_base_w.get())
        except Exception:
            pass

        self.config["chk_1"] = self.var_chk1.get()
        self.config["chk_2"] = self.var_chk2.get()
        self.config["chk_3"] = self.var_chk3.get()
        self.config["auto_restart"] = self.var_auto_restart.get()
        self.config["restart_cmd"] = self.le_restart_cmd.get().strip()

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    # ==========================================
    # --- UI 布局设计 ---
    # ==========================================
    def setup_ui(self):
        self.top_container = ctk.CTkFrame(self, fg_color="transparent")
        self.top_container.pack(fill="x", padx=14, pady=(14, 8))

        self.config_frame = ctk.CTkFrame(self.top_container, fg_color="transparent")
        self.config_frame.pack(fill="x")

        def create_box(parent, title, btn_cmd, btn_color, def_val, lbl_text):
            frame = ctk.CTkFrame(
                parent,
                width=165,
                height=240,
                corner_radius=12,
                border_width=1,
                border_color="#2B2B2B",
            )
            frame.pack_propagate(False)
            frame.pack(side="left", padx=6)

            ctk.CTkLabel(
                frame,
                text=title,
                font=ctk.CTkFont(weight="bold", size=16),
            ).pack(pady=(12, 8))

            btn = ctk.CTkButton(
                frame,
                text="开始",
                fg_color=btn_color,
                hover_color=btn_color,
                command=btn_cmd,
                width=110,
                height=34,
                corner_radius=10,
            )
            btn.pack(pady=6, padx=10)

            entry = ctk.CTkEntry(frame, width=78, height=32, justify="center", corner_radius=8)
            entry.insert(0, str(def_val))
            entry.pack(pady=6)

            lbl = ctk.CTkLabel(
                frame,
                text=f"执行: 0 / {def_val}",
                text_color="#A0A0A0",
                font=ctk.CTkFont(size=16),
            )
            lbl.pack(pady=6)
            return frame, btn, entry, lbl

        def create_arrow(parent, var_checked):
            frame = ctk.CTkFrame(parent, fg_color="transparent", width=70, height=240)
            frame.pack(side="left", padx=2)
            frame.pack_propagate(False)

            ctk.CTkLabel(
                frame,
                text="→",
                font=ctk.CTkFont(size=28, weight="bold"),
                text_color="#5DADE2",
            ).pack(pady=(70, 8))

            chk = ctk.CTkCheckBox(frame, text="继续", variable=var_checked, width=30)
            chk.pack()
            return chk

        self.var_chk1 = ctk.BooleanVar(value=self.config["chk_1"])
        self.var_chk2 = ctk.BooleanVar(value=self.config["chk_2"])
        self.var_chk3 = ctk.BooleanVar(value=self.config["chk_3"])

        box_race, self.btn_race, self.entry_race, self.lbl_race = create_box(
            self.config_frame,
            "1. 循环跑图",
            lambda: self.start_pipeline("race"),
            "#1F6AA5",
            self.config["race_count"],
            "跑图",
        )
        self.entry_share = ctk.CTkEntry(box_race, width=110, justify="center", placeholder_text="蓝图数字代码")
        self.entry_share.insert(0, self.config["share_code"])
        self.entry_share.pack(pady=2)

        self.chk1 = create_arrow(self.config_frame, self.var_chk1)

        box_car, self.btn_car, self.entry_car, self.lbl_car = create_box(
            self.config_frame,
            "2. 批量买车",
            lambda: self.start_pipeline("buy"),
            "#2EA043",
            self.config["buy_count"],
            "买车",
        )
        self.chk2 = create_arrow(self.config_frame, self.var_chk2)

        self.box_cj = ctk.CTkFrame(
            self.config_frame,
            width=300,
            height=240,
            corner_radius=12,
            border_width=1,
            border_color="#2B2B2B",
        )
        self.box_cj.pack_propagate(False)
        self.box_cj.pack(side="left", padx=6)

        top_cj = ctk.CTkFrame(self.box_cj, fg_color="transparent")
        top_cj.pack(fill="x", pady=8)

        left_cj = ctk.CTkFrame(top_cj, fg_color="transparent")
        left_cj.pack(side="left", padx=8)

        ctk.CTkLabel(left_cj, text="3. 超级抽奖", font=ctk.CTkFont(weight="bold", size=16)).pack(pady=(0, 6))

        self.btn_cj = ctk.CTkButton(
            left_cj,
            text="开始",
            width=100,
            height=34,
            corner_radius=10,
            fg_color="#8E44AD",
            hover_color="#8E44AD",
            command=lambda: self.start_pipeline("cj"),
        )
        self.btn_cj.pack(pady=4)

        self.entry_cj = ctk.CTkEntry(left_cj, width=78, height=32, justify="center", corner_radius=8)
        self.entry_cj.insert(0, str(self.config["cj_count"]))
        self.entry_cj.pack(pady=4)

        self.lbl_cj = ctk.CTkLabel(
            left_cj,
            text=f"执行: 0 / {self.config['cj_count']}",
            text_color="#A0A0A0",
            font=ctk.CTkFont(size=12),
        )
        self.lbl_cj.pack(pady=(2, 6))

        dir_frame = ctk.CTkFrame(left_cj, fg_color="transparent")
        dir_frame.pack(pady=4)

        for text, val in [("↑", "up"), ("↓", "down"), ("←", "left"), ("→", "right")]:
            ctk.CTkButton(
                dir_frame,
                text=text,
                width=26,
                height=26,
                corner_radius=8,
                command=lambda x=val: self.add_skill_dir(x),
            ).pack(side="left", padx=2)

        ctk.CTkButton(
            left_cj,
            text="清除矩阵",
            width=78,
            height=26,
            corner_radius=8,
            fg_color="#C0392B",
            hover_color="#A93226",
            command=self.clear_skill_dir,
        ).pack(pady=6)

        self.grid_frame = ctk.CTkFrame(top_cj, fg_color="transparent")
        self.grid_frame.pack(side="right", padx=10)

        self.grid_labels = [[None] * 4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                lbl = ctk.CTkLabel(
                    self.grid_frame,
                    text="",
                    width=24,
                    height=24,
                    corner_radius=5,
                    fg_color="#444444",
                )
                lbl.grid(row=r, column=c, padx=3, pady=3)
                self.grid_labels[r][c] = lbl

        frame_loop = ctk.CTkFrame(
            self.config_frame,
            width=220,
            height=240,
            corner_radius=12,
            border_width=1,
            border_color="#2B2B2B",
        )
        frame_loop.pack(side="left", padx=6)
        frame_loop.pack_propagate(False)

        ctk.CTkLabel(frame_loop, text="LOOP", font=ctk.CTkFont(size=22, weight="bold")).pack(pady=(12, 4))

        self.chk3 = ctk.CTkCheckBox(frame_loop, text="循环清零", variable=self.var_chk3, width=50)
        self.chk3.pack(pady=4)

        ctk.CTkLabel(frame_loop, text="总循环数", font=ctk.CTkFont(size=12)).pack(pady=(8, 2))
        self.entry_global_loop = ctk.CTkEntry(frame_loop, width=80, justify="center")
        self.entry_global_loop.insert(0, str(self.config.get("global_loops", 10)))
        self.entry_global_loop.pack(pady=2)

        self.var_auto_restart = ctk.BooleanVar(value=self.config.get("auto_restart", True))
        self.cb_auto_restart = ctk.CTkCheckBox(
            frame_loop,
            text="游戏闪退自动重启（测试）",
            variable=self.var_auto_restart,
        )
        self.cb_auto_restart.pack(pady=(14, 8))

        self.le_restart_cmd = ctk.CTkEntry(frame_loop, width=180, justify="center", placeholder_text="启动CMD命令")
        self.le_restart_cmd.insert(0, self.config.get("restart_cmd", "start steam://run/2483190"))
        self.le_restart_cmd.pack(pady=2)

        self.running_frame = ctk.CTkFrame(self.top_container, fg_color="#1E1E1E", corner_radius=10, height=10)
        self.running_frame.pack_propagate(False)

        self.lbl_prog_race = ctk.CTkLabel(self.running_frame, text="跑图进度: 0 / 0", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_prog_race.pack(pady=(12, 2))

        self.lbl_prog_buy = ctk.CTkLabel(self.running_frame, text="买车进度: 0 / 0", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_prog_buy.pack(pady=2)

        self.lbl_prog_cj = ctk.CTkLabel(self.running_frame, text="抽奖进度: 0 / 0", font=ctk.CTkFont(size=14, weight="bold"))
        self.lbl_prog_cj.pack(pady=2)

        self.lbl_run_loop = ctk.CTkLabel(
            self.running_frame,
            text="当前执行模块: 等待中...",
            font=ctk.CTkFont(size=13),
            text_color="#3498DB",
        )
        self.lbl_run_loop.pack(pady=(6, 6))

        bottom_frame = ctk.CTkFrame(self, fg_color="transparent", height=160)
        bottom_frame.pack(fill="both", expand=True, padx=14, pady=(4, 10))

        self.btn_stop = ctk.CTkButton(
            bottom_frame,
            text="⏸ 等待指令 (F8)",
            fg_color="#3A3A3A",
            hover_color="#4A4A4A",
            width=150,
            height=54,
            corner_radius=12,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.stop_all,
        )
        self.btn_stop.pack(side="left", padx=5)

        self.res_frame = ctk.CTkFrame(bottom_frame, width=95, fg_color="transparent")
        self.res_frame.pack(side="left", padx=6)

        ctk.CTkLabel(self.res_frame, text="图片原宽", font=ctk.CTkFont(size=12)).pack()
        self.entry_base_w = ctk.CTkEntry(self.res_frame, width=70, justify="center")
        self.entry_base_w.insert(0, str(self.config.get("base_width", 1920)))
        self.entry_base_w.pack(pady=2)

        self.log_box = ctk.CTkTextbox(
            bottom_frame,
            state="disabled",
            wrap="word",
            corner_radius=12,
            height=100,
            font=ctk.CTkFont(size=18),
        )
        self.log_box.pack(side="left", fill="both", expand=True, padx=6)

        self.btn_support = ctk.CTkButton(
            self,
            text="❤ 支持作者 / 检查更新",
            fg_color="#F97316",
            hover_color="#EA580C",
            height=38,
            corner_radius=12,
            font=ctk.CTkFont(weight="bold", size=14),
            command=self.open_support_window,
        )
        self.btn_support.pack(fill="x", padx=15, pady=(5, 10))

    def open_support_window(self):
        if self.support_win is not None and self.support_win.winfo_exists():
            self.support_win.focus()
            return

        self.support_win = ctk.CTkToplevel(self)
        self.support_win.title("感谢支持 & 更新")
        self.support_win.geometry("340x520")
        self.support_win.attributes("-topmost", True)
        self.support_win.resizable(False, False)

        try:
            icon_path = get_asset_path("icon.ico")
            if icon_path:
                self.support_win.iconbitmap(icon_path)
        except Exception:
            pass

        self.support_win.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() - 340) // 2
        y = self.winfo_y() + (self.winfo_height() - 520) // 2
        self.support_win.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            self.support_win,
            text="感谢您的支持与鼓励",
            font=ctk.CTkFont(weight="bold", size=18),
            text_color="#F97316",
        ).pack(pady=(20, 6))

        ctk.CTkLabel(
            self.support_win,
            text="您的支持是我持续优化的动力！",
            font=ctk.CTkFont(size=12),
        ).pack(pady=4)

        qr_path = get_asset_path("qrcode.png")
        try:
            if qr_path and os.path.exists(qr_path):
                img = Image.open(qr_path)
                qr_img = ctk.CTkImage(light_image=img, size=(210, 210))
                qr_label = ctk.CTkLabel(self.support_win, text="", image=qr_img)
                qr_label.image = qr_img
                qr_label.pack(pady=10)
            else:
                ctk.CTkLabel(self.support_win, text="（未找到内置 qrcode.png）", text_color="gray").pack(pady=40)
        except Exception:
            ctk.CTkLabel(self.support_win, text="（二维码加载失败）", text_color="gray").pack(pady=40)

        ctk.CTkButton(
            self.support_win,
            text="前往 爱发电 赞助主页",
            fg_color="#8E44AD",
            hover_color="#7D3C98",
            command=lambda: webbrowser.open("https://ifdian.net/a/yousto"),
        ).pack(pady=5)

        ctk.CTkFrame(self.support_win, height=2, fg_color="#333333").pack(fill="x", padx=20, pady=10)

        self.lbl_version = ctk.CTkLabel(
            self.support_win,
            text=f"当前版本: v{CURRENT_VERSION}",
            text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self.lbl_version.pack()

        def check_update_logic():
            self.ui_call(self.lbl_version.configure, text="正在连接 Github...", text_color="#3498DB")
            try:
                url = "https://raw.githubusercontent.com/YOUSTHEONE/FH6Auto/refs/heads/main/version.json"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    remote_ver = data.get("version", "0.0.0")
                    remote_url = data.get("url", "")

                    if parse_version(remote_ver) > parse_version(CURRENT_VERSION):
                        if remote_url.startswith("https://github.com/YOUSTHEONE/") or remote_url.startswith("https://ifdian.net/"):
                            self.ui_call(
                                self.lbl_version.configure,
                                text=f"发现新版本 v{remote_ver}，已打开浏览器！",
                                text_color="#2EA043",
                            )
                            webbrowser.open(remote_url)
                        else:
                            self.ui_call(
                                self.lbl_version.configure,
                                text="发现更新，但链接不可信，已拦截",
                                text_color="#DA3633",
                            )
                    else:
                        self.ui_call(
                            self.lbl_version.configure,
                            text=f"当前已是最新版本 (v{CURRENT_VERSION})",
                            text_color="gray",
                        )
                else:
                    self.ui_call(
                        self.lbl_version.configure,
                        text="检查更新失败 (服务器异常)",
                        text_color="#DA3633",
                    )
            except Exception:
                self.ui_call(
                    self.lbl_version.configure,
                    text="检查更新失败 (网络超时或无法访问)",
                    text_color="#DA3633",
                )

        btn_frame = ctk.CTkFrame(self.support_win, fg_color="transparent")
        btn_frame.pack(pady=6)

        ctk.CTkButton(
            btn_frame,
            text="检查更新",
            width=100,
            height=30,
            fg_color="#444444",
            hover_color="#555555",
            command=lambda: threading.Thread(target=check_update_logic, daemon=True).start(),
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btn_frame,
            text="GitHub",
            width=100,
            height=30,
            fg_color="#2EA043",
            hover_color="#238636",
            command=lambda: webbrowser.open("https://github.com/YOUSTHEONE/FH6Auto"),
        ).pack(side="left", padx=5)

    def update_running_ui(self, task_name="", current_val=0, max_val=0):
        try:
            self.ui_call(self.lbl_prog_race.configure, text=f"跑图进度: {self.race_counter} / {self.entry_race.get()}")
            self.ui_call(self.lbl_prog_buy.configure, text=f"买车进度: {self.car_counter} / {self.entry_car.get()}")
            self.ui_call(self.lbl_prog_cj.configure, text=f"抽奖进度: {self.cj_counter} / {self.entry_cj.get()}")
            self.ui_call(self.lbl_run_loop.configure, text=f"当前执行模块: 【{task_name}】")
        except Exception:
            pass

    # ==========================================
    # --- 核心操作与流程控制 ---
    # ==========================================
    def hw_key_down(self, key):
        if key not in DIK_CODES:
            return
        scan_code, extended = DIK_CODES[key]
        flags = 0x0008 | (0x0001 if extended else 0)
        extra = ctypes.c_ulong(0)
        ii_ = Input_I()
        ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
        x = Input(ctypes.c_ulong(1), ii_)
        SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

    def hw_key_up(self, key):
        if key not in DIK_CODES:
            return
        scan_code, extended = DIK_CODES[key]
        flags = 0x000A | (0x0001 if extended else 0)
        extra = ctypes.c_ulong(0)
        ii_ = Input_I()
        ii_.ki = KeyBdInput(0, scan_code, flags, 0, ctypes.pointer(extra))
        x = Input(ctypes.c_ulong(1), ii_)
        SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

    def hw_press(self, key, delay=0.08):
        if not self.is_running:
            return
        self.hw_key_down(key)
        time.sleep(delay)
        self.hw_key_up(key)

    def game_click(self, pos, double=False):
        if not self.is_running or not pos:
            return

        pydirectinput.moveTo(int(pos[0]), int(pos[1]))
        time.sleep(0.2)

        for _ in range(2 if double else 1):
            pydirectinput.mouseDown()
            time.sleep(0.1)
            pydirectinput.mouseUp()
            time.sleep(0.1)

        time.sleep(0.1)
        pydirectinput.moveTo(10, 10)
        pydirectinput.move(1, 1)
        time.sleep(0.2)

    def add_skill_dir(self, direction):
        self.config["skill_dirs"].append(direction)
        self.update_skill_grid()
        self.save_config()

    def clear_skill_dir(self):
        self.config["skill_dirs"].clear()
        self.update_skill_grid()
        self.save_config()

    def update_skill_grid(self):
        for r in range(4):
            for c in range(4):
                self.grid_labels[r][c].configure(fg_color="#333333")

        curr_r, curr_c = 3, 0
        self.grid_labels[curr_r][curr_c].configure(fg_color="#3498DB")
        valid_dirs = []

        for d in self.config["skill_dirs"]:
            if d == "up":
                curr_r -= 1
            elif d == "down":
                curr_r += 1
            elif d == "left":
                curr_c -= 1
            elif d == "right":
                curr_c += 1

            if 0 <= curr_r < 4 and 0 <= curr_c < 4:
                self.grid_labels[curr_r][curr_c].configure(fg_color="#3498DB")
                valid_dirs.append(d)
            else:
                break

        self.config["skill_dirs"] = valid_dirs

    def log(self, message):
        curr_time = time.strftime("%H:%M:%S")
        full_msg = f"[{curr_time}] {message}"

        def write_ui():
            try:
                self.log_box.configure(state="normal")
                self.log_box.insert("end", full_msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
            except Exception:
                pass

        self.ui_call(write_ui)

        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(full_msg + "\n")
        except Exception:
            pass

    def load_template(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = actual_path

        if cache_key in self.template_cache:
            return self.template_cache[cache_key], actual_path

        tpl = cv2.imread(actual_path, cv2.IMREAD_COLOR)
        self.template_cache[cache_key] = tpl
        return tpl, actual_path

    # ==========================================
    # --- 逻辑保障 ---
    # ==========================================
    def check_and_focus_game(self):
        self.log("检查游戏进程 (forzahorizon6.exe)...")
        try:
            CREATE_NO_WINDOW = 0x08000000
            cmd = 'tasklist /FI "IMAGENAME eq forzahorizon6.exe" /NH /FO CSV'
            output = subprocess.check_output(cmd, shell=True, text=True, creationflags=CREATE_NO_WINDOW)

            if "forzahorizon6.exe" not in output.lower():
                self.log("未发现 forzahorizon6.exe 进程！(请确保游戏已运行)")
                return False

            target_pid = None
            for line in output.strip().split("\n"):
                parts = line.split('","')
                if len(parts) >= 2 and "forzahorizon6.exe" in parts[0].lower():
                    target_pid = int(parts[1].replace('"', ""))
                    break

            if not target_pid:
                self.log("找到进程但无法解析PID！")
                return False

            hwnds = []

            def foreach_window(hwnd, lParam):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        window_pid = ctypes.c_ulong()
                        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                        if window_pid.value == target_pid:
                            hwnds.append(hwnd)
                return True

            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            ctypes.windll.user32.EnumWindows(EnumWindowsProc(foreach_window), 0)

            if hwnds:
                hwnd = hwnds[0]
                ctypes.windll.user32.ShowWindow(hwnd, 9)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                time.sleep(0.5)

                try:
                    client_rect = win32gui.GetClientRect(hwnd)
                    pt = win32gui.ClientToScreen(hwnd, (0, 0))

                    x, y = pt[0], pt[1]
                    w, h = client_rect[2], client_rect[3]
                    self.update_regions_by_window(x, y, w, h)
                except Exception as e:
                    self.log(f"获取窗口坐标失败: {e}")

                time.sleep(1.0)
                return True

        except Exception as e:
            self.log(f"检查进程异常: {e}")
            return False

        return False

    def restart_game_and_boot(self):
        auto_restart = getattr(self, "var_auto_restart", None)
        if auto_restart is None or not auto_restart.get():
            self.log("未开启自动重启，任务结束。")
            return False

        self.log("触发自动重启机制！正在拉起游戏...")
        try:
            cmd_widget = getattr(self, "le_restart_cmd", None)
            cmd_str = cmd_widget.get() if cmd_widget else self.config.get("restart_cmd", "start steam://run/2483190")
            os.system(cmd_str)
        except Exception as e:
            self.log(f"执行重启命令失败: {e}")
            return False

        self.log("等待游戏启动加载 (10秒)...")
        for _ in range(10):
            if not self.is_running:
                return False
            time.sleep(1)

        self.log("开始持续检测开机界面元素 (限制5分钟)...")
        for _ in range(300):
            if not self.is_running:
                return False

            if self.find_image("horizon6.png", threshold=0.6):
                self.log("识别到欢迎界面，按下回车。")
                self.hw_press("enter")
                time.sleep(4)
                continue

            pos_con = self.find_any_image(["continue-w.png", "continue-b.png"], threshold=0.6)
            if pos_con:
                self.log("识别到继续游戏，点击进入！")
                self.game_click(pos_con)
                time.sleep(10)
                self.log("尝试按 ESC 唤出菜单...")
                self.hw_press("esc")
                time.sleep(2)
                if self.enter_menu():
                    self.log("成功重连并进入菜单，准备恢复执行！")
                    return True
                return False

            time.sleep(2.0)

        self.log("自动重启超时(2分钟未进入漫游)，放弃抢救。")
        return False

    def recover_to_freeroam(self):
        self.log("尝试退回漫游重置状态...")
        for _ in range(30):
            if not self.is_running:
                return False

            if self.find_image("anna.png", region=self.regions["全界面"], threshold=0.5):
                self.log("成功退回漫游界面！")
                return True

            self.hw_press("esc")
            time.sleep(2.0)

        return self.wait_for_freeroam()

    def recover_to_menu(self):
        self.log("尝试退回主菜单重置状态...")
        for _ in range(30):
            if not self.is_running:
                return False

            if self.find_image("collectionjournal.png", region=self.regions["全界面"], threshold=0.55):
                self.log("成功退回主菜单界面！")
                return True

            pos_exit = self.find_any_image(["exit.png", "exit-b.png"], region=self.regions["左下"], threshold=0.85)
            if pos_exit:
                self.log("识别到退出按钮，点击...")
                self.game_click(pos_exit)
                time.sleep(1.5)
                continue

            self.hw_press("esc")
            time.sleep(2.0)

        self.log("多次尝试仍未退回主菜单。")
        return False

    def attempt_recovery(self):
        self.log("任务执行异常中断，准备执行断点恢复流程...")
        if not self.check_and_focus_game():
            if not self.restart_game_and_boot():
                return False
        else:
            if not self.recover_to_menu():
                return False

        self.log("环境重置成功！即将从中断处继续剩余任务。")
        return True

    def wait_for_freeroam(self):
        self.log("验证漫游状态...")
        for i in range(100):
            if not self.is_running:
                return False

            if self.find_image("anna.png", region=self.regions["全界面"], threshold=0.5):
                self.log("验证成功：已确认处于游戏漫游界面。")
                return True

            self.log(f"重试返回漫游界面({i + 1}/100)")
            self.hw_press("esc")

            for _ in range(20):
                if not self.is_running:
                    return False
                time.sleep(0.1)

        self.log("多次尝试验证漫游界面失败，尝试进入菜单。")
        return True

    def enter_menu(self):
        self.log("尝试打开菜单/退回主菜单...")
        menu_anchors = ["collectionjournal.png", "nextstep.png"]

        for i in range(100):
            if not self.is_running:
                return False

            if self.find_any_image(menu_anchors, region=self.regions["全界面"], threshold=0.55):
                self.log("成功停留在菜单页面！")
                return True

            self.log(f"当前视野不在正确菜单页，按 ESC 切换 ({i + 1}/10)...")
            self.hw_press("esc")
            time.sleep(2.0)

        self.log("次尝试进入菜单均失败。")
        return False

    # ==========================================
    # --- 图像寻找 ---
    # ==========================================
    def find_any_image(self, image_list, region=None, threshold=MATCH_THRESHOLD):
        if not self.is_running:
            return None
        for img_path in image_list:
            pos = self.find_image(img_path, region, threshold)
            if pos:
                return pos
        return None

    def find_image(self, template_path, region=None, threshold=0.75):
        try:
            template_orig, actual_path = self.load_template(template_path)
            if template_orig is None:
                self.log(f"找不到文件: {actual_path}")
                return None

            screen = pyautogui.screenshot(region=region)
            screen_bgr = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

            scales_to_try = [1.0]
            full_region = self.regions.get("全界面")
            if full_region:
                curr_w, curr_h = full_region[2], full_region[3]
                common_bases = [1920, 2560, 3840, 1366, 1600, 1280]

                for b in common_bases:
                    sw = round(curr_w / b, 2)
                    sh = round(curr_h / (b * 9 / 16), 2)
                    if 0.3 < sw < 3.0 and sw not in scales_to_try:
                        scales_to_try.append(sw)
                    if 0.3 < sh < 3.0 and sh not in scales_to_try:
                        scales_to_try.append(sh)

                for extra in [0.9, 0.8, 0.7, 0.6, 0.5, 1.1, 1.2]:
                    if extra not in scales_to_try:
                        scales_to_try.append(extra)

            scales_to_try.sort(key=lambda x: abs(x - 1.0))

            for scale in scales_to_try:
                if scale != 1.0:
                    tpl_c = cv2.resize(template_orig, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                else:
                    tpl_c = template_orig.copy()

                if (
                    tpl_c.shape[0] < 5
                    or tpl_c.shape[1] < 5
                    or tpl_c.shape[0] > screen_bgr.shape[0]
                    or tpl_c.shape[1] > screen_bgr.shape[1]
                ):
                    continue

                res_c = cv2.matchTemplate(screen_bgr, tpl_c, cv2.TM_CCOEFF_NORMED)
                _, max_val_c, _, max_loc_c = cv2.minMaxLoc(res_c)

                if max_val_c >= threshold:
                    return (
                        max_loc_c[0] + tpl_c.shape[1] // 2 + (region[0] if region else 0),
                        max_loc_c[1] + tpl_c.shape[0] // 2 + (region[1] if region else 0),
                    )
            return None
        except Exception as e:
            self.log(f"查找图片时发生异常: {e}")
            return None

    def find_image_with_element(self, main_path, sub_path, region=None, threshold=0.85):
        try:
            main_orig, _ = self.load_template(main_path)
            sub_orig, _ = self.load_template(sub_path)

            if main_orig is None or sub_orig is None:
                return None

            screen = pyautogui.screenshot(region=region)
            screen_bgr = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
            scales_to_try = [1.0]

            full_region = self.regions.get("全界面")
            if full_region:
                curr_w, curr_h = full_region[2], full_region[3]
                common_bases = [1920, 2560, 3840, 1366, 1600, 1280]

                for b in common_bases:
                    sw = round(curr_w / b, 2)
                    sh = round(curr_h / (b * 9 / 16), 2)
                    if 0.3 < sw < 3.0 and sw not in scales_to_try:
                        scales_to_try.append(sw)
                    if 0.3 < sh < 3.0 and sh not in scales_to_try:
                        scales_to_try.append(sh)

                for extra in [0.9, 0.8, 0.7, 0.6, 0.5, 1.1, 1.2]:
                    if extra not in scales_to_try:
                        scales_to_try.append(extra)

            scales_to_try.sort(key=lambda x: abs(x - 1.0))

            for scale in scales_to_try:
                if scale != 1.0:
                    main_tpl_c = cv2.resize(main_orig, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                    sub_tpl_c = cv2.resize(sub_orig, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                else:
                    main_tpl_c, sub_tpl_c = main_orig.copy(), sub_orig.copy()

                if (
                    main_tpl_c.shape[0] < 5
                    or main_tpl_c.shape[1] < 5
                    or main_tpl_c.shape[0] > screen_bgr.shape[0]
                    or main_tpl_c.shape[1] > screen_bgr.shape[1]
                ):
                    continue

                h_m, w_m = main_tpl_c.shape[:2]
                res_main_c = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                loc_c = np.where(res_main_c >= threshold)

                for pt in zip(*loc_c[::-1]):
                    x, y = pt
                    sub_roi_c = screen_bgr[
                        max(0, y - 5):min(screen_bgr.shape[0], y + h_m + 5),
                        max(0, x - 5):min(screen_bgr.shape[1], x + w_m + 5),
                    ]

                    if sub_tpl_c.shape[0] > sub_roi_c.shape[0] or sub_tpl_c.shape[1] > sub_roi_c.shape[1]:
                        continue

                    res_sub_c = cv2.matchTemplate(sub_roi_c, sub_tpl_c, cv2.TM_CCOEFF_NORMED)
                    if cv2.minMaxLoc(res_sub_c)[1] >= threshold:
                        return (
                            x + w_m // 2 + (region[0] if region else 0),
                            y + h_m // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception:
            return None

    def start_pipeline(self, start_step):
        if self.is_running:
            return

        self.is_running = True
        self.save_config()

        self.config_frame.pack_forget()
        if hasattr(self, "res_frame"):
            self.res_frame.pack_forget()

        self.running_frame.pack(fill="x", expand=True, pady=(0, 5))
        self.btn_stop.configure(text="停止运行 (F8)", fg_color="#DA3633", hover_color="#B02A37")

        sw = self.winfo_screenwidth()
        mini_w, mini_h = 500, 240
        pos_x = sw - mini_w - 20
        pos_y = 20
        self.attributes("-topmost", True)
        self.geometry(f"{mini_w}x{mini_h}+{pos_x}+{pos_y}")

        self.update_running_ui("初始化中...")
        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.global_loop_current = 0

        def runner():
            if not self.check_and_focus_game():
                self.stop_all()
                return

            steps = ["race", "buy", "cj"]
            curr_idx = steps.index(start_step)

            try:
                total_loops = int(self.entry_global_loop.get())
            except Exception:
                total_loops = self.config.get("global_loops", 10)

            while self.is_running:
                step_name = steps[curr_idx]
                success = False

                try:
                    if step_name == "race":
                        success = self.logic_race(int(self.entry_race.get()))
                    elif step_name == "buy":
                        success = self.logic_buy_car(int(self.entry_car.get()))
                    elif step_name == "cj":
                        success = self.logic_super_wheelspin(int(self.entry_cj.get()))
                except Exception as e:
                    self.log(f"执行模块 {step_name} 时异常: {e}")
                    success = False

                if not self.is_running:
                    break

                if not success:
                    if self.attempt_recovery():
                        continue
                    else:
                        self.log("致命错误：断点恢复失败，彻底停止。")
                        break

                if curr_idx == 0:
                    if self.var_chk1.get():
                        curr_idx = 1
                    else:
                        break
                elif curr_idx == 1:
                    if self.var_chk2.get():
                        curr_idx = 2
                    else:
                        break
                elif curr_idx == 2:
                    if self.var_chk3.get():
                        self.global_loop_current += 1
                        if self.global_loop_current >= total_loops:
                            self.log("达到设定的总循环次数，任务结束。")
                            break
                        self.log(f"开启新一轮完整大循环 ({self.global_loop_current}/{total_loops})")
                        self.race_counter = 0
                        self.car_counter = 0
                        self.cj_counter = 0
                        curr_idx = 0
                    else:
                        break

            self.stop_all()

        self.current_thread = threading.Thread(target=runner, daemon=True)
        self.current_thread.start()

    def stop_all(self):
        if not self.is_running:
            return

        self.is_running = False

        for key in DIK_CODES.keys():
            self.hw_key_up(key)

        for key in ["w", "e", "enter", "esc", "up", "down", "left", "right", "space", "backspace"]:
            self.hw_key_up(key)

        try:
            pydirectinput.mouseUp()
        except Exception:
            pass

        def restore_ui():
            self.running_frame.pack_forget()
            self.config_frame.pack(fill="x")
            self.res_frame.pack(side="left", padx=6, before=self.log_box)
            self.btn_stop.configure(text="等待指令 (F8)", fg_color="#3A3A3A", hover_color="#4A4A4A")
            self.attributes("-topmost", False)
            self.geometry("1080x560")
            self.center_window()

        self.ui_call(restore_ui)
        self.log("!!! 任务已停止，所有物理按键状态已强制重置")

    def start_hotkey_listener(self):
        def hotkey_thread():
            def on_press(k):
                if k == keyboard.Key.f8:
                    self.stop_all()

            with keyboard.Listener(on_press=on_press) as listener:
                listener.join()

        threading.Thread(target=hotkey_thread, daemon=True).start()

    # ==========================================
    # --- 模块：跑图前置与循环跑图 ---
    # ==========================================
    def logic_race(self, target_count):
        if self.race_counter >= target_count:
            return True

        self.update_running_ui("循环跑图", self.race_counter, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        self.log("切换到创意中心...")
        for _ in range(4):
            self.hw_press("pagedown", delay=0.15)
            time.sleep(0.3)

        time.sleep(1.0)
        pos_el = None
        for _ in range(10):
            if not self.is_running:
                return False
            pos_el = self.find_any_image(["eventlab.png", "eventlabcar.png"], region=self.regions["全界面"], threshold=0.5)
            if pos_el:
                break
            time.sleep(0.5)

        if not pos_el:
            self.log("未找到 eventlab")
            return False

        self.game_click(pos_el)
        time.sleep(1.5)

        pos_yg = None
        for _ in range(100):
            if not self.is_running:
                return False
            pos_yg = self.find_image("playenent.png", region=self.regions["中间"])
            if pos_yg:
                break
            time.sleep(1.0)

        if not pos_yg:
            self.log("未找到游玩赛事")
            return False

        self.game_click(pos_yg)
        time.sleep(2.0)

        self.hw_press("backspace")
        time.sleep(1.0)
        self.hw_press("up")
        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(0.8)

        code_text = "".join(c for c in self.entry_share.get() if c.isdigit())
        for char in code_text:
            if char in DIK_CODES:
                self.hw_press(char, delay=0.05)
                time.sleep(0.05)

        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.3)
        self.hw_press("enter")
        time.sleep(2.0)

        pos_ck = None
        for _ in range(100):
            if not self.is_running:
                return False
            pos_ck = self.find_image("VEI.png", region=self.regions["下"])
            if pos_ck:
                break
            time.sleep(2.0)

        if not pos_ck:
            self.log("链接超时超时")
            return False

        self.hw_press("enter")
        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(2.0)

        pos_target = self.find_image_with_element("skillcar.png", "liketag.png", threshold=0.8)
        if not pos_target:
            self.log("未找到带 liketag 的目标车辆，重新选品牌...")
            self.hw_press("backspace")
            time.sleep(1.5)

            found_brand = False
            for _ in range(3):
                if not self.is_running:
                    return False
                pos_brand = self.find_image("skillcarbrand.png", region=self.regions["全界面"])
                if pos_brand:
                    self.game_click(pos_brand)
                    time.sleep(1.5)
                    found_brand = True
                    break
                self.hw_press("up")
                time.sleep(0.5)

            if not found_brand:
                self.log("三次尝试未找到刷图车辆品牌。")
                return False

            for step in range(200):
                if not self.is_running:
                    return False
                pos_target = self.find_image_with_element("skillcar.png", "liketag.png", threshold=0.8)
                if pos_target:
                    break
                if step < 200:
                    for _ in range(4):
                        self.hw_press("right", delay=0.08)
                        time.sleep(0.08)
                    time.sleep(0.8)

        if not pos_target:
            self.log("翻页未能找到带有 liketag 的刷图车辆！")
            return False

        self.game_click(pos_target)
        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(4.0)

        self.log("前置完成，开始循环跑图！")
        while self.race_counter < target_count:
            if not self.is_running:
                return False

            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 找赛事起点...")

            pos = None
            for _ in range(60):
                if not self.is_running:
                    return False
                pos = self.find_any_image(["start.png", "startw.png"], region=self.regions["左下"])
                if pos:
                    break
                time.sleep(1.0)
                self.hw_press("down")

            if not pos:
                self.log("找不到赛事起点，退出跑图。")
                return False

            self.game_click(pos)
            time.sleep(4)
            self.hw_key_down("w")

            start_w = time.time()
            e_pressed = 0
            last_chk = 0
            finished = False

            while self.is_running:
                elap = time.time() - start_w
                if elap >= 3.0 and e_pressed == 0:
                    self.hw_press("e")
                    e_pressed = 1
                elif elap >= 5.0 and e_pressed == 1:
                    self.hw_press("e")
                    e_pressed = 2

                if time.time() - last_chk >= 1.0:
                    if self.find_image("restart.png", region=self.regions["下"]):
                        finished = True
                        break
                    last_chk = time.time()

                time.sleep(0.1)

            self.hw_key_up("w")

            if not finished or not self.is_running:
                return False

            if self.race_counter == target_count - 1:
                self.hw_press("enter")
                time.sleep(2)
            else:
                self.hw_press("x")
                time.sleep(0.8)
                self.hw_press("enter")
                time.sleep(2)

            self.race_counter += 1
            self.update_running_ui("循环跑图", self.race_counter, target_count)

        return True

    # ==========================================
    # --- 模块：买车 ---
    # ==========================================
    def logic_buy_car(self, target_count):
        if self.car_counter >= target_count:
            return True

        self.update_running_ui("批量买车", self.car_counter, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        pos = self.find_image("collectionjournal.png", region=self.regions["全界面"])
        if not pos:
            self.log("进入菜单失败")
            return False

        self.game_click(pos, double=True)
        time.sleep(0.5)

        pos = None
        for _ in range(100):
            if not self.is_running:
                return False
            pos = self.find_image("masterexplorer.png", region=self.regions["全界面"])
            if pos:
                break
            time.sleep(1.0)

        if not pos:
            self.log("未找到探索")
            return False

        self.game_click(pos, double=True)
        time.sleep(0.5)

        pos = None
        for _ in range(100):
            if not self.is_running:
                return False
            pos = self.find_image("carcollection.png", region=self.regions["全界面"])
            if pos:
                break
            time.sleep(0.5)

        if not pos:
            self.log("未找到车辆收集")
            return False

        self.game_click(pos, double=True)
        time.sleep(1.0)

        self.hw_press("backspace")
        time.sleep(0.5)

        brand_pos = None
        for _ in range(15):
            if not self.is_running:
                return False
            brand_pos = self.find_any_image(["CCbrand.png"], region=self.regions["全界面"])
            if brand_pos:
                break
            self.hw_press("up")
            time.sleep(0.3)

        if not brand_pos:
            self.log("未找到品牌")
            return False

        self.game_click(brand_pos)
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.5)

        pos_22b = None
        for _ in range(10):
            if not self.is_running:
                return False
            pos_22b = self.find_image("consumablecar.png", region=self.regions["全界面"])
            if pos_22b:
                break
            time.sleep(0.5)

        if not pos_22b:
            self.log("未找到 消耗品车辆")
            return False

        self.game_click(pos_22b, double=True)
        time.sleep(1.0)

        while self.car_counter < target_count:
            if not self.is_running:
                return False

            self.hw_press("space")
            time.sleep(0.6)
            self.hw_press("down")
            time.sleep(0.2)
            self.hw_press("enter")
            time.sleep(0.6)
            self.hw_press("enter")
            time.sleep(0.6)
            self.hw_press("enter")
            time.sleep(0.6)

            self.car_counter += 1
            self.update_running_ui("批量买车", self.car_counter, target_count)

        for _ in range(5):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(0.8)

        return True

    # ==========================================
    # --- 模块：抽奖 ---
    # ==========================================
    def logic_super_wheelspin(self, target_count):
        if self.cj_counter >= target_count:
            return True

        self.update_running_ui("超级抽奖", self.cj_counter, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        self.log("进入车辆与收藏...")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.5)

        pos_buycar = None
        for _ in range(15):
            if not self.is_running:
                return False
            pos_buycar = self.find_image("BNandUC.png", region=self.regions["左"])
            if pos_buycar:
                break
            time.sleep(0.5)

        if not pos_buycar:
            self.log("未识别到购买车辆")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = None
        for _ in range(30):
            if not self.is_running:
                return False
            pos_bs = self.find_any_image(["buyandsell-w.png", "buyandsell-b.png"], region=self.regions["左"])
            if pos_bs:
                break
            time.sleep(1)

        if not pos_bs:
            self.log("未找到购买与出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1)
        self.hw_press("pagedown", delay=0.15)
        time.sleep(0.5)

        def mark_car_processed(reason=""):
            if reason:
                self.log(reason)
            self.cj_counter += 1
            self.log(f"超级抽奖计数 +1：{self.cj_counter} / {target_count}")
            self.update_running_ui("超级抽奖", self.cj_counter, target_count)

        while self.cj_counter < target_count:
            if not self.is_running:
                return False

            self.log(f"开始寻找第 {self.cj_counter + 1} / {target_count} 辆新车")

            self.hw_press("enter")
            time.sleep(1.0)
            self.hw_press("backspace")
            time.sleep(1)

            brand_pos = None
            for _ in range(30):
                if not self.is_running:
                    return False
                brand_pos = self.find_any_image(["CCbrand.png"], region=self.regions["全界面"])
                if brand_pos:
                    break
                self.hw_press("up")
                time.sleep(0.3)

            if not brand_pos:
                self.log("选品牌失败")
                return False

            self.log("已找到目标品牌，进入品牌车辆列表")
            self.game_click(brand_pos)
            time.sleep(1)

            found_car = False
            for _ in range(85):
                if not self.is_running:
                    return False

                p_car = self.find_image_with_element("newCC.png", "newcartag.png", threshold=0.85)
                if p_car:
                    self.log(f"已找到第 {self.cj_counter + 1} 辆新车，准备进入车辆")
                    self.game_click(p_car)
                    found_car = True
                    break

                for _ in range(4):
                    self.hw_press("right", delay=0.05)
                    time.sleep(0.08)
                time.sleep(0.6)

            if not found_car:
                self.log(f"列表中未找到目标车辆，当前计数：{self.cj_counter} / {target_count}")
                return False

            time.sleep(0.5)
            self.hw_press("enter")
            time.sleep(0.5)
            self.hw_press("enter")
            time.sleep(3)

            # 关键改动：
            # 到这里车辆已经被进入过，new tag 会消失。
            # 所以这里立刻计数，避免后面加点失败导致计数少于实际消耗车辆数。
            mark_car_processed("已进入车辆，new tag 已消失，本车辆按已处理计数。")

            pos_sjy = None
            for _ in range(60):
                if not self.is_running:
                    return False
                self.hw_press("esc")
                time.sleep(1)
                pos_sjy = self.find_any_image(["UandT-w.png", "UandT-b.png"], region=self.regions["左下"])
                if pos_sjy:
                    break

            if not pos_sjy:
                self.log("已计数，但找不到升级页面，跳过本车辆继续下一辆。")
                continue

            self.log("找到升级页面，准备进入熟练度")
            self.hw_press("down")
            time.sleep(0.3)
            self.hw_press("enter")
            time.sleep(1)

            pos_cls = None
            for _ in range(60):
                if not self.is_running:
                    return False
                pos_cls = self.find_any_image(["clsldcnw.png", "clsldcnb.png"], region=self.regions["左下"])
                if pos_cls:
                    break
                time.sleep(1)

            if not pos_cls:
                self.log("已计数，但找不到熟练度入口，跳过本车辆继续下一辆。")
                continue

            self.log("找到熟练度入口，准备加点")
            self.game_click(pos_cls)
            time.sleep(1.5)
            self.hw_press("enter")
            time.sleep(1.5)

            for dk in self.config["skill_dirs"]:
                if not self.is_running:
                    return False
                self.log(f"执行技能方向：{dk}")
                self.hw_press(dk)
                time.sleep(0.2)
                self.hw_press("enter")
                time.sleep(1.5)

            if self.find_image("SPNE.png", region=self.regions["全界面"], threshold=0.7):
                self.log("已无技能点或技能已点完。本车辆已提前计数，准备返回列表。")
                time.sleep(1.0)
                self.hw_press("enter")
                time.sleep(0.8)
                self.hw_press("esc")
                time.sleep(1.0)
                self.hw_press("esc")
                time.sleep(1.0)
                self.hw_press("esc")
                time.sleep(1.0)
                continue

            self.log("技能点击流程完成，准备返回车辆列表")
            self.hw_press("esc")
            time.sleep(1.5)
            self.hw_press("esc")
            time.sleep(0.8)
            self.hw_press("up", delay=0.15)
            time.sleep(1)

        return True


if __name__ == "__main__":
    app = FH_UltimateBot()
    app.mainloop()
