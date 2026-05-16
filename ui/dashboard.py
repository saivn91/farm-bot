"""
Dashboard - hien thi tung instance bot duoi dang card.
Moi card co: status, crop selector, progress bars, countdown, buttons.
"""
import customtkinter as ctk
from typing import Callable
from core.models import BotInstance, BotStatus, CropType

# Mau sac cho tung trang thai
_STATUS_COLOR: dict[str, str] = {
    BotStatus.IDLE:       "#555566",
    BotStatus.RUNNING:    "#226633",
    BotStatus.SCANNING:   "#886600",
    BotStatus.HARVESTING: "#115599",
    BotStatus.PLANTING:   "#226655",
    BotStatus.SELLING:    "#664488",
    BotStatus.WAITING:    "#444455",
    BotStatus.ERROR:      "#882222",
    BotStatus.STOPPED:    "#333344",
}

_CROP_LABELS: dict[CropType, str] = {
    CropType.LUA: "Lua (2 phut)",
}


class InstanceCard(ctk.CTkFrame):
    """Card hien thi trang thai 1 instance bot."""

    def __init__(
        self,
        parent,
        inst:     BotInstance,
        on_start: Callable[[int], None],
        on_stop:  Callable[[int], None],
        on_scan:  Callable[[int], None],
        **kwargs,
    ):
        super().__init__(parent, corner_radius=10, border_width=1, **kwargs)
        self.inst     = inst
        self.on_start = on_start
        self.on_stop  = on_stop
        self.on_scan  = on_scan
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        # ── Hang 0: tieu de + badge trang thai ───────────────────────────────
        row0 = ctk.CTkFrame(self, fg_color="transparent")
        row0.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            row0,
            text=f"Instance #{self.inst.id}",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")

        self._status_lbl = ctk.CTkLabel(
            row0, text=self.inst.status,
            width=100, corner_radius=6,
            fg_color=_STATUS_COLOR.get(self.inst.status, "#444444"),
            font=ctk.CTkFont(size=11),
        )
        self._status_lbl.pack(side="right")

        # ── Hang 1: chon cay + countdown ─────────────────────────────────────
        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.grid(row=1, column=0, sticky="ew", padx=12, pady=2)

        ctk.CTkLabel(row1, text="Cay:").pack(side="left")
        self._crop_var = ctk.StringVar(
            value=_CROP_LABELS.get(self.inst.crop_mode, "Lua (2 phut)")
        )
        ctk.CTkComboBox(
            row1,
            values=list(_CROP_LABELS.values()),
            variable=self._crop_var,
            width=140,
            command=self._on_crop_change,
        ).pack(side="left", padx=(6, 16))

        self._countdown_lbl = ctk.CTkLabel(
            row1, text="", font=ctk.CTkFont(size=11), text_color="gray70"
        )
        self._countdown_lbl.pack(side="left")

        # ── Hang 2: progress bars ─────────────────────────────────────────────
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.grid(row=2, column=0, sticky="ew", padx=12, pady=4)
        row2.grid_columnconfigure((1, 4), weight=1)

        ctk.CTkLabel(row2, text="Chin:", font=ctk.CTkFont(size=11), width=42).grid(
            row=0, column=0, sticky="w")
        self._pb_grown = ctk.CTkProgressBar(row2, height=12, corner_radius=4)
        self._pb_grown.set(0)
        self._pb_grown.grid(row=0, column=1, sticky="ew", padx=(4, 6))
        self._pb_grown_lbl = ctk.CTkLabel(
            row2, text="0%", width=38, font=ctk.CTkFont(size=11))
        self._pb_grown_lbl.grid(row=0, column=2)

        ctk.CTkLabel(row2, text="Trong:", font=ctk.CTkFont(size=11), width=48).grid(
            row=0, column=3, sticky="w", padx=(10, 0))
        self._pb_empty = ctk.CTkProgressBar(row2, height=12, corner_radius=4)
        self._pb_empty.set(0)
        self._pb_empty.grid(row=0, column=4, sticky="ew", padx=(4, 6))
        self._pb_empty_lbl = ctk.CTkLabel(
            row2, text="0%", width=38, font=ctk.CTkFont(size=11))
        self._pb_empty_lbl.grid(row=0, column=5)

        # ── Hang 3: debug checkbox ────────────────────────────────────────────
        row3 = ctk.CTkFrame(self, fg_color="transparent")
        row3.grid(row=3, column=0, sticky="ew", padx=12, pady=(2, 0))

        self._debug_var = ctk.BooleanVar(value=self.inst.debug_mode)
        ctk.CTkCheckBox(
            row3,
            text="Debug (luu anh nhan dien)",
            variable=self._debug_var,
            command=self._on_debug_toggle,
            font=ctk.CTkFont(size=11),
            checkbox_width=16,
            checkbox_height=16,
        ).pack(side="left")

        # ── Hang 4: buttons + stats ───────────────────────────────────────────
        row4 = ctk.CTkFrame(self, fg_color="transparent")
        row4.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 10))

        ctk.CTkButton(
            row4, text="Start", width=76,
            fg_color="#1e6e3a", hover_color="#155228",
            command=lambda: self.on_start(self.inst.id),
        ).pack(side="left", padx=(0, 5))

        ctk.CTkButton(
            row4, text="Stop", width=76,
            fg_color="#7a2c10", hover_color="#5c2008",
            command=lambda: self.on_stop(self.inst.id),
        ).pack(side="left", padx=(0, 5))

        ctk.CTkButton(
            row4, text="Quet Farm", width=96,
            fg_color="#2b2b3d", hover_color="#3a3a55",
            command=lambda: self.on_scan(self.inst.id),
        ).pack(side="left", padx=(0, 5))

        self._stats_lbl = ctk.CTkLabel(
            row4, text="", font=ctk.CTkFont(size=10), text_color="gray55"
        )
        self._stats_lbl.pack(side="right")

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_crop_change(self, val: str):
        for ctype, label in _CROP_LABELS.items():
            if label == val:
                self.inst.crop_mode = ctype
                break

    def _on_debug_toggle(self):
        self.inst.debug_mode = self._debug_var.get()

    # ── Refresh (goi moi giay tu App._tick) ──────────────────────────────────

    def refresh(self):
        inst = self.inst

        # Status badge
        color = _STATUS_COLOR.get(inst.status, "#444444")
        self._status_lbl.configure(text=inst.status, fg_color=color)

        # Countdown
        sec = inst.seconds_until_ready()
        if inst.is_running and sec > 0:
            m, s = divmod(sec, 60)
            self._countdown_lbl.configure(text=f"Thu hoach trong: {m}:{s:02d}")
        elif inst.is_running:
            self._countdown_lbl.configure(text="San sang thu hoach")
        else:
            self._countdown_lbl.configure(text="")

        # Progress bars
        self._pb_grown.set(min(inst.pct_grown / 100, 1.0))
        self._pb_empty.set(min(inst.pct_empty / 100, 1.0))
        self._pb_grown_lbl.configure(text=f"{inst.pct_grown:.0f}%")
        self._pb_empty_lbl.configure(text=f"{inst.pct_empty:.0f}%")

        # Stats
        self._stats_lbl.configure(
            text=(
                f"Gat: {inst.stats.total_harvest}  "
                f"Vong: {inst.stats.total_cycles}  "
                f"{inst.stats.session_duration()}"
            )
        )


# ── Dashboard container ───────────────────────────────────────────────────────

class Dashboard(ctk.CTkScrollableFrame):
    """Hien thi danh sach InstanceCard."""

    def __init__(
        self,
        parent,
        instances: list,
        on_start:  Callable[[int], None],
        on_stop:   Callable[[int], None],
        on_scan:   Callable[[int], None],
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self.on_start = on_start
        self.on_stop  = on_stop
        self.on_scan  = on_scan
        self._cards: dict[int, InstanceCard] = {}
        self.refresh_instances(instances)

    def refresh_instances(self, instances: list):
        for w in self.winfo_children():
            w.destroy()
        self._cards.clear()
        self.grid_columnconfigure(0, weight=1)
        for idx, inst in enumerate(instances):
            card = InstanceCard(
                self, inst,
                on_start=self.on_start,
                on_stop=self.on_stop,
                on_scan=self.on_scan,
            )
            card.grid(row=idx, column=0, sticky="ew", padx=8, pady=6)
            self._cards[inst.id] = card

    def update_cards(self):
        for card in self._cards.values():
            card.refresh()
