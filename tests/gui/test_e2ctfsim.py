@pytest.fixture
def main_form():
    dirname = 'e2ctfsim'
    if not os.path.isdir(dirname):
        os.mkdir(dirname)

    main_form = e2ctfsim.main_loop([])
    yield main_form
    main_form.close()

def test_cli(qtbot, main_form, win):
    win.cycle(qtbot, main_form,'e2ctfsim')

    win.cycle(qtbot, main_form.guiim,'e2ctfsim')
    win.cycle(qtbot, main_form.guiplot,'e2ctfsim')

