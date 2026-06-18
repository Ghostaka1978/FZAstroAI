"""Controller mixins for the FZAstro AI main window."""

__all__ = ["AppStateController", "ApplicationState", "ShutdownControllerMixin"]


def __getattr__(name):
    if name in {"AppStateController", "ApplicationState"}:
        from .app_state_controller import AppStateController, ApplicationState

        return {
            "AppStateController": AppStateController,
            "ApplicationState": ApplicationState,
        }[name]

    if name == "ShutdownControllerMixin":
        from .shutdown_controller import ShutdownControllerMixin

        return ShutdownControllerMixin

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
