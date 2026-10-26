"""Original Probe vector identity: two endpoints connected by a measured signal."""
import tkinter as tk


def draw_mark(canvas, x, y, size, colors):
    """A signal path between two endpoints; shared with the app icon source."""
    def points(values):return [v*size+(x if i%2==0 else y) for i,v in enumerate(values)]
    canvas.create_line(*points((.18,.72,.18,.28,.48,.28,.48,.52,.82,.52)),
                       fill=colors["accent"],width=max(2,size*.08),joinstyle="round")
    for cx,cy in ((.18,.72),(.82,.52)):
        radius=size*.09
        canvas.create_oval(x+cx*size-radius,y+cy*size-radius,x+cx*size+radius,y+cy*size+radius,
                           fill=colors["blue"],outline="")


class Chassis(tk.Canvas):
    """Flat brand header. Class name retained for saved layout integrations."""
    def __init__(self,parent,app,**kwargs):
        super().__init__(parent,height=66,highlightthickness=0,**kwargs)
        self.app=app;self.bind("<Configure>",lambda event:self.redraw())

    def redraw(self):
        c=self.app.colors;self.configure(bg=c["bg"]);self.delete("all")
        w=self.winfo_width();h=self.winfo_height();compact=h<55
        size=36 if compact else 48
        draw_mark(self,0,(h-size)/2,size,c)
        self.create_text(size+12,h/2,text="probe",anchor="w",fill=c["text"],
                         font=(self.app.ui_font,24 if compact else 30,"bold"))
        if w>430:
            self.create_text(190,h/2-8,text="COMMUNICATIONS WORKBENCH",anchor="w",
                             fill=c["muted"],font=(self.app.ui_font,10,"bold"))
            self.create_text(190,h/2+10,text="Connect · Observe · Understand",anchor="w",
                             fill=c["muted"],font=(self.app.ui_font,11))
        if w>760:
            self.create_text(w-8,h/2,text="TCP  /  UDP  /  SERIAL",anchor="e",
                             fill=c["accent"],font=(self.app.mono,10))
        self.create_line(0,h-1,w,h-1,fill=c["border"])


class MeterStrip(tk.Canvas):
    """Legacy extension handle; decorative meter marks have been retired."""
    def __init__(self,parent,app,**kwargs):
        super().__init__(parent,width=1,height=1,highlightthickness=0,**kwargs);self.app=app
    def redraw(self):self.configure(bg=self.app.colors["lcd"]);self.delete("all")


class Rail(tk.Canvas):
    def __init__(self,parent,app):
        super().__init__(parent,width=1,highlightthickness=0);self.app=app
    def redraw(self):self.configure(bg=self.app.colors["bg"]);self.delete("all")
