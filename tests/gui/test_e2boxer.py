import os
from PyQt4.QtCore import Qt
import e2boxer

import pytest

@pytest.fixture
def main_form(curdir):
    dirname = 'e2boxer'
    if not os.path.isdir(dirname):
        os.mkdir(dirname)
    main_form = e2boxer.main_loop(apix=1, imagenames=["1\t%s"%os.path.join(curdir,'e2boxer/test_box.hdf')])
    yield main_form
    main_form.close()
        
def test_cli(qtbot, main_form, win):
    win.cycle(qtbot, main_form,'e2boxer')
    
    win.cycle(qtbot, main_form.wimage,'e2boxer', Qt.LeftButton)
    win.cycle(qtbot, main_form.wparticles,'e2boxer')
