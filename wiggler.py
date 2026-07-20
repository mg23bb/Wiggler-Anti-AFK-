"""
Wiggler — Anti-AFK Mouse Mover
Uses SendInput (Windows input pipeline) — updates GetLastInputInfo & OS idle timers.
No external dependencies — only built-in Python libraries.
"""

import tkinter as tk
import tkinter.ttk as ttk
import ctypes
import threading
import time
import math
import random
import subprocess
import sys

# ─── Windows SendInput ────────────────────────────────────────────────────────

INPUT_MOUSE      = 0
MOUSEEVENTF_MOVE = 0x0001

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx",          ctypes.c_long),
        ("dy",          ctypes.c_long),
        ("mouseData",   ctypes.c_ulong),
        ("dwFlags",     ctypes.c_ulong),
        ("time",        ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("_input", _INPUT_UNION)]
    _anonymous_ = ("_input",)

_SendInput = ctypes.windll.user32.SendInput
_SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
_SendInput.restype  = ctypes.c_uint

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def _send_relative_move(dx: int, dy: int):
    inp = INPUT(
        type=INPUT_MOUSE,
        mi=MOUSEINPUT(dx=dx, dy=dy, mouseData=0,
                      dwFlags=MOUSEEVENTF_MOVE, time=0, dwExtraInfo=None),
    )
    _SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def wiggle_mouse(distance: int, duration_ms: int):
    """Smoothly wiggle cursor by `distance` px and return, over `duration_ms` ms."""
    angle    = random.uniform(0, 2 * math.pi)
    total_dx = int(math.cos(angle) * distance)
    total_dy = int(math.sin(angle) * distance)
    steps    = max(4, duration_ms // 10)
    delay    = (duration_ms / 1000.0) / (2 * steps)

    sx, sy = 0, 0
    for i in range(1, steps + 1):
        tx = int(total_dx * i / steps); ty = int(total_dy * i / steps)
        _send_relative_move(tx - sx, ty - sy)
        sx, sy = tx, ty
        time.sleep(delay)

    rx, ry = sx, sy
    for i in range(1, steps + 1):
        tx = int(total_dx * (steps - i) / steps); ty = int(total_dy * (steps - i) / steps)
        _send_relative_move(tx - rx, ty - ry)
        rx, ry = tx, ty
        time.sleep(delay)


# ─── System Tray (pure ctypes, no dependencies) ──────────────────────────────

class _SysTray(threading.Thread):
    """Minimal Windows system-tray icon using pure ctypes."""

    _WM_TRAYICON      = 0x8000   # WM_APP — our custom tray callback message
    _WM_TRAY_QUIT     = 0x8001   # WM_APP+1 — posted by stop() to exit message loop
    _WM_LBUTTONDBLCLK = 0x0203
    _WM_RBUTTONUP     = 0x0205
    _NIM_ADD          = 0
    _NIM_DELETE       = 2
    _NIF_MESSAGE      = 0x01
    _NIF_ICON         = 0x02
    _NIF_TIP          = 0x04
    _IDI_APPLICATION  = 32512
    _ID_RESTORE       = 3001
    _ID_QUIT          = 3002
    _MF_STRING        = 0x00000000
    _MF_SEPARATOR     = 0x00000800
    _TPM_LEFTALIGN    = 0x0000
    _TPM_RETURNCMD    = 0x0100
    _CS_VREDRAW       = 0x0001
    _CS_HREDRAW       = 0x0002
    _HWND_MESSAGE     = -3

    class _NOTICONDATA(ctypes.Structure):
        _fields_ = [
            ('cbSize',           ctypes.c_uint),
            ('hWnd',             ctypes.c_void_p),
            ('uID',              ctypes.c_uint),
            ('uFlags',           ctypes.c_uint),
            ('uCallbackMessage', ctypes.c_uint),
            ('hIcon',            ctypes.c_void_p),
            ('szTip',            ctypes.c_wchar * 128),
        ]

    def __init__(self, tooltip: str, on_restore, on_quit):
        super().__init__(daemon=True)
        self.tooltip    = tooltip[:127]
        self.on_restore = on_restore
        self.on_quit    = on_quit
        self._hwnd      = None

    def run(self):
        user32   = ctypes.windll.user32
        shell32  = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        # Explicit return types for correct 64-bit pointer handling
        kernel32.GetModuleHandleW.restype     = ctypes.c_void_p
        user32.LoadIconW.restype              = ctypes.c_void_p
        user32.LoadIconW.argtypes             = [ctypes.c_void_p, ctypes.c_void_p]
        user32.RegisterClassExW.restype       = ctypes.c_ushort
        user32.CreateWindowExW.restype        = ctypes.c_void_p
        user32.CreateWindowExW.argtypes       = [
            ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        user32.DefWindowProcW.restype         = ctypes.c_long
        user32.CreatePopupMenu.restype        = ctypes.c_void_p
        user32.TrackPopupMenu.restype         = ctypes.c_int
        shell32.Shell_NotifyIconW.restype     = ctypes.c_bool

        hinstance  = kernel32.GetModuleHandleW(None)
        class_name = f"WigglerTray_{id(self)}"

        WNDPROC_T = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
        )

        nid = self._NOTICONDATA()   # pre-declare so wnd_proc closure can access it

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == self._WM_TRAYICON:
                evt = lparam & 0xFFFF
                if evt == self._WM_LBUTTONDBLCLK:
                    self.on_restore()
                elif evt == self._WM_RBUTTONUP:
                    pt = POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    user32.SetForegroundWindow(hwnd)
                    hmenu = user32.CreatePopupMenu()
                    user32.AppendMenuW(hmenu, self._MF_STRING,    self._ID_RESTORE, "Restore Wiggler")
                    user32.AppendMenuW(hmenu, self._MF_SEPARATOR, 0, None)
                    user32.AppendMenuW(hmenu, self._MF_STRING,    self._ID_QUIT,    "Quit")
                    cmd = user32.TrackPopupMenu(
                        hmenu, self._TPM_LEFTALIGN | self._TPM_RETURNCMD,
                        pt.x, pt.y, 0, hwnd, None,
                    )
                    user32.DestroyMenu(hmenu)
                    if cmd == self._ID_RESTORE: self.on_restore()
                    elif cmd == self._ID_QUIT:  self.on_quit()
            elif msg == self._WM_TRAY_QUIT:
                shell32.Shell_NotifyIconW(self._NIM_DELETE, ctypes.byref(nid))
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = WNDPROC_T(wnd_proc)   # keep alive — prevents GC

        class _WC(ctypes.Structure):
            _fields_ = [
                ('cbSize',        ctypes.c_uint),   ('style',         ctypes.c_uint),
                ('lpfnWndProc',   ctypes.c_void_p), ('cbClsExtra',    ctypes.c_int),
                ('cbWndExtra',    ctypes.c_int),     ('hInstance',     ctypes.c_void_p),
                ('hIcon',         ctypes.c_void_p), ('hCursor',       ctypes.c_void_p),
                ('hbrBackground', ctypes.c_void_p), ('lpszMenuName',  ctypes.c_wchar_p),
                ('lpszClassName', ctypes.c_wchar_p),('hIconSm',       ctypes.c_void_p),
            ]

        icon = user32.LoadIconW(None, ctypes.c_void_p(self._IDI_APPLICATION))

        wc = _WC()
        wc.cbSize        = ctypes.sizeof(_WC)
        wc.style         = self._CS_VREDRAW | self._CS_HREDRAW
        wc.lpfnWndProc   = ctypes.cast(self._wndproc, ctypes.c_void_p).value
        wc.hInstance     = hinstance
        wc.lpszClassName = class_name
        wc.hIcon         = icon
        wc.hIconSm       = icon
        user32.RegisterClassExW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(
            0, class_name, "Wiggler", 0,
            0, 0, 0, 0, self._HWND_MESSAGE, None, hinstance, None,
        )
        self._hwnd = hwnd

        nid.cbSize           = ctypes.sizeof(self._NOTICONDATA)
        nid.hWnd             = hwnd
        nid.uID              = 1
        nid.uFlags           = self._NIF_MESSAGE | self._NIF_ICON | self._NIF_TIP
        nid.uCallbackMessage = self._WM_TRAYICON
        nid.hIcon            = icon
        nid.szTip            = self.tooltip
        shell32.Shell_NotifyIconW(self._NIM_ADD, ctypes.byref(nid))

        class _MSG(ctypes.Structure):
            _fields_ = [
                ('hWnd', ctypes.c_void_p), ('message', ctypes.c_uint),
                ('wParam', ctypes.c_size_t), ('lParam', ctypes.c_ssize_t),
                ('time', ctypes.c_uint), ('ptX', ctypes.c_int), ('ptY', ctypes.c_int),
            ]
        msg = _MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        if self._hwnd:
            ctypes.windll.user32.PostMessageW(self._hwnd, self._WM_TRAY_QUIT, 0, 0)
            self._hwnd = None


# ─── Actions ─────────────────────────────────────────────────────────────────

ACTION_NOTHING = "Nothing"
ACTION_SLEEP   = "Sleep PC"
ACTION_CLOSE   = "Close Wiggler"
ACTION_KILL    = "Kill Process…"
ACTION_CMD     = "Custom Command"

ACTIONS = [ACTION_NOTHING, ACTION_SLEEP, ACTION_CLOSE, ACTION_KILL, ACTION_CMD]
# Actions that require a parameter text field
PARAM_ACTIONS = {
    ACTION_KILL: "Process name to terminate (e.g. game.exe):",
    ACTION_CMD:  "Command to run (supports arguments):",
}

def do_action(action: str, param: str):
    p = param.strip()
    if action == ACTION_SLEEP:
        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
    elif action == ACTION_CLOSE:
        sys.exit(0)
    elif action == ACTION_KILL and p:
        subprocess.Popen(["taskkill", "/F", "/IM", p],
                         creationflags=subprocess.CREATE_NO_WINDOW)
    elif action == ACTION_CMD and p:
        subprocess.Popen(p, shell=True)


# ─── Colours ─────────────────────────────────────────────────────────────────

BG      = "#0d1117"
SURFACE = "#161b22"
CARD    = "#1c2333"
CARD2   = "#21262d"
BORDER  = "#30363d"
ACCENT  = "#58a6ff"
GREEN   = "#3fb950"
AMBER   = "#d29922"
DANGER  = "#f85149"
TEXT    = "#e6edf3"
MUTED   = "#8b949e"
WHITE   = "#ffffff"


# ─── Worker thread ────────────────────────────────────────────────────────────

class WigglerThread(threading.Thread):
    def __init__(self, get_distance, get_interval, get_duration, on_wiggle):
        super().__init__(daemon=True)
        self._stop = threading.Event()
        self.get_distance = get_distance
        self.get_interval = get_interval
        self.get_duration = get_duration
        self.on_wiggle    = on_wiggle

    def run(self):
        while not self._stop.is_set():
            elapsed = 0.0; interval = self.get_interval()
            while elapsed < interval and not self._stop.is_set():
                time.sleep(0.1); elapsed += 0.1
            if not self._stop.is_set():
                wiggle_mouse(self.get_distance(), self.get_duration())
                self.on_wiggle()

    def stop(self): self._stop.set()


# ─── App ─────────────────────────────────────────────────────────────────────

class WigglerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Wiggler — Anti-AFK")
        self.resizable(False, False)
        self.configure(bg=BG)

        self._thread:  WigglerThread | None = None
        self._tray:    _SysTray | None      = None
        self._running  = False
        self._count    = 0
        self._tick_id  = None
        self._countdown = 0
        self._sa_id    = None
        self._sa_remain = 0

        w, h = 440, 720
        self.update_idletasks()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Apply dark title bar after the window is fully realised
        self.after(50, self._apply_dark_titlebar)

    # ── UI shell (fixed header + scrollable body) ─────────────────────────────

    def _build_ui(self):
        # ── Fixed header ──
        hdr = tk.Frame(self, bg=SURFACE, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🐭  Wiggler", font=("Segoe UI", 18, "bold"),
                 bg=SURFACE, fg=TEXT).pack()
        tk.Label(hdr, text="Anti-AFK Mouse Mover  ·  Hardware-pipeline input",
                 font=("Segoe UI", 8), bg=SURFACE, fg=MUTED).pack()

        # Tray button — top-right corner of header
        tk.Button(hdr, text="▼ Tray",
                  font=("Segoe UI", 8), bg=BORDER, fg=MUTED,
                  activebackground=CARD, activeforeground=TEXT,
                  relief="flat", bd=0, padx=8, pady=3, cursor="hand2",
                  command=self._minimize_to_tray
                  ).place(relx=1.0, rely=0.0, x=-10, y=10, anchor="ne")

        # ── Scrollable body ──
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        # Dark scrollbar via ttk clam theme
        _style = ttk.Style(self)
        _style.theme_use("clam")
        _style.configure("Dark.Vertical.TScrollbar",
                         gripcount=0, relief="flat",
                         background=BORDER, darkcolor=BG, lightcolor=CARD,
                         troughcolor=BG, bordercolor=BG, arrowcolor=MUTED,
                         arrowsize=12)
        _style.map("Dark.Vertical.TScrollbar",
                   background=[("active", ACCENT), ("!active", BORDER)])

        self._cv = tk.Canvas(body, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(body, orient="vertical",
                           style="Dark.Vertical.TScrollbar",
                           command=self._cv.yview)
        self._cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._cv.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(self._cv, bg=BG)
        _cid  = self._cv.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>",
                   lambda _: self._cv.configure(scrollregion=self._cv.bbox("all")))
        self._cv.bind("<Configure>",
                      lambda e: self._cv.itemconfig(_cid, width=e.width))
        self._cv.bind_all("<MouseWheel>",
                          lambda e: self._cv.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_content(inner)

    # ── Scrollable content ────────────────────────────────────────────────────

    def _build_content(self, p):
        # ── Status + toggle button (side-by-side) ──
        top = tk.Frame(p, bg=BG, pady=8)
        top.pack(fill="x", padx=20)

        # Left: status info stack
        left = tk.Frame(top, bg=BG)
        left.pack(side="left", fill="both", expand=True, anchor="n")

        sf = tk.Frame(left, bg=BG)
        sf.pack(fill="x", pady=(6, 0))
        self._dot = tk.Canvas(sf, width=12, height=12, bg=BG, highlightthickness=0)
        self._dot.pack(side="left", padx=(0, 8))
        self._draw_dot(MUTED)
        self._status_lbl = tk.Label(sf, text="Idle",
                                    font=("Segoe UI", 11, "bold"), bg=BG, fg=MUTED)
        self._status_lbl.pack(side="left")

        self._count_lbl = tk.Label(left, text="Total wiggles: 0",
                                   font=("Segoe UI", 8), bg=BG, fg=MUTED)
        self._count_lbl.pack(anchor="w")
        self._cd_lbl = tk.Label(left, text="", font=("Segoe UI", 8), bg=BG, fg=MUTED)
        self._cd_lbl.pack(anchor="w")
        self._sa_cd_lbl = tk.Label(left, text="", font=("Segoe UI", 9, "bold"),
                                   bg=BG, fg=AMBER)
        self._sa_cd_lbl.pack(anchor="w", pady=(2, 0))

        # Right: toggle button — top-aligned with the status row
        right = tk.Frame(top, bg=BG)
        right.pack(side="right", anchor="n", pady=(4, 0))
        self._btn = tk.Button(right, text="▶  Start",
                              font=("Segoe UI", 10, "bold"),
                              bg=GREEN, fg=WHITE, activebackground="#2ea043",
                              activeforeground=WHITE, relief="flat", bd=0,
                              padx=18, pady=9, cursor="hand2",
                              command=self._toggle)
        self._btn.pack()

        tk.Frame(p, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(6, 0))

        # ── Wiggle settings card ──
        c1 = tk.Frame(p, bg=CARD, pady=16, padx=18)
        c1.pack(fill="x", padx=20, pady=(12, 0))
        tk.Frame(c1, bg=BORDER, height=1).pack(fill="x", pady=(0, 14))

        self._dist_var = tk.IntVar(value=5)
        self._make_slider(c1, CARD, "Wiggle Distance", "px",
                          "How far the cursor moves before returning.",
                          self._dist_var, 1, 100, "_dist_lbl")
        _spacer(c1, 10)

        self._interval_var = tk.IntVar(value=30)
        self._make_slider(c1, CARD, "Wiggle Interval", "s",
                          "Seconds between each wiggle event.",
                          self._interval_var, 1, 600, "_int_lbl",
                          on_change=self._on_interval_change)
        _spacer(c1, 10)

        self._duration_var = tk.IntVar(value=400)
        self._make_slider(c1, CARD, "Wiggle Duration", "ms",
                          "How long each wiggle animation takes.",
                          self._duration_var, 50, 2000, "_dur_lbl")
        tk.Frame(c1, bg=BORDER, height=1).pack(fill="x", pady=(14, 0))
        _div(p)

        # ── Stop-after group (stop-after card + action card, always in order) ──
        # Using a sub-container means pack_forget/pack on the action card
        # always keeps it immediately below the stop-after card.
        sa_group = tk.Frame(p, bg=BG)
        sa_group.pack(fill="x")

        c2 = tk.Frame(sa_group, bg=CARD2, pady=16, padx=18)
        c2.pack(fill="x", padx=20, pady=(12, 0))
        tk.Frame(c2, bg=BORDER, height=1).pack(fill="x", pady=(0, 14))

        chk_row = tk.Frame(c2, bg=CARD2)
        chk_row.pack(fill="x")
        self._sa_enabled = tk.BooleanVar(value=False)
        tk.Checkbutton(chk_row, variable=self._sa_enabled,
                       text="  Stop After Duration",
                       font=("Segoe UI", 9, "bold"),
                       bg=CARD2, fg=TEXT, activebackground=CARD2, activeforeground=TEXT,
                       selectcolor=BORDER, cursor="hand2",
                       command=self._on_sa_toggle).pack(side="left")
        tk.Label(c2, text="Automatically stop wiggling after a set duration.",
                 font=("Segoe UI", 8), bg=CARD2, fg=MUTED).pack(anchor="w", pady=(4, 10))

        self._sa_hrs_var = tk.IntVar(value=0)
        self._sa_min_var = tk.IntVar(value=30)
        self._sa_time_frame = tk.Frame(c2, bg=CARD2)
        self._sa_time_frame.pack(fill="x")

        for text, var, maxv, suf in [
            ("Hours",   self._sa_hrs_var, 23, "h"),
            ("Minutes", self._sa_min_var, 59, "m"),
        ]:
            col = tk.Frame(self._sa_time_frame, bg=CARD2)
            col.pack(side="left", fill="x", expand=True, padx=(0, 6))
            tk.Label(col, text=text, font=("Segoe UI", 8, "bold"),
                     bg=CARD2, fg=TEXT).pack(anchor="w")
            row = tk.Frame(col, bg=CARD2); row.pack(fill="x")
            lbl = tk.Label(row, text=f"{var.get()} {suf}", width=5,
                           font=("Segoe UI", 9, "bold"), bg=CARD2, fg=ACCENT, anchor="e")
            tk.Scale(row, from_=0, to=maxv, orient="horizontal", variable=var,
                     bg=CARD2, fg=TEXT, troughcolor=BORDER, activebackground=ACCENT,
                     highlightthickness=0, bd=0, sliderlength=16, showvalue=False,
                     command=lambda _, lv=lbl, v=var, s=suf: lv.config(
                         text=f"{v.get()} {s}")
                     ).pack(side="left", fill="x", expand=True)
            lbl.pack(side="left")

        tk.Frame(c2, bg=BORDER, height=1).pack(fill="x", pady=(14, 0))
        self._sa_widgets_enabled(False)

        # Action card — child of sa_group so it always stays just below c2
        self._action_div  = tk.Frame(sa_group, bg=BORDER, height=1)   # divider between cards
        self._action_card = tk.Frame(sa_group, bg=CARD, pady=16, padx=18)
        # Both are hidden initially; _on_sa_toggle will pack them when needed

        c3 = self._action_card
        tk.Frame(c3, bg=BORDER, height=1).pack(fill="x", pady=(0, 14))
        tk.Label(c3, text="Action After Stop",
                 font=("Segoe UI", 9, "bold"), bg=CARD, fg=TEXT).pack(anchor="w")
        tk.Label(c3, text="What happens when the stop-after timer expires.",
                 font=("Segoe UI", 8), bg=CARD, fg=MUTED).pack(anchor="w", pady=(2, 10))

        self._action_var = tk.StringVar(value=ACTION_NOTHING)
        rf = tk.Frame(c3, bg=CARD); rf.pack(fill="x")
        for i, action in enumerate(ACTIONS):
            tk.Radiobutton(rf, text=action, variable=self._action_var, value=action,
                           font=("Segoe UI", 9), bg=CARD, fg=TEXT,
                           activebackground=CARD, activeforeground=TEXT,
                           selectcolor=BORDER, cursor="hand2",
                           command=self._on_action_change
                           ).grid(row=i//2, column=i%2, sticky="w", padx=(0, 16), pady=2)

        self._param_frame = tk.Frame(c3, bg=CARD)
        self._param_lbl   = tk.Label(self._param_frame, text="",
                                     font=("Segoe UI", 8), bg=CARD, fg=MUTED)
        self._param_lbl.pack(anchor="w")
        self._param_entry = tk.Entry(self._param_frame,
                                     font=("Segoe UI", 9),
                                     bg=BORDER, fg=TEXT, insertbackground=TEXT,
                                     relief="flat", bd=4)
        self._param_entry.pack(fill="x", pady=(4, 0))

        self._c3_border = tk.Frame(c3, bg=BORDER, height=1)
        self._c3_border.pack(fill="x", pady=(14, 0))

        # ── Footer ──
        note = tk.Frame(p, bg=BG, pady=8)
        note.pack(fill="x", padx=20)
        tk.Label(note,
                 text="✓  SendInput (hardware pipeline) — resets GetLastInputInfo & OS idle timers.",
                 font=("Segoe UI", 8), bg=BG, fg=GREEN,
                 wraplength=400, justify="left").pack(anchor="w")
        tk.Label(note, text="Cursor returns to its exact origin after each wiggle.",
                 font=("Segoe UI", 8), bg=BG, fg=MUTED,
                 wraplength=400, justify="left").pack(anchor="w", pady=(3, 0))
        _spacer(note, 10)

    # ── Slider factory ────────────────────────────────────────────────────────

    def _make_slider(self, parent, bg, label, unit, desc, var, from_, to,
                     val_lbl_attr, on_change=None):
        tk.Label(parent, text=label, font=("Segoe UI", 9, "bold"),
                 bg=bg, fg=TEXT).pack(anchor="w")
        tk.Label(parent, text=desc, font=("Segoe UI", 8),
                 bg=bg, fg=MUTED).pack(anchor="w", pady=(0, 6))
        row = tk.Frame(parent, bg=bg); row.pack(fill="x")
        lbl = tk.Label(row, text=f"{var.get()} {unit}", width=8,
                       font=("Segoe UI", 9, "bold"), bg=bg, fg=ACCENT, anchor="e")
        def _upd(_=None):
            lbl.config(text=f"{var.get()} {unit}")
            if on_change: on_change()
        tk.Scale(row, from_=from_, to=to, orient="horizontal", variable=var,
                 bg=bg, fg=TEXT, troughcolor=BORDER, activebackground=ACCENT,
                 highlightthickness=0, bd=0, sliderlength=16, showvalue=False,
                 command=_upd).pack(side="left", fill="x", expand=True)
        lbl.pack(side="left")
        setattr(self, val_lbl_attr, lbl)

    # ── Stop-after helpers ────────────────────────────────────────────────────

    def _sa_widgets_enabled(self, on: bool):
        state = "normal" if on else "disabled"
        def _set(w):
            try: w.config(state=state)
            except Exception: pass
            for child in w.winfo_children(): _set(child)
        for child in self._sa_time_frame.winfo_children(): _set(child)

    def _on_sa_toggle(self):
        enabled = self._sa_enabled.get()
        self._sa_widgets_enabled(enabled)
        # Action card lives inside sa_group so order is always preserved
        if enabled:
            self._action_div.pack(fill="x", padx=20, pady=(8, 0))
            self._action_card.pack(fill="x", padx=20, pady=(8, 0))
        else:
            self._action_div.pack_forget()
            self._action_card.pack_forget()

    def _on_action_change(self):
        action = self._action_var.get()
        # Re-order: param_frame must come before the bottom border
        self._c3_border.pack_forget()
        self._param_frame.pack_forget()
        if action in PARAM_ACTIONS:
            self._param_lbl.config(text=PARAM_ACTIONS[action])
            self._param_frame.pack(fill="x", pady=(10, 0))
        self._c3_border.pack(fill="x", pady=(14, 0))

    def _sa_total_secs(self) -> int:
        return self._sa_hrs_var.get() * 3600 + self._sa_min_var.get() * 60

    def _fmt_dur(self, s: int) -> str:
        h = s // 3600; m = (s % 3600) // 60; ss = s % 60
        return f"{h}h {m:02d}m {ss:02d}s" if h else f"{m}m {ss:02d}s"

    def _sa_tick(self):
        if not self._running: return
        if self._sa_remain > 0:
            self._sa_remain -= 1
            self._sa_cd_lbl.config(text=f"⏱  Stops in: {self._fmt_dur(self._sa_remain)}")
            self._sa_id = self.after(1000, self._sa_tick)
        else:
            self._sa_cd_lbl.config(text="⏱  Time's up — stopping…")
            action = self._action_var.get()
            param  = self._param_entry.get()
            self._stop()
            self.after(300, lambda: do_action(action, param))

    # ── Wiggle countdown ─────────────────────────────────────────────────────

    def _draw_dot(self, colour):
        self._dot.delete("all")
        self._dot.create_oval(1, 1, 11, 11, fill=colour, outline="")

    def _on_interval_change(self):
        if self._running: self._countdown = self._interval_var.get()

    def _on_wiggle_cb(self):
        self._count += 1
        self._countdown = self._interval_var.get()
        self.after(0, lambda: self._count_lbl.config(
            text=f"Total wiggles: {self._count}"))

    def _tick(self):
        if not self._running: return
        if self._countdown > 0: self._countdown -= 1
        self._cd_lbl.config(text=f"Next wiggle in: {self._countdown}s")
        self._tick_id = self.after(1000, self._tick)

    # ── Dark title bar ────────────────────────────────────────────────────────

    def _apply_dark_titlebar(self):
        """Use DWM API to give the native title bar a dark background (Win10/11)."""
        try:
            dwmapi = ctypes.windll.dwmapi
            dwmapi.DwmSetWindowAttribute.argtypes = [
                ctypes.c_void_p,   # HWND
                ctypes.c_uint,     # DWMWINDOWATTRIBUTE
                ctypes.c_void_p,   # pvAttribute
                ctypes.c_uint,     # cbAttribute
            ]
            dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long  # HRESULT
            hwnd = self.winfo_id()
            val  = ctypes.c_int(1)
            # Try Win11 / Win10 21H1+ attribute first, fall back to older attribute
            for attr in (20, 19):
                hr = dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd), attr,
                    ctypes.byref(val), ctypes.sizeof(val)
                )
                if hr == 0:   # S_OK — succeeded
                    break
            # Toggle visibility to force the title bar to re-render
            self.withdraw()
            self.after(20, self.deiconify)
        except Exception:
            pass

    # ── Tray ─────────────────────────────────────────────────────────────────

    def _minimize_to_tray(self):
        self.withdraw()
        if self._tray is None or not self._tray.is_alive():
            self._tray = _SysTray(
                "Wiggler — Anti-AFK",
                on_restore=lambda: self.after(0, self._restore_from_tray),
                on_quit=lambda: self.after(0, self._on_close),
            )
            self._tray.start()

    def _restore_from_tray(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        if self._tray:
            self._tray.stop()
            self._tray = None

    # ── Toggle ───────────────────────────────────────────────────────────────

    def _toggle(self):
        if self._running: self._stop()
        else: self._start()

    def _start(self):
        self._running    = True
        self._count      = 0
        self._countdown  = self._interval_var.get()
        self._count_lbl.config(text="Total wiggles: 0")

        self._thread = WigglerThread(
            get_distance = lambda: self._dist_var.get(),
            get_interval = lambda: self._interval_var.get(),
            get_duration = lambda: self._duration_var.get(),
            on_wiggle    = self._on_wiggle_cb,
        )
        self._thread.start()

        self._btn.config(text="⏹  Stop", bg=DANGER, activebackground="#b91c1c",
                         padx=22)
        self._status_lbl.config(text="Running", fg=GREEN)
        self._draw_dot(GREEN)
        self._tick()

        if self._sa_enabled.get():
            total = self._sa_total_secs()
            if total > 0:
                self._sa_remain = total
                self._sa_cd_lbl.config(text=f"⏱  Stops in: {self._fmt_dur(total)}")
                self._sa_tick()

    def _stop(self):
        self._running = False
        if self._thread:  self._thread.stop();              self._thread = None
        if self._tick_id: self.after_cancel(self._tick_id); self._tick_id = None
        if self._sa_id:   self.after_cancel(self._sa_id);   self._sa_id = None

        self._btn.config(text="▶  Start", bg=GREEN, activebackground="#2ea043",
                         padx=18)
        self._status_lbl.config(text="Idle", fg=MUTED)
        self._draw_dot(MUTED)
        self._cd_lbl.config(text="")
        self._sa_cd_lbl.config(text="")

    def _on_close(self):
        self._stop()
        if self._tray: self._tray.stop(); self._tray = None
        self.destroy()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _div(parent):
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=20, pady=4)

def _spacer(parent, h=8):
    tk.Frame(parent, bg=parent.cget("bg"), height=h).pack()


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try: ctypes.windll.kernel32.FreeConsole()
    except Exception: pass
    WigglerApp().mainloop()

