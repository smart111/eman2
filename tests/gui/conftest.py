import pytest
import os


def pytest_configure(config):
    import EMAN2
    EMAN2._called_from_test = True

def pytest_unconfigure(config):
    import EMAN2
    del EMAN2._called_from_test

@pytest.fixture
def curdir(request):
    return request.fspath.dirname

# args default is [] rather than None,
# otherwise command-line args passed to pytest are captured
def get_main_form(module_name, args=[]):
    module = __import__(module_name)
    main_form = module.main(args)
    
    return main_form

@pytest.fixture
def main_form():
    return get_main_form
