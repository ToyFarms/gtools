import sys

from gtools.gui.touch.impl.null import NullTouchRouter

if sys.platform == "win32":
    from gtools.gui.touch.impl.windows.touch_win import WindowsTouchRouter
    TouchRouter = WindowsTouchRouter
elif sys.platform == "darwin":
    TouchRouter = NullTouchRouter
else:
    TouchRouter = NullTouchRouter
