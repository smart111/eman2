import os
import e2display
import pytest


@pytest.fixture
def main_form():
    dirname = 'e2display'
    if not os.path.isdir(dirname):
        os.mkdir(dirname)
    main_form = e2display.main([])
    yield main_form
    main_form.close()

def test_display_file(qtbot, main_form, win):
    win.cycle(qtbot, main_form,'e2display')
