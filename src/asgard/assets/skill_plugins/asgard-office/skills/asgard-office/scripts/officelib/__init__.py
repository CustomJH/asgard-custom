"""Shared engine for the Asgard Office (Sága) lanes.

Everything here is pure Python. LibreOffice, pandoc, and Word itself are optional
render-time gates, never build-time ones — an Asgard install is one `uv tool install`
and the document lanes have to work from that alone.
"""
