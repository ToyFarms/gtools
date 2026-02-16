from functools import wraps
from typing import Any
import weakref
import atexit


def auto_call(meth: str):
    def decorator[T](cls: type[T]) -> type[T]:
        original_init = cls.__init__

        if not hasattr(cls, meth):
            raise AttributeError(f"class {cls.__name__} does not have a '{meth}' method")

        called_field = "__meth_called"

        @wraps(original_init)
        def new_init(self, *args: Any, **kwargs: Any) -> None:
            original_init(self, *args, **kwargs)

            setattr(self, called_field, False)
            cleanup_func = getattr(self, meth)

            def safe_cleanup():
                if not getattr(self, called_field, False):
                    setattr(self, called_field, True)
                    cleanup_func()

            self._finalizer = weakref.finalize(self, safe_cleanup)

            atexit.register(safe_cleanup)

        setattr(cls, "__init__", new_init)

        original_meth = getattr(cls, meth)

        @wraps(original_meth)
        def new_meth(self, *args: Any, **kwargs: Any) -> Any:
            setattr(self, called_field, True)
            return original_meth(self, *args, **kwargs)

        setattr(cls, meth, new_meth)

        return cls

    return decorator
