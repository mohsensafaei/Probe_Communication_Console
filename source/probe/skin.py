"""Original Probe instrument housing and hardware test-probe emblem."""
import tkinter as tk


def draw_mark(canvas,x,y,size,colors):
    def pts(values):return [v*size+(x if i%2==0 else y) for i,v in enumerate(values)]
    def polygon(values,color):canvas.create_polygon(*pts(values),fill=color,outline="")
    # Insulated lead, sculpted grip, finger guard, metal shaft and contact tip.
    canvas.create_line(*pts((.29,.70,.20,.79,.20,.88,.30,.92,.40,.88)),
                       fill=colors["blue"],width=max(2,size*.065),smooth=True)
    polygon((.24,.62,.35,.73,.65,.43,.54,.32),colors["metal"])
    polygon((.27,.64,.31,.68,.61,.38,.57,.34),colors["shine"])
    polygon((.48,.30,.54,.24,.73,.43,.67,.49),colors["accent"])
    polygon((.61,.28,.66,.33,.84,.15,.79,.10),colors["metal"])
    polygon((.79,.10,.84,.15,.91,.03),colors["accent"])
    for delta in (0,.08,.16):
        canvas.create_line(*pts((.32+delta,.59-delta,.37+delta,.64-delta)),
                           fill=colors["border"],width=max(1,size*.025))


class Chassis(tk.Canvas):
    def __init__(self,parent,app,**kwargs):
        super().__init__(parent,height=66,highlightthickness=0,**kwargs)
        self.app=app;self.bind("<Configure>",lambda event:self.redraw())

    def redraw(self):
        c=self.app.colors;self.configure(bg=c["bg"]);self.delete("all")
        w=self.winfo_width();h=self.winfo_height();compact=h<55
        # Symmetric instrument shell, with a separate enamel name plate.
        self.create_polygon(0,9,9,0,w-9,0,w,9,w,h-9,w-9,h,9,h,0,h-9,
                            fill=c["metal"],outline=c["shine"])
        self.create_rectangle(6,5,w-6,h-6,fill=c["panel"],outline=c["border"])
        self.create_line(12,7,w-12,7,fill=c["shine"])
        size=35 if compact else 49
        draw_mark(self,12,(h-size)/2,size,c)
        self.create_text(size+27,h/2-5,text="PROBE",anchor="w",fill=c["text"],
                         font=(self.app.display_font,16 if compact else 20))
        if not compact:
            self.create_text(size+28,h-13,text="COMMUNICATIONS WORKBENCH",anchor="w",
                             fill=c["muted"],font=(self.app.ui_font,8,"bold"))
        if w>500:
            self.create_line(275,15,275,h-15,fill=c["border"])
            self.create_text(295,h/2-8,text="CONNECT  /  OBSERVE  /  UNDERSTAND",anchor="w",
                             fill=c["text"],font=(self.app.ui_font,11,"bold"))
            self.create_text(295,h/2+10,text="TCP  ·  UDP  ·  USB SERIAL",anchor="w",
                             fill=c["blue"],font=(self.app.mono,10))
        if w>810:
            self.create_rectangle(w-120,17,w-17,h-17,fill=c["lcd"],outline=c["border"])
            self.create_text(w-68,h/2,text="BYTE EXACT",fill=c["accent"],font=(self.app.ui_font,10,"bold"))


class MeterStrip(tk.Canvas):
    """Legacy extension handle. No decorative signal gauges."""
    def __init__(self,parent,app,**kwargs):
        super().__init__(parent,width=1,height=1,highlightthickness=0,**kwargs);self.app=app
    def redraw(self):self.configure(bg=self.app.colors["lcd"]);self.delete("all")


class Rail(tk.Canvas):
    def __init__(self,parent,app):
        super().__init__(parent,width=5,highlightthickness=0);self.app=app
        self.bind("<Configure>",lambda event:self.redraw())
    def redraw(self):
        c=self.app.colors;self.configure(bg=c["bg"]);self.delete("all")
        self.create_line(2,0,2,self.winfo_height(),fill=c["border"],width=2)
        self.create_line(3,0,3,self.winfo_height(),fill=c["metal"])
