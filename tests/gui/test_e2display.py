def test_display_initial_gui(main_form, win):
    main_form = main_form('e2display', [])
    win = win('e2display')
    win(main_form)
