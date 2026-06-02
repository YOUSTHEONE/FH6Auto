import sys
import os
import json
import time
import shutil
import ctypes
import threading
import subprocess
import webbrowser
import traceback

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
from PIL import Image, ImageGrab
from tkinter import messagebox
import win32gui
import pickle


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
CACHE_DIR = os.path.join(APP_DIR, "cache")
TEMPLATE_CACHE_FILE = os.path.join(CACHE_DIR, "template_cache.pkl")
TEMPLATE_META_FILE = os.path.join(CACHE_DIR, "template_meta.json")
DIAGNOSTICS_DIR = os.path.join(APP_DIR, "diagnostics")
CURRENT_VERSION = "1.2.0"
APP_DISPLAY_NAME = "FH6Auto by YSTO | 深度优化 SArB1e"
ORIGINAL_AUTHOR_NAME = "原作者 YSTO"
OPTIMIZER_NAME = "深度优化者 SArB1e"
ORIGINAL_AFDIAN_URL = "https://ifdian.net/a/yousto"
OPTIMIZER_AFDIAN_URL = "https://afdian.com/a/SArB1e"
OPTIMIZER_GITHUB_URL = "https://github.com/HikigayaHachiman0211"

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
    # control
    "esc": (0x01, False),
    "enter": (0x1C, False),
    "space": (0x39, False),
    "backspace": (0x0E, False),
    "tab": (0x0F, False),
    "lshift": (0x2A, False),
    "rshift": (0x36, False),
    "lctrl": (0x1D, False),
    "rctrl": (0x1D, True),
    "lalt": (0x38, False),
    "ralt": (0x38, True),
    "capslock": (0x3A, False),

    # letters
    "a": (0x1E, False),
    "b": (0x30, False),
    "c": (0x2E, False),
    "d": (0x20, False),
    "e": (0x12, False),
    "f": (0x21, False),
    "g": (0x22, False),
    "h": (0x23, False),
    "i": (0x17, False),
    "j": (0x24, False),
    "k": (0x25, False),
    "l": (0x26, False),
    "m": (0x32, False),
    "n": (0x31, False),
    "o": (0x18, False),
    "p": (0x19, False),
    "q": (0x10, False),
    "r": (0x13, False),
    "s": (0x1F, False),
    "t": (0x14, False),
    "u": (0x16, False),
    "v": (0x2F, False),
    "w": (0x11, False),
    "x": (0x2D, False),
    "y": (0x15, False),
    "z": (0x2C, False),

    # number row
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

    # arrows / navigation
    "up": (0xC8, True),
    "down": (0xD0, True),
    "left": (0xCB, True),
    "right": (0xCD, True),
    "pageup": (0xC9, True),
    "pagedown": (0xD1, True),
    "home": (0xC7, True),
    "end": (0xCF, True),
    "insert": (0xD2, True),
    "delete": (0xD3, True),

    # function keys
    "f1": (0x3B, False),
    "f2": (0x3C, False),
    "f3": (0x3D, False),
    "f4": (0x3E, False),
    "f5": (0x3F, False),
    "f6": (0x40, False),
    "f7": (0x41, False),
    "f8": (0x42, False),
    "f9": (0x43, False),
    "f10": (0x44, False),
    "f11": (0x57, False),
    "f12": (0x58, False),
}

# --- 全局配置 ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")
MATCH_THRESHOLD = 0.8
pyautogui.FAILSAFE = False


class FH_UltimateBot(ctk.CTk):
    def __init__(self):
        super().__init__()
        #窗口相关
        self.title(f"{APP_DISPLAY_NAME} v{CURRENT_VERSION}")
        self.geometry("1800x800")
        self.minsize(1280, 720)
        self.attributes("-topmost", False)
        self.attributes("-alpha", 0.98)
        self.resizable(True, True)

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
        self.sc_count = 0
        self.global_loop_current = 0

        self.template_cache = {}
        self.scaled_template_cache = {}
        self.file_template_cache = {}
        self.last_positions = {}
        self.support_win = None
        self.template_debug_win = None
        self.template_debug_rows = {}
        self.template_debug_issue_text = None
        self.template_debug_search_var = None
        self.template_debug_filter_var = None
        self.template_debug_category_var = None
        self.template_debug_images = []
        self.template_debug_syncing = False
        self.template_debug_all_items = []
        self.template_debug_filtered_items = []
        self.template_debug_pending_thresholds = {}
        self.template_debug_page = 0
        self.template_debug_page_size = 35
        self.template_debug_page_label = None
        self.template_debug_prev_btn = None
        self.template_debug_next_btn = None
        self.template_match_records = []
        self.template_match_records_lock = threading.Lock()
        self.template_match_issue_map = {}
        self.template_match_last_log_at = {}
        self.template_file_list_cache = None
        self.template_group_members_cache = None
        self.edge_template_cache = {}
        self.scaled_edge_template_cache = {}
        self.current_step_name = ""
        self.last_failure_context = None
        self.pipeline_next_step_override = None
        self.filter_panel_region = None
        self.filter_fast_scales = None
        self.failure_snapshot_lock = threading.Lock()
        self.failure_snapshot_counter = 0
        self.failure_snapshot_cooldown = {}
        self.process_guard_thread = None
        self.process_guard_stop_event = None
        self.process_guard_seen_process = False
        self.process_lost_event = threading.Event()
        self.recovery_in_progress = threading.Event()
        self.app_closing = threading.Event()
        self.sell_tail_position_ready = False
        self.sell_fresh_skip_count = 0
        self.sell_stop_no_deletable = False

        self.init_regions()

        # 【优化加载速度】：将IO提取与图像缓存的加载/生成放到后台线程，避免阻塞主界面启动
        def background_init():
            auto_extract_images()
            self.prepare_template_cache()
        threading.Thread(target=background_init, daemon=True).start()

        #初始配置
        self.config = {
            "race_count": 99,
            "buy_count": 30,
            "cj_count": 30,
            "sc_count": 30,
            "chk_1": True,
            "chk_2": True,
            "chk_3": True,
            "chk_4": True,
            "next_1": 2,
            "next_2": 3,
            "next_3": 1,
            "next_4": 1,
            "global_loops": 10,
            "skill_dirs": ["right", "up", "up", "up", "left"],
            "share_code": "705399298",
            "race_car_type": "s1_790",
            "auto_restart": False,
            "restart_cmd": "start steam://run/2483190",
            "race_stall_timeout_seconds": 60,
            "race_restart_timeout_seconds": 150,
            "race_reverse_seconds": 3,
            "process_guard_enabled": True,
            "process_guard_interval_seconds": 120,
            "cj_car_right_offset": 0,
            "super_calc_target": "",
            "super_calc_race_sp": "10",
            "super_calc_spin_sp": "30",
            "cr_car_type": "wuling",
            "cr_settlement_enabled": True,
            "cr_settlement_laps": 5,
            "cr_shortfall_fallback_enabled": True,
            "cr_shortfall_car_type": "wuling",
            "cr_shortfall_settlement_laps": 5,
            "cr_shortfall_car_cost": 85000,
            "cr_wuling_lap_seconds": 340,
            "cr_toyota_lap_seconds": 380,
            "cr_step_retry_count": 3,
            "step_retry_enabled": False,
            "general_step_retry_count": 2,
            "cr_click_wait_seconds": 0.8,
            "cr_page_load_wait_seconds": 2.0,
            "cr_rival_data_initial_wait_seconds": 5,
            "cr_rival_apply_wait_seconds": 5,
            "cr_guard_interval_seconds": 60,
            "cr_unknown_error_enter_interval_seconds": 5,
            "general_menu_retry_wait_seconds": 0.6,
            "general_image_timeout_multiplier": 1.0,
            "general_click_wait_multiplier": 1.0,
            "general_vehicle_move_wait_seconds": 0.08,
            "filter_strict_click_verify": False,
            "like_guard_enabled": True,
            "like_guard_stall_seconds": 180,
            "like_guard_max_prompt_passes": 3,
            "skip_startup_prompts": False,
            "template_thresholds": {},
            "template_match_debug_enabled": True,
        }
        self.load_config()
        if not isinstance(self.config.get("template_thresholds"), dict):
            self.config["template_thresholds"] = {}

        self.setup_ui()
        self.start_hotkey_listener()
        self.update_skill_grid()
        self.center_window()
        self.log("免责声明：本脚本仅供 Python 自动化技术交流与学习使用。请勿用于商业盈利或破坏游戏平衡，因使用本脚本造成的账号封禁等损失，由使用者自行承担。")
        self.log(f"当前刷图车辆：{self.get_race_car_display_text()}")
        self.log("启动前先将键盘设置为【英文键盘】")
        self.log("游戏设置为【难度所向披靡】【自动转向】【自动挡】，游戏语言设置为【简体中文】")
        self.log("重要提醒：脚本会通过【设计与喷漆】页面快速选车，请提前进入该界面并将提示弹窗选择【不再显示此消息】。")
        self.log("大部分以图像识别作为引导，减少机器盲目操作的风险，但仍无法完全避免，使用前请做好准备")
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)
        self.after(1000, self.start_process_guard_thread)

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
        gx, gy, gw, gh = self.regions["全界面"]
        x = gx + (gw - w) // 2
        y = gy + (gh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def on_app_close(self):
        self.app_closing.set()
        try:
            if self.is_running:
                self.stop_all()
            self.stop_process_guard_thread()
        finally:
            self.destroy()

    def sync_buy_to_sell(self, event=None):
        try:
            val = "".join(c for c in self.entry_car.get() if c.isdigit())
            if val == "":
                val = "0"
            self.entry_sc.delete(0, "end")
            self.entry_sc.insert(0, val)
        except Exception:
            pass

    def normalize_step_entry(self, entry_widget, default_value):
        try:
            v = "".join(c for c in entry_widget.get() if c.isdigit())
            if v == "":
                v = str(default_value)
            iv = int(v)
            if iv < 1:
                iv = 1
            if iv > 4:
                iv = 4
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(iv))
        except Exception:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(default_value))

    def normalize_positive_entry(self, entry_widget, default_value, min_value=1):
        try:
            v = "".join(c for c in entry_widget.get() if c.isdigit())
            if v == "":
                v = str(default_value)
            iv = int(v)
            if iv < min_value:
                iv = min_value
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(iv))
        except Exception:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(default_value))

    def get_positive_entry_value(self, entry_widget, default_value, min_value=1):
        try:
            v = "".join(c for c in entry_widget.get() if c.isdigit())
            value = int(v) if v else int(default_value)
        except Exception:
            value = int(default_value)

        if value < min_value:
            value = min_value

        try:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(value))
        except Exception:
            pass

        return value
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
            self.config["sc_count"] = int(self.entry_sc.get())
            self.config["global_loops"] = int(self.entry_global_loop.get())
            self.config["share_code"] = "".join(c for c in self.entry_share.get() if c.isdigit())
            #self.config["base_width"] = int(self.entry_base_w.get())
            self.config["next_1"] = int(self.entry_next1.get())
            self.config["next_2"] = int(self.entry_next2.get())
            self.config["next_3"] = int(self.entry_next3.get())
            self.config["next_4"] = int(self.entry_next4.get())
        except Exception:
            pass

        if hasattr(self, "entry_race_stall_timeout"):
            self.config["race_stall_timeout_seconds"] = self.get_positive_entry_value(
                self.entry_race_stall_timeout,
                self.config.get("race_stall_timeout_seconds", 60),
            )
        if hasattr(self, "entry_race_restart_timeout"):
            self.config["race_restart_timeout_seconds"] = self.get_positive_entry_value(
                self.entry_race_restart_timeout,
                self.config.get("race_restart_timeout_seconds", 150),
            )
        if hasattr(self, "entry_race_reverse_seconds"):
            self.config["race_reverse_seconds"] = self.get_positive_entry_value(
                self.entry_race_reverse_seconds,
                self.config.get("race_reverse_seconds", 3),
            )
        self.config["process_guard_interval_seconds"] = self.get_positive_entry_value(
            self.entry_process_guard_interval,
            self.config.get("process_guard_interval_seconds", 120),
        )
        if hasattr(self, "var_process_guard_enabled"):
            self.config["process_guard_enabled"] = bool(self.var_process_guard_enabled.get())

        self.config["chk_1"] = self.var_chk1.get()
        self.config["chk_2"] = self.var_chk2.get()
        self.config["chk_3"] = self.var_chk3.get()
        self.config["chk_4"] = self.var_chk4.get()
        self.config["auto_restart"] = self.var_auto_restart.get()
        self.config["restart_cmd"] = self.le_restart_cmd.get().strip()
        if hasattr(self, "var_4k_experimental"):
            self.config["enable_4k_experimental"] = bool(self.var_4k_experimental.get())
        if hasattr(self, "var_step_retry_enabled"):
            self.config["step_retry_enabled"] = bool(self.var_step_retry_enabled.get())
        if hasattr(self, "var_filter_strict_click_verify"):
            self.config["filter_strict_click_verify"] = bool(self.var_filter_strict_click_verify.get())
        if hasattr(self, "var_like_guard_enabled"):
            self.config["like_guard_enabled"] = bool(self.var_like_guard_enabled.get())
        if hasattr(self, "var_skip_startup_prompts"):
            self.config["skip_startup_prompts"] = bool(self.var_skip_startup_prompts.get())
        if hasattr(self, "var_template_match_debug_enabled"):
            self.config["template_match_debug_enabled"] = bool(self.var_template_match_debug_enabled.get())
        if hasattr(self, "entry_like_guard_stall_seconds"):
            self.config["like_guard_stall_seconds"] = self.get_positive_entry_value(
                self.entry_like_guard_stall_seconds,
                self.config.get("like_guard_stall_seconds", 180),
            )
        if hasattr(self, "option_race_car_type"):
            self.config["race_car_type"] = "s1_790" if self.option_race_car_type.get() == "S1 790" else "s2_900"
        if hasattr(self, "option_cr_car_type"):
            self.config["cr_car_type"] = "toyota" if self.option_cr_car_type.get() == "丰田" else "wuling"
        if hasattr(self, "var_cr_settlement_enabled"):
            self.config["cr_settlement_enabled"] = bool(self.var_cr_settlement_enabled.get())
        if hasattr(self, "entry_cr_settlement_laps"):
            self.config["cr_settlement_laps"] = self.get_positive_entry_value(
                self.entry_cr_settlement_laps,
                self.config.get("cr_settlement_laps", 5),
            )
        if hasattr(self, "entry_cr_lap_seconds"):
            self.save_current_cr_lap_seconds_to_config(normalize_entry=True)
        if hasattr(self, "entry_cr_step_retry_count"):
            self.config["cr_step_retry_count"] = self.get_positive_entry_value(
                self.entry_cr_step_retry_count,
                self.config.get("cr_step_retry_count", 3),
            )
        if hasattr(self, "var_cr_shortfall_fallback_enabled") and self.var_cr_shortfall_fallback_enabled is not None:
            try:
                self.config["cr_shortfall_fallback_enabled"] = bool(self.var_cr_shortfall_fallback_enabled.get())
            except Exception:
                pass
        if hasattr(self, "option_cr_shortfall_car_type") and self.option_cr_shortfall_car_type is not None:
            try:
                self.config["cr_shortfall_car_type"] = (
                    "toyota" if self.option_cr_shortfall_car_type.get() == "丰田" else "wuling"
                )
            except Exception:
                pass
        if hasattr(self, "entry_cr_shortfall_settlement_laps") and self.entry_cr_shortfall_settlement_laps is not None:
            try:
                self.config["cr_shortfall_settlement_laps"] = self.get_positive_entry_value(
                    self.entry_cr_shortfall_settlement_laps,
                    self.config.get("cr_shortfall_settlement_laps", self.config.get("cr_settlement_laps", 5)),
                )
            except Exception:
                pass
        self.config.pop("race_car_template", None)
        self.config.pop("race_car_fallback_enabled", None)
        try:
            if hasattr(self, "entry_calc_a"):
                self.config["calc_a"] = self.entry_calc_a.get().strip()
                self.config["calc_b"] = self.entry_calc_b.get().strip()
                self.config["calc_c"] = self.entry_calc_c.get().strip()
            if hasattr(self, "entry_super_calc_target"):
                self.config["super_calc_target"] = self.entry_super_calc_target.get().strip()
                self.config["super_calc_race_sp"] = self.entry_super_calc_race_sp.get().strip()
                self.config["super_calc_spin_sp"] = self.entry_super_calc_spin_sp.get().strip()
        except Exception:
            pass
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def save_runtime_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception:
            pass

    def open_cr_shortfall_settings_window(self):
        win = ctk.CTkToplevel(self)
        win.title("CR不足兜底设置")
        win.geometry("460x360")
        win.resizable(False, False)
        win.attributes("-topmost", True)

        frame = ctk.CTkFrame(win, corner_radius=10)
        frame.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            frame,
            text="CR不足兜底",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#F5B041",
        ).pack(pady=(14, 8))
        ctk.CTkLabel(
            frame,
            text="买 22B 前检测当前 CR；不足时自动刷 CR 到足够完成本轮买车循环。",
            wraplength=390,
            justify="center",
            text_color="#D0D0D0",
        ).pack(pady=(0, 12))

        var_enabled = ctk.BooleanVar(
            value=bool(self.config.get("cr_shortfall_fallback_enabled", True))
        )
        ctk.CTkCheckBox(
            frame,
            text="启用 CR 不足自动兜底",
            variable=var_enabled,
        ).pack(anchor="w", padx=38, pady=(4, 12))

        row_car = ctk.CTkFrame(frame, fg_color="transparent")
        row_car.pack(fill="x", padx=38, pady=6)
        ctk.CTkLabel(row_car, text="刷 CR 车辆:", width=110, anchor="w").pack(side="left")
        option_car = ctk.CTkOptionMenu(row_car, width=120, values=["五菱", "丰田"])
        option_car.set(
            "丰田" if self.config.get("cr_shortfall_car_type", self.config.get("cr_car_type", "wuling")) == "toyota" else "五菱"
        )
        option_car.pack(side="left")

        row_laps = ctk.CTkFrame(frame, fg_color="transparent")
        row_laps.pack(fill="x", padx=38, pady=6)
        ctk.CTkLabel(row_laps, text="几圈结算一次:", width=110, anchor="w").pack(side="left")
        entry_laps = ctk.CTkEntry(row_laps, width=80, justify="center")
        entry_laps.insert(
            0,
            str(self.config.get("cr_shortfall_settlement_laps", self.config.get("cr_settlement_laps", 5))),
        )
        entry_laps.pack(side="left")

        summary = ctk.CTkLabel(
            frame,
            text=f"计算规则：剩余买车数 × {self.get_cr_shortfall_car_cost():,} CR",
            text_color="#A0A0A0",
            wraplength=390,
        )
        summary.pack(pady=(14, 8))

        def save_shortfall_settings():
            self.config["cr_shortfall_fallback_enabled"] = bool(var_enabled.get())
            self.config["cr_shortfall_car_type"] = (
                "toyota" if option_car.get() == "丰田" else "wuling"
            )
            self.config["cr_shortfall_settlement_laps"] = self.get_positive_entry_value(
                entry_laps,
                self.config.get("cr_shortfall_settlement_laps", self.config.get("cr_settlement_laps", 5)),
            )
            self.save_runtime_config()
            self.log(
                "CR不足兜底设置已保存："
                f"{'启用' if self.config['cr_shortfall_fallback_enabled'] else '关闭'}，"
                f"车辆 {'丰田' if self.config['cr_shortfall_car_type'] == 'toyota' else '五菱'}，"
                f"{self.config['cr_shortfall_settlement_laps']} 圈结算。"
            )
            win.destroy()

        ctk.CTkButton(
            frame,
            text="保存",
            width=130,
            height=34,
            fg_color="#2EA043",
            hover_color="#238636",
            command=save_shortfall_settings,
        ).pack(pady=(10, 4))

    def get_template_key(self, template_path):
        return os.path.basename(str(template_path or "")).replace("\\", "/")

    def clamp_template_threshold(self, value, default_value=0.75):
        try:
            value = float(value)
        except Exception:
            value = float(default_value)
        return max(0.30, min(0.95, value))

    def get_template_threshold(self, template_path, default_threshold):
        thresholds = self.config.get("template_thresholds")
        if not isinstance(thresholds, dict):
            thresholds = {}
            self.config["template_thresholds"] = thresholds

        key = self.get_template_key(template_path)
        if key in thresholds:
            return self.clamp_template_threshold(thresholds.get(key), default_threshold)
        return float(default_threshold)

    def set_template_threshold(self, template_path, threshold):
        key = self.get_template_key(template_path)
        if not key:
            return
        thresholds = self.config.setdefault("template_thresholds", {})
        thresholds[key] = round(self.clamp_template_threshold(threshold), 2)

    def reset_template_threshold(self, template_path):
        thresholds = self.config.setdefault("template_thresholds", {})
        thresholds.pop(self.get_template_key(template_path), None)

    def is_template_match_debug_enabled(self):
        var_widget = self.__dict__.get("var_template_match_debug_enabled")
        if var_widget is not None:
            try:
                return bool(var_widget.get())
            except Exception:
                pass
        return bool(self.config.get("template_match_debug_enabled", True))

    def get_images_root_dir(self):
        external_dir = os.path.join(APP_DIR, "images")
        if os.path.isdir(external_dir):
            return external_dir
        internal_dir = os.path.join(INTERNAL_DIR, "images")
        if os.path.isdir(internal_dir):
            return internal_dir
        return None

    def list_template_files(self):
        if self.template_file_list_cache is not None:
            return list(self.template_file_list_cache)

        images_dir = self.get_images_root_dir()
        if not images_dir:
            return []

        valid_exts = {".png", ".jpg", ".jpeg", ".bmp"}
        templates = []
        try:
            for root, _, files in os.walk(images_dir):
                for file_name in files:
                    ext = os.path.splitext(file_name)[1].lower()
                    if ext not in valid_exts:
                        continue
                    full_path = os.path.join(root, file_name)
                    rel_path = os.path.relpath(full_path, images_dir).replace("\\", "/")
                    templates.append({
                        "name": file_name,
                        "rel_path": rel_path,
                        "full_path": full_path,
                    })
        except Exception:
            return []
        templates.sort(key=lambda item: item["rel_path"].lower())
        self.template_file_list_cache = list(templates)
        self.template_group_members_cache = None
        return templates

    def get_template_metadata_overrides(self):
        return {
            "designandpaint_w.png": ("CJ", "cj_design_paint", "白底入口", "CJ 超级抽奖：车辆页入口-设计与喷漆，白底状态"),
            "designandpaint-b.png": ("CJ", "cj_design_paint", "黑底入口", "CJ 超级抽奖：车辆页入口-设计与喷漆，黑底/选中状态"),
            "choosecar.png": ("CJ", "cj_choose_car", "白底入口", "CJ 超级抽奖：设计与喷漆内的选择车辆入口，白底状态"),
            "choosecar-b.png": ("CJ", "cj_choose_car", "黑底入口", "CJ 超级抽奖：设计与喷漆内的选择车辆入口，黑底/选中状态"),
            "UandT-w.png": ("CJ", "cj_upgrade_tuning", "白底入口", "CJ 超级抽奖：升级与调教入口，白底状态"),
            "UandT-b.png": ("CJ", "cj_upgrade_tuning", "黑底入口", "CJ 超级抽奖：升级与调教入口，黑底/选中状态"),
            "clsldcnw.png": ("CJ", "cj_skill_tree", "白底入口", "CJ 超级抽奖：车辆熟练度/技能树入口，白底状态"),
            "clsldcnb.png": ("CJ", "cj_skill_tree", "黑底入口", "CJ 超级抽奖：车辆熟练度/技能树入口，黑底/选中状态"),
            "FreshTagText.png": ("删车/CJ", "fresh_car_tag", "全新文字", "删车保护/CJ 选车：车辆卡片上的全新标签文字，检测到则禁止删车"),
            "newcartag.png": ("CJ", "fresh_car_tag", "全新图标", "CJ 选车：车辆卡片上的全新标签图标，用于定位待抽奖车辆"),
            "SPNE.png": ("CJ", "cj_skill_state", "技能点不足", "CJ 超级抽奖：技能点不足或技能已点完提示"),
            "EXPwU.png": ("CJ", "cj_skill_state", "经验技能", "CJ 超级抽奖：经验技能已升级/可用状态"),
            "DSI.png": ("CJ", "cj_prompt", "不再显示", "设计与喷漆首次提示：不再显示该消息"),
            "buyandsell-w.png": ("车辆菜单", "buy_and_sell", "白底入口", "车辆菜单：购买与出售入口，白底状态"),
            "buyandsell-b.png": ("车辆菜单", "buy_and_sell", "黑底入口", "车辆菜单：购买与出售入口，黑底/选中状态"),
            "BNandUC.png": ("车辆菜单", "festival_buy_used", "入口", "嘉年华车辆与收藏：购买新车与二手车入口"),
            "RemoveFromGarageWhite.png": ("删车", "remove_from_garage", "白底选项", "删车：操作菜单中的从车库移除车辆选项，白底状态"),
            "RemoveFromGarageBlack.png": ("删车", "remove_from_garage", "黑底选项", "删车：操作菜单中的从车库移除车辆选项，黑底/选中状态"),
            "rc.png": ("车辆菜单", "car_action_menu", "操作菜单", "车辆操作菜单：上车/移除等操作弹窗锚点"),
            "collectionjournal.png": ("买车", "buy_collection_journal", "入口", "批量买车：嘉年华播放列表内的车辆收集簿入口"),
            "masterexplorer.png": ("买车", "buy_master_explorer", "入口", "批量买车：车辆收集簿内探索分类入口"),
            "carcollection.png": ("买车", "buy_car_collection", "入口", "批量买车：车辆收集页面入口"),
            "CCbrand.png": ("买车", "subaru_brand", "品牌筛选", "批量买车/CJ：斯巴鲁品牌筛选项"),
            "consumablecar.png": ("买车", "subaru_22b_buy", "目标车辆", "批量买车：目标消耗品车辆 Subaru 22B"),
            "Subaru22BScore0706.png": ("车辆/品牌", "subaru_22b", "车辆卡片", "车辆识别：Subaru 22B 分数/卡片特征"),
            "SubaruBrandFocused.png": ("车辆/品牌", "subaru_brand_state", "聚焦", "品牌筛选：Subaru 品牌聚焦状态"),
            "SubaruBrandUnfocused.png": ("车辆/品牌", "subaru_brand_state", "未聚焦", "品牌筛选：Subaru 品牌未聚焦状态"),
            "skillcar.png": ("赛事", "race_skill_car_like", "S2车辆主模板", "刷图/CJ：S2 900 技能车主模板，需要与 liketag 组合确认"),
            "SkillCarS1790.png": ("赛事", "race_skill_car_like", "S1车辆主模板", "刷图/CJ：S1 790 技能车主模板，需要与 liketag 组合确认"),
            "liketag.png": ("赛事", "race_skill_car_like", "车辆标签", "刷图/CJ：车辆卡片点赞/收藏标签，用于组合验证技能车"),
            "LikeW2.png": ("赛后评分", "post_race_like", "白底点赞", "赛后评分：点赞按钮白底状态"),
            "LikeB2.png": ("赛后评分", "post_race_like", "黑底点赞", "赛后评分：点赞按钮黑底/选中状态"),
            "CancelW2.png": ("赛后评分", "post_race_cancel", "白底取消", "赛后评分：取消按钮白底状态"),
            "CancelB2.png": ("赛后评分", "post_race_cancel", "黑底取消", "赛后评分：取消按钮黑底/选中状态"),
            "DislikeW2.png": ("赛后评分", "post_race_dislike", "点踩", "赛后评分：点踩按钮白底状态"),
            "CRPoint.png": ("CR", "cr_read_anchor", "大号CR锚点", "CR 检测：CR 点数字前的大号 CR 锚点"),
            "CRPointSmall.png": ("CR", "cr_read_anchor", "小号CR锚点", "CR 检测：CR 点数字前的小号 CR 锚点"),
            "ServerError.png": ("错误处理", "server_error", "服务器错误", "刷图/刷CR：服务器错误提示"),
            "ServerErrorCantUpdateFormidableAdversaryData.png": ("错误处理", "server_error", "劲敌数据错误", "刷CR：无法更新劲敌数据提示"),
            "ServerErrorSolved.png": ("错误处理", "server_error", "错误已处理", "服务器错误恢复/关闭后的确认状态"),
            "ControllerDisconnect.png": ("错误处理", "controller_disconnect", "手柄断连", "全局守护：控制器断开提示"),
            "NoAvailableCars.png": ("CJ", "cj_no_available_car", "无可用车", "CJ/选车：没有可用车辆提示"),
            "NoBlack.png": ("按钮", "yes_no", "否黑底", "确认弹窗：否/取消黑底状态"),
            "NoWhite.png": ("按钮", "yes_no", "否白底", "确认弹窗：否/取消白底状态"),
            "YesBlack.png": ("按钮", "yes_no", "是黑底", "确认弹窗：是/确认黑底状态"),
            "YesWhite.png": ("按钮", "yes_no", "是白底", "确认弹窗：是/确认白底状态"),
        }

    def infer_template_group_id(self, template_name, fallback):
        name = self.get_template_key(template_name)
        stem = os.path.splitext(name)[0]
        normalized = stem
        for suffix in ("Black", "White", "-b", "-w", "_w"):
            normalized = normalized.replace(suffix, "")
        normalized = normalized.replace("FullChecked", "").replace("FullUnchecked", "")
        normalized = normalized.replace("Checked", "").replace("Unchecked", "")
        return normalized.lower() or fallback

    def infer_template_metadata(self, template_name):
        name = self.get_template_key(template_name)
        lower = name.lower()
        stem = os.path.splitext(name)[0]
        overrides = self.get_template_metadata_overrides()
        if name in overrides:
            category, group_id, role, description = overrides[name]
            return {"category": category, "group_id": group_id, "role": role, "description": description}

        filter_prefixes = {
            "Duplicate": ("删车筛选", "filter_duplicate", "重复项筛选"),
            "ClassB": ("删车筛选", "filter_class_b", "B 级筛选"),
            "AllWheelDrive": ("删车筛选", "filter_awd", "全轮驱动筛选"),
            "Legendary": ("删车筛选", "filter_legendary", "传奇稀有度筛选"),
            "ForzaEdition": ("删车筛选", "filter_forza_edition", "Forza Edition 筛选"),
            "RearWheelDrive": ("删车筛选", "filter_rwd", "后轮驱动筛选"),
            "TrackToys": ("删车筛选", "filter_track_toys", "Track Toys 类型筛选"),
        }
        for prefix, (category, group_id, label) in filter_prefixes.items():
            if name.startswith(prefix):
                color = "黑底" if "Black" in name else "白底"
                state = "已勾选" if "Checked" in name else "未勾选"
                full = "整行状态" if "Full" in name else "局部状态"
                return {
                    "category": category,
                    "group_id": group_id,
                    "role": f"{color}{state}{full}",
                    "description": f"删车筛选：{label}，{color}/{state}/{full} 模板",
                }

        brand_names = {
            "Toyota": "Toyota/丰田",
            "ToyotaBlack": "Toyota/丰田",
            "ToyotaWhite": "Toyota/丰田",
            "ToyotaRaceCar": "丰田刷CR车辆",
            "ToyotaAE86SpecialMisdetect": "丰田 AE86 误识别排除模板",
            "Wuling": "Wuling/五菱",
            "WulingBlack": "Wuling/五菱",
            "WulingRaceCar": "五菱刷CR车辆",
            "WulingRaceCar2": "五菱刷CR车辆备用",
            "Hyundai": "Hyundai/现代",
            "Chevrolet": "Chevrolet/雪佛兰",
            "Volvo": "Volvo/沃尔沃",
        }
        if stem in brand_names:
            base = stem.replace("Black", "").replace("White", "").replace("RaceCar2", "RaceCar")
            role = "黑底状态" if "Black" in stem else "白底状态" if "White" in stem else "车辆/品牌"
            return {
                "category": "车辆/品牌",
                "group_id": f"brand_{base.lower()}",
                "role": role,
                "description": f"车辆/品牌识别：{brand_names[stem]}，{role}",
            }

        if lower.startswith("cr_credits/") or name in [f"{i}.png" for i in range(10)] or stem.isdigit():
            return {
                "category": "数字识别",
                "group_id": "cr_digit_templates",
                "role": f"数字 {stem}",
                "description": f"CR 检测：数字识别模板 {stem}",
            }

        if "formidableadversary" in lower or "race" in lower or name in {
            "AutoDriveOn.png", "eventlab.png", "eventlabcar.png", "RoadRacing.png",
            "CreativeCenter.png", "Online.png", "horizon6.png", "start.png", "startw.png",
            "restart.png", "nextstep.png", "playenent.png", "Enter.png", "exit.png", "exit-b.png",
            "ExitRaceConfirm.png", "RestartRace.png", "RestartRaceConfirm.png", "RestartRaceConfirmPage.png",
        }:
            return {
                "category": "赛事",
                "group_id": self.infer_template_group_id(name, "race_flow"),
                "role": "赛事流程锚点",
                "description": f"刷图/刷CR赛事流程：{stem} 页面、按钮或状态锚点",
            }

        if name in {"Filter.png", "FilterPanel.png", "FilterDriveTypeHeader.png", "DriveTypeHeader.png", "RarityHeader.png"}:
            return {
                "category": "删车筛选",
                "group_id": "filter_panel",
                "role": "筛选面板锚点",
                "description": f"删车筛选：筛选面板或筛选分类标题 {stem}",
            }

        if name in {"R998.png", "R998Detail1.png", "D.png", "DFull.png", "VEI.png"}:
            return {
                "category": "车辆/品牌",
                "group_id": "vehicle_stat_labels",
                "role": "车辆属性/评分",
                "description": f"车辆识别：车辆评分、等级或属性标识 {stem}",
            }

        if name in {"anna.png", "link.png", "GoeliaDetail.png", "GoeliaSmall.png", "GapWithFormidableAdversary.png", "LeftFormidableAdversaryMatch.png", "AnnaAndLinkInFormidableAdversaryRace.png"}:
            return {
                "category": "赛事",
                "group_id": "race_hud_anchors",
                "role": "赛事 HUD 锚点",
                "description": f"刷图/刷CR：赛事 HUD、路线或劲敌匹配锚点 {stem}",
            }

        if name in {"continue-b.png", "continue-w.png"}:
            return {
                "category": "按钮",
                "group_id": "continue_button",
                "role": "继续按钮",
                "description": f"通用按钮：继续，{'黑底/选中' if '-b' in name else '白底'}状态",
            }

        if name in {"BarnFindBlack.png", "BarnFindWhite.png"}:
            return {
                "category": "车辆/品牌",
                "group_id": "barn_find_filter",
                "role": "车房宝物状态",
                "description": f"车辆筛选：车房宝物，{'黑底' if 'Black' in name else '白底'}状态",
            }

        if name in {"searcha.png", "searchb.png", "newCC.png", "Residence.png"}:
            return {
                "category": "菜单",
                "group_id": self.infer_template_group_id(name, "menu_misc"),
                "role": "菜单/搜索锚点",
                "description": f"菜单流程：搜索、收藏或居住地相关锚点 {stem}",
            }

        return {
            "category": "模板",
            "group_id": self.infer_template_group_id(name, f"template_{stem.lower()}"),
            "role": "文件名定位",
            "description": f"模板识别：{stem}，按文件名定位用途；可在运行日志中查看调用阶段",
        }

    def get_template_metadata(self, template_name):
        return self.infer_template_metadata(template_name)

    def get_template_description(self, template_name):
        return self.get_template_metadata(template_name).get("description", f"模板识别：{template_name}")

    def get_template_category(self, template_name):
        return self.get_template_metadata(template_name).get("category", "模板")

    def get_template_group_id(self, template_name):
        return self.get_template_metadata(template_name).get("group_id", "")

    def get_template_group_members(self, template_name):
        if self.template_group_members_cache is None:
            group_map = {}
            for item in self.list_template_files():
                key = self.get_template_key(item["name"])
                group_id = self.get_template_group_id(item["name"])
                if group_id:
                    group_map.setdefault(group_id, []).append(key)
            self.template_group_members_cache = {
                group_id: sorted(set(members), key=str.lower)
                for group_id, members in group_map.items()
            }

        group_id = self.get_template_group_id(template_name)
        if not group_id:
            return [self.get_template_key(template_name)]
        return self.template_group_members_cache.get(group_id) or [self.get_template_key(template_name)]

    def set_template_group_threshold(self, template_name, threshold):
        for member in self.get_template_group_members(template_name):
            self.set_template_threshold(member, threshold)

    def reset_template_group_threshold(self, template_name):
        thresholds = self.config.setdefault("template_thresholds", {})
        for member in self.get_template_group_members(template_name):
            thresholds.pop(member, None)

    def classify_template_match_issue(self, score, threshold, matched):
        try:
            score = float(score)
            threshold = float(threshold)
        except Exception:
            return ""
        if matched:
            return "命中"
        if score >= max(0.40, threshold - 0.25):
            return "疑似阈值过高/模板差异"
        if score < 0.15:
            return "基本无匹配，可能页面不对/模板不在当前画面"
        return "未命中"

    def describe_match_region(self, region):
        if not region:
            return "full"
        try:
            normalized = tuple(int(v) for v in region)
            for name, candidate in self.regions.items():
                if tuple(int(v) for v in candidate) == normalized:
                    return name
        except Exception:
            pass
        return str(region)

    def record_template_match(self, record):
        template_name = self.get_template_key(record.get("template"))
        if not template_name:
            return

        record = dict(record)
        record["template"] = template_name
        record["timestamp"] = time.strftime("%H:%M:%S")
        record["issue"] = self.classify_template_match_issue(
            record.get("score", 0.0),
            record.get("threshold", 0.0),
            record.get("matched", False),
        )

        with self.template_match_records_lock:
            self.template_match_records.append(record)
            if len(self.template_match_records) > 300:
                self.template_match_records = self.template_match_records[-300:]
            if record["issue"] and record["issue"] != "命中":
                self.template_match_issue_map[template_name] = record

        self.refresh_template_debug_row(record)

        if self.is_template_match_debug_enabled():
            now = time.time()
            log_key = f"{template_name}:{record.get('threshold'):.2f}:{record.get('matched')}"
            should_log = bool(record.get("matched")) or record["issue"] in (
                "疑似阈值过高/模板差异",
                "基本无匹配，可能页面不对/模板不在当前画面",
            )
            last_log_at = self.template_match_last_log_at.get(log_key, 0)
            if should_log and now - last_log_at >= 1.0:
                self.template_match_last_log_at[log_key] = now
                pos_text = record.get("pos") if record.get("pos") else "-"
                self.log(
                    f"[match] {template_name} score={record.get('score', 0.0):.2f}/"
                    f"{record.get('threshold', 0.0):.2f} scale={record.get('scale', 1.0):.3f} "
                    f"{'hit' if record.get('matched') else 'miss'} region={record.get('region_label', 'full')} "
                    f"pos={pos_text} {record['issue']}"
                )

    def get_recent_template_match_records(self, limit=80):
        with self.template_match_records_lock:
            return list(self.template_match_records[-limit:])

    def get_recent_template_match_issues(self, limit=80):
        with self.template_match_records_lock:
            issues = [record for record in self.template_match_records if record.get("issue") not in ("", "命中")]
        return issues[-limit:]

    def apply_pipeline_values(self, races_per_loop, actions_per_loop, loops):
        self.entry_race.delete(0, "end")
        self.entry_race.insert(0, str(races_per_loop))

        self.entry_car.delete(0, "end")
        self.entry_car.insert(0, str(actions_per_loop))

        self.entry_cj.delete(0, "end")
        self.entry_cj.insert(0, str(actions_per_loop))

        self.entry_sc.delete(0, "end")
        self.entry_sc.insert(0, str(actions_per_loop))

        self.entry_global_loop.delete(0, "end")
        self.entry_global_loop.insert(0, str(loops))

    def get_race_car_template_candidates(self):
        car_type = self.config.get("race_car_type", "s2_900")
        option_widget = getattr(self, "option_race_car_type", None)
        if option_widget is not None and option_widget.get() == "S1 790":
            car_type = "s1_790"

        if car_type == "s1_790":
            return ["SkillCarS1790.png"]
        return ["skillcar.png"]

    def get_race_car_display_text(self):
        car_type = self.config.get("race_car_type", "s2_900")
        option_widget = getattr(self, "option_race_car_type", None)
        if option_widget is not None and option_widget.get() == "S1 790":
            car_type = "s1_790"

        if car_type == "s1_790":
            return "【斯巴鲁Impreza 22B-STi Version】【调校S1 790】【保持默认涂装】【收藏车辆】【车辆共享代码 772778773】【适用地图共享代码 705399298】"
        return "【斯巴鲁Impreza 22B-STi Version】【调校S2 900】【保持默认涂装】【收藏车辆】"

    def get_race_car_hint_text(self):
        option_widget = getattr(self, "option_race_car_type", None)
        car_type = "s1_790" if option_widget is not None and option_widget.get() == "S1 790" else self.config.get("race_car_type", "s2_900")
        if car_type == "s1_790":
            return "S1 790：车辆共享代码 772778773\n适用地图共享代码 705399298"
        return "S2 900：使用默认刷图配置"

    def update_race_car_hint(self):
        if hasattr(self, "lbl_race_car_hint"):
            self.lbl_race_car_hint.configure(text=self.get_race_car_hint_text())

    def set_race_car_type(self, value):
        self.config["race_car_type"] = "s1_790" if value == "S1 790" else "s2_900"
        self.save_runtime_config()
        self.update_race_car_hint()
        self.log(f"当前刷图车辆已切换为：{self.get_race_car_display_text()}")

    def wait_for_race_car_template_multi(self, template_candidates, region, timeout=10, interval=0.25):
        if not template_candidates:
            return None, None

        per_template_timeout = max(2, (int(timeout) + len(template_candidates) - 1) // len(template_candidates))
        for idx, template_name in enumerate(template_candidates, start=1):
            if not self.is_running:
                return None, None

            self.log(f"尝试识别刷图车模板 {template_name} ({idx}/{len(template_candidates)})...")
            pos = self.wait_for_image_with_element_multi(
                template_name,
                "liketag.png",
                region=region,
                fast_mode=False,
                main_threshold=0.60,
                like_threshold=0.7,
                final_threshold=0.7,
                timeout=per_template_timeout,
                interval=interval,
            )
            if pos:
                self.log(f"命中刷图车模板: {template_name}")
                return pos, template_name

        return None, None

    def find_race_car_template_in_list(self, template_candidates, region, threshold=0.8, fast_mode=True):
        for template_name in template_candidates:
            if not self.is_running:
                return None, None

            pos = self.find_image_with_element(
                template_name,
                "liketag.png",
                region=region,
                threshold=threshold,
                fast_mode=fast_mode,
            )
            if pos:
                self.log(f"命中刷图车模板: {template_name}")
                return pos, template_name

        return None, None

    def auto_calculate_pipeline(self):
        val_a = self.entry_calc_a.get().strip()
        if not val_a:
            self.log("未输入CR，无需计算。")
            return
            
        try:
            target_cr = int(val_a)
            val_b = self.entry_calc_b.get().strip()
            cost_per_car = int(val_b) if val_b else 81700
            
            val_c = self.entry_calc_c.get().strip()
            sp_per_car = int(val_c) if val_c else 30
        except Exception:
            self.log("输入格式有误，请确保只输入数字！")
            return

        if cost_per_car <= 0 or sp_per_car <= 0:
            self.log("单车成本或技能点不能为 0！")
            return

        # 1. 基础转换（总车数 & 总跑图数）
        total_cars = target_cr // cost_per_car
        total_races = (total_cars * sp_per_car) // 10

        if total_races <= 0:
            self.log(f"目标金额不足(只够买{total_cars}辆车)，无法产生有效跑图！")
            return

        # 2. 核心分配逻辑
        if total_races <= 99:
            final_loops = 1
            final_races_per_loop = total_races
        else:
            import math
            loops = math.ceil(total_races / 99)
            avg_races = total_races // loops

            # 如果平均下来大于等于70次，就采用均分策略
            if avg_races >= 70:
                final_loops = loops
                final_races_per_loop = avg_races
            # 小于70次，直接拉满每个99，舍弃最后不够塞满一轮的余数
            else:
                final_races_per_loop = 99
                final_loops = total_races // 99 

        # 3. 反推每一轮买车、抽奖、卖车的具体数量
        cars_per_loop = (final_races_per_loop * 10) // sp_per_car

        if final_loops <= 0:
            self.log("计算后可用大循环次数为0。")
            return

        # 4. 自动填写到界面
        self.apply_pipeline_values(final_races_per_loop, cars_per_loop, final_loops)

        self.log(f"✅计算完成: 总计需{total_cars}车, 共跑图{total_races}次。分配为: {final_loops} 个大循环, 每轮跑图 {final_races_per_loop} 次, 动作 {cars_per_loop} 辆。")
        self.save_config()

    def calculate_required_races(self, action_count, skill_points_per_action, skill_points_per_race):
        return (action_count * skill_points_per_action + skill_points_per_race - 1) // skill_points_per_race

    def auto_calculate_super_wheelspin(self):
        val_target = self.entry_super_calc_target.get().strip()
        if not val_target:
            self.log("未输入目标超级抽奖数，无需计算。")
            return

        try:
            target_spins = int(val_target)
            race_sp_text = self.entry_super_calc_race_sp.get().strip()
            spin_sp_text = self.entry_super_calc_spin_sp.get().strip()
            skill_points_per_race = int(race_sp_text) if race_sp_text else 10
            skill_points_per_spin = int(spin_sp_text) if spin_sp_text else 30
        except Exception:
            self.log("超级抽奖计算器输入格式有误，请确保只输入数字！")
            return

        if target_spins <= 0:
            self.log("目标超级抽奖数必须大于 0！")
            return
        if skill_points_per_race <= 0 or skill_points_per_spin <= 0:
            self.log("每圈技术点和每抽需技术点都必须大于 0！")
            return

        total_races = self.calculate_required_races(
            target_spins,
            skill_points_per_spin,
            skill_points_per_race,
        )
        loops = max(1, (total_races + 98) // 99)
        spins_per_loop = (target_spins + loops - 1) // loops
        races_per_loop = self.calculate_required_races(
            spins_per_loop,
            skill_points_per_spin,
            skill_points_per_race,
        )

        while races_per_loop > 99:
            loops += 1
            spins_per_loop = (target_spins + loops - 1) // loops
            races_per_loop = self.calculate_required_races(
                spins_per_loop,
                skill_points_per_spin,
                skill_points_per_race,
            )

        actual_total_spins = loops * spins_per_loop
        actual_total_races = loops * races_per_loop
        self.apply_pipeline_values(races_per_loop, spins_per_loop, loops)
        self.log(
            f"✅超级抽奖计算完成: 目标 {target_spins} 次，至少需跑图 {total_races} 次。"
            f"当前分配为 {loops} 个大循环，每轮跑图 {races_per_loop} 次，"
            f"买车/抽奖/移除各 {spins_per_loop} 辆，实际覆盖约 {actual_total_spins} 次，"
            f"总跑图约 {actual_total_races} 次。"
        )
        self.save_config()

    def get_config_float(self, key, default_value, min_value=0.1):
        try:
            value = float(self.config.get(key, default_value))
        except Exception:
            value = float(default_value)
        return max(float(min_value), value)

    def get_config_int(self, key, default_value, min_value=1):
        try:
            value = int(float(self.config.get(key, default_value)))
        except Exception:
            value = int(default_value)
        return max(int(min_value), value)

    def open_debug_settings_window(self):
        if hasattr(self, "debug_settings_win") and self.debug_settings_win is not None:
            try:
                if self.debug_settings_win.winfo_exists():
                    self.debug_settings_win.lift()
                    return
            except Exception:
                pass

        self.debug_settings_win = ctk.CTkToplevel(self)
        self.debug_settings_win.title("调试设置")
        self.debug_settings_win.geometry("720x560")
        self.debug_settings_win.resizable(False, False)
        self.debug_settings_win.attributes("-topmost", True)

        root = ctk.CTkFrame(self.debug_settings_win, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=18, pady=16)

        ctk.CTkLabel(
            root,
            text="操作验证重试说明：开启后关键步骤会执行 操作 -> 等待 -> 模板验证 -> 失败重试。普通流程大约增加10-30秒；刷CR首次进赛事大约增加20-60秒；网络慢或服务器错误时可能增加1-3分钟以上。",
            wraplength=660,
            justify="left",
            text_color="#F5B041",
            font=ctk.CTkFont(size=13),
        ).pack(fill="x", pady=(0, 12))

        self.debug_entries = {}

        def add_section(title):
            frame = ctk.CTkFrame(root, fg_color="#242424", corner_radius=8)
            frame.pack(fill="x", pady=(0, 12))
            ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=16, weight="bold")).grid(
                row=0, column=0, columnspan=4, sticky="w", padx=12, pady=(10, 8)
            )
            return frame

        def add_entry(frame, row, col, label, key, default_value, width=80):
            ctk.CTkLabel(frame, text=label).grid(row=row, column=col, sticky="w", padx=(12, 6), pady=6)
            entry = ctk.CTkEntry(frame, width=width, justify="center")
            entry.insert(0, str(self.config.get(key, default_value)))
            entry.grid(row=row, column=col + 1, sticky="w", padx=(0, 18), pady=6)
            self.debug_entries[key] = entry

        cr_section = add_section("刷CR模块调试")
        add_entry(cr_section, 1, 0, "普通点击等待秒数", "cr_click_wait_seconds", 0.8)
        add_entry(cr_section, 1, 2, "页面加载等待秒数", "cr_page_load_wait_seconds", 2.0)
        add_entry(cr_section, 2, 0, "劲敌数据初始等待秒数", "cr_rival_data_initial_wait_seconds", 5)
        add_entry(cr_section, 2, 2, "选中劲敌后应用等待秒数", "cr_rival_apply_wait_seconds", 5)
        add_entry(cr_section, 3, 0, "刷CR守护检测间隔", "cr_guard_interval_seconds", 60)
        add_entry(cr_section, 3, 2, "未知错误Enter间隔", "cr_unknown_error_enter_interval_seconds", 5)

        general_section = add_section("跑图 / 买车 / 抽奖模块调试")
        add_entry(general_section, 1, 0, "菜单进入重试等待", "general_menu_retry_wait_seconds", 0.6)
        add_entry(general_section, 1, 2, "图像等待超时倍率", "general_image_timeout_multiplier", 1.0)
        add_entry(general_section, 2, 0, "普通点击后等待倍率", "general_click_wait_multiplier", 1.0)
        add_entry(general_section, 2, 2, "车辆列表横向移动等待", "general_vehicle_move_wait_seconds", 0.08)
        add_entry(general_section, 3, 0, "通用模块重试次数", "general_step_retry_count", 2)

        def save_debug_settings():
            float_keys = {
                "cr_click_wait_seconds",
                "cr_page_load_wait_seconds",
                "cr_rival_data_initial_wait_seconds",
                "cr_rival_apply_wait_seconds",
                "cr_guard_interval_seconds",
                "cr_unknown_error_enter_interval_seconds",
                "general_menu_retry_wait_seconds",
                "general_image_timeout_multiplier",
                "general_click_wait_multiplier",
                "general_vehicle_move_wait_seconds",
            }
            int_keys = {"general_step_retry_count"}
            for key, entry in self.debug_entries.items():
                raw = entry.get().strip()
                try:
                    if key in int_keys:
                        value = max(1, int(float(raw)))
                    elif key in float_keys:
                        value = max(0.05, float(raw))
                    else:
                        value = raw
                    self.config[key] = value
                    entry.delete(0, "end")
                    entry.insert(0, str(value))
                except Exception:
                    entry.delete(0, "end")
                    entry.insert(0, str(self.config.get(key, "")))
            self.save_runtime_config()
            self.log("调试设置已保存。")

        ctk.CTkButton(
            root,
            text="保存调试设置",
            width=140,
            height=34,
            fg_color="#1F6AA5",
            hover_color="#185680",
            command=save_debug_settings,
        ).pack(side="right", pady=(2, 0))

    def open_race_fallback_settings_window(self):
        if hasattr(self, "race_fallback_settings_win") and self.race_fallback_settings_win is not None:
            try:
                if self.race_fallback_settings_win.winfo_exists():
                    self.race_fallback_settings_win.lift()
                    self.race_fallback_settings_win.focus()
                    return
            except Exception:
                pass

        self.race_fallback_settings_win = ctk.CTkToplevel(self)
        self.race_fallback_settings_win.title("刷圈兜底参数设置")
        self.race_fallback_settings_win.geometry("520x420")
        self.race_fallback_settings_win.resizable(False, False)
        self.race_fallback_settings_win.attributes("-topmost", True)

        root = ctk.CTkFrame(self.race_fallback_settings_win, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=18, pady=16)

        ctk.CTkLabel(
            root,
            text="刷圈兜底参数设置",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#F1C40F",
        ).pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(
            root,
            text="这些参数只影响循环跑图赛事中的卡住恢复，不会改变买车、超抽或删车逻辑。",
            font=ctk.CTkFont(size=12),
            text_color="#BBBBBB",
            wraplength=470,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        entries = {}

        def add_setting(label, key, default_value, desc):
            row = ctk.CTkFrame(root, fg_color="#242424", corner_radius=8)
            row.pack(fill="x", pady=6)
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="both", expand=True, padx=12, pady=10)
            ctk.CTkLabel(
                left,
                text=label,
                font=ctk.CTkFont(size=14, weight="bold"),
                anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                left,
                text=desc,
                font=ctk.CTkFont(size=12),
                text_color="#B0B0B0",
                wraplength=330,
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=(3, 0))
            entry = ctk.CTkEntry(row, width=90, height=32, justify="center")
            entry.insert(0, str(self.config.get(key, default_value)))
            entry.pack(side="right", padx=12, pady=10)
            entries[key] = (entry, default_value)

        add_setting(
            "超时秒数",
            "race_stall_timeout_seconds",
            60,
            "单场刷圈开始后，如果超过这个秒数仍没检测到完成界面，就认为车辆可能卡住，先尝试倒车兜底。",
        )
        add_setting(
            "重开秒数",
            "race_restart_timeout_seconds",
            150,
            "单场赛事持续超过这个秒数仍未完成时，进入重开/恢复流程。建议大于或等于超时秒数。",
        )
        add_setting(
            "倒车秒数",
            "race_reverse_seconds",
            3,
            "触发卡住兜底时，松开 W 并按住 S 倒车的持续时间，用于把车辆从墙边或障碍物处拉出来。",
        )

        def save_race_fallback_settings():
            for key, (entry, default_value) in entries.items():
                value = self.get_positive_entry_value(entry, default_value)
                self.config[key] = value
            if self.config["race_restart_timeout_seconds"] < self.config["race_stall_timeout_seconds"]:
                self.config["race_restart_timeout_seconds"] = self.config["race_stall_timeout_seconds"]
                entry, _ = entries["race_restart_timeout_seconds"]
                entry.delete(0, "end")
                entry.insert(0, str(self.config["race_restart_timeout_seconds"]))
            self.save_runtime_config()
            self.log(
                "刷圈兜底参数已保存："
                f"超时 {self.config['race_stall_timeout_seconds']} 秒，"
                f"重开 {self.config['race_restart_timeout_seconds']} 秒，"
                f"倒车 {self.config['race_reverse_seconds']} 秒。"
            )

        ctk.CTkButton(
            root,
            text="保存",
            width=120,
            height=34,
            fg_color="#1F6AA5",
            hover_color="#185680",
            command=save_race_fallback_settings,
        ).pack(side="right", pady=(14, 0))

    # ==========================================
    # --- UI 布局设计 ---
    # ==========================================
    def setup_ui(self):
        self.top_container = ctk.CTkFrame(self, fg_color="transparent")
        self.top_container.pack(fill="x", padx=18, pady=(18, 10))

        self.config_frame = ctk.CTkScrollableFrame(
            self.top_container,
            fg_color="transparent",
            orientation="horizontal",
            height=390,
        )
        self.config_frame.pack(fill="x", expand=False)

        def create_box(parent, title, btn_text, btn_cmd, btn_color, def_val):
            frame = ctk.CTkFrame(
                parent,
                width=210,
                height=300,
                corner_radius=12,
                border_width=1,
                border_color="#2B2B2B",
            )
            frame.pack_propagate(False)
            frame.pack(side="left", padx=8)

            ctk.CTkLabel(
                frame,
                text=title,
                font=ctk.CTkFont(weight="bold", size=20),
            ).pack(pady=(14, 10))

            btn = ctk.CTkButton(
                frame,
                text=btn_text,
                fg_color=btn_color,
                hover_color=btn_color,
                command=btn_cmd,
                width=140,
                height=38,
                corner_radius=10,
            )
            btn.pack(pady=8, padx=10)

            entry = ctk.CTkEntry(frame, width=95, height=34, justify="center", corner_radius=8)
            entry.insert(0, str(def_val))
            entry.pack(pady=8)

            lbl = ctk.CTkLabel(
                frame,
                text=f"执行: 0 / {def_val}",
                text_color="#A0A0A0",
                font=ctk.CTkFont(size=16),
            )
            lbl.pack(pady=8)
            return frame, btn, entry, lbl

        def create_next_step(parent, var_checked, def_step, box_h=300, settings_button=None):
            frame = ctk.CTkFrame(parent, width=120, height=box_h, corner_radius=12, border_width=1, border_color="#2B2B2B")
            frame.pack(side="left", padx=4)
            frame.pack_propagate(False)

            ctk.CTkLabel(
                frame,
                text="下一步骤",
                font=ctk.CTkFont(size=18, weight="bold"),
                text_color="#5DADE2",
            ).pack(pady=(55, 10))

            entry = ctk.CTkEntry(frame, width=60, height=34, justify="center", corner_radius=8)
            entry.insert(0, str(def_step))
            entry.pack(pady=6)

            chk = ctk.CTkCheckBox(frame, text="继续", variable=var_checked, width=60)
            chk.pack(pady=8)

            if settings_button is not None:
                btn_text, btn_cmd = settings_button
                ctk.CTkButton(
                    frame,
                    text=btn_text,
                    width=92,
                    height=30,
                    corner_radius=8,
                    fg_color="#566573",
                    hover_color="#424949",
                    command=btn_cmd,
                ).pack(pady=(8, 0))

            return frame, entry, chk

        self.var_chk1 = ctk.BooleanVar(value=self.config["chk_1"])
        self.var_chk2 = ctk.BooleanVar(value=self.config["chk_2"])
        self.var_chk3 = ctk.BooleanVar(value=self.config["chk_3"])
        self.var_chk4 = ctk.BooleanVar(value=self.config.get("chk_4", True))

        box_race, self.btn_race, self.entry_race, self.lbl_race = create_box(
            self.config_frame,
            "1. 循环跑图",
            "开始",
            lambda: self.start_pipeline("race"),
            "#1F6AA5",
            self.config["race_count"],
        )
        self.entry_share = ctk.CTkEntry(box_race, width=130, justify="center", placeholder_text="蓝图数字代码")
        self.entry_share.insert(0, self.config["share_code"])
        self.entry_share.pack(pady=4)
        ctk.CTkLabel(box_race, text="刷图车", font=ctk.CTkFont(size=13)).pack(pady=(2, 0))
        self.option_race_car_type = ctk.CTkOptionMenu(
            box_race,
            width=110,
            height=28,
            values=["S1 790", "S2 900"],
            command=self.set_race_car_type,
        )
        self.option_race_car_type.set("S1 790" if self.config.get("race_car_type") == "s1_790" else "S2 900")
        self.option_race_car_type.pack(pady=(2, 4))
        self.lbl_race_car_hint = ctk.CTkLabel(
            box_race,
            text=self.get_race_car_hint_text(),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#F5B041",
            justify="center",
            wraplength=180,
        )
        self.lbl_race_car_hint.pack(pady=(0, 4))

        self.next_frame1, self.entry_next1, self.chk1 = create_next_step(
            self.config_frame, self.var_chk1, self.config.get("next_1", 2)
        )

        box_car, self.btn_car, self.entry_car, self.lbl_car = create_box(
            self.config_frame,
            "2. 批量买车",
            "开始",
            lambda: self.start_pipeline("buy"),
            "#2EA043",
            self.config["buy_count"],
        )
        self.entry_car.bind("<KeyRelease>", self.sync_buy_to_sell)
        ctk.CTkButton(
            box_car,
            text="CR不足兜底",
            width=120,
            height=28,
            corner_radius=8,
            fg_color="#D97706",
            hover_color="#B45309",
            command=self.open_cr_shortfall_settings_window,
        ).pack(pady=(0, 6))

        self.next_frame2, self.entry_next2, self.chk2 = create_next_step(
            self.config_frame, self.var_chk2, self.config.get("next_2", 3)
        )

        self.box_cj = ctk.CTkFrame(
            self.config_frame,
            width=360,
            height=300,
            corner_radius=12,
            border_width=1,
            border_color="#2B2B2B",
        )
        self.box_cj.pack_propagate(False)
        self.box_cj.pack(side="left", padx=8)

        top_cj = ctk.CTkFrame(self.box_cj, fg_color="transparent")
        top_cj.pack(fill="x", pady=10)

        left_cj = ctk.CTkFrame(top_cj, fg_color="transparent")
        left_cj.pack(side="left", padx=10)

        ctk.CTkLabel(left_cj, text="3. 超级抽奖", font=ctk.CTkFont(weight="bold", size=20)).pack(pady=(0, 8))

        self.btn_cj = ctk.CTkButton(
            left_cj,
            text="开始",
            width=120,
            height=38,
            corner_radius=10,
            fg_color="#8E44AD",
            hover_color="#8E44AD",
            command=lambda: self.start_pipeline("cj"),
        )
        self.btn_cj.pack(pady=5)

        self.btn_auto_cj = ctk.CTkButton(
            left_cj,
            text="自动抽奖",
            width=120,
            height=30,
            corner_radius=8,
            fg_color="#6C3483",
            hover_color="#512E5F",
            command=self.start_auto_super_wheelspin,
        )
        self.btn_auto_cj.pack(pady=(0, 5))
        ctk.CTkButton(
            left_cj,
            text="CR不足兜底",
            width=120,
            height=28,
            corner_radius=8,
            fg_color="#D97706",
            hover_color="#B45309",
            command=self.open_cr_shortfall_settings_window,
        ).pack(pady=(0, 5))

        self.entry_cj = ctk.CTkEntry(left_cj, width=95, height=34, justify="center", corner_radius=8)
        self.entry_cj.insert(0, str(self.config["cj_count"]))
        self.entry_cj.pack(pady=5)

        self.lbl_cj = ctk.CTkLabel(
            left_cj,
            text=f"执行: 0 / {self.config['cj_count']}",
            text_color="#A0A0A0",
            font=ctk.CTkFont(size=14),
        )
        self.lbl_cj.pack(pady=(2, 8))

        dir_frame = ctk.CTkFrame(left_cj, fg_color="transparent")
        dir_frame.pack(pady=4)

        for text, val in [("↑", "up"), ("↓", "down"), ("←", "left"), ("→", "right")]:
            ctk.CTkButton(
                dir_frame,
                text=text,
                width=30,
                height=28,
                corner_radius=8,
                command=lambda x=val: self.add_skill_dir(x),
            ).pack(side="left", padx=2)

        ctk.CTkButton(
            left_cj,
            text="清除矩阵",
            width=90,
            height=28,
            corner_radius=8,
            fg_color="#C0392B",
            hover_color="#A93226",
            command=self.clear_skill_dir,
        ).pack(pady=8)

        self.grid_frame = ctk.CTkFrame(top_cj, fg_color="transparent")
        self.grid_frame.pack(side="right", padx=12)

        self.grid_labels = [[None] * 4 for _ in range(4)]
        for r in range(4):
            for c in range(4):
                lbl = ctk.CTkLabel(
                    self.grid_frame,
                    text="",
                    width=28,
                    height=28,
                    corner_radius=5,
                    fg_color="#444444",
                )
                lbl.grid(row=r, column=c, padx=4, pady=4)
                self.grid_labels[r][c] = lbl
        ctk.CTkLabel(
            self.grid_frame,
            text="技能树",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#A0A0A0",
        ).grid(row=4, column=0, columnspan=4, pady=(8, 0))

        self.next_frame3, self.entry_next3, self.chk3 = create_next_step(
            self.config_frame, self.var_chk3, self.config.get("next_3", 4)
        )

        box_sc, self.btn_sc, self.entry_sc, self.lbl_sc = create_box(
            self.config_frame,
            "4. 移除车辆",
            "！！开始！！",
            lambda: self.start_pipeline("sell"),
            "#D97706",
            self.config.get("sc_count", 30),
        )
        ctk.CTkLabel(
            box_sc,
            text="删除：重复项+B级+全轮驱动+传奇\n大概率22B，请先人工审核",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#FFB020",
            justify="center",
            wraplength=170,
        ).pack(pady=(2, 6))

        self.next_frame4, self.entry_next4, self.chk4 = create_next_step(
            self.config_frame,
            self.var_chk4,
            self.config.get("next_4", 1),
            box_h=300,
            settings_button=("刷圈兜底\n参数设置", self.open_race_fallback_settings_window),
        )
        self.next_frame4.configure(width=130, border_width=2, border_color="#F1C40F")
                # ====== 抽离到底部的全局设置栏 (放在上方) ======
        # 【修改1】把 self.top_container 改成了 self
        self.global_settings_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", height=45, corner_radius=10)
        # 【修改2】加上了 padx=18，让它和上下边缘对齐
        self.global_settings_frame.pack(fill="x", padx=18, pady=(15, 0))
        self.global_settings_frame.pack_propagate(False)
        ctk.CTkLabel(
            self.global_settings_frame, 
            text="⚙️ 循环与守护设置", 
            font=ctk.CTkFont(weight="bold", size=15), 
            text_color="#F1C40F"
        ).pack(side="left", padx=(15, 20))
        ctk.CTkLabel(self.global_settings_frame, text="大循环次数:").pack(side="left", padx=(10, 5))
        self.entry_global_loop = ctk.CTkEntry(self.global_settings_frame, width=70, height=28, justify="center")
        self.entry_global_loop.insert(0, str(self.config.get("global_loops", 10)))
        self.entry_global_loop.pack(side="left", padx=(0, 20))
        self.var_step_retry_enabled = ctk.BooleanVar(value=self.config.get("step_retry_enabled", False))
        self.cb_step_retry = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="操作验证重试",
            variable=self.var_step_retry_enabled,
            command=self.save_config,
        )
        self.cb_step_retry.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(
            self.global_settings_frame,
            text="更稳但更慢，单轮通常增加10-60秒",
            text_color="#F5B041",
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(0, 14))
        ctk.CTkButton(
            self.global_settings_frame,
            text="调试设置",
            width=82,
            height=28,
            fg_color="#566573",
            hover_color="#424949",
            command=self.open_debug_settings_window,
        ).pack(side="left", padx=(0, 14))
        ctk.CTkButton(
            self.global_settings_frame,
            text="【测试】模板调试",
            width=82,
            height=28,
            fg_color="#2E86C1",
            hover_color="#2874A6",
            command=self.open_template_debug_window,
        ).pack(side="left", padx=(0, 10))
        self.var_template_match_debug_enabled = ctk.BooleanVar(value=self.config.get("template_match_debug_enabled", True))
        self.cb_template_match_debug = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="模板评分日志",
            variable=self.var_template_match_debug_enabled,
            width=105,
            command=self.save_config,
        )
        self.cb_template_match_debug.pack(side="left", padx=(0, 14))
        self.var_filter_strict_click_verify = ctk.BooleanVar(value=self.config.get("filter_strict_click_verify", False))
        self.cb_filter_strict_click_verify = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="筛选严格复核",
            variable=self.var_filter_strict_click_verify,
            command=self.save_config,
        )
        self.cb_filter_strict_click_verify.pack(side="left", padx=(0, 14))
        self.var_process_guard_enabled = ctk.BooleanVar(value=self.config.get("process_guard_enabled", True))
        self.cb_process_guard = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="进程检测守护",
            variable=self.var_process_guard_enabled,
            command=self.on_process_guard_toggle,
        )
        self.cb_process_guard.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(self.global_settings_frame, text="检测秒:").pack(side="left", padx=(0, 5))
        self.entry_process_guard_interval = ctk.CTkEntry(self.global_settings_frame, width=58, height=28, justify="center")
        self.entry_process_guard_interval.insert(0, str(self.config.get("process_guard_interval_seconds", 120)))
        self.entry_process_guard_interval.pack(side="left", padx=(0, 12))
        self.var_auto_restart = ctk.BooleanVar(value=self.config.get("auto_restart", True))
        self.cb_auto_restart = ctk.CTkCheckBox(self.global_settings_frame, text="游戏闪退自动重启（测试）", variable=self.var_auto_restart)
        self.cb_auto_restart.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(self.global_settings_frame, text="启动命令(CMD):").pack(side="left", padx=(10, 5))
        self.le_restart_cmd = ctk.CTkEntry(self.global_settings_frame, width=250, height=28)
        self.le_restart_cmd.insert(0, self.config.get("restart_cmd", "start steam://run/2483190"))
        self.le_restart_cmd.pack(side="left", fill="x", expand=True, padx=(0, 12))

        # 4K 实验适配复选框
        self.var_4k_experimental = ctk.BooleanVar(value=self.config.get("enable_4k_experimental", False))
        self.cb_4k_experimental = ctk.CTkCheckBox(
            self.global_settings_frame,
            text="4K实验适配",
            variable=self.var_4k_experimental,
            width=120,
            command=self.save_config,
        )
        self.cb_4k_experimental.pack(side="left", padx=(15, 5))
        self.lbl_4k_warning = ctk.CTkLabel(
            self.global_settings_frame,
            text="(作者未适配4K，建议先将系统分辨率调为2K后运行)",
            text_color="#E67E22",
            font=ctk.CTkFont(size=11),
        )
        self.lbl_4k_warning.pack(side="left", padx=(0, 15))

        self.pipeline_tip_frame = ctk.CTkFrame(self, fg_color="#2B2418", height=34, corner_radius=8)
        self.pipeline_tip_frame.pack(fill="x", padx=18, pady=(10, 0))
        self.pipeline_tip_frame.pack_propagate(False)
        self.var_like_guard_enabled = ctk.BooleanVar(value=self.config.get("like_guard_enabled", True))
        self.cb_like_guard = ctk.CTkCheckBox(
            self.pipeline_tip_frame,
            text="点赞检测（尚未完整优化和测试，建议手动完成点赞）",
            variable=self.var_like_guard_enabled,
            command=self.save_config,
        )
        self.cb_like_guard.pack(side="right", padx=(8, 14))
        self.var_skip_startup_prompts = ctk.BooleanVar(value=self.config.get("skip_startup_prompts", False))
        self.cb_skip_startup_prompts = ctk.CTkCheckBox(
            self.pipeline_tip_frame,
            text="跳过启动提示",
            variable=self.var_skip_startup_prompts,
            command=self.save_config,
        )
        self.cb_skip_startup_prompts.pack(side="right", padx=(8, 0))
        self.entry_like_guard_stall_seconds = ctk.CTkEntry(self.pipeline_tip_frame, width=54, height=24, justify="center")
        self.entry_like_guard_stall_seconds.insert(0, str(self.config.get("like_guard_stall_seconds", 180)))
        self.entry_like_guard_stall_seconds.pack(side="right", padx=(4, 0))
        ctk.CTkLabel(
            self.pipeline_tip_frame,
            text="卡住秒:",
            text_color="#F5B041",
            font=ctk.CTkFont(size=12),
        ).pack(side="right", padx=(8, 0))
        ctk.CTkLabel(
            self.pipeline_tip_frame,
            text="建议：买车数量 > 超抽数量 > 删除数量，给模板匹配容错，避免后续无对应车辆仍继续循环。",
            text_color="#F5B041",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=14)

        self.cr_ticket_warning_frame = ctk.CTkFrame(self, fg_color="#3A1111", height=38, corner_radius=8)
        self.cr_ticket_warning_frame.pack(fill="x", padx=18, pady=(8, 0))
        self.cr_ticket_warning_frame.pack_propagate(False)
        ctk.CTkLabel(
            self.cr_ticket_warning_frame,
            text="重要提醒：买车 CR 点不足时可能会消耗车辆票券（贵重物品），请一定一定预留充足 CR 点再刷技术点！",
            text_color="#FFB4A8",
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=14)


        # ====== 新增：智能计算分配工具栏 (放在下方) ======
        # 【修改1】把 self.top_container 改成了 self
        self.calc_frame = ctk.CTkFrame(self, fg_color="#2B2B2B", height=45, corner_radius=10)
        # 【修改2】加上了 padx=18，让它和上下边缘对齐
        self.calc_frame.pack(fill="x", padx=18, pady=(10, 0))
        self.calc_frame.pack_propagate(False)
        ctk.CTkLabel(
            self.calc_frame, 
            text="次数计算器", 
            font=ctk.CTkFont(weight="bold", size=15), 
            text_color="#2EA043"
        ).pack(side="left", padx=(15, 20))
        ctk.CTkLabel(self.calc_frame, text="CR:").pack(side="left", padx=(0, 5))
        self.entry_calc_a = ctk.CTkEntry(self.calc_frame, width=110, height=28, placeholder_text="留空不计算")
        self.entry_calc_a.insert(0, self.config.get("calc_a", ""))
        self.entry_calc_a.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(self.calc_frame, text="单车成本(CR):").pack(side="left", padx=(0, 5))
        self.entry_calc_b = ctk.CTkEntry(self.calc_frame, width=70, height=28)
        self.entry_calc_b.insert(0, self.config.get("calc_b", "81700"))
        self.entry_calc_b.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(self.calc_frame, text="单车技能点:").pack(side="left", padx=(0, 5))
        self.entry_calc_c = ctk.CTkEntry(self.calc_frame, width=50, height=28)
        self.entry_calc_c.insert(0, self.config.get("calc_c", "30"))
        self.entry_calc_c.pack(side="left", padx=(0, 15))
        ctk.CTkButton(
            self.calc_frame,
            text="计算并应用",
            width=90,
            height=28,
            fg_color="#D35400",
            hover_color="#A04000",
            command=self.auto_calculate_pipeline
        ).pack(side="left", padx=(0, 15))
        
        # 动态限制输入框长度（只允许数字并截断）
        def limit_len(evt, widget, max_l):
            val = "".join(c for c in widget.get() if c.isdigit())
            if len(val) > max_l:
                val = val[:max_l]
            if widget.get() != val:
                widget.delete(0, "end")
                widget.insert(0, val)
        self.entry_calc_a.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_calc_a, 10))
        self.entry_calc_b.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_calc_b, 7))
        self.entry_calc_c.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_calc_c, 2))
        self.entry_like_guard_stall_seconds.bind(
            "<FocusOut>",
            lambda e: self.normalize_positive_entry(
                self.entry_like_guard_stall_seconds,
                self.config.get("like_guard_stall_seconds", 180),
            ),
        )
        self.entry_like_guard_stall_seconds.bind(
            "<KeyRelease>",
            lambda e: limit_len(e, self.entry_like_guard_stall_seconds, 4),
        )

        self.super_calc_frame = ctk.CTkFrame(self, fg_color="#26222B", height=45, corner_radius=10)
        self.super_calc_frame.pack(fill="x", padx=18, pady=(10, 0))
        self.super_calc_frame.pack_propagate(False)
        ctk.CTkLabel(
            self.super_calc_frame,
            text="超级抽奖计算器",
            font=ctk.CTkFont(weight="bold", size=15),
            text_color="#BB8FCE",
        ).pack(side="left", padx=(15, 18))
        ctk.CTkLabel(self.super_calc_frame, text="目标超抽:").pack(side="left", padx=(0, 5))
        self.entry_super_calc_target = ctk.CTkEntry(self.super_calc_frame, width=80, height=28)
        self.entry_super_calc_target.insert(0, self.config.get("super_calc_target", ""))
        self.entry_super_calc_target.pack(side="left", padx=(0, 14))
        ctk.CTkLabel(self.super_calc_frame, text="每圈技术点:").pack(side="left", padx=(0, 5))
        self.entry_super_calc_race_sp = ctk.CTkEntry(self.super_calc_frame, width=55, height=28, justify="center")
        self.entry_super_calc_race_sp.insert(0, self.config.get("super_calc_race_sp", "10"))
        self.entry_super_calc_race_sp.pack(side="left", padx=(0, 14))
        ctk.CTkLabel(self.super_calc_frame, text="每抽技术点:").pack(side="left", padx=(0, 5))
        self.entry_super_calc_spin_sp = ctk.CTkEntry(self.super_calc_frame, width=55, height=28, justify="center")
        self.entry_super_calc_spin_sp.insert(0, self.config.get("super_calc_spin_sp", "30"))
        self.entry_super_calc_spin_sp.pack(side="left", padx=(0, 14))
        ctk.CTkButton(
            self.super_calc_frame,
            text="计算并应用",
            width=90,
            height=28,
            fg_color="#8E44AD",
            hover_color="#6C3483",
            command=self.auto_calculate_super_wheelspin,
        ).pack(side="left", padx=(0, 14))
        self.entry_super_calc_target.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_super_calc_target, 6))
        self.entry_super_calc_race_sp.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_super_calc_race_sp, 3))
        self.entry_super_calc_spin_sp.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_super_calc_spin_sp, 3))

        self.cr_frame = ctk.CTkFrame(self, fg_color="#202A24", height=58, corner_radius=10)
        self.cr_frame.pack(fill="x", padx=18, pady=(10, 0))
        self.cr_frame.pack_propagate(False)
        ctk.CTkLabel(
            self.cr_frame,
            text="刷CR点",
            font=ctk.CTkFont(weight="bold", size=15),
            text_color="#58D68D"
        ).pack(side="left", padx=(15, 18))
        self.btn_cr = ctk.CTkButton(
            self.cr_frame,
            text="开始刷CR",
            width=95,
            height=30,
            fg_color="#229954",
            hover_color="#1E8449",
            command=self.start_cr_grind,
        )
        self.btn_cr.pack(side="left", padx=(0, 14))
        ctk.CTkLabel(self.cr_frame, text="车辆:").pack(side="left", padx=(0, 5))
        self.option_cr_car_type = ctk.CTkOptionMenu(
            self.cr_frame,
            width=82,
            height=30,
            values=["五菱", "丰田"],
            dynamic_resizing=False,
            command=self.on_cr_car_type_changed,
        )
        self.option_cr_car_type.set("丰田" if self.config.get("cr_car_type") == "toyota" else "五菱")
        self.option_cr_car_type.pack(side="left", padx=(0, 14))
        self.var_cr_settlement_enabled = ctk.BooleanVar(value=self.config.get("cr_settlement_enabled", True))
        self.cb_cr_settlement = ctk.CTkCheckBox(
            self.cr_frame,
            text="周期结算",
            variable=self.var_cr_settlement_enabled,
            width=85,
        )
        self.cb_cr_settlement.pack(side="left", padx=(0, 8))
        ctk.CTkLabel(self.cr_frame, text="圈数:").pack(side="left", padx=(0, 5))
        self.entry_cr_settlement_laps = ctk.CTkEntry(self.cr_frame, width=55, height=30, justify="center")
        self.entry_cr_settlement_laps.insert(0, str(self.config.get("cr_settlement_laps", 5)))
        self.entry_cr_settlement_laps.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(self.cr_frame, text="每圈秒:").pack(side="left", padx=(0, 5))
        self.entry_cr_lap_seconds = ctk.CTkEntry(self.cr_frame, width=60, height=30, justify="center")
        self.entry_cr_lap_seconds.insert(0, str(self.get_cr_lap_seconds_for_car()))
        self.entry_cr_lap_seconds.pack(side="left", padx=(0, 8))
        self.btn_cr_lap_save = ctk.CTkButton(
            self.cr_frame,
            text="保存",
            width=50,
            height=30,
            fg_color="#2E86C1",
            hover_color="#2874A6",
            command=self.save_cr_lap_seconds_from_ui,
        )
        self.btn_cr_lap_save.pack(side="left", padx=(0, 14))
        ctk.CTkLabel(self.cr_frame, text="兜底重试:").pack(side="left", padx=(0, 5))
        self.entry_cr_step_retry_count = ctk.CTkEntry(self.cr_frame, width=45, height=30, justify="center")
        self.entry_cr_step_retry_count.insert(0, str(self.config.get("cr_step_retry_count", 3)))
        self.entry_cr_step_retry_count.pack(side="left", padx=(0, 16))
        self.lbl_cr_current = ctk.CTkLabel(self.cr_frame, text="当前CR: -", font=ctk.CTkFont(size=13))
        self.lbl_cr_current.pack(side="left", padx=(0, 16))
        self.lbl_cr_delta = ctk.CTkLabel(self.cr_frame, text="累计: -", font=ctk.CTkFont(size=13))
        self.lbl_cr_delta.pack(side="left", padx=(0, 16))
        self.lbl_cr_eff = ctk.CTkLabel(self.cr_frame, text="效率: -", font=ctk.CTkFont(size=13))
        self.lbl_cr_eff.pack(side="left", padx=(0, 16))

        self.entry_cr_settlement_laps.bind(
            "<FocusOut>",
            lambda e: self.normalize_positive_entry(
                self.entry_cr_settlement_laps,
                self.config.get("cr_settlement_laps", 5),
            ),
        )
        self.entry_cr_settlement_laps.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_cr_settlement_laps, 3))
        self.entry_cr_lap_seconds.bind(
            "<FocusOut>",
            lambda e: self.normalize_positive_entry(
                self.entry_cr_lap_seconds,
                self.get_cr_lap_seconds_for_car(),
            ),
        )
        self.entry_cr_lap_seconds.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_cr_lap_seconds, 4))
        self.entry_cr_step_retry_count.bind(
            "<FocusOut>",
            lambda e: self.normalize_positive_entry(
                self.entry_cr_step_retry_count,
                self.config.get("cr_step_retry_count", 3),
            ),
        )
        self.entry_cr_step_retry_count.bind("<KeyRelease>", lambda e: limit_len(e, self.entry_cr_step_retry_count, 2))
        # ==========================================
        #ctk.CTkLabel(self.global_settings_frame, text="图片原宽（不要修改）:").pack(side="left", padx=(10, 5))
        #self.entry_base_w = ctk.CTkEntry(self.global_settings_frame, width=70, height=28, justify="center")
        #self.entry_base_w.insert(0, str(self.config.get("base_width", 2560)))
        #self.entry_base_w.pack(side="left", padx=(0, 20))

        self.entry_next1.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next1, 2))
        self.entry_next2.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next2, 3))
        self.entry_next3.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next3, 4))
        self.entry_next4.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next4, 1))
        self.entry_process_guard_interval.bind(
            "<FocusOut>",
            lambda e: self.normalize_positive_entry(
                self.entry_process_guard_interval,
                self.config.get("process_guard_interval_seconds", 120),
            ),
        )
        if not self.entry_sc.get().strip():
            self.entry_sc.insert(0, "30")

        # === 全新的横向迷你UI设计 ===
        self.mini_frame = ctk.CTkFrame(self, fg_color="#1E1E1E", corner_radius=10)

        # 1. 日志区 (最左侧，占据主要伸缩空间)
        self.mini_log_box = ctk.CTkTextbox(self.mini_frame, state="disabled", wrap="word", font=ctk.CTkFont(size=13), fg_color="#2B2B2B")
        self.mini_log_box.pack(side="left", fill="both", expand=True, padx=(10, 5), pady=10)

        # 2. 信息区 (垂直排列任务状态和耗时)
        self.mini_info_frame = ctk.CTkFrame(self.mini_frame, fg_color="transparent", width=175)
        self.mini_info_frame.pack(side="left", fill="y", padx=5, pady=10)
        self.mini_info_frame.pack_propagate(False)

        self.lbl_mini_task = ctk.CTkLabel(
            self.mini_info_frame,
            text="当前任务: 等待中",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#3498DB",
            wraplength=165,
            justify="left",
        )
        self.lbl_mini_task.pack(pady=(5, 2), anchor="w")

        self.lbl_mini_prog = ctk.CTkLabel(self.mini_info_frame, text="任务进度: 0 / 0", font=ctk.CTkFont(size=12), wraplength=165, justify="left")
        self.lbl_mini_prog.pack(pady=2, anchor="w")

        self.lbl_mini_loop = ctk.CTkLabel(self.mini_info_frame, text="大循环: 0 / 0", font=ctk.CTkFont(size=12), wraplength=165, justify="left")
        self.lbl_mini_loop.pack(pady=2, anchor="w")

        self.lbl_mini_cr_cycle = ctk.CTkLabel(self.mini_info_frame, text="", font=ctk.CTkFont(size=12), wraplength=165, justify="left")

        self.lbl_mini_cr_laps = ctk.CTkLabel(self.mini_info_frame, text="", font=ctk.CTkFont(size=12), wraplength=165, justify="left")

        self.lbl_mini_cr_mode = ctk.CTkLabel(self.mini_info_frame, text="", font=ctk.CTkFont(size=12), wraplength=165, justify="left")

        # 3. 按钮区 (靠右排列)
        self.btn_mini_stop = ctk.CTkButton(self.mini_frame, text="⏸ 停止 (F8)", fg_color="#DA3633", hover_color="#B02A37", width=90, font=ctk.CTkFont(weight="bold"), command=self.stop_all)
        self.btn_mini_stop.pack(side="left", fill="y", padx=5, pady=10)

        self.btn_mini_support = ctk.CTkButton(self.mini_frame, text="❤ 赞助", fg_color="#F97316", hover_color="#EA580C", width=60, font=ctk.CTkFont(weight="bold"), command=self.open_support_window)
        self.btn_mini_support.pack(side="left", fill="y", padx=(5, 10), pady=10)


        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent", height=260)
        self.bottom_frame.pack(fill="both", expand=True, padx=18, pady=(6, 12))

        self.btn_stop = ctk.CTkButton(
            self.bottom_frame,
            text="⏸ 等待指令 (F8)",
            fg_color="#3A3A3A",
            hover_color="#4A4A4A",
            width=180,
            height=60,
            corner_radius=12,
            font=ctk.CTkFont(size=16, weight="bold"),
            command=self.stop_all,
        )
        self.btn_stop.pack(side="left", padx=6)

        self.btn_support = ctk.CTkButton(
            self.bottom_frame,
            text="❤ 赞助 / 更新",
            fg_color="#F97316",
            hover_color="#EA580C",
            width=120,
            height=60,
            corner_radius=12,
            font=ctk.CTkFont(weight="bold", size=14),
            command=self.open_support_window,
        )
        self.btn_support.pack(side="left", padx=6)

        self.log_box = ctk.CTkTextbox(
            self.bottom_frame,
            state="disabled",
            wrap="word",
            corner_radius=12,
            height=220,
            font=ctk.CTkFont(size=18),
        )
        self.log_box.pack(side="left", fill="both", expand=True, padx=8)
        self.sync_buy_to_sell()

    def open_template_debug_window(self):
        if self.template_debug_win is not None and self.template_debug_win.winfo_exists():
            self.template_debug_win.focus()
            self.refresh_template_debug_window()
            return

        self.template_debug_rows = {}
        self.template_debug_images = []
        self.template_debug_win = ctk.CTkToplevel(self)
        self.template_debug_win.title("【测试】模板识别评分调试")
        self.template_debug_win.geometry("1180x760")
        self.template_debug_win.minsize(960, 620)
        self.template_debug_win.attributes("-topmost", True)

        def on_close():
            self.template_debug_win.destroy()
            self.template_debug_win = None
            self.template_debug_rows = {}
            self.template_debug_issue_text = None
            self.template_debug_search_var = None
            self.template_debug_filter_var = None
            self.template_debug_category_var = None
            self.template_debug_images = []
            self.template_debug_all_items = []
            self.template_debug_filtered_items = []
            self.template_debug_pending_thresholds = {}
            self.template_debug_page = 0
            self.template_debug_page_label = None
            self.template_debug_prev_btn = None
            self.template_debug_next_btn = None

        self.template_debug_win.protocol("WM_DELETE_WINDOW", on_close)

        header = ctk.CTkFrame(self.template_debug_win, fg_color="#20242A", height=92, corner_radius=8)
        header.pack(fill="x", padx=12, pady=(12, 8))
        header.pack_propagate(False)

        ctk.CTkLabel(
            header,
            text="【测试】模板识别评分调试",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color="#5DADE2",
        ).pack(side="left", padx=(14, 18))

        self.template_debug_search_var = ctk.StringVar(value="")
        search_entry = ctk.CTkEntry(
            header,
            width=210,
            height=30,
            textvariable=self.template_debug_search_var,
            placeholder_text="搜索模板名/用途",
        )
        search_entry.pack(side="left", padx=(0, 10))
        search_entry.bind("<KeyRelease>", lambda _e: self.apply_template_debug_filters(reset_page=True))

        self.template_debug_filter_var = ctk.StringVar(value="全部")
        filter_menu = ctk.CTkOptionMenu(
            header,
            width=130,
            height=30,
            values=["全部", "最近失败/问题"],
            variable=self.template_debug_filter_var,
            command=lambda _v: self.apply_template_debug_filters(reset_page=True),
        )
        filter_menu.pack(side="left", padx=(0, 10))

        categories = ["全部分类"]
        try:
            categories.extend(sorted({self.get_template_category(item["name"]) for item in self.list_template_files()}))
        except Exception:
            pass
        self.template_debug_category_var = ctk.StringVar(value="全部分类")
        category_menu = ctk.CTkOptionMenu(
            header,
            width=130,
            height=30,
            values=categories,
            variable=self.template_debug_category_var,
            command=lambda _v: self.apply_template_debug_filters(reset_page=True),
        )
        category_menu.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            header,
            text="保存",
            width=74,
            height=30,
            fg_color="#2EA043",
            hover_color="#238636",
            command=self.save_template_debug_thresholds,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            header,
            text="全部恢复默认",
            width=110,
            height=30,
            fg_color="#7D3C98",
            hover_color="#633974",
            command=self.reset_all_template_debug_thresholds,
        ).pack(side="left", padx=(0, 10))

        self.template_debug_issue_text = ctk.CTkTextbox(
            header,
            width=430,
            height=70,
            state="disabled",
            wrap="word",
            font=ctk.CTkFont(size=12),
        )
        self.template_debug_issue_text.pack(side="right", fill="y", padx=12, pady=10)

        table_header = ctk.CTkFrame(self.template_debug_win, fg_color="#2B2B2B", height=34, corner_radius=6)
        table_header.pack(fill="x", padx=12, pady=(0, 6))
        table_header.pack_propagate(False)
        for text, width in [
            ("模板", 185),
            ("预览", 72),
            ("阈值", 180),
            ("最近得分", 118),
            ("状态", 155),
            ("分类/组合/用途", 360),
            ("操作", 115),
        ]:
            ctk.CTkLabel(table_header, text=text, width=width, anchor="w", font=ctk.CTkFont(weight="bold")).pack(
                side="left", padx=4
            )

        self.template_debug_list_frame = ctk.CTkScrollableFrame(self.template_debug_win, fg_color="#1E1E1E")
        self.template_debug_list_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        pager = ctk.CTkFrame(self.template_debug_win, fg_color="#20242A", height=38, corner_radius=8)
        pager.pack(fill="x", padx=12, pady=(0, 12))
        pager.pack_propagate(False)
        self.template_debug_prev_btn = ctk.CTkButton(
            pager,
            text="上一页",
            width=78,
            height=28,
            fg_color="#566573",
            hover_color="#424949",
            command=lambda: self.change_template_debug_page(-1),
        )
        self.template_debug_prev_btn.pack(side="left", padx=(10, 8), pady=5)
        self.template_debug_page_label = ctk.CTkLabel(pager, text="", width=260, anchor="w")
        self.template_debug_page_label.pack(side="left", padx=(0, 8))
        self.template_debug_next_btn = ctk.CTkButton(
            pager,
            text="下一页",
            width=78,
            height=28,
            fg_color="#566573",
            hover_color="#424949",
            command=lambda: self.change_template_debug_page(1),
        )
        self.template_debug_next_btn.pack(side="left", padx=(0, 8), pady=5)
        ctk.CTkLabel(
            pager,
            text="测试功能：尚未完整测试。为避免卡顿，模板行按页懒加载；搜索/筛选后仅渲染当前页。",
            text_color="#A0A0A0",
            font=ctk.CTkFont(size=12),
        ).pack(side="left", padx=(10, 0))

        self.template_debug_all_items = self.list_template_files()
        self.apply_template_debug_filters(reset_page=True)

        self.refresh_template_debug_window(update_filters=False)

    def create_template_debug_row(self, item):
        template_name = item["name"]
        metadata = self.get_template_metadata(template_name)
        category = metadata.get("category", "模板")
        group_id = metadata.get("group_id", "")
        role = metadata.get("role", "")
        description = metadata.get("description", self.get_template_description(template_name))
        full_description = f"[{category}] 组:{group_id or '-'} 角色:{role or '-'}\n{description}"
        row = ctk.CTkFrame(self.template_debug_list_frame, fg_color="#262626", corner_radius=6)
        row.pack(fill="x", pady=3, padx=2)

        ctk.CTkLabel(row, text=item["rel_path"], width=185, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left", padx=4)

        preview_label = ctk.CTkLabel(row, text="", width=72)
        try:
            img = Image.open(item["full_path"])
            img.thumbnail((64, 42))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self.template_debug_images.append(ctk_img)
            preview_label.configure(image=ctk_img)
        except Exception:
            preview_label.configure(text="无预览", font=ctk.CTkFont(size=11))
        preview_label.pack(side="left", padx=4)

        threshold_value = self.get_template_debug_row_threshold(template_name)
        value_var = ctk.StringVar(value=f"{threshold_value:.2f}")
        entry = ctk.CTkEntry(row, width=54, height=26, justify="center", textvariable=value_var)
        entry.pack(side="left", padx=(4, 4))
        slider = ctk.CTkSlider(row, width=116, from_=0.30, to=0.95, number_of_steps=65)
        slider.set(threshold_value)
        slider.pack(side="left", padx=(0, 4))
        dirty_state = {"dirty": False}

        def on_slider(value, var=value_var, name=template_name):
            dirty_state["dirty"] = True
            var.set(f"{float(value):.2f}")
            if not self.template_debug_syncing:
                self.sync_template_debug_group_value(name, float(value))

        def on_entry_commit(_event=None, s=slider, var=value_var, name=template_name):
            value = self.clamp_template_threshold(var.get())
            dirty_state["dirty"] = True
            var.set(f"{value:.2f}")
            s.set(value)
            if not self.template_debug_syncing:
                self.sync_template_debug_group_value(name, value)

        slider.configure(command=on_slider)
        entry.bind("<FocusOut>", on_entry_commit)
        entry.bind("<Return>", on_entry_commit)

        score_label = ctk.CTkLabel(row, text="-", width=118, anchor="w", font=ctk.CTkFont(size=12))
        score_label.pack(side="left", padx=4)
        issue_label = ctk.CTkLabel(row, text="未记录", width=155, anchor="w", font=ctk.CTkFont(size=12), text_color="#A0A0A0")
        issue_label.pack(side="left", padx=4)
        desc_label = ctk.CTkLabel(row, text=full_description, width=360, anchor="w", wraplength=350, font=ctk.CTkFont(size=12))
        desc_label.pack(side="left", padx=4)

        def reset_one(name=template_name, s=slider, var=value_var):
            self.reset_template_group_threshold(name)
            for member in self.get_template_group_members(name):
                self.template_debug_pending_thresholds.pop(member, None)
                member_row = self.template_debug_rows.get(member)
                if not member_row:
                    continue
                member_row["entry_var"].set("0.75")
                member_row["slider"].set(0.75)
                member_row["original_value"] = 0.75
                member_row.get("dirty_state", {})["dirty"] = False
            self.save_runtime_config()
            self.log(f"模板组合阈值已恢复默认: {self.get_template_group_id(name) or name}")

        ctk.CTkButton(
            row,
            text="重置",
            width=70,
            height=26,
            fg_color="#566573",
            hover_color="#424949",
            command=reset_one,
        ).pack(side="left", padx=4)

        self.template_debug_rows[template_name] = {
            "frame": row,
            "description": description,
            "category": category,
            "group_id": group_id,
            "role": role,
            "entry_var": value_var,
            "slider": slider,
            "original_value": threshold_value,
            "dirty_state": dirty_state,
            "score_label": score_label,
            "issue_label": issue_label,
            "rel_path": item["rel_path"],
        }

    def sync_template_debug_group_value(self, template_name, value):
        group_id = self.get_template_group_id(template_name)
        if not group_id:
            return
        value = self.clamp_template_threshold(value)
        self.template_debug_syncing = True
        try:
            for member in self.get_template_group_members(template_name):
                self.template_debug_pending_thresholds[member] = value
                if member == template_name:
                    continue
                row = self.template_debug_rows.get(member)
                if not row:
                    continue
                row["entry_var"].set(f"{value:.2f}")
                row["slider"].set(value)
                row.get("dirty_state", {})["dirty"] = True
        finally:
            self.template_debug_syncing = False

    def collect_template_debug_visible_values(self):
        for template_name, row in list(self.template_debug_rows.items()):
            try:
                self.template_debug_pending_thresholds[template_name] = self.clamp_template_threshold(row["entry_var"].get())
            except Exception:
                pass

    def get_template_debug_row_threshold(self, template_name):
        if template_name in self.template_debug_pending_thresholds:
            return self.clamp_template_threshold(self.template_debug_pending_thresholds[template_name])
        return self.get_template_threshold(template_name, 0.75)

    def clear_template_debug_visible_rows(self):
        for row in list(self.template_debug_rows.values()):
            try:
                row["frame"].destroy()
            except Exception:
                pass
        self.template_debug_rows = {}
        self.template_debug_images = []

    def change_template_debug_page(self, delta):
        self.collect_template_debug_visible_values()
        total = len(self.template_debug_filtered_items)
        max_page = max(0, (total - 1) // self.template_debug_page_size)
        self.template_debug_page = max(0, min(max_page, self.template_debug_page + int(delta)))
        self.render_template_debug_current_page()

    def render_template_debug_current_page(self):
        win = self.__dict__.get("template_debug_win")
        if win is None or not win.winfo_exists():
            return

        self.clear_template_debug_visible_rows()
        total = len(self.template_debug_filtered_items)
        page_size = self.template_debug_page_size
        max_page = max(0, (total - 1) // page_size)
        self.template_debug_page = max(0, min(max_page, self.template_debug_page))
        start = self.template_debug_page * page_size
        end = min(total, start + page_size)

        for item in self.template_debug_filtered_items[start:end]:
            self.create_template_debug_row(item)

        if self.template_debug_page_label is not None:
            if total:
                text = f"第 {self.template_debug_page + 1}/{max_page + 1} 页，显示 {start + 1}-{end} / {total} 个模板"
            else:
                text = "没有符合条件的模板"
            self.template_debug_page_label.configure(text=text)
        if self.template_debug_prev_btn is not None:
            self.template_debug_prev_btn.configure(state="normal" if self.template_debug_page > 0 else "disabled")
        if self.template_debug_next_btn is not None:
            self.template_debug_next_btn.configure(state="normal" if self.template_debug_page < max_page else "disabled")

        self.refresh_template_debug_window(update_filters=False)

    def save_template_debug_thresholds(self):
        self.collect_template_debug_visible_values()
        saved_count = 0
        thresholds = self.config.setdefault("template_thresholds", {})
        candidate_names = set(self.template_debug_pending_thresholds) | set(self.template_debug_rows) | set(thresholds)
        for template_name in sorted(candidate_names, key=str.lower):
            row = self.template_debug_rows.get(template_name)
            value = self.clamp_template_threshold(
                self.template_debug_pending_thresholds.get(
                    template_name,
                    row["entry_var"].get() if row else self.get_template_threshold(template_name, 0.75),
                )
            )
            if row:
                row["entry_var"].set(f"{value:.2f}")
                row["slider"].set(value)
            should_save = (
                bool(row and row.get("dirty_state", {}).get("dirty"))
                or template_name in thresholds
                or template_name in self.template_debug_pending_thresholds
            )
            if should_save:
                self.set_template_group_threshold(template_name, value)
                if row:
                    row["original_value"] = value
                    row.get("dirty_state", {})["dirty"] = False
                saved_count += 1
        self.template_debug_pending_thresholds = {}
        for template_name, row in self.template_debug_rows.items():
            value = self.get_template_threshold(template_name, row.get("original_value", 0.75))
            row["entry_var"].set(f"{value:.2f}")
            row["slider"].set(value)
            row["original_value"] = value
            row.get("dirty_state", {})["dirty"] = False
        self.save_runtime_config()
        self.log(f"模板调试阈值已保存：{saved_count} 个覆盖项。未修改模板继续使用调用点默认阈值。")
        self.refresh_template_debug_window()

    def reset_all_template_debug_thresholds(self):
        self.config["template_thresholds"] = {}
        self.template_debug_pending_thresholds = {}
        for row in self.template_debug_rows.values():
            row["entry_var"].set("0.75")
            row["slider"].set(0.75)
            row["original_value"] = 0.75
            row.get("dirty_state", {})["dirty"] = False
        self.save_runtime_config()
        self.log("所有模板阈值已恢复默认。")
        self.refresh_template_debug_window()

    def apply_template_debug_filters(self, reset_page=False):
        if not self.template_debug_all_items:
            return
        self.collect_template_debug_visible_values()
        search_text = ""
        filter_text = "全部"
        category_text = "全部分类"
        try:
            search_text = self.template_debug_search_var.get().strip().lower()
            filter_text = self.template_debug_filter_var.get()
            category_text = self.template_debug_category_var.get()
        except Exception:
            pass

        problem_templates = {record.get("template") for record in self.get_recent_template_match_issues(limit=300)}
        filtered = []
        for item in self.template_debug_all_items:
            template_name = item["name"]
            metadata = self.get_template_metadata(template_name)
            haystack = (
                f"{template_name} {item['rel_path']} {metadata.get('description', '')} "
                f"{metadata.get('category', '')} {metadata.get('group_id', '')} {metadata.get('role', '')}"
            ).lower()
            visible = True
            if search_text and search_text not in haystack:
                visible = False
            if filter_text == "最近失败/问题" and template_name not in problem_templates:
                visible = False
            if category_text != "全部分类" and metadata.get("category") != category_text:
                visible = False

            if visible:
                filtered.append(item)

        self.template_debug_filtered_items = filtered
        if reset_page:
            self.template_debug_page = 0
        self.render_template_debug_current_page()

    def refresh_template_debug_row(self, record):
        win = self.__dict__.get("template_debug_win")
        if win is None or not win.winfo_exists():
            return

        def update():
            try:
                template_name = record.get("template")
                row = self.template_debug_rows.get(template_name)
                if row:
                    row["score_label"].configure(
                        text=f"{record.get('score', 0.0):.2f}/{record.get('threshold', 0.0):.2f}"
                    )
                    issue = record.get("issue", "")
                    color = "#2EA043" if record.get("matched") else "#F5B041"
                    if issue.startswith("基本无匹配"):
                        color = "#E74C3C"
                    row["issue_label"].configure(text=issue or "未记录", text_color=color)
                self.refresh_template_debug_issues()
            except Exception:
                pass

        self.ui_call(update)

    def refresh_template_debug_issues(self):
        if self.template_debug_issue_text is None:
            return
        issues = self.get_recent_template_match_issues(limit=8)
        lines = []
        for record in issues:
            lines.append(
                f"{record.get('timestamp', '')} {record.get('template')} "
                f"{record.get('score', 0.0):.2f}/{record.get('threshold', 0.0):.2f} "
                f"{record.get('issue', '')}"
            )
        if not lines:
            lines = ["暂无运行中模板问题。"]
        try:
            self.template_debug_issue_text.configure(state="normal")
            self.template_debug_issue_text.delete("1.0", "end")
            self.template_debug_issue_text.insert("end", "\n".join(lines))
            self.template_debug_issue_text.configure(state="disabled")
        except Exception:
            pass

    def refresh_template_debug_window(self, update_filters=True):
        recent_records = self.get_recent_template_match_records(limit=300)
        latest_by_template = {}
        for record in recent_records:
            latest_by_template[record.get("template")] = record
        for template_name, record in latest_by_template.items():
            row = self.template_debug_rows.get(template_name)
            if not row:
                continue
            row["score_label"].configure(text=f"{record.get('score', 0.0):.2f}/{record.get('threshold', 0.0):.2f}")
            issue = record.get("issue", "") or "未记录"
            color = "#2EA043" if record.get("matched") else "#F5B041"
            if issue.startswith("基本无匹配"):
                color = "#E74C3C"
            row["issue_label"].configure(text=issue, text_color=color)
        self.refresh_template_debug_issues()
        if update_filters:
            self.apply_template_debug_filters()

    def open_support_window(self):
        if self.support_win is not None and self.support_win.winfo_exists():
            self.support_win.focus()
            return

        self.support_win = ctk.CTkToplevel(self)
        win_w, win_h = 620, 640
        self.support_win.title("赞助支持 & 更新")
        self.support_win.geometry(f"{win_w}x{win_h}")
        self.support_win.attributes("-topmost", True)
        self.support_win.resizable(False, False)

        try:
            icon_path = get_asset_path("icon.ico")
            if icon_path:
                self.support_win.iconbitmap(icon_path)
        except Exception:
            pass

        self.support_win.update_idletasks()
        screen_w = self.support_win.winfo_screenwidth()
        screen_h = self.support_win.winfo_screenheight()
        x = max(0, screen_w - win_w - 80)
        y = max(0, (screen_h - win_h) // 2)
        self.support_win.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            self.support_win,
            text="感谢您的支持与鼓励",
            font=ctk.CTkFont(weight="bold", size=18),
            text_color="#F97316",
        ).pack(pady=(18, 4))

        ctk.CTkLabel(
            self.support_win,
            text=f"{ORIGINAL_AUTHOR_NAME} / {OPTIMIZER_NAME}",
            font=ctk.CTkFont(size=12),
        ).pack(pady=(0, 8))

        self.support_qr_images = []
        qr_frame = ctk.CTkFrame(self.support_win, fg_color="transparent")
        qr_frame.pack(fill="x", padx=18, pady=(4, 8))

        def add_support_card(parent, title, subtitle, qr_asset, button_text, button_url, button_color, qr_size=180):
            card = ctk.CTkFrame(parent, fg_color="#2A2A2A", corner_radius=10)
            card.pack(side="left", fill="both", expand=True, padx=6)
            ctk.CTkLabel(
                card,
                text=title,
                font=ctk.CTkFont(size=15, weight="bold"),
                text_color="#F97316",
            ).pack(pady=(12, 2))
            ctk.CTkLabel(
                card,
                text=subtitle,
                font=ctk.CTkFont(size=11),
                text_color="#BBBBBB",
            ).pack(pady=(0, 8))

            qr_path = get_asset_path(qr_asset)
            try:
                if qr_path and os.path.exists(qr_path):
                    img = Image.open(qr_path)
                    qr_img = ctk.CTkImage(light_image=img, size=(qr_size, qr_size))
                    self.support_qr_images.append(qr_img)
                    ctk.CTkLabel(card, text="", image=qr_img).pack(pady=(0, 8))
                else:
                    ctk.CTkLabel(card, text=f"（未找到 {qr_asset}）", text_color="gray").pack(pady=70)
            except Exception:
                ctk.CTkLabel(card, text="（二维码加载失败）", text_color="gray").pack(pady=70)

            ctk.CTkButton(
                card,
                text=button_text,
                width=170,
                height=30,
                fg_color=button_color,
                hover_color="#7D3C98" if button_color == "#8E44AD" else "#2874A6",
                command=lambda: webbrowser.open(button_url),
            ).pack(pady=(0, 12))

        add_support_card(
            qr_frame,
            ORIGINAL_AUTHOR_NAME,
            "作者赞助二维码",
            "qrcode.png",
            "前往作者爱发电",
            ORIGINAL_AFDIAN_URL,
            "#8E44AD",
            180,
        )
        add_support_card(
            qr_frame,
            OPTIMIZER_NAME,
            "深度优化者赞助二维码",
            "SArB1eQRCodeBig.png",
            "前往 SArB1e 爱发电",
            OPTIMIZER_AFDIAN_URL,
            "#2E86C1",
            220,
        )

        ctk.CTkFrame(self.support_win, height=2, fg_color="#333333").pack(fill="x", padx=20, pady=10)

        self.lbl_version = ctk.CTkLabel(
            self.support_win,
            text=f"{APP_DISPLAY_NAME} | 当前版本: v{CURRENT_VERSION}",
            text_color="gray",
            font=ctk.CTkFont(size=12),
        )
        self.lbl_version.pack()

        def check_update_logic():
            self.ui_call(self.lbl_version.configure, text="正在连接 Github...", text_color="#3498DB")
            try:
                url = "https://raw.githubusercontent.com/HikigayaHachiman0211/FH6Auto/refs/heads/main/version.json"
                resp = requests.get(url, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    remote_ver = data.get("version", "0.0.0")
                    remote_url = data.get("url", "")

                    if parse_version(remote_ver) > parse_version(CURRENT_VERSION):
                        if (
                            remote_url.startswith("https://github.com/YOUSTHEONE/")
                            or remote_url.startswith("https://github.com/HikigayaHachiman0211")
                            or remote_url.startswith("https://ifdian.net/")
                            or remote_url.startswith("https://afdian.com/")
                        ):
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
            text="SArB1e GitHub",
            width=130,
            height=30,
            fg_color="#2EA043",
            hover_color="#238636",
            command=lambda: webbrowser.open(OPTIMIZER_GITHUB_URL),
        ).pack(side="left", padx=5)
    def update_timer(self):
        if not self.is_running:
            return
        elapsed = int(time.time() - self.start_time)
        hrs = elapsed // 3600
        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        time_str = f"总耗时: {hrs:02d}:{mins:02d}:{secs:02d}"
        try:
            self.lbl_mini_time.configure(text=time_str)
        except Exception: pass
        
        if self.is_running:
            self.after(1000, self.update_timer)

    def update_running_ui(self, task_name="", current_val=0, max_val=0):
        try:
            if task_name:
                self.ui_call(self.lbl_mini_task.configure, text=f"当前任务: {task_name}")
            if max_val > 0:
                self.ui_call(self.lbl_mini_prog.configure, text=f"执行进度: {current_val} / {max_val}")
            elif current_val > 0:
                self.ui_call(self.lbl_mini_prog.configure, text=f"执行进度: {current_val}")
        except Exception:
            pass

    def update_mini_cr_status(self, settlement_enabled=None, estimated_laps=None, target_laps=None):
        try:
            if settlement_enabled is None:
                settlement_enabled = self.is_cr_settlement_enabled()
            cycle_text = f"周期循环: {'开启' if settlement_enabled else '关闭'}"
            if target_laps is None:
                target_laps = self.get_cr_settlement_laps()
            if estimated_laps is None:
                estimated_laps = 0
            laps_text = f"预计圈数: {estimated_laps} / {target_laps}"
            mode_text = "刷CR模式: 自动无限循环"
            self.ui_call(self.ensure_mini_cr_status_visible)
            self.ui_call(self.lbl_mini_cr_cycle.configure, text=cycle_text)
            self.ui_call(self.lbl_mini_cr_laps.configure, text=laps_text)
            self.ui_call(self.lbl_mini_cr_mode.configure, text=mode_text)
        except Exception:
            pass

    def ensure_mini_cr_status_visible(self):
        if not self.lbl_mini_cr_cycle.winfo_manager():
            self.lbl_mini_cr_cycle.pack(pady=2, anchor="w", before=self.lbl_mini_prog)
        if not self.lbl_mini_cr_laps.winfo_manager():
            self.lbl_mini_cr_laps.pack(pady=2, anchor="w", before=self.lbl_mini_prog)
        if not self.lbl_mini_cr_mode.winfo_manager():
            self.lbl_mini_cr_mode.pack(pady=2, anchor="w", before=self.lbl_mini_prog)

    def clear_mini_cr_status(self):
        try:
            self.ui_call(self.lbl_mini_cr_cycle.configure, text="")
            self.ui_call(self.lbl_mini_cr_laps.configure, text="")
            self.ui_call(self.lbl_mini_cr_mode.configure, text="")
            self.ui_call(self.lbl_mini_cr_cycle.pack_forget)
            self.ui_call(self.lbl_mini_cr_laps.pack_forget)
            self.ui_call(self.lbl_mini_cr_mode.pack_forget)
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
    #副屏支持
    def hw_mouse_move(self, x, y):
        # 获取多显示器组成的整个“虚拟桌面”坐标和尺寸
        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79
        left = ctypes.windll.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        top = ctypes.windll.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = ctypes.windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = ctypes.windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
        if width == 0 or height == 0:
            return
        # 映射到 0~65535 的绝对虚拟坐标系统
        calc_x = int((x - left) * 65535 / width)
        calc_y = int((y - top) * 65535 / height)
        # MOUSEEVENTF_MOVE = 0x0001, MOUSEEVENTF_ABSOLUTE = 0x8000, MOUSEEVENTF_VIRTUALDESK = 0x4000
        flags = 0x0001 | 0x8000 | 0x4000 
        extra = ctypes.c_ulong(0)
        ii_ = Input_I()
        ii_.mi = MouseInput(calc_x, calc_y, 0, flags, 0, ctypes.pointer(extra))
        cmd = Input(ctypes.c_ulong(0), ii_)
        SendInput(1, ctypes.pointer(cmd), ctypes.sizeof(cmd))

    def move_mouse_to_desktop_top_left(self):
        try:
            left = ctypes.windll.user32.GetSystemMetrics(76)
            top = ctypes.windll.user32.GetSystemMetrics(77)
            self.hw_mouse_move(left + 5, top + 5)
        except Exception:
            self.hw_mouse_move(5, 5)

    def is_4k_experimental_enabled(self):
        """4K实验适配开关，默认关闭。
        仅在用户主动勾选UI复选框或配置中启用时才生效。"""
        var_widget = getattr(self, "var_4k_experimental", None)
        if var_widget is not None:
            try:
                return bool(var_widget.get())
            except Exception:
                pass
        return bool(self.config.get("enable_4k_experimental", False))

    def get_resolution_scale(self):
        """获取当前窗口宽度与基准宽度的缩放比。
        仅在4K实验模式开启时生效，否则始终返回1.0（保持原有行为不变）。"""
        if not self.is_4k_experimental_enabled():
            return 1.0
        try:
            full = self.regions.get("全界面")
            curr_w = full[2] if full else 2560
            base_w = self.config.get("base_width", 2560)
            if curr_w > 0 and base_w > 0:
                return curr_w / base_w
        except Exception:
            pass
        return 1.0

    def game_click(self, pos, double=False):
        if not self.is_running or not pos:
            return
        x, y = int(pos[0]), int(pos[1])
        
        # 使用多屏兼容的硬件级移动
        self.hw_mouse_move(x, y)
        time.sleep(0.2)
        for _ in range(2 if double else 1):
            pydirectinput.mouseDown()
            time.sleep(0.1)
            pydirectinput.mouseUp()
            time.sleep(0.1)
        time.sleep(0.1)
        # 移开鼠标 10 像素，防止游戏里的悬浮提示框遮挡下一次截图
        try:
            gx, gy, gw, gh = self.regions["全界面"]
            # 移动到游戏左上角向内偏移 5 个像素，确保在游戏内但绝对不会挡住任何中间UI
            self.hw_mouse_move(gx + 5, gy + 5)
        except Exception:
            # 兜底：如果获取不到窗口坐标，移到绝对屏幕左上角
            self.hw_mouse_move(5, 5)
        time.sleep(0.2)

    def move_to_game_coord(self, x, y):
        """
        将鼠标移动到以【游戏窗口左上角】为起点的 (x, y) 坐标。
        例如传入 (5, 5)，就会移动到游戏内左上角 5 像素的安全位置。
        """
        try:
            gx, gy, gw, gh = self.regions["全界面"]
            abs_x = gx + x
            abs_y = gy + y
            self.hw_mouse_move(abs_x, abs_y)
        except Exception:
            # 兜底：如果获取不到窗口坐标，就直接当绝对坐标移动
            self.hw_mouse_move(x, y)
    
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
                # 写入下方大界面的日志
                self.log_box.configure(state="normal")
                self.log_box.insert("end", full_msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
                # 同时写入迷你界面的横向日志
                if hasattr(self, "mini_log_box"):
                    self.mini_log_box.configure(state="normal")
                    self.mini_log_box.insert("end", full_msg + "\n")
                    self.mini_log_box.see("end")
                    self.mini_log_box.configure(state="disabled")
            except Exception:
                pass
        self.ui_call(write_ui)

        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(full_msg + "\n")
        except Exception:
            pass

    def set_failure_context(self, reason, details=None):
        self.last_failure_context = {
            "reason": reason,
            "details": details or {},
        }

    def clear_failure_context(self):
        self.last_failure_context = None

    def sanitize_diagnostic_token(self, value):
        text = str(value or "unknown").strip().lower()
        token = []
        for ch in text:
            if ch.isalnum() or ch in ("-", "_"):
                token.append(ch)
            else:
                token.append("_")

        safe_value = "".join(token).strip("_")
        return safe_value or "unknown"

    def get_failure_snapshot_region(self):
        region = self.regions.get("全界面")
        if not region or len(region) != 4:
            return None

        x, y, w, h = region
        if w <= 0 or h <= 0:
            return None

        return (int(x), int(y), int(w), int(h))

    def capture_failure_snapshot(self, reason, module_name=None, details=None):
        try:
            module_name = module_name or self.current_step_name or "unknown"
            details = details or {}
            cooldown_key = f"{module_name}:{reason}"
            now = time.time()
            last_capture = self.failure_snapshot_cooldown.get(cooldown_key, 0)
            if now - last_capture < 10.0:
                self.log(f"[诊断] {module_name}/{reason} 在冷却期内，跳过重复截图。")
                return None

            self.failure_snapshot_cooldown[cooldown_key] = now

            with self.failure_snapshot_lock:
                self.failure_snapshot_counter += 1
                snapshot_index = self.failure_snapshot_counter

            local_time = time.localtime(now)
            event_id = f"{time.strftime('%Y%m%d_%H%M%S', local_time)}_{int((now % 1) * 1000):03d}_{snapshot_index:04d}"
            date_dir = os.path.join(DIAGNOSTICS_DIR, time.strftime("%Y-%m-%d", local_time))
            os.makedirs(date_dir, exist_ok=True)

            module_token = self.sanitize_diagnostic_token(module_name)
            reason_token = self.sanitize_diagnostic_token(reason)
            base_name = f"{event_id}_{module_token}_{reason_token}"
            screenshot_path = os.path.join(date_dir, base_name + ".png")
            meta_path = os.path.join(date_dir, base_name + ".json")

            screenshot_saved = False
            screenshot_error = None
            region = self.get_failure_snapshot_region()
            capture_regions = [region]
            if region is not None:
                capture_regions.append(None)

            for capture_region in capture_regions:
                try:
                    screen_bgr = self.capture_region(capture_region)
                    if cv2.imwrite(screenshot_path, screen_bgr):
                        screenshot_saved = True
                        break
                except Exception as e:
                    screenshot_error = str(e)

            metadata = {
                "event_id": event_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", local_time),
                "module": module_name,
                "reason": reason,
                "details": details,
                "current_step": self.current_step_name,
                "is_running": self.is_running,
                "counters": {
                    "race_counter": self.race_counter,
                    "car_counter": self.car_counter,
                    "cj_counter": self.cj_counter,
                    "sc_count": self.sc_count,
                    "global_loop_current": self.global_loop_current,
                },
                "window_region": list(region) if region else None,
                    "config_snapshot": {
                        "race_stall_timeout_seconds": self.config.get("race_stall_timeout_seconds", 60),
                        "race_restart_timeout_seconds": self.config.get("race_restart_timeout_seconds", 150),
                        "race_reverse_seconds": self.config.get("race_reverse_seconds", 3),
                        "process_guard_enabled": self.config.get("process_guard_enabled", True),
                    "process_guard_interval_seconds": self.config.get("process_guard_interval_seconds", 120),
                    "auto_restart": self.config.get("auto_restart", False),
                },
                "log_path": LOG_FILE,
                "screenshot_path": screenshot_path if screenshot_saved else None,
                "screenshot_error": screenshot_error,
                "recent_match_scores": self.get_recent_template_match_records(limit=80),
                "recent_match_issues": self.get_recent_template_match_issues(limit=40),
                "report_hint": {
                    "github_issues": "https://github.com/HikigayaHachiman0211/FH6Auto/issues",
                    "runtime_log": LOG_FILE,
                    "error_log_json": meta_path,
                    "diagnostics_dir": DIAGNOSTICS_DIR,
                    "screenshot": screenshot_path if screenshot_saved else None,
                },
            }

            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=4, ensure_ascii=False, default=str)

            if screenshot_saved:
                self.log(f"[诊断] 已保存失败截图: {screenshot_path}")
            else:
                self.log(f"[诊断] 截图保存失败，已记录诊断信息: {meta_path}")

            self.log(f"[诊断] 事件 {event_id}，诊断文件: {meta_path}")
            return {
                "event_id": event_id,
                "screenshot_path": screenshot_path if screenshot_saved else None,
                "meta_path": meta_path,
            }
        except Exception as e:
            self.log(f"[诊断] 保存失败现场时异常: {e}")
            return None

    def log_error_report_guidance(self, snapshot_info=None):
        now = time.time()
        last_hint_at = getattr(self, "last_error_report_hint_at", 0)
        if now - last_hint_at < 30:
            return
        self.last_error_report_hint_at = now

        self.log("如果需要开发者定位，请到 GitHub 提交更详细错误信息：")
        self.log("GitHub Issues: https://github.com/HikigayaHachiman0211/FH6Auto/issues")
        self.log(f"运行时 log: {LOG_FILE}")
        self.log(f"错误 log/截图目录: {DIAGNOSTICS_DIR}\\日期\\")
        if snapshot_info:
            meta_path = snapshot_info.get("meta_path")
            screenshot_path = snapshot_info.get("screenshot_path")
            if meta_path:
                self.log(f"本次错误 JSON: {meta_path}")
            if screenshot_path:
                self.log(f"本次错误截图: {screenshot_path}")
        self.log("请同时提供运行时 log、错误 JSON、错误截图；如果能复现，也请附上复现步骤和当时所在页面截图。")

    def perform_race_stall_recovery(self, reverse_seconds):
        self.hw_key_up("w")
        if not self.is_running:
            return False

        self.hw_key_down("s")
        reverse_end = time.time() + reverse_seconds
        while self.is_running and time.time() < reverse_end:
            time.sleep(0.05)
        self.hw_key_up("s")

        if not self.is_running:
            return False

        recovery_end = time.time() + 0.2
        while self.is_running and time.time() < recovery_end:
            time.sleep(0.05)

        if not self.is_running:
            return False

        self.hw_key_down("w")
        return True

    def restart_current_skill_race(self, race_index, target_count):
        self.log(f"跑图 {race_index}/{target_count}: 整轮超时，尝试重新开始赛事。")
        self.hw_key_up("w")
        time.sleep(0.3)
        self.hw_press("esc")
        time.sleep(1.2)

        pos_restart = self.wait_for_image(
            "RestartRace.png",
            region=self.regions["全界面"],
            threshold=0.70,
            timeout=8,
            interval=0.3,
            fast_mode=True,
        )
        if not pos_restart:
            self.log("未找到 重新开始赛事 选项。")
            self.capture_failure_snapshot(
                "skill_race_restart_option_not_found",
                module_name="race",
                details={"race_index": race_index, "target_count": target_count},
            )
            return False

        self.game_click(pos_restart)
        time.sleep(0.8)
        self.wait_for_any_image(
            ["RestartRaceConfirm.png", "RestartRaceConfirmPage.png"],
            region=self.regions["全界面"],
            threshold=0.65,
            timeout=4,
            interval=0.3,
            fast_mode=True,
        )
        self.hw_press("enter")
        self.log(f"跑图 {race_index}/{target_count}: 已发送重新开始赛事确认。")

        pos_start = self.wait_for_any_image(
            ["start.png", "startw.png"],
            region=self.regions["左下"],
            threshold=0.75,
            timeout=30,
            interval=0.4,
            fast_mode=True,
        )
        if not pos_start:
            self.log(f"跑图 {race_index}/{target_count}: 重开后未找到开始赛事按钮。")
            self.capture_failure_snapshot(
                "skill_race_restart_start_button_not_found",
                module_name="race",
                details={"race_index": race_index, "target_count": target_count},
            )
            return False

        self.game_click(pos_start)
        self.log(f"跑图 {race_index}/{target_count}: 已点击开始赛事按钮，准备继续给油。")
        time.sleep(0.5)
        return True

    def is_auto_restart_enabled(self):
        auto_restart = getattr(self, "var_auto_restart", None)
        if auto_restart is None:
            return bool(self.config.get("auto_restart", False))

        try:
            return bool(auto_restart.get())
        except Exception:
            return bool(self.config.get("auto_restart", False))

    def is_process_guard_enabled(self):
        process_guard = getattr(self, "var_process_guard_enabled", None)
        if process_guard is None:
            return bool(self.config.get("process_guard_enabled", True))

        try:
            return bool(process_guard.get())
        except Exception:
            return bool(self.config.get("process_guard_enabled", True))

    def on_process_guard_toggle(self):
        enabled = self.is_process_guard_enabled()
        self.config["process_guard_enabled"] = enabled
        self.save_config()
        if enabled:
            self.process_lost_event.clear()
            self.start_process_guard_thread()
        else:
            self.process_guard_seen_process = False
            self.process_lost_event.clear()
            self.stop_process_guard_thread()
            self.log("进程守护已关闭。")

    def get_game_process_pid(self, log_details=False):
        try:
            CREATE_NO_WINDOW = 0x08000000
            cmd = 'tasklist /FI "IMAGENAME eq forzahorizon6.exe" /NH /FO CSV'
            output = subprocess.check_output(cmd, shell=True, text=True, creationflags=CREATE_NO_WINDOW)

            if "forzahorizon6.exe" not in output.lower():
                if log_details:
                    self.log("未发现 forzahorizon6.exe 进程！(请确保游戏已运行)")
                return None

            for line in output.strip().split("\n"):
                parts = line.split('\",\"')
                if len(parts) >= 2 and "forzahorizon6.exe" in parts[0].lower():
                    return int(parts[1].replace('"', ""))

            if log_details:
                self.log("找到进程但无法解析PID！")
            return None
        except Exception as e:
            if log_details:
                self.log(f"检查进程异常: {e}")
            return None

    def should_abort_for_process_loss(self, details=None):
        if not self.process_lost_event.is_set() or self.recovery_in_progress.is_set():
            return False

        if self.last_failure_context and self.last_failure_context.get("reason") == "process_guard_detected":
            return True

        detail_map = {
            "message": "进程守护检测到 forzahorizon6.exe 已退出",
            "guard_interval_seconds": max(1, int(self.config.get("process_guard_interval_seconds", 120))),
            "current_step": self.current_step_name,
        }
        if details:
            detail_map.update(details)

        self.set_failure_context("process_guard_detected", detail_map)
        return True

    def quick_network_check(self):
        result = {
            "adapter": "unknown",
            "internet": "unknown",
            "details": [],
        }

        try:
            CREATE_NO_WINDOW = 0x08000000
            cmd = (
                'powershell -NoProfile -Command '
                '"Get-NetAdapter | Where-Object {$_.Status -eq \'Up\'} | '
                'Select-Object -First 1 -ExpandProperty Name"'
            )
            output = subprocess.check_output(
                cmd,
                shell=True,
                text=True,
                timeout=3,
                creationflags=CREATE_NO_WINDOW,
            ).strip()
            if output:
                result["adapter"] = "up"
                result["details"].append(f"network_adapter={output}")
            else:
                result["adapter"] = "down"
                result["internet"] = "offline"
                result["details"].append("network_adapter=none_up")
                return result
        except Exception as e:
            result["details"].append(f"adapter_check_error={e}")

        probe_urls = [
            "https://www.microsoft.com/favicon.ico",
            "https://www.github.com/favicon.ico",
            "https://www.baidu.com/favicon.ico",
        ]
        for url in probe_urls:
            try:
                resp = requests.get(url, timeout=2)
                result["details"].append(f"{url}={resp.status_code}")
                if 200 <= resp.status_code < 500:
                    result["internet"] = "online"
                    return result
            except Exception as e:
                result["details"].append(f"{url}=error:{type(e).__name__}")

        result["internet"] = "offline"
        return result

    def log_process_exit_network_state(self):
        net = self.quick_network_check()
        detail_text = "; ".join(net.get("details", [])) or "no_detail"
        if net.get("internet") == "online":
            self.log(f"进程守护：快速网络检查正常，网络可访问。{detail_text}")
        elif net.get("adapter") == "down":
            self.log(f"进程守护：快速网络检查异常，未检测到已连接网络适配器。{detail_text}")
        else:
            self.log(f"进程守护：快速网络检查异常，可能断网或网络不可达。{detail_text}")
        return net

    def stop_process_guard_thread(self):
        stop_event = self.process_guard_stop_event
        if stop_event is not None:
            stop_event.set()

        guard_thread = self.process_guard_thread
        if guard_thread and guard_thread.is_alive() and guard_thread is not threading.current_thread():
            guard_thread.join(timeout=0.5)

        self.process_guard_thread = None
        self.process_guard_stop_event = None

    def process_guard_loop(self, stop_event):
        first_check = True
        while not self.app_closing.is_set() and not stop_event.is_set():
            if not self.is_process_guard_enabled():
                return

            interval = max(1, int(self.config.get("process_guard_interval_seconds", 120)))
            if not first_check and stop_event.wait(timeout=interval):
                return
            first_check = False

            if self.app_closing.is_set() or stop_event.is_set():
                return

            if self.recovery_in_progress.is_set() or self.process_lost_event.is_set():
                continue

            pid = self.get_game_process_pid(log_details=False)
            if pid is not None:
                if not self.process_guard_seen_process:
                    self.log("进程守护：已检测到 forzahorizon6.exe。")
                self.process_guard_seen_process = True
                continue

            if not self.process_guard_seen_process and not self.is_running:
                continue

            if self.is_running:
                restart_hint = "准备恢复" if self.is_auto_restart_enabled() else "自动重启未开启，将中断当前任务"
                self.log(f"进程守护：检测间隔 {interval} 秒，发现 forzahorizon6.exe 已退出，{restart_hint}。")
                network_state = self.log_process_exit_network_state()
                self.set_failure_context(
                    "process_guard_detected",
                    {
                        "message": "进程守护检测到 forzahorizon6.exe 已退出",
                        "guard_interval_seconds": interval,
                        "current_step": self.current_step_name,
                        "network_state": network_state,
                    },
                )
                self.process_lost_event.set()
                return

            self.log("进程守护：检测到 forzahorizon6.exe 已退出，当前没有运行任务，仅记录状态。")
            self.log_process_exit_network_state()
            self.process_guard_seen_process = False

    def start_process_guard_thread(self):
        if self.app_closing.is_set() or self.recovery_in_progress.is_set() or not self.is_process_guard_enabled():
            return

        if self.process_guard_thread and self.process_guard_thread.is_alive():
            if self.is_running and self.get_game_process_pid(log_details=False) is not None:
                self.process_guard_seen_process = True
            return

        interval = max(1, int(self.config.get("process_guard_interval_seconds", 120)))
        self.process_guard_stop_event = threading.Event()
        self.process_guard_thread = threading.Thread(
            target=self.process_guard_loop,
            args=(self.process_guard_stop_event,),
            daemon=True,
        )
        self.process_guard_thread.start()
        self.log(f"进程守护已启动，检测间隔: {interval} 秒。")
   
    # ==========================================
    # --- 逻辑保障 ---
    # ==========================================
    # 【新增】：强制切换英文键盘与关闭中文状态
    def set_english_input(self):
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            if not hwnd:
                return
            # 策略1：尝试切美式键盘
            hkl = ctypes.windll.user32.LoadKeyboardLayoutW("00000409", 1)
            ctypes.windll.user32.PostMessageW(hwnd, 0x0050, 0, hkl) 
            # 策略2：底层强制关闭当前中文输入法的中文状态(绝杀)
            WM_IME_CONTROL = 0x0283
            IMC_SETOPENSTATUS = 0x0006
            ctypes.windll.user32.SendMessageW(hwnd, WM_IME_CONTROL, IMC_SETOPENSTATUS, 0)
            
            self.log("已自动切换英文键盘/关闭中文输入法状态。")
        except Exception as e:
            self.log(f"自动防中文输入设置失败: {e}")
    def check_and_focus_game(self):
        self.log("检查游戏进程 (forzahorizon6.exe)...")
        try:
            target_pid = self.get_game_process_pid(log_details=True)
            if not target_pid:
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
                if ctypes.windll.user32.IsIconic(hwnd):
                    ctypes.windll.user32.ShowWindow(hwnd, 9)
                else:
                    ctypes.windll.user32.ShowWindow(hwnd, 5)
                    
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                time.sleep(0.5)
                # ====== 【新增】：强制关闭中文输入法 ======
                self.set_english_input()
                # ==========================================
                try:
                    client_rect = win32gui.GetClientRect(hwnd)
                    pt = win32gui.ClientToScreen(hwnd, (0, 0))
                    x, y = pt[0], pt[1]
                    w, h = client_rect[2], client_rect[3]
                    self.update_regions_by_window(x, y, w, h)
                    # ====== 【新增】：小窗口精准吸附游戏所在屏幕的右上角 ======
                    def snap_to_game():
                        if self.is_running:
                            calc_w = int(w * 0.30)
                            calc_h = int(h * 0.10)
                            rs = self.get_resolution_scale()
                            calc_w = max(calc_w, int(520 * rs))
                            calc_h = max(calc_h, int(120 * rs))
                            pos_x = x + w - calc_w - 20
                            pos_y = y + 20
                            self.geometry(f"{calc_w}x{calc_h}+{pos_x}+{pos_y}")
                    self.ui_call(snap_to_game)
                    # ==========================================
                except Exception as e:
                    self.log(f"获取窗口坐标失败: {e}")

                time.sleep(1.0)
                return True

        except Exception as e:
            self.log(f"检查进程异常: {e}")
            return False

        return False

    def log_recovery(self, message):
        self.log(f"[恢复] {message}")

    def find_world_anchor(self, threshold=0.55):
        for image_name in ["anna.png", "link.png"]:
            pos = self.find_image(
                image_name,
                region=self.regions["左下"],
                threshold=threshold,
                fast_mode=True,
            )
            if pos:
                return image_name, pos

        return None, None

    def wait_for_interactive_recovery_state(self, timeout_seconds=300):
        deadline = time.time() + timeout_seconds
        last_enter_press_at = 0.0
        last_continue_click_at = 0.0

        while self.is_running and time.time() < deadline:
            if self.is_in_menu():
                self.log_recovery("检测到菜单锚点，游戏已回到菜单。")
                return "menu"

            anchor_name, _ = self.find_world_anchor(threshold=0.55)
            if anchor_name:
                self.log_recovery(f"检测到大世界锚点 {anchor_name}，游戏已回到可交互界面。")
                return "world"

            now = time.time()

            if self.find_image("horizon6.png", threshold=0.6):
                if now - last_enter_press_at >= 5.0:
                    self.log_recovery("检测到欢迎界面，按 Enter 推进启动流程。")
                    self.hw_press("enter")
                    last_enter_press_at = now
                time.sleep(1.5)
                continue

            pos_con = self.find_any_image(["continue-w.png", "continue-b.png"], threshold=0.6)
            if pos_con:
                if now - last_continue_click_at >= 8.0:
                    self.log_recovery("检测到继续游戏，点击进入。")
                    self.game_click(pos_con)
                    last_continue_click_at = now
                    time.sleep(8.0)
                else:
                    time.sleep(1.0)
                continue

            time.sleep(1.5)

        return None

    def restart_game_and_boot(self):
        if not self.is_auto_restart_enabled():
            self.log("未开启自动重启，任务结束。")
            return False

        self.log_recovery("触发自动重启机制！正在拉起游戏...")
        try:
            cmd_widget = getattr(self, "le_restart_cmd", None)
            cmd_str = cmd_widget.get() if cmd_widget else self.config.get("restart_cmd", "start steam://run/2483190")
            os.system(cmd_str)
        except Exception as e:
            self.log(f"执行重启命令失败: {e}")
            return False

        self.log_recovery("等待游戏启动加载 (10秒)...")
        for _ in range(10):
            if not self.is_running:
                return False
            time.sleep(1)

        self.log_recovery("开始持续检测重启后的游戏状态 (限制5分钟)...")
        recovery_state = self.wait_for_interactive_recovery_state(timeout_seconds=300)
        if recovery_state:
            self.log_recovery(f"自动重启后确认状态：{recovery_state}。")
            return True

        self.log_recovery("自动重启超时，未能确认进入大世界或菜单。")
        return False

    def recover_to_freeroam(self):
        self.log_recovery("尝试退回漫游重置状态...")
        for _ in range(30):
            if not self.is_running:
                return False

            anchor_name, _ = self.find_world_anchor(threshold=0.55)
            if anchor_name:
                self.log_recovery(f"成功退回漫游界面，命中锚点 {anchor_name}。")
                return True

            self.hw_press("esc")
            time.sleep(2.0)

        return self.wait_for_freeroam()

    def recover_to_menu(self):
        self.log_recovery("尝试退回主菜单重置状态...")
        world_anchor_logged = False
        for _ in range(120):
            if not self.is_running:
                return False

            if self.is_in_menu():
                self.log_recovery("成功退回主菜单界面！")
                return True

            anchor_name, _ = self.find_world_anchor(threshold=0.55)
            if anchor_name and not world_anchor_logged:
                self.log_recovery(f"检测到大世界锚点 {anchor_name}，按 ESC 尝试进入菜单。")
                world_anchor_logged = True

            if self.find_image("ExitRaceConfirm.png", region=self.regions["全界面"], threshold=0.70, fast_mode=True):
                self.log_recovery("检测到退出赛事确认弹窗，按 Enter 确认退出。")
                self.hw_press("enter")
                time.sleep(3.0)
                continue

            pos_exit = self.find_any_image(["exit.png", "exit-b.png"], region=self.regions["左下"], threshold=0.85)
            if pos_exit:
                # 检测是否处于赛事上下文，避免在主菜单等非赛事场景误点退出导致退出游戏
                in_race_context = self.find_any_image(
                    ["RestartRace.png", "start.png", "startw.png", "restart.png", "ExitRaceConfirm.png"],
                    region=self.regions["全界面"],
                    threshold=0.55,
                    fast_mode=True,
                )
                if in_race_context:
                    self.log_recovery("检测到赛事上下文，点击退出并确认返回大世界。")
                    self.game_click(pos_exit)
                    time.sleep(1.5)
                    self.hw_press("enter")  # 确认"是否退出比赛"
                    time.sleep(3.0)         # 等待退出到大世界
                else:
                    self.log_recovery("识别到退出按钮但非赛事上下文，跳过点击，改用 ESC 返回。")
                continue

            self.hw_press("esc")
            time.sleep(0.5)

        self.log_recovery("多次尝试仍未退回主菜单。")
        return False

    def ensure_recovery_menu_ready(self):
        if self.is_in_menu():
            self.log_recovery("已确认菜单锚点，无需额外菜单恢复。")
            return True, "already_in_menu"

        if self.recover_to_menu():
            return True, "recover_to_menu"

        self.log_recovery("直接退回菜单失败，尝试先确认大世界状态再重新进入菜单。")
        if not self.recover_to_freeroam():
            return False, "recover_to_freeroam"

        self.log_recovery("已确认回到大世界，尝试重新进入菜单。")
        if not self.enter_menu():
            return False, "enter_menu_after_freeroam"

        self.log_recovery("从大世界重新进入菜单成功。")
        return True, "enter_menu_after_freeroam"

    def attempt_recovery(self):
        self.recovery_in_progress.set()
        self.stop_process_guard_thread()
        try:
            recovery_stage = "focus_existing_game"
            self.log_recovery("任务执行异常中断，准备执行断点恢复流程...")
            if not self.check_and_focus_game():
                recovery_stage = "restart_game_and_boot_wait_interactive"
                if not self.restart_game_and_boot():
                    self.capture_failure_snapshot(
                        "recovery_failed",
                        module_name="attempt_recovery",
                        details={"stage": recovery_stage},
                    )
                    return False
                recovery_stage = "focus_restarted_game"
                if not self.check_and_focus_game():
                    self.capture_failure_snapshot(
                        "recovery_failed",
                        module_name="attempt_recovery",
                        details={"stage": recovery_stage},
                    )
                    return False
            else:
                self.log_recovery("检测到游戏进程仍存在，进入菜单恢复阶段。")

            recovery_ok, recovery_stage = self.ensure_recovery_menu_ready()
            if not recovery_ok:
                self.capture_failure_snapshot(
                    "recovery_failed",
                    module_name="attempt_recovery",
                    details={"stage": recovery_stage},
                )
                return False

            self.process_lost_event.clear()
            self.log_recovery("环境重置成功！即将从中断处继续剩余任务。")
            return True
        finally:
            self.recovery_in_progress.clear()

    def wait_for_freeroam(self):
        self.log_recovery("验证漫游状态...")
        for i in range(100):
            if not self.is_running:
                return False

            anchor_name, _ = self.find_world_anchor(threshold=0.55)
            if anchor_name:
                self.log_recovery(f"验证成功：已确认处于游戏漫游界面，命中锚点 {anchor_name}。")
                return True

            self.log_recovery(f"重试返回漫游界面({i + 1}/100)")
            self.hw_press("esc")

            for _ in range(20):
                if not self.is_running:
                    return False
                time.sleep(0.1)

        self.log_recovery("多次尝试验证漫游界面失败。")
        return False

    def is_in_menu(self):
        return self.find_any_image(
            ["collectionjournal.png", "nextstep.png"],
            region=self.regions["全界面"],
            threshold=0.55,
            fast_mode=True
        )

    def enter_menu(self):
        self.log("正在搜索菜单锚点...")
        menu_anchors = ["collectionjournal.png", "nextstep.png"]

        for i in range(100):
            if not self.is_running:
                return False

            pos = self.wait_for_any_image(
                menu_anchors,
                region=self.regions["全界面"],
                threshold=0.55,
                timeout=0.8,
                interval=0.15,
                fast_mode=True
            )
            if pos:
                self.log(f"成功进入菜单页面！({i + 1}/100)")
                time.sleep(0.4)
                return True

            self.log(f"未识别到菜单锚点，正在重试 ({i + 1}/100)")
            self.hw_press("esc")
            time.sleep(0.6)

        self.log("100 次尝试进入菜单均失败。")
        return False
    
    # ==========================================
    # --- 图像寻找 ---
    # ==========================================
    def load_template(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = actual_path

        if cache_key in self.template_cache:
            return self.template_cache[cache_key], actual_path

        tpl = cv2.imread(actual_path, cv2.IMREAD_COLOR)
        if tpl is not None:
            self.template_cache[cache_key] = tpl
        return tpl, actual_path
    def load_template_gray(self, template_path):
        actual_path = get_img_path(template_path)
        cache_key = ("gray", actual_path)
        if not hasattr(self, "template_gray_cache"):
            self.template_gray_cache = {}
        if cache_key in self.template_gray_cache:
            return self.template_gray_cache[cache_key]
        tpl = cv2.imread(actual_path, cv2.IMREAD_GRAYSCALE)
        if tpl is not None:
            self.template_gray_cache[cache_key] = tpl
        return tpl
    def get_images_root_dir(self):
        ext_dir = os.path.join(APP_DIR, "images")
        if os.path.isdir(ext_dir):
            return ext_dir

        int_dir = os.path.join(INTERNAL_DIR, "images")
        if os.path.isdir(int_dir):
            return int_dir

        return None

    def get_template_meta(self):
        images_dir = self.get_images_root_dir()
        meta_data = {}
        if not images_dir:
            return meta_data

        for root, _, files in os.walk(images_dir):
            for file in files:
                if not file.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                    continue

                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, images_dir).replace("\\", "/")

                try:
                    stat = os.stat(path)
                    meta_data[rel_path] = {
                        "mtime": stat.st_mtime,
                        "size": stat.st_size,
                    }
                except Exception:
                    pass

        return meta_data

    def is_template_cache_valid(self):
        if not os.path.exists(TEMPLATE_CACHE_FILE) or not os.path.exists(TEMPLATE_META_FILE):
            return False

        try:
            with open(TEMPLATE_META_FILE, "r", encoding="utf-8") as f:
                old_meta = json.load(f)
        except Exception:
            return False

        new_meta = self.get_template_meta()
        return old_meta == new_meta

    def build_template_file_cache(self):
        self.log("开始构建模板缓存文件...")
        os.makedirs(CACHE_DIR, exist_ok=True)

        images_dir = self.get_images_root_dir()
        if not images_dir:
            self.log("未找到 images 目录，无法构建模板缓存。")
            return False

        cache_data = {}
        meta_data = self.get_template_meta()

        scales = self.get_scales_to_try(fast_mode=False)

        for rel_path in meta_data.keys():
            img_path = os.path.join(images_dir, rel_path)
            tpl = cv2.imread(img_path, cv2.IMREAD_COLOR)
            if tpl is None:
                continue

            cache_data[rel_path] = {}
            for scale in scales:
                try:
                    if scale == 1.0:
                        scaled = tpl.copy()
                    else:
                        scaled = cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    cache_data[rel_path][str(round(scale, 3))] = scaled
                except Exception:
                    continue

        try:
            with open(TEMPLATE_CACHE_FILE, "wb") as f:
                pickle.dump(cache_data, f, protocol=pickle.HIGHEST_PROTOCOL)

            with open(TEMPLATE_META_FILE, "w", encoding="utf-8") as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)

            self.log("模板缓存文件构建完成。")
            return True
        except Exception as e:
            self.log(f"写入模板缓存失败: {e}")
            return False

    def load_template_file_cache(self):
        try:
            with open(TEMPLATE_CACHE_FILE, "rb") as f:
                self.file_template_cache = pickle.load(f)
            self.log("模板缓存文件加载成功。")
            return True
        except Exception as e:
            self.log(f"加载模板缓存失败: {e}")
            self.file_template_cache = {}
            return False

    def prepare_template_cache(self):
        os.makedirs(CACHE_DIR, exist_ok=True)

        if self.is_template_cache_valid():
            if self.load_template_file_cache():
                return

        self.log("模板缓存不存在或已失效，开始后台重建（这可能需要几秒钟）...")
        if self.build_template_file_cache():
            self.template_cache.clear()
            self.scaled_template_cache.clear()
            self.load_template_file_cache()

    def capture_region(self, region=None):
        try:
            if region:
                x, y, w, h = region
                # 将浮点数转换为整数，并计算右下角边界
                bbox = (int(x), int(y), int(x + w), int(y + h))
                # all_screens=True 允许跨越所有显示器截图
                screen = ImageGrab.grab(bbox=bbox, all_screens=True)
            else:
                screen = ImageGrab.grab(all_screens=True)
        except Exception:
            # 兼容老版本 Pillow 的降级方案
            screen = pyautogui.screenshot(region=region)
            
        return cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)

    def get_scales_to_try(self, fast_mode=True):
        full_region = self.regions.get("全界面")
        curr_w = full_region[2] if full_region else pyautogui.size()[0]
        # 你的图主要是按 2560 截的，就优先围绕 2560 计算
        primary_base = 2560
        primary_scale = curr_w / primary_base
        scales = []
        def add_scale(s):
            s = round(float(s), 3)
            if 0.45 <= s <= 1.8 and s not in scales:
                scales.append(s)
        # 先加“最可能正确”的比例及其微调
        add_scale(primary_scale)
        add_scale(primary_scale * 0.98)
        add_scale(primary_scale * 1.02)
        add_scale(primary_scale * 0.95)
        add_scale(primary_scale * 1.05)
        add_scale(primary_scale * 0.92)
        add_scale(primary_scale * 1.08)
        # 再兼容其它来源
        for bw in [1920, 1600]:
            s = curr_w / bw
            add_scale(s)
            add_scale(s * 0.98)
            add_scale(s * 1.02)
        # 最后兜底常用比例
        for s in [1.0, 0.95, 1.05, 0.9, 1.1, 0.85, 1.15, 0.8, 0.75, 0.7]:
            add_scale(s)
        if fast_mode:
            return scales[:8]
        return scales

    def get_scaled_template(self, template_path, scale):
        actual_path = get_img_path(template_path)
        images_dir = self.get_images_root_dir()

        if images_dir and os.path.exists(actual_path):
            try:
                rel_key = os.path.relpath(actual_path, images_dir).replace("\\", "/")
            except Exception:
                rel_key = os.path.basename(actual_path)
        else:
            rel_key = os.path.basename(actual_path)

        mem_key = (actual_path, round(scale, 3))
        if mem_key in self.scaled_template_cache:
            return self.scaled_template_cache[mem_key], actual_path

        scale_key = str(round(scale, 3))
        if rel_key in self.file_template_cache:
            tpl = self.file_template_cache[rel_key].get(scale_key)
            if tpl is not None:
                self.scaled_template_cache[mem_key] = tpl
                return tpl, actual_path

        template_orig, actual_path = self.load_template(template_path)
        if template_orig is None:
            return None, actual_path

        try:
            if scale == 1.0:
                tpl = template_orig.copy()
            else:
                tpl = cv2.resize(template_orig, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

            self.scaled_template_cache[mem_key] = tpl
            return tpl, actual_path
        except Exception:
            return None, actual_path

    def find_image_in_screen(self, screen_bgr, template_path, region=None, threshold=0.75, fast_mode=True):
        try:
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            effective_threshold = self.get_template_threshold(template_path, threshold)
            best_score = -1.0
            best_scale = None
            best_loc = None
            best_shape = None
            best_pos = None
            matched_pos = None
            matched_scale = None

            for scale in scales_to_try:
                tpl_c, actual_path = self.get_scaled_template(template_path, scale)
                if tpl_c is None:
                    continue

                h, w = tpl_c.shape[:2]
                if h < 5 or w < 5:
                    continue
                if h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                    continue

                res = cv2.matchTemplate(screen_bgr, tpl_c, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                max_val = float(max_val)
                if max_val > best_score:
                    best_score = max_val
                    best_scale = scale
                    best_loc = max_loc
                    best_shape = (w, h)
                    best_pos = (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )

                if matched_pos is None and max_val >= effective_threshold:
                    pos = (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
                    matched_pos = pos
                    matched_scale = scale

            if best_score < 0:
                best_score = 0.0

            self.record_template_match({
                "template": template_path,
                "score": best_score,
                "threshold": effective_threshold,
                "default_threshold": float(threshold),
                "scale": matched_scale if matched_scale is not None else (best_scale if best_scale is not None else 1.0),
                "pos": matched_pos if matched_pos is not None else best_pos,
                "best_loc": best_loc,
                "best_shape": best_shape,
                "matched": matched_pos is not None,
                "region_label": self.describe_match_region(region),
                "fast_mode": bool(fast_mode),
            })

            if matched_pos is not None:
                self.last_positions[template_path] = matched_pos
                return matched_pos

            return None

        except Exception as e:
            self.log(f"find_image_in_screen 异常: {e}")
            return None

    def find_image(self, template_path, region=None, threshold=0.75, fast_mode=True):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            return self.find_image_in_screen(
                screen_bgr,
                template_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode
            )
        except Exception as e:
            self.log(f"查找图片时发生异常: {e}")
            return None

    def find_any_image(self, image_list, region=None, threshold=MATCH_THRESHOLD, fast_mode=True):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            for img_path in image_list:
                pos = self.find_image_in_screen(
                    screen_bgr,
                    img_path,
                    region=region,
                    threshold=threshold,
                    fast_mode=fast_mode
                )
                if pos:
                    return pos
            return None
        except Exception as e:
            self.log(f"find_any_image 异常: {e}")
            return None

    def find_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, fast_mode=True):
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            main_threshold = self.get_template_threshold(main_path, threshold)
            sub_threshold = self.get_template_threshold(sub_path, threshold)
            best_main_score = 0.0
            best_main_scale = 1.0
            best_main_pos = None
            best_sub_score = 0.0
            matched_pos = None
            matched_scale = None
            for scale in scales_to_try:
                # 1. 结合新架构缓存直接读取缩放好的图像
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                sub_tpl_c, _ = self.get_scaled_template(sub_path, scale)
                if main_tpl_c is None or sub_tpl_c is None:
                    continue
                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue
                # 2. 一阶匹配：寻找全屏符合的主目标
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                _, scale_main_score, _, scale_main_loc = cv2.minMaxLoc(res_main)
                if float(scale_main_score) > best_main_score:
                    best_main_score = float(scale_main_score)
                    best_main_scale = scale
                    best_main_pos = (
                        scale_main_loc[0] + w_m // 2 + (region[0] if region else 0),
                        scale_main_loc[1] + h_m // 2 + (region[1] if region else 0),
                    )
                loc = np.where(res_main >= main_threshold)
                checked = set() # 【关键优化】：坐标去重，解决几十万次无效循环造成的卡顿
                for pt in zip(*loc[::-1]):
                    x, y = pt
                    # 过滤相邻 10 个像素内的重复识别点
                    key = (x // 10, y // 10)
                    if key in checked:
                        continue
                    checked.add(key)
                    # 3. 旧代码的核心精髓：在主图区域四周略微扩大 5 像素的范围内找元素
                    sub_roi = screen_bgr[
                        max(0, y - 5):min(screen_bgr.shape[0], y + h_m + 5),
                        max(0, x - 5):min(screen_bgr.shape[1], x + w_m + 5),
                    ]
                    if sub_tpl_c.shape[0] > sub_roi.shape[0] or sub_tpl_c.shape[1] > sub_roi.shape[1]:
                        continue
                    # 4. 二阶匹配：验证提取范围内是否包含子元素
                    res_sub = cv2.matchTemplate(sub_roi, sub_tpl_c, cv2.TM_CCOEFF_NORMED)
                    sub_score = float(cv2.minMaxLoc(res_sub)[1])
                    best_sub_score = max(best_sub_score, sub_score)
                    if sub_score >= sub_threshold:
                        matched_pos = (
                            x + w_m // 2 + (region[0] if region else 0),
                            y + h_m // 2 + (region[1] if region else 0),
                        )
                        matched_scale = scale
                        self.record_template_match({
                            "template": main_path,
                            "score": best_main_score,
                            "threshold": main_threshold,
                            "default_threshold": float(threshold),
                            "scale": matched_scale,
                            "pos": matched_pos,
                            "matched": True,
                            "region_label": self.describe_match_region(region),
                            "fast_mode": bool(fast_mode),
                        })
                        self.record_template_match({
                            "template": sub_path,
                            "score": best_sub_score,
                            "threshold": sub_threshold,
                            "default_threshold": float(threshold),
                            "scale": matched_scale,
                            "pos": matched_pos,
                            "matched": True,
                            "region_label": self.describe_match_region(region),
                            "fast_mode": bool(fast_mode),
                        })
                        return matched_pos
            self.record_template_match({
                "template": main_path,
                "score": best_main_score,
                "threshold": main_threshold,
                "default_threshold": float(threshold),
                "scale": best_main_scale,
                "pos": best_main_pos,
                "matched": False,
                "region_label": self.describe_match_region(region),
                "fast_mode": bool(fast_mode),
            })
            self.record_template_match({
                "template": sub_path,
                "score": best_sub_score,
                "threshold": sub_threshold,
                "default_threshold": float(threshold),
                "scale": best_main_scale,
                "pos": best_main_pos,
                "matched": False,
                "region_label": self.describe_match_region(region),
                "fast_mode": bool(fast_mode),
            })
            return None
        except Exception as e:
            self.log(f"find_image_with_element 异常: {e}")
            return None
    def find_image_with_element_stable(
        self,
        main_path,
        sub_path,
        region=None,
        main_threshold=0.60,
        verify_threshold=0.72,
        sub_threshold=0.70,
        max_candidates=15
    ):
        if not self.is_running:
            return None

        try:
            screen = pyautogui.screenshot(region=region)
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)

            main_tpl = self.load_template_gray(main_path)
            sub_tpl = self.load_template_gray(sub_path)

            if main_tpl is None or sub_tpl is None:
                return None

            h_m, w_m = main_tpl.shape[:2]
            h_s, w_s = sub_tpl.shape[:2]

            if h_m > screen_gray.shape[0] or w_m > screen_gray.shape[1]:
                return None

            res_main = cv2.matchTemplate(screen_gray, main_tpl, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(res_main >= main_threshold)

            if len(xs) == 0:
                return None

            candidates = [(float(res_main[y, x]), x, y) for x, y in zip(xs, ys)]
            candidates.sort(key=lambda t: t[0], reverse=True)

            checked = set()
            checked_count = 0

            for main_score, x, y in candidates:
                key = (x // 8, y // 8)
                if key in checked:
                    continue
                checked.add(key)

                checked_count += 1
                if checked_count > max_candidates:
                    break

                pad = 8
                x1 = max(0, x - pad)
                y1 = max(0, y - pad)
                x2 = min(screen_gray.shape[1], x + w_m + pad)
                y2 = min(screen_gray.shape[0], y + h_m + pad)

                sub_roi = screen_gray[y1:y2, x1:x2]
                if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                    continue

                res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                sub_score = cv2.minMaxLoc(res_sub)[1]

                if main_score >= verify_threshold and sub_score >= sub_threshold:
                    cx = x + w_m // 2
                    cy = y + h_m // 2
                    if region:
                        cx += region[0]
                        cy += region[1]
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"⚠️ find_image_with_element_stable 识别报错: {e}")
            return None
    
    def find_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
                                      main_threshold=0.60, like_threshold=0.75, final_threshold=0.72):
        if not self.is_running:
            return None

        try:
            screen_bgr = self.capture_region(region)
            screen_gray = self.to_gray_image(screen_bgr)
            screen_edge = self.to_edge_image(screen_bgr)

            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            effective_main_threshold = self.get_template_threshold(main_path, main_threshold)
            effective_like_threshold = self.get_template_threshold(sub_path, like_threshold)
            effective_final_threshold = self.get_template_threshold(main_path, final_threshold)

            best_score = 0.0
            best_pos = None
            best_scale = 1.0
            best_like_score = 0.0

            for scale in scales_to_try:
                main_tpl_c, _ = self.get_scaled_template(main_path, scale)
                sub_tpl_c, _ = self.get_scaled_template(sub_path, scale)

                if main_tpl_c is None or sub_tpl_c is None:
                    continue

                main_tpl_gray = self.to_gray_image(main_tpl_c)
                main_tpl_edge = self.to_edge_image(main_tpl_c)

                h_m, w_m = main_tpl_c.shape[:2]
                if h_m < 5 or w_m < 5:
                    continue
                if h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 用彩色主模板先找候选，但阈值放低一点，后面再综合筛
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= effective_main_threshold)

                checked_points = set()

                for pt in zip(*loc[::-1]):
                    x, y = pt

                    # 避免相邻重复点过多
                    key = (x // 10, y // 10)
                    if key in checked_points:
                        continue
                    checked_points.add(key)

                    roi_bgr = screen_bgr[y:y + h_m, x:x + w_m]
                    roi_gray = screen_gray[y:y + h_m, x:x + w_m]
                    roi_edge = screen_edge[y:y + h_m, x:x + w_m]

                    if roi_bgr.shape[:2] != main_tpl_c.shape[:2]:
                        continue

                    color_score = self.match_template_score(roi_bgr, main_tpl_c)
                    gray_score = self.match_template_score(roi_gray, main_tpl_gray)
                    edge_score = self.match_template_score(roi_edge, main_tpl_edge)

                    # 中心区域再匹配一次，减少白边影响
                    roi_center = self.crop_center_ratio(roi_bgr, ratio=0.6)
                    tpl_center = self.crop_center_ratio(main_tpl_c, ratio=0.6)
                    center_score = self.match_template_score(roi_center, tpl_center)

                    # like 标签匹配
                    pad = 5
                    sub_roi = screen_bgr[
                        max(0, y - pad):min(screen_bgr.shape[0], y + h_m + pad),
                        max(0, x - pad):min(screen_bgr.shape[1], x + w_m + pad),
                    ]
                    like_score = self.match_template_score(sub_roi, sub_tpl_c)
                    best_like_score = max(best_like_score, like_score)

                    if like_score < effective_like_threshold:
                        continue

                    final_score = (
                        color_score * 0.30 +
                        gray_score * 0.20 +
                        edge_score * 0.20 +
                        center_score * 0.15 +
                        like_score * 0.15
                    )

                    if final_score > best_score:
                        best_score = final_score
                        best_scale = scale
                        best_pos = (
                            x + w_m // 2 + (region[0] if region else 0),
                            y + h_m // 2 + (region[1] if region else 0),
                        )

            matched = best_score >= effective_final_threshold
            self.record_template_match({
                "template": main_path,
                "score": best_score,
                "threshold": effective_final_threshold,
                "default_threshold": float(final_threshold),
                "scale": best_scale,
                "pos": best_pos,
                "matched": matched,
                "region_label": self.describe_match_region(region),
                "fast_mode": bool(fast_mode),
            })
            self.record_template_match({
                "template": sub_path,
                "score": best_like_score,
                "threshold": effective_like_threshold,
                "default_threshold": float(like_threshold),
                "scale": best_scale,
                "pos": best_pos,
                "matched": matched and best_like_score >= effective_like_threshold,
                "region_label": self.describe_match_region(region),
                "fast_mode": bool(fast_mode),
            })

            if matched:
                self.log(f"[multi_match] 命中 {main_path} 最终分数: {best_score:.3f}")
                return best_pos

            self.log(f"[multi_match] 未命中 {main_path}，最高分仅: {best_score:.3f}")
            return None

        except Exception as e:
            self.log(f"find_image_with_element_multi 异常: {e}")
            return None
    def find_image_with_element_fast(self, main_path, sub_path, region=None, threshold=0.70, sub_threshold=0.70):
        if not self.is_running:
            return None

        try:
            screen = pyautogui.screenshot(region=region)
            screen_gray = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2GRAY)

            main_tpl = self.load_template_gray(main_path)
            sub_tpl = self.load_template_gray(sub_path)

            if main_tpl is None or sub_tpl is None:
                return None

            h_m, w_m = main_tpl.shape[:2]
            h_s, w_s = sub_tpl.shape[:2]

            if h_m > screen_gray.shape[0] or w_m > screen_gray.shape[1]:
                return None

            res_main = cv2.matchTemplate(screen_gray, main_tpl, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res_main >= threshold)

            checked = set()

            for pt in zip(*loc[::-1]):
                x, y = pt

                # 去重，避免相邻重复点太多
                key = (x // 10, y // 10)
                if key in checked:
                    continue
                checked.add(key)

                x1 = max(0, x - 5)
                y1 = max(0, y - 5)
                x2 = min(screen_gray.shape[1], x + w_m + 5)
                y2 = min(screen_gray.shape[0], y + h_m + 5)

                sub_roi = screen_gray[y1:y2, x1:x2]

                if sub_roi.shape[0] < h_s or sub_roi.shape[1] < w_s:
                    continue

                res_sub = cv2.matchTemplate(sub_roi, sub_tpl, cv2.TM_CCOEFF_NORMED)
                _, max_val_sub, _, _ = cv2.minMaxLoc(res_sub)

                if max_val_sub >= sub_threshold:
                    cx = x + w_m // 2
                    cy = y + h_m // 2
                    if region:
                        cx += region[0]
                        cy += region[1]
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"find_image_with_element_fast 异常: {e}")
            return None

    def wait_for_image_with_element_multi(self, main_path, sub_path, region=None, fast_mode=True,
        main_threshold=0.60, like_threshold=0.75,
        final_threshold=0.72, timeout=30, interval=0.4):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            if self.should_abort_for_process_loss({"wait_target": main_path, "wait_mode": "image_with_element_multi"}):
                return None

            pos = self.find_image_with_element_multi(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                fast_mode=fast_mode,
                main_threshold=main_threshold,
                like_threshold=like_threshold,
                final_threshold=final_threshold
            )
            if pos:
                return pos

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                if self.should_abort_for_process_loss({"wait_target": main_path, "wait_mode": "image_with_element_multi"}):
                    return None
                time.sleep(0.05)

        return None
    def wait_for_image_with_element_stable(
        self,
        main_path,
        sub_path,
        region=None,
        main_threshold=0.60,
        verify_threshold=0.72,
        sub_threshold=0.70,
        max_candidates=15,
        timeout=3,
        interval=0.2
    ):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_stable(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                main_threshold=main_threshold,
                verify_threshold=verify_threshold,
                sub_threshold=sub_threshold,
                max_candidates=max_candidates
            )
            if pos:
                return pos
            time.sleep(interval)
        return None
    def wait_for_image_with_element_fast(
        self,
        main_path,
        sub_path,
        region=None,
        threshold=0.70,
        sub_threshold=0.70,
        timeout=4,
        interval=0.25
    ):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_with_element_fast(
                main_path=main_path,
                sub_path=sub_path,
                region=region,
                threshold=threshold,
                sub_threshold=sub_threshold
            )
            if pos:
                return pos

            time.sleep(interval)

        return None

    def find_image_smart(self, template_path, primary_region=None, fallback_region=None, threshold=0.75, fast_mode=True):
        if primary_region:
            pos = self.find_image(template_path, region=primary_region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos

        if fallback_region:
            return self.find_image(template_path, region=fallback_region, threshold=threshold, fast_mode=fast_mode)

        return None
    def to_gray_image(self, img):
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    def to_edge_image(self, img):
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edge = cv2.Canny(blur, 50, 150)
        return edge
    def crop_center_ratio(self, img, ratio=0.6):
        h, w = img.shape[:2]
        ch = int(h * ratio)
        cw = int(w * ratio)
        y1 = max(0, (h - ch) // 2)
        x1 = max(0, (w - cw) // 2)
        return img[y1:y1 + ch, x1:x1 + cw]

    def wait_for_any_image(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            if self.should_abort_for_process_loss({"wait_targets": list(image_list), "wait_mode": "any_image"}):
                return None

            try:
                screen_bgr = self.capture_region(region)
                for img_path in image_list:
                    pos = self.find_image_in_screen(
                        screen_bgr,
                        img_path,
                        region=region,
                        threshold=threshold,
                        fast_mode=fast_mode
                    )
                    if pos:
                        return pos
            except Exception as e:
                self.log(f"wait_for_any_image 异常: {e}")

            if log_text:
                self.log(log_text)

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                if self.should_abort_for_process_loss({"wait_targets": list(image_list), "wait_mode": "any_image"}):
                    return None
                time.sleep(0.05)

        return None

    def wait_for_image(self, template_path, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        return self.wait_for_any_image(
            [template_path],
            region=region,
            threshold=threshold,
            timeout=timeout,
            interval=interval,
            fast_mode=fast_mode,
            log_text=log_text
        )

    def is_like_guard_enabled(self):
        var_widget = getattr(self, "var_like_guard_enabled", None)
        if var_widget is not None:
            try:
                return bool(var_widget.get())
            except Exception:
                pass
        return bool(self.config.get("like_guard_enabled", True))

    def get_like_guard_stall_seconds(self):
        entry_widget = getattr(self, "entry_like_guard_stall_seconds", None)
        if entry_widget is not None:
            return self.get_positive_entry_value(
                entry_widget,
                self.config.get("like_guard_stall_seconds", 180),
            )
        return self.get_config_int("like_guard_stall_seconds", 180)

    def get_like_guard_max_prompt_passes(self):
        return self.get_config_int("like_guard_max_prompt_passes", 3)

    def get_like_prompt_like_templates(self):
        return ["LikeB2.png", "LikeW2.png"]

    def get_like_prompt_anchor_templates(self):
        return ["DislikeW2.png", "CancelB2.png", "CancelW2.png"]

    def find_like_prompt_candidate(self, region=None, like_threshold=0.66, anchor_threshold=0.68):
        if not self.is_running:
            return None

        region = region or self.regions["全界面"]
        try:
            screen_bgr = self.capture_region(region)
            for template_name in self.get_like_prompt_like_templates():
                pos = self.find_image_in_screen(
                    screen_bgr,
                    template_name,
                    region=region,
                    threshold=like_threshold,
                    fast_mode=True,
                )
                if pos:
                    return {"action": "like", "template": template_name, "pos": pos}

            for template_name in self.get_like_prompt_anchor_templates():
                pos = self.find_image_in_screen(
                    screen_bgr,
                    template_name,
                    region=region,
                    threshold=anchor_threshold,
                    fast_mode=True,
                )
                if pos:
                    return {"action": "anchor", "template": template_name, "pos": pos}
        except Exception as e:
            self.log(f"点赞检测识别异常: {e}")

        return None

    def handle_like_prompt_sequence(self, context="未知状态"):
        if not self.is_like_guard_enabled():
            return 0

        max_passes = self.get_like_guard_max_prompt_passes()
        handled_count = 0
        anchor_snapshot_saved = False
        for attempt in range(1, max_passes + 1):
            if not self.is_running:
                break

            candidate = self.find_like_prompt_candidate(region=self.regions["全界面"])
            if not candidate:
                break

            if candidate.get("action") != "like":
                self.log(
                    f"点赞检测：{context} 疑似点赞弹窗，但只命中 {candidate.get('template')}，未点击点踩/取消。"
                )
                if not anchor_snapshot_saved:
                    self.capture_failure_snapshot(
                        "like_prompt_like_button_not_found",
                        module_name="like_guard",
                        details={
                            "context": context,
                            "matched_template": candidate.get("template"),
                            "message": "疑似点赞弹窗但未命中点赞按钮模板",
                        },
                    )
                    anchor_snapshot_saved = True
                break

            self.log(
                f"点赞检测：{context} 命中点赞按钮 {candidate.get('template')} "
                f"({attempt}/{max_passes})，执行点赞。"
            )
            self.game_click(candidate.get("pos"))
            handled_count += 1
            if not self.wait_with_running(0.8):
                break

            still_prompt = self.find_like_prompt_candidate(region=self.regions["全界面"])
            if not still_prompt:
                continue

            self.log(
                f"点赞检测：{context} 点击后仍检测到 {still_prompt.get('template')}，补按 Enter 确认。"
            )
            self.hw_press("enter")
            if not self.wait_with_running(1.0):
                break

            still_prompt = self.find_like_prompt_candidate(region=self.regions["全界面"])
            if still_prompt:
                self.log(
                    f"点赞检测：{context} Enter 兜底后仍检测到 {still_prompt.get('template')}，停止本轮点赞处理。"
                )
                break

        if handled_count:
            self.log(f"点赞检测：{context} 已处理 {handled_count} 个点赞弹窗。")
        return handled_count

    def handle_like_prompt_after_stall(self, context, stall_started_at):
        if not self.is_like_guard_enabled():
            return 0

        stall_seconds = self.get_like_guard_stall_seconds()
        elapsed = time.time() - stall_started_at
        remaining = stall_seconds - elapsed
        if remaining > 0:
            self.log(
                f"点赞检测：{context} 已等待 {int(elapsed)} 秒，"
                f"将在 {stall_seconds} 秒卡住阈值后检查点赞弹窗。"
            )
            if not self.wait_with_running(remaining):
                return 0

        return self.handle_like_prompt_sequence(context)

    def wait_for_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, timeout=30, interval=0.4, fast_mode=True):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
            if self.should_abort_for_process_loss({"wait_target": main_path, "wait_mode": "image_with_element"}):
                return None

            pos = self.find_image_with_element(
                main_path,
                sub_path,
                region=region,
                threshold=threshold,
                fast_mode=fast_mode
            )
            if pos:
                return pos

            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                if self.should_abort_for_process_loss({"wait_target": main_path, "wait_mode": "image_with_element"}):
                    return None
                time.sleep(0.05)

        return None

    def match_template_score(self, src, tpl):
        try:
            if tpl is None or src is None:
                return 0.0
            th, tw = tpl.shape[:2]
            sh, sw = src.shape[:2]
            if th < 5 or tw < 5 or th > sh or tw > sw:
                return 0.0
            res = cv2.matchTemplate(src, tpl, cv2.TM_CCOEFF_NORMED)
            return cv2.minMaxLoc(res)[1]
        except Exception:
            return 0.0

    def show_mini_running_ui(self):
        # 隐藏大窗的所有元素
        self.config_frame.pack_forget()
        self.global_settings_frame.pack_forget()
        if hasattr(self, "pipeline_tip_frame"):
            self.pipeline_tip_frame.pack_forget()
        if hasattr(self, "cr_ticket_warning_frame"):
            self.cr_ticket_warning_frame.pack_forget()
        self.calc_frame.pack_forget()
        if hasattr(self, "super_calc_frame"):
            self.super_calc_frame.pack_forget()
        if hasattr(self, "cr_frame"):
            self.cr_frame.pack_forget()
        self.top_container.pack_forget()
        if hasattr(self, "bottom_frame"):
            self.bottom_frame.pack_forget()

        # 显示新的迷你横向 UI
        self.mini_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.main_window_geometry_before_mini = self.geometry()

        # ====== 运行中小窗默认保持保守尺寸，避免遮挡游戏模板区域；用户仍可手动拉伸。 ======
        last_x, last_y, last_w, last_h = self.regions["全界面"]
        if last_w <= 0: last_w = self.winfo_screenwidth()
        if last_h <= 0: last_h = self.winfo_screenheight()

        calc_w = int(last_w * 0.30)
        calc_h = int(last_h * 0.10)
        rs = self.get_resolution_scale()
        calc_w = max(calc_w, int(520 * rs))
        calc_h = max(calc_h, int(120 * rs))

        pos_x = last_x + last_w - calc_w - 20
        pos_y = last_y + 20

        self.attributes("-topmost", True)
        self.minsize(420, 110)
        self.resizable(True, True)
        self.geometry(f"{calc_w}x{calc_h}+{pos_x}+{pos_y}")

        # 启动计时器
        self.start_time = time.time()
        self.update_timer()

    def should_skip_startup_prompts(self, prompt_name):
        var_widget = getattr(self, "var_skip_startup_prompts", None)
        try:
            enabled = bool(var_widget.get()) if var_widget is not None else bool(self.config.get("skip_startup_prompts", False))
        except Exception:
            enabled = bool(self.config.get("skip_startup_prompts", False))

        if enabled:
            self.log(f"已按设置跳过启动提示弹窗：{prompt_name}")
        return enabled

    def confirm_pipeline_requirements(self, start_step):
        if start_step not in {"race", "buy", "cj", "sell"}:
            return True

        if self.should_skip_startup_prompts("启动前强提示"):
            return True

        warning = (
            "启动前请先确认：\n\n"
            "1. 请把桌面分辨率调节为 2K 使用。\n"
            "2. 跑图车辆请使用默认涂装，不要更换涂装。\n"
            "3. 跑图用车辆调教已经提前点赞。\n"
            "4. 跑图蓝图已经提前点赞。\n"
            "5. 作者测试使用 B站【地平线6 25秒10技术点2.0】视频中的蓝图和车辆调教。\n"
            "   视频: https://www.bilibili.com/video/BV13vGv6JEqw/?share_source=copy_web&vd_source=fd5ff2dddef9d74dc41f3ea17bd9d996\n"
            "   车辆共享代码: 772778773；地图共享代码: 705399298。\n\n"
            "6. 建议车库里除了22b以外的斯巴鲁品牌车辆换成白色等与原厂差异大的涂装，用来提高刷图车辆模板识别稳定性。\n"
            "   但跑图车辆本身请保持默认涂装。\n\n"
            "7. 建议把用于刷技术点的 22B 技能树提前点满，可明显提高获取效率，最快一张图约 9-10 技能点。\n"
            "8. 游戏难度已改为【所向披靡】，避免出现“赢得太轻松，建议更换难度”的提示卡住流程。\n"
            "9. 转向已改为【自动转向】。\n"
            "10. 换挡已改为【自动挡】。\n\n"
            "11. 建议首次进入【设计与喷漆】时，将默认提示勾选【不再显示此消息】，可提高脚本稳定性和执行效率。\n\n"
            "12. 脚本会通过【设计与喷漆】页面快速选车；为保证选车正常，请提前手动进入该界面，并将进入时触发的提示弹窗选择【不再显示此消息】。\n\n"
            "【旧版兼容提醒】\n"
            "如果你继续使用旧模板/旧蓝图，请自行确认车辆、调教、蓝图与当前模板匹配。\n\n"
            "【移除车辆重要提醒】\n"
            "删除逻辑会筛选并批量移除【重复项 + B级 + 全轮驱动 + 传奇】车辆，大概率是 22B。\n"
            "启动前必须人工审核筛选结果；如果有其他车辆混入，请先改装至非 B 级或不要启动删车。\n\n"
            "【买车 CR 重要提醒】\n"
            "如果买车时 CR 点不足，游戏可能会消耗车辆票券（贵重物品）。\n"
            "请一定一定要预留充足 CR 点再进行刷技术点！\n\n"
            "否则可能出现模板误判、点赞弹窗卡住、超级抽奖选错车/买错车等问题。\n\n"
            "确认已经处理好后再继续启动。"
        )
        try:
            return bool(messagebox.askokcancel("启动前强提示", warning, parent=self))
        except Exception:
            self.log(warning.replace("\n", " "))
            return True

    def confirm_cr_grind_requirements(self):
        if self.should_skip_startup_prompts("刷CR点启动前强提醒"):
            return True

        warning = (
            "刷CR点启动前强提醒：\n\n"
            "1. 五菱、丰田两辆刷CR点车辆必须保持【出场涂装】，不要换涂装。\n"
            "2. 如果想让 CR 点收益最高，可以把驾驶辅助预设直接调整到【终极】，这样能获取最多 CR 点奖励。\n"
            "3. 建议提前给刷CR点车辆调教点赞，避免周期结算后弹出点赞窗口卡住流程。\n"
            "4. 如果后续还要继续刷技术点，记得把设置改回【自动挡】和【自动转向】。\n"
            "5. 脚本其他流水线会通过【设计与喷漆】页面快速选车；为保证后续选车正常，请提前手动进入该界面，并将进入时触发的提示弹窗选择【不再显示此消息】。\n\n"
            "确认已经处理好后再继续启动刷CR点。"
        )
        try:
            return bool(messagebox.askokcancel("刷CR点启动前强提醒", warning, parent=self))
        except Exception:
            self.log(warning.replace("\n", " "))
            return True

    def confirm_auto_super_wheelspin_requirements(self):
        if self.should_skip_startup_prompts("自动超级抽奖启动前强提醒"):
            return True

        warning = (
            "自动超级抽奖启动前强提醒：\n\n"
            "1. 请先手动打开游戏里的【超级抽奖】页面。\n"
            "2. 当前脚本只负责高频按 Enter 快速抽奖，不负责自动进入页面或智能识别奖励。\n"
            "3. 智能超级抽奖功能正在开发中。\n"
            "4. 脚本其他流水线会通过【设计与喷漆】页面快速选车；为保证后续选车正常，请提前手动进入该界面，并将进入时触发的提示弹窗选择【不再显示此消息】。\n\n"
            "确认已经停留在超级抽奖页面后再继续启动。"
        )
        try:
            return bool(messagebox.askokcancel("自动超级抽奖启动前强提醒", warning, parent=self))
        except Exception:
            self.log(warning.replace("\n", " "))
            return True

    def confirm_pipeline_final_check(self):
        """强提醒之后追加的最终确认，提示用户检查关键设置。"""
        if self.should_skip_startup_prompts("最终确认"):
            return True

        warning = (
            "⚠ 最终确认：\n\n"
            "1. 请根据上方日志提示，确认已选择正确的车辆和调教。\n"
            "2. 确认蓝图分享代码正确，蓝图已点赞。\n"
            "3. 确认车辆调教已点赞。\n"
            "4. 确认游戏难度已设为【所向披靡】。\n"
            "5. 确认【自动转向】已开启。\n"
            "6. 确认【自动换挡】已开启。\n"
            "7. 确认已提前进入【设计与喷漆】页面，并将提示弹窗选择【不再显示此消息】。\n\n"
            "以上全部确认无误后再启动！"
        )
        try:
            return bool(messagebox.askokcancel("最终确认", warning, parent=self))
        except Exception:
            self.log(warning.replace("\n", " "))
            return True

    def start_pipeline(self, start_step):
        if self.is_running:
            return

        if not self.confirm_pipeline_requirements(start_step):
            self.log("用户取消启动：未确认车辆涂装/点赞前置要求。")
            return

        if not self.confirm_pipeline_final_check():
            self.log("用户取消启动：未通过最终确认。")
            return

        self.is_running = True
        self.process_lost_event.clear()
        self.recovery_in_progress.clear()
        self.save_config()

        self.show_mini_running_ui()
        self.update_running_ui("初始化中...")
        self.clear_mini_cr_status()
        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.sc_count = 0
        self.global_loop_current = 0

        def runner():
            pipeline_success = False

            def execute_pipeline():
                steps = ["race", "buy", "cj", "sell"]
                curr_idx = steps.index(start_step)

                try:
                    total_loops = int(self.entry_global_loop.get())
                except Exception:
                    total_loops = self.config.get("global_loops", 10)
                self.global_loop_current = 1
                self.pipeline_next_step_override = None
                if hasattr(self, "lbl_mini_loop"):
                    self.ui_call(self.lbl_mini_loop.configure, text=f"大循环: {self.global_loop_current} / {total_loops}")
                while self.is_running:
                    step_name = steps[curr_idx]
                    step_success = False
                    self.current_step_name = step_name
                    self.clear_failure_context()

                    if self.should_abort_for_process_loss({"check_point": "before_step", "step_name": step_name}):
                        step_success = False
                    else:
                        try:
                            if step_name == "race":
                                step_success = self.execute_verified_step(
                                    "循环跑图模块",
                                    lambda: self.logic_race(int(self.entry_race.get())),
                                    retry_count=self.get_config_int("general_step_retry_count", 2),
                                )
                            elif step_name == "buy":
                                step_success = self.execute_verified_step(
                                    "批量买车模块",
                                    lambda: self.logic_buy_car(int(self.entry_car.get())),
                                    retry_count=self.get_config_int("general_step_retry_count", 2),
                                )
                            elif step_name == "cj":
                                step_success = self.execute_verified_step(
                                    "超级抽奖模块",
                                    lambda: self.logic_super_wheelspin(int(self.entry_cj.get())),
                                    retry_count=self.get_config_int("general_step_retry_count", 2),
                                )
                            elif step_name == "sell":
                                step_success = self.execute_verified_step(
                                    "移除车辆模块",
                                    lambda: self.sell_consumable_car(int(self.entry_sc.get())),
                                    retry_count=self.get_config_int("general_step_retry_count", 2),
                                )
                        except Exception as e:
                            self.log(f"执行模块 {step_name} 时异常: {e}")
                            self.set_failure_context(
                                "module_exception",
                                {
                                    "exception": str(e),
                                    "traceback": traceback.format_exc(),
                                },
                            )
                            step_success = False

                    if not self.is_running:
                        return False

                    if step_success and self.should_abort_for_process_loss({"check_point": "after_step", "step_name": step_name}):
                        step_success = False

                    if not step_success:
                        failure_context = self.last_failure_context or {
                            "reason": "module_failed",
                            "details": {"message": "模块返回 False"},
                        }
                        snapshot_info = self.capture_failure_snapshot(
                            failure_context.get("reason", "module_failed"),
                            module_name=step_name,
                            details=failure_context.get("details"),
                        )
                        if self.attempt_recovery():
                            self.process_lost_event.clear()
                            self.start_process_guard_thread()
                            self.clear_failure_context()
                            self.log_recovery(f"恢复完成，重新进入 {step_name} 模块。")
                            continue
                        else:
                            self.log("致命错误：断点恢复失败，彻底停止。")
                            self.log_error_report_guidance(snapshot_info)
                            return False
                    #v1.0.1
                    # ====== 核心流转与无限循环逻辑 ======
                    next_idx = curr_idx + 1 # 默认前往下一步
                    override_step = self.pipeline_next_step_override
                    self.pipeline_next_step_override = None
                    if override_step in steps:
                        next_idx = steps.index(override_step)
                        self.log(f"流水线按业务分支跳转到 {override_step} 模块。")
                        curr_idx = next_idx
                        continue

                    if curr_idx == 0:
                        if self.var_chk1.get():
                            try: next_idx = max(0, min(3, int(self.entry_next1.get()) - 1))
                            except Exception: next_idx = 1
                        else: break
                    elif curr_idx == 1:
                        if self.var_chk2.get():
                            try: next_idx = max(0, min(3, int(self.entry_next2.get()) - 1))
                            except Exception: next_idx = 2
                        else: break
                    elif curr_idx == 2:
                        if self.var_chk3.get():
                            try: next_idx = max(0, min(3, int(self.entry_next3.get()) - 1))
                            except Exception: next_idx = 3
                        else: break
                    elif curr_idx == 3:
                        if self.var_chk4.get():
                            try: next_idx = max(0, min(3, int(self.entry_next4.get()) - 1))
                            except Exception: next_idx = 0
                        else: break

                    if next_idx <= curr_idx:
                        self.global_loop_current += 1

                        if self.global_loop_current > total_loops:
                            self.log("达到设定的总循环次数，任务圆满结束。")
                            break

                        self.log(f"开启新一轮大循环 ({self.global_loop_current}/{total_loops})")

                        if hasattr(self, "lbl_mini_loop"):
                            self.ui_call(self.lbl_mini_loop.configure, text=f"大循环: {self.global_loop_current} / {total_loops}")

                        self.race_counter = 0
                        self.car_counter = 0
                        self.cj_counter = 0
                        self.sc_count = 0

                    curr_idx = next_idx

                return True

            try:
                if not self.check_and_focus_game():
                    return
                self.start_process_guard_thread()
                pipeline_success = execute_pipeline()
            except Exception as e:
                self.log(f"流水线异常: {e}")
                self.set_failure_context(
                    "pipeline_exception",
                    {"exception": str(e), "traceback": traceback.format_exc()},
                )
            finally:
                while self.is_running and not pipeline_success:
                    failure_context = self.last_failure_context or {
                        "reason": "pipeline_failed",
                        "details": {"message": "流水线未成功完成"},
                    }
                    snapshot_info = self.capture_failure_snapshot(
                        failure_context.get("reason", "pipeline_failed"),
                        module_name="pipeline",
                        details=failure_context.get("details"),
                    )
                    if self.attempt_recovery():
                        self.process_lost_event.clear()
                        self.start_process_guard_thread()
                        self.clear_failure_context()
                        self.log_recovery("流水线恢复完成，重新进入流水线。")
                        self.race_counter = 0
                        self.car_counter = 0
                        self.cj_counter = 0
                        self.sc_count = 0
                        self.global_loop_current = 0
                        try:
                            pipeline_success = execute_pipeline()
                        except Exception as e2:
                            self.log(f"流水线恢复后异常: {e2}")
                            self.set_failure_context(
                                "pipeline_exception",
                                {"exception": str(e2), "traceback": traceback.format_exc()},
                            )
                        continue

                    self.log("流水线恢复失败，停止任务。")
                    self.log_error_report_guidance(snapshot_info)
                    break

                self.stop_all()

        self.current_thread = threading.Thread(target=runner, daemon=True)
        self.current_thread.start()

    def start_auto_super_wheelspin(self):
        if self.is_running:
            return

        if not self.confirm_auto_super_wheelspin_requirements():
            self.log("用户取消启动：未确认已手动打开超级抽奖页面。")
            return

        self.is_running = True
        self.process_lost_event.clear()
        self.recovery_in_progress.clear()
        self.clear_failure_context()
        self.save_config()
        self.show_mini_running_ui()
        self.update_running_ui("自动超级抽奖", 0, 0)
        self.clear_mini_cr_status()

        def runner():
            press_count = 0
            success = False
            try:
                if not self.check_and_focus_game():
                    return

                self.start_process_guard_thread()
                self.log("自动超级抽奖已启动：请保持在超级抽奖界面，F8 或停止按钮结束。")
                next_press_at = time.time()
                while self.is_running:
                    if self.should_abort_for_process_loss({"check_point": "auto_cj_loop"}):
                        break
                    self.hw_press("enter", delay=0.04)
                    press_count += 1
                    self.update_running_ui("自动超级抽奖", press_count, 0)

                    next_press_at += 1.0 / 6.0
                    sleep_seconds = max(0.0, next_press_at - time.time())
                    sleep_end = time.time() + sleep_seconds
                    while self.is_running and time.time() < sleep_end:
                        if self.should_abort_for_process_loss({"check_point": "auto_cj_loop_sleep"}):
                            break
                        time.sleep(0.02)
                success = True
            except Exception as e:
                self.log(f"自动超级抽奖异常: {e}")
                self.set_failure_context(
                    "auto_super_wheelspin_exception",
                    {
                        "exception": str(e),
                        "traceback": traceback.format_exc(),
                    },
                )
            finally:
                while self.is_running and not success:
                    failure_context = self.last_failure_context or {
                        "reason": "auto_super_wheelspin_failed",
                        "details": {"message": "自动超级抽奖流程未成功完成"},
                    }
                    snapshot_info = self.capture_failure_snapshot(
                        failure_context.get("reason", "auto_super_wheelspin_failed"),
                        module_name="cj",
                        details=failure_context.get("details"),
                    )
                    if self.attempt_recovery():
                        self.process_lost_event.clear()
                        self.start_process_guard_thread()
                        self.clear_failure_context()
                        self.log_recovery("自动超级抽奖恢复完成，重新进入抽奖流程。")
                        press_count = 0
                        try:
                            self.log("自动超级抽奖已启动：请保持在超级抽奖界面，F8 或停止按钮结束。")
                            next_press_at = time.time()
                            while self.is_running:
                                if self.should_abort_for_process_loss({"check_point": "auto_cj_loop"}):
                                    break
                                self.hw_press("enter", delay=0.04)
                                press_count += 1
                                self.update_running_ui("自动超级抽奖", press_count, 0)
                                next_press_at += 1.0 / 6.0
                                sleep_seconds = max(0.0, next_press_at - time.time())
                                sleep_end = time.time() + sleep_seconds
                                while self.is_running and time.time() < sleep_end:
                                    if self.should_abort_for_process_loss({"check_point": "auto_cj_loop_sleep"}):
                                        break
                                    time.sleep(0.02)
                            success = True
                        except Exception as e2:
                            self.log(f"自动超级抽奖恢复后异常: {e2}")
                            self.set_failure_context(
                                "auto_super_wheelspin_exception",
                                {"exception": str(e2), "traceback": traceback.format_exc()},
                            )
                        continue

                    self.log("自动超级抽奖恢复失败，停止任务。")
                    self.log_error_report_guidance(snapshot_info)
                    break

                self.stop_all()

        self.current_thread = threading.Thread(target=runner, daemon=True)
        self.current_thread.start()

    def start_cr_grind(self):
        if self.is_running:
            return

        if not self.confirm_cr_grind_requirements():
            self.log("用户取消启动：未确认刷CR车辆涂装/驾驶辅助设置提醒。")
            return

        self.is_running = True
        self.process_lost_event.clear()
        self.recovery_in_progress.clear()
        self.clear_failure_context()
        self.current_step_name = "cr"
        self.save_config()
        self.show_mini_running_ui()
        self.update_running_ui("刷CR点", 0, 0)
        self.update_mini_cr_status(self.is_cr_settlement_enabled(), 0, self.get_cr_settlement_laps())

        self.cr_session = {
            "start_cr": None,
            "last_cr": None,
            "total_delta": 0,
            "total_laps": 0,
            "records": [],
        }

        def runner():
            success = False
            try:
                if not self.check_and_focus_game():
                    return

                self.start_process_guard_thread()
                success = self.logic_cr_grind()
            except Exception as e:
                self.log(f"刷CR点异常: {e}")
                self.set_failure_context(
                    "cr_grind_exception",
                    {
                        "exception": str(e),
                        "traceback": traceback.format_exc(),
                    },
                )
            finally:
                while self.is_running and not success:
                    failure_context = self.last_failure_context or {
                        "reason": "cr_grind_failed",
                        "details": {"message": "刷CR点流程未成功完成"},
                    }
                    snapshot_info = self.capture_failure_snapshot(
                        failure_context.get("reason", "cr_grind_failed"),
                        module_name="cr",
                        details=failure_context.get("details"),
                    )
                    if self.attempt_recovery():
                        self.process_lost_event.clear()
                        self.start_process_guard_thread()
                        self.clear_failure_context()
                        self.log_recovery("刷CR点恢复完成，重新进入刷CR流程。")
                        success = self.logic_cr_grind()
                        continue

                    self.log("刷CR点恢复失败，停止任务。")
                    self.log_error_report_guidance(snapshot_info)
                    break

                self.stop_all()

        self.current_thread = threading.Thread(target=runner, daemon=True)
        self.current_thread.start()

    def stop_all(self):
        if not self.is_running:
            return

        self.is_running = False
        self.current_step_name = ""
        self.pipeline_next_step_override = None
        self.clear_failure_context()
        self.process_lost_event.clear()
        self.recovery_in_progress.clear()

        for key in DIK_CODES.keys():
            self.hw_key_up(key)

        for key in ["w", "e", "y", "enter", "esc", "up", "down", "left", "right", "space", "backspace"]:
            self.hw_key_up(key)

        try:
            pydirectinput.mouseUp()
        except Exception:
            pass

        def restore_ui():
            if hasattr(self, "mini_frame"):
                self.mini_frame.pack_forget()

            # 【核心修复】：先让大容器里的东西全部解绑，洗牌重来
            self.config_frame.pack_forget()
            self.global_settings_frame.pack_forget()
            if hasattr(self, "pipeline_tip_frame"):
                self.pipeline_tip_frame.pack_forget()
            if hasattr(self, "cr_ticket_warning_frame"):
                self.cr_ticket_warning_frame.pack_forget()
            self.calc_frame.pack_forget()
            if hasattr(self, "super_calc_frame"):
                self.super_calc_frame.pack_forget()
            if hasattr(self, "cr_frame"):
                self.cr_frame.pack_forget()

            # 1. 铺设最外层大容器
            self.top_container.pack(fill="x", padx=18, pady=(18, 10))

            # 2. 依次按顺序塞入三个模块，完美保证从上到下的顺序！
            self.config_frame.pack(fill="x")
            self.global_settings_frame.pack(fill="x", padx=18, pady=(15, 0))
            if hasattr(self, "pipeline_tip_frame"):
                self.pipeline_tip_frame.pack(fill="x", padx=18, pady=(10, 0))
            if hasattr(self, "cr_ticket_warning_frame"):
                self.cr_ticket_warning_frame.pack(fill="x", padx=18, pady=(8, 0))
            self.calc_frame.pack(fill="x", padx=18, pady=(10, 0))
            if hasattr(self, "super_calc_frame"):
                self.super_calc_frame.pack(fill="x", padx=18, pady=(10, 0))
            if hasattr(self, "cr_frame"):
                self.cr_frame.pack(fill="x", padx=18, pady=(10, 0))

            # 3. 铺设底部的日志和按钮
            if hasattr(self, "bottom_frame"):
                self.bottom_frame.pack(fill="both", expand=True, padx=18, pady=(6, 12))

            # 恢复窗口原本的状态
            self.btn_stop.configure(text="等待指令 (F8)", fg_color="#3A3A3A", hover_color="#4A4A4A")
            self.attributes("-topmost", False)
            if hasattr(self, "main_window_geometry_before_mini"):
                self.geometry(self.main_window_geometry_before_mini)

        self.ui_call(restore_ui)
        if not self.app_closing.is_set() and self.is_process_guard_enabled():
            self.start_process_guard_thread()
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
    def find_skill_race_start_position(self, race_index):
        pos = None
        for _ in range(60):
            if not self.is_running:
                return None

            if self.should_abort_for_process_loss({"phase": "find_race_start", "race_index": race_index}):
                return None

            pos = self.wait_for_any_image(
                ["start.png", "startw.png"],
                region=self.regions["左下"],
                threshold=0.75,
                timeout=0.7,
                interval=0.2,
                fast_mode=True
            )
            if pos:
                return pos

            if self.should_abort_for_process_loss({"phase": "find_race_start", "race_index": race_index}):
                return None

            self.hw_press("down")
            time.sleep(0.25)

        return None

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

        time.sleep(0.8)

        pos_el = self.wait_for_any_image(
            ["eventlab.png", "eventlabcar.png"],
            region=self.regions["全界面"],
            threshold=0.5,
            timeout=5,
            interval=0.25,
            fast_mode=True
        )
        if not pos_el:
            self.log("未找到 eventlab")
            return False

        self.game_click(pos_el)
        time.sleep(1.2)

        pos_yg = self.wait_for_image(
            "playenent.png",
            region=self.regions["中间"],
            threshold=0.75,
            timeout=40,
            interval=0.3,
            fast_mode=True
        )
        if not pos_yg:
            self.log("未找到游玩赛事")
            return False

        self.game_click(pos_yg)
        time.sleep(1.5)

        self.hw_press("backspace")
        time.sleep(0.8)
        self.hw_press("up")
        time.sleep(0.4)
        self.hw_press("enter")
        time.sleep(0.8)

        code_text = "".join(c for c in self.entry_share.get() if c.isdigit())
        for char in code_text:
            if not self.is_running:
                return False
            if char in DIK_CODES:
                self.hw_press(char, delay=0.05)
                time.sleep(0.05)

        time.sleep(0.4)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.3)
        self.hw_press("enter")
        time.sleep(1.5)

        pos_ck = self.wait_for_image(
            "VEI.png",
            region=self.regions["下"],
            threshold=0.75,
            timeout=100,
            interval=1.0,
            fast_mode=True
        )
        if not pos_ck:
            self.log("链接超时")
            return False

        self.hw_press("enter")
        time.sleep(1.5)
        self.hw_press("enter")
        time.sleep(2.0)

        race_car_templates = self.get_race_car_template_candidates()
        self.log(f"刷图车模板: {', '.join(race_car_templates)}")

        pos_target, _ = self.wait_for_race_car_template_multi(
            race_car_templates,
            region=self.regions["全界面"],
            timeout=10,
            interval=0.25,
        )

        if not pos_target:
            self.log("未找到带 liketag 的目标车辆，重新选品牌...")
            self.hw_press("backspace")
            time.sleep(1.2)

            found_brand = False
            for _ in range(3):
                if not self.is_running:
                    return False

                pos_brand = self.wait_for_image(
                    "skillcarbrand.png",
                    region=self.regions["全界面"],
                    threshold=0.75,
                    timeout=0.8,
                    interval=0.2,
                    fast_mode=True
                )
                if pos_brand:
                    self.game_click(pos_brand)
                    time.sleep(1.2)
                    found_brand = True
                    break

                self.hw_press("up")
                time.sleep(0.4)

            if not found_brand:
                self.log("三次尝试未找到刷图车辆品牌。")
                return False

            for _ in range(200):
                if not self.is_running:
                    return False

                pos_target, _ = self.find_race_car_template_in_list(
                    race_car_templates,
                    region=self.regions["全界面"],
                    threshold=0.8,
                    fast_mode=True,
                )
                if pos_target:
                    break

                for _ in range(4):
                    self.hw_press("right", delay=0.08)
                    time.sleep(0.08)
                time.sleep(0.4)

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

            if self.should_abort_for_process_loss({"phase": "logic_race_loop", "race_index": self.race_counter + 1}):
                return False

            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 找赛事起点...")

            race_start_search_at = time.time()
            pos = self.find_skill_race_start_position(self.race_counter + 1)

            if not pos:
                if self.should_abort_for_process_loss({"phase": "find_race_start", "race_index": self.race_counter + 1}):
                    return False
                handled_likes = self.handle_like_prompt_after_stall(
                    f"跑图 {self.race_counter + 1}/{target_count} 未进入下一圈",
                    race_start_search_at,
                )
                if handled_likes:
                    self.log(f"跑图 {self.race_counter + 1}/{target_count}: 点赞兜底后重新寻找赛事起点。")
                    pos = self.find_skill_race_start_position(self.race_counter + 1)

            if not pos:
                self.log("找不到赛事起点，退出跑图。")
                return False

            self.game_click(pos)
            time.sleep(4.0)
            self.hw_key_down("w")

            race_start_time = time.time()
            stall_watch_start = race_start_time
            last_chk = 0
            finished = False
            stall_recovery_count = 0
            stall_timeout = max(1, int(self.config.get("race_stall_timeout_seconds", 60)))
            restart_timeout = max(stall_timeout, int(self.config.get("race_restart_timeout_seconds", 150)))
            reverse_seconds = max(1, int(self.config.get("race_reverse_seconds", 3)))
            restart_drive_confirm_deadline = time.time() + 15.0
            restart_drive_confirm_retry_used = False
            restart_drive_last_confirm_check = 0.0
            restart_drive_confirm_last_wait_log = 0.0
            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 已按住 W，开始后台检测 anna 确认可驾驶状态。")

            while self.is_running:
                if self.should_abort_for_process_loss({"phase": "race_drive", "race_index": self.race_counter + 1}):
                    break

                now = time.time()
                elap = now - race_start_time

                if restart_drive_confirm_deadline and now - restart_drive_last_confirm_check >= 1.0:
                    restart_drive_last_confirm_check = now
                    if self.find_image("anna.png", region=self.regions["左下"], threshold=0.55, fast_mode=True):
                        self.log(f"跑图 {self.race_counter + 1}/{target_count}: 检测到 anna，确认已进入可驾驶阶段。")
                        restart_drive_confirm_deadline = 0.0
                        restart_drive_confirm_last_wait_log = 0.0
                    elif now >= restart_drive_confirm_deadline:
                        self.log(f"跑图 {self.race_counter + 1}/{target_count}: anna 后台确认窗口内未检测到，检查是否仍停留在开始赛事界面。")
                        pos_still_start = self.wait_for_any_image(
                            ["start.png", "startw.png"],
                            region=self.regions["左下"],
                            threshold=0.75,
                            timeout=0.8,
                            interval=0.2,
                            fast_mode=True,
                        )
                        if pos_still_start:
                            if restart_drive_confirm_retry_used:
                                self.log(f"跑图 {self.race_counter + 1}/{target_count}: 开始确认后仍卡在开始赛事界面。")
                                self.capture_failure_snapshot(
                                    "skill_race_restart_start_button_stuck",
                                    module_name="race",
                                    details={
                                        "race_index": self.race_counter + 1,
                                        "target_count": target_count,
                                        "confirm_window_seconds": 15,
                                    },
                                )
                                self.set_failure_context(
                                    "skill_race_restart_start_button_stuck",
                                    {
                                        "race_index": self.race_counter + 1,
                                        "target_count": target_count,
                                        "message": "补按 Enter 后仍停留在开始赛事界面",
                                    },
                                )
                                break

                            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 仍在开始赛事界面，补按 Enter 一次。")
                            self.hw_press("enter")
                            self.hw_key_down("w")
                            restart_drive_confirm_retry_used = True
                            restart_drive_confirm_deadline = time.time() + 15.0
                            restart_drive_last_confirm_check = 0.0
                            restart_drive_confirm_last_wait_log = 0.0
                            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 已继续按住 W，延长 anna 后台确认窗口 15 秒。")
                        elif self.find_image("ExitRaceConfirm.png", region=self.regions["全界面"], threshold=0.70, fast_mode=True):
                            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 未检测到 anna，命中退出赛事确认弹窗，按 Enter 退出并交给恢复流程。")
                            self.hw_press("enter")
                            time.sleep(3.0)
                            self.set_failure_context(
                                "race_exit_confirm_prompt_after_start",
                                {
                                    "race_index": self.race_counter + 1,
                                    "target_count": target_count,
                                    "message": "开始跑图后未检测到 anna，卡在退出赛事确认弹窗，已确认退出",
                                },
                            )
                            break
                        elif self.find_image("restart.png", region=self.regions["下"], threshold=0.75, fast_mode=True):
                            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 未检测到 anna，但已检测到完赛按钮，按完赛处理。")
                            finished = True
                            break
                        else:
                            self.log(
                                f"跑图 {self.race_counter + 1}/{target_count}: 未检测到 anna，且未命中开始按钮/退出赛事弹窗/完赛按钮，保存现场并进入恢复。"
                            )
                            self.capture_failure_snapshot(
                                "race_drive_state_not_confirmed",
                                module_name="race",
                                details={
                                    "race_index": self.race_counter + 1,
                                    "target_count": target_count,
                                    "message": "开始跑图后未检测到 anna，且无法确认当前赛事状态",
                                },
                            )
                            self.set_failure_context(
                                "race_drive_state_not_confirmed",
                                {
                                    "race_index": self.race_counter + 1,
                                    "target_count": target_count,
                                    "message": "开始跑图后未检测到 anna，且未命中已知兜底状态",
                                },
                            )
                            break
                    elif now - restart_drive_confirm_last_wait_log >= 5.0:
                        remaining = max(0, int(restart_drive_confirm_deadline - now))
                        self.log(f"跑图 {self.race_counter + 1}/{target_count}: anna 暂未检测到，继续后台确认（剩余约 {remaining} 秒）。")
                        restart_drive_confirm_last_wait_log = now

                if time.time() - last_chk >= 1.0:
                    if self.find_image("restart.png", region=self.regions["下"], threshold=0.75, fast_mode=True):
                        finished = True
                        break
                    last_chk = time.time()

                if elap >= restart_timeout:
                    if self.restart_current_skill_race(self.race_counter + 1, target_count):
                        race_start_time = time.time()
                        stall_watch_start = race_start_time
                        last_chk = race_start_time
                        stall_recovery_count = 0
                        self.hw_key_down("w")
                        restart_drive_confirm_deadline = time.time() + 15.0
                        restart_drive_confirm_retry_used = False
                        restart_drive_last_confirm_check = 0.0
                        restart_drive_confirm_last_wait_log = 0.0
                        self.log(f"跑图 {self.race_counter + 1}/{target_count}: 已按住 W，开始后台检测 anna 确认可驾驶状态。")
                        continue

                    self.set_failure_context(
                        "race_restart_failed",
                        {
                            "race_index": self.race_counter + 1,
                            "target_count": target_count,
                            "stall_timeout_seconds": stall_timeout,
                            "restart_timeout_seconds": restart_timeout,
                            "reverse_seconds": reverse_seconds,
                            "stall_recovery_count": stall_recovery_count,
                        },
                    )
                    break

                if now - stall_watch_start >= stall_timeout:
                    if stall_recovery_count < 2:
                        stall_recovery_count += 1
                        self.log(
                            f"跑图 {self.race_counter + 1}/{target_count}: {stall_timeout} 秒未检测到下一圈，执行倒车兜底 {stall_recovery_count}/2（倒车 {reverse_seconds} 秒）。"
                        )

                        if not self.perform_race_stall_recovery(reverse_seconds):
                            self.set_failure_context(
                                "race_stall_recovery_interrupted",
                                {
                                    "race_index": self.race_counter + 1,
                                    "target_count": target_count,
                                    "stall_timeout_seconds": stall_timeout,
                                    "reverse_seconds": reverse_seconds,
                                    "stall_recovery_count": stall_recovery_count,
                                },
                            )
                            break
                    else:
                        self.log(
                            f"跑图 {self.race_counter + 1}/{target_count}: 倒车兜底已达上限，等待整轮 {restart_timeout} 秒超时后重开赛事。"
                        )

                    stall_watch_start = time.time()
                    last_chk = stall_watch_start
                    continue

                time.sleep(0.1)

            self.hw_key_up("w")

            if not finished or not self.is_running:
                return False

            if self.race_counter == target_count - 1:
                self.hw_press("enter")
                time.sleep(2.0)
            else:
                self.hw_press("x")
                time.sleep(0.8)
                self.hw_press("enter")
                time.sleep(2.0)

            self.race_counter += 1
            self.update_running_ui("循环跑图", self.race_counter, target_count)

        return True

    # ==========================================
    # --- 模块：买车 ---
    # ==========================================
    def logic_buy_car(self, target_count):
        if self.car_counter >= target_count:
            return True

        if not self.ensure_cr_for_buy_cycle(target_count):
            return False

        self.update_running_ui("批量买车", self.car_counter, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        pos = self.wait_for_image(
            "collectionjournal.png",
            region=self.regions["左"],
            threshold=0.7,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos:
            self.log("未找到收集簿")
            return False

        self.game_click(pos, double=True)
        time.sleep(0.6)

        pos = self.wait_for_image(
            "masterexplorer.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos:
            self.log("未找到探索")
            return False

        self.game_click(pos, double=True)
        time.sleep(0.6)

        pos = self.wait_for_image(
            "carcollection.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=30,
            interval=0.3,
            fast_mode=True
        )
        if not pos:
            self.log("未找到车辆收集")
            return False

        self.game_click(pos, double=True)
        time.sleep(1.0)

        self.hw_press("backspace")
        time.sleep(0.5)

        self.log("买车：定位斯巴鲁品牌...")
        brand_pos = None
        for _ in range(20):
            if not self.is_running:
                return False

            brand_pos = self.wait_for_any_image(
                ["CCbrand.png"],
                region=self.regions["全界面"],
                threshold=0.75,
                timeout=0.8,
                interval=0.2,
                fast_mode=True
            )
            if brand_pos:
                break

            self.hw_press("up")
            time.sleep(0.25)

        if not brand_pos:
            self.log("未找到斯巴鲁品牌")
            return False

        self.game_click(brand_pos)
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.4)

        pos_22b = self.wait_for_image(
            "consumablecar.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=8,
            interval=0.3,
            fast_mode=True
        )
        if not pos_22b:
            self.log("未找到消耗品车辆")
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
            time.sleep(0.7)

            self.car_counter += 1
            self.update_running_ui("批量买车", self.car_counter, target_count)

        for _ in range(5):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(0.8)

        return True

    def dismiss_cj_dsi_prompt(self):
        pos = self.wait_for_image(
            "DSI.png",
            region=self.regions["全界面"],
            threshold=0.68,
            timeout=3.5,
            interval=0.4,
            fast_mode=False
        )
        if pos:
            self.log("识别到 不再显示该消息，点击文字按钮后确认...")
            self.game_click(pos)
            time.sleep(0.2)
            self.hw_press("enter")
            time.sleep(0.6)
            return True
        return False

    def recover_cj_vehicle_menu(self):
        vehicle_menu_anchors = [
            "designandpaint_w.png",
            "designandpaint-b.png",
            "buyandsell-w.png",
            "buyandsell-b.png",
        ]

        for _ in range(8):
            if not self.is_running:
                return False

            pos = self.wait_for_any_image(
                vehicle_menu_anchors,
                region=self.regions["全界面"],
                threshold=0.75,
                timeout=0.6,
                interval=0.2,
                fast_mode=True
            )
            if pos:
                return True

            self.hw_press("esc")
            time.sleep(0.6)

        self.log("未能退回车辆菜单")
        return False

    def find_subaru_brand_simple(self, max_attempts=30, timeout=0.8):
        for _ in range(max_attempts):
            if not self.is_running:
                return None

            brand_pos = self.wait_for_any_image(
                ["CCbrand.png"],
                region=self.regions["全界面"],
                threshold=0.75,
                timeout=timeout,
                interval=0.2,
                fast_mode=True
            )
            if brand_pos:
                return brand_pos

            self.hw_press("up")
            time.sleep(0.25)

        return None

    def find_and_click_cj_target_car(self, current_right_offset, timeout=3, interval=0.25):
        pos_target = self.wait_for_any_image(
            ["FreshTagText.png", "newcartag.png"],
            region=self.regions["全界面"],
            threshold=0.70,
            timeout=timeout,
            interval=interval,
            fast_mode=True,
        )
        if not pos_target:
            return False

        self.game_click(pos_target)
        if self.config.get("cj_car_right_offset", 0) != current_right_offset:
            self.config["cj_car_right_offset"] = current_right_offset
            self.save_runtime_config()
            self.log(f"修正目标车辆偏移: right x {current_right_offset}")
        return True

    def scan_cj_target_car_backward(self, current_right_offset):
        current_right_offset = max(0, min(400, current_right_offset))
        if current_right_offset <= 0:
            return False

        self.log(f"当前偏移未找到目标车辆，开始向前回扫: left x {current_right_offset}")
        while self.is_running and current_right_offset >= 0:
            if self.find_and_click_cj_target_car(current_right_offset, timeout=0.45, interval=0.15):
                return True

            if current_right_offset == 0:
                break

            self.hw_press("left", delay=0.04)
            current_right_offset -= 1
            time.sleep(0.06)

        return False

    def reset_cj_filtered_car_list_to_front(self, key="pageup", wait_seconds=0.8):
        self.hw_press(key, delay=0.15)
        time.sleep(wait_seconds)

    def scan_cj_target_car_forward_once(self, round_index, max_steps=85):
        current_right_offset = 0
        self.log(f"超级抽奖：第 {round_index}/3 轮从列表前端寻找带全新标签的 22B。")
        for _ in range(max_steps):
            if not self.is_running:
                return False

            if self.find_and_click_cj_target_car(current_right_offset, timeout=0.45, interval=0.15):
                return True

            for _ in range(4):
                if not self.is_running:
                    return False
                self.hw_press("right", delay=0.05)
                time.sleep(0.08)
            current_right_offset += 4
            time.sleep(0.12)

        return False

    def select_cj_target_car(self):
        self.log("超级抽奖：先应用重复项+B级+全轮驱动+传奇筛选，再直接定位目标车。")
        if not self.apply_duplicate_b_filter_for_garage(
            module_name="cj",
            log_prefix="超级抽奖",
            include_awd_legendary=True
        ):
            return False

        self.log("超级抽奖：筛选完成，PageUp 回到列表前端后开始寻找带全新标签的 22B。")
        self.reset_cj_filtered_car_list_to_front(key="pageup", wait_seconds=0.9)

        for round_index in range(1, 4):
            if self.scan_cj_target_car_forward_once(round_index):
                return True
            if not self.is_running:
                return False
            if round_index < 3:
                self.log("超级抽奖：本轮未找到目标车，PageDown 回到初始页面后重试。")
                self.reset_cj_filtered_car_list_to_front(key="pagedown", wait_seconds=0.9)

        self.log("超级抽奖：3 轮未找到带全新标签的目标车辆，回到买车模块补车。")
        self.car_counter = 0
        self.pipeline_next_step_override = "buy"
        return False

    def is_cj_vehicle_page_visible(self):
        return bool(self.wait_for_any_image(
            ["UandT-w.png", "UandT-b.png"],
            region=self.regions["全界面"],
            threshold=0.65,
            timeout=0.45,
            interval=0.15,
            fast_mode=True,
        ))

    def enter_cj_design_and_paint_by_keyboard_fallback(self):
        self.log("车辆页已可见但未命中设计与喷漆模板，尝试键盘兜底：从我的车辆向下两次进入设计与喷漆。")
        for _ in range(2):
            if not self.is_running:
                return False
            self.hw_press("down", delay=0.12)
            time.sleep(0.25)
        self.hw_press("enter", delay=0.12)
        time.sleep(0.8)
        return True

    def select_cj_car_via_design_and_paint(self):
        self.log("进入设计与喷漆...")

        pos_design = None
        entered_design = False
        for i in range(12):
            if not self.is_running:
                return False

            pos_design = self.wait_for_any_image(
                ["designandpaint_w.png", "designandpaint-b.png"],
                region=self.regions["全界面"],
                threshold=0.75,
                timeout=0.8,
                interval=0.2,
                fast_mode=True
            )
            if pos_design:
                break

            if self.is_cj_vehicle_page_visible():
                if self.enter_cj_design_and_paint_by_keyboard_fallback():
                    entered_design = True
                    break
                return False

            self.hw_press("right" if i < 6 else "left", delay=0.15)
            time.sleep(0.3)

        if not pos_design and not entered_design:
            self.log("未找到设计与喷漆")
            return False

        if pos_design:
            self.game_click(pos_design)
            time.sleep(0.6)

        self.dismiss_cj_dsi_prompt()

        pos_choose_entry = self.wait_for_any_image(
            ["choosecar.png", "choosecar-b.png"],
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=10,
            interval=0.3,
            fast_mode=True
        )
        if not pos_choose_entry:
            self.log("未识别到 选择车辆，尝试处理可能残留的首次提示")
            if self.dismiss_cj_dsi_prompt():
                pos_choose_entry = self.wait_for_any_image(
                    ["choosecar.png", "choosecar-b.png"],
                    region=self.regions["全界面"],
                    threshold=0.75,
                    timeout=6,
                    interval=0.3,
                    fast_mode=True
                )
            if not pos_choose_entry:
                self.log("未识别到 选择车辆")
                return False

        self.game_click(pos_choose_entry)
        time.sleep(0.6)

        if not self.select_cj_target_car():
            return False

        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(1.0)

        pos_choose_exit = self.wait_for_any_image(
            ["choosecar.png", "choosecar-b.png"],
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=15,
            interval=0.5,
            fast_mode=True
        )
        if not pos_choose_exit:
            self.log("选车后未返回设计与喷漆")
            return False

        self.hw_press("esc")
        time.sleep(0.8)
        return True

    def select_cj_car_via_normal_flow(self):
        self.log("进入我的车辆.")
        self.hw_press("enter")
        time.sleep(2.0)

        self.dismiss_cj_dsi_prompt()

        if not self.select_cj_target_car():
            return False

        time.sleep(1.2)
        self.hw_press("enter")
        time.sleep(1.0)
        self.hw_press("enter")
        time.sleep(1.0)
        return True

    def click_and_verify_entry(self, label, pos, verify_templates, verify_region=None, retries=3):
        for attempt in range(1, retries + 1):
            if not self.is_running:
                return False

            self.log(f"{label}: 尝试进入 ({attempt}/{retries})")
            if attempt == 1 and pos:
                self.game_click(pos)
            else:
                self.hw_press("enter")
            time.sleep(0.6)

            verified = self.wait_for_any_image(
                verify_templates,
                region=verify_region or self.regions["全界面"],
                threshold=0.75,
                timeout=4,
                interval=0.3,
                fast_mode=True,
            )
            if verified:
                return True

        self.capture_failure_snapshot(
            f"{self.sanitize_diagnostic_token(label)}_entry_failed",
            module_name="cj",
        )
        return False

    def click_and_wait_leave_entry(self, label, pos, current_templates, current_region=None, retries=3):
        for attempt in range(1, retries + 1):
            if not self.is_running:
                return False

            self.log(f"{label}: 尝试进入 ({attempt}/{retries})")
            if attempt == 1 and pos:
                self.game_click(pos)
            else:
                self.hw_press("enter")
            time.sleep(1.2)

            still_here = self.wait_for_any_image(
                current_templates,
                region=current_region or self.regions["全界面"],
                threshold=0.75,
                timeout=1.0,
                interval=0.25,
                fast_mode=True,
            )
            if not still_here:
                return True

        self.capture_failure_snapshot(
            f"{self.sanitize_diagnostic_token(label)}_entry_failed",
            module_name="cj",
        )
        return False

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
        time.sleep(1.0)

        pos_buycar = self.wait_for_image(
            "BNandUC.png",
            region=self.regions["左"],
            threshold=0.75,
            timeout=12,
            interval=0.3,
            fast_mode=True
        )
        if not pos_buycar:
            self.log("未识别到 购买新车与二手车")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = self.wait_for_any_image(
            ["buyandsell-w.png", "buyandsell-b.png"],
            region=self.regions["左"],
            threshold=0.75,
            timeout=60,
            interval=0.5,
            fast_mode=True
        )
        if not pos_bs:
            self.log("未找到购买与出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)
        self.hw_press("pagedown", delay=0.15)
        self.log("确认进入车辆菜单，准备选车...")
        time.sleep(0.5)

        design_selection_failures = 0
        force_normal_selection = False

        while self.cj_counter < target_count:
            if not self.is_running:
                return False
            used_normal_selection = force_normal_selection

            if force_normal_selection:
                self.log("本轮已切换为正常选车流程。")
                if not self.select_cj_car_via_normal_flow():
                    if self.pipeline_next_step_override == "buy":
                        return True
                    return False
            else:
                if not self.select_cj_car_via_design_and_paint():
                    if self.pipeline_next_step_override == "buy":
                        return True
                    design_selection_failures += 1
                    self.log(f"设计与涂装选车失败 ({design_selection_failures}/2)，尝试回退正常选车流程。")
                    if design_selection_failures >= 2:
                        force_normal_selection = True
                        self.log("设计与涂装选车已失败两次，本轮后续默认使用正常选车流程。")

                    if not self.recover_cj_vehicle_menu():
                        return False

                    used_normal_selection = True
                    if not self.select_cj_car_via_normal_flow():
                        if self.pipeline_next_step_override == "buy":
                            return True
                        return False


            pos_sjy = None
            for i in range(30):
                if not self.is_running:
                    return False

                pos_sjy = self.wait_for_any_image(
                    ["UandT-w.png", "UandT-b.png"],
                    region=self.regions["全界面"],
                    threshold=0.75,
                    timeout=0.8,
                    interval=0.2,
                    fast_mode=True
                )
                if pos_sjy:
                    break

                self.hw_press("right" if i < 15 else "left", delay=0.15)
                time.sleep(0.3)

            if not pos_sjy:
                self.log("找不到升级与调教")
                return False

            if not self.click_and_verify_entry(
                "升级与调教",
                pos_sjy,
                ["clsldcnw.png", "clsldcnb.png"],
                verify_region=self.regions["左下"],
                retries=3,
            ):
                self.log("升级与调教入口多次点击后仍未进入")
                return False

            pos_cls = self.wait_for_any_image(
                ["clsldcnw.png", "clsldcnb.png"],
                region=self.regions["左下"],
                threshold=0.75,
                timeout=20,
                interval=0.4,
                fast_mode=True
            )
            if not pos_cls:
                self.log("找不到熟练度入口")
                return False

            if not self.click_and_wait_leave_entry(
                "熟练度入口",
                pos_cls,
                ["clsldcnw.png", "clsldcnb.png"],
                current_region=self.regions["左下"],
                retries=3,
            ):
                self.log("熟练度入口多次点击后仍未进入")
                return False

            pos_exp = self.wait_for_any_image(
                ["EXPwU.png"],
                region=self.regions["左"],
                threshold=0.75,
                timeout=2,
                interval=0.3,
                fast_mode=True
            )

            if pos_exp:
                self.log("该车辆技能已点过，跳过计数")
            else:
                time.sleep(1.0)
                self.hw_press("enter")
                time.sleep(1.5)

                for dk in self.config["skill_dirs"]:
                    if not self.is_running:
                        return False
                    self.hw_press(dk)
                    time.sleep(0.2)
                    self.hw_press("enter")
                    time.sleep(1.2)
                if self.find_image("SPNE.png", region=self.regions["全界面"], threshold=0.7, fast_mode=True):
                    self.log("已无技能点或技能已点完，提前结束抽奖！")
                    time.sleep(1.0)
                    self.hw_press("enter")
                    time.sleep(0.8)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("esc")
                    time.sleep(1.0)
                    return True
                self.cj_counter += 1
                if self.cj_counter % 3 == 0:
                    self.log(
                        "已升级 3 辆同列车辆；不再按列推测增加车辆偏移，"
                        "下次将通过模板重新确认目标 22B 并保存真实偏移。"
                    )
                self.update_running_ui("超级抽奖", self.cj_counter, target_count)

            self.hw_press("esc")
            time.sleep(1.2)
            self.hw_press("esc")
            time.sleep(0.8)
            if used_normal_selection:
                self.hw_press("up", delay=0.15)
                time.sleep(0.8)
        self.hw_press("esc")
        time.sleep(1.2)
        self.hw_press("esc")
        time.sleep(1.2)
        return True
    # ==========================================
    # --- 模块：移除车辆 ---
    # ==========================================
    def get_filter_panel_search_region(self, panel_pos):
        try:
            gx, gy, gw, gh = self.regions["全界面"]
            px, py = panel_pos
            rs = self.get_resolution_scale()
            min_wh = int(720 * rs)
            region_w = min(gw, max(min_wh, int(gw * 0.34)))
            region_h = min(gh, max(min_wh, int(gh * 0.70)))
            x1 = max(gx, min(gx + gw - region_w, int(px - region_w // 2)))
            y1 = max(gy, min(gy + gh - region_h, int(py - int(115 * rs))))
            return (x1, y1, region_w, region_h)
        except Exception:
            return self.regions["全界面"]

    def get_filter_scales_to_try(self, strict_verify=False):
        scales = self.get_scales_to_try(fast_mode=True)
        if strict_verify:
            return scales
        return scales[:4]

    def find_filter_option_row(self, row_templates, threshold=0.66, timeout=3.0, region=None, scales_to_try=None):
        start = time.time()
        region = region or self.filter_panel_region or self.regions["全界面"]
        scales_to_try = scales_to_try or self.get_scales_to_try(fast_mode=True)
        while self.is_running and time.time() - start < timeout:
            try:
                screen_bgr = self.capture_region(region)
                best = None
                for template_name in row_templates:
                    for scale in scales_to_try:
                        tpl, _ = self.get_scaled_template(template_name, scale)
                        if tpl is None:
                            continue
                        th, tw = tpl.shape[:2]
                        if th < 5 or tw < 5 or th > screen_bgr.shape[0] or tw > screen_bgr.shape[1]:
                            continue
                        res = cv2.matchTemplate(screen_bgr, tpl, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(res)
                        if max_val >= threshold and (best is None or max_val > best["score"]):
                            left = max_loc[0] + region[0]
                            top = max_loc[1] + region[1]
                            row_width = tw
                            row_height = th
                            if tw < 400:
                                expected_width = int(880 * scale)
                                left = int(left - 28 * scale)
                                row_width = max(tw, expected_width)
                                row_height = max(th, int(54 * scale))
                                # 安全钳制：防止在极端缩放下行宽超出屏幕范围
                                max_screen_w = self.regions["全界面"][2] if self.regions.get("全界面") else 3840
                                row_width = min(row_width, max_screen_w)
                            checkbox_size = max(18, min(42, int(row_height * 0.52)))
                            checkbox_x = left + row_width - max(24, int(row_height * 0.72))
                            checkbox_y = top + row_height // 2
                            best = {
                                "template": template_name,
                                "score": float(max_val),
                                "pos": (left + row_width // 2, top + row_height // 2),
                                "row_left_top": (left, top),
                                "size": (row_width, row_height),
                                "match_size": (tw, th),
                                "checkbox_pos": (checkbox_x, checkbox_y),
                                "checkbox_size": checkbox_size,
                            }
                if best:
                    return best
            except Exception as e:
                self.log(f"筛选项定位异常: {e}")
            time.sleep(0.2)
        return None

    def get_filter_row_template_checked_state(self, row_info):
        template_name = os.path.basename(str(row_info.get("template", ""))).lower()
        if "unchecked" in template_name:
            return False
        if "checked" in template_name:
            return True
        return None

    def is_filter_row_checked_by_checkbox(self, row_info):
        try:
            cx, cy = row_info.get("checkbox_pos", row_info["pos"])
            checkbox_size = int(row_info.get("checkbox_size", 28))
            gx, gy, gw, gh = self.regions["全界面"]
            crop_w = max(22, min(54, checkbox_size + 10))
            crop_h = max(22, min(54, checkbox_size + 10))
            x1 = int(cx - crop_w / 2)
            y1 = int(cy - crop_h / 2)
            x1 = max(gx, min(gx + gw - crop_w, x1))
            y1 = max(gy, min(gy + gh - crop_h, y1))
            roi = self.capture_region((x1, y1, crop_w, crop_h))
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            margin_x = max(6, int(crop_w * 0.28))
            margin_y = max(6, int(crop_h * 0.28))
            inner = gray[margin_y:crop_h - margin_y, margin_x:crop_w - margin_x]
            if inner.size == 0:
                return False
            bg = float(np.median(inner))
            if bg >= 128:
                mark_ratio = float((inner < 70).sum()) / float(inner.size)
            else:
                mark_ratio = float((inner > 185).sum()) / float(inner.size)
            return mark_ratio >= 0.12
        except Exception as e:
            self.log(f"筛选项勾选检测异常: {e}")
            return False

    def is_filter_row_checked(self, row_info):
        template_state = self.get_filter_row_template_checked_state(row_info)
        if template_state is not None:
            return template_state
        return self.is_filter_row_checked_by_checkbox(row_info)

    def is_filter_strict_click_verify_enabled(self):
        var_widget = getattr(self, "var_filter_strict_click_verify", None)
        if var_widget is not None:
            try:
                return bool(var_widget.get())
            except Exception:
                pass
        return bool(self.config.get("filter_strict_click_verify", False))

    def ensure_filter_option_checked_by_templates(self, label, row_templates, log_prefix="筛选"):
        strict_verify = self.is_filter_strict_click_verify_enabled()
        find_timeout = 3.0 if strict_verify else 0.9
        find_attempts = 3 if strict_verify else 2
        scales_to_try = self.filter_fast_scales or self.get_filter_scales_to_try(strict_verify=strict_verify)
        search_region = self.filter_panel_region or self.regions["全界面"]
        for attempt in range(1, find_attempts + 1):
            if not self.is_running:
                return False

            row_info = self.find_filter_option_row(
                row_templates,
                threshold=0.66,
                timeout=find_timeout,
                region=search_region,
                scales_to_try=scales_to_try,
            )
            if not row_info:
                self.log(f"{log_prefix}筛选：未找到 {label} 选项 ({attempt}/{find_attempts})。")
                continue

            if self.is_filter_row_checked(row_info):
                self.log(f"{log_prefix}筛选：{label} 已勾选。")
                self.move_mouse_to_desktop_top_left()
                return True

            self.log(f"{log_prefix}筛选：勾选 {label} ({attempt}/{find_attempts})。")
            self.game_click(row_info.get("checkbox_pos", row_info["pos"]))
            self.move_mouse_to_desktop_top_left()
            if not strict_verify:
                time.sleep(0.15)
                self.log(f"{log_prefix}筛选：{label} 已点击。")
                return True

            time.sleep(0.7)

            row_info = self.find_filter_option_row(
                row_templates,
                threshold=0.66,
                timeout=1.5,
                region=search_region,
                scales_to_try=scales_to_try,
            )
            if row_info and self.is_filter_row_checked(row_info):
                self.log(f"{log_prefix}筛选：{label} 勾选成功。")
                self.move_mouse_to_desktop_top_left()
                return True

            self.log(f"{log_prefix}筛选：鼠标点击后未确认 {label}，尝试 Enter 兜底。")
            self.hw_press("enter")
            time.sleep(0.8)

            row_info = self.find_filter_option_row(
                row_templates,
                threshold=0.66,
                timeout=1.5,
                region=search_region,
                scales_to_try=scales_to_try,
            )
            if row_info and self.is_filter_row_checked(row_info):
                self.log(f"{log_prefix}筛选：{label} Enter 兜底勾选成功。")
                self.move_mouse_to_desktop_top_left()
                return True

        self.log(f"{log_prefix}筛选：{label} 勾选后未能确认。")
        return False

    def scroll_filter_panel_to_bottom(self, hold_seconds=10.0):
        if not self.is_running:
            return False
        self.log(f"筛选：长按 S {hold_seconds:g} 秒滚动到底部。")
        try:
            self.hw_key_down("s")
            end_at = time.time() + float(hold_seconds)
            while self.is_running and time.time() < end_at:
                time.sleep(0.05)
        finally:
            self.hw_key_up("s")
        time.sleep(0.5)
        return self.is_running

    def apply_duplicate_b_filter_by_keyboard(self, log_prefix="筛选"):
        self.log(f"{log_prefix}：按固定键序列勾选重复项+B级。")
        self.hw_press("home", delay=0.08)
        time.sleep(0.15)
        for _ in range(2):
            if not self.is_running:
                return False
            self.hw_press("down", delay=0.06)
            time.sleep(0.08)
        self.hw_press("enter")
        time.sleep(0.2)
        self.log(f"{log_prefix}：已按固定路径勾选重复项。")

        for _ in range(3):
            if not self.is_running:
                return False
            self.hw_press("down", delay=0.06)
            time.sleep(0.08)
        self.hw_press("enter")
        time.sleep(0.2)
        self.log(f"{log_prefix}：已按固定路径勾选B级。")
        self.move_mouse_to_desktop_top_left()
        return True

    def apply_duplicate_b_filter_for_garage(self, module_name="sell", log_prefix="删车", include_awd_legendary=False):
        self.log(f"{log_prefix}：按 Y 打开筛选面板。")
        self.hw_press("y")
        panel_pos = self.wait_for_image(
            "FilterPanel.png",
            region=self.regions["全界面"],
            threshold=0.70,
            timeout=8,
            interval=0.3,
            fast_mode=True,
        )
        if not panel_pos:
            self.log(f"{log_prefix}：未识别到筛选面板。")
            self.capture_failure_snapshot(f"{module_name}_filter_panel_not_found", module_name=module_name)
            return False

        self.filter_panel_region = self.get_filter_panel_search_region(panel_pos)
        self.filter_fast_scales = self.get_filter_scales_to_try(
            strict_verify=self.is_filter_strict_click_verify_enabled()
        )
        self.log(f"{log_prefix}：筛选面板已打开，重置筛选后按模板勾选条件。")
        self.hw_press("x")
        time.sleep(0.5)

        if not self.apply_duplicate_b_filter_by_keyboard(log_prefix):
            self.capture_failure_snapshot(f"{module_name}_duplicate_filter_failed", module_name=module_name)
            return False

        if include_awd_legendary:
            self.log(f"{log_prefix}：向下滚动筛选面板，准备勾选全轮驱动和传奇。")
            if not self.scroll_filter_panel_to_bottom(hold_seconds=10.0):
                return False

            if not self.ensure_filter_option_checked_by_templates(
                "全轮驱动",
                [
                    "AllWheelDriveWhiteFullUnchecked.png",
                    "AllWheelDriveWhiteFullChecked.png",
                    "AllWheelDriveBlackFullUnchecked.png",
                    "AllWheelDriveBlackFullChecked.png",
                    "AllWheelDriveWhite.png",
                    "AllWheelDriveBlack.png",
                ],
                log_prefix,
            ):
                self.capture_failure_snapshot(f"{module_name}_awd_filter_failed", module_name=module_name)
                return False

            if not self.ensure_filter_option_checked_by_templates(
                "传奇",
                [
                    "LegendaryWhiteFullUnchecked.png",
                    "LegendaryWhiteFullChecked.png",
                    "LegendaryBlackFullUnchecked.png",
                    "LegendaryBlackFullChecked.png",
                    "LegendaryWhite.png",
                    "LegendaryBlack.png",
                ],
                log_prefix,
            ):
                self.capture_failure_snapshot(f"{module_name}_legendary_filter_failed", module_name=module_name)
                return False

        self.hw_press("esc")
        time.sleep(3.0)
        if include_awd_legendary:
            self.log(f"{log_prefix}：重复项+B级+全轮驱动+传奇筛选已退出，等待筛选生效完成。")
        else:
            self.log(f"{log_prefix}：重复项+B级筛选已退出，等待筛选生效完成。")
        return True

    def apply_duplicate_b_filter_for_sell(self):
        return self.apply_duplicate_b_filter_for_garage(module_name="sell", log_prefix="删车", include_awd_legendary=True)

    def enter_subaru_after_garage_filter(self, module_name="sell", log_prefix="删车"):
        self.log(f"{log_prefix}：进入制造商页并定位斯巴鲁。")
        self.hw_press("backspace")
        time.sleep(0.8)

        brand_pos = self.find_subaru_brand_simple(max_attempts=30, timeout=0.8)
        if not brand_pos:
            self.log(f"{log_prefix}：筛选后未找到斯巴鲁制造商。")
            self.capture_failure_snapshot(f"{module_name}_subaru_brand_not_found", module_name=module_name)
            return False

        self.game_click(brand_pos)
        time.sleep(1.0)
        return True

    def is_sell_car_grid_visible(self, timeout=0.8):
        return self.wait_for_image(
            "Filter.png",
            region=self.regions["全界面"],
            threshold=0.64,
            timeout=timeout,
            interval=0.2,
            fast_mode=True,
        ) is not None

    def is_sell_vehicle_menu_visible(self, timeout=0.8):
        return self.wait_for_any_image(
            ["buyandsell-b.png", "buyandsell-w.png", "designandpaint_w.png", "designandpaint-b.png"],
            region=self.regions["上"],
            threshold=0.70,
            timeout=timeout,
            interval=0.2,
            fast_mode=True,
        ) is not None

    def ensure_sell_car_grid_ready(self, reason="continue"):
        if self.is_sell_car_grid_visible(timeout=0.8):
            return True

        if self.is_sell_vehicle_menu_visible(timeout=0.8):
            self.log(f"删车：当前在车辆菜单页，重新进入我的车辆列表 ({reason})。")
            self.hw_press("enter")
            time.sleep(2.0)
            if self.is_sell_car_grid_visible(timeout=5.0):
                self.log("删车：车库列表已就绪。")
                return True

        self.log(f"删车：未确认车库列表就绪 ({reason})。")
        self.capture_failure_snapshot(f"sell_car_grid_not_ready_{self.sanitize_diagnostic_token(reason)}", module_name="sell")
        return False

    def wait_for_sell_ready_after_delete(self):
        self.log("删车：删除指令已提交，跳过成功检测，等待界面恢复。")
        time.sleep(2.0)
        return True

    def reset_sell_tail_position(self, reason=""):
        self.sell_tail_position_ready = False
        self.sell_fresh_skip_count = 0
        self.sell_stop_no_deletable = False
        if reason:
            self.log(f"删车：重置末页定位状态 ({reason})。")

    def select_sell_last_subaru_card(self):
        if not self.ensure_sell_car_grid_ready(reason="select_last_subaru"):
            return False

        if self.sell_tail_position_ready:
            self.log("删车：沿用上次删除后的末页位置，不重复 PageDown。")
            return True

        self.log("删车：筛选结果列表 PageDown 到尾部，准备删除当前选中车辆。")
        for _ in range(20):
            if not self.is_running:
                return False
            self.hw_press("pagedown", delay=0.12)
            time.sleep(0.18)
        time.sleep(0.8)
        ready = self.ensure_sell_car_grid_ready(reason="after_pagedown_tail")
        if ready:
            self.sell_tail_position_ready = True
        return ready

    def selected_sell_car_has_fresh_tag(self):
        pos = self.wait_for_image(
            "FreshTagText.png",
            region=self.regions["全界面"],
            threshold=0.70,
            timeout=0.7,
            interval=0.15,
            fast_mode=True,
        )
        if pos:
            self.log("删车保护：当前候选车辆检测到全新标签，跳过该车。")
            return True
        return False

    def prepare_deletable_sell_car(self, max_fresh_skips=24):
        for _ in range(max_fresh_skips + 1):
            if not self.is_running:
                return False
            if not self.ensure_sell_car_grid_ready(reason="fresh_tag_guard"):
                return False
            if not self.selected_sell_car_has_fresh_tag():
                return True

            self.sell_fresh_skip_count += 1
            if self.sell_fresh_skip_count > max_fresh_skips:
                self.sell_stop_no_deletable = True
                self.log("删车保护：连续候选车辆均带全新标签，停止删车以避免误删。")
                self.capture_failure_snapshot("sell_only_fresh_tag_candidates", module_name="sell")
                return False

            self.hw_press("left", delay=0.08)
            time.sleep(0.45)

    def click_sell_remove_option_from_action_menu(self):
        option_templates = ["RemoveFromGarageWhite.png", "RemoveFromGarageBlack.png"]
        for attempt in range(1, 4):
            if not self.is_running:
                return False

            pos_remove = self.wait_for_any_image(
                option_templates,
                region=self.regions["全界面"],
                threshold=0.70,
                timeout=2.5,
                interval=0.25,
                fast_mode=True,
            )
            if not pos_remove:
                self.log(f"删车：未找到从车库移除车辆选项 ({attempt}/3)。")
                continue

            self.log(f"删车：模板点击从车库移除车辆 ({attempt}/3)。")
            self.game_click(pos_remove)
            time.sleep(0.35)
            return True

        self.log("删车：操作菜单仍停留，移除选项可能未触发。")
        return False

    def confirm_sell_remove_dialog(self):
        self.log("删车：确认移除页，直接选择“嗯”。")
        time.sleep(0.15)
        self.hw_press("down", delay=0.06)
        time.sleep(0.12)
        self.hw_press("enter", delay=0.06)
        time.sleep(0.45)
        return True

    def remove_selected_sell_car(self):
        self.log("删车：打开车辆操作菜单。")
        self.hw_press("enter")
        pos_menu = self.wait_for_image(
            "rc.png",
            region=self.regions["全界面"],
            threshold=0.65,
            timeout=5,
            interval=0.25,
            fast_mode=True,
        )
        if not pos_menu:
            self.log("删车：未确认车辆操作菜单已打开，停止本次删除以避免误操作。")
            self.capture_failure_snapshot("sell_action_menu_not_found", module_name="sell")
            return False

        time.sleep(0.5)
        option_opened = False
        for attempt in range(1, 4):
            if not self.is_running:
                return False
            if self.click_sell_remove_option_from_action_menu():
                option_opened = True
                break
            self.log(f"删车：重新定位操作菜单并重试移除选项 ({attempt}/3)。")
            pos_menu = self.wait_for_image(
                "rc.png",
                region=self.regions["全界面"],
                threshold=0.65,
                timeout=2,
                interval=0.25,
                fast_mode=True,
            )
            if not pos_menu:
                break

        if not option_opened:
            self.capture_failure_snapshot("sell_remove_option_not_opened", module_name="sell")
            return False

        return self.confirm_sell_remove_dialog()

    def delete_one_sell_car(self):
        if not self.select_sell_last_subaru_card():
            return False

        if not self.prepare_deletable_sell_car():
            return False

        if not self.remove_selected_sell_car():
            self.capture_failure_snapshot("sell_remove_selected_car_failed", module_name="sell")
            return False

        ready = self.wait_for_sell_ready_after_delete()
        if ready:
            self.sell_tail_position_ready = True
        return ready

    def sell_consumable_car(self, target_count):
        # 如果后续你单独增加 sell_counter，建议把 cj_counter 全部替换掉
        if self.sc_count >= target_count:
            return True

        self.reset_sell_tail_position("module_start")
        self.update_running_ui("移除车辆", self.sc_count, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        self.log("进入车辆与收藏...")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_image(
            "BNandUC.png",
            region=self.regions["左"],
            threshold=0.75,
            timeout=12,
            interval=0.3,
            fast_mode=True
        )
        if not pos_buycar:
            self.log("未识别到 购买新车与二手车")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = self.wait_for_any_image(
            ["buyandsell-w.png", "buyandsell-b.png"],
            region=self.regions["上"],
            threshold=0.75,
            timeout=40,
            interval=0.5,
            fast_mode=True
        )
        if not pos_bs:
            self.log("未找到购买与出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)

        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        self.hw_press("enter")  # 进入我的车辆
        time.sleep(2.0)

        # 先驾驶一辆收藏 22B，避免删掉当前保留用车。
        self.hw_press("y")
        time.sleep(1.0)
        self.hw_press("enter")
        time.sleep(0.8)
        self.hw_press("esc") 
        time.sleep(1.5)
        #驾驶收藏的车
        self.hw_press("enter")
        time.sleep(0.8)
        self.move_to_game_coord(5, 5)
        time.sleep(0.2)
        pos = self.wait_for_image(
            "rc.png",
            region=self.regions["全界面"], # 【修改】：从中间改为全界面，防止漏搜
            threshold=0.65,             # 【修改】：稍微降低阈值，提高识别率
            timeout=5,                  # 【修改】：给足弹窗出现的时间
            interval=0.2,
            fast_mode=True
        )
        if pos:
            self.log("找到上车，执行点击")
            self.game_click(pos) # 【重要修复】：之前写的是 self.safe_click 导致直接报错崩溃，现已修正
            time.sleep(2.0)
        else:
            self.log("该车辆已经驾驶，或未找到图片，执行两次ESC")
            self.hw_press("esc")
            time.sleep(1.5)
            self.hw_press("esc")
        time.sleep(2.0)

        found_buy_sell = False
        for i in range(30):
            if not self.is_running:
                return False
            pos = self.wait_for_any_image(
                ["buyandsell-b.png", "buyandsell-w.png"],
                region=self.regions["上"],
                threshold=0.70,
                timeout=0.8,
                interval=0.2,
                fast_mode=True,
            )
            if pos:
                self.log(f"第 {i + 1} 次检测到购买与出售，进入我的车辆")
                self.hw_press("enter")
                found_buy_sell = True
                break
            self.log(f"第 {i + 1} 次未检测到购买与出售，等待后重试")
            time.sleep(1.0)
        if not found_buy_sell:
            self.log("删车：驾驶收藏车后未能回到购买与出售")
            self.capture_failure_snapshot("sell_buy_and_sell_not_found_after_drive", module_name="sell")
            return False

        time.sleep(2.0)

        if not self.apply_duplicate_b_filter_for_sell():
            return False

        if not self.ensure_sell_car_grid_ready(reason="after_precise_filter"):
            return False

        self.reset_sell_tail_position("after_precise_filter")
        self.log("开始删除筛选结果中的重复项+B级+全轮驱动+传奇车辆。请确认筛选结果已人工审核。")

        while self.sc_count < target_count:
            self.log(f"is_running = {self.is_running}")
            if not self.is_running:
                return False

            if not self.delete_one_sell_car():
                if self.sell_stop_no_deletable:
                    self.log("删车：未找到无全新标签的可删候选，提前结束删车模块。")
                    return True
                return False

            self.sc_count += 1
            self.update_running_ui("移除车辆", self.sc_count, target_count)
            self.log(f"已尝试删除车辆 {self.sc_count}/{target_count}")

        for _ in range(3):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(1.0)

        return True

    # ==========================================
    # --- 模块：刷CR点 ---
    # ==========================================
    def get_cr_car_profile(self):
        return self.get_cr_car_profile_by_type(self.get_selected_cr_car_type())

    def get_cr_car_profile_by_type(self, car_type):
        if car_type == "toyota":
            return {
                "type": "toyota",
                "label": "丰田",
                "lap_seconds": self.get_cr_lap_seconds_for_car("toyota"),
                "car_template": "ToyotaRaceCar.png",
                "negative_templates": ["ToyotaAE86SpecialMisdetect.png"],
            }

        return {
            "type": "wuling",
            "label": "五菱",
            "lap_seconds": self.get_cr_lap_seconds_for_car("wuling"),
            "brand_templates": ["Wuling.png", "WulingBlack.png"],
            "brand_threshold": 0.68,
            "car_template": "WulingRaceCar.png",
            "car_templates": ["WulingRaceCar.png", "WulingRaceCar2.png"],
            "negative_templates": ["ToyotaAE86SpecialMisdetect.png"],
        }

    def get_cr_shortfall_car_cost(self):
        return self.get_config_int("cr_shortfall_car_cost", 85000, min_value=1)

    def get_cr_shortfall_settlement_laps(self):
        entry_widget = getattr(self, "entry_cr_shortfall_settlement_laps", None)
        if entry_widget is not None:
            return self.get_positive_entry_value(
                entry_widget,
                self.config.get("cr_shortfall_settlement_laps", self.config.get("cr_settlement_laps", 5)),
            )
        return self.get_config_int(
            "cr_shortfall_settlement_laps",
            self.config.get("cr_settlement_laps", 5),
            min_value=1,
        )

    def get_cr_shortfall_car_type(self):
        option_widget = getattr(self, "option_cr_shortfall_car_type", None)
        if option_widget is not None:
            return "toyota" if option_widget.get() == "丰田" else "wuling"
        return self.config.get("cr_shortfall_car_type", self.config.get("cr_car_type", "wuling"))

    def ensure_cr_for_buy_cycle(self, target_count):
        if self.car_counter >= target_count:
            return True

        remaining = max(0, int(target_count) - int(self.car_counter))
        required_cr = remaining * self.get_cr_shortfall_car_cost()
        if required_cr <= 0:
            return True

        self.log(f"CR兜底：买车前检测，剩余 {remaining} 辆，预计需要 {required_cr:,} CR。")
        current_cr = self.read_current_cr_value()
        if current_cr is None:
            self.log("CR兜底：无法识别当前 CR，停止买车以避免余额不足导致流程失控。")
            self.capture_failure_snapshot("cr_shortfall_current_cr_unreadable", module_name="buy")
            return False

        if current_cr >= required_cr:
            self.log(f"CR兜底：当前 {current_cr:,} CR，已足够完成本轮买车。")
            return True

        if not bool(self.config.get("cr_shortfall_fallback_enabled", True)):
            self.log(
                f"CR兜底已关闭：当前 {current_cr:,} CR，不足 {required_cr:,} CR，停止买车。"
            )
            self.capture_failure_snapshot(
                "cr_shortfall_disabled_insufficient_cr",
                module_name="buy",
                details={"current_cr": current_cr, "required_cr": required_cr},
            )
            return False

        self.log(
            f"CR兜底：当前 {current_cr:,} CR，不足 {required_cr:,} CR，"
            f"开始自动刷 CR 到目标值后继续买车。"
        )
        if not self.logic_cr_grind_until_target(required_cr):
            self.capture_failure_snapshot(
                "cr_shortfall_grind_failed",
                module_name="buy",
                details={"current_cr": current_cr, "required_cr": required_cr},
            )
            return False

        final_cr = self.read_current_cr_value()
        if final_cr is None or final_cr < required_cr:
            self.log("CR兜底：刷 CR 后仍未确认余额足够，停止买车。")
            self.capture_failure_snapshot(
                "cr_shortfall_final_cr_insufficient",
                module_name="buy",
                details={"final_cr": final_cr, "required_cr": required_cr},
            )
            return False

        self.log(f"CR兜底：当前 {final_cr:,} CR，已达到买车目标，返回批量买车流程。")
        return True

    def get_cr_race_car_template_candidates(self, car_profile):
        templates = car_profile.get("car_templates") or []
        if templates:
            return templates

        template = car_profile.get("car_template")
        return [template] if template else []

    def get_selected_cr_car_type(self):
        car_type = self.config.get("cr_car_type", "wuling")
        option_widget = getattr(self, "option_cr_car_type", None)
        if option_widget is not None:
            car_type = "toyota" if option_widget.get() == "丰田" else "wuling"
        return car_type if car_type in ("wuling", "toyota") else "wuling"

    def get_cr_lap_seconds_key(self, car_type=None):
        return "cr_toyota_lap_seconds" if (car_type or self.get_selected_cr_car_type()) == "toyota" else "cr_wuling_lap_seconds"

    def get_default_cr_lap_seconds(self, car_type=None):
        return 380 if (car_type or self.get_selected_cr_car_type()) == "toyota" else 340

    def get_cr_lap_seconds_for_car(self, car_type=None):
        key = self.get_cr_lap_seconds_key(car_type)
        return self.get_config_int(key, self.get_default_cr_lap_seconds(car_type), min_value=1)

    def save_current_cr_lap_seconds_to_config(self, normalize_entry=False):
        entry_widget = getattr(self, "entry_cr_lap_seconds", None)
        if entry_widget is None:
            return self.get_cr_lap_seconds_for_car()
        car_type = self.get_selected_cr_car_type()
        default_value = self.get_default_cr_lap_seconds(car_type)
        value = self.get_positive_entry_value(entry_widget, self.config.get(self.get_cr_lap_seconds_key(car_type), default_value))
        self.config[self.get_cr_lap_seconds_key(car_type)] = value
        if normalize_entry:
            self.normalize_positive_entry(entry_widget, value)
        return value

    def on_cr_car_type_changed(self, value=None):
        old_car_type = self.config.get("cr_car_type", "wuling")
        entry_widget = getattr(self, "entry_cr_lap_seconds", None)
        if entry_widget is not None and old_car_type in ("wuling", "toyota"):
            old_key = self.get_cr_lap_seconds_key(old_car_type)
            old_default = self.get_default_cr_lap_seconds(old_car_type)
            self.config[old_key] = self.get_positive_entry_value(
                entry_widget,
                self.config.get(old_key, old_default),
            )

        car_type = "toyota" if value == "丰田" else "wuling"
        self.config["cr_car_type"] = car_type
        if entry_widget is not None:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, str(self.get_cr_lap_seconds_for_car(car_type)))
        self.save_runtime_config()

    def save_cr_lap_seconds_from_ui(self):
        value = self.save_current_cr_lap_seconds_to_config(normalize_entry=True)
        self.save_runtime_config()
        self.log(f"刷CR：已保存 {self.get_cr_car_profile()['label']} 每圈 {value} 秒。")

    def get_cr_settlement_laps(self):
        entry_widget = getattr(self, "entry_cr_settlement_laps", None)
        if entry_widget is None:
            return max(1, int(self.config.get("cr_settlement_laps", 5)))
        return self.get_positive_entry_value(entry_widget, self.config.get("cr_settlement_laps", 5))

    def is_cr_settlement_enabled(self):
        var_widget = getattr(self, "var_cr_settlement_enabled", None)
        if var_widget is not None:
            try:
                return bool(var_widget.get())
            except Exception:
                pass
        return bool(self.config.get("cr_settlement_enabled", True))

    def update_cr_status_labels(self, current_cr=None, total_delta=None, per_lap=None, per_hour=None):
        try:
            if hasattr(self, "lbl_cr_current"):
                current_text = "-" if current_cr is None else f"{current_cr:,}"
                self.ui_call(self.lbl_cr_current.configure, text=f"当前CR: {current_text}")
            if hasattr(self, "lbl_cr_delta"):
                delta_text = "-" if total_delta is None else f"+{total_delta:,}"
                self.ui_call(self.lbl_cr_delta.configure, text=f"累计: {delta_text}")
            if hasattr(self, "lbl_cr_eff"):
                if per_lap is None or per_hour is None:
                    eff_text = "-"
                else:
                    eff_text = f"{int(per_lap):,}/圈  {int(per_hour):,}/小时"
                self.ui_call(self.lbl_cr_eff.configure, text=f"效率: {eff_text}")
        except Exception:
            pass

    def wait_with_running(self, seconds):
        deadline = time.time() + max(0, seconds)
        while self.is_running and time.time() < deadline:
            time.sleep(0.05)
        return self.is_running

    def is_step_retry_enabled(self):
        var_widget = getattr(self, "var_step_retry_enabled", None)
        if var_widget is not None:
            try:
                return bool(var_widget.get())
            except Exception:
                pass
        return bool(self.config.get("step_retry_enabled", False))

    def get_cr_step_retry_count(self):
        entry_widget = getattr(self, "entry_cr_step_retry_count", None)
        if entry_widget is not None:
            return self.get_positive_entry_value(entry_widget, self.config.get("cr_step_retry_count", 3))
        return self.get_config_int("cr_step_retry_count", 3)

    def execute_verified_step(self, step_name, action_func, retry_count=None, retry_wait=None):
        attempts = 1
        if self.is_step_retry_enabled():
            attempts = max(1, int(retry_count or self.get_config_int("general_step_retry_count", 2)))
        wait_seconds = retry_wait if retry_wait is not None else self.get_config_float("general_menu_retry_wait_seconds", 0.6)

        for attempt in range(1, attempts + 1):
            if not self.is_running:
                return False

            if attempt > 1:
                self.log(f"[重试] {step_name}: 第 {attempt}/{attempts} 次")

            try:
                if action_func():
                    return True
            except Exception as e:
                self.log(f"[重试] {step_name} 异常: {e}")

            if attempt < attempts:
                self.wait_with_running(wait_seconds)

        self.log(f"[重试] {step_name}: 已失败 {attempts} 次")
        return False

    def find_and_click_image(self, image_list, label, region=None, threshold=0.75, timeout=20, interval=0.35, fast_mode=True):
        pos = self.wait_for_any_image(
            image_list,
            region=region or self.regions["全界面"],
            threshold=threshold,
            timeout=timeout,
            interval=interval,
            fast_mode=fast_mode,
        )
        if not pos:
            self.log(f"未找到 {label}")
            return False

        self.game_click(pos)
        time.sleep(self.get_config_float("cr_click_wait_seconds", 0.8))
        return True

    def find_and_click_with_scroll(self, image_list, label, scroll_key="down", attempts=18, threshold=0.72):
        for i in range(attempts):
            if not self.is_running:
                return False

            pos = self.wait_for_any_image(
                image_list,
                region=self.regions["全界面"],
                threshold=threshold,
                timeout=0.8,
                interval=0.2,
                fast_mode=True,
            )
            if pos:
                self.log(f"找到 {label} ({i + 1}/{attempts})")
                self.game_click(pos)
                time.sleep(1.0)
                return True

            self.hw_press(scroll_key, delay=0.12)
            time.sleep(0.35)

        self.log(f"滚动未找到 {label}")
        return False

    def select_cr_goelia_event(self):
        self.log("进入公路赛事列表，固定右移 20 次选中迎战巨汉...")
        time.sleep(self.get_config_float("cr_page_load_wait_seconds", 2.0))

        for _ in range(20):
            if not self.is_running:
                return False
            self.hw_press("right", delay=0.10)
            time.sleep(0.12)

        time.sleep(self.get_config_float("cr_click_wait_seconds", 0.8))

        pos_goelia = self.wait_for_image(
            "GoeliaSmall.png",
            region=self.regions["全界面"],
            threshold=0.62,
            timeout=2,
            interval=0.3,
            fast_mode=True,
        )
        if pos_goelia:
            self.log("已确认选中迎战巨汉赛事，进入赛事详情。")
            self.hw_press("enter")
            time.sleep(self.get_config_float("cr_page_load_wait_seconds", 2.0))
            return True

        self.log("固定右移后未识别到迎战巨汉，尝试模板点击兜底。")
        pos_goelia = self.wait_for_image(
            "GoeliaSmall.png",
            region=self.regions["全界面"],
            threshold=0.58,
            timeout=4,
            interval=0.3,
            fast_mode=False,
        )
        if pos_goelia:
            self.game_click(pos_goelia)
            time.sleep(self.get_config_float("cr_click_wait_seconds", 0.8))
            self.hw_press("enter")
            time.sleep(self.get_config_float("cr_page_load_wait_seconds", 2.0))
            return True

        self.log("未能确认或点击迎战巨汉赛事。")
        self.capture_failure_snapshot("cr_goelia_event_not_found", module_name="cr")
        return False

    def wait_for_cr_rival_data(self):
        self.log("等待 R998 劲敌数据加载...")
        if not self.wait_with_running(self.get_config_float("cr_rival_data_initial_wait_seconds", 5)):
            return False

        retry_count = self.get_cr_step_retry_count()
        for attempt in range(1, retry_count + 1):
            if self.handle_cr_server_error():
                self.log("服务器错误已处理，继续等待劲敌数据。")

            pos = self.wait_for_image(
                "GapWithFormidableAdversary.png",
                region=self.regions["全界面"],
                threshold=0.70,
                timeout=12,
                interval=0.6,
                fast_mode=True,
            )
            if pos:
                self.log("劲敌数据加载完成。")
                return True

            self.log(f"未识别到 与劲敌差距，等待后重试 ({attempt}/{retry_count})")
            self.hw_press("enter")
            if not self.wait_with_running(self.get_config_float("cr_unknown_error_enter_interval_seconds", 5)):
                return False

        self.log("未识别到 与劲敌差距，劲敌数据可能未加载完成。")
        return False

    def is_cr_rival_detail_visible(self, timeout=0.8):
        return self.wait_for_image(
            "GapWithFormidableAdversary.png",
            region=self.regions["全界面"],
            threshold=0.70,
            timeout=timeout,
            interval=0.2,
            fast_mode=True,
        ) is not None

    def wait_for_cr_car_list_visible(self, timeout=8):
        deadline = time.time() + max(0.1, timeout)
        while self.is_running and time.time() < deadline:
            if self.is_cr_car_list_visible(timeout=0.4):
                return True
            time.sleep(0.15)
        return False

    def select_first_cr_rival_and_open_car_list(self):
        self.log("选择第一名劲敌，防止胜利后赛事自动结束。")
        self.hw_press("y")

        rival_list_pos = self.wait_for_image(
            "ChangeFormidableAdversary.png",
            region=self.regions["全界面"],
            threshold=0.65,
            timeout=3,
            interval=0.25,
            fast_mode=True,
        )
        if not rival_list_pos:
            self.log("刷CR：未确认进入更改劲敌列表，仍尝试按 Enter 选择当前劲敌。")

        self.hw_press("enter")
        if not self.wait_with_running(self.get_config_float("cr_rival_apply_wait_seconds", 5)):
            return False

        for attempt in range(1, 4):
            if self.wait_for_cr_car_list_visible(timeout=1.0):
                self.log("刷CR：已进入车辆选择列表。")
                return True

            if self.is_cr_rival_detail_visible(timeout=0.5):
                self.log(f"刷CR：仍在劲敌详情页，按 Enter 进入车辆选择列表 ({attempt}/3)。")
            else:
                self.log(f"刷CR：未确认车辆选择列表，按 Enter 继续确认 ({attempt}/3)。")

            self.hw_press("enter")
            if self.wait_for_cr_car_list_visible(timeout=4.0):
                self.log("刷CR：已进入车辆选择列表。")
                return True

        self.log("刷CR：选择劲敌后未能进入车辆选择列表。")
        self.capture_failure_snapshot("cr_car_list_not_open_after_rival", module_name="cr")
        return False

    def handle_cr_server_error(self):
        server_error = self.find_any_image(
            ["ServerError.png", "ServerErrorCantUpdateFormidableAdversaryData.png"],
            region=self.regions["全界面"],
            threshold=0.68,
            fast_mode=True,
        )
        if not server_error:
            return False

        retry_count = self.get_cr_step_retry_count()
        wait_seconds = self.get_config_float("cr_unknown_error_enter_interval_seconds", 5)
        self.log("检测到服务器错误/无法更新劲敌数据，开始 Enter 等待恢复。")
        for attempt in range(1, retry_count + 1):
            if not self.is_running:
                return False
            self.hw_press("enter")
            self.wait_with_running(wait_seconds)

            solved = self.find_any_image(
                ["ServerErrorSolved.png", "UpdateFormidableAdversaryDataSucessful.png"],
                region=self.regions["全界面"],
                threshold=0.68,
                fast_mode=True,
            )
            if solved:
                self.log(f"服务器错误已解决 ({attempt}/{retry_count})，按 Enter 返回。")
                self.hw_press("enter")
                time.sleep(1.0)
                return True

            still_error = self.find_any_image(
                ["ServerError.png", "ServerErrorCantUpdateFormidableAdversaryData.png"],
                region=self.regions["全界面"],
                threshold=0.68,
                fast_mode=True,
            )
            if not still_error:
                self.log(f"服务器错误界面已离开 ({attempt}/{retry_count})。")
                return True

        self.log("服务器错误多次尝试仍未解决。")
        self.capture_failure_snapshot("cr_server_error_unresolved", module_name="cr")
        return False

    def select_cr_r998_class(self):
        self.log("固定右移 6 次选择 R 998 车辆等级...")
        time.sleep(self.get_config_float("cr_click_wait_seconds", 0.8))
        for _ in range(6):
            if not self.is_running:
                return False
            self.hw_press("right", delay=0.10)
            time.sleep(0.15)

        time.sleep(self.get_config_float("cr_click_wait_seconds", 0.8))
        r998_pos = self.wait_for_any_image(
            ["R998.png", "R998Detail1.png"],
            region=self.regions["全界面"],
            threshold=0.68,
            timeout=2,
            interval=0.25,
            fast_mode=True,
        )
        if r998_pos:
            self.log("已确认选中 R 998。")
            return True

        self.log("固定右移后未确认 R 998，尝试模板点击兜底。")
        r998_pos = self.wait_for_any_image(
            ["R998.png", "R998Detail1.png"],
            region=self.regions["全界面"],
            threshold=0.60,
            timeout=4,
            interval=0.3,
            fast_mode=False,
        )
        if r998_pos:
            self.game_click(r998_pos)
            time.sleep(self.get_config_float("cr_click_wait_seconds", 0.8))
            return True

        self.log("未能确认或点击 R 998 车辆等级。")
        self.capture_failure_snapshot("cr_r998_class_not_found", module_name="cr")
        return False

    def enter_cr_event_page(self):
        self.log("刷CR：准备进入在线劲敌赛事...")
        if not self.enter_menu():
            return False

        session = getattr(self, "cr_session", {})
        if not session.get("start_cr") and not self.record_cr_value("开始刷圈", 0, 0):
            self.log("开始CR记录失败，继续执行刷CR流程。")

        online_pos = None
        for _ in range(8):
            if not self.is_running:
                return False
            online_pos = self.wait_for_image(
                "Online.png",
                region=self.regions["全界面"],
                threshold=0.70,
                timeout=0.8,
                interval=0.2,
                fast_mode=True,
            )
            if online_pos:
                break
            self.hw_press("pagedown", delay=0.15)
            time.sleep(0.5)

        if not online_pos:
            self.log("未找到 在线 选项卡")
            return False

        self.game_click(online_pos)
        time.sleep(1.0)

        if not self.find_and_click_image(["FormidableAdversary.png"], "劲敌赛事", threshold=0.70, timeout=20):
            return False
        if not self.find_and_click_image(["FrozaHorizonFormidableAdversary.png"], "地平线劲敌赛事", threshold=0.70, timeout=30):
            return False
        if not self.find_and_click_image(["RoadRacing.png"], "公路竞速赛", threshold=0.70, timeout=30):
            return False

        if not self.select_cr_goelia_event():
            return False

        pos_detail = self.wait_for_image(
            "GoeliaDetail.png",
            region=self.regions["全界面"],
            threshold=0.65,
            timeout=4,
            interval=0.5,
            fast_mode=True,
        )
        if not pos_detail:
            self.log("未命中迎战巨汉详情模板，按当前界面继续选择 R 998。")

        if not self.select_cr_r998_class():
            return False

        if not self.wait_for_cr_rival_data():
            return False

        return self.select_first_cr_rival_and_open_car_list()

    def apply_cr_race_car_fast_filter(self):
        self.log("刷CR：快速筛选 赛道玩具（模板匹配）。")
        self.hw_press("y")
        panel_pos = self.wait_for_image(
            "FilterPanel.png",
            region=self.regions["全界面"],
            threshold=0.70,
            timeout=8,
            interval=0.3,
            fast_mode=True,
        )
        if not panel_pos:
            self.log("刷CR：未识别到筛选面板，跳过快筛。")
            self.capture_failure_snapshot("cr_fast_filter_panel_not_found", module_name="cr")
            return False

        self.filter_panel_region = self.get_filter_panel_search_region(panel_pos)
        self.filter_fast_scales = self.get_filter_scales_to_try(
            strict_verify=self.is_filter_strict_click_verify_enabled()
        )
        self.log("刷CR：筛选面板已打开，重置筛选后按模板勾选赛道玩具。")
        self.hw_press("x")
        time.sleep(0.5)

        self.hw_press("home", delay=0.08)
        time.sleep(0.25)

        track_toys_templates = [
            "TrackToysWhiteUnchecked.png",
            "TrackToysWhiteChecked.png",
            "TrackToysBlackUnchecked.png",
            "TrackToysBlackChecked.png",
        ]
        scales_to_try = self.filter_fast_scales or self.get_filter_scales_to_try(strict_verify=False)
        search_region = self.filter_panel_region or self.regions["全界面"]

        track_toys_ok = False
        for attempt in range(1, 4):
            if not self.is_running:
                return False

            row_info = self.find_filter_option_row(
                track_toys_templates,
                threshold=0.66,
                timeout=2.0,
                region=search_region,
                scales_to_try=scales_to_try,
            )
            if not row_info:
                self.log(f"刷CR筛选：未找到 赛道玩具 选项 (第{attempt}次)。")
                time.sleep(0.3)
                continue

            if self.is_filter_row_checked(row_info):
                self.log("刷CR筛选：赛道玩具 已勾选。")
                self.move_mouse_to_desktop_top_left()
                track_toys_ok = True
                break

            self.log(f"刷CR筛选：点击勾选 赛道玩具 (第{attempt}次)。")
            self.game_click(row_info.get("checkbox_pos", row_info["pos"]))
            self.move_mouse_to_desktop_top_left()
            time.sleep(0.5)

            row_info = self.find_filter_option_row(
                track_toys_templates,
                threshold=0.66,
                timeout=1.5,
                region=search_region,
                scales_to_try=scales_to_try,
            )
            if row_info and self.is_filter_row_checked(row_info):
                self.log("刷CR筛选：赛道玩具 勾选成功。")
                track_toys_ok = True
                break

            self.log(f"刷CR筛选：点击未确认，尝试 Enter 兜底 (第{attempt}次)。")
            self.hw_press("enter")
            time.sleep(0.5)

            row_info = self.find_filter_option_row(
                track_toys_templates,
                threshold=0.66,
                timeout=1.5,
                region=search_region,
                scales_to_try=scales_to_try,
            )
            if row_info and self.is_filter_row_checked(row_info):
                self.log("刷CR筛选：赛道玩具 Enter 兜底勾选成功。")
                track_toys_ok = True
                break

        if not track_toys_ok:
            self.log("刷CR筛选：赛道玩具 3次尝试均未确认勾选，回退到全车辆筛选。")
            self.capture_failure_snapshot("cr_track_toys_filter_failed", module_name="cr")
            self.hw_press("esc")
            time.sleep(1.0)
            return False

        self.hw_press("esc")
        time.sleep(3.0)
        self.hw_press("pageup", delay=0.15)
        time.sleep(0.9)
        self.log("刷CR：快筛完成，开始在筛选结果中查找目标车。")
        return True

    def is_cr_filtered_result_invalid(self):
        pos = self.find_image(
            "NoAvailableCars.png",
            region=self.regions["全界面"],
            threshold=0.70,
            fast_mode=True,
        )
        if pos:
            self.log("刷CR：筛选结果显示没有可用车辆，转入慢速兜底。")
            return True
        return False

    def is_cr_target_brand_visible(self, car_profile, log_on_missing=True):
        brand_pos = self.find_any_image(
            car_profile.get("brand_templates", []),
            region=self.regions["全界面"],
            threshold=car_profile.get("brand_threshold", 0.72),
            fast_mode=True,
        )
        if not brand_pos:
            if log_on_missing:
                self.log(f"刷CR：筛选结果未识别到 {car_profile['label']} 车厂页签，转入慢速兜底。")
            return False
        return True

    def clear_cr_race_car_filters(self):
        self.log("刷CR：清空筛选后进入慢速兜底扫描。")
        no_cars_pos = self.find_image(
            "NoAvailableCars.png",
            region=self.regions["全界面"],
            threshold=0.70,
            fast_mode=True,
        )
        if no_cars_pos:
            self.log("刷CR：检测到没有可用车辆提示，按 Enter 回到完整选车界面。")
            self.hw_press("enter")
            time.sleep(2.0)

        panel_pos = self.find_image(
            "FilterPanel.png",
            region=self.regions["全界面"],
            threshold=0.70,
            fast_mode=True,
        )
        if not panel_pos:
            self.hw_press("y")
            panel_pos = self.wait_for_image(
                "FilterPanel.png",
                region=self.regions["全界面"],
                threshold=0.70,
                timeout=4,
                interval=0.3,
                fast_mode=True,
            )

        if not panel_pos:
            self.log("刷CR：未能打开筛选面板清空筛选，直接尝试慢速扫描。")
            return False

        self.hw_press("x")
        time.sleep(0.5)
        self.hw_press("esc")
        time.sleep(3.0)
        self.hw_press("pageup", delay=0.15)
        time.sleep(0.9)
        self.filter_panel_region = None
        self.filter_fast_scales = None
        return True

    def scan_cr_race_car_by_template(
        self,
        car_profile,
        scan_attempts=120,
        right_steps=4,
        template_timeout=0.8,
        scan_label="慢速兜底",
    ):
        template_candidates = self.get_cr_race_car_template_candidates(car_profile)
        negative_templates = car_profile.get("negative_templates", [])
        skipped_negative = 0

        if not template_candidates:
            self.log(f"刷CR：{scan_label}没有可用的 {car_profile['label']} 目标车模板。")
            return None, {"attempts": 0, "skipped_negative": skipped_negative}

        for attempt in range(scan_attempts):
            if not self.is_running:
                return None, {"attempts": attempt, "skipped_negative": skipped_negative}

            car_pos = self.wait_for_any_image(
                template_candidates,
                region=self.regions["全界面"],
                threshold=0.74,
                timeout=template_timeout,
                interval=0.2,
                fast_mode=False,
            )
            if car_pos:
                negative_pos = self.find_any_image(
                    negative_templates,
                    region=self.regions["全界面"],
                    threshold=0.72,
                    fast_mode=False,
                ) if negative_templates else None

                same_candidate = (
                    negative_pos
                    and abs(negative_pos[0] - car_pos[0]) <= 220
                    and abs(negative_pos[1] - car_pos[1]) <= 180
                )
                if same_candidate:
                    skipped_negative += 1
                    self.log("刷CR：检测到 AE86 误识别候选，跳过当前车辆。")
                else:
                    return car_pos, {"attempts": attempt + 1, "skipped_negative": skipped_negative}

            for _ in range(right_steps):
                if not self.is_running:
                    return None, {"attempts": attempt + 1, "skipped_negative": skipped_negative}
                self.hw_press("right", delay=0.06)
                time.sleep(0.07)
            time.sleep(0.25)

        self.log(f"刷CR：{scan_label}未找到 {car_profile['label']} 目标车。")
        return None, {"attempts": scan_attempts, "skipped_negative": skipped_negative}

    def is_cr_car_list_visible(self, timeout=0.8):
        if self.is_cr_rival_detail_visible(timeout=0.2):
            return False

        return self.wait_for_image(
            "Filter.png",
            region=self.regions["全界面"],
            threshold=0.78,
            timeout=timeout,
            interval=0.2,
            fast_mode=True,
        ) is not None

    def is_cr_manufacturer_grid_visible(self):
        return self.find_any_image(
            ["ToyotaWhite.png", "ToyotaBlack.png", "Wuling.png", "WulingBlack.png"],
            region=self.regions["全界面"],
            threshold=0.68,
            fast_mode=True,
        ) is not None

    def ensure_cr_car_list_ready_for_basic_scan(self):
        if self.is_cr_car_list_visible(timeout=0.8):
            return True

        if self.is_cr_manufacturer_grid_visible():
            self.log("刷CR：检测到制造商选择页，按 Esc 返回车辆列表。")
            self.hw_press("esc")
            time.sleep(1.0)
            if self.is_cr_car_list_visible(timeout=3.0):
                return True

        self.log("刷CR：未确认车辆列表，按 Enter 进入选车列表。")
        self.hw_press("enter")
        time.sleep(3.0)
        if self.is_cr_car_list_visible(timeout=3.0):
            return True

        if self.is_cr_manufacturer_grid_visible():
            self.log("刷CR：误入制造商选择页，按 Esc 返回车辆列表。")
            self.hw_press("esc")
            time.sleep(1.0)
            if self.is_cr_car_list_visible(timeout=3.0):
                return True

        self.log("刷CR：未能确认车辆列表，停止基础模板选车。")
        self.capture_failure_snapshot("cr_car_list_not_ready", module_name="cr")
        return False

    def select_cr_race_car_basic_template(self, car_profile):
        self.log(f"进入选车界面，准备使用基础模板识别选择 {car_profile['label']} 加成车...")
        if not self.ensure_cr_car_list_ready_for_basic_scan():
            return False

        self.log(f"刷CR：{car_profile['label']} 使用基础模板识别，不执行快筛。")
        negative_templates = car_profile.get("negative_templates", [])
        scan_attempts = 120
        skipped_negative = 0
        car_pos = None

        for attempt in range(scan_attempts):
            if not self.is_running:
                return False

            car_pos = self.wait_for_image(
                car_profile["car_template"],
                region=self.regions["全界面"],
                threshold=0.74,
                timeout=0.8,
                interval=0.2,
                fast_mode=False,
            )
            if car_pos:
                negative_pos = self.find_any_image(
                    negative_templates,
                    region=self.regions["全界面"],
                    threshold=0.72,
                    fast_mode=False,
                ) if negative_templates else None

                same_candidate = (
                    negative_pos
                    and abs(negative_pos[0] - car_pos[0]) <= 220
                    and abs(negative_pos[1] - car_pos[1]) <= 180
                )
                if same_candidate:
                    skipped_negative += 1
                    self.log("刷CR：检测到 AE86 误识别候选，跳过当前车辆。")
                    car_pos = None
                else:
                    break

            for _ in range(4):
                if not self.is_running:
                    return False
                self.hw_press("right", delay=0.06)
                time.sleep(0.07)
            time.sleep(0.25)

        if not car_pos:
            self.log(f"未找到 {car_profile['label']} 加成车")
            self.capture_failure_snapshot(
                "cr_car_not_found",
                module_name="cr",
                details={
                    "car": car_profile["label"],
                    "scan_mode": "basic_template",
                    "car_template": car_profile["car_template"],
                    "negative_templates": negative_templates,
                    "scan_attempts": scan_attempts,
                    "skipped_negative": skipped_negative,
                },
            )
            return False

        self.game_click(car_pos)
        time.sleep(0.6)
        self.hw_press("enter")
        time.sleep(4.0)
        return True

    def select_cr_race_car(self, car_profile):
        if car_profile.get("type") == "toyota":
            return self.select_cr_race_car_basic_template(car_profile)

        self.log(f"进入选车界面，准备选择 {car_profile['label']} 加成车...")

        car_list_ready = self.is_cr_car_list_visible(timeout=0.8)
        if car_list_ready:
            self.log("刷CR：当前已在选择车辆列表，准备快速筛选。")
        else:
            self.hw_press("enter")
            time.sleep(3.0)

        if not car_list_ready:
            car_list_ready = self.is_cr_car_list_visible(timeout=3.0)

        if not car_list_ready:
            self.log("刷CR：未确认筛选入口，仍尝试快速筛选。")

        # Phase 1: Template scan on current page (no filter, no scroll)
        self.log(f"刷CR：直接模板匹配查找 {car_profile['label']} 目标车（当前页面）。")
        car_pos, _ = self.scan_cr_race_car_by_template(
            car_profile,
            scan_attempts=1,
            right_steps=0,
            template_timeout=1.0,
            scan_label="当前页面模板识别",
        )
        if car_pos:
            self.log(f"刷CR：当前页面命中 {car_profile['label']} 车辆模板。")
            self.game_click(car_pos)
            time.sleep(0.6)
            self.hw_press("enter")
            time.sleep(4.0)
            return True

        # Phase 2: Not found on first page — PageUp × 3 to jump to last pages
        self.log(f"刷CR：当前页面未找到 {car_profile['label']}，按 3 次 PageUp 跳转到倒数页面。")
        for i in range(3):
            if not self.is_running:
                return False
            self.hw_press("pageup", delay=0.12)
            time.sleep(0.5)

        # Phase 3: Template scan on last pages
        self.log(f"刷CR：倒数页面模板匹配查找 {car_profile['label']} 目标车。")
        car_pos, _ = self.scan_cr_race_car_by_template(
            car_profile,
            scan_attempts=1,
            right_steps=0,
            template_timeout=1.0,
            scan_label="倒数页面模板识别",
        )
        if car_pos:
            self.log(f"刷CR：倒数页面命中 {car_profile['label']} 车辆模板。")
            self.game_click(car_pos)
            time.sleep(0.6)
            self.hw_press("enter")
            time.sleep(4.0)
            return True

        # Phase 4: Slow fallback — 120-attempt right-scroll scan
        self.log(f"刷CR：倒数页面未找到，切换慢速兜底扫描。")
        car_pos, slow_scan_stats = self.scan_cr_race_car_by_template(
            car_profile,
            scan_attempts=120,
            right_steps=4,
            template_timeout=0.8,
            scan_label="慢速兜底扫描",
        )

        if not car_pos:
            self.log(f"未找到 {car_profile['label']} 加成车")
            self.capture_failure_snapshot(
                "cr_car_not_found",
                module_name="cr",
                details={
                    "car": car_profile["label"],
                    "car_template": car_profile["car_template"],
                    "car_templates": self.get_cr_race_car_template_candidates(car_profile),
                    "negative_templates": car_profile.get("negative_templates", []),
                    "scan_attempts": 120,
                    "slow_scan_attempts": slow_scan_stats.get("attempts", 0),
                    "skipped_negative": slow_scan_stats.get("skipped_negative", 0),
                },
            )
            return False

        self.game_click(car_pos)
        time.sleep(0.6)
        self.hw_press("enter")
        time.sleep(4.0)
        return True

    def is_cr_autodrive_enabled(self, timeout=1.2):
        end_time = time.time() + max(0.1, timeout)
        while self.is_running and time.time() < end_time:
            if self.find_image("AutoDriveOn.png", region=self.regions["全界面"], threshold=0.70, fast_mode=True):
                return True
            time.sleep(0.2)
        return False

    def start_cr_race_and_autodrive(self):
        pos_start = self.wait_for_any_image(
            ["StartFormidableAdversaryRace.png", "StartFormidableAdversaryRaceBlack.png"],
            region=self.regions["全界面"],
            threshold=0.70,
            timeout=90,
            interval=0.6,
            fast_mode=True,
        )
        if not pos_start:
            self.log("未找到 开始劲敌赛事")
            return False

        self.game_click(pos_start)
        time.sleep(0.5)
        self.hw_press("enter")
        self.log("等待赛事加载...")
        if not self.wait_with_running(10.0):
            return False

        if self.is_cr_autodrive_enabled(timeout=2.0):
            self.log("已检测到自动驾驶开启，跳过 c+2。")
            return True

        for attempt in range(3):
            if not self.is_running:
                return False
            self.log(f"尝试开启自动驾驶 ({attempt + 1}/3)")
            self.hw_press("c")
            time.sleep(0.6)
            self.hw_press("2")
            time.sleep(2.0)

            if self.is_cr_autodrive_enabled(timeout=1.2):
                self.log("自动驾驶已开启。")
                return True

        self.log("未识别到自动驾驶开启状态")
        self.capture_failure_snapshot("cr_autodrive_not_confirmed", module_name="cr")
        return False

    def recover_cr_known_race_state(self):
        if self.find_image("ControllerDisconnect.png", region=self.regions["全界面"], threshold=0.70, fast_mode=True):
            self.log("刷CR守护：检测到手柄失联提示，按 Enter 后 Esc 回到刷圈。")
            self.hw_press("enter")
            time.sleep(1.0)
            self.hw_press("esc")
            time.sleep(1.0)
            return True

        if self.find_image("SettingInFormidableAdversaryRace.png", region=self.regions["全界面"], threshold=0.65, fast_mode=True):
            self.log("刷CR守护：检测到赛事设置界面，按 Esc 回到刷圈。")
            self.hw_press("esc")
            time.sleep(1.0)
            return True

        return False

    def verify_cr_race_guard_state(self):
        if self.handle_cr_server_error():
            return True

        if self.recover_cr_known_race_state():
            return True

        pos = self.find_any_image(
            ["AnnaAndLinkInFormidableAdversaryRace.png", "anna.png", "link.png"],
            region=self.regions["左下"],
            threshold=0.58,
            fast_mode=True,
        )
        if pos:
            self.log("刷CR守护：赛事刷圈状态正常。")
            return True

        handled_likes = self.handle_like_prompt_sequence("刷CR守护未知状态")
        if handled_likes:
            if self.recover_cr_known_race_state():
                return True
            pos = self.find_any_image(
                ["AnnaAndLinkInFormidableAdversaryRace.png", "anna.png", "link.png"],
                region=self.regions["左下"],
                threshold=0.58,
                fast_mode=True,
            )
            if pos:
                self.log("刷CR守护：点赞后已回到赛事刷圈状态。")
                return True
            self.log("刷CR守护：已处理点赞弹窗，等待下一次守护确认当前状态。")
            return True

        self.log("刷CR守护：未命中已知刷圈状态模板，已保存诊断截图。")
        self.capture_failure_snapshot("cr_unknown_race_state", module_name="cr")
        wait_seconds = self.get_config_float("cr_unknown_error_enter_interval_seconds", 5)
        for attempt in range(1, self.get_cr_step_retry_count() + 1):
            if not self.is_running:
                return False
            self.log(f"刷CR守护：未知状态尝试 Enter 恢复 ({attempt}/{self.get_cr_step_retry_count()})")
            self.hw_press("enter")
            self.wait_with_running(wait_seconds)
            if self.recover_cr_known_race_state():
                return True
            pos = self.find_any_image(
                ["AnnaAndLinkInFormidableAdversaryRace.png", "anna.png", "link.png"],
                region=self.regions["左下"],
                threshold=0.58,
                fast_mode=True,
            )
            if pos:
                self.log("刷CR守护：未知状态已通过 Enter 恢复。")
                return True
        return False

    def wait_cr_lap_period(self, car_profile, laps):
        target_seconds = max(1, int(car_profile["lap_seconds"] * max(1, laps)))
        start_time = time.time()
        next_guard_at = start_time + self.get_config_float("cr_guard_interval_seconds", 60)
        self.log(f"刷CR守护开始：{car_profile['label']} 约 {target_seconds} 秒后周期结算。")

        while self.is_running and time.time() - start_time < target_seconds:
            if self.should_abort_for_process_loss({"phase": "cr_grind_race_guard"}):
                return False

            now = time.time()
            if now >= next_guard_at:
                if not self.verify_cr_race_guard_state():
                    return False
                next_guard_at = now + self.get_config_float("cr_guard_interval_seconds", 60)

            elapsed = int(now - start_time)
            estimated_laps = min(laps, elapsed // max(1, car_profile["lap_seconds"]))
            self.update_running_ui("刷CR点", estimated_laps, laps)
            self.update_mini_cr_status(self.is_cr_settlement_enabled(), estimated_laps, laps)
            time.sleep(1.0)

        return self.is_running

    def exit_cr_race_for_settlement(self):
        self.log("到达周期圈数，准备退出赛事结算CR。")
        self.hw_press("esc")
        time.sleep(1.2)

        pos_exit = self.wait_for_image(
            "LeftFormidableAdversaryMatch.png",
            region=self.regions["全界面"],
            threshold=0.70,
            timeout=12,
            interval=0.4,
            fast_mode=True,
        )
        if not pos_exit:
            self.log("未找到 退出劲敌赛事 选项")
            self.capture_failure_snapshot("cr_exit_match_option_not_found", module_name="cr")
            return False

        self.game_click(pos_exit)
        time.sleep(0.8)
        self.wait_for_any_image(
            ["LeftMatch.png", "yes.png", "no.png"],
            region=self.regions["全界面"],
            threshold=0.65,
            timeout=3,
            interval=0.3,
            fast_mode=True,
        )
        self.hw_press("enter")
        settlement_return_started_at = time.time()
        time.sleep(5.0)
        self.handle_like_prompt_sequence("刷CR周期结算后")

        if not self.enter_menu():
            handled_likes = self.handle_like_prompt_after_stall(
                "刷CR周期结算后未回主菜单",
                settlement_return_started_at,
            )
            if handled_likes and self.enter_menu():
                return True
            self.log("退出赛事后未能回到菜单")
            self.capture_failure_snapshot("cr_exit_menu_not_found_after_settlement", module_name="cr")
            return False
        return True

    def get_cr_capture_region(self):
        gx, gy, gw, gh = self.regions["全界面"]
        return (
            int(gx + gw * 0.52),
            int(gy),
            int(gw * 0.48),
            int(gh * 0.20),
        )

    def hide_cr_overlay_for_capture(self):
        try:
            state = {
                "geometry": self.geometry(),
                "topmost": self.attributes("-topmost"),
            }
            self.ui_call(self.withdraw)
            self.ui_call(self.update_idletasks)
            time.sleep(0.6)
            return state
        except Exception:
            return None

    def restore_cr_overlay_after_capture(self, state):
        try:
            time.sleep(3.0)

            def restore():
                try:
                    self.deiconify()
                    if state and state.get("geometry"):
                        self.geometry(state["geometry"])
                    if state and "topmost" in state:
                        self.attributes("-topmost", state["topmost"])
                    self.update_idletasks()
                except Exception:
                    pass

            self.ui_call(restore)
        except Exception:
            pass

    def save_cr_debug_capture(self, image_bgr, reason):
        try:
            local_time = time.localtime()
            date_dir = os.path.join(DIAGNOSTICS_DIR, time.strftime("%Y-%m-%d", local_time))
            os.makedirs(date_dir, exist_ok=True)
            base_name = f"{time.strftime('%Y%m%d_%H%M%S', local_time)}_cr_region_{self.sanitize_diagnostic_token(reason)}"
            raw_path = os.path.join(date_dir, base_name + "_raw.png")
            if cv2.imwrite(raw_path, image_bgr):
                self.log(f"[诊断] 已保存CR区域截图: {raw_path}")

            mask = self.make_yellow_digit_mask(image_bgr)
            components = []
            if mask is not None:
                mask_path = os.path.join(date_dir, base_name + "_mask.png")
                cv2.imwrite(mask_path, mask)
                try:
                    num_labels, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
                    for label_id in range(1, num_labels):
                        x, y, w, h, area = stats[label_id]
                        components.append({
                            "x": int(x),
                            "y": int(y),
                            "w": int(w),
                            "h": int(h),
                            "area": int(area),
                        })
                except Exception:
                    pass

            meta_path = os.path.join(date_dir, base_name + "_candidates.json")
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "reason": reason,
                        "raw_path": raw_path,
                        "shape": list(image_bgr.shape) if image_bgr is not None else None,
                        "components": components,
                    },
                    f,
                    indent=4,
                    ensure_ascii=False,
                )
        except Exception as e:
            self.log(f"[诊断] 保存CR区域截图失败: {e}")

    def load_cr_digit_templates(self):
        digit_templates = []
        for digit in range(10):
            path = os.path.join(APP_DIR, "images", "cr_credits", f"{digit}.png")
            tpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if tpl is None:
                continue
            digit_templates.append((str(digit), tpl))
        return digit_templates

    def recognize_cr_digits_from_region(self, region_bgr):
        color_value = self.recognize_cr_digits_by_yellow_mask(region_bgr)
        if color_value is not None:
            return color_value

        digit_templates = self.load_cr_digit_templates()
        if not digit_templates:
            return None

        gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
        candidates = []
        scales = [0.18, 0.20, 0.22, 0.24, 0.26, 0.30, 0.34, 0.38, 0.42, 0.46, 0.50, 0.55, 0.65, 0.75, 0.85, 0.95, 1.0]

        for digit, tpl in digit_templates:
            for scale in scales:
                try:
                    scaled = tpl if scale == 1.0 else cv2.resize(tpl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                except Exception:
                    continue

                th, tw = scaled.shape[:2]
                if th < 5 or tw < 3 or th > gray.shape[0] or tw > gray.shape[1]:
                    continue

                res = cv2.matchTemplate(gray, scaled, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res >= 0.64)
                for pt in zip(*loc[::-1]):
                    x, y = int(pt[0]), int(pt[1])
                    score = float(res[y, x])
                    candidates.append({
                        "digit": digit,
                        "x": x,
                        "y": y,
                        "w": tw,
                        "h": th,
                        "score": score,
                    })

        if not candidates:
            return None

        candidates.sort(key=lambda item: item["score"], reverse=True)
        selected = []
        for cand in candidates:
            duplicate = False
            for old in selected:
                x_overlap = max(0, min(cand["x"] + cand["w"], old["x"] + old["w"]) - max(cand["x"], old["x"]))
                y_overlap = max(0, min(cand["y"] + cand["h"], old["y"] + old["h"]) - max(cand["y"], old["y"]))
                overlap_area = x_overlap * y_overlap
                min_area = min(cand["w"] * cand["h"], old["w"] * old["h"])
                if min_area > 0 and overlap_area / min_area > 0.35:
                    duplicate = True
                    break
            if not duplicate:
                selected.append(cand)

        selected.sort(key=lambda item: item["x"])
        if len(selected) < 3:
            return None

        digits = "".join(item["digit"] for item in selected)
        try:
            return int(digits)
        except Exception:
            return None

    def make_yellow_digit_mask(self, image_bgr):
        try:
            hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, np.array([20, 80, 100]), np.array([45, 255, 255]))
            return mask
        except Exception:
            return None

    def classify_cr_digit_component(self, component_mask):
        best_digit = None
        best_score = -1.0
        h, w = component_mask.shape[:2]
        if h <= 0 or w <= 0:
            return None

        comp = (component_mask > 0).astype(np.uint8)
        if self.count_mask_holes(comp) >= 2:
            return "8"
        for digit in range(10):
            path = os.path.join(APP_DIR, "images", "cr_credits", f"{digit}.png")
            tpl_bgr = cv2.imread(path, cv2.IMREAD_COLOR)
            if tpl_bgr is None:
                continue
            tpl_mask = self.make_yellow_digit_mask(tpl_bgr)
            if tpl_mask is None:
                tpl_gray = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)
                _, tpl_mask = cv2.threshold(tpl_gray, 180, 255, cv2.THRESH_BINARY)
            resized = cv2.resize(tpl_mask, (w, h), interpolation=cv2.INTER_AREA)
            tmpl = (resized > 0).astype(np.uint8)
            intersection = int(np.logical_and(comp, tmpl).sum())
            union = int(np.logical_or(comp, tmpl).sum())
            score = intersection / union if union else 0.0
            if score > best_score:
                best_score = score
                best_digit = str(digit)

        if best_score < 0.22:
            return None
        return best_digit

    def count_mask_holes(self, mask01):
        try:
            mask = (mask01 > 0).astype(np.uint8) * 255
            inv = cv2.bitwise_not(mask)
            h, w = inv.shape[:2]
            flood = inv.copy()
            cv2.floodFill(flood, np.zeros((h + 2, w + 2), np.uint8), (0, 0), 0)
            num_labels, _, stats, _ = cv2.connectedComponentsWithStats(flood, connectivity=8)
            holes = 0
            for label_id in range(1, num_labels):
                area = int(stats[label_id, cv2.CC_STAT_AREA])
                if area >= 4:
                    holes += 1
            return holes
        except Exception:
            return 0

    def recognize_cr_digits_by_yellow_mask(self, region_bgr):
        mask = self.make_yellow_digit_mask(region_bgr)
        if mask is None:
            return None

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        components = []
        img_h, img_w = mask.shape[:2]
        for label_id in range(1, num_labels):
            x, y, w, h, area = stats[label_id]
            if area < 20 or h < 14 or w < 4:
                continue
            if h > img_h * 0.95 or w > img_w * 0.4:
                continue
            components.append((int(x), int(y), int(w), int(h), int(area)))

        if not components:
            return None

        components.sort(key=lambda item: item[4], reverse=True)
        digit_height = components[0][3]
        filtered = []
        for x, y, w, h, area in components:
            if h < digit_height * 0.45:
                continue
            filtered.append((x, y, w, h, area))

        filtered.sort(key=lambda item: item[0])
        digits = []
        for x, y, w, h, _ in filtered:
            pad = 2
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(mask.shape[1], x + w + pad)
            y2 = min(mask.shape[0], y + h + pad)
            digit = self.classify_cr_digit_component(mask[y1:y2, x1:x2])
            if digit is not None:
                digits.append(digit)

        if len(digits) < 3:
            return None

        try:
            return int("".join(digits))
        except Exception:
            return None

    def read_current_cr_value(self):
        region = self.get_cr_capture_region()
        overlay_state = None
        try:
            overlay_state = self.hide_cr_overlay_for_capture()
            screen_bgr = self.capture_region(region)
            cr_anchor = self.find_image_in_screen(
                screen_bgr,
                "CRPointSmall.png",
                region=region,
                threshold=0.62,
                fast_mode=True,
            ) or self.find_image_in_screen(
                screen_bgr,
                "CRPoint.png",
                region=region,
                threshold=0.62,
                fast_mode=True,
            )

            if cr_anchor:
                local_x = max(0, int(cr_anchor[0] - region[0]) + 22)
                local_y = max(0, int(cr_anchor[1] - region[1]) - 45)
                local_w = min(screen_bgr.shape[1] - local_x, 420)
                local_h = min(screen_bgr.shape[0] - local_y, 100)
                roi = screen_bgr[local_y:local_y + local_h, local_x:local_x + local_w]
            else:
                roi = screen_bgr

            value = self.recognize_cr_digits_from_region(roi)
            if value is not None:
                return value

            self.save_cr_debug_capture(roi, "recognition_failed")
            self.capture_failure_snapshot("cr_value_recognition_failed", module_name="cr")
            return None
        except Exception as e:
            self.log(f"读取CR点异常: {e}")
            self.capture_failure_snapshot("cr_value_read_exception", module_name="cr", details={"exception": str(e)})
            return None
        finally:
            self.restore_cr_overlay_after_capture(overlay_state)

    def record_cr_value(self, phase, laps_delta, lap_seconds):
        value = self.read_current_cr_value()
        if value is None:
            self.log(f"CR记录失败: {phase}")
            self.update_cr_status_labels(None, None, None, None)
            return False

        session = getattr(self, "cr_session", None)
        if session is None:
            session = {
                "start_cr": None,
                "last_cr": None,
                "total_delta": 0,
                "total_laps": 0,
                "records": [],
            }
            self.cr_session = session

        if session["start_cr"] is None:
            session["start_cr"] = value
            session["last_cr"] = value
            delta = 0
        else:
            last_value = session["last_cr"] if session["last_cr"] is not None else value
            delta = max(0, value - last_value)
            session["last_cr"] = value
            session["total_delta"] = max(0, value - session["start_cr"])
            session["total_laps"] += max(0, laps_delta)

        per_lap = None
        per_hour = None
        if laps_delta > 0 and delta > 0:
            per_lap = delta / laps_delta
            per_hour = per_lap * 3600 / max(1, lap_seconds)

        session["records"].append({
            "phase": phase,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cr": value,
            "delta": delta,
            "total_delta": session["total_delta"],
            "total_laps": session["total_laps"],
            "per_lap": per_lap,
            "per_hour": per_hour,
        })

        self.update_cr_status_labels(value, session["total_delta"], per_lap, per_hour)
        if per_lap is not None and per_hour is not None:
            self.log(f"CR记录[{phase}]: 当前 {value:,}，本周期 +{delta:,}，约 {int(per_lap):,}/圈，约 {int(per_hour):,}/小时。")
        else:
            self.log(f"CR记录[{phase}]: 当前 {value:,}。")
        return True

    def logic_cr_grind_until_target(self, target_cr):
        car_type = self.get_cr_shortfall_car_type()
        settlement_laps = self.get_cr_shortfall_settlement_laps()
        car_profile = self.get_cr_car_profile_by_type(car_type)
        self.config["cr_shortfall_car_type"] = car_type
        self.config["cr_shortfall_settlement_laps"] = settlement_laps
        self.save_runtime_config()

        self.log(
            f"CR兜底启动：车辆 {car_profile['label']}，周期结算 {settlement_laps} 圈，"
            f"目标 {int(target_cr):,} CR。"
        )

        current_cr = self.read_current_cr_value()
        if current_cr is not None and current_cr >= target_cr:
            self.log(f"CR兜底：当前 {current_cr:,} CR 已达标。")
            return True

        while self.is_running:
            if self.should_abort_for_process_loss({"phase": "cr_shortfall_loop"}):
                return False

            cr_retries = self.get_cr_step_retry_count()
            if not self.execute_verified_step("CR兜底进入赛事页", self.enter_cr_event_page, retry_count=cr_retries):
                return False
            if not self.execute_verified_step("CR兜底选择车辆", lambda: self.select_cr_race_car(car_profile), retry_count=cr_retries):
                return False
            if not self.execute_verified_step("CR兜底开始赛事并开启自动驾驶", self.start_cr_race_and_autodrive, retry_count=cr_retries):
                return False
            if not self.wait_cr_lap_period(car_profile, settlement_laps):
                return False
            if not self.execute_verified_step("CR兜底周期退出赛事", self.exit_cr_race_for_settlement, retry_count=cr_retries):
                return False

            self.record_cr_value("CR不足兜底结算", settlement_laps, car_profile["lap_seconds"])
            current_cr = self.read_current_cr_value()
            if current_cr is None:
                self.log("CR兜底：结算后无法读取 CR，停止兜底。")
                return False
            if current_cr >= target_cr:
                self.log(f"CR兜底：当前 {current_cr:,} CR，达到目标 {int(target_cr):,} CR。")
                return True

            self.log(f"CR兜底：当前 {current_cr:,} CR，仍不足 {int(target_cr):,} CR，继续刷 CR。")

        return False

    def logic_cr_grind(self):
        car_profile = self.get_cr_car_profile()
        settlement_enabled = self.is_cr_settlement_enabled()
        settlement_laps = self.get_cr_settlement_laps()
        self.config["cr_car_type"] = car_profile["type"]
        self.config["cr_settlement_enabled"] = settlement_enabled
        self.config["cr_settlement_laps"] = settlement_laps
        self.save_runtime_config()

        self.log(
            f"刷CR点启动：车辆 {car_profile['label']}，"
            f"{'周期结算 ' + str(settlement_laps) + ' 圈' if settlement_enabled else '不启用周期结算'}。"
        )

        while self.is_running:
            if self.should_abort_for_process_loss({"phase": "cr_grind_loop"}):
                return False

            cr_retries = self.get_cr_step_retry_count()
            if not self.execute_verified_step("刷CR进入赛事页", self.enter_cr_event_page, retry_count=cr_retries):
                return False
            if not self.execute_verified_step("刷CR选择车辆", lambda: self.select_cr_race_car(car_profile), retry_count=cr_retries):
                return False
            if not self.execute_verified_step("刷CR开始赛事并开启自动驾驶", self.start_cr_race_and_autodrive, retry_count=cr_retries):
                return False

            if not settlement_enabled:
                self.log("未启用周期结算，将持续刷圈直到手动停止。")
                while self.is_running:
                    if self.should_abort_for_process_loss({"phase": "cr_grind_no_settlement"}):
                        return False
                    self.wait_cr_lap_period(car_profile, 1)
                return True

            if not self.wait_cr_lap_period(car_profile, settlement_laps):
                return False
            if not self.execute_verified_step("刷CR周期退出赛事", self.exit_cr_race_for_settlement, retry_count=cr_retries):
                return False
            self.record_cr_value("周期结算", settlement_laps, car_profile["lap_seconds"])

        return True
    #===============================
    #---自动超级抽奖-----
    #===============================
    

if __name__ == "__main__":
    app = FH_UltimateBot()
    app.mainloop()
