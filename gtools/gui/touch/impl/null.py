from gtools.gui.touch.base import TouchRouterBase


class NullTouchRouter(TouchRouterBase):
    def install(self) -> None:
        pass

    def uninstall(self) -> None:
        pass
