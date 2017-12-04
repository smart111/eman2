import os


def test_display_initial_gui(main_form, win, curdir):
    main_form = main_form('e2evalimage',[os.path.join(curdir,'e2evalimage/BGal_000232.hdf')])
    win = win('e2evalimage')
    win(main_form)
    win(main_form.wplot)
    win(main_form.wfft)
    win(main_form.wimage)
