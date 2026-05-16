"""
Log Panel - hien thi log bot, co the loc theo instance.
"""
import customtkinter as ctk
from tkinter import END
from core.models import BotInstance


class LogPanel(ctk.CTkFrame):
    def __init__(self, parent, instances: list, **kwargs):
        super().__init__(parent, **kwargs)
        self._buf: dict[int, list[str]] = {}
        self._instance_ids: list[int] = []
        self._build()
        self.refresh_instances(instances)

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Thanh cong cu
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))

        ctk.CTkLabel(toolbar, text="Instance:").pack(side="left")
        self._filter_var = ctk.StringVar(value="Tat ca")
        self._filter_cb  = ctk.CTkComboBox(
            toolbar,
            variable=self._filter_var,
            values=["Tat ca"],
            width=110,
            command=self._on_filter,
        )
        self._filter_cb.pack(side="left", padx=6)

        ctk.CTkButton(
            toolbar, text="Xoa log", width=80,
            fg_color="gray30", hover_color="gray40",
            command=self._clear,
        ).pack(side="right", padx=6)

        # Text box
        self._box = ctk.CTkTextbox(
            self, state="disabled",
            font=("Consolas", 11),
            wrap="word",
        )
        self._box.grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self._box.tag_config("err", foreground="#ff7777")
        self._box.tag_config("ok",  foreground="#77ee99")
        self._box.tag_config("dim", foreground="#888888")

    # ── Public ────────────────────────────────────────────────────────────────

    def refresh_instances(self, instances: list):
        self._instance_ids = [i.id for i in instances]
        vals = ["Tat ca"] + [str(i) for i in self._instance_ids]
        self._filter_cb.configure(values=vals)
        for inst in instances:
            if inst.id not in self._buf:
                self._buf[inst.id] = []

    def append(self, inst_id: int, msg: str):
        """Them dong log moi. Goi tu FarmEngine thread."""
        if inst_id not in self._buf:
            self._buf[inst_id] = []
        self._buf[inst_id].append(msg)
        if len(self._buf[inst_id]) > 300:
            self._buf[inst_id] = self._buf[inst_id][-300:]

        fv = self._filter_var.get()
        if fv == "Tat ca" or fv == str(inst_id):
            self._write(inst_id, msg)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _write(self, inst_id: int, text: str):
        line = f"[#{inst_id}] {text}\n"
        tag  = ""
        low  = text.lower()
        if "loi" in low or "error" in low or "that bai" in low:
            tag = "err"
        elif "xong" in low or "hoan thanh" in low or "da ket noi" in low:
            tag = "ok"
        elif "cho" in low or "scanning" in low:
            tag = "dim"

        self._box.configure(state="normal")
        self._box.insert(END, line, tag)
        self._box.see(END)
        self._box.configure(state="disabled")

    def _on_filter(self, val: str):
        self._box.configure(state="normal")
        self._box.delete("1.0", END)
        if val == "Tat ca":
            lines: list[tuple[str, int]] = []
            for iid, msgs in self._buf.items():
                for m in msgs:
                    lines.append((m, iid))
            lines.sort(key=lambda x: x[0])
            for m, iid in lines:
                self._box.insert(END, f"[#{iid}] {m}\n")
        else:
            try:
                iid = int(val)
                for m in self._buf.get(iid, []):
                    self._box.insert(END, f"[#{iid}] {m}\n")
            except ValueError:
                pass
        self._box.see(END)
        self._box.configure(state="disabled")

    def _clear(self):
        fv = self._filter_var.get()
        if fv == "Tat ca":
            self._buf.clear()
        else:
            try:
                self._buf[int(fv)] = []
            except ValueError:
                pass
        self._box.configure(state="normal")
        self._box.delete("1.0", END)
        self._box.configure(state="disabled")
