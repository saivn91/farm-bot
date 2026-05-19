"""
Dashboard - hiển thị từng instance bot dưới dạng card.
"""
import customtkinter as ctk
from typing import Callable
from core.models import BotInstance, BotStatus, CropType

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
    CropType.LUA: "Lúa (2 phút)",
}

class InstanceCard(ctk.CTkFrame):
    def __init__(self, parent, inst: BotInstance, on_start: Callable[[int], None], on_stop: Callable[[int], None], **kwargs):
        super().__init__(parent, corner_radius=10, border_width=1, **kwargs)
        self.inst     = inst
        self.on_start = on_start
        self.on_stop  = on_stop
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        row0 = ctk.CTkFrame(self, fg_color="transparent")
        row0.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))
        
        # HIỂN THỊ TÊN DO NGƯỜI DÙNG ĐẶT
        ctk.CTkLabel(row0, text=f"📱 {self.inst.get_display_name()}", font=ctk.CTkFont(size=14, weight="bold")).pack(side="left")

        self._status_lbl = ctk.CTkLabel(
            row0, text=self.inst.status, width=120, corner_radius=6,
            fg_color=_STATUS_COLOR.get(self.inst.status, "#444444"), font=ctk.CTkFont(size=11)
        )
        self._status_lbl.pack(side="right")

        row1 = ctk.CTkFrame(self, fg_color="transparent")
        row1.grid(row=1, column=0, sticky="ew", padx=12, pady=2)
        ctk.CTkLabel(row1, text="Cây trồng:").pack(side="left")
        self._crop_var = ctk.StringVar(value=_CROP_LABELS.get(self.inst.crop_mode, "Lúa (2 phút)"))
        ctk.CTkComboBox(row1, values=list(_CROP_LABELS.values()), variable=self._crop_var, width=140, command=self._on_crop_change).pack(side="left", padx=(6, 16))
        self._countdown_lbl = ctk.CTkLabel(row1, text="", font=ctk.CTkFont(size=11), text_color="gray70")
        self._countdown_lbl.pack(side="left")


        row3 = ctk.CTkFrame(self, fg_color="transparent")
        row3.grid(row=2, column=0, sticky="ew", padx=12, pady=(2, 0))
        self._debug_var = ctk.BooleanVar(value=self.inst.debug_mode)
        ctk.CTkCheckBox(row3, text="Gỡ lỗi (Lưu ảnh nhận diện AI)", variable=self._debug_var, command=self._on_debug_toggle, font=ctk.CTkFont(size=11), checkbox_width=16, checkbox_height=16).pack(side="left")

        row4 = ctk.CTkFrame(self, fg_color="transparent")
        row4.grid(row=3, column=0, sticky="ew", padx=12, pady=(4, 10))
        self._toggle_btn = ctk.CTkButton(row4, text="Bắt đầu", width=96, fg_color="#1e6e3a", hover_color="#155228", command=self._on_toggle)
        self._toggle_btn.pack(side="left", padx=(0, 5))
       
        self._stats_lbl = ctk.CTkLabel(row4, text="", font=ctk.CTkFont(size=10), text_color="gray55")
        self._stats_lbl.pack(side="right")

    def _on_crop_change(self, val: str):
        for ctype, label in _CROP_LABELS.items():
            if label == val:
                self.inst.crop_mode = ctype
                break

    def _on_toggle(self):
        if self.inst.is_running:
            self.on_stop(self.inst.id)
        else:
            self.on_start(self.inst.id)

    def _on_debug_toggle(self):
        self.inst.debug_mode = self._debug_var.get()

    def refresh(self):
        inst = self.inst
        self._status_lbl.configure(text=inst.status, fg_color=_STATUS_COLOR.get(inst.status, "#444444"))

        if inst.is_running:
            self._toggle_btn.configure(text="Dừng lại", fg_color="#7a2c10", hover_color="#5c2008")
        else:
            self._toggle_btn.configure(text="Bắt đầu", fg_color="#1e6e3a", hover_color="#155228")

        sec = inst.seconds_until_ready()
        if inst.is_running and sec > 0:
            m, s = divmod(sec, 60)
            self._countdown_lbl.configure(text=f"Thu hoạch sau: {m}:{s:02d}")
        elif inst.is_running:
            self._countdown_lbl.configure(text="Sẵn sàng thu hoạch")
        else:
            self._countdown_lbl.configure(text="")

        self._stats_lbl.configure(text=f"Đã gặt: {inst.stats.total_harvest}  Vòng: {inst.stats.total_cycles}  {inst.stats.session_duration()}")


class Dashboard(ctk.CTkScrollableFrame):
    def __init__(self, parent, instances: list, on_start: Callable[[int], None], on_stop: Callable[[int], None], **kwargs):
        super().__init__(parent, **kwargs)
        self.on_start = on_start
        self.on_stop  = on_stop
        self._cards: dict[int, InstanceCard] = {}
        self.refresh_instances(instances)

    def refresh_instances(self, instances: list):
        for w in self.winfo_children():
            w.destroy()
        self._cards.clear()
        self.grid_columnconfigure(0, weight=1)
        for idx, inst in enumerate(instances):
            card = InstanceCard(self, inst, on_start=self.on_start, on_stop=self.on_stop)
            card.grid(row=idx, column=0, sticky="ew", padx=8, pady=6)
            self._cards[inst.id] = card

    def update_cards(self):
        for card in self._cards.values():
            card.refresh()