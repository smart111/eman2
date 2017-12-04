from PyQt4.QtCore import Qt
import os


def test_display_initial_gui(main_form, win, curdir, qtbot):
    main_form = main_form('e2filtertool',['%s'%os.path.join(curdir,'e2display/twod.hdf')])
    win = win('e2filtertool')
    win(main_form)
    win(main_form.viewer[0])
    qtbot.mouseClick(main_form.viewer[0], Qt.LeftButton, Qt.AltModifier)
    qtbot.wait(1000)
# Need a set of filters and filter types to test spinboxes, checkboxes and buttons
