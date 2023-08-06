import importlib.util
import os
import sys
from typing import Any, Awaitable, Callable

import orjson
from core import JSONDict, JSONList, SwayIPCConnection

TaskFunc = Callable[[SwayIPCConnection], Awaitable[None]]
SubscriptionFunc = Callable[[SwayIPCConnection, JSONDict | JSONList], Awaitable[None]]
Subscriptions = dict[str, dict[str, SubscriptionFunc]]
Tasks = list[TaskFunc]

settings_file = "settings.json"
plugin_dir = "plugins"


def copy_file(src_file: str, dest_file: str) -> None:
    with open(src_file, "rb") as src, open(dest_file, "wb") as dest:
        dest.write(src.read())


def load_function(path: str, fname: str) -> Callable[..., Any]:
    try:
        sys.path.append(os.path.dirname(path))
        spec = importlib.util.spec_from_file_location("module.name", path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return getattr(module, fname)
        raise ImportError(f"Failed to load {fname} from {path}")
    finally:
        sys.path.pop()


def locate_func(directory: str, key: str) -> tuple[str, str]:
    path, funcname = key.split(":")
    path = os.path.join(directory, path) if not os.path.isabs(path) else path
    path += ".py" if not path.endswith(".py") else ""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File {path} does not exist")
    return path, funcname


def setup_environment() -> str:
    """Sets up the necessary directories and returns the path to the settings file."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "")
    if not xdg_config:
        raise EnvironmentError("XDG_CONFIG_HOME is not set, exiting")

    dirs: dict[str, str] = {
        name: os.path.join(xdg_config, "swayipc", name) for name in ["", plugin_dir]
    }
    for dir in dirs.values():
        os.makedirs(dir, exist_ok=True)

    s_file = os.path.join(dirs[""], settings_file)
    if not os.path.exists(s_file):
        copy_file(os.path.join(os.path.dirname(__file__), settings_file), s_file)
    return s_file


def load_plugins_from_settings(s_file: str) -> tuple[Subscriptions, Tasks]:
    with open(s_file, "rb") as f:
        settings: dict[str, Any] = orjson.loads(f.read())

    plugins = os.path.join(os.path.dirname(s_file), plugin_dir)
    funcs: set[str] = set(
        value
        for subdict in settings["subscriptions"].values()
        for value in subdict.values()
        if value
    )
    funcs.update(settings["tasks"])

    f_dict: dict[str, TaskFunc | SubscriptionFunc] = {
        func: load_function(*locate_func(plugins, func)) for func in funcs
    }

    tasks: Tasks = [f_dict[task] for task in settings["tasks"]]  # pyright: ignore
    subs: Subscriptions = {
        event: {change: f_dict.get(func) for change, func in changes.items()}
        for event, changes in settings["subscriptions"].items()
        if any(changes.values())
    }  # pyright: ignore

    return subs, tasks


def initialize_and_load() -> tuple[Subscriptions, Tasks]:
    s_file = setup_environment()
    return load_plugins_from_settings(s_file)
