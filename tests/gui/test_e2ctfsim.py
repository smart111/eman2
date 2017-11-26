def test_cli(qtbot, win):
    win = win('e2ctfsim')
    win.cycle(qtbot, win.main_form)
    win.cycle(qtbot, win.main_form.guiim)
    win.cycle(qtbot, win.main_form.guiplot)

