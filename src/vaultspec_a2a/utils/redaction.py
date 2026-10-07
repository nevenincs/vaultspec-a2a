"""Secret redaction: the one masking rule for text that may carry a credential.

Every surface that renders text it did not author shares one threat - a log
line, a failed child's account of itself, a settings refusal, a span attribute
can each carry a credential to a reader who must not see it - so they share one
redactor rather than each deciding for itself. Separate copies are how one
surface came to retain a credential verbatim while its neighbour masked it.

Three kinds of credential are recognised wherever they appear:

- the userinfo of a URL, which is where a DSN carries its password;
- a value introduced by a name that says it is a secret (``API_KEY=...``,
  ``"apiKey": "..."``, ``Authorization: Basic ...``) or by a bearer prefix;
- a value whose own shape is a well-known token format (``sk-...``, GitHub
  tokens, JSON Web Tokens), whatever introduces it.

A masked value becomes :data:`REDACTED`; the name that introduced it stays, so
the text still says what was there.
"""

from __future__ import annotations

import re
from typing import Final
from urllib.parse import unquote_plus

__all__ = [
    "REDACTED",
    "is_secret_name",
    "redact_text",
    "redact_url",
]

#: What a masked value is replaced with.
REDACTED: Final = "<redacted>"

#: Words that name a secret wherever they appear inside a name. Matched as
#: substrings, so ``OPENAI_API_KEY``, ``apiKey`` and ``sslpassword`` all count.
_SECRET_NAME_WORDS: Final = (
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "key",
    "passwd",
    "password",
    "secret",
    "token",
)

#: The userinfo of a URL. Runs to the LAST ``@`` before the path, because a
#: password written without percent-encoding may itself contain one.
_URL_USERINFO: Final = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*://)[^/\s]*@")

#: A credential shape that is a secret whoever introduces it.
_SECRET_SHAPE: Final = re.compile(
    r"(?i)\bsk-[a-z0-9_-]{16,}"
    r"|\b(?:ghp|gho|ghs|ghu|github_pat)_[a-z0-9_]{16,}"
    r"|\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"
)

# A value introduced by a secret name and an assignment, or by a bearer prefix.
# The name is anchored at its own first character so a long run of name
# characters is scanned once rather than once per position. An authorization
# scheme word is part of the value, so ``Authorization: Basic Zm9v`` loses the
# credential and not merely the word in front of it.
_NAMED_SECRET: Final = re.compile(
    r"(?i)((?<![A-Z0-9_])[A-Z0-9_]*(?:"
    + "|".join(_SECRET_NAME_WORDS)
    + r")[A-Z0-9_]*[\"']?\s*[=:]\s*|bearer\s+)"
    r"((?:(?:basic|bearer|digest|token)\s+)?(?:\"[^\"]*\"|'[^']*'|\S+))"
)

#: Where a URL's query or fragment begins, and what separates its parameters.
_URL_QUERY_START: Final = re.compile(r"[?#]")
_URL_PARAMETER_DELIMITER: Final = re.compile(r"([?&;#])")


def is_secret_name(name: str) -> bool:
    """Return whether *name* - a key, a field, a parameter - says it holds a secret.

    The test reads the name alone. A caller that also knows the value's type
    decides whether a value that cannot hold text is exempt: a token COUNT is a
    size, and masking it would cost the reader the fact it exists to carry.
    """
    lowered = name.lower()
    return any(word in lowered for word in _SECRET_NAME_WORDS)


def _mask_userinfo(match: re.Match[str]) -> str:
    return f"{match.group('scheme')}{REDACTED}@"


def _mask_named(match: re.Match[str]) -> str:
    value = match.group(2)
    quoted = len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]
    replacement = f"{value[0]}{REDACTED}{value[0]}" if quoted else REDACTED
    return f"{match.group(1)}{replacement}"


def redact_text(text: str) -> str:
    """Mask every credential in free text: URL userinfo, named values, token shapes.

    A named value is matched on the NAME rather than its shape: a token has no
    reliable shape, but the thing introducing it - an assignment to something
    called a token, secret, key, password or credential, an authorization or
    cookie header, or a bearer prefix - does. Known token formats are masked
    wherever they stand, introduced or not.

    JSON is covered as well as ``NAME=value``. A provider that dumps its config
    as JSON writes ``"apiKey": "sk-..."``, where a quote sits between the name
    and its separator, so one is admitted there. A quoted value keeps its
    quotes, so the surrounding structure still reads as JSON after masking.

    Accepts a single line or a whole multi-line block. The separator between a
    name and its value spans newlines deliberately, so a value written on the
    line after its name is masked too; an unquoted value is non-whitespace and
    therefore never runs past its own line, and a quoted one is bounded by its
    closing quote.
    """
    masked = _URL_USERINFO.sub(_mask_userinfo, text)
    masked = _SECRET_SHAPE.sub(REDACTED, masked)
    return _NAMED_SECRET.sub(_mask_named, masked)


def _masked_parameter(parameter: str) -> str:
    """Mask one query or fragment parameter, wholly when its name is a secret."""
    name, equals, _ = parameter.partition("=")
    if equals and is_secret_name(unquote_plus(name)):
        return f"{name}={REDACTED}"
    return redact_text(parameter)


def redact_url(url: str) -> str:
    """Mask every credential one URL carries, keeping the parts that carry none.

    The userinfo is masked whole and the rest of the URL is masked as
    :func:`redact_text` masks text, except that the query and fragment are
    masked one parameter at a time: a parameter whose name says it holds a
    secret loses its value, and every other parameter is masked only where it
    would be as text, so the parameters that carry no secret still read as
    they did.
    """
    masked = _URL_USERINFO.sub(_mask_userinfo, url)
    start = _URL_QUERY_START.search(masked)
    if start is None:
        return redact_text(masked)
    pieces = _URL_PARAMETER_DELIMITER.split(masked[start.start() :])
    return redact_text(masked[: start.start()]) + "".join(
        piece if index % 2 else _masked_parameter(piece)
        for index, piece in enumerate(pieces)
    )
