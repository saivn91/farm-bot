"""
Log Panel - Hiển thị nhật ký hoạt động, có thể lọc theo từng giả lập.
"""
import customtkinter as ctk
from tkinter import END
from core.models import BotInstance

class LogPanel(ctk.CTkFrame):
    def __init__(self, parent, instances: list, **kwargs):
        super().__init__(parent, **kwargs)
        self._buf: dict[int, list[str]] = {}
        self._instances = instances
        self._build()
        self.refresh_instances(instances)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))

        ctk.CTkLabel(toolbar, text="Xem Log:").pack(side="left")
        self._filter_var = ctk.StringVar(value="Tất cả")
        self._filter_cb  = ctk.CTkComboBox(toolbar, variable=self._filter_var, values=["Tất cả"], width=130, command=self._on_filter)
        self._filter_cb.pack(side="left", padx=6)

        ctk.CTkButton(toolbar, text="Xóa màn hình", width=100, fg_color="gray30", hover_color="gray40", command=self._clear).pack(side="right", padx=6)

        self._box = ctk.CTkTextbox(self, state="disabled", font=("Consolas", 11), wrap="word")
        self._box.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self._box.tag_config("err", foreground="#ff7777")
        self._box.tag_config("ok",  foreground="#77ee99")
        self._box.tag_config("dim", foreground="#888888")

    def refresh_instances(self, instances: list):
        self._instances = instances
        vals = ["Tất cả"] + [inst.get_display_name() for inst in instances]
        self._filter_cb.configure(values=vals)
        for inst in instances:
            if inst.id not in self._buf:
                self._buf[inst.id] = []

    def append(self, inst_id: int, msg: str):
        if inst_id not in self._buf:
            self._buf[inst_id] = []
        self._buf[inst_id].append(msg)
        if len(self._buf[inst_id]) > 300:
            self._buf[inst_id] = self._buf[inst_id][-300:]

        fv = self._filter_var.get()
        # Tìm tên của giả lập tương ứng với id này
        inst_name = next((i.get_display_name() for i in self._instances if i.id == inst_id), f"#{inst_id}")
        
        if fv == "Tất cả" or fv == inst_name:
            self._write(inst_name, msg)

    def _write(self, inst_name: str, text: str):
        line = f"[{inst_name}] {text}\n"
        tag  = ""
        low  = text.lower()
        if "lỗi" in low or "error" in low or "thất bại" in low or "cảnh báo" in low or "không" in low:
            tag = "err"
        elif "xong" in low or "hoàn tất" in low or "thành công" in low or "đã kết nối" in low:
            tag = "ok"
        elif "chờ" in low or "quét" in low or "đang" in low:
            tag = "dim"

        self._box.configure(state="normal")
        self._box.insert(END, line, tag)
        self._box.see(END)
        self._box.configure(state="disabled")

    def _on_filter(self, val: str):
        self._box.configure(state="normal")
        self._box.delete("1.0", END)
        if val == "Tất cả":
            lines: list[tuple[str, int]] = []
            for iid, msgs in self._buf.items():
                for m in msgs:
                    lines.append((m, iid))
            lines.sort(key=lambda x: x[0])
            for m, iid in lines:
                iname = next((i.get_display_name() for i in self._instances if i.id == iid), f"#{iid}")
                self._box.insert(END, f"[{iname}] {m}\n")
        else:
            # Lọc theo tên giả lập
            target_id = next((i.id for i in self._instances if i.get_display_name() == val), None)
            if target_id is not None:
                for m in self._buf.get(target_id, []):
                    self._box.insert(END, f"[{val}] {m}\n")
                    
        self._box.see(END)
        self._box.configure(state="disabled")

    def _clear(self):
        fv = self._filter_var.get()
        if fv == "Tất cả":
            self._buf.clear()
        else:
            target_id = next((i.id for i in self._instances if i.get_display_name() == fv), None)
            if target_id is not None:
                self._buf[target_id] = []
                
        self._box.configure(state="normal")
        self._box.delete("1.0", END)
        self._box.configure(state="disabled")