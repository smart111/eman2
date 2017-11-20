import pytest
from PyQt4.QtCore import Qt
import os
import e2filtertool


@pytest.fixture
def main_form(curdir):
    dirname = 'e2filtertool'
    if not os.path.isdir(dirname):
        os.mkdir(dirname)
    main_form = e2filtertool.main_loop('%s'%os.path.join(curdir,'e2display/twod.hdf'))
    yield main_form
    main_form.close()

def test_mouseClick_altModifier(qtbot, main_form, win):
    win.cycle(qtbot, main_form,'e2filtertool')
    win.cycle(qtbot, main_form.viewer[0],'e2filtertool')
    qtbot.mouseClick(main_form.viewer[0], Qt.LeftButton, Qt.AltModifier)
    qtbot.wait(1000)
# Need a set of filters and filter types to test spinboxes, checkboxes and buttons
