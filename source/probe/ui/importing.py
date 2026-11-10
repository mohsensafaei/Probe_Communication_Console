from tkinter import ttk
from .widgets import Actions, modal


class ImportPreview(Actions):
    def __init__(self,parent,app,description,apply):
        import tkinter as tk
        self.window=modal(parent,'Review import','780x580',(680,480));self.feedback=tk.StringVar()
        body=ttk.Frame(self.window,padding=16);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Review before applying',font=(app.ui_font,18,'bold')).pack(anchor='w')
        ttk.Label(body,text='Validation passed. Applying replaces the current configuration; it never connects or sends.',wraplength=700).pack(anchor='w',pady=8)
        text=app.text_widget(body,height=15,wrap='word');text.pack(fill='both',expand=True)
        app.put_text(text,description)
        ttk.Label(body,textvariable=self.feedback,wraplength=700).pack(anchor='w',pady=5)
        actions=ttk.Frame(body);actions.pack(fill='x',pady=6)
        def confirm():
            apply();self.window.destroy()
        self.apply_button=ttk.Button(actions,text='Apply import',style='Accent.TButton',command=lambda:self.action(confirm));self.apply_button.pack(side='right')
        ttk.Button(actions,text='Cancel',command=self.window.destroy).pack(side='right',padx=8)
        self.window.grab_set()
