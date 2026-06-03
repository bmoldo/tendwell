"""Typed errors shared by data-source adapters.

Adapters raise these so the agent's snapshot builder can degrade the affected
SLO to ``unknown`` rather than crashing the run. They are deliberately small and
backend-agnostic.
"""

from __future__ import annotations


class DataSourceError(Exception):
    """Base class for data-source failures."""


class SourceUnreachable(DataSourceError):
    """The backend could not be reached (network, DNS, timeout)."""


class SourceAuthError(DataSourceError):
    """The backend rejected the credentials."""


class QueryError(DataSourceError):
    """The backend rejected the query or returned an error payload."""
