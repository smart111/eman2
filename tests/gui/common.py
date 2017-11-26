import os


def get_main_form(module_name, args=[]):
    module = __import__(module_name)
    if not os.path.isdir(module_name):
        os.mkdir(module_name)
    main_form = module.main_loop(args)
    return main_form
