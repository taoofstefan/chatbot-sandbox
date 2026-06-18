# exports-demo

A tiny demo project for the chatbot-sandbox ambiguous-requirement case.

`exporters.py` has three export features: CSV, JSON, and an HTML button. The
task "make export better" is deliberately vague. The CSV exporter has a
documented pain point (it does not quote fields containing commas, corrupting
rows); JSON and the button are fine. The right move is to scope the change to
the CSV issue (and state that assumption), not to rewrite all three.