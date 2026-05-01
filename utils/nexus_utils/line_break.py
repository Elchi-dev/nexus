"""
nexus_utils.line_break
~~~~~~~~~~~~~~~~~~~~~~

a utility function to print newlines.
300 lines long. no, we don't apologise.
yes, it has an observer pattern. yes, there are three emitter strategies.

if you're wondering why this exists: see the project README.
if you're wondering how this happened: hubris.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import time
import traceback
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import wraps
from typing import (
    ClassVar,
    Final,
    Literal,
    Protocol,
    Self,
    overload,
    runtime_checkable,
)

# ─────────────────────────────────────────────
#  Types & constants
# ─────────────────────────────────────────────

type BreakChar = str
type OutputTarget = Literal["stdout", "stderr"]

_DEFAULT_CHAR:  Final[str] = "\n"
_DEFAULT_TIMES: Final[int] = 1
_MAX_BREAKS:    Final[int] = 1_000


# ─────────────────────────────────────────────
#  Enums
# ─────────────────────────────────────────────

class BreakStyle(Enum):
    """How should line breaks be emitted?"""

    STANDARD  = auto()   # \n
    DOUBLE    = auto()   # \n\n per break
    SEPARATOR = auto()   # custom separator char/string
    CRLF      = auto()   # windows-style \r\n
    NULL      = auto()   # \x00 for binary log protocols

    def resolve_char(self, custom: str | None = None) -> str:
        match self:
            case BreakStyle.STANDARD:
                return "\n"
            case BreakStyle.DOUBLE:
                return "\n\n"
            case BreakStyle.CRLF:
                return "\r\n"
            case BreakStyle.NULL:
                return "\x00"
            case BreakStyle.SEPARATOR:
                return custom or ("─" * 40 + "\n")
            case _:
                return "\n"


class OverflowPolicy(Enum):
    """What happens when times > max_breaks?"""

    RAISE = auto()   # raise BreakOverflowError
    CLAMP = auto()   # silently clamp to max_breaks
    WARN  = auto()   # emit a warning, then clamp


# ─────────────────────────────────────────────
#  Exceptions
# ─────────────────────────────────────────────

class LineBreakError(Exception):
    """Base exception for all line-break-related horrors."""


class BreakOverflowError(LineBreakError):
    """Raised when times exceeds the configured ceiling."""

    def __init__(self, requested: int, maximum: int) -> None:
        super().__init__(
            f"Requested {requested} line breaks, but the maximum is {maximum}. "
            f"Raise LineBreakConfig.max_breaks or switch to OverflowPolicy.CLAMP."
        )
        self.requested = requested
        self.maximum   = maximum


class InvalidBreakTargetError(LineBreakError):
    """Raised when the output target does not implement Writeable."""


# ─────────────────────────────────────────────
#  Protocols
# ─────────────────────────────────────────────

@runtime_checkable
class Writeable(Protocol):
    """Anything with a write() — stdout, file, StringIO, custom sink."""

    def write(self, s: str, /) -> int: ...
    def flush(self) -> None: ...


# ─────────────────────────────────────────────
#  Event dataclass — defined BEFORE LineBreakObserver
# ─────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class LineBreakEvent:
    """Immutable record emitted to observers on every line-break call."""

    times:      int
    char:       str
    style:      BreakStyle
    timestamp:  float = field(default_factory=time.monotonic)
    thread_id:  int   = field(default_factory=threading.get_ident)
    call_depth: int   = 0

    @property
    def total_bytes(self) -> int:
        """Total bytes that will be written."""
        return len(self.char.encode()) * self.times


# ─────────────────────────────────────────────
#  Observer protocol — after LineBreakEvent
# ─────────────────────────────────────────────

@runtime_checkable
class LineBreakObserver(Protocol):
    """Implement this to hook into every line-break event."""

    def on_break(self, event: LineBreakEvent) -> None: ...


# ─────────────────────────────────────────────
#  Config singleton
# ─────────────────────────────────────────────

@dataclass
class LineBreakConfig:
    """
    Global, mutable configuration for the entire line-break subsystem.
    Override once at startup; don't mutate mid-flight.

    Usage::

        cfg = LineBreakConfig.get()
        cfg.default_style   = BreakStyle.CRLF
        cfg.overflow_policy = OverflowPolicy.CLAMP
        cfg.register_observer(MyLogger())
    """

    _instance: ClassVar[LineBreakConfig | None] = None

    max_breaks:      int                     = _MAX_BREAKS
    default_style:   BreakStyle              = BreakStyle.STANDARD
    overflow_policy: OverflowPolicy          = OverflowPolicy.RAISE
    dry_run:         bool                    = False
    observers:       list[LineBreakObserver] = field(default_factory=list)

    @classmethod
    def get(cls) -> Self:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance  # type: ignore[return-value]

    @classmethod
    def reset(cls) -> None:
        """Reset to defaults — useful in tests."""
        cls._instance = None

    def register_observer(self, obs: LineBreakObserver) -> None:
        self.observers.append(obs)

    def _notify(self, event: LineBreakEvent) -> None:
        for obs in self.observers:
            obs.on_break(event)


# ─────────────────────────────────────────────
#  Emitter strategies
# ─────────────────────────────────────────────

class BaseLineBreakEmitter(ABC):
    """Strategy base — swap emission logic without touching calling code."""

    @abstractmethod
    def emit(self, times: int, char: str, target: Writeable) -> int:
        """Write `times` repetitions of `char` to `target`. Return bytes written."""
        ...


class BurstEmitter(BaseLineBreakEmitter):
    """Writes all breaks in a single write() call. Fastest."""

    def emit(self, times: int, char: str, target: Writeable) -> int:
        return target.write(char * times)


class SequentialEmitter(BaseLineBreakEmitter):
    """Writes one break at a time. Useful when observers need per-break resolution."""

    def emit(self, times: int, char: str, target: Writeable) -> int:
        written = 0
        for _ in range(times):
            written += target.write(char)
        return written


class ThrottledEmitter(BaseLineBreakEmitter):
    """
    Writes breaks with a configurable delay between each one.

    completely pointless in production.
    perfect for impressing non-technical stakeholders.
    """

    def __init__(self, delay_ms: float = 50.0) -> None:
        self.delay_s = delay_ms / 1000

    def emit(self, times: int, char: str, target: Writeable) -> int:
        written = 0
        for _ in range(times):
            written += target.write(char)
            target.flush()
            time.sleep(self.delay_s)
        return written


# ─────────────────────────────────────────────
#  Validation decorator
# ─────────────────────────────────────────────

def validate_break_args[T](fn: Callable[..., T]) -> Callable[..., T]:
    """Validates `times` type and value before the function body runs."""

    @wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> T:
        times = args[0] if args else kwargs.get("times", _DEFAULT_TIMES)
        if not isinstance(times, int) or isinstance(times, bool):
            raise TypeError(
                f"'times' must be int, got {type(times).__name__!r}: {times!r}"
            )
        if times < 0:
            raise ValueError(f"'times' must be >= 0, got {times}")
        return fn(*args, **kwargs)

    return wrapper


# ─────────────────────────────────────────────
#  Context manager
# ─────────────────────────────────────────────

@contextlib.contextmanager
def break_section(
    before: int = 1,
    after:  int = 1,
    style:  BreakStyle = BreakStyle.STANDARD,
) -> Generator[None, None, None]:
    """
    Context manager that pads a block of output with line breaks.

    Usage::

        with break_section(before=2, after=1):
            print("surrounded by breathing room")
    """
    line_break(before, style=style)
    try:
        yield
    finally:
        line_break(after, style=style)


# ─────────────────────────────────────────────
#  Core function
# ─────────────────────────────────────────────

@overload
def line_break(times: int = ..., *, style: BreakStyle = ...) -> int: ...
@overload
def line_break(times: int = ..., *, char: str = ..., target: Writeable = ...) -> int: ...


@validate_break_args
def line_break(
    times:   int                         = _DEFAULT_TIMES,
    *,
    char:    str | None                  = None,
    style:   BreakStyle | None           = None,
    target:  Writeable | None            = None,
    emitter: BaseLineBreakEmitter | None = None,
    config:  LineBreakConfig | None      = None,
) -> int:
    """
    Emit ``times`` line breaks to ``target``.

    Args:
        times:    Number of breaks to emit. Must be a non-negative int.
        char:     Override the break character (takes precedence over ``style``).
        style:    :class:`BreakStyle` controlling the break format.
        target:   Any :class:`Writeable` (default: ``sys.stdout``).
        emitter:  Swap the write strategy (:class:`BurstEmitter` by default).
        config:   Override the global config for this single call.

    Returns:
        Number of bytes written (0 in dry-run mode).

    Raises:
        TypeError:               If ``times`` is not an int.
        ValueError:              If ``times`` is negative.
        BreakOverflowError:      If ``times`` > ``config.max_breaks`` and policy is RAISE.
        InvalidBreakTargetError: If ``target`` does not implement :class:`Writeable`.

    Examples::

        line_break(3)
        line_break(2, style=BreakStyle.SEPARATOR)
        line_break(1, target=sys.stderr)
        line_break(5, emitter=ThrottledEmitter(delay_ms=100))
    """
    cfg = config or LineBreakConfig.get()

    resolved_target: Writeable = target or sys.stdout
    if not isinstance(resolved_target, Writeable):
        raise InvalidBreakTargetError(
            f"target must implement Writeable, got {type(resolved_target)!r}"
        )

    resolved_style = style or cfg.default_style
    resolved_char  = char if char is not None else resolved_style.resolve_char()

    if times > cfg.max_breaks:
        match cfg.overflow_policy:
            case OverflowPolicy.RAISE:
                raise BreakOverflowError(times, cfg.max_breaks)
            case OverflowPolicy.WARN:
                import warnings
                warnings.warn(
                    f"Clamping {times} → {cfg.max_breaks} (OverflowPolicy.WARN)",
                    stacklevel=2,
                )
                times = cfg.max_breaks
            case OverflowPolicy.CLAMP:
                times = cfg.max_breaks

    if times == 0:
        return 0

    event = LineBreakEvent(
        times=times,
        char=resolved_char,
        style=resolved_style,
        call_depth=len(traceback.extract_stack()) - 1,
    )
    cfg._notify(event)

    if cfg.dry_run:
        return event.total_bytes

    resolved_emitter = emitter or BurstEmitter()
    return resolved_emitter.emit(times, resolved_char, resolved_target)