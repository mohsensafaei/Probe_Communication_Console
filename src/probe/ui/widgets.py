import tkinter as tk
from tkinter import ttk


class Actions:
    def action(self, operation):
        try:return operation()
        except (ValueError, TypeError, KeyError, OSError, RuntimeError, RecursionError) as exc:self.feedback.set(str(exc))


def entry(parent, label, variable, row, column=0, values=None, width=20):
    box=ttk.Frame(parent);box.grid(row=row,column=column,sticky="ew",padx=(0,10),pady=4)
    ttk.Label(box,text=label).pack(anchor="w")
    widget=ttk.Combobox(box,textvariable=variable,values=values,state="readonly",width=width) if values else ttk.Entry(box,textvariable=variable,width=width)
    widget.pack(fill="x",pady=(3,0));return widget


def table(parent,columns,height=7):
    box=ttk.Frame(parent);box.pack(fill="both",expand=True,pady=6)
    view=ttk.Treeview(box,columns=tuple(key for key,_,_ in columns),show="headings",height=height,selectmode="browse")
    for key,title,width in columns:view.heading(key,text=title);view.column(key,width=width,minwidth=45,stretch=True)
    view.pack(side="left",fill="both",expand=True)
    scroll=ttk.Scrollbar(box,command=view.yview);scroll.pack(side="right",fill="y");view.configure(yscrollcommand=scroll.set)
    return view


def modal(parent,title,size="760x560",minimum=(700,500)):
    app=parent.app if hasattr(parent,"app") else parent
    win=tk.Toplevel(parent);win.title("Probe · "+title);win.geometry(size);win.minsize(*minimum)
    win.configure(bg=app.colors["panel"]);win.transient(parent.winfo_toplevel())
    win.bind("<Escape>",lambda event:win.destroy());return win
