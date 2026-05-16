"""
Settings Panel - form cai dat toan cuc va tung instance.
"""
import customtkinter as ctk
from tkinter import messagebox, filedialog
from typing import Callable, List

from core.models import BotInstance

MAX_INSTANCES = 4


class SettingsPanel(ctk.CTkScrollableFrame):
    def __init__(
        self,
        parent,
        instances:    list,
        settings:     dict,
        on_save:      Callable,
        on_add:       Callable,
        on_remove:    Callable[[int], None],
        on_test_adb:  Callable[[int], str],
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        self.instances   = instances
        self.settings    = settings
        self.on_save     = on_save
        self.on_add      = on_add
        self.on_remove   = on_remove
        self.on_test_adb = on_test_adb
        self._inst_container: ctk.CTkFrame = None
        self._build()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        # ---- Cai dat chung ----
        glob = ctk.CTkFrame(self, corner_radius=8)
        glob.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        glob.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            glob, text="Cai dat chung",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4))

        ctk.CTkLabel(glob, text="Duong dan ADB:").grid(
            row=1, column=0, padx=12, pady=5, sticky="w")
        self._adb_var = ctk.StringVar(value=self.settings.get("adb_path", "adb"))
        ctk.CTkEntry(glob, textvariable=self._adb_var).grid(
            row=1, column=1, padx=6, pady=5, sticky="ew")
        ctk.CTkButton(
            glob, text="Browse", width=74,
            command=self._browse_adb,
        ).grid(row=1, column=2, padx=(0, 12), pady=5)

        ctk.CTkLabel(glob, text="Giao dien:").grid(
            row=2, column=0, padx=12, pady=5, sticky="w")
        self._theme_var = ctk.StringVar(value=self.settings.get("theme", "dark"))
        ctk.CTkComboBox(
            glob,
            values=["dark", "light", "system"],
            variable=self._theme_var,
            width=120,
        ).grid(row=2, column=1, padx=6, pady=5, sticky="w")

        ctk.CTkButton(
            glob, text="Luu cai dat",
            fg_color="#1e6e3a", hover_color="#155228",
            command=self._save,
        ).grid(row=3, column=0, columnspan=3, padx=12, pady=(4, 12), sticky="e")

        # ---- Tieu de instances ----
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 0))
        ctk.CTkLabel(
            hdr, text="Danh sach instance",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left")
        ctk.CTkButton(
            hdr, text="+ Them instance", width=130,
            fg_color="#2b2b3d", hover_color="#3a3a55",
            command=self._add_instance,
        ).pack(side="right")

        # ---- Container cac instance ----
        self._inst_container = ctk.CTkFrame(self, fg_color="transparent")
        self._inst_container.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        self._inst_container.grid_columnconfigure(0, weight=1)
        self.refresh_instances(self.instances)

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_instances(self, instances: list):
        self.instances = instances
        for w in self._inst_container.winfo_children():
            w.destroy()
        for row_idx, inst in enumerate(instances):
            frame = self._build_inst_row(self._inst_container, inst)
            frame.grid(row=row_idx, column=0, sticky="ew", pady=5)

    def _build_inst_row(self, parent, inst: BotInstance) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, corner_radius=8, border_width=1)
        f.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            f, text=f"Instance #{inst.id}",
            font=ctk.CTkFont(weight="bold"),
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 2))

        # LDPlayer index
        ctk.CTkLabel(f, text="LDPlayer Index:").grid(
            row=1, column=0, padx=12, pady=4, sticky="w")
        emu_var = ctk.StringVar(value=str(inst.emu_index))
        emu_e   = ctk.CTkEntry(f, textvariable=emu_var, width=60)
        emu_e.grid(row=1, column=1, padx=6, pady=4, sticky="w")
        emu_e.bind("<FocusOut>", lambda e, v=emu_var, i=inst: self._set_int(v, i, "emu_index"))

        # ADB serial
        ctk.CTkLabel(f, text="ADB Serial:").grid(
            row=2, column=0, padx=12, pady=4, sticky="w")
        ser_var = ctk.StringVar(value=inst.adb_serial)
        ser_e   = ctk.CTkEntry(
            f, textvariable=ser_var, width=200,
            placeholder_text="VD: 127.0.0.1:5554 (de trong = tu dong)")
        ser_e.grid(row=2, column=1, padx=6, pady=4, sticky="ew")
        ser_e.bind("<FocusOut>", lambda e, v=ser_var, i=inst: setattr(i, "adb_serial", v.get().strip()))

        # Enable shop
        ctk.CTkLabel(f, text="Cho phep ban hang:").grid(
            row=3, column=0, padx=12, pady=4, sticky="w")
        shop_var = ctk.BooleanVar(value=inst.enable_shop)
        ctk.CTkSwitch(
            f, variable=shop_var, text="",
            command=lambda v=shop_var, i=inst: setattr(i, "enable_shop", v.get()),
        ).grid(row=3, column=1, padx=6, pady=4, sticky="w")

        # Buttons
        btn_row = ctk.CTkFrame(f, fg_color="transparent")
        btn_row.grid(row=4, column=0, columnspan=3, sticky="ew", padx=12, pady=(2, 10))

        ctk.CTkButton(
            btn_row, text="Test ADB", width=82,
            fg_color="gray35", hover_color="gray45",
            command=lambda i=inst: self._test_adb(i),
        ).pack(side="left", padx=(0, 8))

        if len(self.instances) > 1:
            ctk.CTkButton(
                btn_row, text="Xoa", width=66,
                fg_color="#7a2c10", hover_color="#5c2008",
                command=lambda i=inst.id: self.on_remove(i),
            ).pack(side="right")

        return f

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse_adb(self):
        path = filedialog.askopenfilename(
            title="Chon file adb.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self._adb_var.set(path)

    def _test_adb(self, inst: BotInstance):
        result = self.on_test_adb(inst.id)
        messagebox.showinfo("Ket qua Test ADB", result)

    def _add_instance(self):
        if len(self.instances) >= MAX_INSTANCES:
            messagebox.showwarning("Gioi han", f"Toi da {MAX_INSTANCES} instance.")
            return
        self.on_add()

    def _save(self):
        self.settings["adb_path"] = self._adb_var.get().strip()
        self.settings["theme"]    = self._theme_var.get()
        for inst in self.instances:
            inst.adb_path = self.settings["adb_path"]
        ctk.set_appearance_mode(self.settings["theme"])
        self.on_save()
        messagebox.showinfo("Da luu", "Cai dat da duoc luu thanh cong.")

    @staticmethod
    def _set_int(var: ctk.StringVar, inst: BotInstance, attr: str):
        try:
            setattr(inst, attr, int(var.get()))
        except ValueError:
            var.set(str(getattr(inst, attr)))
