import functools
import queue
import threading
import time

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
        self.stop_queue = queue.Queue()
        self.frame_queue = queue.Queue()
        self.exit_queue = queue.Queue()
        self.bp_queue = queue.Queue()
        self.last_selected_frame_level = None
        self.view_mode = "source"
        self.current_path = None
        self.current_line_number = None
        self.current_disassembly = None
        self.current_pc = None
        self.current_breakpoints = []
        self.current_frames = []
        gdb.events.stop.connect(self.stop_handler)
        gdb.events.cont.connect(self.continue_handler)
        gdb.events.gdb_exiting.connect(self.cleanup_handler)
        gdb.events.exited.connect(self.exited_handler)
        gdb.events.before_prompt.connect(self.before_prompt_handler)
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
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(int(screen_w * 0.75), int(screen_h * 16/9))
        height = int(screen_h * 0.75)
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(800, 600)
        self.setup_styles()

        self.create_toolbar()
        self.create_togglebar()
        self.paned_window = ttk.PanedWindow(self.root, orient=HORIZONTAL)
        self.paned_window.grid(column=0, row=2, columnspan=1, sticky="nsew")

        self.left_pane = ttk.Frame(self.paned_window)
        self.right_pane = ttk.Frame(self.paned_window)
        self.right_pane.rowconfigure(0, weight=1)
        self.right_pane.columnconfigure(0, weight=1)
        self.paned_window.add(self.left_pane)
        self.paned_window.add(self.right_pane)

        self.create_statusbar()
        self.create_source_view(self.left_pane)

        self.right_vertical_paned = ttk.PanedWindow(self.right_pane, orient=VERTICAL)
        self.right_vertical_paned.grid(column=0, row=0, sticky="nsew")

        self.backtrace_frame = ttk.Frame(self.right_vertical_paned)
        self.breakpoint_frame = ttk.Frame(self.right_vertical_paned)
        self.locals_frame = ttk.Frame(self.right_vertical_paned)
        self.right_vertical_paned.add(self.backtrace_frame, weight=1)
        self.right_vertical_paned.add(self.breakpoint_frame, weight=2)
        self.right_vertical_paned.add(self.locals_frame, weight=1)

        self.create_backtrace_view(self.backtrace_frame)
        self.create_breakpoint_view(self.breakpoint_frame)
        self.create_locals_view(self.locals_frame)

        self.root.rowconfigure(2, weight=1)
        self.root.columnconfigure(0, weight=1)

        self.root.bind('<<StopEvent>>', lambda e: self.stop())
        self.root.bind('<<ContinueEvent>>', lambda e: self.cont())
        self.root.bind('<<ExitedEvent>>', lambda e: self.exited())
        self.root.bind('<<ShowGui>>', lambda e: self.root.deiconify())
        self.root.bind('<<CleanUpEvent>>', lambda e: self.root.quit())
        self.root.bind('<<FrameChangedEvent>>', lambda e: self.before_prompt())
        self.root.bind("<<BreakpointChangedEvent>>", lambda e: self.on_breakpoints_changed())
        self.root.bind('<<DisableGui>>', lambda e: self.on_close())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # set the position of the sash divider
        self.root.update_idletasks()
        total_width = self.paned_window.winfo_width()
        self.paned_window.sashpos(0, int(total_width * 0.65))

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
        self.style.configure("Active.TButton", background="#4a90d9", foreground="white")
        self.style.map("Active.TButton",
            background=[("active", "#4a90d9")],
            foreground=[("active", "white")])
        self.style.configure("Inactive.TButton", background="#3c3c3c", foreground="#ffffff")
        self.style.configure("Status.TLabel", background="#e1e1e1", foreground="#000000", font=("Sans", 9), padding=2)
        self.style.configure("TCheckbutton", background=self.bg_color, foreground=self.fg_color, font=("Monospace", 10))
        self.style.map("TCheckbutton", background=[("active", "#3c3c3c")], foreground=[("active", "#ffffff")])

    @in_gui_thread
    def create_toolbar(self):
        self.frm = ttk.Frame(self.root, padding=5)
        self.frm.grid(column=0, row=0, sticky="ew")

        def gdb_cmd(cmd):
            return lambda: gdb.post_event(lambda: gdb.execute(f"{cmd}&"))

        ttk.Button(self.frm, text="continue", command=gdb_cmd("continue"), width=10).grid(column=0, row=0)
        ttk.Button(self.frm, text="interrupt", command=gdb_cmd("interrupt"), width=10).grid(column=1, row=0)
        self.step_btn = ttk.Button(self.frm, text="step", command=gdb_cmd("step"), width=10)
        self.step_btn.grid(column=2, row=0)
        self.next_btn = ttk.Button(self.frm, text="next", command=gdb_cmd("next"), width=10)
        self.next_btn.grid(column=3, row=0)
        self.stepi_btn = ttk.Button(self.frm, text="stepi", command=gdb_cmd("stepi"), width=10)
        self.stepi_btn.grid(column=2, row=0)
        self.stepi_btn.grid_remove()
        self.nexti_btn = ttk.Button(self.frm, text="nexti", command=gdb_cmd("nexti"), width=10)
        self.nexti_btn.grid(column=3, row=0)
        self.nexti_btn.grid_remove()
        ttk.Button(self.frm, text="finish", command=gdb_cmd("finish"), width=10).grid(column=4, row=0)
        ttk.Button(self.frm, text="run", command=gdb_cmd("run"), width=10).grid(column=5, row=0)

    @in_gui_thread
    def create_togglebar(self):
        self.toggle_frm = ttk.Frame(self.root, padding=10)
        self.toggle_frm.grid(column=0, row=1, sticky="nsew", padx=10, pady=5)

        self.source_btn = ttk.Button(
            self.toggle_frm,
            text="source",
            command=lambda: self.toggle_view("source"),
            style="Active.TButton")
        self.source_btn.grid(column=0, row=0)

        self.asm_btn = ttk.Button(
            self.toggle_frm,
            text="asm",
            command=lambda: self.toggle_view("asm"),
            style="Inactive.TButton")
        self.asm_btn.grid(column=1, row=0)

    @in_gui_thread
    def create_source_view(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        self.line_numbers = Text(parent, bg=self.bg_color, fg="#858585",
                    width=5, font=("Monospace", 11), highlightthickness=0, bd=0,
                    state="disabled")
        self.line_numbers.grid(column=0, row=0, sticky="ns")
        self.line_numbers.tag_configure("breakpoint", background="#8b0000")
        self.line_numbers.tag_configure("breakpoint_disabled", background="#605050")
        self.line_numbers.tag_configure("breakpoint_pending", background="#6b6b00")
        self.source_code = Text(parent, bg=self.bg_color, fg=self.fg_color,
                    insertbackground=self.fg_color,
                    selectbackground=self.highlight_color,
                    highlightthickness=0, bd=0, wrap = "none",
                    font=("Monospace", 11), state="disabled")
        self.source_code.grid(column=1, row=0, sticky="nsew")
        self.source_code.tag_configure("current_line", background=self.highlight_color)
        self.scrollbar = ttk.Scrollbar(parent, command=self.on_scroll)
        self.scrollbar.grid(column=2, row=0, sticky="ns")
        self.h_scrollbar = ttk.Scrollbar(parent, orient=HORIZONTAL, command=self.source_code.xview)
        self.h_scrollbar.grid(column=1, row=1, sticky="ew")
        self.source_code.configure(xscrollcommand=self.h_scrollbar.set)
        self.source_code.configure(yscrollcommand=self.on_text_scroll)
        self.line_numbers.bind("<Button-1>", self.on_line_number_click)

        # prevent line number scrolling independently from the source code
        self.line_numbers.bind("<MouseWheel>", lambda e: "break")
        self.line_numbers.bind("<Button-4>", lambda e: "break")
        self.line_numbers.bind("<Button-5>", lambda e: "break")

    @in_gui_thread
    def create_backtrace_view(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        self.bt_label = ttk.Label(parent, text="Backtrace")
        self.bt_label.grid(row=0)
        self.backtrace = Text(parent, bg=self.bg_color, fg=self.fg_color,
                    insertbackground=self.fg_color,
                    selectbackground=self.highlight_color,
                    highlightthickness=0, bd=0,
                    font=("Monospace", 11),
                    padx=5, pady=5, height=5)

        self.backtrace.grid(column=0, row=1, sticky="nsew")
        self.backtrace.tag_configure("current_line", background=self.highlight_color)
        self.backtrace_scrollbar = ttk.Scrollbar(parent, orient=VERTICAL, command=self.backtrace.yview)
        self.backtrace_scrollbar.grid(column=1, row=1, sticky="ns")
        self.backtrace.configure(yscrollcommand=self.backtrace_scrollbar.set)
        self.backtrace.bind("<Button-1>", self.on_backtrace_click)

    @in_gui_thread
    def create_breakpoint_view(self, parent):
        parent.rowconfigure(3, weight=1)
        parent.columnconfigure(0, weight=1)

        self.bp_label = ttk.Label(parent, text="Breakpoints")
        self.bp_label.grid(row=0)

        bp_btn_frame = ttk.Frame(parent)
        bp_btn_frame.grid(column=0, row=2, sticky="w")
        ttk.Button(bp_btn_frame, text="Disable All", command=lambda: self.set_all_breakpoints(False)).grid(column=0, row=0, padx=(0, 5))
        ttk.Button(bp_btn_frame, text="Enable All", command=lambda: self.set_all_breakpoints(True)).grid(column=1, row=0)

        self.bp_canvas = Canvas(parent, bg=self.bg_color, highlightthickness=0)
        self.bp_canvas.grid(column=0, row=3, sticky="nsew")

        self.bp_scrollbar = ttk.Scrollbar(parent, orient=VERTICAL, command=self.bp_canvas.yview)
        self.bp_scrollbar.grid(column=1, row=3, sticky="ns")
        self.bp_canvas.configure(yscrollcommand=self.bp_scrollbar.set)

        self.bp_inner_frame = Frame(self.bp_canvas, bg=self.bg_color)
        self.bp_canvas_window = self.bp_canvas.create_window((0, 0), window=self.bp_inner_frame, anchor="nw")

        # Update scroll region when the inner frame changes size
        self._bp_frame_configuring = False
        def on_frame_configure(event):
            if self._bp_frame_configuring:
                return
            self._bp_frame_configuring = True
            self.bp_canvas.configure(scrollregion=self.bp_canvas.bbox("all"))
            self._bp_frame_configuring = False
        self.bp_inner_frame.bind("<Configure>", on_frame_configure)

        # Make the inner frame stretch to canvas width
        self._bp_configuring = False
        def on_canvas_configure(event):
            if self._bp_configuring:
                return
            self._bp_configuring = True
            self.bp_canvas.itemconfig(self.bp_canvas_window, width=event.width)
            self._bp_configuring = False
        self.bp_canvas.bind("<Configure>", on_canvas_configure)

        self.bp_canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.bp_inner_frame.bind("<MouseWheel>", self.on_mouse_wheel)

    @in_gui_thread
    def create_locals_view(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        self.locals_label = ttk.Label(parent, text="Locals")
        self.locals_label.grid(row=0)
        self.locals_text = Text(parent, bg=self.bg_color, fg=self.fg_color,
                    insertbackground=self.fg_color,
                    selectbackground=self.highlight_color,
                    highlightthickness=0, bd=0,
                    font=("Monospace", 11),
                    padx=5, pady=5, height=5)
        self.locals_text.grid(column=0, row=1, sticky="nsew")
        self.locals_scrollbar = ttk.Scrollbar(parent, orient=VERTICAL, command=self.locals_text.yview)
        self.locals_scrollbar.grid(column=1, row=1, sticky="ns")
        self.locals_text.configure(yscrollcommand=self.locals_scrollbar.set, state="disabled")

    @in_gui_thread
    def create_statusbar(self):
        self.root.columnconfigure(0, weight=1)
        self.statusbar = ttk.Label(self.root, text="Idle", anchor="w", style="Status.TLabel")
        self.statusbar.grid(column=0, row=3, columnspan=1, sticky="ew")

    @in_gdb_thread
    def stop_handler(self, event):
        if self.gui_alive and self.root is not None:
            if isinstance(event, gdb.BreakpointEvent):
                reason = "breakpoint"
            elif isinstance(event, gdb.SignalEvent):
                reason = event.stop_signal
            else:
                reason = "step"
            frames = self.collect_frame_data(reason)
            breakpoint_data = self.get_breakpoint_data()
            self.stop_queue.put({'frames': frames, 'breakpoints': breakpoint_data})
            try:
                self.root.event_generate("<<StopEvent>>")
            except RuntimeError:
                pass

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
            self.exit_queue.put({'exit_code': event.exit_code if hasattr(event, 'exit_code') else None})
            try:
                self.root.event_generate("<<ExitedEvent>>")
            except RuntimeError:
                pass

    @in_gdb_thread
    def collect_frame_data(self, reason):
        frame = gdb.newest_frame()
        frames = []
        frame_num = 0
        selected = gdb.selected_frame()
        while frame is not None:
            sal = frame.find_sal()
            disassembly_data, pc_value = self.get_disassembly_data(frame)
            locals_data = self.get_locals_data(frame)
            frames.append({
                'frame_num': frame_num,
                'function_name': frame.name(),
                'file_name': sal.symtab.filename if sal.symtab else None,
                'file_path': sal.symtab.fullname() if sal.symtab else None,
                'line_number': sal.line,
                'reason': reason,
                'is_selected': frame == selected,
                'disassembly': disassembly_data,
                'pc': pc_value,
                'locals': locals_data
            })
            frame = frame.older()
            frame_num += 1
        return frames

    # gdb.events.before_prompt fires when gdb is about to prompt the user for input
    # update gui only if the selected frame level has changed
    @in_gdb_thread
    def before_prompt_handler(self):
        if self.gui_alive and self.root is not None:
            try:
                if self.last_selected_frame_level != gdb.selected_frame().level():
                    self.last_selected_frame_level = gdb.selected_frame().level()
                    self.frame_queue.put({'frame_level': self.last_selected_frame_level})
                    try:
                        self.root.event_generate("<<FrameChangedEvent>>")
                    except RuntimeError:
                        pass
            except gdb.error:
                pass
            self.refresh_breakpoints()

    @in_gdb_thread
    def get_disassembly_data(self, frame):
        try:
            block = gdb.block_for_pc(frame.pc())
            while block.function is None:
                block = block.superblock
            disassembly_data = frame.architecture().disassemble(block.start, end_pc=block.end-1)
            return disassembly_data, frame.pc()
        except Exception:
            return [], None

    @in_gdb_thread
    def get_breakpoint_data(self):
        breakpoint_data = []
        try:
            breakpoints = gdb.breakpoints()
            if breakpoints:
                for breakpoint in breakpoints:
                    # breakpoint becomes invalid if user deletes it from GDB
                    if breakpoint.is_valid():
                        source = None
                        if breakpoint.locations:
                            source = breakpoint.locations[0].source
                        breakpoint_data.append({
                            'number': breakpoint.number,
                            'location': breakpoint.location,
                            'enabled': breakpoint.enabled,
                            'hit_count': breakpoint.hit_count,
                            'source_file': source[0] if source else None,
                            'source_line': source[1] if source else None,
                        })
        except Exception:
            pass
        return breakpoint_data

    @in_gdb_thread
    def get_locals_data(self, frame):
        locals_list = []
        try:
            block = frame.block()
            for symbol in block:
                if symbol.is_argument or symbol.is_variable:
                    locals_list.append({
                        'name': symbol.name,
                        'value': str(symbol.value(frame))
                    })
        except Exception:
            pass
        return locals_list

    @in_gdb_thread
    def refresh_breakpoints(self):
        bp_data = self.get_breakpoint_data()
        self.bp_queue.put({'breakpoints': bp_data})
        try:
            self.root.event_generate("<<BreakpointChangedEvent>>")
        except RuntimeError:
            pass

    @in_gdb_thread
    def refresh_current_state(self):
        # Wait for the GUI to be initialized
        while self.root is None:
            time.sleep(0.1)

        # When there is a running frame
        try:
            frames = self.collect_frame_data("step")
            self.stop_queue.put({'frames': frames, 'breakpoints': self.get_breakpoint_data()})
            self.root.event_generate("<<StopEvent>>")
            return
        except gdb.error:
            pass

        # When there is no running frame, get the main source file from the symbol table
        main_symbol = gdb.lookup_global_symbol("main")
        if main_symbol and main_symbol.symtab:
            disassembly_data = []
            pc_value = None
            try:
                block = gdb.block_for_pc(int(main_symbol.value().address))
                while block.function is None:
                    block = block.superblock
                arch = gdb.selected_inferior().architecture()
                disassembly_data = arch.disassemble(block.start, end_pc=block.end - 1)
                pc_value = int(main_symbol.value().address)
            except Exception:
                pass
            path = main_symbol.symtab.fullname()
            line = main_symbol.line
            self.stop_queue.put({'frames': [{
                'frame_num': 0,
                'function_name': 'main',
                'file_name': main_symbol.symtab.filename,
                'file_path': path,
                'line_number': line,
                'reason': 'initialization',
                'is_selected': True,
                'disassembly': disassembly_data,
                'pc': pc_value,
                'locals': [],
            }], 'breakpoints': self.get_breakpoint_data()})
            try:
                self.root.event_generate("<<StopEvent>>")
            except RuntimeError:
                pass

    @in_gui_thread
    def stop(self):
        data = self.stop_queue.get()
        stop_info = data['frames']
        path = stop_info[0]['file_path']
        line_number = stop_info[0]['line_number']
        function_name = stop_info[0]['function_name']
        file_name = stop_info[0]['file_name']
        reason = stop_info[0]['reason']
        self.current_disassembly = stop_info[0]['disassembly']
        self.current_pc = stop_info[0]['pc']
        self.current_path = path
        self.current_line_number = line_number
        self.current_breakpoints = data['breakpoints']
        if self.view_mode == "source":
            self.update_source_code(path, line_number)
        elif self.view_mode == "asm":
            self.update_disassembly_view(self.current_disassembly, self.current_pc)
        self.update_backtrace_view(stop_info)
        if reason == "initialization":
            self.statusbar.config(text="Program not running. Use 'run' to begin.")
        else:
            self.statusbar.config(text=f"Stopped ({reason}) in {function_name}() at {file_name}:{line_number} - {path}")
        self.last_selected_frame_level = 0
        self.update_breakpoint_view()
        self.update_locals_view(stop_info[0]['locals'])

    @in_gui_thread
    def cont(self):
        self.statusbar.config(text=f"Running...")

    @in_gui_thread
    def exited(self):
        exit_code = self.exit_queue.get()['exit_code']
        if exit_code is not None:
            self.statusbar.config(text=f"Exited with exit code {exit_code}")
        else:
            self.statusbar.config(text=f"Program terminated")

    @in_gui_thread
    def before_prompt(self):
        frame_num = self.frame_queue.get()['frame_level']
        self.select_frame(frame_num)

    @in_gui_thread
    def select_frame(self, frame_num):
        if not self.current_frames or frame_num >= len(self.current_frames):
            return
        path = self.current_frames[frame_num]['file_path']
        line_number = self.current_frames[frame_num]['line_number']
        self.current_disassembly = self.current_frames[frame_num]['disassembly']
        self.current_pc = self.current_frames[frame_num]['pc']
        self.current_path = path
        self.current_line_number = line_number
        if self.view_mode == "source":
            self.update_source_code(path, line_number)
        elif self.view_mode == "asm":
            self.update_disassembly_view(self.current_disassembly, self.current_pc)
        self.backtrace.config(state="normal")
        self.backtrace.tag_remove("current_line", "1.0", END)
        self.backtrace.tag_add("current_line", f"{frame_num + 1}.0", f"{frame_num + 1}.end")
        self.backtrace.config(state="disabled")
        self.update_locals_view(self.current_frames[frame_num]['locals'])

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
        except (FileNotFoundError, TypeError):
            self.source_code.delete("1.0", END)
            self.source_code.insert("1.0", f"File not found: {path}")
        self.source_code.tag_remove("current_line", "1.0", END)
        self.source_code.tag_add("current_line", f"{line_number}.0", f"{line_number}.end")
        self.source_code.see(f"{line_number}.0")
        self.source_code.config(state="disabled")
        self.line_numbers.config(state="normal")
        self.line_numbers.grid()
        self.line_numbers.delete("1.0", END)
        for i in range(1, num_lines + 1):
            self.line_numbers.insert(END, f"{i}\n")
        self.line_numbers.tag_remove("breakpoint", "1.0", END)
        self.line_numbers.tag_remove("breakpoint_disabled", "1.0", END)
        self.line_numbers.tag_remove("breakpoint_pending", "1.0", END)
        for bp in self.current_breakpoints:
            try:
                if bp['source_file'] and bp['source_file'] == path:
                    if bp['enabled']:
                        self.line_numbers.tag_add("breakpoint", f"{bp['source_line']}.0", f"{bp['source_line']}.end")
                    else:
                        self.line_numbers.tag_add("breakpoint_disabled", f"{bp['source_line']}.0", f"{bp['source_line']}.end")
                elif bp['location']:
                    file_path, bp_line = bp['location'].rsplit(':', 1)
                    if file_path == path and bp_line.isdigit():
                        self.line_numbers.tag_add("breakpoint_pending", f"{bp_line}.0", f"{bp_line}.end")
            except Exception:
                pass
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
    def update_locals_view(self, locals_data):
        self.locals_text.config(state="normal")
        self.locals_text.delete("1.0", END)
        for local in locals_data:
            self.locals_text.insert(END, f"{local['name']}: {local['value']}\n")
        self.locals_text.config(state="disabled")

    @in_gui_thread
    def update_breakpoint_view(self):
        self.bp_vars = []
        for checkbox in self.bp_inner_frame.winfo_children():
            checkbox.destroy()
        for i, bp in enumerate(self.current_breakpoints):
            bp_enabled = BooleanVar(value=bp['enabled'])
            self.bp_vars.append(bp_enabled)
            if bp['source_file'] and bp['source_line']:
                bp_text=f"#{bp['number']} {bp['source_file']}:{bp['source_line']} (hit:{bp['hit_count']})"
            else:
                bp_text=f"#{bp['number']} {bp['location']} (hit:{bp['hit_count']})"
            cb = ttk.Checkbutton(self.bp_inner_frame,
                text=bp_text,
                command=lambda num=bp['number'], enabled_var=bp_enabled: self.toggle_breakpoint(num, enabled_var),
                variable=bp_enabled)
            cb.grid(column=0, row=i, sticky="w")
            cb.bind("<MouseWheel>", self.on_mouse_wheel)

    @in_gui_thread
    def toggle_breakpoint(self, bp_number, bp_enabled):
        new_state = bp_enabled.get()

        def do_toggle():
            try:
                for bp in gdb.breakpoints():
                    if bp.number == bp_number and bp.is_valid():
                        bp.enabled = new_state
                        self.refresh_breakpoints()
                        break
            except Exception:
                pass

        gdb.post_event(do_toggle)

    @in_gui_thread
    def set_all_breakpoints(self, enabled):
        def do_set():
            try:
                for bp in gdb.breakpoints():
                    if bp.is_valid():
                        bp.enabled = enabled
                self.refresh_breakpoints()
            except Exception:
                pass

        gdb.post_event(do_set)

    @in_gui_thread
    def update_disassembly_view(self, disassembly, pc):
        self.source_code.config(state="normal")
        self.source_code.delete("1.0", END)
        current_line = 0
        for i, instruction in enumerate(disassembly):
            line_text = f"{hex(instruction['addr'])}  {instruction['asm']}\n"
            self.source_code.insert(END, line_text)
            if instruction['addr'] == pc:
                current_line = i + 1
        self.source_code.tag_remove("current_line", "1.0", END)
        if current_line > 0:
            self.source_code.tag_add("current_line", f"{current_line}.0", f"{current_line}.end")
            self.source_code.see(f"{current_line}.0")
        self.source_code.config(state="disabled")
        self.line_numbers.grid_remove()

    @in_gui_thread
    def toggle_view(self, mode):
        self.view_mode = mode
        if mode == "source" and self.current_path:
            self.step_btn.grid()
            self.next_btn.grid()
            self.stepi_btn.grid_remove()
            self.nexti_btn.grid_remove()
            self.update_source_code(self.current_path, self.current_line_number)
            self.source_btn.configure(style="Active.TButton")
            self.asm_btn.configure(style="Inactive.TButton")

        elif mode == "asm" and self.current_disassembly:
            self.step_btn.grid_remove()
            self.next_btn.grid_remove()
            self.stepi_btn.grid()
            self.nexti_btn.grid()
            self.update_disassembly_view(self.current_disassembly, self.current_pc)
            self.asm_btn.configure(style="Active.TButton")
            self.source_btn.configure(style="Inactive.TButton")

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

    @in_gui_thread
    def on_mouse_wheel(self, event):
        self.bp_canvas.yview_scroll(-1 * (event.delta // 120), "units")

    @in_gui_thread
    def on_line_number_click(self, event):
        if self.current_path is not None:
            row = self.line_numbers.index(f"@{event.x},{event.y}").split('.')[0]
            line_num = int(row)
            path = self.current_path

            def do_toggle():
                try:
                    existing = gdb.breakpoints()
                    if existing:
                        for breakpoint in existing:
                            if breakpoint.locations:
                                source = breakpoint.locations[0].source
                                if source and source[0] == path and source[1] == line_num:
                                    breakpoint.delete()
                                    self.refresh_breakpoints()
                                    return
                            if breakpoint.is_valid() and breakpoint.location == f"{path}:{line_num}":
                                breakpoint.delete()
                                self.refresh_breakpoints()
                                return
                    gdb.Breakpoint(f"{path}:{line_num}", allow_pending=False)
                    self.refresh_breakpoints()
                except Exception:
                    pass

            gdb.post_event(do_toggle)
        return "break"

    @in_gui_thread
    def on_breakpoints_changed(self):
        data = self.bp_queue.get()
        self.current_breakpoints = data['breakpoints']
        self.update_breakpoint_view()
        if self.view_mode == "source" and self.current_path:
            self.update_source_code(self.current_path, self.current_line_number)

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

class GuiCommand (gdb.Command):
    """GUI related commands."""
    def __init__(self):
        super().__init__ ("gui", gdb.COMMAND_USER, prefix=True)

    def invoke(self, arg, from_tty):
        gdb.execute("help gui")

class GuiEnableCommand (gdb.Command):
    """Enable the graphical debugger window."""
    def __init__(self):
        super().__init__ ("gui enable", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        global debugger_gui
        if debugger_gui is None:
            debugger_gui = DebuggerGUI()
        else:
            debugger_gui.reopen()
        gdb.post_event(lambda: debugger_gui.refresh_current_state())

class GuiDisableCommand (gdb.Command):
    """Disable the graphical debugger window."""
    def __init__(self):
        super().__init__ ("gui disable", gdb.COMMAND_USER)

    def invoke(self, arg, from_tty):
        global debugger_gui
        if debugger_gui is not None and debugger_gui.root is not None:
            debugger_gui.root.event_generate("<<DisableGui>>")

debugger_gui = None
GuiCommand()
GuiEnableCommand()
GuiDisableCommand()
