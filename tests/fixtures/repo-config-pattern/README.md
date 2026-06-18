# config-pattern

A tiny demo project for the chatbot-sandbox repo-pattern case.

`config.py` defines a typed `Config` dataclass with a `from_dict` classmethod.
Every field follows the same pattern: a module-level `DEFAULT_*` constant, a
dataclass field defaulting to it, and a `from_dict` line that reads the key
with that constant as the fallback. The task is to add a new field the same
way — not to introduce a new abstraction.