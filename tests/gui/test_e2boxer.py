from PyQt4.QtCore import Qt
import os

def test_display_initial_gui(main_form, win, curdir):
    main_form = main_form('e2boxer', ["--gui", "--apix=1", "--no_ctf", os.path.join(curdir,'e2boxer/test_box.hdf')])
    win = win('e2boxer')
    win(main_form)
    win(main_form.wimage, Qt.LeftButton)
    win(main_form.wparticles)
