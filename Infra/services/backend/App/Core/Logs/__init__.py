"""Logs package."""

from .Logs import (
    LogLevel,
    LogStatus,
    Logger,
    set_request_id,
    get_request_id,
    set_session_id,
    get_session_id,
    get_logger,
    debug,
    info,
    warning,
    error,
    critical,
    audit,
    http,
    log_by_level,
    get_log_file_path,
)

__all__ = [
    # Logs
    "LogLevel",
    "LogStatus",
    "Logger",
    "set_request_id",
    "get_request_id",
    "set_session_id",
    "get_session_id",
    "get_logger",
    "debug",
    "info",
    "warning",
    "error",
    "critical",
    "audit",
    "http",
    "log_by_level",
    "get_log_file_path",
]
