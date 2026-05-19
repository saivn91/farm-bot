"""
App - cua so chinh cua Farm Bot.
"""
import logging
import customtkinter as ctk
from typing import List

from core.models import BotInstance
from core.farm_engine import FarmEngine
import core.config as config

from ui.dashboard import Dashboard
from ui.log_panel import LogPanel
from ui.settings import SettingsPanel

logger = logging.getLogger(__name__)

MAX_INSTANCES = 4

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Farm Bot")
        self.geometry("980x660")
        self.minsize(820, 560)

        self.instances: List[BotInstance] = []
        self.engines:   dict[int, FarmEngine] = {}
        self.settings:  dict = {}

        self._load_config()
        ctk.set_appearance_mode(self.settings.get("theme", "dark"))
        ctk.set_default_color_theme("blue")

        self._build_ui()
        self.after(1000, self._tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_config(self):
        self.instances, self.settings = config.load()

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        hdr = ctk.CTkFrame(self, height=50, corner_radius=0, fg_color="#1a1a2e")
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_propagate(False)
        ctk.CTkLabel(hdr, text="  Farm Bot", font=ctk.CTkFont(size=19, weight="bold"), text_color="#aaddff").pack(side="left", padx=8)
        ctk.CTkLabel(hdr, text="1280x720", font=ctk.CTkFont(size=11), text_color="gray55").pack(side="right", padx=12)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.tabs.add("Dashboard")
        self.tabs.add("Cài đặt")
        self.tabs.add("Log")

        self.dashboard = Dashboard(self.tabs.tab("Dashboard"), self.instances, on_start=self._on_start, on_stop=self._on_stop)
        self.dashboard.pack(fill="both", expand=True)

        self.settings_panel = SettingsPanel(self.tabs.tab("Cài đặt"), self.instances, self.settings, on_save=self._on_save, on_add=self._on_add, on_remove=self._on_remove, on_test_adb=self._on_test_adb)
        self.settings_panel.pack(fill="both", expand=True)

        self.log_panel = LogPanel(self.tabs.tab("Log"), self.instances)
        self.log_panel.pack(fill="both", expand=True)

    def _on_start(self, inst_id: int):
        inst = self._get(inst_id)
        if inst is None or inst.is_running: return
        engine = FarmEngine(inst, on_log=lambda msg: self.after(0, lambda: self.log_panel.append(inst_id, msg)))
        self.engines[inst_id] = engine
        engine.start()

    def _on_stop(self, inst_id: int):
        engine = self.engines.get(inst_id)
        if engine: engine.stop()

    def _on_save(self):
        config.save(self.instances, self.settings)
        # Ép làm mới toàn cục ngay khi lưu
        self._refresh_all()

    def _on_add(self):
        if len(self.instances) >= MAX_INSTANCES: return
        new_id = max((i.id for i in self.instances), default=-1) + 1
        inst = BotInstance(id=new_id, emu_index=new_id, adb_path=self.settings.get("adb_path", "adb"))
        self.instances.append(inst)
        self._refresh_all()

    def _on_remove(self, inst_id: int):
        eng = self.engines.pop(inst_id, None)
        if eng: eng.stop()
        self.instances = [i for i in self.instances if i.id != inst_id]
        self._refresh_all()

    def _on_test_adb(self, inst_id: int) -> str:
        inst = self._get(inst_id)
        if inst is None: return "Không tìm thấy giả lập."
        
        serial_to_test = inst.adb_serial
        if serial_to_test and serial_to_test.isdigit():
            serial_to_test = f"127.0.0.1:{serial_to_test}"
            
        from core.adb import AdbController
        adb = AdbController(adb_path=inst.adb_path, serial=serial_to_test)
        ok, msg = adb.full_connect()
        
        if ok:
            # Ghi đè lại đúng cổng đã nhận vào giao diện cho người dùng thấy
            inst.adb_serial = adb.serial
            self.after(0, self.settings_panel.refresh_instances, self.instances)
            
        return msg

    def _on_close(self):
        for eng in self.engines.values():
            try: eng.stop()
            except Exception: pass
        self.destroy()

    def _tick(self):
        self.dashboard.update_cards()
        self.after(1000, self._tick)

    def _get(self, inst_id: int) -> BotInstance | None:
        for i in self.instances:
            if i.id == inst_id: return i
        return None

    def _refresh_all(self):
        self.dashboard.refresh_instances(self.instances)
        self.settings_panel.refresh_instances(self.instances)
        self.log_panel.refresh_instances(self.instances)