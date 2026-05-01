"""
nexus_utils.logging
~~~~~~~~~~~~~~~~~~~

a structured logger for nexus.
because print() wasn't overengineered enough.

features:
- structured fields — log.info("msg", key=value) everywhere
- pluggable formatters: PrettyFormatter (dev) and JSONFormatter (prod)
- pluggable sinks: ConsoleSink, FileSink, AsyncQueueSink, NullSink
- context binding — logger.bind(guild_id=123) returns a child logger
- scoped context manager — with log.context(request_id=...) as l: ...
- @logged decorator for automatic function call tracing
- LoggingLineBreakObserver — because of course line_break() is logged
- NO_COLOR / FORCE_COLOR env var support
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback as tb_module
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from functools import wraps
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, Self, TextIO, runtime_checkable

if TYPE_CHECKING:
    from nexus_utils.line_break import LineBreakEvent


# ─────────────────────────────────────────────
#  ANSI color codes — no dependencies
# ─────────────────────────────────────────────

_RESET          = "\033[0m"
_BOLD           = "\033[1m"
_DIM            = "\033[2m"
_BRIGHT_RED     = "\033[91m"
_BRIGHT_GREEN   = "\033[92m"
_BRIGHT_YELLOW  = "\033[93m"
_BRIGHT_CYAN    = "\033[96m"
_WHITE          = "\033[37m"


def _supports_color(stream: TextIO) -> bool:
    """Detect ANSI color support. Respects NO_COLOR and FORCE_COLOR."""
    if os.getenv("NO_COLOR"):
        return False
    if os.getenv("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


# ─────────────────────────────────────────────
#  Log level
# ─────────────────────────────────────────────

class LogLevel(IntEnum):
    """Severity levels, ordered. IntEnum so > and < work naturally."""

    DEBUG    = 10
    INFO     = 20
    WARN     = 30
    ERROR    = 40
    CRITICAL = 50

    @property
    def label(self) -> str:
        """Right-padded name for aligned output."""
        return self.name.ljust(8)

    @property
    def color(self) -> str:
        match self:
            case LogLevel.DEBUG:
                return _DIM + _WHITE
            case LogLevel.INFO:
                return _BRIGHT_GREEN
            case LogLevel.WARN:
                return _BRIGHT_YELLOW
            case LogLevel.ERROR:
                return _BRIGHT_RED
            case LogLevel.CRITICAL:
                return _BOLD + _BRIGHT_RED
            case _:
                return _RESET


# ─────────────────────────────────────────────
#  Log record — immutable event snapshot
# ─────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class LogRecord:
    """Everything about a single log event. Passed to formatters and sinks."""

    level:       LogLevel
    message:     str
    logger_name: str
    timestamp:   float          = field(default_factory=time.monotonic)
    wall_time:   float          = field(default_factory=time.time)
    thread_id:   int            = field(default_factory=threading.get_ident)
    fields:      dict[str, Any] = field(default_factory=dict)
    exc_text:    str | None     = None

    @property
    def iso_time(self) -> str:
        return datetime.fromtimestamp(self.wall_time).strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────
#  Protocols
# ─────────────────────────────────────────────

@runtime_checkable
class LogFormatter(Protocol):
    """Turns a LogRecord into a string."""

    def format(self, record: LogRecord) -> str: ...


@runtime_checkable
class LogSink(Protocol):
    """Receives and stores/transmits formatted log output."""

    def emit(self, record: LogRecord, formatted: str) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class LogFilter(Protocol):
    """Decides whether a record should be emitted."""

    def should_log(self, record: LogRecord) -> bool: ...


# ─────────────────────────────────────────────
#  Formatters
# ─────────────────────────────────────────────

@dataclass
class PrettyFormatter:
    """
    Human-readable, optionally colored output for development.

    Example output::

        2025-01-01 12:00:00 INFO     [discord] bot ready  guild_count=42
    """

    color: bool = True

    def format(self, record: LogRecord) -> str:
        use_color = self.color and _supports_color(sys.stdout)

        name       = f"[{record.logger_name}]" if record.logger_name else ""
        fields_str = "  ".join(
            f"{_DIM}{k}{_RESET}={v}" if use_color else f"{k}={v}"
            for k, v in record.fields.items()
        )

        if use_color:
            parts = [
                f"{_DIM}{record.iso_time}{_RESET}",
                f"{record.level.color}{record.level.label}{_RESET}",
                f"{_BRIGHT_CYAN}{name}{_RESET}" if name else "",
                record.message,
                f"  {fields_str}" if fields_str else "",
            ]
        else:
            parts = [
                record.iso_time,
                record.level.label,
                name,
                record.message,
                f"  {fields_str}" if fields_str else "",
            ]

        line = " ".join(p for p in parts if p)

        if record.exc_text:
            dim = _DIM if use_color else ""
            rst = _RESET if use_color else ""
            line += f"\n{dim}{record.exc_text}{rst}"

        return line


@dataclass
class JSONFormatter:
    """
    Structured JSON output for production and log aggregators.
    One JSON object per line — friendly to Loki, Datadog, CloudWatch, etc.
    """

    indent: int | None = None

    def format(self, record: LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts":      record.iso_time,
            "level":   record.level.name,
            "logger":  record.logger_name,
            "message": record.message,
            **record.fields,
        }
        if record.exc_text:
            payload["exception"] = record.exc_text
        return json.dumps(payload, default=str, indent=self.indent)


# ─────────────────────────────────────────────
#  Sinks
# ─────────────────────────────────────────────

@dataclass
class ConsoleSink:
    """
    Writes to stdout (DEBUG/INFO) or stderr (WARN+).
    Thread-safe via a lock.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def emit(self, record: LogRecord, formatted: str) -> None:
        stream = sys.stderr if record.level >= LogLevel.WARN else sys.stdout
        with self._lock:
            print(formatted, file=stream)

    def flush(self) -> None:
        sys.stdout.flush()
        sys.stderr.flush()

    def close(self) -> None:
        pass


@dataclass
class FileSink:
    """Appends log records to a file. Thread-safe."""

    path:  str
    _file: TextIO          = field(init=False, repr=False)
    _lock: threading.Lock  = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self._file = open(self.path, "a", encoding="utf-8")  # noqa: SIM115

    def emit(self, record: LogRecord, formatted: str) -> None:
        with self._lock:
            self._file.write(formatted + "\n")

    def flush(self) -> None:
        self._file.flush()

    def close(self) -> None:
        self._file.close()


class NullSink:
    """Swallows everything. For testing."""

    def emit(self, record: LogRecord, formatted: str) -> None:
        pass

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


class AsyncQueueSink:
    """
    Buffers records in an asyncio queue and emits them asynchronously.
    Wraps any sync LogSink. For production workloads where I/O latency matters.
    Records are dropped under pressure (queue full) — this is intentional.
    """

    def __init__(self, inner: LogSink, max_queue: int = 10_000) -> None:
        self._inner = inner
        self._queue: asyncio.Queue[tuple[LogRecord, str] | None] = asyncio.Queue(max_queue)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background worker. Call this in your async startup."""
        self._task = asyncio.create_task(self._worker())

    async def _worker(self) -> None:
        while True:
            item = await self._queue.get()
            if item is None:
                break
            record, formatted = item
            self._inner.emit(record, formatted)

    def emit(self, record: LogRecord, formatted: str) -> None:
        try:
            self._queue.put_nowait((record, formatted))
        except asyncio.QueueFull:
            pass

    def flush(self) -> None:
        self._inner.flush()

    def close(self) -> None:
        try:
            self._queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        self._inner.close()


# ─────────────────────────────────────────────
#  Filters
# ─────────────────────────────────────────────

@dataclass
class LevelFilter:
    """Only passes records at or above the given level."""

    min_level: LogLevel

    def should_log(self, record: LogRecord) -> bool:
        return record.level >= self.min_level


@dataclass
class NameFilter:
    """Only passes records from loggers whose name starts with prefix."""

    prefix: str

    def should_log(self, record: LogRecord) -> bool:
        return record.logger_name.startswith(self.prefix)


# ─────────────────────────────────────────────
#  Config singleton
# ─────────────────────────────────────────────

@dataclass
class LoggerConfig:
    """
    Global logger configuration singleton. Set once at startup.

    Usage::

        cfg = LoggerConfig.get()
        cfg.level     = LogLevel.DEBUG
        cfg.formatter = JSONFormatter()
        cfg.sinks     = [ConsoleSink(), FileSink("nexus.log")]
    """

    _instance: ClassVar[LoggerConfig | None] = None

    level:     LogLevel        = LogLevel.INFO
    formatter: LogFormatter    = field(default_factory=PrettyFormatter)
    sinks:     list[LogSink]   = field(default_factory=lambda: [ConsoleSink()])
    filters:   list[LogFilter] = field(default_factory=list)

    @classmethod
    def get(cls) -> Self:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance  # type: ignore[return-value]

    @classmethod
    def reset(cls) -> None:
        """Reset to defaults — useful in tests."""
        cls._instance = None

    def add_sink(self, sink: LogSink) -> None:
        self.sinks.append(sink)

    def add_filter(self, f: LogFilter) -> None:
        self.filters.append(f)


# ─────────────────────────────────────────────
#  Logger
# ─────────────────────────────────────────────

class Logger:
    """
    A structured, bindable logger.

    Usage::

        log = get_logger("discord")
        log.info("bot ready", guild_count=42)

        # bind returns a child logger with pre-attached context
        cmd_log = log.bind(guild_id=12345, channel="general")
        cmd_log.info("command received", command="!play")

        # scoped context manager
        with log.context(request_id="abc123") as l:
            l.debug("processing")
    """

    __slots__ = ("_name", "_bound_fields", "_config")

    def __init__(
        self,
        name:   str,
        config: LoggerConfig | None = None,
        fields: dict[str, Any] | None = None,
    ) -> None:
        self._name         = name
        self._config       = config or LoggerConfig.get()
        self._bound_fields = fields or {}

    def bind(self, **fields: Any) -> Logger:
        """Return a child logger with additional pre-bound context fields."""
        return Logger(
            name=self._name,
            config=self._config,
            fields={**self._bound_fields, **fields},
        )

    def _emit(
        self,
        level:   LogLevel,
        message: str,
        exc:     BaseException | None = None,
        **fields: Any,
    ) -> None:
        cfg = self._config

        if level < cfg.level:
            return

        exc_text = (
            "".join(
                tb_module.format_exception(type(exc), exc, exc.__traceback__)
            ).rstrip()
            if exc
            else None
        )

        record = LogRecord(
            level=level,
            message=message,
            logger_name=self._name,
            fields={**self._bound_fields, **fields},
            exc_text=exc_text,
        )

        for f in cfg.filters:
            if not f.should_log(record):
                return

        formatted = cfg.formatter.format(record)

        for sink in cfg.sinks:
            sink.emit(record, formatted)

    def debug(self, message: str, **fields: Any) -> None:
        self._emit(LogLevel.DEBUG, message, **fields)

    def info(self, message: str, **fields: Any) -> None:
        self._emit(LogLevel.INFO, message, **fields)

    def warn(self, message: str, **fields: Any) -> None:
        self._emit(LogLevel.WARN, message, **fields)

    def error(self, message: str, exc: BaseException | None = None, **fields: Any) -> None:
        self._emit(LogLevel.ERROR, message, exc=exc, **fields)

    def critical(self, message: str, exc: BaseException | None = None, **fields: Any) -> None:
        self._emit(LogLevel.CRITICAL, message, exc=exc, **fields)

    @contextmanager
    def context(self, **fields: Any) -> Generator[Logger, None, None]:
        """Scoped context — bound fields only live for the duration of the block."""
        yield self.bind(**fields)

    def __repr__(self) -> str:
        return f"Logger(name={self._name!r}, level={self._config.level.name})"


# ─────────────────────────────────────────────
#  @logged decorator
# ─────────────────────────────────────────────

def logged[T](
    logger: Logger | None = None,
    level: LogLevel = LogLevel.DEBUG,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """
    Decorator that logs function entry, exit, and exceptions.

    Usage::

        @logged(log, level=LogLevel.INFO)
        def process_event(event: str) -> None:
            ...
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        log = logger or get_logger(fn.__module__)

        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            log._emit(level, f"→ {fn.__qualname__}")
            try:
                result = fn(*args, **kwargs)
                log._emit(level, f"← {fn.__qualname__}")
                return result
            except Exception as exc:
                log.error(f"✗ {fn.__qualname__} raised {type(exc).__name__}", exc=exc)
                raise

        return wrapper

    return decorator


# ─────────────────────────────────────────────
#  LineBreakObserver bridge
# ─────────────────────────────────────────────

class LoggingLineBreakObserver:
    """
    Bridges line_break() events into structured log records.

    register with LineBreakConfig to audit every newline in the application.
    completely unnecessary. obviously implemented.

    Usage::

        from nexus_utils.line_break import LineBreakConfig
        LineBreakConfig.get().register_observer(
            LoggingLineBreakObserver(get_logger("nexus.utils.line_break"))
        )
    """

    def __init__(self, logger: Logger) -> None:
        self._log = logger.bind(subsystem="line_break")

    def on_break(self, event: LineBreakEvent) -> None:
        self._log.debug(
            "line break emitted",
            times=event.times,
            style=event.style.name,
            total_bytes=event.total_bytes,
            thread_id=event.thread_id,
            call_depth=event.call_depth,
        )


# ─────────────────────────────────────────────
#  Factory & convenience
# ─────────────────────────────────────────────

_registry: dict[str, Logger] = {}
_registry_lock = threading.Lock()


def get_logger(name: str, config: LoggerConfig | None = None) -> Logger:
    """
    Get or create a named logger. Loggers are cached by name.

    Usage::

        log = get_logger("nexus.discord")
        log.info("connected", guild_count=5)
    """
    with _registry_lock:
        if name not in _registry:
            _registry[name] = Logger(name=name, config=config)
        return _registry[name]


def configure(
    *,
    level:     LogLevel | None     = None,
    formatter: LogFormatter | None = None,
    sinks:     list[LogSink] | None = None,
) -> None:
    """
    Configure the global logger at startup.

    Usage::

        configure(
            level=LogLevel.DEBUG,
            formatter=JSONFormatter(),
            sinks=[ConsoleSink(), FileSink("nexus.log")],
        )
    """
    cfg = LoggerConfig.get()
    if level is not None:
        cfg.level = level
    if formatter is not None:
        cfg.formatter = formatter
    if sinks is not None:
        cfg.sinks = sinks