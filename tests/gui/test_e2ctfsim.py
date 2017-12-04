def test_cli(qtbot, win):
    main_form = main_form('e2ctfsim')
    win = win('e2ctfsim')
    win(main_form)
    win(main_form.guiim)
    win(main_form.guiplot)

