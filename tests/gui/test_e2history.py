from PyQt4.QtCore import Qt


def test_okButton(main_form, win, qtbot):
    main_form = main_form('e2history',["--gui"])
    win = win('e2history')
    win(main_form.form)
    qtbot.mouseClick(main_form.form.layout().itemAt(1).itemAt(1).widget(), Qt.LeftButton)
