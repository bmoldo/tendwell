"""Tendwell: a self-hostable, local-first AgentOps tool.

It observes live production signal and operational knowledge, reasons over them
with a local LLM, and reports on the health of production. By default no data
leaves the host.

This package is organized around four stable interfaces (see
``tendwell.interfaces``); concrete adapters implement them and the core agent
loop depends only on the contracts.
"""

__version__ = "0.0.1"
