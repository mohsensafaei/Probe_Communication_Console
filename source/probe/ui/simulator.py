'Progressively disclosed editors for device matching and repeatable faults.'
import tkinter as tk
from dataclasses import replace
from tkinter import ttk

from ..codec import parse_hex
from ..protocol import CHECKSUMS
from ..simulation import DeviceModel, Exchange, Reply, model_from_dict, model_to_dict
from ..simulator_rules import (
    FAULTS,
    FRAME_MODES,
    OPERATORS,
    SOURCES,
    Condition,
    Fault,
    FrameSpec,
    integer,
    milliseconds,
)


class Editor(tk.Toplevel):
    def __init__(self, pane, title, geometry, owner=None):
        super().__init__(owner or pane)
        self.pane = pane
        self.title('Probe · '+title)
        self.geometry(geometry)
        self.minsize(*map(int, geometry.split('x')))
        self.configure(bg=pane.app.colors['panel'])
        self.transient((owner or pane).winfo_toplevel())
        self.body = ttk.Frame(self, padding=16)
        self.feedback = tk.StringVar(self)
        bottom = ttk.Frame(self, padding=(16, 8, 16, 16)); bottom.pack(side='bottom', fill='x')
        self.body.pack(fill='both', expand=True)
        ttk.Label(bottom, textvariable=self.feedback, wraplength=600).pack(anchor='w', pady=4)
        ttk.Button(bottom, text='Save', style='Accent.TButton', command=self.save_checked).pack(side='right')
        ttk.Button(bottom, text='Cancel', command=self.destroy).pack(side='right', padx=8)
        self.vars = {}
        self.widgets = {}

    def field(self, parent, key, label, value='', choices=None):
        row=ttk.Frame(parent); row.pack(fill='x', pady=4)
        ttk.Label(row, text=label, width=27, wraplength=210).pack(side='left', anchor='n')
        var=tk.StringVar(self, value=value); self.vars[key]=var
        widget=ttk.Combobox(row, textvariable=var, values=choices, state='readonly') if choices else ttk.Entry(row,textvariable=var)
        widget.pack(side='left', fill='x', expand=True)
        self.widgets[key]=widget
        return widget

    def save_checked(self):
        try: self.save()
        except (ValueError, TypeError, KeyError, OSError) as exc: self.feedback.set(str(exc))


class FrameEditor(Editor):
    def __init__(self, pane):
        super().__init__(pane, 'Request framing', '660x540')
        spec = pane.app.simulator_model.framing if pane.app.simulator_model else None
        spec = spec or getattr(pane, "pending_framing", None) or FrameSpec()
        ttk.Label(self.body,text='How does a complete request end?',font=(pane.app.ui_font,16,'bold')).pack(anchor='w',pady=(0,10))
        self.field(self.body,'mode','Message boundary',spec.mode if (pane.app.simulator_model and pane.app.simulator_model.framing) or getattr(pane, 'pending_framing', None) else 'Exact stream',('Exact stream',)+FRAME_MODES).bind('<<ComboboxSelected>>',self.update_fields)
        self.options=ttk.Frame(self.body);self.options.pack(fill='x')
        self.checks=ttk.Frame(self.body);self.checks.pack(fill='x',pady=6)
        ttk.Label(self.body,text='Field conditions read the payload: prefix, delimiter and trailing checksum are excluded.\nOffsets start at zero. Exact stream preserves legacy recorded-byte matching.',wraplength=610).pack(anchor='w',pady=12)
        self.spec=spec;self.update_fields()

    def update_fields(self,event=None):
        old={k:v.get() for k,v in self.vars.items()}
        for box in (self.options,self.checks):
            for child in box.winfo_children():child.destroy()
        mode=self.vars['mode'].get();s=self.spec
        if mode=='Delimiter':self.field(self.options,'delimiter','Delimiter (hex)',old.get('delimiter',s.delimiter.hex(' ').upper()))
        if mode=='Fixed length':self.field(self.options,'size','Full request size (bytes)',old.get('size',s.size))
        if mode=='Length prefix':
            self.field(self.options,'prefix_size','Prefix size (bytes)',old.get('prefix_size',s.prefix_size))
            self.field(self.options,'prefix_format','Prefix encoding',old.get('prefix_format',s.prefix_format),('ASCII','Unsigned LE','Unsigned BE'))
            ttk.Label(self.options,text='Length counts everything after the prefix, including the checksum.',wraplength=600).pack(anchor='w')
        if mode not in ('JSON','Exact stream'):
            self.field(self.checks,'check','Trailing checksum',old.get('check',s.check),('None',)+CHECKSUMS)
            self.field(self.checks,'check_start','Checksum coverage starts at',old.get('check_start',s.check_start))
        if mode=='JSON':ttk.Label(self.options,text='Accepts UTF-8 objects/arrays, with an optional ASCII body-length prefix.\nMalformed JSON and incorrect declared lengths are rejected.',wraplength=600).pack(anchor='w')

    def save(self):
        self.pane.ensure_editable()
        mode=self.vars['mode'].get();s=self.spec
        get=lambda key,default:self.vars[key].get() if key in self.vars else default
        spec=None if mode=='Exact stream' else FrameSpec(mode,parse_hex(get('delimiter',s.delimiter.hex())),integer(get('size',s.size),'Request size',1),integer(get('prefix_size',s.prefix_size),'Prefix size',1,12),get('prefix_format',s.prefix_format),'None' if mode=='JSON' else get('check',s.check),integer(get('check_start',s.check_start),'Checksum start'))
        model=self.pane.app.simulator_model
        if model:self.pane.install(model_from_dict(model_to_dict(replace(model,framing=spec))))
        else:
            self.pane.pending_framing=spec
            self.pane.framing_info.set('Request framing: '+(spec.mode if spec else 'Exact stream'))
        self.destroy()


class ConditionEditor(Editor):
    def __init__(self, pane, callback, condition=None, owner=None):
        super().__init__(pane,'Request field','640x440',owner)
        self.callback=callback;self.condition=condition or Condition(selector='data.service')
        c=self.condition
        self.field(self.body,'source','Read from',c.source,SOURCES).bind('<<ComboboxSelected>>',self.update_fields)
        self.options=ttk.Frame(self.body);self.options.pack(fill='x');self.update_fields()
        self.field(self.body,'operator','Condition',c.operator,OPERATORS)
        self.field(self.body,'value','Expected value',c.value)
        ttk.Label(self.body,text='All conditions in a rule must match. “exists” checks that the field is present.\nJSON: data.service or /data/service · TLV: tag such as 9F02 or E1/9F02.',wraplength=590).pack(anchor='w',pady=10)

    def update_fields(self,event=None):
        for child in self.options.winfo_children():child.destroy()
        c=self.condition;source=self.vars['source'].get()
        if source in ('JSON','TLV','BER-TLV'):self.field(self.options,'selector','Field path / tag',c.selector)
        if source=='Bytes':
            self.field(self.options,'offset','Payload byte offset',c.offset)
            self.field(self.options,'length','Number of bytes',c.length)
        if source in ('TLV','BER-TLV','Bytes'):self.field(self.options,'format','Interpret as',c.format,('Text','Hex','Unsigned LE','Unsigned BE'))

    def save(self):
        v=self.vars;source=v['source'].get()
        condition=Condition(source,v['selector'].get() if source in ('JSON','TLV','BER-TLV') else '',v['operator'].get(),v['value'].get(),integer(v['offset'].get(),'Offset') if source=='Bytes' else 0,integer(v['length'].get(),'Length',1) if source=='Bytes' else 1,v['format'].get() if source in ('TLV','BER-TLV','Bytes') else 'Text')
        self.callback(condition);self.destroy()


class RuleEditor(Editor):
    def __init__(self,pane,index=None):
        super().__init__(pane,'Device rule','780x680')
        self.index=index
        self.original=pane.app.simulator_model.exchanges[index] if index is not None else Exchange(b'',(Reply(b''),))
        item=self.original;self.conditions=list(item.match or ())
        self.field(self.body,'name','Rule name',item.name)
        notebook=ttk.Notebook(self.body);notebook.pack(fill='both',expand=True,pady=8)
        main=ttk.Frame(notebook,padding=12);fault=ttk.Frame(notebook,padding=12)
        notebook.add(main,text='Request & reply');notebook.add(fault,text='Fault injection')
        self.notebook=notebook
        self.field(main,'match_mode','Match request by','Fields' if item.match else 'Exact bytes',('Exact bytes','Fields')).bind('<<ComboboxSelected>>',self.update_match)
        self.match_box=ttk.Frame(main);self.match_box.pack(fill='both',expand=True)
        self.request_hex=item.request.hex(' ').upper()
        self.update_match()
        self.reply_input_mode='Hex'
        self.field(main,'reply_format','Reply input','Hex',('Hex','Text (UTF-8)')).bind('<<ComboboxSelected>>',self.convert_reply)
        self.field(main,'reply','Reply payload',b''.join(r.data for r in item.replies).hex(' ').upper())
        self.initial_delay=f'{sum(r.delay_ms for r in item.replies):g}'
        self.field(main,'delay','Reply delay (ms)',self.initial_delay)
        ttk.Label(main,text='A respond() plugin can build the reply, even when this payload is empty. Otherwise Probe uses the configured reply and timing.',wraplength=690).pack(anchor='w',pady=8)
        self.fault_original=item.fault or Fault('Delay')
        self.field(fault,'fault','Inject a fault',item.fault.kind if item.fault else 'None',('None',)+FAULTS).bind('<<ComboboxSelected>>',self.update_fault)
        self.fault_box=ttk.Frame(fault);self.fault_box.pack(fill='x')
        self.update_fault()
        ttk.Label(fault,text='Triggers count matches of this rule separately for each connected app. Reset matching\nclears the counters. Reply timing × also scales fault delays and gaps.',wraplength=690).pack(anchor='w',pady=12)

    def convert_reply(self,event=None):
        target=self.vars['reply_format'].get()
        try:
            raw=parse_hex(self.vars['reply'].get()) if self.reply_input_mode=='Hex' else self.vars['reply'].get().encode('utf-8')
            value=raw.hex(' ').upper() if target=='Hex' else raw.decode('utf-8')
        except (ValueError,UnicodeError) as exc:
            self.vars['reply_format'].set(self.reply_input_mode)
            self.feedback.set('Cannot convert this reply: '+str(exc));return
        self.vars['reply'].set(value);self.reply_input_mode=target;self.feedback.set('')

    def update_match(self,event=None):
        if 'request' in self.vars:self.request_hex=self.vars['request'].get()
        for child in self.match_box.winfo_children():child.destroy()
        if self.vars['match_mode'].get()=='Exact bytes':
            self.field(self.match_box,'request','Request payload (hex)',self.request_hex)
            ttk.Label(self.match_box,text='Matches the exact recorded bytes across any number of reads.').pack(anchor='w',pady=10)
            return
        ttk.Label(self.match_box,text='Match every condition below; changing unrelated fields is allowed.').pack(anchor='w')
        self.table=ttk.Treeview(self.match_box,columns=('field','condition','value'),show='headings',height=4,selectmode='browse')
        for key,title,width in (('field','Field / byte range',250),('condition','Condition',120),('value','Expected value',180)):
            self.table.heading(key,text=title);self.table.column(key,width=width)
        self.table.pack(fill='both',expand=True,pady=5)
        self.table.bind('<Double-1>',lambda e:self.edit_condition())
        bar=ttk.Frame(self.match_box);bar.pack(fill='x')
        for text,fn in (('Add condition…',lambda:self.edit_condition(True)),('Edit…',self.edit_condition),('Remove',self.remove_condition)):
            ttk.Button(bar,text=text,command=fn).pack(side='left',padx=(0,6))
        self.refresh_conditions()

    def refresh_conditions(self):
        self.table.delete(*self.table.get_children())
        for i,c in enumerate(self.conditions):self.table.insert('','end',iid=str(i),values=(f'{c.source}: {c.selector or (str(c.offset)+":"+str(c.offset+c.length) if c.source=="Bytes" else "request")}',c.operator,c.value))

    def edit_condition(self,new=False):
        selected=self.table.selection()
        if not new and not selected:self.feedback.set('Select a condition to edit.');return
        index=None if new else int(selected[0])
        def accept(c):
            if index is None:self.conditions.append(c)
            else:self.conditions[index]=c
            self.refresh_conditions()
        self.condition_editor=ConditionEditor(self.pane,accept,None if index is None else self.conditions[index],owner=self)

    def remove_condition(self):
        selected=self.table.selection()
        if selected:del self.conditions[int(selected[0])];self.refresh_conditions()

    def update_fault(self,event=None):
        old={k:v.get() for k,v in self.vars.items()}
        for child in self.fault_box.winfo_children():child.destroy()
        kind=self.vars['fault'].get();f=self.fault_original
        if kind=='None':
            ttk.Label(self.fault_box,text='Normal device behavior. Enable a fault to test application recovery.').pack(anchor='w',pady=12);return
        self.field(self.fault_box,'trigger','When to inject',old.get('trigger',f.trigger),('Every match','Once on match N','Every Nth match'))
        self.field(self.fault_box,'nth','N (matching request)',old.get('nth',f.nth))
        if kind=='Delay':self.field(self.fault_box,'extra_delay','Additional delay (ms)',old.get('extra_delay',f.delay_ms))
        if kind=='Error reply':self.field(self.fault_box,'error_payload','Complete error reply (hex)',old.get('error_payload',f.payload.hex(' ').upper()))
        if kind in ('Disconnect','Truncate','Duplicate','Split'):
            default=f.count if f.kind==kind else 2 if kind=='Duplicate' else 1
            self.field(self.fault_box,'count',{'Disconnect':'Send bytes, then disconnect','Truncate':'Keep first N reply bytes','Duplicate':'Total copies (2–16)','Split':'Bytes per chunk'}[kind],default)
        if kind in ('Duplicate','Split'):self.field(self.fault_box,'gap','Gap between copies/chunks (ms)',old.get('gap',f.gap_ms))
        if kind=='Corrupt byte':
            self.field(self.fault_box,'offset','Reply offset (-1 = last byte)',old.get('offset',f.offset))
            self.field(self.fault_box,'mask','XOR mask (decimal 1–255)',old.get('mask',f.xor_mask))
        hints={'No reply':'Consumes the request and advances the conversation without sending a reply.', 'Disconnect':'TCP: closes this client; the server keeps listening. Serial: closes Probe’s endpoint.\nClosing one end of a virtual COM pair may not appear as unplugging to the app.', 'Corrupt byte':'Select the CRC byte offset to damage a checksum. Probe does not guess its location.', 'Split':'Sends separate writes with a gap. TCP may merge them into different read chunks.', 'Truncate':'Keeps the connection open after a partial reply.'}
        ttk.Label(self.fault_box,text=hints.get(kind,''),wraplength=670).pack(anchor='w',pady=10)

    def save(self):
        self.pane.ensure_editable();v=self.vars;item=self.original
        semantic=v['match_mode'].get()=='Fields'
        if semantic and not self.conditions:raise ValueError('Add at least one request condition.')
        request=parse_hex(self.request_hex) if semantic else parse_hex(v['request'].get())
        payload=v['reply'].get().encode('utf-8') if v['reply_format'].get()=='Text (UTF-8)' else parse_hex(v['reply'].get())
        delay=milliseconds(v['delay'].get())
        unchanged=v['reply_format'].get()=='Hex' and payload==b''.join(r.data for r in item.replies) and v['delay'].get()==self.initial_delay
        replies=item.replies if unchanged else (Reply(payload,delay),) if payload or delay else ()
        kind=v['fault'].get();fault=None
        if kind!='None':
            get=lambda key,default:v[key].get() if key in v else default
            fault=Fault(kind,get('trigger','Every match'),integer(get('nth',1),'N',1,1000000),milliseconds(get('extra_delay',0)),parse_hex(get('error_payload','')),integer(get('count',1),'Count',0,8*1024*1024),milliseconds(get('gap',0)),integer(get('offset',-1),'Offset',-1,8*1024*1024),integer(get('mask',1),'XOR mask',1,255))
        exchange=Exchange(request,replies,tuple(self.conditions) if semantic else None,fault,v['name'].get().strip())
        model=self.pane.app.simulator_model
        items=list(model.exchanges) if model else []
        if self.index is None:items.append(exchange)
        else:items[self.index]=exchange
        framing=model.framing if model else getattr(self.pane,'pending_framing',None)
        if semantic and framing is None:
            if all(e.match and all(c.source=='JSON' for c in e.match) for e in items):framing=FrameSpec()
            else:raise ValueError('Choose Request framing on the simulator first, then add field rules.')
        self.pane.install(model_from_dict(model_to_dict(DeviceModel(tuple(items),framing=framing))))
        self.pane.table.selection_set(str(len(items)-1 if self.index is None else self.index))
        self.destroy()
