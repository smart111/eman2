import os


@pytest.fixture
def main_form(curdir):
    dirname = 'e2evalimage'
    if not os.path.isdir(dirname):
        os.mkdir(dirname)
    main_form = e2evalimage.main_loop([os.path.join(curdir,'e2evalimage/BGal_000232.hdf')])
    yield main_form
    main_form.close()

def test_display_file(qtbot, main_form, win):
    qtbot.addWidget(main_form)

    win.cycle(qtbot, main_form,'e2evalimage')
    win.cycle(qtbot, main_form.wplot, 'e2evalimage')
    win.cycle(qtbot, main_form.wfft, 'e2evalimage')
    win.cycle(qtbot, main_form.wimage, 'e2evalimage')
