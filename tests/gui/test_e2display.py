def test_display_file(qtbot, win):
    win = win('e2display',[])
    win.cycle(qtbot, win.main_form)
