import sys

from gtools.gui.touch.impl.null import NullTouchRouter
from gtools.gui.touch.impl.windows.touch_win import WindowsTouchRouter

if sys.platform == "win32":
    TouchRouter = WindowsTouchRouter
elif sys.platform == "darwin":
    TouchRouter = NullTouchRouter
else:
    TouchRouter = NullTouchRouter
