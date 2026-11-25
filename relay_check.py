"""Windows desktop interface for Codex Relay Check."""

import queue
import threading
import tkinter as tk
from tkinter import ttk

from probe import Report, inspect_log, request_check


BG, INK, MUTED = "#f3f3f9", "#24263c", "#535974"


class RelayCheck(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Codex 中转站诊断器")
        self.geometry("850x735")
        self.minsize(700, 645)
        self.configure(bg=BG)
        self.option_add("*Font", ("Microsoft YaHei UI", 10))
        self.mode = tk.StringVar(value="中转站")
        self.endpoint = tk.StringVar()
        self.model = tk.StringVar()
        self.key = tk.StringVar()
        self.title_text = tk.StringVar(value="等待检查")
        self.body_text = tk.StringVar(value="填写 API 信息，或粘贴报错片段进行本地判断。")
        self.events = queue.Queue()
        self.busy = False
        self.styles()
        self.build()
        self.after(100, self.deliver)

    def styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=INK)
        style.configure("TEntry", fieldbackground="white", padding=7)
        style.configure("TCombobox", fieldbackground="white", padding=7)
        style.configure("TNotebook.Tab", padding=(15, 8))
        style.configure("TButton", padding=(12, 7))
        style.configure("Primary.TButton", background="#4c3db1", foreground="white")
        style.map("Primary.TButton", background=[("active", "#3c2b90"), ("disabled", "#837da0")])

    def build(self):
        banner = tk.Frame(self, bg="#292442")
        banner.pack(fill="x")
        tk.Label(banner, text="Codex 中转站诊断器", bg="#292442", fg="white",
                 font=("Microsoft YaHei UI", 23, "bold")).pack(anchor="w", padx=24, pady=(17, 3))
        tk.Label(banner, text="检查 API 地址、认证与 /responses 接口", bg="#292442", fg="#dfd9f6").pack(
            anchor="w", padx=26, pady=(0, 17))
        panel = ttk.Frame(self, padding=(22, 15))
        panel.pack(fill="both", expand=True)

        provider = ttk.Frame(panel)
        provider.pack(fill="x", pady=(0, 10))
        ttk.Label(provider, text="密钥来源").pack(side="left", padx=(0, 12))
        mode = ttk.Combobox(provider, textvariable=self.mode, values=("中转站", "OpenAI 官方"),
                            state="readonly", width=16)
        mode.pack(side="left")
        mode.bind("<<ComboboxSelected>>", self.change_mode)

        tabs = ttk.Notebook(panel)
        tabs.pack(fill="both", expand=True)
        connection = ttk.Frame(tabs, padding=12)
        log = ttk.Frame(tabs, padding=12)
        tabs.add(connection, text="连接检查")
        tabs.add(log, text="报错分析")

        connection.columnconfigure(1, weight=1)
        for row, (label, value, show) in enumerate((
            ("Base URL", self.endpoint, ""), ("API 密钥", self.key, "●"), ("模型名", self.model, "")
        )):
            ttk.Label(connection, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            ttk.Entry(connection, textvariable=value, show=show).grid(row=row, column=1, sticky="ew", pady=5)
        tk.Label(connection, text="填写服务商提供的 API 根地址。测试 Responses 需要模型名，可能消耗少量额度。",
                 bg=BG, fg=MUTED, anchor="w", wraplength=610, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(9, 6))
        actions = ttk.Frame(connection)
        actions.grid(row=4, column=0, columnspan=2, sticky="w", pady=5)
        self.model_button = ttk.Button(actions, text="检查模型列表", command=lambda: self.run("models"),
                                       style="Primary.TButton")
        self.model_button.pack(side="left", padx=(0, 8))
        self.response_button = ttk.Button(actions, text="发送 Responses 测试", command=lambda: self.run("responses"))
        self.response_button.pack(side="left")

        ttk.Label(log, text="粘贴包含状态码或请求地址的报错片段。请先遮盖密钥。").pack(anchor="w", pady=(0, 8))
        self.log = tk.Text(log, height=7, wrap="word", relief="flat", padx=8, pady=7)
        self.log.pack(fill="both", expand=True)
        ttk.Button(log, text="分析报错", command=self.read_log).pack(anchor="w", pady=(8, 0))

        result = tk.Frame(panel, bg="white", highlightbackground="#dadbeb", highlightthickness=1)
        result.pack(fill="x", pady=(13, 0))
        tk.Label(result, textvariable=self.title_text, bg="white", fg=INK,
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w", padx=13, pady=(11, 3))
        self.result = tk.Label(result, textvariable=self.body_text, bg="white", fg=MUTED, justify="left",
                               anchor="w", wraplength=660)
        self.result.pack(fill="x", padx=13, pady=(0, 11))
        result.bind("<Configure>", lambda event: self.result.configure(wraplength=max(100, event.width - 28)))
        ttk.Button(panel, text="复制诊断结果", command=self.copy).pack(anchor="e", pady=(8, 0))

    def kind(self):
        return "relay" if self.mode.get() == "中转站" else "official"

    def change_mode(self, _event):
        official = "https://api.openai.com/v1"
        if self.kind() == "official":
            self.endpoint.set(official)
        elif self.endpoint.get() == official:
            self.endpoint.set("")
        self.key.set("")

    def run(self, operation):
        if self.busy:
            return
        self.busy = True
        self.model_button.configure(state="disabled")
        self.response_button.configure(state="disabled")
        self.display(Report("正在检查", "正在连接填写的 API 地址…"))
        args = (self.endpoint.get(), self.kind(), self.key.get().strip(), self.model.get().strip(), operation)

        def fetch():
            try:
                self.events.put(request_check(*args))
            except ValueError as error:
                self.events.put(Report("请检查输入", str(error)))

        threading.Thread(target=fetch, daemon=True).start()

    def deliver(self):
        try:
            result = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.model_button.configure(state="normal")
            self.response_button.configure(state="normal")
            self.display(result)
        self.after(100, self.deliver)

    def read_log(self):
        if not self.busy:
            text = self.log.get("1.0", "end-1c")[:100000]
            self.display(inspect_log(text, self.kind()))

    def display(self, report):
        timing = f"  ·  {report.elapsed_ms} ms" if report.elapsed_ms is not None else ""
        self.title_text.set(report.title + timing)
        self.body_text.set(report.details)

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.title_text.get() + "\n" + self.body_text.get())


if __name__ == "__main__":
    RelayCheck().mainloop()
