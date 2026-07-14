"""Compact 390x275 glass dashboard for Codex Moon Dashboard."""

from __future__ import annotations

import math
import os
import json
import random
import tkinter as tk
from tkinter import colorchooser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageTk
except ImportError:  # pragma: no cover - install.ps1 installs Pillow.
    Image = None
    ImageChops = None
    ImageDraw = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None
    ImageTk = None

from data_provider import load_dashboard_data, mark_manually_dismissed


ROOT = Path(__file__).resolve().parents[1]
MOON_PATH = ROOT / "assets" / "moon-reference.png"
MOON_PHASE_DIR = ROOT / "assets" / "moon-phases"
MOON_FRAME_COUNT = 33
FONT = "Microsoft YaHei UI"
WIDTH = 390
HEIGHT = 275
HEADER_HEIGHT = 40
COLLAPSED_HEIGHT = 52
FRAME_MS = 25  # 40 FPS keeps shooting stars smooth while Codex is working.
CHROMA_KEY = "#ff00ff"
HEADER_RGB = (9, 36, 53)
BODY_RGB = (39, 56, 77)
BASE_RGB = BODY_RGB

TEXT = "#f1f5ff"
MUTED = "#d0daee"
FINE = "#b0c4df"
ACCENT = "#f08ab8"
CYAN = "#83dbe4"
GREEN = "#9be7c7"

# UI glass remains 20% opaque. The header uses the Codex Radar dark blue and
# the body uses the supplied #27384d blue-gray reference color.
GLASS_ALPHA = 51
HEADER_ALPHA = 230
MOON_ALPHA = 255
MOON_CONTRAST = 1.25
MOON_BRIGHTNESS = 0.74
WORK_BAR_ALPHA = 200
STAR_COUNT = 12
STAR_PERIOD = 9.0
STAR_ACTIVE_THRESHOLD = 0.35

STAR_POSITIONS = (
    (28, 18),
    (160, 16),
    (320, 18),
    (18, 72),
    (18, 150),
    (18, 230),
    (372, 72),
    (372, 150),
    (372, 230),
    (70, 260),
    (195, 260),
    (320, 260),
)
SETTINGS_PATH = Path.home() / ".codex" / "codex-moon-dashboard-settings.json"


def env_int(name: str, fallback: int) -> int:
    try:
        return int(os.environ.get(name, fallback))
    except (TypeError, ValueError):
        return fallback


LIFECYCLE_ID = os.environ.get("CODEX_LIFECYCLE_ID", "manual")
STARTED_AT_MS = env_int("CODEX_STARTED_AT_MS", 0)


def _font(size: int, weight: str = "normal") -> Tuple[str, int, str]:
    return (FONT, size, weight)


DEFAULT_SETTINGS = {
    "interface_r": BODY_RGB[0],
    "interface_g": BODY_RGB[1],
    "interface_b": BODY_RGB[2],
    "interface_alpha": int(round(GLASS_ALPHA / 255 * 100)),
    "background_r": BASE_RGB[0],
    "background_g": BASE_RGB[1],
    "background_b": BASE_RGB[2],
    "background_alpha": 100,
    "moon_alpha": 100,
    "moon_contrast": 100,
}


def _load_settings() -> Dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
            saved = json.load(handle)
        legacy = not isinstance(saved, dict) or saved.get("_version") != 2
        if isinstance(saved, dict):
            for key in settings:
                if key in saved:
                    value = float(saved[key])
                    if legacy and key == "interface_alpha" and value == GLASS_ALPHA:
                        value = DEFAULT_SETTINGS[key]
                    if key in {"interface_alpha", "background_alpha", "moon_alpha"} and value > 100:
                        value = value / 255 * 100
                    if key == "moon_contrast" and value > 100:
                        value = 100
                    settings[key] = value
    except (OSError, ValueError, TypeError):
        pass
    return settings


class MoonDashboard:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Codex Moon Dashboard")
        self.root.geometry("{}x{}+{}+{}".format(WIDTH, HEIGHT, 80, 110))
        self.root.resizable(False, False)
        self.root.overrideredirect(True)
        self.root.configure(bg=CHROMA_KEY)
        try:
            self.root.wm_attributes("-transparentcolor", CHROMA_KEY)
        except tk.TclError:
            pass
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.drag_origin = (0, 0)
        self.pinned = True
        self.closed = False
        self.data: Dict[str, Any] = {}
        self.background_photo: Optional[Any] = None
        self.moon_frame_cache: Dict[int, Any] = {}
        self.settings = _load_settings()
        self.settings_window: Optional[tk.Toplevel] = None
        self.settings_canvas: Optional[tk.Canvas] = None
        self.settings_surface_photo: Optional[Any] = None
        self.settings_close_item: Optional[int] = None
        self.setting_scales: Dict[str, tk.Scale] = {}
        self.settings_save_after: Optional[str] = None
        self.is_collapsed = False
        self._sync_settings()
        self.animation_time = 0.0
        self.shooting_star: Optional[Dict[str, float]] = None
        self.star_rng = random.Random(47)
        self.next_shooting_star_at = self.star_rng.uniform(2.8, 5.2)
        self.idle_star_strength = 0.0
        self.was_working = False

        self.canvas = tk.Canvas(
            self.root,
            width=WIDTH,
            height=HEIGHT,
            bg=CHROMA_KEY,
            bd=0,
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-1>", self._handle_press)
        self.canvas.bind("<ButtonRelease-1>", self._handle_release)
        self.canvas.bind("<B1-Motion>", self._drag_move)

        self.background_item = self.canvas.create_image(0, 0, anchor="nw")
        self._create_text_items()
        self._create_interaction_items()
        self.refresh()
        self.animate()

    def _sync_settings(self) -> None:
        def bounded(key: str, low: float, high: float) -> float:
            value = float(self.settings.get(key, DEFAULT_SETTINGS[key]))
            value = max(low, min(high, value))
            self.settings[key] = value
            return value

        self.interface_color = tuple(
            int(bounded(key, 0, 255)) for key in ("interface_r", "interface_g", "interface_b")
        )
        self.header_color = tuple(
            max(0, min(255, int(HEADER_RGB[index] + (self.interface_color[index] - BODY_RGB[index]) * 0.35)))
            for index in range(3)
        )
        self.interface_alpha = int(round(bounded("interface_alpha", 0, 100) * 255 / 100))
        self.background_color = tuple(
            int(bounded(key, 0, 255)) for key in ("background_r", "background_g", "background_b")
        )
        self.background_alpha = int(round(bounded("background_alpha", 0, 100) * 255 / 100))
        self.moon_alpha = int(round(bounded("moon_alpha", 0, 100) * 255 / 100))
        contrast_percent = bounded("moon_contrast", 0, 100)
        self.moon_contrast = 0.5 + contrast_percent / 100.0 * 0.75
        self.moon_frame_cache.clear()

    def _save_settings(self) -> None:
        self.settings_save_after = None
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(self.settings)
            payload["_version"] = 2
            with SETTINGS_PATH.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _on_setting_change(self, key: str, value: str) -> None:
        self.settings[key] = float(value)
        self._sync_settings()
        self._render_background()
        self._render_settings_surface()
        if self.settings_save_after is not None:
            self.root.after_cancel(self.settings_save_after)
        self.settings_save_after = self.root.after(250, self._save_settings)

    @staticmethod
    def _rgb_hex(rgb: Tuple[int, int, int]) -> str:
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    def _render_settings_surface(self) -> None:
        if self.settings_canvas is None or Image is None or ImageDraw is None or ImageTk is None:
            return
        width, height = 380, 590
        surface = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(surface)
        draw.rounded_rectangle(
            (3, 3, width - 4, height - 4),
            radius=20,
            fill=self.background_color + (255,),
            outline=(190, 220, 244, 255),
            width=1,
        )
        draw.rounded_rectangle(
            (3, 3, width - 4, 50),
            radius=20,
            fill=self.header_color + (255,),
        )
        draw.rectangle((3, 26, width - 4, 50), fill=self.header_color + (255,))
        draw.line((16, 50, width - 16, 50), fill=(1, 146, 173, 180), width=1)
        self.settings_surface_photo = ImageTk.PhotoImage(surface)
        self.settings_canvas.itemconfigure(self.settings_surface_item, image=self.settings_surface_photo)

    def _settings_drag_start(self, event: tk.Event) -> None:
        if event.y <= 50 and self.settings_window is not None:
            self.settings_drag_origin = (
                event.x_root - self.settings_window.winfo_x(),
                event.y_root - self.settings_window.winfo_y(),
            )

    def _settings_drag_move(self, event: tk.Event) -> None:
        if self.settings_window is None or event.y > 50:
            return
        x = event.x_root - self.settings_drag_origin[0]
        y = event.y_root - self.settings_drag_origin[1]
        self.settings_window.geometry("+{}+{}".format(x, y))

    def _settings_section(self, parent: tk.Frame, title: str, color_kind: Optional[str] = None) -> None:
        row = tk.Frame(parent, bg=self.settings_panel_bg)
        row.pack(fill="x", padx=12, pady=(5, 1))
        tk.Label(
            row,
            text=title,
            bg=self.settings_panel_bg,
            fg="#83dbe4",
            font=(FONT, 9, "bold"),
        ).pack(side="left")
        if color_kind:
            tk.Button(
                row,
                text="取色",
                command=lambda: self.pick_color(color_kind),
                bg=self._rgb_hex(self.header_color),
                fg="#f1f5ff",
                activebackground="#3b6985",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                padx=7,
                pady=1,
                font=(FONT, 8),
            ).pack(side="right")

    def _add_setting_scale(
        self,
        parent: tk.Frame,
        key: str,
        label: str,
        from_value: int,
        to_value: int,
    ) -> None:
        row = tk.Frame(parent, bg=self.settings_panel_bg)
        row.pack(fill="x", padx=12, pady=2)
        tk.Label(
            row,
            text=label,
            width=13,
            anchor="w",
            bg=self.settings_panel_bg,
            fg="#dce9f8",
            font=(FONT, 9),
        ).pack(side="left")
        scale = tk.Scale(
            row,
            from_=from_value,
            to=to_value,
            orient="horizontal",
            showvalue=True,
            resolution=1,
            length=235,
            bd=0,
            highlightthickness=0,
            troughcolor=self._rgb_hex(self.header_color),
            activebackground="#83dbe4",
            bg=self.settings_panel_bg,
            fg="#eff7ff",
            font=(FONT, 8),
            command=lambda value, setting_key=key: self._on_setting_change(setting_key, value),
        )
        scale.set(self.settings.get(key, DEFAULT_SETTINGS[key]))
        scale.pack(side="right", fill="x", expand=True)
        self.setting_scales[key] = scale

    def open_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            return

        window = tk.Toplevel(self.root)
        self.settings_window = window
        window.title("Codex 监控设置")
        window.overrideredirect(True)
        window.configure(bg=CHROMA_KEY)
        try:
            window.wm_attributes("-transparentcolor", CHROMA_KEY)
        except tk.TclError:
            pass
        window.resizable(False, False)
        window.transient(self.root)
        window.attributes("-topmost", True)
        window.lift()
        window.focus_force()
        x = self.root.winfo_x() + max(0, WIDTH - 380)
        y = self.root.winfo_y() + 32
        window.geometry("380x590+{}+{}".format(x, y))
        window.protocol("WM_DELETE_WINDOW", self._close_settings)

        self.setting_scales = {}
        self.settings_panel_bg = self._rgb_hex(self.interface_color)
        self.settings_drag_origin = (0, 0)
        self.settings_canvas = tk.Canvas(
            window,
            width=380,
            height=590,
            bg=CHROMA_KEY,
            bd=0,
            highlightthickness=0,
        )
        self.settings_canvas.pack(fill="both", expand=True)
        self.settings_surface_item = self.settings_canvas.create_image(0, 0, anchor="nw")
        self.settings_header_item = self.settings_canvas.create_text(
            20,
            25,
            anchor="w",
            text="监控外观设置",
            fill="#f1f5ff",
            font=_font(12, "bold"),
        )
        self.settings_close_item = self.settings_canvas.create_text(
            358, 24, anchor="center", text="×", fill=MUTED, font=_font(15)
        )
        self.settings_canvas.tag_bind(
            self.settings_close_item, "<Button-1>", lambda _event: self._close_settings()
        )
        self.settings_canvas.bind("<ButtonPress-1>", self._settings_drag_start)
        self.settings_canvas.bind("<B1-Motion>", self._settings_drag_move)
        self._render_settings_surface()

        panel = tk.Frame(window, bg=self.settings_panel_bg)
        panel.place(x=10, y=56, width=360, height=524)
        tk.Label(panel, text="拖动滑块实时预览，设置会自动保存", bg=self.settings_panel_bg, fg="#9eb8d2", font=(FONT, 8)).pack(anchor="w", padx=12, pady=(3, 3))
        self._settings_section(panel, "界面颜色 / 透明度", "interface")
        self._add_setting_scale(panel, "interface_r", "界面 R", 0, 255)
        self._add_setting_scale(panel, "interface_g", "界面 G", 0, 255)
        self._add_setting_scale(panel, "interface_b", "界面 B", 0, 255)
        self._add_setting_scale(panel, "interface_alpha", "界面透明度 %", 0, 100)

        self._settings_section(panel, "背景颜色 / 透明度", "background")
        self._add_setting_scale(panel, "background_r", "背景 R", 0, 255)
        self._add_setting_scale(panel, "background_g", "背景 G", 0, 255)
        self._add_setting_scale(panel, "background_b", "背景 B", 0, 255)
        self._add_setting_scale(panel, "background_alpha", "背景透明度 %", 0, 100)

        self._settings_section(panel, "天体效果")
        self._add_setting_scale(panel, "moon_alpha", "天体透明度 %", 0, 100)
        self._add_setting_scale(panel, "moon_contrast", "天体对比度 %", 0, 100)

        buttons = tk.Frame(panel, bg=self.settings_panel_bg)
        buttons.pack(fill="x", padx=12, pady=(8, 3))
        tk.Button(
            buttons,
            text="恢复默认",
            command=self._reset_settings,
            bg=self._rgb_hex(self.header_color),
            fg="#f1f5ff",
            activebackground="#3b6985",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
        ).pack(side="left")
        tk.Button(
            buttons,
            text="关闭",
            command=self._close_settings,
            bg=self._rgb_hex(self.header_color),
            fg="#f1f5ff",
            activebackground="#3b6985",
            activeforeground="#ffffff",
            relief="flat",
            padx=10,
        ).pack(side="right")
        panel.lift()
        window.after(30, window.lift)
        window.after(40, window.focus_force)

    def _reset_settings(self) -> None:
        self.settings = dict(DEFAULT_SETTINGS)
        self._sync_settings()
        for key, scale in self.setting_scales.items():
            scale.set(self.settings[key])
        self._render_background()
        self._render_settings_surface()
        self._save_settings()

    def pick_color(self, color_kind: str) -> None:
        prefix = "interface" if color_kind == "interface" else "background"
        keys = ("{}_r".format(prefix), "{}_g".format(prefix), "{}_b".format(prefix))
        current = tuple(int(self.settings.get(key, DEFAULT_SETTINGS[key])) for key in keys)
        result = colorchooser.askcolor(
            color=self._rgb_hex(current),
            parent=self.settings_window,
            title="选择{}颜色".format("界面" if prefix == "interface" else "背景"),
        )
        rgb = result[0]
        if rgb is None:
            return
        for key, value in zip(keys, rgb):
            self.settings[key] = int(round(value))
        self._sync_settings()
        for key in keys:
            if key in self.setting_scales:
                self.setting_scales[key].set(self.settings[key])
        self._render_background()
        self._render_settings_surface()
        self._save_settings()

    def _close_settings(self) -> None:
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None
        self.settings_canvas = None
        self.settings_surface_photo = None
        self.settings_close_item = None
        self.setting_scales = {}

    def _create_text_items(self) -> None:
        self.title_item = self.canvas.create_text(
            20, 24, anchor="w", text="Codex 监控", fill=TEXT, font=_font(10, "normal")
        )
        self.sync_item = self.canvas.create_text(
            295, 24, anchor="e", text="● 已同步", fill=GREEN, font=_font(8, "bold")
        )
        self.pin_item = self.canvas.create_text(
            310, 24, anchor="center", text="●", fill=CYAN, font=_font(8, "bold")
        )
        self.settings_item = self.canvas.create_text(
            329, 24, anchor="center", text="⚙", fill=MUTED, font=_font(11, "normal")
        )
        self.toggle_item = self.canvas.create_text(
            349, 24, anchor="center", text="▴", fill=MUTED, font=_font(10, "bold")
        )
        self.close_item = self.canvas.create_text(
            370, 23, anchor="center", text="×", fill=MUTED, font=_font(15)
        )

        self.quota_name = self.canvas.create_text(
            24, 58, anchor="w", text="账户近期额度", fill=TEXT, font=_font(9, "bold")
        )
        self.quota_value = self.canvas.create_text(
            366, 58, anchor="e", text="剩余 100%", fill=CYAN, font=_font(9, "bold")
        )
        self.quota_status = self.canvas.create_text(
            24, 102, anchor="w", text="已同步 --", fill=FINE, font=_font(7)
        )

        self.reset_heading = self.canvas.create_text(
            24, 128, anchor="w", text="可用手动重置", fill=TEXT, font=_font(9, "bold")
        )
        self.reset_count = self.canvas.create_text(
            24, 147, anchor="w", text="-- 次", fill=TEXT, font=_font(13, "bold")
        )
        self.reset_auto_meta = self.canvas.create_text(
            366, 128, anchor="e", text="额度自动重置 --", fill=MUTED, font=_font(7)
        )
        self.reset_manual_meta = self.canvas.create_text(
            366, 148, anchor="e", text="手动重置到期 --", fill=MUTED, font=_font(7)
        )

        self.token_heading = self.canvas.create_text(
            24, 190, anchor="w", text="TOKEN 使用情况", fill=TEXT, font=_font(9, "bold")
        )
        self.token_7 = self.canvas.create_text(
            24, 217, anchor="w", text="7天 --", fill=CYAN, font=_font(9, "bold")
        )
        self.token_session = self.canvas.create_text(
            145, 217, anchor="w", text="本次 --", fill=TEXT, font=_font(9, "bold")
        )
        self.token_30 = self.canvas.create_text(
            242, 217, anchor="w", text="消耗总TOKEN --", fill=ACCENT, font=_font(9, "bold")
        )

        self.footer_right = self.canvas.create_text(
            236, 24, anchor="e", text="--", fill=FINE, font=_font(8)
        )
        self.detail_items = (
            self.quota_name,
            self.quota_value,
            self.quota_status,
            self.reset_heading,
            self.reset_count,
            self.reset_auto_meta,
            self.reset_manual_meta,
            self.token_heading,
            self.token_7,
            self.token_session,
            self.token_30,
        )
        # Folded mode is a compact one-line capsule: keep only the summary
        # and the expand/close affordances visible.
        self.collapsed_hidden_items = (
            self.title_item,
            self.sync_item,
            self.pin_item,
            self.settings_item,
            self.footer_right,
        )
        self.collapsed_info_item = self.canvas.create_text(
            20,
            26,
            anchor="w",
            text="额度 -- · 本次 --",
            fill=TEXT,
            font=_font(9, "normal"),
            state="hidden",
        )

    def _create_interaction_items(self) -> None:
        self.pin_hit = self.canvas.create_rectangle(296, 6, 318, 37, fill="", outline="")
        self.settings_hit = self.canvas.create_rectangle(318, 6, 338, 37, fill="", outline="")
        self.toggle_hit = self.canvas.create_rectangle(338, 6, 359, 37, fill="", outline="")
        self.close_hit = self.canvas.create_rectangle(359, 6, 387, 37, fill="", outline="")
        self.canvas.tag_bind(self.pin_hit, "<Button-1>", lambda _event: self.toggle_pin())
        self.canvas.tag_bind(self.close_hit, "<Button-1>", lambda _event: self.close())
        self.canvas.tag_bind(self.pin_item, "<Button-1>", lambda _event: self.toggle_pin())
        self.canvas.tag_bind(self.close_item, "<Button-1>", lambda _event: self.close())

    @staticmethod
    def _is_header_control(x: int, y: int) -> bool:
        return 6 <= y <= HEADER_HEIGHT and 296 <= x <= 387

    def _handle_press(self, event: tk.Event) -> None:
        if self._is_header_control(event.x, event.y):
            self.drag_origin = (-1, -1)
            return
        self._drag_start(event)

    def _handle_release(self, event: tk.Event) -> None:
        if event.y < 6 or event.y > HEADER_HEIGHT:
            return
        if 318 <= event.x < 338:
            self.open_settings()
        elif 338 <= event.x < 359:
            self.toggle_collapsed()

    @staticmethod
    def _rounded(
        draw: Any,
        box: Tuple[int, int, int, int],
        fill: Tuple[int, ...],
        outline: Optional[Tuple[int, ...]],
        radius: int = 14,
    ) -> None:
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=1)

    def _load_moon_frame(self, index: int, size: int) -> Any:
        index = max(0, min(MOON_FRAME_COUNT - 1, index))
        if index in self.moon_frame_cache:
            return self.moon_frame_cache[index]

        path = MOON_PHASE_DIR / "moon-{:02d}.png".format(index)
        source_path = path if path.exists() else MOON_PATH
        source = Image.open(source_path).convert("RGBA")
        fitted = ImageOps.contain(source, (size, size), method=Image.Resampling.LANCZOS)
        offset = ((size - fitted.width) // 2, (size - fitted.height) // 2)
        source_alpha = fitted.getchannel("A")
        contrasted = ImageEnhance.Contrast(fitted.convert("RGB")).enhance(self.moon_contrast)
        dimmed = ImageEnhance.Brightness(contrasted).enhance(MOON_BRIGHTNESS)
        fitted = dimmed.convert("RGBA")

        # The phase frames contain a faint antialiased halo outside the lunar
        # disc. Keep the source alpha for the phase itself, but clip it to the
        # real disc bounds so the black source background cannot form a ring.
        disc_mask = Image.new("L", fitted.size, 0)
        ImageDraw.Draw(disc_mask).ellipse(
            (
                int(round(fitted.width * 0.022)),
                int(round(fitted.height * 0.051)),
                int(round(fitted.width * 0.963)),
                int(round(fitted.height * 0.982)),
            ),
            fill=255,
        )
        fitted.putalpha(ImageChops.multiply(source_alpha, disc_mask))

        frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        frame.alpha_composite(fitted, offset)
        frame.putalpha(frame.getchannel("A").point(lambda value: int(value * self.moon_alpha / 255)))
        self.moon_frame_cache[index] = frame
        return frame

    def _moon_frame_for_ratio(self, ratio: float, size: int) -> Any:
        position = max(0.02, min(1.0, ratio)) * (MOON_FRAME_COUNT - 1)
        lower = int(math.floor(position))
        upper = min(MOON_FRAME_COUNT - 1, lower + 1)
        blend = position - lower
        first = self._load_moon_frame(lower, size)
        if upper == lower:
            return first
        second = self._load_moon_frame(upper, size)
        return Image.blend(first, second, blend)

    def _spawn_shooting_star(self) -> None:
        self.shooting_star = {
            "x": -96.0,
            "y": self.star_rng.uniform(24, 78),
            "dx": self.star_rng.uniform(WIDTH + 140, WIDTH + 190),
            "dy": self.star_rng.uniform(105, 165),
            "progress": 0.0,
            "speed": self.star_rng.uniform(0.032, 0.045),
            "tail": self.star_rng.uniform(0.13, 0.19),
        }

    def _draw_shooting_star(self, image: Any) -> None:
        star = self.shooting_star
        if not star:
            return

        progress = star["progress"]
        tail_progress = max(0.0, progress - star["tail"])

        def point(at: float) -> Tuple[float, float]:
            return (
                star["x"] + star["dx"] * at,
                star["y"] + star["dy"] * at,
            )

        tail = point(tail_progress)
        head = point(progress)

        glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.line((tail, head), fill=(91, 181, 255, 72), width=8)
        glow = glow.filter(ImageFilter.GaussianBlur(4))
        image.alpha_composite(glow)

        trail = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        trail_draw = ImageDraw.Draw(trail)
        segments = 7
        for index in range(segments):
            start = max(0.0, progress - star["tail"] * (1.0 - index / segments))
            end = max(0.0, progress - star["tail"] * (1.0 - (index + 1) / segments))
            alpha = int(44 + 190 * ((index + 1) / segments))
            trail_draw.line((point(start), point(end)), fill=(218, 240, 255, alpha), width=2)
        head_x, head_y = head
        trail_draw.ellipse((head_x - 2, head_y - 2, head_x + 2, head_y + 2), fill=(255, 255, 255, 235))
        image.alpha_composite(trail)

    def _moon_background(self, ratio: float) -> Any:
        moon_size = 220
        moon = self._moon_frame_for_ratio(ratio, moon_size)

        # Use the reference blue-gray body color as the compositing base so
        # the translucent dashboard surface retains the supplied swatch while
        # the moon remains visible through it.
        image = Image.new("RGBA", (WIDTH, HEIGHT), self.background_color + (self.background_alpha,))
        image.alpha_composite(moon, ((WIDTH - moon_size) // 2, 30))

        stars = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        star_draw = ImageDraw.Draw(stars)
        idle_strength = max(0.0, min(1.0, self.idle_star_strength))
        rng = random.Random(19)
        for index, (x, y) in enumerate(STAR_POSITIONS[:STAR_COUNT]):
            radius_px = rng.choice([1, 1, 1, 2])
            base_alpha = rng.choice([100, 125, 150, 175])
            phase = math.tau * index / STAR_COUNT
            wave = 0.5 + 0.5 * math.sin(math.tau * self.animation_time / STAR_PERIOD + phase)
            pulse = max(0.0, (wave - STAR_ACTIVE_THRESHOLD) / (1.0 - STAR_ACTIVE_THRESHOLD))
            alpha = int(base_alpha * idle_strength * pulse)
            if alpha <= 0:
                continue
            star_draw.ellipse(
                (x - radius_px, y - radius_px, x + radius_px, y + radius_px),
                fill=(214, 231, 255, alpha),
            )
        image.alpha_composite(stars)
        self._draw_shooting_star(image)

        visible_height = COLLAPSED_HEIGHT if self.is_collapsed else HEIGHT
        outer_bottom = visible_height - 8
        glass = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        glass_draw = ImageDraw.Draw(glass)
        self._rounded(
            glass_draw,
            (8, 8, WIDTH - 8, outer_bottom),
            self.interface_color + (self.interface_alpha,),
            (190, 220, 244, 84),
            18,
        )
        header_bottom = COLLAPSED_HEIGHT if self.is_collapsed else HEADER_HEIGHT
        header_alpha = int(HEADER_ALPHA * self.interface_alpha / max(1, GLASS_ALPHA))
        glass_draw.rectangle(
            (8, 8, WIDTH - 8, header_bottom),
            fill=self.header_color + (min(255, header_alpha),),
        )
        if not self.is_collapsed:
            glass_draw.line(
                (18, header_bottom, WIDTH - 18, header_bottom),
                fill=(1, 146, 173, 150),
                width=1,
            )
        if not self.is_collapsed:
            for box in ((18, 46, WIDTH - 18, 108), (18, 116, WIDTH - 18, 166), (18, 176, WIDTH - 18, 246)):
                self._rounded(
                    glass_draw,
                    box,
                    self.interface_color + (self.interface_alpha,),
                    (180, 215, 239, 50),
                    12,
                )

            remaining = max(0.0, min(100.0, float(self.data.get("remaining_percent", 100.0))))
            intensity = remaining / 100.0
            gray = (166, 181, 199)
            vivid = (113, 219, 229)
            quota_color = tuple(int(gray[i] * (1 - intensity) + vivid[i] * intensity) for i in range(3))
            glass_draw.rounded_rectangle(
                (24, 74, WIDTH - 24, 84),
                radius=5,
                fill=(156, 181, 205, 88),
                outline=(198, 224, 243, 86),
            )
            if remaining > 0:
                fill_end = 24 + max(7, int((WIDTH - 48) * remaining / 100.0))
                glass_draw.rounded_rectangle(
                    (24, 74, fill_end, 84),
                    radius=5,
                    fill=quota_color + (WORK_BAR_ALPHA,),
                    outline=None,
                )

        rounded_alpha = Image.new("L", (WIDTH, HEIGHT), 0)
        ImageDraw.Draw(rounded_alpha).rounded_rectangle(
            (8, 8, WIDTH - 8, outer_bottom), radius=18, fill=255
        )
        image.alpha_composite(glass)
        image.putalpha(ImageChops.multiply(image.getchannel("A"), rounded_alpha))
        return image

    def _render_background(self) -> None:
        if Image is None or ImageTk is None or not MOON_PATH.exists():
            return
        image = self._moon_background(float(self.data.get("moon_ratio", 1.0)))
        self.background_photo = ImageTk.PhotoImage(image)
        self.canvas.itemconfigure(self.background_item, image=self.background_photo)
        self.canvas.tag_lower(self.background_item)

    @staticmethod
    def _quota_text_color(remaining: float) -> str:
        intensity = max(0.0, min(1.0, remaining / 100.0))
        gray = (166, 181, 199)
        vivid = (113, 219, 229)
        rgb = tuple(int(gray[i] * (1 - intensity) + vivid[i] * intensity) for i in range(3))
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    def _update_text(self) -> None:
        remaining = float(self.data.get("remaining_percent", 100.0))
        is_working = bool(self.data.get("is_working"))
        manual_reset_count = self.data.get("manual_reset_count")
        count_label = "--" if manual_reset_count is None else str(manual_reset_count)
        auto_reset_label = str(self.data.get("auto_reset_time_label", "--"))
        manual_expiry_label = str(self.data.get("manual_reset_expiry_label", "--"))

        self.canvas.itemconfigure(
            self.sync_item,
            text="● 工作中" if is_working else "● 已同步",
            fill="#77b8e8" if is_working else GREEN,
        )
        self.canvas.itemconfigure(
            self.quota_value,
            text="剩余 {:.0f}%".format(remaining),
            fill=self._quota_text_color(remaining),
        )
        self.canvas.itemconfigure(
            self.quota_status,
            text="已同步 {}".format(self.data.get("latest_update", "--")),
            fill="#86b8e7" if is_working else FINE,
        )
        self.canvas.itemconfigure(self.reset_count, text="{} 次".format(count_label))
        self.canvas.itemconfigure(
            self.reset_auto_meta,
            text="额度自动重置 {}".format(auto_reset_label),
        )
        self.canvas.itemconfigure(
            self.reset_manual_meta,
            text="手动重置到期 {}".format(manual_expiry_label),
        )
        self.canvas.itemconfigure(
            self.token_7,
            text="7天 {}".format(self.data.get("recent_7d_label", "0")),
        )
        self.canvas.itemconfigure(
            self.token_session,
            text="本次 {}".format(self.data.get("session_tokens_label", "0")),
        )
        self.canvas.itemconfigure(
            self.token_30,
            text="消耗总TOKEN {}".format(self.data.get("recent_30d_label", "0")),
        )
        self.canvas.itemconfigure(
            self.footer_right,
            text="{}".format(self.data.get("refreshed_at", "--")),
        )
        session_label = self.data.get("session_tokens_label", "0")
        refreshed_label = str(self.data.get("refreshed_at", "--"))
        status_label = "工作中" if is_working else "已同步"
        collapsed_text = "{} · {} · 额度 {:.0f}% · 本次 {}".format(
            refreshed_label,
            status_label,
            remaining,
            session_label,
        )
        self.canvas.itemconfigure(
            self.collapsed_info_item,
            text=collapsed_text,
            state="normal" if self.is_collapsed else "hidden",
        )
        self.canvas.itemconfigure(self.toggle_item, text="▾" if self.is_collapsed else "▴")
        self.canvas.itemconfigure(self.pin_item, fill=CYAN if self.pinned else FINE)

    def refresh(self) -> None:
        if self.closed:
            return
        try:
            self.data = load_dashboard_data(LIFECYCLE_ID, STARTED_AT_MS or 0)
            self._render_background()
            self._update_text()
        except Exception:
            self.canvas.itemconfigure(self.sync_item, text="● 读取异常", fill=ACCENT)
        self.root.after(3500, self.refresh)

    def animate(self) -> None:
        if self.closed:
            return
        self.animation_time += FRAME_MS / 1000.0
        should_render = False
        if not self.data.get("is_working"):
            if self.shooting_star is not None:
                self.shooting_star = None
            if self.idle_star_strength < 1.0:
                self.idle_star_strength = min(1.0, self.idle_star_strength + 0.06)
            should_render = True
            self.was_working = False
            self._render_background()
            self.root.after(FRAME_MS, self.animate)
            return

        if self.idle_star_strength > 0.0:
            self.idle_star_strength = max(0.0, self.idle_star_strength - 0.12)
            should_render = True

        if not self.was_working:
            self.next_shooting_star_at = self.animation_time + self.star_rng.uniform(1.2, 3.2)
            self.was_working = True

        if self.shooting_star is None and self.animation_time >= self.next_shooting_star_at:
            self._spawn_shooting_star()
            should_render = True
        if self.shooting_star is not None:
            self.shooting_star["progress"] += self.shooting_star["speed"]
            should_render = True
            if self.shooting_star["progress"] > 1.12:
                self.shooting_star = None
                self.next_shooting_star_at = self.animation_time + self.star_rng.uniform(4.5, 8.5)
        if should_render:
            self._render_background()
        self.root.after(FRAME_MS, self.animate)

    def toggle_pin(self) -> None:
        self.pinned = not self.pinned
        self.root.attributes("-topmost", self.pinned)
        self.canvas.itemconfigure(self.pin_item, fill=CYAN if self.pinned else FINE)

    def toggle_collapsed(self) -> None:
        self.is_collapsed = not self.is_collapsed
        height = COLLAPSED_HEIGHT if self.is_collapsed else HEIGHT
        x = self.root.winfo_x()
        y = self.root.winfo_y()
        self.root.geometry("{}x{}+{}+{}".format(WIDTH, height, x, y))
        self.canvas.configure(height=height)
        self.canvas.itemconfigure(
            self.collapsed_info_item,
            state="normal" if self.is_collapsed else "hidden",
        )
        for item in self.detail_items:
            self.canvas.itemconfigure(item, state="hidden" if self.is_collapsed else "normal")
        for item in self.collapsed_hidden_items:
            self.canvas.itemconfigure(item, state="hidden" if self.is_collapsed else "normal")
        self.canvas.itemconfigure(self.toggle_item, text="▾" if self.is_collapsed else "▴")
        self._render_background()

    def _drag_start(self, event: tk.Event) -> None:
        self.drag_origin = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event: tk.Event) -> None:
        x = event.x_root - self.drag_origin[0]
        y = event.y_root - self.drag_origin[1]
        self.root.geometry("+{}+{}".format(x, y))

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._close_settings()
        if LIFECYCLE_ID != "manual":
            mark_manually_dismissed(LIFECYCLE_ID)
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    MoonDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
