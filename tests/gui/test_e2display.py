def test_display_file(qtbot, win):
    win = win('e2display',[])
    qtbot.addWidget(win.main_form)
    win.cycle(qtbot, win.main_form)
