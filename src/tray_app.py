# FILE: src/tray_app.py
# PURPOSE: Трей Windows + окно деталей в стиле dashboard Cursor (ru/en).
# WHY: UI как в ЛК: карточки Current plan / Balance + heatmap без прыжков ширины.

from __future__ import annotations

import threading
import webbrowser
from datetime import date as date_cls
from typing import Any

import pystray
from pystray import MenuItem as Item

from . import autostart
from .config import AppConfig
from .i18n import I18n, translate_display_message
from .icon import make_icon
from .models import DayBucket, Money, UsageSnapshot
from .service import refresh_usage
from .settings_store import (
    REFRESH_MAX,
    REFRESH_MIN,
    load_refresh_interval_sec,
    save_refresh_interval_sec,
)
from .status_bar_install import install_status_bar

DASHBOARD_URL = "https://cursor.com/dashboard/usage"

# Палитра как на скрине ЛК: чистый чёрный + тёмные карточки + синий heatmap
BG = "#000000"
BG_CARD = "#111111"
BG_RAISED = "#1a1a1a"
FG = "#ffffff"
MUTED = "#8a8a8a"
BORDER = "#222222"
TRACK = "#2a2a2a"
HOVER = "#252525"
# Белая «таблетка» как Upgrade / Auto top-up
PILL_BG = "#ffffff"
PILL_FG = "#000000"
# Синяя шкала активности (как AI line edits)
HEAT = ("#1a1a1a", "#0c4a6e", "#0284c7", "#38bdf8", "#7dd3fc")
OK_GREEN = "#22c55e"
ERR_RED = "#ef4444"

# Годовой contribution-graph как в ЛК (колонки = недели, строки = дни)
YEAR_CELL = 11
YEAR_PAD = 2
YEAR_WEEKS = 53
YEAR_MONTH_H = 14
YEAR_CANVAS_W = YEAR_WEEKS * (YEAR_CELL + YEAR_PAD) + 4
YEAR_CANVAS_H = YEAR_MONTH_H + 7 * (YEAR_CELL + YEAR_PAD) + 4


class TrayController:
    """Трей + одно живое окно деталей (withdraw вместо destroy)."""

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.i18n = I18n()
        self.snapshot = UsageSnapshot(error=self.i18n.t("loading"))
        # Интервал опроса (настраивается в UI, 60–3600 с)
        self.refresh_interval_sec = load_refresh_interval_sec(cfg.refresh_interval_sec)
        self._icon: pystray.Icon | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._refreshing = threading.Event()
        self._popup_root: Any = None
        self._popup_widgets: dict[str, Any] = {}
        self._popup_thread: threading.Thread | None = None
        self._online_ok: bool | None = None
        # Вкладка активности: full = год, week = детализация по дням
        self._activity_tab: str = "full"

    def start(self) -> None:
        self._icon = pystray.Icon(
            name="CursorLimits",
            icon=make_icon("error", 0),
            title=self.i18n.t("app_title"),
            menu=self._build_menu(),
        )
        threading.Thread(target=self._refresh_safe, daemon=True, name="cl-first").start()
        threading.Thread(target=self._loop_refresh, daemon=True, name="cl-poll").start()
        if self.cfg.show_popup_on_start:
            self.open_details()
        assert self._icon is not None
        self._icon.run()

    def stop(self, _icon: Any = None, _item: Any = None) -> None:
        self._stop.set()
        self._shutdown_popup()
        if self._icon:
            self._icon.stop()

    def _build_menu(self) -> pystray.Menu:
        i = self.i18n
        return pystray.Menu(
            Item(i.t("open_details"), self.open_details, default=True),
            Item(i.t("refresh_now"), self._on_refresh_click),
            Item(i.t("check_online"), self._on_online_check),
            Item(
                lambda _item: (
                    "✓ Language: English" if self.i18n.lang == "en" else "✓ Язык: Русский"
                ),
                self._on_toggle_lang,
            ),
            Item(
                i.t("autostart"),
                self._on_toggle_autostart,
                checked=lambda _item: autostart.is_enabled(),
            ),
            Item(i.t("open_dashboard"), self._open_dashboard),
            Item(i.t("install_statusbar"), self._on_install_statusbar),
            Item(i.t("exit"), self.stop),
        )

    def _rebuild_menu(self) -> None:
        if self._icon:
            try:
                self._icon.menu = self._build_menu()
                self._icon.update_menu()
            except Exception:
                pass

    def _on_refresh_click(self, _icon: Any = None, _item: Any = None) -> None:
        threading.Thread(target=self._refresh_safe, daemon=True, name="cl-manual").start()

    def _on_online_check(self, _icon: Any = None, _item: Any = None) -> None:
        threading.Thread(target=self._run_online_check_ui, daemon=True, name="cl-online").start()

    def _on_toggle_lang(self, _icon: Any = None, _item: Any = None) -> None:
        self.i18n.toggle()
        self._rebuild_menu()
        with self._lock:
            snap = self.snapshot
        if self._icon:
            try:
                self._icon.title = snap.tray_title() if not snap.error else self.i18n.t("app_title")
            except Exception:
                pass
        root = self._popup_root
        if root is not None:
            try:
                root.after(0, lambda: self._apply_chrome_texts())
                root.after(0, lambda: self._render_popup_content(snap))
            except Exception:
                pass

    def _run_online_check_ui(self) -> None:
        from .online_check import run_online_check

        try:
            report = run_online_check(cfg=self.cfg)
            self._online_ok = bool(report.usage_online)
        except Exception:
            self._online_ok = False

        self._refresh_safe()
        root = self._popup_root
        if root is not None:
            try:
                root.after(0, self._update_online_indicator)
            except Exception:
                pass

    def _on_toggle_autostart(self, _icon: Any = None, _item: Any = None) -> None:
        try:
            autostart.toggle()
        except OSError:
            pass

    def _open_dashboard(self, _icon: Any = None, _item: Any = None) -> None:
        webbrowser.open(DASHBOARD_URL)

    def _on_install_statusbar(self, _icon: Any = None, _item: Any = None) -> None:
        """Установка расширения нижней панели Cursor из трея/окна."""
        try:
            dst = install_status_bar()
            msg = self.i18n.t("statusbar_ok", path=str(dst))
        except Exception as exc:  # noqa: BLE001
            msg = self.i18n.t("statusbar_fail", err=str(exc))
        root = self._popup_root
        try:
            import tkinter.messagebox as mb

            if root is not None:
                root.after(0, lambda: mb.showinfo(self.i18n.t("statusbar_title"), msg, parent=root))
            else:
                tmp = __import__("tkinter").Tk()
                tmp.withdraw()
                mb.showinfo(self.i18n.t("statusbar_title"), msg, parent=tmp)
                tmp.destroy()
        except Exception:
            if self._icon:
                try:
                    self._icon.title = msg[:127]
                except Exception:
                    pass

    def open_details(self, _icon: Any = None, _item: Any = None) -> None:
        threading.Thread(target=self._refresh_safe, daemon=True, name="cl-open").start()
        if self._popup_root is not None:
            self._show_popup()
            return
        if self._popup_thread and self._popup_thread.is_alive():
            threading.Thread(target=self._wait_and_show, daemon=True, name="cl-wait").start()
            return
        self._popup_thread = threading.Thread(
            target=self._ensure_popup, daemon=True, name="cl-popup"
        )
        self._popup_thread.start()

    def _wait_and_show(self) -> None:
        t = self._popup_thread
        if t:
            t.join(timeout=5.0)
        self._show_popup()

    def _loop_refresh(self) -> None:
        while not self._stop.is_set():
            # Читаем актуальный интервал каждый цикл (UI мог поменять)
            wait = max(REFRESH_MIN, min(REFRESH_MAX, int(self.refresh_interval_sec)))
            if self._stop.wait(wait):
                break
            self._refresh_safe()

    def _refresh_safe(self) -> None:
        if self._refreshing.is_set():
            return
        self._refreshing.set()
        try:
            try:
                snap, _creds = refresh_usage(self.cfg)
            except Exception as exc:  # noqa: BLE001
                snap = UsageSnapshot(error=str(exc))
            self._online_ok = bool(snap.online_usage_ok) and not snap.error
            with self._lock:
                self.snapshot = snap
            self._apply_icon(snap)
            self._push_popup_update(snap)
        finally:
            self._refreshing.clear()

    def _apply_icon(self, snap: UsageSnapshot) -> None:
        if not self._icon:
            return
        # % недельного пула → плавный цвет badge/дуги на иконке
        pct = snap.usage_percent() if not snap.error else 0.0
        try:
            self._icon.icon = make_icon(snap.level, pct)
            self._icon.title = snap.tray_title()
        except Exception:
            pass

    def _shutdown_popup(self) -> None:
        root = self._popup_root
        if root is None:
            return

        def _die() -> None:
            try:
                root.quit()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass

        try:
            root.after(0, _die)
        except Exception:
            pass

    def _push_popup_update(self, snap: UsageSnapshot) -> None:
        root = self._popup_root
        if root is None:
            return
        try:
            if not bool(root.winfo_ismapped()):
                return
        except Exception:
            return

        def _safe() -> None:
            try:
                self._render_popup_content(snap)
                self._update_online_indicator()
            except Exception:
                pass

        try:
            root.after(0, _safe)
        except Exception:
            pass

    def _show_popup(self) -> None:
        root = self._popup_root
        if root is None:
            return

        def _show() -> None:
            try:
                root.deiconify()
                root.lift()
                root.focus_force()
            except Exception:
                return
            with self._lock:
                snap = self.snapshot
            try:
                self._render_popup_content(snap)
                self._update_online_indicator()
            except Exception:
                pass

        try:
            root.after(0, _show)
        except Exception:
            pass

    def _apply_chrome_texts(self) -> None:
        w = self._popup_widgets
        if not w:
            return
        i = self.i18n
        try:
            w["root"].title(i.t("app_title"))
            w["btn_refresh"].configure(text=i.t("refresh"))
            w["online_label"].configure(text=i.t("online"))
            w["btn_dash"].configure(text=i.t("dashboard"))
            btn_sb = w.get("btn_statusbar")
            if btn_sb is not None:
                btn_sb.configure(text=i.t("install_statusbar_short"))
            btn_up = w.get("btn_upgrade")
            if btn_up is not None:
                try:
                    btn_up.configure(text=i.t("open_upgrade"))
                except Exception:
                    pass
            self._paint_lang_flag()
            rate_lbl = w.get("rate_label")
            if rate_lbl is not None:
                with self._lock:
                    snap = self.snapshot
                rate_lbl.configure(text=self._rate_text(snap))
        except Exception:
            pass

    def _rate_text(self, snap: UsageSnapshot) -> str:
        i = self.i18n
        if snap.usd_rub_rate:
            return f"{i.t('rate_cbr')}: {snap.usd_rub_rate:.2f} ₽/$"
        return i.t("rate_na")

    def _apply_refresh_interval(self, raw: str | int) -> None:
        self.refresh_interval_sec = save_refresh_interval_sec(raw)

    def _mk_btn(
        self,
        parent: Any,
        tk: Any,
        text: str,
        command: Any,
        *,
        pill: bool = False,
        padx: int = 14,
    ) -> Any:
        if pill:
            bg, fg, active = PILL_BG, PILL_FG, "#e5e5e5"
        else:
            bg, fg, active = BG_RAISED, FG, HOVER
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=active,
            activeforeground=fg,
            relief="flat",
            bd=0,
            padx=padx,
            pady=5,
            font=("Segoe UI", 9),
            cursor="hand2",
            highlightthickness=0,
        )

    def _paint_lang_flag(self) -> None:
        w = self._popup_widgets
        canvas = w.get("lang_canvas")
        if canvas is None:
            return
        canvas.delete("all")
        target = "en" if self.i18n.lang == "ru" else "ru"
        w_, h_ = 28, 18
        if target == "ru":
            for i, color in enumerate(("#ffffff", "#0039a6", "#d52b1e")):
                y0 = i * (h_ // 3)
                canvas.create_rectangle(0, y0, w_, y0 + h_ // 3 + 1, fill=color, outline="")
        else:
            canvas.create_rectangle(0, 0, w_, h_, fill="#012169", outline="")
            canvas.create_line(0, 0, w_, h_, fill="#ffffff", width=3)
            canvas.create_line(0, h_, w_, 0, fill="#ffffff", width=3)
            canvas.create_line(0, 0, w_, h_, fill="#c8102e", width=1)
            canvas.create_line(0, h_, w_, 0, fill="#c8102e", width=1)
            canvas.create_rectangle(w_ // 2 - 2, 0, w_ // 2 + 2, h_, fill="#ffffff", outline="")
            canvas.create_rectangle(0, h_ // 2 - 2, w_, h_ // 2 + 2, fill="#ffffff", outline="")
            canvas.create_rectangle(w_ // 2 - 1, 0, w_ // 2 + 1, h_, fill="#c8102e", outline="")
            canvas.create_rectangle(0, h_ // 2 - 1, w_, h_ // 2 + 1, fill="#c8102e", outline="")
        canvas.create_rectangle(0, 0, w_ - 1, h_ - 1, outline=BORDER)

    def _update_online_indicator(self) -> None:
        w = self._popup_widgets
        canvas = w.get("online_dot")
        if canvas is None:
            return
        if self._online_ok is True:
            color = OK_GREEN
        elif self._online_ok is False:
            color = ERR_RED
        else:
            color = MUTED
        canvas.delete("all")
        canvas.create_oval(2, 2, 12, 12, fill=color, outline="")

    def _card(self, parent: Any, tk: Any) -> Any:
        """Тёмная карточка ЛК (компактные отступы — чтобы всё влезло в окно)."""
        return tk.Frame(
            parent,
            bg=BG_CARD,
            highlightthickness=1,
            highlightbackground=BORDER,
            padx=14,
            pady=12,
        )

    def _ensure_popup(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        if self._popup_root is not None:
            self._show_popup()
            return

        root = tk.Tk()
        self._popup_root = root
        root.title(self.i18n.t("app_title"))
        # Чуть выше — чтобы heatmap + статы влезали без ручного растягивания
        root.geometry("980x700")
        root.minsize(920, 660)
        root.protocol("WM_DELETE_WINDOW", self._on_popup_close)
        root.configure(bg=BG)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG, font=("Segoe UI", 9))
        style.configure(
            "Hero.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 22)
        )
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 8))

        outer = tk.Frame(root, bg=BG, padx=16, pady=10)
        outer.pack(fill=tk.BOTH, expand=True)

        # ── Тулбар слева, флаг справа ──
        toolbar = tk.Frame(outer, bg=BG)
        toolbar.pack(fill=tk.X, pady=(0, 12))
        left_bar = tk.Frame(toolbar, bg=BG)
        left_bar.pack(side=tk.LEFT)

        def on_refresh() -> None:
            threading.Thread(target=self._refresh_safe, daemon=True, name="cl-btn").start()

        def on_online() -> None:
            threading.Thread(target=self._run_online_check_ui, daemon=True, name="cl-on").start()

        def on_lang() -> None:
            self.i18n.toggle()
            self._rebuild_menu()
            self._apply_chrome_texts()
            with self._lock:
                snap = self.snapshot
            self._render_popup_content(snap)

        btn_refresh = self._mk_btn(left_bar, tk, self.i18n.t("refresh"), on_refresh)
        btn_refresh.pack(side=tk.LEFT, padx=(0, 6))

        online_wrap = tk.Frame(left_bar, bg=BG_RAISED, cursor="hand2")
        online_wrap.pack(side=tk.LEFT, padx=(0, 6))
        online_inner = tk.Frame(online_wrap, bg=BG_RAISED, padx=10, pady=5)
        online_inner.pack()
        online_dot = tk.Canvas(
            online_inner, width=14, height=14, bg=BG_RAISED, highlightthickness=0, bd=0
        )
        online_dot.pack(side=tk.LEFT, padx=(0, 6))
        online_label = tk.Label(
            online_inner,
            text=self.i18n.t("online"),
            bg=BG_RAISED,
            fg=FG,
            font=("Segoe UI", 9),
            cursor="hand2",
        )
        online_label.pack(side=tk.LEFT)
        for wdg in (online_wrap, online_inner, online_dot, online_label):
            wdg.bind("<Button-1>", lambda _e: on_online())

        btn_dash = self._mk_btn(
            left_bar,
            tk,
            self.i18n.t("dashboard"),
            lambda: webbrowser.open(DASHBOARD_URL),
            pill=True,
        )
        btn_dash.pack(side=tk.LEFT, padx=(0, 6))

        btn_statusbar = self._mk_btn(
            left_bar,
            tk,
            self.i18n.t("install_statusbar_short"),
            self._on_install_statusbar,
        )
        btn_statusbar.pack(side=tk.LEFT)

        # Курс ЦБ + настройка интервала опроса (60–3600 с)
        mid_bar = tk.Frame(toolbar, bg=BG)
        mid_bar.pack(side=tk.LEFT, padx=(16, 0))
        rate_label = tk.Label(
            mid_bar,
            text=self._rate_text(self.snapshot),
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 9),
        )
        rate_label.pack(side=tk.LEFT, padx=(0, 12))
        tk.Label(
            mid_bar,
            text=self.i18n.t("refresh_sec"),
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT, padx=(0, 4))
        refresh_var = tk.StringVar(value=str(self.refresh_interval_sec))
        spin = tk.Spinbox(
            mid_bar,
            from_=REFRESH_MIN,
            to=REFRESH_MAX,
            increment=30,
            width=5,
            textvariable=refresh_var,
            bg=BG_RAISED,
            fg=FG,
            buttonbackground=BG_RAISED,
            relief="flat",
            font=("Segoe UI", 9),
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        spin.pack(side=tk.LEFT)

        def _on_refresh_commit(_event: Any = None) -> None:
            self._apply_refresh_interval(refresh_var.get())
            refresh_var.set(str(self.refresh_interval_sec))

        spin.bind("<Return>", _on_refresh_commit)
        spin.bind("<FocusOut>", _on_refresh_commit)

        lang_wrap = tk.Frame(toolbar, bg=BG_RAISED, cursor="hand2")
        lang_wrap.pack(side=tk.RIGHT)
        lang_pad = tk.Frame(lang_wrap, bg=BG_RAISED, padx=8, pady=5)
        lang_pad.pack()
        lang_canvas = tk.Canvas(
            lang_pad, width=28, height=18, bg=BG_RAISED, highlightthickness=0, bd=0, cursor="hand2"
        )
        lang_canvas.pack()
        for wdg in (lang_wrap, lang_pad, lang_canvas):
            wdg.bind("<Button-1>", lambda _e: on_lang())

        # ── Welcome ──
        head = tk.Frame(outer, bg=BG)
        head.pack(fill=tk.X)
        title = ttk.Label(head, text=self.i18n.t("welcome"), style="Hero.TLabel")
        title.pack(side=tk.LEFT)
        subtitle = ttk.Label(head, text="", style="Muted.TLabel")
        subtitle.pack(side=tk.LEFT, padx=(14, 0), pady=(8, 0))

        # ── Верхний ряд: две равные карточки (grid + uniform → без прыжков) ──
        top = tk.Frame(outer, bg=BG)
        top.pack(fill=tk.X, pady=(14, 10))
        top.grid_columnconfigure(0, weight=1, uniform="cards")
        top.grid_columnconfigure(1, weight=1, uniform="cards")
        top.grid_rowconfigure(0, weight=1)

        plan_card = self._card(top, tk)
        bal_card = self._card(top, tk)
        plan_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        bal_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        # ── Нижняя карточка: heatmap на всю ширину ──
        heat_card = self._card(outer, tk)
        heat_card.pack(fill=tk.BOTH, expand=True)

        self._popup_widgets = {
            "root": root,
            "title": title,
            "subtitle": subtitle,
            "plan_card": plan_card,
            "bal_card": bal_card,
            "heat_card": heat_card,
            "rate_label": rate_label,
            "refresh_var": refresh_var,
            "btn_refresh": btn_refresh,
            "btn_dash": btn_dash,
            "btn_statusbar": btn_statusbar,
            "btn_upgrade": None,
            "online_dot": online_dot,
            "online_label": online_label,
            "lang_canvas": lang_canvas,
            "tk": tk,
            "ttk": ttk,
        }

        self._paint_lang_flag()
        self._update_online_indicator()

        with self._lock:
            snap = self.snapshot
        try:
            self._render_popup_content(snap)
        except Exception:
            pass

        try:
            root.mainloop()
        finally:
            self._popup_root = None
            self._popup_widgets = {}

    def _on_popup_close(self) -> None:
        root = self._popup_root
        if root is None:
            return
        try:
            root.withdraw()
        except Exception:
            pass

    def _clear(self, frame: Any) -> None:
        for child in frame.winfo_children():
            child.destroy()

    def _render_popup_content(self, snap: UsageSnapshot) -> None:
        w = self._popup_widgets
        if not w:
            return
        root = w.get("root")
        if root is None:
            return
        try:
            if not root.winfo_exists():
                return
        except Exception:
            return

        tk = w["tk"]
        i = self.i18n
        plan_card = w["plan_card"]
        bal_card = w["bal_card"]
        heat_card = w["heat_card"]

        try:
            w["title"].configure(text=self.i18n.t("welcome"))
            msg = translate_display_message(snap.display_message, i.lang)
            w["subtitle"].configure(text=msg)

            self._clear(plan_card)
            self._clear(bal_card)
            self._clear(heat_card)

            if snap.error:
                tk.Label(
                    plan_card,
                    text=snap.error,
                    bg=BG_CARD,
                    fg=ERR_RED,
                    font=("Segoe UI", 10),
                    wraplength=360,
                    justify="left",
                ).pack(anchor="w")
            else:
                self._fill_plan_card(plan_card, snap, tk)
                self._fill_balance_card(bal_card, snap, tk)
                self._fill_heat_card(heat_card, snap, tk)

            self._update_online_indicator()
            rate_lbl = w.get("rate_label")
            if rate_lbl is not None:
                rate_lbl.configure(text=self._rate_text(snap))
        except Exception:
            pass

    def _bar_white(self, parent: Any, tk: Any, percent: float, width: int = 320) -> None:
        """Тонкий белый прогресс как в Current plan на скрине."""
        pct = max(0.0, min(100.0, float(percent)))
        h = 3
        canvas = tk.Canvas(parent, width=width, height=h, bg=BG_CARD, highlightthickness=0, bd=0)
        canvas.pack(anchor="w", pady=(10, 8))
        canvas.create_rectangle(0, 0, width, h, fill=TRACK, outline="")
        fw = int(width * pct / 100.0)
        if fw > 0:
            canvas.create_rectangle(0, 0, max(fw, 2), h, fill=FG, outline="")

    def _fill_plan_card(self, parent: Any, snap: UsageSnapshot, tk: Any) -> None:
        i = self.i18n
        week_pct = float(
            (
                snap.weekly_percent
                if snap.weekly_enabled and snap.weekly_percent is not None
                else snap.auto_percent
                if snap.auto_percent is not None
                else snap.total_percent
            )
            or 0.0
        )

        head = tk.Frame(parent, bg=BG_CARD)
        head.pack(fill=tk.X)
        tk.Label(
            head,
            text=i.t("current_plan"),
            bg=BG_CARD,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)
        btn = self._mk_btn(
            head,
            tk,
            i.t("open_upgrade"),
            lambda: webbrowser.open(DASHBOARD_URL),
            pill=True,
            padx=12,
        )
        btn.pack(side=tk.RIGHT)
        self._popup_widgets["btn_upgrade"] = btn

        tk.Label(
            parent,
            text=snap.plan_name or "Cursor",
            bg=BG_CARD,
            fg=FG,
            font=("Segoe UI Semibold", 20),
        ).pack(anchor="w", pady=(10, 0))

        tk.Label(
            parent,
            text=i.t("pct_used", pct=week_pct),
            bg=BG_CARD,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(4, 0))

        self._bar_white(parent, tk, week_pct, width=340)

        # Лимит пула: $ и ₽ (как раньше — это главное, не выкидываем)
        if snap.limit.cents > 0 or snap.weekly_limit.cents > 0:
            used_m = snap.weekly_used if snap.weekly_enabled and snap.weekly_limit.cents else snap.used
            lim_m = snap.weekly_limit if snap.weekly_enabled and snap.weekly_limit.cents else snap.limit
            # Если weekly $ пустые — берём месячный included
            if lim_m.cents <= 0:
                used_m, lim_m = snap.used, snap.limit
            tk.Label(
                parent,
                text=i.t(
                    "limit_line",
                    used_usd=used_m.format_usd(),
                    limit_usd=lim_m.format_usd(),
                    used_rub=used_m.format_rub(),
                    limit_rub=lim_m.format_rub(),
                ),
                bg=BG_CARD,
                fg=FG,
                font=("Segoe UI", 9),
            ).pack(anchor="w", pady=(2, 0))
            rem = snap.weekly_remaining if snap.weekly_enabled and snap.weekly_limit.cents else snap.remaining
            if rem.cents or lim_m.cents:
                tk.Label(
                    parent,
                    text=i.t(
                        "remaining_line",
                        usd=rem.format_usd(),
                        rub=rem.format_rub(),
                    ),
                    bg=BG_CARD,
                    fg=MUTED,
                    font=("Segoe UI", 8),
                ).pack(anchor="w", pady=(2, 0))
        else:
            tk.Label(
                parent,
                text=i.t("no_money"),
                bg=BG_CARD,
                fg=MUTED,
                font=("Segoe UI", 8),
            ).pack(anchor="w", pady=(2, 0))

        reset = snap.weekly_resets_at or snap.cycle_end
        reset_s = reset.strftime("%d.%m") if reset else "—"
        kind = i.t("weekly_included") if snap.weekly_enabled else i.t("monthly_included")
        tk.Label(
            parent,
            text=f"{kind}  ·  {i.t('resets_on', date=reset_s)}",
            bg=BG_CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(6, 0))

    def _fill_balance_card(self, parent: Any, snap: UsageSnapshot, tk: Any) -> None:
        i = self.i18n

        head = tk.Frame(parent, bg=BG_CARD)
        head.pack(fill=tk.X)
        tk.Label(
            head,
            text=i.t("account_balance"),
            bg=BG_CARD,
            fg=MUTED,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)

        # Потрачено за период подписки — $ и ₽ крупно
        used_usd = snap.used.format_usd()
        used_rub = snap.used.format_rub()
        tk.Label(
            parent,
            text=i.t("spend_period", usd=used_usd, rub=used_rub),
            bg=BG_CARD,
            fg=FG,
            font=("Segoe UI Semibold", 14),
        ).pack(anchor="w", pady=(12, 0))

        if snap.limit.cents > 0:
            tk.Label(
                parent,
                text=i.t(
                    "limit_line",
                    used_usd=snap.used.format_usd(),
                    limit_usd=snap.limit.format_usd(),
                    used_rub=snap.used.format_rub(),
                    limit_rub=snap.limit.format_rub(),
                ),
                bg=BG_CARD,
                fg=MUTED,
                font=("Segoe UI", 9),
            ).pack(anchor="w", pady=(6, 0))
            tk.Label(
                parent,
                text=i.t(
                    "remaining_line",
                    usd=snap.remaining.format_usd(),
                    rub=snap.remaining.format_rub(),
                ),
                bg=BG_CARD,
                fg=MUTED,
                font=("Segoe UI", 8),
            ).pack(anchor="w", pady=(2, 0))

        if snap.cycle_start and snap.cycle_end:
            tk.Label(
                parent,
                text=i.t(
                    "period_range",
                    start=snap.cycle_start.strftime("%d.%m.%Y"),
                    end=snap.cycle_end.strftime("%d.%m.%Y"),
                ),
                bg=BG_CARD,
                fg=MUTED,
                font=("Segoe UI", 8),
            ).pack(anchor="w", pady=(8, 0))

        api_pct = float(snap.api_percent or 0.0)
        mt = snap.month_tokens
        tk.Label(
            parent,
            text=(
                f"{i.t('api_usage')}: {api_pct:.0f}%  ·  "
                f"{i.t('tokens')}: Σ {_fmt_tok(mt.total_billable_ish)} "
                f"(in {_fmt_tok(mt.input_tokens)} / out {_fmt_tok(mt.output_tokens)})"
            ),
            bg=BG_CARD,
            fg=MUTED,
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(8, 0))

    def _fill_heat_card(self, parent: Any, snap: UsageSnapshot, tk: Any) -> None:
        """Активность: Полностью (год как в ЛК) / Неделя (компактные строки)."""
        i = self.i18n
        year_days = snap.year_days or snap.days
        # Для полного вида считаем «line edits» ≈ локальные события
        year_values = [float(d.local_events or d.local_requests) for d in year_days]
        total_v = int(sum(year_values)) if year_values else 0

        head = tk.Frame(parent, bg=BG_CARD)
        head.pack(fill=tk.X)
        left_h = tk.Frame(head, bg=BG_CARD)
        left_h.pack(side=tk.LEFT)
        tk.Label(
            left_h, text=i.t("activity_edits"), bg=BG_CARD, fg=MUTED, font=("Segoe UI", 9)
        ).pack(anchor="w")
        tk.Label(
            left_h,
            text=_fmt_tok(total_v) if total_v else "0",
            bg=BG_CARD,
            fg=FG,
            font=("Segoe UI Semibold", 18),
        ).pack(anchor="w")

        tabs = tk.Frame(head, bg=BG_RAISED)
        tabs.pack(side=tk.RIGHT, anchor="n")

        def _set_tab(name: str) -> None:
            if self._activity_tab == name:
                return
            self._activity_tab = name
            heat = self._popup_widgets.get("heat_card")
            if heat is None:
                return
            self._clear(heat)
            self._fill_heat_card(heat, snap, tk)

        for key, label in (("full", i.t("tab_full")), ("week", i.t("tab_week"))):
            active = self._activity_tab == key
            tk.Button(
                tabs,
                text=label,
                command=lambda k=key: _set_tab(k),
                bg="#2a2a2a" if active else BG_RAISED,
                fg=FG if active else MUTED,
                activebackground=HOVER,
                activeforeground=FG,
                relief="flat",
                bd=0,
                padx=12,
                pady=4,
                font=("Segoe UI Semibold", 8) if active else ("Segoe UI", 8),
                cursor="hand2",
                highlightthickness=0,
            ).pack(side=tk.LEFT, padx=1, pady=1)

        body = tk.Frame(parent, bg=BG_CARD)
        body.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        if self._activity_tab == "week":
            self._fill_week_tab(body, snap, tk)
        else:
            self._fill_full_tab(body, snap, tk, year_days, year_values)

    def _fill_full_tab(
        self,
        body: Any,
        snap: UsageSnapshot,
        tk: Any,
        year_days: list[DayBucket],
        values: list[float],
    ) -> None:
        """Годовой contribution graph как AI line edits в ЛК + лимит цикла."""
        i = self.i18n
        tip_var = tk.StringVar(value=i.t("hover_day"))
        max_v = max(values) if values else 0.0

        # Лимит подписки (компактно, одной строкой)
        limit_bits: list[str] = [i.t("cycle_calendar")]
        if snap.cycle_start and snap.cycle_end:
            limit_bits.append(
                f"{snap.cycle_start.strftime('%d.%m')}→{snap.cycle_end.strftime('%d.%m.%Y')}"
            )
        if snap.limit.cents > 0:
            limit_bits.append(
                f"{snap.used.format_usd()}/{snap.limit.format_usd()} · "
                f"{snap.used.format_rub()}/{snap.limit.format_rub()}"
            )
        tk.Label(
            body, text="  ·  ".join(limit_bits), bg=BG_CARD, fg=MUTED, font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(0, 4))

        if not year_days:
            tk.Label(
                body, text=i.t("no_data"), bg=BG_CARD, fg=MUTED, font=("Segoe UI", 9)
            ).pack(anchor="w")
            return

        cells = {d.date: (d, v) for d, v in zip(year_days, values)}
        first = date_cls.fromisoformat(year_days[0].date)
        last = date_cls.fromisoformat(year_days[-1].date)
        grid_start = first.fromordinal(first.toordinal() - first.weekday())
        # Ровно YEAR_WEEKS колонок
        grid_end = grid_start.fromordinal(grid_start.toordinal() + YEAR_WEEKS * 7 - 1)

        canvas = tk.Canvas(
            body,
            width=YEAR_CANVAS_W,
            height=YEAR_CANVAS_H,
            bg=BG_CARD,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(anchor="w")

        # Подписи месяцев над колонками (как в ЛК)
        months = (
            "mo_jan", "mo_feb", "mo_mar", "mo_apr", "mo_may", "mo_jun",
            "mo_jul", "mo_aug", "mo_sep", "mo_oct", "mo_nov", "mo_dec",
        )
        drawn_months: set[tuple[int, int]] = set()
        cur = grid_start
        while cur <= grid_end:
            week_i = (cur.toordinal() - grid_start.toordinal()) // 7
            if week_i >= YEAR_WEEKS:
                break
            if cur.day <= 7:
                key_m = (cur.year, cur.month)
                if key_m not in drawn_months:
                    drawn_months.add(key_m)
                    x = week_i * (YEAR_CELL + YEAR_PAD) + 2
                    canvas.create_text(
                        x,
                        6,
                        text=i.t(months[cur.month - 1]),
                        fill=MUTED,
                        font=("Segoe UI", 7),
                        anchor="w",
                    )
            cur = cur.fromordinal(cur.toordinal() + 1)

        day_rects: dict[int, str] = {}
        cur = grid_start
        while cur <= grid_end:
            week_i = (cur.toordinal() - grid_start.toordinal()) // 7
            if week_i >= YEAR_WEEKS:
                break
            row = cur.weekday()  # Пн=0 … Вс=6
            x0 = week_i * (YEAR_CELL + YEAR_PAD) + 2
            y0 = YEAR_MONTH_H + row * (YEAR_CELL + YEAR_PAD) + 2
            key = cur.isoformat()
            info = cells.get(key)
            if info is None or cur < first or cur > last:
                fill = HEAT[0] if first <= cur <= last else BG
                day_obj = None
                intens = 0.0
            else:
                day_obj, val = info
                intens = (val / max_v) if max_v > 0 else 0.0
                fill = _heat_color(intens)
            outline = "#555555" if (day_obj and day_obj.is_today) else fill
            rid = canvas.create_rectangle(
                x0, y0, x0 + YEAR_CELL, y0 + YEAR_CELL,
                fill=fill, outline=outline, width=1,
            )
            day_rects[rid] = key
            cur = cur.fromordinal(cur.toordinal() + 1)

        def _on_move(event: Any) -> None:
            for item in canvas.find_overlapping(event.x, event.y, event.x, event.y):
                key = day_rects.get(item)
                if not key:
                    continue
                info = cells.get(key)
                if not info:
                    tip_var.set(f"{key}: {i.t('no_data')}")
                    return
                tip_var.set(_day_tip(info[0], snap, i))
                return

        canvas.bind("<Motion>", _on_move)

        # Легенда + tip в одной строке
        foot = tk.Frame(body, bg=BG_CARD)
        foot.pack(fill=tk.X, pady=(6, 0))
        tk.Label(foot, text=i.t("less"), bg=BG_CARD, fg=MUTED, font=("Segoe UI", 7)).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        for color in HEAT:
            c = tk.Canvas(foot, width=9, height=9, bg=BG_CARD, highlightthickness=0, bd=0)
            c.pack(side=tk.LEFT, padx=1)
            c.create_rectangle(0, 0, 9, 9, fill=color, outline="")
        tk.Label(foot, text=i.t("more"), bg=BG_CARD, fg=MUTED, font=("Segoe UI", 7)).pack(
            side=tk.LEFT, padx=(3, 12)
        )
        tk.Label(
            foot, textvariable=tip_var, bg=BG_CARD, fg=MUTED, font=("Segoe UI", 8)
        ).pack(side=tk.LEFT)

        # Статы в ряд — как на скрине ЛК
        most_day, longest, current = _streak_stats_days(year_days, values)
        most_month = _most_active_month(year_days, values, i)
        stats = tk.Frame(body, bg=BG_CARD)
        stats.pack(fill=tk.X, pady=(10, 0))
        for col, (label, value) in enumerate(
            (
                (i.t("most_active_month"), most_month),
                (i.t("most_active_day"), most_day or "—"),
                (i.t("longest_streak"), i.t("days_n", n=longest)),
                (i.t("current_streak"), i.t("days_n", n=current)),
            )
        ):
            cell = tk.Frame(stats, bg=BG_CARD)
            cell.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0 if col == 0 else 8, 0))
            tk.Label(cell, text=label, bg=BG_CARD, fg=MUTED, font=("Segoe UI", 8)).pack(
                anchor="w"
            )
            tk.Label(
                cell, text=value, bg=BG_CARD, fg=FG, font=("Segoe UI Semibold", 11)
            ).pack(anchor="w")

    def _fill_week_tab(self, body: Any, snap: UsageSnapshot, tk: Any) -> None:
        """Неделя подписки: 7 компактных строк — всё влезает в окно без скролла."""
        i = self.i18n
        tk.Label(
            body, text=i.t("week_detail"), bg=BG_CARD, fg=MUTED, font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(0, 4))

        week_days = _current_week_days(snap)
        if not week_days:
            tk.Label(
                body, text=i.t("no_data"), bg=BG_CARD, fg=MUTED, font=("Segoe UI", 9)
            ).pack(anchor="w")
            return

        max_v = max((_day_value(d, snap.days_source) for d in week_days), default=0.0) or 1.0
        wd_names = i.weekdays()
        bar_w = 200

        for idx, day in enumerate(week_days):
            val = _day_value(day, snap.days_source)
            try:
                d = date_cls.fromisoformat(day.date)
                left = f"{wd_names[d.weekday()]} {d.strftime('%d.%m')}"
            except ValueError:
                left = day.date
            if day.is_today:
                left = f"{left}*"

            row_bg = BG_RAISED if idx % 2 == 0 else BG_CARD
            row = tk.Frame(body, bg=row_bg)
            row.pack(fill=tk.X, pady=1)

            tk.Label(
                row, text=left, bg=row_bg, fg=FG, font=("Segoe UI Semibold", 9), width=10, anchor="w"
            ).pack(side=tk.LEFT, padx=(6, 4), pady=3)

            bar = tk.Canvas(row, width=bar_w, height=5, bg=row_bg, highlightthickness=0)
            bar.pack(side=tk.LEFT, padx=(0, 8))
            bar.create_rectangle(0, 0, bar_w, 5, fill=TRACK, outline="")
            fw = int(bar_w * min(1.0, val / max_v))
            if fw > 0:
                bar.create_rectangle(0, 0, max(fw, 2), 5, fill=HEAT[3], outline="")

            spend = Money(cents=day.spend_cents, usd_rub_rate=snap.usd_rub_rate)
            bits = [
                f"{day.local_requests} req",
                f"{day.local_events} ev",
            ]
            if day.tokens.total_billable_ish:
                bits.append(
                    f"Σ{_fmt_tok(day.tokens.total_billable_ish)} "
                    f"(in {_fmt_tok(day.tokens.input_tokens)}/"
                    f"out {_fmt_tok(day.tokens.output_tokens)})"
                )
            if day.spend_cents:
                bits.append(f"{spend.format_usd()}/{spend.format_rub()}")
            tk.Label(
                row,
                text="  ·  ".join(bits),
                bg=row_bg,
                fg=MUTED,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

def _day_value(day: DayBucket, source: str) -> float:
    if source == "api" and day.tokens.total_billable_ish > 0:
        return float(day.tokens.total_billable_ish)
    if day.tokens.total_billable_ish > 0:
        return float(day.tokens.total_billable_ish)
    return float(day.local_requests or day.local_events)


def _heat_color(intensity: float) -> str:
    if intensity <= 0:
        return HEAT[0]
    t = min(1.0, intensity)
    idx = 1 + int(t * (len(HEAT) - 2))
    return HEAT[min(idx, len(HEAT) - 1)]


def _day_tip(day: DayBucket, snap: UsageSnapshot, i: I18n) -> str:
    parts = [day.date]
    if day.tokens.total_billable_ish:
        parts.append(f"{_fmt_tok(day.tokens.total_billable_ish)} tok")
    if day.local_requests or day.local_events:
        parts.append(
            f"{i.t('day_requests')}: {day.local_requests}, "
            f"{i.t('day_events')}: {day.local_events}"
        )
    if day.spend_cents:
        m = Money(cents=day.spend_cents, usd_rub_rate=snap.usd_rub_rate)
        parts.append(f"{m.format_usd()} / {m.format_rub()}")
    if len(parts) == 1:
        return f"{day.date}: {i.t('no_data')}"
    return " · ".join(parts)


def _current_week_days(snap: UsageSnapshot) -> list[DayBucket]:
    """Пн–вс недели подписки; мержим year_days + cycle days (токены/$)."""
    from datetime import timedelta

    today = date_cls.today()
    if snap.weekly_enabled and snap.cycle_start:
        start = snap.cycle_start.astimezone().date()
        if (today - start).days > 7 or (today - start).days < 0:
            start = today - timedelta(days=today.weekday())
    else:
        start = today - timedelta(days=today.weekday())

    by_date = {d.date: d for d in snap.year_days}
    # Данные цикла (API-токены / spend) важнее — перекрывают локальные
    for d in snap.days:
        prev = by_date.get(d.date)
        if prev is None:
            by_date[d.date] = d
        else:
            by_date[d.date] = DayBucket(
                date=d.date,
                tokens=d.tokens if d.tokens.total_billable_ish else prev.tokens,
                spend_cents=d.spend_cents or prev.spend_cents,
                local_requests=max(d.local_requests, prev.local_requests),
                local_events=max(d.local_events, prev.local_events),
                source=d.source if d.source != "none" else prev.source,
                is_today=d.is_today or prev.is_today,
            )

    out: list[DayBucket] = []
    for i in range(7):
        d = start + timedelta(days=i)
        key = d.isoformat()
        if key in by_date:
            out.append(by_date[key])
        else:
            out.append(DayBucket(date=key, is_today=(d == today)))
    return out


def _streak_stats_days(
    days: list[DayBucket], values: list[float]
) -> tuple[str | None, int, int]:
    """Самый активный день + серии по ненулевым дням."""
    if not days or not values:
        return None, 0, 0
    max_i = max(range(len(values)), key=lambda i: values[i])
    most = days[max_i].date if values[max_i] > 0 else None
    if most:
        try:
            d = date_cls.fromisoformat(most)
            most = d.strftime("%b %d, %Y")
        except ValueError:
            pass

    longest = current = run = 0
    for v in values:
        if v > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    run = 0
    for v in reversed(values):
        if v > 0:
            run += 1
        else:
            break
    current = run
    return most, longest, current


def _most_active_month(days: list[DayBucket], values: list[float], i: I18n) -> str:
    months = (
        "mo_jan", "mo_feb", "mo_mar", "mo_apr", "mo_may", "mo_jun",
        "mo_jul", "mo_aug", "mo_sep", "mo_oct", "mo_nov", "mo_dec",
    )
    totals: dict[int, float] = {}
    for day, val in zip(days, values):
        try:
            m = date_cls.fromisoformat(day.date).month
        except ValueError:
            continue
        totals[m] = totals.get(m, 0.0) + val
    if not totals or max(totals.values()) <= 0:
        return "—"
    best = max(totals, key=lambda m: totals[m])
    return i.t(months[best - 1]).title()


def _fmt_tok(n: int | None) -> str:
    if n is None:
        return "—"
    abs_n = abs(n)
    if abs_n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if abs_n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}".replace(",", " ")


def run_tray(cfg: AppConfig) -> None:
    TrayController(cfg).start()
