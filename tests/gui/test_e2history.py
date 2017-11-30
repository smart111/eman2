from PyQt4.QtCore import Qt


def test_okButton(qtbot, win):
    main_form = win('e2history').main_form
    qtbot.mouseClick(main_form.form.layout().itemAt(1).itemAt(1).widget(), Qt.LeftButton)
