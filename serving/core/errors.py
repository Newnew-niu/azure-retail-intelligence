"""Errors the API and the MCP server translate into their own responses."""


class ServingError(Exception):
    """Base class; the message is safe to show to the caller."""


class QueryRejected(ServingError):
    """The SQL broke a safety rule and was never sent to the database."""


class QueryFailed(ServingError):
    """The database could not run an allowed query (for example, an unknown column)."""


class QueryTimedOut(ServingError):
    """The query ran longer than the configured timeout and was cancelled."""


class DatasetNotFound(ServingError):
    """The dataset is not in the catalog."""
