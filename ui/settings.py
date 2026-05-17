"""
Settings Panel - Cài đặt toàn cục và cho từng cửa sổ giả lập.
"""
import customtkinter as ctk
from tkinter import messagebox, filedialog
from typing import Callable, List

from core.models import BotInstance

MAX_INSTANCES = 4

class SettingsPanel(ctk.CTkScrollableFrame):
    def __init__(self, parent, instances: list, settings: dict, on_save: Callable, on_add: Callable, on_remove: Callable[[int], None], on_test_adb: Callable[[int], str], **kwargs):
        super().__init__(parent, **kwargs)
        self.instances   = instances
        self.settings    = settings
        self.on_save     = on_save
        self.on_add      = on_add
        self.on_remove   = on_remove
        self.on_test_adb = on_test_adb
        self._inst_container: ctk.CTkFrame = None
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)

        glob = ctk.CTkFrame(self, corner_radius=8)
        glob.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        glob.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(glob, text="Cài đặt hệ thống", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4))
        
        # ADB
        ctk.CTkLabel(glob, text="Đường dẫn ADB:").grid(row=1, column=0, padx=12, pady=5, sticky="w")
        self._adb_var = ctk.StringVar(value=self.settings.get("adb_path", "adb"))
        ctk.CTkEntry(glob, textvariable=self._adb_var).grid(row=1, column=1, padx=6, pady=5, sticky="ew")
        ctk.CTkButton(glob, text="Chọn file", width=74, command=self._browse_adb).grid(row=1, column=2, padx=(0, 12), pady=5)

        # Tesseract OCR
        ctk.CTkLabel(glob, text="Đường dẫn OCR (Tesseract):").grid(row=2, column=0, padx=12, pady=5, sticky="w")
        self._tesseract_var = ctk.StringVar(value=self.settings.get("tesseract_path", r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
        ctk.CTkEntry(glob, textvariable=self._tesseract_var).grid(row=2, column=1, padx=6, pady=5, sticky="ew")
        ctk.CTkButton(glob, text="Chọn file", width=74, command=self._browse_tesseract).grid(row=2, column=2, padx=(0, 12), pady=5)

        # Theme
        ctk.CTkLabel(glob, text="Giao diện:").grid(row=3, column=0, padx=12, pady=5, sticky="w")
        self._theme_var = ctk.StringVar(value=self.settings.get("theme", "dark"))
        ctk.CTkComboBox(glob, values=["dark", "light", "system"], variable=self._theme_var, width=120).grid(row=3, column=1, padx=6, pady=5, sticky="w")

        ctk.CTkButton(glob, text="Lưu cài đặt", fg_color="#1e6e3a", hover_color="#155228", command=self._save).grid(row=4, column=0, columnspan=3, padx=12, pady=(4, 12), sticky="e")

        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 0))
        ctk.CTkLabel(hdr, text="Danh sách Giả lập", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        ctk.CTkButton(hdr, text="+ Thêm giả lập", width=130, fg_color="#2b2b3d", hover_color="#3a3a55", command=self._add_instance).pack(side="right")

        self._inst_container = ctk.CTkFrame(self, fg_color="transparent")
        self._inst_container.grid(row=2, column=0, sticky="ew", padx=10, pady=4)
        self._inst_container.grid_columnconfigure(0, weight=1)
        self.refresh_instances(self.instances)

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

        ctk.CTkLabel(f, text=f"💻 Cấu hình cho: {inst.get_display_name()}", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(8, 2))

        ctk.CTkLabel(f, text="Tên hiển thị (Tuỳ chọn):").grid(row=1, column=0, padx=12, pady=4, sticky="w")
        name_var = ctk.StringVar(value=inst.name)
        name_var.trace_add("write", lambda *args, v=name_var, i=inst: setattr(i, "name", v.get().strip()))
        name_e   = ctk.CTkEntry(f, textvariable=name_var, width=180, placeholder_text=f"VD: Nông trại {inst.id}")
        name_e.grid(row=1, column=1, padx=6, pady=4, sticky="w")

        ctk.CTkLabel(f, text="Chỉ số LDPlayer (Index):").grid(row=2, column=0, padx=12, pady=4, sticky="w")
        emu_var = ctk.StringVar(value=str(inst.emu_index))
        emu_e   = ctk.CTkEntry(f, textvariable=emu_var, width=60)
        emu_e.grid(row=2, column=1, padx=6, pady=4, sticky="w")
        emu_e.bind("<FocusOut>", lambda e, v=emu_var, i=inst: self._set_int(v, i, "emu_index"))

        ctk.CTkLabel(f, text="Cổng ADB Serial:").grid(row=3, column=0, padx=12, pady=4, sticky="w")
        ser_var = ctk.StringVar(value=inst.adb_serial)
        ser_var.trace_add("write", lambda *args, v=ser_var, i=inst: setattr(i, "adb_serial", v.get().strip()))
        ser_e   = ctk.CTkEntry(f, textvariable=ser_var, width=220, placeholder_text="VD: 127.0.0.1:5554 (Để trống = Tự tìm)")
        ser_e.grid(row=3, column=1, padx=6, pady=4, sticky="ew")

        ctk.CTkLabel(f, text="Cho phép tự động bán hàng:").grid(row=4, column=0, padx=12, pady=4, sticky="w")
        shop_var = ctk.BooleanVar(value=inst.enable_shop)
        ctk.CTkSwitch(f, variable=shop_var, text="", command=lambda v=shop_var, i=inst: setattr(i, "enable_shop", v.get())).grid(row=4, column=1, padx=6, pady=4, sticky="w")

        btn_row = ctk.CTkFrame(f, fg_color="transparent")
        btn_row.grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=(2, 10))

        ctk.CTkButton(btn_row, text="Kiểm tra kết nối", width=110, fg_color="gray35", hover_color="gray45", command=lambda i=inst: self._test_adb(i)).pack(side="left", padx=(0, 8))

        if len(self.instances) > 1:
            ctk.CTkButton(btn_row, text="Xóa", width=66, fg_color="#7a2c10", hover_color="#5c2008", command=lambda i=inst.id: self.on_remove(i)).pack(side="right")

        return f

    def _browse_adb(self):
        path = filedialog.askopenfilename(title="Chọn file adb.exe", filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path: self._adb_var.set(path)
        
    def _browse_tesseract(self):
        path = filedialog.askopenfilename(title="Chọn file tesseract.exe", filetypes=[("Executable", "*.exe"), ("All files", "*.*")])
        if path: self._tesseract_var.set(path)

    def _test_adb(self, inst: BotInstance):
        result = self.on_test_adb(inst.id)
        messagebox.showinfo("Kết quả Test kết nối ADB", result)

    def _add_instance(self):
        if len(self.instances) >= MAX_INSTANCES:
            messagebox.showwarning("Giới hạn", f"Hỗ trợ tối đa {MAX_INSTANCES} giả lập chạy cùng lúc.")
            return
        self.on_add()

    def _save(self):
        self.focus() 
        self.settings["adb_path"] = self._adb_var.get().strip()
        self.settings["tesseract_path"] = self._tesseract_var.get().strip()
        self.settings["theme"]    = self._theme_var.get()
        for inst in self.instances:
            inst.adb_path = self.settings["adb_path"]
            inst.tesseract_path = self.settings["tesseract_path"]
        ctk.set_appearance_mode(self.settings["theme"])
        self.on_save()
        messagebox.showinfo("Đã lưu", "Cài đặt đã được cập nhật thành công.")

    @staticmethod
    def _set_int(var: ctk.StringVar, inst: BotInstance, attr: str):
        val = var.get()
        if not val: return
        try:
            setattr(inst, attr, int(val))
        except ValueError:
            pass