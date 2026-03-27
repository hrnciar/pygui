import functools
import queue
import threading

from tkinter import *
from tkinter import ttk

def in_gui_thread(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if threading.current_thread() is not _gui_thread:
            raise RuntimeError("Function must be called from GUI thread")
        return func(*args, **kwargs)
    return wrapper

def in_gdb_thread(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if threading.current_thread() is not _gdb_thread:
            raise RuntimeError("Function must be called from GDB thread")
        return func(*args, **kwargs)
    return wrapper

_gdb_thread = threading.current_thread()
_gui_thread = None

class DebuggerGUI:
    @in_gdb_thread
    def __init__(self):
        self.root = None
        self.gui_alive = True
        self.event_queue = queue.Queue()
        gdb.events.stop.connect(self.stop_handler)
        gdb.events.gdb_exiting.connect(self.exit_handler)
        gdb.execute("set confirm off")
        GuiThread(self).start()

    def build_gui(self):
        global _gui_thread
        _gui_thread = threading.current_thread()
        self.root = Tk()
        Tk.focus_force(self.root)
        self.bg_color = "#2d2d2d"
        self.fg_color = "#d4d4d4"
        self.highlight_color = "#264f78"
        self.root.configure(bg=self.bg_color)
        self.root.geometry("1200x600")
        self.root.minsize(600, 400)

        self.setup_styles()
        self.create_toolbar()
        self.create_source_view()

        self.root.bind('<<StopEvent>>', lambda e: self.action())
        self.root.bind('<<ShowGui>>', lambda e: self.root.deiconify())
        self.root.bind('<<ExitEvent>>', lambda e: self.root.quit())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.root.mainloop()

    @in_gui_thread
    def setup_styles(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.style.configure(".", background="#3c3c3c", foreground="#ffffff")
        self.style.configure("TFrame", background=self.bg_color)
        self.style.configure("TLabel", background=self.bg_color, foreground=self.fg_color)
        self.style.configure("TButton", background="#3c3c3c", foreground="#ffffff", padding=5)
        self.style.map("TButton",
            background=[("active", "#505050")],
            foreground=[("active", "#ffffff")])

    @in_gui_thread
    def create_toolbar(self):
        self.frm = ttk.Frame(self.root, padding=10)
        self.frm.grid(column=0, row=0, columnspan=5)
        self.lbl = ttk.Label(self.frm, text="Hello World!")
        self.lbl.grid(column=0, row=1, columnspan=5)
        commands = {
            "continue": lambda: gdb.post_event(lambda: gdb.execute("continue&")),
            "interrupt": lambda: gdb.post_event(lambda: gdb.execute("interrupt&")),
            "step": lambda: gdb.post_event(lambda: gdb.execute("step&")),
            "next": lambda: gdb.post_event(lambda: gdb.execute("next&")),
            "finish": lambda: gdb.post_event(lambda: gdb.execute("finish&")),
            "run": lambda: gdb.post_event(lambda: gdb.execute("run&")),
            "kill": lambda: gdb.post_event(lambda: gdb.execute("kill")),
        }
        col = 0
        for name, click_function in commands.items():
            ttk.Button(self.frm, text=name, command=click_function).grid(column=col, row=0)
            col += 1

    @in_gui_thread
    def create_source_view(self):
        self.line_numbers = Text(self.root, bg=self.bg_color, fg="#858585",
                    width=5, font=("Monospace", 11),
                    state="disabled")
        self.line_numbers.grid(column=0, row=2, sticky="ns")
        self.source_code = Text(self.root, bg=self.bg_color, fg=self.fg_color,
                    insertbackground=self.fg_color,
                    selectbackground=self.highlight_color,
                    font=("Monospace", 11))
        self.source_code.grid(column=1, row=2, columnspan=4)
        self.source_code.tag_configure("current_line", background=self.highlight_color)
        self.scrollbar = Scrollbar(self.root, command=self.on_scroll)
        self.scrollbar.grid(column=5, row=2, sticky="ns")
        self.source_code.configure(yscrollcommand=self.on_text_scroll)

    @in_gdb_thread
    def stop_handler(self, event):
        if self.gui_alive and self.root is not None:
            frame = gdb.newest_frame().find_sal()
            self.event_queue.put({
                'file_path': frame.symtab.fullname(),
                'line_number': frame.line,
            })
            self.root.event_generate("<<StopEvent>>")

    @in_gdb_thread
    def exit_handler(self, event):
        if self.root is not None:
            self.root.event_generate("<<ExitEvent>>")

    @in_gui_thread
    def action(self):
        file_info = self.event_queue.get()
        path = file_info['file_path']
        line_number = file_info['line_number']
        self.lbl.config(text=path)
        self.update_source_code(path, line_number)

    @in_gui_thread
    def update_source_code(self, path, line_number):
        self.source_code.delete("1.0", END)
        with open(path, "r") as file:
            file_content = file.read()
            self.source_code.insert("1.0", file_content)
        self.source_code.tag_remove("current_line", "1.0", END)
        self.source_code.tag_add("current_line", f"{line_number}.0", f"{line_number}.end")
        self.source_code.see(f"{line_number}.0")
        num_lines = len(file_content.splitlines())
        self.line_numbers.config(state="normal")
        self.line_numbers.delete("1.0", END)
        for i in range(1, num_lines + 1):
            self.line_numbers.insert(END, f"{i}\n")
        self.line_numbers.config(state="disabled")

    @in_gui_thread
    def on_close(self):
        self.gui_alive = False
        self.root.withdraw()

    @in_gui_thread
    def on_scroll(self, *args):
        self.source_code.yview(*args)
        self.line_numbers.yview(*args)

    @in_gui_thread
    def on_text_scroll(self, *args):
        self.scrollbar.set(*args)
        self.line_numbers.yview_moveto(args[0])

    @in_gdb_thread
    def reopen(self):
        self.root.event_generate("<<ShowGui>>")
        self.gui_alive = True


class GuiThread(gdb.Thread):
    def __init__(self, gui):
        super().__init__()
        self.gui = gui

    def run(self):
        self.gui.build_gui()


try:
    debugger_gui
except NameError:
    debugger_gui = None

if debugger_gui is None:
    debugger_gui = DebuggerGUI()
else:
    debugger_gui.reopen()
