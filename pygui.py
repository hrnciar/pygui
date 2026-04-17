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
        self.last_selected_frame_level = None
        gdb.events.stop.connect(self.stop_handler)
        gdb.events.cont.connect(self.continue_handler)
        gdb.events.gdb_exiting.connect(self.cleanup_handler)
        gdb.events.exited.connect(self.exited_handler)
        gdb.events.before_prompt.connect(self.before_prompt_handler)
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
        self.root.geometry("1920x1080")
        self.root.minsize(1200, 800)
        self.setup_styles()

        self.create_toolbar()
        self.paned_window = ttk.PanedWindow(self.root, orient=HORIZONTAL)
        self.paned_window.grid(column=0, row=1, columnspan=1, sticky="nsew")

        self.left_pane = ttk.Frame(self.paned_window)
        self.right_pane = ttk.Frame(self.paned_window)
        self.paned_window.add(self.left_pane)
        self.paned_window.add(self.right_pane)

        self.create_statusbar()
        self.create_source_view(self.left_pane)
        self.create_backtrace_view(self.right_pane)

        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)

        self.root.bind('<<StopEvent>>', lambda e: self.stop())
        self.root.bind('<<ContinueEvent>>', lambda e: self.cont())
        self.root.bind('<<ExitedEvent>>', lambda e: self.exited())
        self.root.bind('<<ShowGui>>', lambda e: self.root.deiconify())
        self.root.bind('<<CleanUpEvent>>', lambda e: self.root.quit())
        self.root.bind('<<FrameChangedEvent>>', lambda e: self.before_prompt())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # set the position of the sash divider
        self.root.update_idletasks()
        self.paned_window.sashpos(0, 1200)

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
        self.style.configure("Status.TLabel", background="#e1e1e1", foreground="#000000", font=("Sans", 9), padding=2)

    @in_gui_thread
    def create_toolbar(self):
        self.frm = ttk.Frame(self.root, padding=5)
        self.frm.grid(column=0, row=0, columnspan=7,sticky="ew")
        commands = {
            "continue": lambda: gdb.post_event(lambda: gdb.execute("continue&")),
            "interrupt": lambda: gdb.post_event(lambda: gdb.execute("interrupt&")),
            "step": lambda: gdb.post_event(lambda: gdb.execute("step&")),
            "next": lambda: gdb.post_event(lambda: gdb.execute("next&")),
            "finish": lambda: gdb.post_event(lambda: gdb.execute("finish&")),
            "run": lambda: gdb.post_event(lambda: gdb.execute("run&")),
        }
        col = 0
        for name, click_function in commands.items():
            ttk.Button(self.frm, text=name, command=click_function).grid(column=col, row=0)
            col += 1

    @in_gui_thread
    def create_source_view(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        self.line_numbers = Text(parent, bg=self.bg_color, fg="#858585",
                    width=5, font=("Monospace", 11), highlightthickness=0, bd=0,
                    state="disabled")
        self.line_numbers.grid(column=0, row=0, sticky="ns")
        self.source_code = Text(parent, bg=self.bg_color, fg=self.fg_color,
                    insertbackground=self.fg_color,
                    selectbackground=self.highlight_color,
                    highlightthickness=0, bd=0,
                    font=("Monospace", 11), state="disabled")
        self.source_code.grid(column=1, row=0, sticky="nsew")
        self.source_code.tag_configure("current_line", background=self.highlight_color)
        self.scrollbar = ttk.Scrollbar(parent, command=self.on_scroll)
        self.scrollbar.grid(column=2, row=0, sticky="ns")
        self.source_code.configure(yscrollcommand=self.on_text_scroll)

    @in_gui_thread
    def create_backtrace_view(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        self.backtrace = Text(parent, bg=self.bg_color, fg=self.fg_color,
                    insertbackground=self.fg_color,
                    selectbackground=self.highlight_color,
                    highlightthickness=0, bd=0,
                    font=("Monospace", 11),
                    padx=5, pady=5)

        self.backtrace.grid(column=0, row=0, sticky="nsew")
        self.backtrace.tag_configure("current_line", background=self.highlight_color)
        self.backtrace_scrollbar = ttk.Scrollbar(parent, orient=VERTICAL, command=self.backtrace.yview)
        self.backtrace_scrollbar.grid(column=1, row=0, sticky="ns")
        self.backtrace.configure(yscrollcommand=self.backtrace_scrollbar.set)
        self.backtrace.bind("<Button-1>", self.on_backtrace_click)

    @in_gui_thread
    def create_statusbar(self):
        self.root.columnconfigure(0, weight=1)
        self.statusbar = ttk.Label(self.root, text="Idle", anchor="w", style="Status.TLabel")
        self.statusbar.grid(column=0, row=2, columnspan=1, sticky="ew")

    @in_gdb_thread
    def stop_handler(self, event):
        if self.gui_alive and self.root is not None:
            if isinstance(event, gdb.BreakpointEvent):
                reason = "breakpoint"
            elif isinstance(event, gdb.SignalEvent):
                reason = event.stop_signal
            else:
                reason = "step"
            frame = gdb.newest_frame()
            frames = []
            frame_num = 0
            selected = gdb.selected_frame()
            while frame is not None:
                sal = frame.find_sal()
                frames.append({
                    'frame_num': frame_num,
                    'function_name': frame.name(),
                    'file_name': sal.symtab.filename if sal.symtab else None,
                    'file_path': sal.symtab.fullname() if sal.symtab else None,
                    'line_number': sal.line,
                    'reason': reason,
                    'is_selected': frame == selected
                })
                frame = frame.older()
                frame_num += 1
            self.event_queue.put(frames)
            self.root.event_generate("<<StopEvent>>")

    @in_gdb_thread
    def continue_handler(self, event):
        if self.gui_alive and self.root is not None:
            self.root.event_generate("<<ContinueEvent>>")

    @in_gdb_thread
    def cleanup_handler(self, event):
        if self.root is not None:
            self.root.event_generate("<<CleanUpEvent>>")

    @in_gdb_thread
    def exited_handler(self, event):
        if self.gui_alive and self.root is not None:
            self.event_queue.put({'exit_code': event.exit_code if hasattr(event, 'exit_code') else None})
            try:
                self.root.event_generate("<<ExitedEvent>>")
            except RuntimeError:
                pass

    # gdb.events.before_prompt fires when gdb is about to prompt the user for input
    # update gui only if the selected frame level has changed
    @in_gdb_thread
    def before_prompt_handler(self):
        if self.gui_alive and self.root is not None:
            try:
                if self.last_selected_frame_level != gdb.selected_frame().level():
                    self.last_selected_frame_level = gdb.selected_frame().level()
                    self.event_queue.put({'frame_level': self.last_selected_frame_level})
                    try:
                        self.root.event_generate("<<FrameChangedEvent>>")
                    except RuntimeError:
                        pass
                else:
                    return
            except gdb.error:
                pass

    @in_gui_thread
    def stop(self):
        stop_info = self.event_queue.get()
        path = stop_info[0]['file_path']
        line_number = stop_info[0]['line_number']
        function_name = stop_info[0]['function_name']
        file_name = stop_info[0]['file_name']
        reason = stop_info[0]['reason']
        self.update_source_code(path, line_number)
        self.update_backtrace_view(stop_info)
        self.statusbar.config(text=f"Stopped ({reason}) in {function_name}() at {file_name}:{line_number} - {path}")
        self.last_selected_frame_level = 0

    @in_gui_thread
    def cont(self):
        self.statusbar.config(text=f"Running...")

    @in_gui_thread
    def exited(self):
        exit_code = self.event_queue.get()['exit_code']
        if exit_code is not None:
            self.statusbar.config(text=f"Exited with exit code {exit_code}")
        else:
            self.statusbar.config(text=f"Program terminated")

    @in_gui_thread
    def before_prompt(self):
        frame_num = self.event_queue.get()['frame_level']
        self.select_frame(frame_num)

    @in_gui_thread
    def select_frame(self, frame_num):
        path = self.current_frames[frame_num]['file_path']
        line_number = self.current_frames[frame_num]['line_number']
        self.update_source_code(path, line_number)
        self.backtrace.config(state="normal")
        self.backtrace.tag_remove("current_line", "1.0", END)
        self.backtrace.tag_add("current_line", f"{frame_num + 1}.0", f"{frame_num + 1}.end")
        self.backtrace.config(state="disabled")

    @in_gui_thread
    def on_backtrace_click(self, event):
        row = self.backtrace.index(f"@{event.x},{event.y}").split('.')[0]
        frame_num = int(row) - 1
        if frame_num < 0 or frame_num >= len(self.current_frames):
            return
        self.select_frame(frame_num)
        gdb.post_event(lambda:gdb.execute(f"frame {frame_num}"))

    @in_gui_thread
    def update_source_code(self, path, line_number):
        self.source_code.config(state="normal")
        self.source_code.delete("1.0", END)
        num_lines = 0
        try:
            with open(path, "r") as file:
                file_content = file.read()
            self.source_code.insert("1.0", file_content)
            num_lines = len(file_content.splitlines())
        except FileNotFoundError:
            self.source_code.delete("1.0", END)
            self.source_code.insert("1.0", f"File not found: {path}")
        self.source_code.tag_remove("current_line", "1.0", END)
        self.source_code.tag_add("current_line", f"{line_number}.0", f"{line_number}.end")
        self.source_code.see(f"{line_number}.0")
        self.source_code.config(state="disabled")
        self.line_numbers.config(state="normal")
        self.line_numbers.delete("1.0", END)
        for i in range(1, num_lines + 1):
            self.line_numbers.insert(END, f"{i}\n")
        self.line_numbers.config(state="disabled")

    @in_gui_thread
    def update_backtrace_view(self, stop_info):
        self.current_frames = stop_info
        self.backtrace.config(state="normal")
        self.backtrace.delete("1.0", END)
        for frame in stop_info:
            self.backtrace.insert(END, f"{frame['frame_num']}. {frame['function_name']}() at {frame['file_name']}:{frame['line_number']}\n")
            if frame['is_selected']:
                line = frame['frame_num'] + 1
                self.backtrace.tag_add("current_line", f"{line}.0", f"{line}.end")
        self.backtrace.config(state="disabled")

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
