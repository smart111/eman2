from PyQt4.QtCore import Qt
import os


def test_mouseClick_altModifier(qtbot, win, curdir):
    win = win('e2filtertool','%s'%os.path.join(curdir,'e2display/twod.hdf'))
    win.cycle(qtbot, win.main_form)
    win.cycle(qtbot, win.main_form.viewer[0])
    qtbot.mouseClick(win.main_form.viewer[0], Qt.LeftButton, Qt.AltModifier)
    qtbot.wait(1000)
# Need a set of filters and filter types to test spinboxes, checkboxes and buttons
