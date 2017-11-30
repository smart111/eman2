import pytest
from PyQt4.QtCore import Qt
import e2history

@pytest.fixture
def main_form():
    return e2history.main_loop()

def test_okButton(qtbot,main_form):
    qtbot.waitExposed(main_form.form)
    qtbot.wait(1000)
    qtbot.mouseClick(main_form.form.layout().itemAt(1).itemAt(1).widget(), Qt.LeftButton)
