"""Small vector-only instrument decorations, inspired by PC Probe II's chassis."""
import tkinter as tk


class Chassis(tk.Canvas):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, height=66, highlightthickness=0, **kwargs)
        self.app = app
        self.bind("<Configure>", lambda event: self.redraw())

    def redraw(self):
        c = self.app.colors
        self.configure(bg=c["bg"])
        self.delete("all")
        w = self.winfo_width(); h = self.winfo_height()
        self.create_polygon(0, 16, 16, 0, w-24, 0, w, 24, w, h-16,
                            w-16, h, 24, h, 0, h-24,
                            fill=c["metal"], outline=c["shine"])
        self.create_polygon(218, 4, w-26, 4, w-5, 26, w-5, h-17,
                            w-18, h-5, 188, h-5,
                            fill=c["panel"], outline=c["border"])
        self.create_line(10, 20, 22, 8, 196, 8, fill=c["shine"])
        compact = h < 55
        self.create_text(28, 20 if compact else 29, text="PROBE", anchor="w", fill=c["ink"],
                         font=(self.app.display_font, 17 if compact else 22))
        self.create_text(29, 37 if compact else 51, text="COMMUNICATIONS CONSOLE", anchor="w", fill=c["ink"],
                         font=(self.app.ui_font, 8 if compact else 9, "bold"))
        self.create_text(236, 23 if compact else 25, text="TCP  /  UDP  /  USB SERIAL", anchor="w",
                         fill=c["text"], font=(self.app.display_font, 10))
        if not compact:
            self.create_text(236, 47, text="DIRECT CONNECTION  •  PROXY MONITOR  •  BYTE INSPECTOR",
                             anchor="w", fill=c["muted"], font=(self.app.ui_font, 10))
        if w > 780:
            for i in range(7):
                x = w-73+i*6
                self.create_line(x, 22, x-10, 43, fill=c["accent"] if i<3 else c["border"], width=2)


class MeterStrip(tk.Canvas):
    def __init__(self, parent, app, **kwargs):
        super().__init__(parent, width=1, height=7, highlightthickness=0, **kwargs)
        self.app = app
        self.bind("<Configure>", lambda event: self.redraw())

    def redraw(self):
        c = self.app.colors; self.configure(bg=c["lcd"]); self.delete("all")
        w = self.winfo_width()
        # An ornamental bezel stripe, deliberately not a signal/traffic gauge.
        for x in range(0, w, 10):
            self.create_rectangle(x, 1, x+6, 4, fill=c["border"], outline="")


class Rail(tk.Canvas):
    def __init__(self, parent, app):
        super().__init__(parent, width=8, highlightthickness=0)
        self.app = app; self.bind("<Configure>", lambda event: self.redraw())

    def redraw(self):
        c = self.app.colors; h = self.winfo_height()
        self.configure(bg=c["bg"]); self.delete("all")
        self.create_polygon(0, 0, 7, 7, 7, h-7, 0, h, fill=c["metal"], outline=c["shine"])
        self.create_line(3, 40, 3, h-40, fill=c["blue"])
