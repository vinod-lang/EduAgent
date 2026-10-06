"""Lightweight module injection; defaults resolve at use, never at import."""
from importlib import import_module

def dependency(injected, name):
    return injected if injected is not None else import_module(name)
