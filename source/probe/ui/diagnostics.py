import json
import time

from ..engine import MODES


def smoke_test(app, report):
    try:
        for mode in MODES:
            app.choose_mode(mode)
            app.update_idletasks()
        app.test_lab()
        for tab in (0, 1):
            app.testlab_notebook.select(tab)
            app.update_idletasks()
        for page in (app.traffic_tab,app.plot,app.terminal):
            app.notebook.select(page);app.update_idletasks()
            if app.notebook.select()!=str(page):raise RuntimeError("Main workspace tab is not selectable.")
        app.plot.feed(dict(direction="RX",peer="smoke",data=b"1,2\n3,4\n"));app.plot.render(force=True)
        if not app.plot.canvas.find_withtag("curve"):raise RuntimeError("Live plot failed in bundle.")
        app.terminal.feed(dict(direction="RX",peer="smoke",data=b"READY\r\n"));app.terminal.render(force=True)
        if "READY" not in "".join(app.terminal.model.screen.display):raise RuntimeError("Terminal failed in bundle.")
        app.notebook.select(app.traffic_tab)
        for payload in (b'{"sessionId":"1"}',b'{"sessionId":"123"}'):
            app.add_event(dict(kind="data",direction="RX",peer="smoke",time=time.time(),data=payload))
        app.table.selection_set(app.order[-1])
        analysis=app.analyze()
        app.update_idletasks()
        if not any(field.selector=="/sessionId" for field in analysis.protocol.fields):raise RuntimeError("Protocol Inspector failed in bundle.")
        if not analysis.comparison.differences:raise RuntimeError("Capture Diff failed in bundle.")
        if "123" not in analysis.payload.decoded.get("1.0","end"):raise RuntimeError("Analyze decoded text failed in bundle.")
        if not analysis.payload.byte_table.get_children():raise RuntimeError("Analyze byte views failed in bundle.")
        analysis.destroy()
        app.table.selection_set(app.order[-2:])
        comparison=app.compare_selected()
        if comparison.comparison.a!=app.events[app.order[-2]]["data"] or comparison.comparison.b!=app.events[app.order[-1]]["data"]:
            raise RuntimeError("Selected-message Capture Diff failed in bundle.")
        if len(app.table.selection())!=2:raise RuntimeError("Traffic multi-selection changed during comparison.")
        comparison.destroy()
        simulator=app.simulator_panel
        rule=simulator.edit_rule(True)
        rule.vars["match_mode"].set("Fields");rule.update_match()
        rule.vars["fault"].set("Split");rule.update_fault()
        rule.notebook.select(1);app.update_idletasks();rule.destroy()
        framing=simulator.edit_framing();app.update_idletasks();framing.destroy()
        pane=app.sequence_panel
        app.current_probe.macros=[dict(name="Smoke template",text="${sid}",flow=dict(extract=[dict(name="sid",source="JSON",selector="sessionId")]))]
        pane.refresh();pane.open_editor(0)
        rules=pane.response_rules();rules.tabs.select(1);app.update_idletasks();rules.destroy();pane.editor.destroy()
        variables=pane.variables_dialog();app.update_idletasks();variables.destroy()
        if app.terminal.error: raise RuntimeError(app.terminal.error)
        from ..diagnostics import wait_for
        primary=app.current_probe
        secondary=app.new_probe();secondary.save_settings=lambda:None
        for probe in (primary,secondary):
            probe.choose_mode("USB / Serial");probe.vars["serial_port"].set("loop://");probe.toggle()
        wait_for(lambda:all(p.engine.ready for p in (primary,secondary)))
        primary.engine.send(b"PRIMARY");secondary.engine.send(b"SECONDARY")
        wait_for(lambda:primary.engine.rx==7 and secondary.engine.rx==9)
        app.update()
        for probe,amount in ((primary,100000),(secondary,10000)):
            probe.add_event(dict(kind='data',direction='TX',peer='trace-smoke',time=time.time(),
                data=json.dumps(dict(sid='trace-smoke',amount=amount)).encode()))
        trace=app.trace_path(primary);trace.reference.set(next(reversed(trace.references)))
        trace.field.set('sid');trace.match();app.update_idletasks()
        if len(trace.matches)!=1:raise RuntimeError('Trace identifier match failed in bundle.')
        diff=trace.compare().comparison
        if not any(d.kind in ('changed','removed','added') for d in diff.differences):raise RuntimeError('Trace Capture Diff failed in bundle.')
        trace.destroy()
        primary.clear_search();primary.vars['search_mode'].set('Hex bytes')
        if len(primary.table.get_children())!=len(primary.events):raise RuntimeError('Search type hid traffic before Search in bundle.')
        app.close_probe(secondary)
        if not primary.engine.ready:raise RuntimeError("Closing one probe stopped another connection.")

    except Exception as exc:
        report(False, str(exc))
        app.close()
        raise SystemExit(1)
    report(True)
    app.close()
