import pytest
from PyQt4.QtGui import QPixmap
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

@pytest.fixture
def cycle(qtbot):
    def get_cycle(form, clickButton=None):
        form.raise_()
        form.activateWindow()
        qtbot.waitForWindowShown(form)
        
        if clickButton:
            qtbot.mouseClick(form, clickButton)
        qtbot.wait(100)
    
        # fname = '%s.png'%os.path.join(self.dir, str(self.counter))
        # qpxmap = QPixmap.grabWindow(form.winId())
        qtbot.wait(100)
    
        # qpxmap.save(fname,'png')
        qtbot.wait(100)
    
        # self.counter += 1
    
        # print("Click!: %s"%fname)
    return get_cycle

# cycle = cycle(form, clickButton=None)


@pytest.fixture
def win(qtbot):
    class Win(object):
        def __init__(self, dir):
            self.counter = 0
            self.dir = dir
            
            if not os.path.isdir(self.dir):
                os.mkdir(self.dir)
        
        def __call__(self, form, clickButton=None):
            form.raise_()
            form.activateWindow()
            qtbot.waitForWindowShown(form)

            if clickButton:
                qtbot.mouseClick(form, clickButton)
            qtbot.wait(100)

            fname = '%s.png'%os.path.join(self.dir, str(self.counter))
            qpxmap = QPixmap.grabWindow(form.winId())
            qtbot.wait(100)

            qpxmap.save(fname,'png')
            qtbot.wait(100)

            self.counter += 1

            print("Click!: %s"%fname)
    return Win
