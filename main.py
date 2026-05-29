import sys
import os
# ====== 【修复 OMP 冲突的核心代码】 ======
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
# =======================================
import json
import time
import shutil
import ctypes
import subprocess
import webbrowser
# ====== 【新增】：启动前置环境检测 (防闪退机制) ======
def check_windows_dependencies():
    if sys.platform != "win32":
        return
    missing_dlls = []
    # OpenCV(cv2) 等图像识别库强依赖微软 VC++ 2015-2022 运行库
    required_dlls = ["vcruntime140.dll", "msvcp140.dll", "vcruntime140_1.dll"]
    
    for dll in required_dlls:
        try:
            # 尝试静默加载该运行库，如果系统里没有，就会触发 OSError
            ctypes.WinDLL(dll)
        except OSError:
            missing_dlls.append(dll)
            
    if missing_dlls:
        msg = (
            f"警告：系统缺失以下关键运行库，大概率会导致程序闪退或图像识别失败：\n\n"
            f"{', '.join(missing_dlls)}\n\n"
            f"这是因为您的电脑缺少微软 C++ 运行环境。\n"
            f"请搜索下载【微软常用运行库合集】或【VC++ 2015-2022】安装后重试。\n\n"
            f"点击“确定”强行继续运行（如果闪退请安装运行库）。"
        )
        # 0x30 = MB_ICONWARNING (黄色警告图标), 0x0 = MB_OK (只有确定按钮)
        ctypes.windll.user32.MessageBoxW(0, msg, "缺少运行库拦截提示", 0x30 | 0x0)
# 在导入耗性能的大型模块前，第一时间执行拦截检测
check_windows_dependencies()
# ===================================================
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
import win32gui
import pickle
import threading



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
# 【新增 config 目录路径】
CONFIG_DIR = os.path.join(APP_DIR, "config")
USER_CONFIG_FILE = os.path.join(APP_DIR, "config.json")      # <--- 全面替换为 config.json
LOG_FILE = os.path.join(APP_DIR, "bot_log.txt")
CACHE_DIR = os.path.join(APP_DIR, "cache")
TEMPLATE_CACHE_FILE = os.path.join(CACHE_DIR, "template_cache.pkl")
TEMPLATE_META_FILE = os.path.join(CACHE_DIR, "template_meta.json")
CURRENT_VERSION = "1.1.5.2"
def auto_extract_configs():
    os.makedirs(CONFIG_DIR, exist_ok=True)
    
    # 向下兼容，自动重命名并迁移老版本 bot_config
    old_configs = [
        os.path.join(APP_DIR, "bot_config.json"),
        os.path.join(APP_DIR, "bot-config.json"),
        os.path.join(CONFIG_DIR, "bot-config.json"),
        os.path.join(CONFIG_DIR, "bot_config.json"),
        os.path.join(CONFIG_DIR, "config.json")
    ]
    for old_path in old_configs:
        if os.path.exists(old_path):
            try:
                if not os.path.exists(USER_CONFIG_FILE):
                    shutil.move(old_path, USER_CONFIG_FILE)
                else:
                    os.remove(old_path)
            except Exception:
                pass
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
        self.title(f"FH6Auto by YSTO v{CURRENT_VERSION}")
        self.geometry("1800x800")
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
        self.sc_count = 0
        self.global_loop_current = 0

        self.template_cache = {}
        self.scaled_template_cache = {}
        self.file_template_cache = {}
        self.last_positions = {}
        self.support_win = None
        self.edge_template_cache = {}
        self.scaled_edge_template_cache = {}

        self.init_regions()
        
        # 【优化加载速度】：将IO提取与图像缓存的加载/生成放到后台线程，避免阻塞主界面启动
        # 增加模型释放步骤
        def background_init():
            auto_extract_images()
            
            self.prepare_template_cache()
            #self.use_ocr = self.config.get("use_ocr", True)
            #if self.use_ocr:
            #    self.init_ocr_engine()
        threading.Thread(target=background_init, daemon=True).start()
        
        #加载配置文件
        auto_extract_configs()  
        self.load_config()

        self.setup_ui()
        self.start_hotkey_listener()
        self.update_skill_grid()
        self.center_window()
        
        self.log("免责声明：本脚本仅供 Python 自动化技术交流与学习使用。请勿用于商业盈利或破坏游戏平衡，因使用本脚本造成的账号封禁等损失，由使用者自行承担。")
        self.log("工具运行目录不要有中文")
        self.log("默认刷图车辆：【斯巴鲁Impreza 22B-STi Version】【调校S2  900】【保持默认涂装】【收藏车辆】")
        self.log("启动前先将键盘设置为【英文键盘】")
        self.log("游戏设置为【自动转向】【自动挡】，游戏语言设置为【简体中文】")
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
        gx, gy, gw, gh = self.regions["全界面"]
        x = gx + (gw - w) // 2
        y = gy + (gh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
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
        # 1. 直接使用内置字典作为“绝对底本”（最安全，无视打包丢文件问题）
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
            "share_code": "890169683", 
            "auto_restart": False,
            "restart_cmd": "start steam://run/2483190", 
            "sell_mode": 1 
        }
        ext_path = USER_CONFIG_FILE
        # 2. 读取用户的 config.json，并与底本合并（自动补全缺失项）
        if os.path.exists(ext_path):
            try:
                with open(ext_path, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                    self.config.update(user_config) 
            except Exception as e:
                self.log(f"用户 config.json 损坏，已自动恢复默认配置。")
                
        # 3. 将最新、最完整的配置重新写回外置文件
        try:
            with open(ext_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
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
            if hasattr(self, "opt_sell_mode"):
                val = self.opt_sell_mode.get()
                if "模式1" in val:
                    self.config["sell_mode"] = 1
                else:
                    self.config["sell_mode"] = 2
        except Exception:
            pass

        self.config["chk_1"] = self.var_chk1.get()
        self.config["chk_2"] = self.var_chk2.get()
        self.config["chk_3"] = self.var_chk3.get()
        self.config["chk_4"] = self.var_chk4.get()
        self.config["auto_restart"] = self.var_auto_restart.get()
        self.config["restart_cmd"] = self.le_restart_cmd.get().strip()
        try:
            if hasattr(self, "entry_calc_a"):
                self.config["calc_a"] = self.entry_calc_a.get().strip()
                self.config["calc_b"] = self.entry_calc_b.get().strip()
                self.config["calc_c"] = self.entry_calc_c.get().strip()
        except Exception:
            pass
        try:
            with open(USER_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"保存配置失败: {e}")

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
        self.entry_race.delete(0, "end")
        self.entry_race.insert(0, str(final_races_per_loop))
        
        self.entry_car.delete(0, "end")
        self.entry_car.insert(0, str(cars_per_loop))
        
        self.entry_cj.delete(0, "end")
        self.entry_cj.insert(0, str(cars_per_loop))
        
        self.entry_sc.delete(0, "end")
        self.entry_sc.insert(0, str(cars_per_loop))
        
        self.entry_global_loop.delete(0, "end")
        self.entry_global_loop.insert(0, str(final_loops))

        self.log(f"✅计算完成: 总计需{total_cars}车, 共跑图{total_races}次。分配为: {final_loops} 个大循环, 每轮跑图 {final_races_per_loop} 次, 动作 {cars_per_loop} 辆。")
        self.save_config()

    # ==========================================
    # --- UI 布局设计 ---
    # ==========================================
    def setup_ui(self):
        self.top_container = ctk.CTkFrame(self, fg_color="transparent")
        self.top_container.pack(fill="x", padx=18, pady=(18, 10))

        self.config_frame = ctk.CTkFrame(self.top_container, fg_color="transparent")
        self.config_frame.pack(fill="x")

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

        def create_next_step(parent, var_checked, def_step, box_h=300):
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
            self.config.get("race_count", 99),
        )
        self.entry_share = ctk.CTkEntry(box_race, width=130, justify="center", placeholder_text="蓝图数字代码")
        self.entry_share.insert(0, self.config.get("share_code", "890169683"))
        self.entry_share.pack(pady=4)

        self.next_frame1, self.entry_next1, self.chk1 = create_next_step(
            self.config_frame, self.var_chk1, self.config.get("next_1", 2)
        )

        box_car, self.btn_car, self.entry_car, self.lbl_car = create_box(
            self.config_frame,
            "2. 批量买车",
            "开始",
            lambda: self.start_pipeline("buy"),
            "#2EA043",
            self.config.get("buy_count", 30),
        )
        self.entry_car.bind("<KeyRelease>", self.sync_buy_to_sell)

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

        self.entry_cj = ctk.CTkEntry(left_cj, width=95, height=34, justify="center", corner_radius=8)
        self.entry_cj.insert(0, str(self.config.get("cj_count", 30)))
        self.entry_cj.pack(pady=5)

        self.lbl_cj = ctk.CTkLabel(
            left_cj,
            text=f"执行: 0 / {self.config.get('cj_count', 30)}",
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
        # ====== 【新增】：移除车辆模式下拉选择 ======
        self.opt_sell_mode = ctk.CTkOptionMenu(
            box_sc,
            values=["模式1: 识图移除模式", "模式2: 移除最近添加"],
            width=180,
            height=28,
            corner_radius=6,
            font=ctk.CTkFont(size=12),
            fg_color="#D97706",
            button_color="#B96705",
            button_hover_color="#995704"
        )
        # 读取配置，默认选模式1
        saved_mode = self.config.get("sell_mode", 1)
        if str(saved_mode) == "1" or "模式1" in str(saved_mode):
            self.opt_sell_mode.set("模式1: 识图移除模式")
        else:
            self.opt_sell_mode.set("模式2: 移除最近添加")
            
        self.opt_sell_mode.pack(pady=4)
        # ==========================================
        self.next_frame4, self.entry_next4, self.chk4 = create_next_step(
        self.config_frame, self.var_chk4, self.config.get("next_4", 1)
        )
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
        self.var_auto_restart = ctk.BooleanVar(value=self.config.get("auto_restart", True))
        self.cb_auto_restart = ctk.CTkCheckBox(self.global_settings_frame, text="游戏闪退自动重启（测试）", variable=self.var_auto_restart)
        self.cb_auto_restart.pack(side="left", padx=(10, 20))
        ctk.CTkLabel(self.global_settings_frame, text="启动命令(CMD):").pack(side="left", padx=(10, 5))
        self.le_restart_cmd = ctk.CTkEntry(self.global_settings_frame, width=250, height=28)
        self.le_restart_cmd.insert(0, self.config.get("restart_cmd", "start steam://run/2483190"))
        self.le_restart_cmd.pack(side="left", padx=(0, 20))
        
        # =================================


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
        # ==========================================
        #ctk.CTkLabel(self.global_settings_frame, text="图片原宽（不要修改）:").pack(side="left", padx=(10, 5))
        #self.entry_base_w = ctk.CTkEntry(self.global_settings_frame, width=70, height=28, justify="center")
        #self.entry_base_w.insert(0, str(self.config.get("base_width", 2560)))
        #self.entry_base_w.pack(side="left", padx=(0, 20))

        self.entry_next1.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next1, 2))
        self.entry_next2.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next2, 3))
        self.entry_next3.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next3, 4))
        self.entry_next4.bind("<FocusOut>", lambda e: self.normalize_step_entry(self.entry_next4, 1))

        if not self.entry_sc.get().strip():
            self.entry_sc.insert(0, "30")

        # === 全新的横向迷你UI设计 ===
        self.mini_frame = ctk.CTkFrame(self, fg_color="#1E1E1E", corner_radius=10)

        # 1. 日志区 (最左侧，占据主要伸缩空间)
        self.mini_log_box = ctk.CTkTextbox(self.mini_frame, state="disabled", wrap="word", font=ctk.CTkFont(size=13), fg_color="#2B2B2B")
        self.mini_log_box.pack(side="left", fill="both", expand=True, padx=(10, 5), pady=10)

        # 2. 信息区 (垂直排列任务状态和耗时)
        self.mini_info_frame = ctk.CTkFrame(self.mini_frame, fg_color="transparent")
        self.mini_info_frame.pack(side="left", fill="y", padx=5, pady=10)

        self.lbl_mini_task = ctk.CTkLabel(self.mini_info_frame, text="当前任务: 等待中", font=ctk.CTkFont(size=14, weight="bold"), text_color="#3498DB")
        self.lbl_mini_task.pack(pady=(5, 2), anchor="w")

        self.lbl_mini_prog = ctk.CTkLabel(self.mini_info_frame, text="任务进度: 0 / 0", font=ctk.CTkFont(size=13))
        self.lbl_mini_prog.pack(pady=2, anchor="w")

        self.lbl_mini_loop = ctk.CTkLabel(self.mini_info_frame, text="大循环: 0 / 0", font=ctk.CTkFont(size=13))
        self.lbl_mini_loop.pack(pady=2, anchor="w")

        self.lbl_mini_time = ctk.CTkLabel(self.mini_info_frame, text="总耗时: 00:00:00", font=ctk.CTkFont(size=13))
        self.lbl_mini_time.pack(pady=2, anchor="w")
        # 3. 按钮区 (靠右排列)
        self.btn_mini_stop = ctk.CTkButton(self.mini_frame, text="⏸ 停止 (F8)", fg_color="#DA3633", hover_color="#B02A37", width=90, font=ctk.CTkFont(weight="bold"), command=self.stop_all)
        self.btn_mini_stop.pack(side="left", fill="y", padx=5, pady=10)

        self.btn_mini_support = ctk.CTkButton(self.mini_frame, text="❤ 支持", fg_color="#F97316", hover_color="#EA580C", width=60, font=ctk.CTkFont(weight="bold"), command=self.open_support_window)
        self.btn_mini_support.pack(side="left", fill="y", padx=(5, 10), pady=10)


        self.bottom_frame = ctk.CTkFrame(self, fg_color="transparent", height=200)
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

        self.log_box = ctk.CTkTextbox(
            self.bottom_frame,
            state="disabled",
            wrap="word",
            corner_radius=12,
            height=120,
            font=ctk.CTkFont(size=18),
        )
        self.log_box.pack(side="left", fill="both", expand=True, padx=8)

        self.btn_support = ctk.CTkButton(
            self,
            text="❤ 支持作者 / 检查更新",
            fg_color="#F97316",
            hover_color="#EA580C",
            height=42,
            corner_radius=12,
            font=ctk.CTkFont(weight="bold", size=15),
            command=self.open_support_window,
        )
        self.btn_support.pack(fill="x", padx=18, pady=(6, 12))
        self.sync_buy_to_sell()

        #ocr加载 
    
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
    def start_pipeline(self, start_step):
        if self.is_running:
            return

        self.is_running = True
        self.save_config()

        # 隐藏大窗的所有元素
        self.config_frame.pack_forget()
        self.global_settings_frame.pack_forget()
        self.calc_frame.pack_forget()
        self.top_container.pack_forget()
        if hasattr(self, "bottom_frame"):
            self.bottom_frame.pack_forget()
        self.btn_support.pack_forget()

        # 显示新的迷你横向 UI
        self.mini_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # ====== 计算 15% 高度 40% 宽度 ======
        last_x, last_y, last_w, last_h = self.regions["全界面"]
        if last_w <= 0: last_w = self.winfo_screenwidth()
        if last_h <= 0: last_h = self.winfo_screenheight()

        calc_w = int(last_w * 0.40)
        calc_h = int(last_h * 0.15)
        # 设置一个兜底最小值，防止分辨率过低时文字挤压导致崩溃
        calc_w = max(calc_w, 650)
        calc_h = max(calc_h, 150)

        pos_x = last_x + last_w - calc_w - 20
        pos_y = last_y + 20

        self.attributes("-topmost", True)
        self.geometry(f"{calc_w}x{calc_h}+{pos_x}+{pos_y}")
        
        # 启动计时器
        self.start_time = time.time()
        self.update_timer()

        
        self.update_running_ui("初始化中...")
        self.race_counter = 0
        self.car_counter = 0
        self.cj_counter = 0
        self.sc_count = 0
        self.global_loop_current = 0

        def runner():
            if not self.check_and_focus_game():
                self.stop_all()
                return

            steps = ["race", "buy", "cj", "sell"]
            curr_idx = steps.index(start_step)

            try:
                total_loops = int(self.entry_global_loop.get())
            except Exception:
                total_loops = self.config.get("global_loops", 10)
            self.global_loop_current = 1
            if hasattr(self, "lbl_mini_loop"):
                self.ui_call(self.lbl_mini_loop.configure, text=f"大循环: {self.global_loop_current} / {total_loops}")

            # 【新增】：全局连续失败计数器
            continuous_failures = 0 
            # 【你可以修改这里】：设置全局允许的最大连续恢复次数（比如 3 次）
            MAX_RECOVERIES = 10 

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
                    elif step_name == "sell":
                        # ====== 【新增】：判断下拉框的模式 ======
                        sell_mode = self.opt_sell_mode.get()
                        if "模式1" in sell_mode:
                            success = self.find_and_remove_consumable_car(int(self.entry_sc.get()))
                        else:
                            success = self.sell_consumable_car(int(self.entry_sc.get()))
                        # =========================================
                except Exception as e:
                    self.log(f"执行模块 {step_name} 时异常: {e}")
                    success = False

                if not self.is_running:
                    break

                if not success:
                    continuous_failures += 1
                    
                    # 检查是否超过最大容忍次数
                    if continuous_failures > MAX_RECOVERIES:
                        self.log(f"!!! 警告：连续 {continuous_failures} 次触发断点恢复仍未能解决问题！")
                        self.log("为防止游戏陷入死循环，强制终止当前所有任务，请人工检查游戏状态。")
                        break # 直接跳出 while，停止脚本
                        
                    self.log(f"正在进行全局恢复 (第 {continuous_failures}/{MAX_RECOVERIES} 次允许的重试)...")
                    
                    if self.attempt_recovery():
                        continue # 恢复成功，回到 while 顶部再次尝试这个任务
                    else:
                        self.log("致命错误：连退回菜单/重启也失败了，彻底停止。")
                        break
                else:
                    # 只要这一个大步骤成功跑完了，就把连续失败次数清零，奖励它继续跑！
                    continuous_failures = 0
                #v1.0.1
                # ====== 核心流转与无限循环逻辑 ======
                next_idx = curr_idx + 1 # 默认前往下一步
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

            self.stop_all()

        self.current_thread = threading.Thread(target=runner, daemon=True)
        self.current_thread.start()

    def stop_all(self):
        if not self.is_running:
            return

        self.is_running = False

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
            self.calc_frame.pack_forget()
            
            # 1. 铺设最外层大容器
            self.top_container.pack(fill="x", padx=18, pady=(18, 10))
            
            # 2. 依次按顺序塞入三个模块，完美保证从上到下的顺序！
            self.config_frame.pack(fill="x")
            self.global_settings_frame.pack(fill="x", pady=(15, 0))
            self.calc_frame.pack(fill="x", pady=(10, 0))
            
            # 3. 铺设底部的日志和按钮
            if hasattr(self, "bottom_frame"):
                self.bottom_frame.pack(fill="both", expand=True, padx=18, pady=(6, 12))
            self.btn_support.pack(fill="x", padx=18, pady=(6, 12))
            
            # 恢复窗口原本的状态
            self.btn_stop.configure(text="等待指令 (F8)", fg_color="#3A3A3A", hover_color="#4A4A4A")
            self.attributes("-topmost", False)
            self.geometry("1800x800")
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
                    # 1. 更新识图区域为游戏实际窗口区域（识图必须在游戏窗口内）
                    client_rect = win32gui.GetClientRect(hwnd)
                    pt = win32gui.ClientToScreen(hwnd, (0, 0))
                    gx, gy = pt[0], pt[1]
                    gw, gh = client_rect[2], client_rect[3]
                    self.update_regions_by_window(gx, gy, gw, gh)

                    # 2. 获取该窗口所在的物理显示器边界
                    MONITOR_DEFAULTTONEAREST = 2
                    hMonitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                    class RECT(ctypes.Structure):
                        _fields_ = [
                            ("left", ctypes.c_long), 
                            ("top", ctypes.c_long), 
                            ("right", ctypes.c_long), 
                            ("bottom", ctypes.c_long)
                        ]
                    class MONITORINFO(ctypes.Structure):
                        _fields_ = [
                            ("cbSize", ctypes.c_ulong), 
                            ("rcMonitor", RECT), 
                            ("rcWork", RECT), 
                            ("dwFlags", ctypes.c_ulong)
                        ]
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    
                    if ctypes.windll.user32.GetMonitorInfoW(hMonitor, ctypes.byref(mi)):
                        mx = mi.rcMonitor.left
                        my = mi.rcMonitor.top
                        mw = mi.rcMonitor.right - mi.rcMonitor.left
                        mh = mi.rcMonitor.bottom - mi.rcMonitor.top
                    else:
                        # 兜底：如果获取不到屏幕边界，就用游戏窗口边界
                        mx, my, mw, mh = gx, gy, gw, gh

                    # ====== 【修改】：小窗口精准吸附所在显示器的右上角 ======
                    def snap_to_game():
                        if self.is_running:
                            calc_w = int(mw * 0.40)
                            calc_h = int(mh * 0.15)
                            calc_w = max(calc_w, 650)
                            calc_h = max(calc_h, 150)
                            
                            # 放置在当前显示器的右上角（预留20像素边距）
                            pos_x = mx + mw - calc_w - 20
                            pos_y = my + 20
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

            if self.find_image("anna.png", region=self.regions["左下"], threshold=0.5):
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

    def recover_to_menu(self):
        self.log("开始尝试退回主菜单 (强制ESC兜底)...")
        return self.enter_menu()

    def is_in_menu(self):    
        return self.find_image_gray(
            "collectionjournal.png",
            region=self.regions["左"],
            threshold=0.70,
            fast_mode=True
        )
    def enter_menu(self):
        self.log("正在尝试进入主菜单 (按ESC验证)...")
  
        # 连续尝试 60 次，大概花费 40~60 秒
        for i in range(60):
            if not self.is_running:
                return False
                

            pos_menu = self.find_image_gray("collectionjournal.png", region=self.regions["左"], threshold=0.70, fast_mode=True)
            
            if pos_menu:
                self.log(f"成功定位到菜单锚点！({i + 1}/60)")
                time.sleep(0.5)
                return True
                
            self.log(f"未在主菜单，按下 ESC... ({i + 1}/60)")
            self.hw_press("esc")
            # 给游戏一点动画加载时间
            time.sleep(1.0)
            
        self.log("60 次 ESC 尝试均未进入菜单，请检查游戏状态。")
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

                if max_val >= threshold:
                    pos = (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
                    self.last_positions[template_path] = pos
                    # 【新增】：在基础图像查找中增加详细日志返回
                    self.log(f"[ImageMatch] 命中: {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return pos

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
                loc = np.where(res_main >= threshold)
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
                    sub_score = cv2.minMaxLoc(res_sub)[1]
                    if sub_score >= threshold:
                        # 【新增】：在组合图像查找中增加详细日志返回
                        main_score = res_main[y, x]
                        self.log(f"[ComboMatch] 命中: {main_path}+{sub_path} | 主图得分: {main_score:.3f} | 元素得分: {sub_score:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            x + w_m // 2 + (region[0] if region else 0),
                            y + h_m // 2 + (region[1] if region else 0),
                        )
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
                    # 【新增】：打印稳定版组合匹配的详细得分
                    self.log(f"[StableMatch] 命中: {main_path}+{sub_path} | 主图: {main_score:.3f} (需>{verify_threshold}) | 元素: {sub_score:.3f} (需>{sub_threshold})")
                    return (cx, cy)

            return None

        except Exception as e:
            self.log(f"find_image_with_element_stable 识别报错: {e}")
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

                # 用彩色主模板先找候选，门槛放低
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_c, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= main_threshold)

                # ==========================================
                # 【核心魔法】：强制从左到右、从上到下排序！
                # 保证在有多个相同目标时，绝对按顺序点击！
                # ==========================================
                points = list(zip(*loc[::-1]))
                points.sort(key=lambda p: (p[1] // 50, p[0])) 

                checked_points = set()

                for pt in points:
                    x, y = pt

                    # 去重，避免同一辆车计算多次
                    key = (x // 10, y // 10)
                    if key in checked_points:
                        continue
                    checked_points.add(key)

                    roi_bgr = screen_bgr[y:y + h_m, x:x + w_m]
                    roi_gray = screen_gray[y:y + h_m, x:x + w_m]
                    roi_edge = screen_edge[y:y + h_m, x:x + w_m]

                    if roi_bgr.shape[:2] != main_tpl_c.shape[:2]:
                        continue

                    # 四维打分系统 (抗 HDR 核心)
                    color_score = self.match_template_score(roi_bgr, main_tpl_c)
                    gray_score = self.match_template_score(roi_gray, main_tpl_gray)
                    edge_score = self.match_template_score(roi_edge, main_tpl_edge)

                    roi_center = self.crop_center_ratio(roi_bgr, ratio=0.6)
                    tpl_center = self.crop_center_ratio(main_tpl_c, ratio=0.6)
                    center_score = self.match_template_score(roi_center, tpl_center)

                    # 标签匹配 (NEW 标签或作者点赞标签)
                    pad = 5
                    sub_roi = screen_bgr[
                        max(0, y - pad):min(screen_bgr.shape[0], y + h_m + pad),
                        max(0, x - pad):min(screen_bgr.shape[1], x + w_m + pad),
                    ]
                    like_score = self.match_template_score(sub_roi, sub_tpl_c)

                    if like_score < like_threshold:
                        continue

                    # 综合计算总分
                    final_score = (
                        color_score * 0.30 +
                        gray_score * 0.20 +
                        edge_score * 0.20 +
                        center_score * 0.15 +
                        like_score * 0.15
                    )

                    curr_pos = (
                        x + w_m // 2 + (region[0] if region else 0),
                        y + h_m // 2 + (region[1] if region else 0),
                    )

                    # 只要及格，立刻返回（因为已经排过序了，第一个及格的一定是左上角的第一个目标）
                    if final_score >= final_threshold:
                        self.log(
                            f"[MultiMatch] 锁定目标: {main_path}+{sub_path} | "
                            f"综合: {final_score:.3f} | 彩色: {color_score:.3f} | "
                            f"灰度: {gray_score:.3f} | 边缘: {edge_score:.3f} | "
                            f"中心: {center_score:.3f} | 标签: {like_score:.3f}"
                        )
                        return curr_pos

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
                    # 【新增】：打印快速匹配模式得分
                    main_score = res_main[y, x]
                    self.log(f"[FastMatch] 命中: {main_path}+{sub_path} | 主图: {main_score:.3f} (需>{threshold}) | 元素: {max_val_sub:.3f} (需>{sub_threshold})")
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
                time.sleep(0.05)

        return None

    def load_template_transparent(self, template_path):
        """专门加载带有 Alpha 透明通道的图片"""
        actual_path = get_img_path(template_path)
        cache_key = ("transparent", actual_path)
        if not hasattr(self, "template_transparent_cache"):
            self.template_transparent_cache = {}
        if cache_key in self.template_transparent_cache:
            return self.template_transparent_cache[cache_key]
            
        # 注意这里的 cv2.IMREAD_UNCHANGED，它会保留透明通道 (BGRA)
        tpl = cv2.imread(actual_path, cv2.IMREAD_UNCHANGED)
        if tpl is not None:
            self.template_transparent_cache[cache_key] = tpl
        return tpl
    def find_image_transparent(self, template_path, region=None, threshold=0.70, fast_mode=True):
        """带透明通道的匹配：彻底无视透明背景，只匹配图像主体"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            tpl_bgra = self.load_template_transparent(template_path)
            
            if tpl_bgra is None:
                return None
            # 如果图片没有透明通道(不是4通道)，降级为普通匹配
            if tpl_bgra.shape[2] != 4:
                return self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                # 对带有透明通道的原图进行缩放
                if scale == 1.0:
                    tpl_scaled = tpl_bgra.copy()
                else:
                    tpl_scaled = cv2.resize(tpl_bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                h, w = tpl_scaled.shape[:2]
                if h < 5 or w < 5 or h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                    continue
                # 分离出 BGR 色彩层 和 Alpha 透明遮罩层
                tpl_bgr = tpl_scaled[:, :, :3]
                alpha_mask = tpl_scaled[:, :, 3]
                                # 核心魔法：带 mask 的匹配！透明区域不参与算分！
                res = cv2.matchTemplate(screen_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    # 【新增】：带透明通道的匹配日志
                    self.log(f"[AlphaMatch] 命中(无视背景): {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
            return None
        except Exception as e:
            self.log(f"find_image_transparent 异常: {e}")
            return None
    def wait_for_image_transparent(self, template_path, region=None, threshold=0.70, timeout=30, interval=0.4, fast_mode=True):
        """等待带有透明背景的图片"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_transparent(template_path, region, threshold, fast_mode)
            if pos:
                return pos
            time.sleep(interval)
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

    # ==========================================
    # --- 【终极安全锁 V5.1】：排他 + 右下角调校精准狙击 + 强制从左到右 ---
    # ==========================================
    def find_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65):
        if not self.is_running: return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)

            scales_to_try = self.get_scales_to_try(fast_mode=True)

            for scale in scales_to_try:
                main_tpl_bgr, _ = self.get_scaled_template(main_path, scale)
                anti_tpl_bgr, _ = self.get_scaled_template(anti_path, scale)

                if main_tpl_bgr is None or anti_tpl_bgr is None: continue
                
                main_tpl_gray = cv2.cvtColor(main_tpl_bgr, cv2.COLOR_BGR2GRAY)
                h_m, w_m = main_tpl_bgr.shape[:2]
                h_a, w_a = anti_tpl_bgr.shape[:2]

                if h_m < 10 or w_m < 10 or h_m > screen_bgr.shape[0] or w_m > screen_bgr.shape[1]:
                    continue

                # 1. 基础彩色初筛
                res_main = cv2.matchTemplate(screen_bgr, main_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                loc = np.where(res_main >= main_threshold)

                
                points = list(zip(*loc[::-1]))
                # 强制按 X 坐标（从左到右）优先排序，无视上下排
                points.sort(key=lambda p: (p[0] // 50, p[1]))

                checked = set()
                for pt in points:
                    x, y = pt
                    if (x // 10, y // 10) in checked: continue
                    checked.add((x // 10, y // 10))

                    base_score = res_main[y, x]
                    
                    roi_bgr = screen_bgr[y:y+h_m, x:x+w_m]
                    roi_gray = screen_gray[y:y+h_m, x:x+w_m]
                    if roi_bgr.shape[:2] != main_tpl_bgr.shape[:2]: continue

                    # ==================================
                    # 防线 1: 排他校验
                    # ==================================
                    pad_anti = 10
                    roi_y1, roi_y2 = max(0, y - pad_anti), min(screen_bgr.shape[0], y + h_m + pad_anti)
                    roi_x1, roi_x2 = max(0, x - pad_anti), min(screen_bgr.shape[1], x + w_m + pad_anti)
                    anti_roi = screen_bgr[roi_y1:roi_y2, roi_x1:roi_x2]

                    if anti_roi.shape[0] >= h_a and anti_roi.shape[1] >= w_a:
                        res_anti = cv2.matchTemplate(anti_roi, anti_tpl_bgr, cv2.TM_CCOEFF_NORMED)
                        _, anti_score, _, _ = cv2.minMaxLoc(res_anti)
                        if anti_score >= anti_threshold:
                            self.log(f"[排他拦截]: 发现 NEW 标签 ({anti_score:.2f})，放弃该目标。")
                            continue

                    # ==================================
                    # 防线 2: 顶部文字
                    # ==================================
                    top_h = int(h_m * 0.25)
                    tpl_top = main_tpl_gray[:top_h, :]
                    
                    score_top = 0.0
                    pad_slide = 5 
                    if top_h > pad_slide*2 and w_m > pad_slide*2:
                        tpl_top_core = tpl_top[pad_slide:-pad_slide, pad_slide:-pad_slide]
                        search_top = roi_gray[:int(h_m * 0.35), :]
                        if search_top.shape[0] >= tpl_top_core.shape[0] and search_top.shape[1] >= tpl_top_core.shape[1]:
                            res_top = cv2.matchTemplate(search_top, tpl_top_core, cv2.TM_CCOEFF_NORMED)
                            _, score_top, _, _ = cv2.minMaxLoc(res_top)

                    # ==================================
                    # 防线 3: 【右下角】
                    # ==================================
                    bottom_h = int(h_m * 0.25)
                    right_w = int(w_m * 0.35)
                    tpl_pi_box = main_tpl_bgr[h_m - bottom_h:, w_m - right_w:]

                    score_bot = 0.0
                    if bottom_h > pad_slide*2 and right_w > pad_slide*2:
                        tpl_pi_core = tpl_pi_box[pad_slide:-pad_slide, pad_slide:-pad_slide]
                        search_y1 = h_m - int(h_m * 0.35)
                        search_x1 = w_m - int(w_m * 0.45)
                        search_bot = roi_bgr[search_y1:, search_x1:]
                        
                        if search_bot.shape[0] >= tpl_pi_core.shape[0] and search_bot.shape[1] >= tpl_pi_core.shape[1]:
                            res_bot = cv2.matchTemplate(search_bot, tpl_pi_core, cv2.TM_CCOEFF_NORMED)
                            _, score_bot, _, _ = cv2.minMaxLoc(res_bot)

                    if base_score >= 0.76 and score_top >= 0.75 and score_bot >= 0.85:
                        self.log(f"[终极安全-通过]: 锁定目标！总分:{base_score:.3f} | 顶部车名:{score_top:.2f} | 右下调校:{score_bot:.2f}")
                        return (x + w_m // 2 + (region[0] if region else 0), y + h_m // 2 + (region[1] if region else 0))
                    else:
                        pass # 静默拦截，继续寻找下一个坐标

            return None
        except Exception as e:
            self.log(f"ultimate_safe 异常: {e}")
            return None
    def wait_for_image_ultimate_safe(self, main_path, anti_path, region=None, main_threshold=0.80, anti_threshold=0.65, timeout=3, interval=0.2):
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_ultimate_safe(main_path, anti_path, region, main_threshold, anti_threshold)
            if pos: return pos
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
    def find_image_gray(self, template_path, region=None, threshold=0.75, fast_mode=True):
        """纯灰度UI查找，支持多分辨率缩放"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            for scale in scales_to_try:
                tpl_gray = self.load_template_gray(template_path)
                if tpl_gray is None:
                    continue
                if scale != 1.0:
                    tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                h, w = tpl_gray.shape[:2]
                if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                    continue
                res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    # 【新增】：灰度图匹配的得分日志
                    self.log(f"[GrayMatch] 命中: {template_path} | 灰度得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                    return (
                        max_loc[0] + w // 2 + (region[0] if region else 0),
                        max_loc[1] + h // 2 + (region[1] if region else 0),
                    )
            return None
        except Exception as e:
            self.log(f"find_image_gray 异常: {e}")
            return None
    def find_any_image_gray(self, image_list, region=None, threshold=0.75, fast_mode=True):
        """纯灰度多图查找，支持多分辨率缩放"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)
            
            for img_path in image_list:
                for scale in scales_to_try:
                    tpl_gray = self.load_template_gray(img_path)
                    if tpl_gray is None:
                        continue
                    if scale != 1.0:
                        tpl_gray = cv2.resize(tpl_gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                    h, w = tpl_gray.shape[:2]
                    if h < 5 or w < 5 or h > screen_gray.shape[0] or w > screen_gray.shape[1]:
                        continue
                    res = cv2.matchTemplate(screen_gray, tpl_gray, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)
                    if max_val >= threshold:
                        # 【新增】：多张灰度图匹配的得分日志
                        self.log(f"[GrayMatchAny] 命中: {img_path} | 灰度得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc[0] + w // 2 + (region[0] if region else 0),
                            max_loc[1] + h // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_any_image_gray 异常: {e}")
            return None

    def wait_for_any_image_gray(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.3, fast_mode=True):
        """等待多张灰度图中的任意一张出现（已补全 fast_mode 参数）"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_any_image_gray(image_list, region=region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos
            
            # 安全等待机制，防止卡死
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None
    def wait_for_image_gray(self, template_path, region=None, threshold=0.75, timeout=30, interval=0.3, fast_mode=True):
        """等待单张灰度图出现（已补全 fast_mode 参数）"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_image_gray(template_path, region=region, threshold=threshold, fast_mode=fast_mode)
            if pos:
                return pos
            
            # 安全等待机制
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None

    def find_any_image_transparent(self, image_list, region=None, threshold=0.70, fast_mode=True):
        """查找多张带透明通道的图片中的任意一张"""
        if not self.is_running:
            return None
        try:
            screen_bgr = self.capture_region(region)
            scales_to_try = self.get_scales_to_try(fast_mode=fast_mode)

            for template_path in image_list:
                tpl_bgra = self.load_template_transparent(template_path)
                if tpl_bgra is None:
                    continue
                
                # 如果图片没有透明通道，降级为普通匹配
                if tpl_bgra.shape[2] != 4:
                    pos = self.find_image_in_screen(screen_bgr, template_path, region, threshold, fast_mode)
                    if pos: return pos
                    continue

                for scale in scales_to_try:
                    if scale == 1.0:
                        tpl_scaled = tpl_bgra.copy()
                    else:
                        tpl_scaled = cv2.resize(tpl_bgra, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

                    h, w = tpl_scaled.shape[:2]
                    if h < 5 or w < 5 or h > screen_bgr.shape[0] or w > screen_bgr.shape[1]:
                        continue

                    tpl_bgr = tpl_scaled[:, :, :3]
                    alpha_mask = tpl_scaled[:, :, 3]

                    res = cv2.matchTemplate(screen_bgr, tpl_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha_mask)
                    _, max_val, _, max_loc = cv2.minMaxLoc(res)

                    if max_val >= threshold:
                        # 【新增】：多张带透明通道的匹配日志
                        self.log(f"[AlphaMatchAny] 命中(无视背景): {template_path} | 得分: {max_val:.3f} (阈值 {threshold}) | 缩放比: {scale:.3f}")
                        return (
                            max_loc[0] + w // 2 + (region[0] if region else 0),
                            max_loc[1] + h // 2 + (region[1] if region else 0),
                        )
            return None
        except Exception as e:
            self.log(f"find_any_image_transparent 异常: {e}")
            return None

    def wait_for_any_image_transparent(self, image_list, region=None, threshold=0.70, timeout=30, interval=0.4, fast_mode=True):
        """等待带有透明背景的多张图片中的任意一张出现"""
        start = time.time()
        while self.is_running and time.time() - start < timeout:
            pos = self.find_any_image_transparent(image_list, region, threshold, fast_mode)
            if pos:
                return pos
            
            sleep_end = time.time() + interval
            while self.is_running and time.time() < sleep_end:
                time.sleep(0.05)
        return None
    def wait_for_any_image(self, image_list, region=None, threshold=0.75, timeout=30, interval=0.4, fast_mode=True, log_text=None):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
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

    def wait_for_image_with_element(self, main_path, sub_path, region=None, threshold=0.85, timeout=30, interval=0.4, fast_mode=True):
        start = time.time()

        while self.is_running and time.time() - start < timeout:
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

        time.sleep(0.8)


        pos_el = self.wait_for_image_gray(
            "eventlab.png",
            region=self.regions["全界面"],
            threshold=0.7,
            timeout=5,
            interval=0.25,
            fast_mode=True
        )
    
        if not pos_el:
            self.log("未找到 eventlab")
            return False

        self.game_click(pos_el)
        time.sleep(1.2)

        pos_yg = self.wait_for_image_gray(
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

        pos_ck = self.wait_for_image_gray(
            "VEI.png",
            region=self.regions["下"],
            threshold=0.75,
            timeout=20,
            interval=1.0,
            fast_mode=True
        )
        if not pos_ck:
            self.log("链接超时")
            return False

        self.hw_press("enter")
        time.sleep(2.0)
        self.hw_press("enter")
        time.sleep(2.0)

        pos_target = self.wait_for_image_with_element_multi(
            "skillcar.png",
            "liketag.png",
            region=self.regions["全界面"],
            fast_mode=True,
            main_threshold=0.75,
            like_threshold=0.7,
            final_threshold=0.7,
            timeout=2,
            interval=0.25
        )

        if not pos_target:
            self.log("未找到带 liketag 的目标车辆，重新选品牌...")
            self.hw_press("backspace")
            time.sleep(1.2)

            found_brand = False
            for _ in range(3):
                if not self.is_running:
                    return False

                pos_brand = self.wait_for_image_gray("skillcarbrand.png", region=self.regions["全界面"], threshold=0.8, timeout=1.2, interval=0.2, fast_mode=True)
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

            for _ in range(20):
                if not self.is_running:
                    return False

                pos_target = self.wait_for_image_with_element_multi(
                    "skillcar.png",
                    "liketag.png",
                    region=self.regions["全界面"],
                    main_threshold=0.75,
                    like_threshold=0.7,
                    final_threshold=0.7,
                    timeout=2,
                    interval=0.25,
                    fast_mode=True
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

            self.log(f"跑图 {self.race_counter + 1}/{target_count}: 找赛事起点...")

            pos = None
            for _ in range(120):
                if not self.is_running:
                    return False

                pos = self.wait_for_any_image_gray(
                    ["start.png", "startw.png"],
                    region=self.regions["左下"],
                    threshold=0.75,
                    timeout=0.7,
                    interval=0.2,
                    fast_mode=True
                )
                if pos:
                    break

                self.hw_press("down")
                time.sleep(0.25)

            if not pos:
                self.log("找不到赛事起点，退出跑图。")
                return False

            self.game_click(pos)
            time.sleep(4.0)
            self.hw_key_down("w")
            self.hw_key_down("up") 
            
            # 初始化各类计时器
            race_start_time = time.time()  # 新增：记录跑图发车时间
            last_like_chk = time.time()
            last_chk = 0
            finished = False
            timeout_triggered = False      # 新增：标记是否触发了120秒超时

            while self.is_running:
                now = time.time()
                
                # 【新增逻辑】：120秒超时防卡死检测
                if now - race_start_time > 120.0:
                    self.log("跑图超时(已超过120秒)！触发强制重开赛事逻辑...")
                    timeout_triggered = True
                    break
                
                # 【原生逻辑】：每隔3秒识别一次 likeauthor.png
                if now - last_like_chk >= 3.0:
                    pos_like = self.find_any_image_gray(["likeauthor.png", "dislikeauthor.png"], region=self.regions["中间"], threshold=0.70)
                    if pos_like:
                        self.log("识别到点赞作界面，执行回车确认！")
                        self.hw_press("enter")
                    last_like_chk = now
                    
                # 【原生逻辑】：每1秒检测一次重新开始(正常完赛)
                if now - last_chk >= 1.0:
                    found_restart = self.find_image_gray("restart.png", region=self.regions["下"], threshold=0.75, fast_mode=True)
                    if found_restart:
                        finished = True
                        break
                    last_chk = now
                    
                time.sleep(0.3)
                
            # 无论正常结束还是超时，都必须先松开油门和方向
            self.hw_key_up("w")
            self.hw_key_up("up")

            if not self.is_running:
                return False

            # ====== 【新增】：执行超时重置操作 ======
            if timeout_triggered:
                time.sleep(0.5)
                self.hw_press("esc")
                time.sleep(1.5)  # 等待菜单动画加载
                
                # 寻找并点击 restarta.png
                pos_restarta = self.wait_for_image_gray("restarta.png", region=self.regions["全界面"], threshold=0.70, timeout=4.0, interval=0.3, fast_mode=True)
                if pos_restarta:
                    self.log("找到 restarta.png，点击重开赛事...")
                    self.game_click(pos_restarta)
                    time.sleep(1.0)
                    self.hw_press("enter")  # 地平线重开赛事通常有确认弹窗，按一次回车确认
                    time.sleep(4.0)         # 等待黑屏重加载动画
                else:
                    self.log("未找到 restarta.png，尝试直接继续...")
                    
                # 【关键】：直接跳过下方的结算流程，回到最外层 while 重新找 start.png（并且本次不计入 race_counter）
                continue
            # ========================================

            if not finished:
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

        self.update_running_ui("批量买车", self.car_counter, target_count)

        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        pos_collectionjournal = self.wait_for_image_transparent(
            "collectionjournal.png",
            region=self.regions["左"],
            threshold=0.7,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos_collectionjournal:
            self.log("未找到收集簿")
            return False

        self.game_click(pos_collectionjournal, double=True)
        time.sleep(1.0)


        pos_masterexplorer = self.wait_for_image(
            "masterexplorer.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=30,
            interval=0.4,
            fast_mode=True
        )
        if not pos_masterexplorer:
            self.log("未找到探索")
            return False

        self.game_click(pos_masterexplorer, double=True)
        time.sleep(0.6)

        pos_carcollection = self.wait_for_image_transparent(
            "carcollection.png",
            region=self.regions["全界面"],
            threshold=0.75,
            timeout=30,
            interval=0.3,
            fast_mode=True
        )
        if not pos_carcollection:
            self.log("未找到车辆收集")
            return False

        self.game_click(pos_carcollection, double=True)
        time.sleep(1.0)

        self.hw_press("backspace")
        time.sleep(0.5)

        brand_pos = None
        for _ in range(5):
            if not self.is_running:
                return False
                

            brand_pos = self.wait_for_any_image_gray(
                ["CCbrand.png", "CCbrand-b.png"],
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
            self.log("未找到品牌")
            return False

        self.game_click(brand_pos)
        time.sleep(0.8)
        self.hw_press("down")
        time.sleep(0.4)

        pos_22b = self.wait_for_image(
            "consumablecar.png",
            region=self.regions["全界面"],
            threshold=0.90,
            timeout=8,
            interval=0.3,
            fast_mode=False
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
            self.move_to_game_coord(5, 5)
            self.hw_press("down")
            time.sleep(0.2)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
            self.hw_press("enter")
            time.sleep(0.6)
            self.move_to_game_coord(5, 5)
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
    # ==========================================
    # --- 模块：抽奖 ---
    # ==========================================
    def logic_super_wheelspin(self, target_count):
        if self.cj_counter >= target_count:
            return True

        self.update_running_ui("超级抽奖", self.cj_counter, target_count)
        # 【新增】：初始化记忆页码
        if not hasattr(self, 'memory_car_page'):
            self.memory_car_page = 0
        self.log("准备验证/进入菜单...")
        if not self.enter_menu():
            return False

        self.log("进入车辆与收藏...")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_image(
            "BNandUC.png",
            region=self.regions["左"],
            threshold=0.70,
            timeout=15,
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


        pos_bs = self.wait_for_any_image_gray(
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
        self.log("进入车辆界面...")
        time.sleep(0.5)

        while self.cj_counter < target_count:
            if not self.is_running:
                return False
            self.log("进入我的车辆.")
            self.hw_press("enter")
            time.sleep(2.0)
            self.hw_press("backspace")
            time.sleep(1.0)

            brand_pos = None
            for _ in range(30):
                if not self.is_running:
                    return False

                brand_pos = self.wait_for_any_image_gray(
                    ["CCbrand.png", "CCbrand-b.png"],
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
                self.log("选品牌失败")
                return False

            self.game_click(brand_pos)
            time.sleep(1.0)
            jump_pages = max(0, self.memory_car_page - 1)
            
            if jump_pages > 0:
                self.log(f"智能记忆触发：快速跳过前 {jump_pages} 页...")
                for _ in range(jump_pages):
                    if not self.is_running: return False
                    for _ in range(4):
                        self.hw_press("right", delay=0.06)
                        time.sleep(0.1)
                    time.sleep(0.15) # 给一点点动画缓冲时间
            pos_target = None
            found_car = False
            current_page = jump_pages # 记录当前所在的真实页码
            
            # 最大翻页次数扣除已经跳过的页数
            for _ in range(85 - jump_pages):
                if not self.is_running:
                    return False
                pos_target = self.wait_for_image_with_element_multi(
                    "newCC.png",
                    "newcartag.png",
                    region=self.regions["全界面"],
                    main_threshold=0.75,   # 防HDR核心：第一道门槛放低
                    like_threshold=0.75,
                    final_threshold=0.70,
                    timeout=1.5,
                    interval=0.2,
                    fast_mode=True
                )
                
                if pos_target:
                    self.game_click(pos_target)
                    found_car = True
                    # 记住这次找到车是在哪一页
                    self.memory_car_page = current_page 
                    self.log(f"锁定目标车辆！已记录当前页码: {current_page}")
                    break
                    
                # 翻下一页
                for _ in range(4):
                    self.hw_press("right", delay=0.06)
                    time.sleep(0.1)
                time.sleep(0.4)
                current_page += 1
            if not found_car:
                self.log("列表中未找到目标车辆，重置记忆页码。")
                self.memory_car_page = 0 # 没找到说明车刷完了，清零记忆
                return False
            time.sleep(1.2)
            self.log("尝试寻找'上车'按钮...")

            pos_rc = None
            pos_rc = self.wait_for_image_gray("rc.png", region=self.regions["全界面"], threshold=0.70, timeout=0.5, interval=0.1, fast_mode=True)
            
            if pos_rc:
                self.log("点击上车")
                self.game_click(pos_rc)
                time.sleep(2.0)  # 点击后等待上车加载
            else:
                self.log("回车上车")
                self.hw_press("enter")
                time.sleep(1.0)
                self.hw_press("enter")
                time.sleep(1.0)


            pos_sjy = None
            for _ in range(20):
                if not self.is_running:
                    return False

                pos_sjy = self.find_any_image_gray(["UandT-w.png", "UandT-b.png"], region=self.regions["左下"], threshold=0.70)
                if pos_sjy:
                    break

                self.hw_press("esc")
                time.sleep(0.5)

            if not pos_sjy:
                self.log("找不到升级页面")
                return False

            self.game_click(pos_sjy)
            time.sleep(0.5)

            pos_cls = self.wait_for_any_image_gray(
                ["clsldcnw.png", "clsldcnb.png"],
                region=self.regions["左下"],
                threshold=0.70,
                timeout=20
            )
            if not pos_cls:
                self.log("未找到车辆熟练度")
                return False
            self.game_click(pos_cls)
            time.sleep(1.5)

            pos_exp = self.wait_for_any_image(
                ["EXPwU.png"],
                region=self.regions["左"],
                threshold=0.75,
                timeout=1.5,
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

                spne_found = self.find_image_gray("SPNE.png", region=self.regions["全界面"], threshold=0.70)
                
                if spne_found:
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
                self.update_running_ui("超级抽奖", self.cj_counter, target_count)

            self.hw_press("esc")
            time.sleep(1.2)
            self.hw_press("esc")
            time.sleep(0.8)
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
    def sell_consumable_car(self, target_count):
        if self.sc_count >= target_count:
            return True

        self.update_running_ui("移除车辆", self.sc_count, target_count)

        self.log("准备验证/进入菜单！！！使用前请人工核验到正常移除车辆再进行自动化移除处理")
        if not self.enter_menu():
            return False

        self.log("进入车辆与收藏！！！使用前请人工核验到正常移除车辆再进行自动化移除处理")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_image("BNandUC.png", region=self.regions["左"], threshold=0.70, timeout=12, interval=0.3, fast_mode=True)
        if not pos_buycar:
            self.log("未识别到 购买新车与二手车")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = self.wait_for_any_image(["buyandsell-w.png", "buyandsell-b.png"], region=self.regions["上"], threshold=0.75, timeout=40, interval=0.5, fast_mode=True)
        if not pos_bs:
            self.log("未找到购买与出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)

        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        self.hw_press("enter")  # 进入我的车辆
        time.sleep(2.0)
        #选择一辆收藏
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

        pos = self.wait_for_image("rc.png", region=self.regions["全界面"], threshold=0.65, timeout=5, interval=0.2, fast_mode=True)
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

        found = False
        for i in range(60):
            if not self.is_running:
                return False

            pos = self.wait_for_any_image(["buyandsell-b.png", "buyandsell-w.png"], region=self.regions["上"], threshold=0.70, timeout=0.8, interval=0.2, fast_mode=True)
            if pos:
                self.log(f"第 {i + 1} 次检测到购买与出售，进入车辆界面")
                self.hw_press("enter")
                found = True
                break
            self.log(f"第 {i + 1} 次未检测到购买与出售，等待后重试")
            time.sleep(1.0)
        if not found:
            self.log("60次内未找到购买与出售")
            return False
        
        time.sleep(1.5)
        # 切换排序：最近获得
        self.hw_press("x")
        time.sleep(0.5)
        #鼠标复位
        self.move_to_game_coord(5, 5)
        #选择最近获得
        self.log("切换到 最近获得 的排序...")
        for _ in range(6):
            if not self.is_running:
                return False
            self.hw_press("down")
            time.sleep(0.25)
        time.sleep(0.2)
        self.hw_press("enter")
        time.sleep(1.2)
        self.log("回到最近获得的前面")
        # 回到列表首项
        self.hw_press("backspace")
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(1.5)

        self.log("开始删除最近获得的车辆！！！请人工确认是否移除")

        while self.sc_count < target_count:
            self.log(f"is_running = {self.is_running}")
            if not self.is_running:
                return False
            # 进入当前车辆
            self.hw_press("enter")
            time.sleep(1.2)
            #跳到从车库移除
            for _ in range(6):
                if not self.is_running:
                    return False
                self.hw_press("down")
                time.sleep(0.2)
            self.hw_press("enter")
            time.sleep(0.5)
            #向下选择“嗯”
            self.hw_press("down")
            time.sleep(0.3)
            #确认“嗯”
            self.hw_press("enter")
            time.sleep(0.8)
            self.sc_count += 1
            self.log(f"已尝试删除车辆 {self.sc_count}/{target_count}")

        for _ in range(3):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(1.0)

        return True
    
    def find_and_remove_consumable_car(self, target_count):
        if self.sc_count >= target_count:
            return True
        
        self.update_running_ui("移除车辆", self.sc_count, target_count)

        self.log("准备验证/进入菜单！！！使用前请人工核验到正常移除车辆再进行自动化移除处理")
        if not self.enter_menu():
            return False

        self.log("进入车辆与收藏！！！使用前请人工核验到正常移除车辆再进行自动化移除处理")
        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        pos_buycar = self.wait_for_image("BNandUC.png", region=self.regions["左"], threshold=0.70, timeout=12, interval=0.3, fast_mode=True)
        if not pos_buycar:
            self.log("未识别到 购买新车与二手车")
            return False

        self.game_click(pos_buycar)
        time.sleep(0.8)
        self.hw_press("enter")
        time.sleep(5)

        pos_bs = self.wait_for_any_image(["buyandsell-w.png", "buyandsell-b.png"], region=self.regions["上"], threshold=0.75, timeout=40, interval=0.5, fast_mode=True)
        if not pos_bs:
            self.log("未找到购买与出售")
            return False

        self.game_click(pos_bs)
        time.sleep(1.0)

        self.hw_press("pagedown", delay=0.15)
        time.sleep(1.0)

        self.hw_press("enter")  # 进入我的车辆
        time.sleep(2.0)
        #选择一辆收藏
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

        pos = self.wait_for_image("rc.png", region=self.regions["全界面"], threshold=0.65, timeout=5, interval=0.2, fast_mode=True)
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

        found = False
        for i in range(30):
            if not self.is_running:
                return False

            pos = self.wait_for_any_image(["buyandsell-b.png", "buyandsell-w.png"], region=self.regions["上"], threshold=0.70, timeout=0.8, interval=0.2, fast_mode=True)
            if pos:
                self.log(f"第 {i + 1} 次检测到购买与出售，进入车辆界面")
                self.hw_press("enter")  #进入我的车辆
                time.sleep(1.5)
                found = True
                break
            self.log(f"第 {i + 1} 次未检测到购买与出售，等待后重试")
            time.sleep(1.0)
        if not found:
            self.log("30次内未找到购买与出售")
            return False
        #筛选
        self.hw_press("y")
        time.sleep(1.0)
        for _ in range(2):
            self.hw_press("down", delay=0.06)
            time.sleep(0.2)
        time.sleep(0.5)
        self.hw_press("enter")
        time.sleep(1.0)
        self.hw_press("esc")
        time.sleep(1.0)


        #切换到消耗品品牌
        self.log("切换到消耗品品牌...")
        self.hw_press("backspace")
        brand_pos = None
        for _ in range(5):
            if not self.is_running:
                return False
                

            brand_pos = self.wait_for_any_image_gray(
                ["CCbrand.png", "CCbrand-b.png"],
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
            self.log("未找到品牌")
            return False

        self.game_click(brand_pos)
        time.sleep(0.8)

        self.log("开始删除最近获得的车辆！！！请人工确认是否移除")
        
        not_found_pages = 0  
        while self.sc_count < target_count:
            if not self.is_running:
                return False
            self.log(f"正在使用 3模式 严格扫描当前页面... (连续未找到: {not_found_pages}/5)")
            
            # 【使用终极安全锁】：2张图，4道防线，绝不乱删
            pos_target = self.wait_for_image_ultimate_safe(
                main_path="removecarobject.png",  # 你要删的车的截图
                anti_path="newcartag.png",        # NEW标签截图
                region=self.regions["全界面"],
                main_threshold=0.77,              # 极高的基础相似度要求
                anti_threshold=0.65,              # 极度敏感的 NEW 标签排斥
                timeout=3.0,
                interval=0.2
            )
            
            if not pos_target:
                not_found_pages += 1
                if not_found_pages >= 2:
                    self.log("=连续翻找 2 页仍未搜索到目标车辆！视为车辆已全部清理完毕。")
                    self.log("主动结束清理任务，准备进入下一步骤...")
                    break  # 直接跳出循环，结束当前任务
                    
                self.log(f"当前页面未找到，向右翻页寻找... (第 {not_found_pages} 次翻页)")
                for _ in range(4):
                    self.hw_press("right", delay=0.06)
                    time.sleep(0.1)
                time.sleep(0.4)
                continue
            # ====== 找到了目标车辆，重置翻页计数器 ======
            not_found_pages = 0
            
            self.log("精准锁定目标车辆，执行点击...")
            self.game_click(pos_target)
            time.sleep(1.2) # 等待点击后的反应
            
            # ==========================================
            # 核心逻辑：寻找 removecar.png (从车库移除)
            # ==========================================
            self.log("寻找 '从车库移除' 按钮...")
            pos_remove = self.find_image_gray("removecar.png", region=self.regions["全界面"], threshold=0.75, fast_mode=True)
            
            if pos_remove:
                self.log("直接找到移除按钮，点击...")
                self.game_click(pos_remove)
            else:
                self.log("未直接找到移除按钮，按下 Enter 呼出菜单...")
                self.hw_press("enter")
                time.sleep(0.8) # 等待菜单弹出动画
                
                # 再次寻找
                pos_remove = self.find_image_gray("removecar.png", region=self.regions["全界面"], threshold=0.75, fast_mode=True)
                if pos_remove:
                    self.log("呼出菜单后找到移除按钮，点击...")
                    self.game_click(pos_remove)
                else:
                    self.log("仍未找到移除按钮，可能点错了/该车无法移除，按 ESC 放弃该车...")
                    self.hw_press("esc")
                    time.sleep(1.0)
                    self.hw_press("right") # 往右挪一格，防止死循环一直点这辆假车
                    time.sleep(1.2)
                    continue
                    
            time.sleep(0.8) # 等待“你确定要移除吗”的确认弹窗
            
            # 确认移除操作 (按向下选"嗯"，然后回车)
            self.log("确认移除...")
            self.hw_press("down")
            time.sleep(0.3)
            self.hw_press("enter")
            time.sleep(1.2)

            
            self.sc_count += 1
            self.update_running_ui("移除车辆", self.sc_count, target_count)
            self.log(f"成功移除车辆！当前进度: {self.sc_count}/{target_count}")

        # 循环结束，退回上一级
        for _ in range(3):
            if not self.is_running:
                return False
            self.hw_press("esc")
            time.sleep(1.0)

        return True
 
    #===============================
    #---自动超级抽奖-----
    #===============================
if __name__ == "__main__":
    app = FH_UltimateBot()
    app.mainloop()