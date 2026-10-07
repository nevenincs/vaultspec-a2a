"""Canonical identity and kind rules for ACP permission options (Layer 1 leaf).

An ACP ``PermissionOption`` reaches this process through several transports —
the provider's ``session/request_permission`` RPC params, a LangGraph interrupt
resume payload, an SSE frame, and a durable ``allowed_options_json`` column — and
those transports do not agree on the spelling of the identity field. The ACP wire
schema uses camelCase ``optionId``; our own snake_case surfaces (the versioned
API edge and the dashboard) use ``option_id``. Both spellings are accepted, and
``optionId`` wins when a single dict somehow carries both.

The same option must also MEAN the same thing on every surface: whether choosing
it lets the call proceed, refuses it, or asks the agent to remember the answer
for later calls. Those meanings are read here and nowhere else, so the provider
rung, the stream projection, the run-status projection, and the durable verdict
cannot classify one option two ways.

This module is the one place those rules live. Its only package import is the
sibling Layer 1 leaf :mod:`vaultspec_a2a.graph.enums`, which owns the ACP option
*vocabulary* (``PermissionOptionKind``) and imports nothing from the package, so
every layer that speaks ACP — ``providers``, ``graph.nodes``, ``streaming``,
``control`` — depends on it downward with no new package edge. The vocabulary
stays in ``enums`` because an enum is not a dict-shape predicate.

Every helper is total over untrusted input: an option that is not a dict, or
whose id is missing, non-string, or empty, simply has no id. Callers therefore
never see ``None`` leak into a set of "valid" ids, and never need a bare
``option["optionId"]`` subscript that could raise ``KeyError`` on a malformed
payload from a subprocess.
"""

from typing import cast

from .enums import PermissionOptionKind

__all__ = [
    "OPTION_ID_KEYS",
    "is_approval",
    "is_rejection",
    "is_remembering",
    "narrowest_option_id",
    "offered_option",
    "option_id_of",
    "option_id_of_kind",
    "option_kind",
    "valid_option_ids",
]

# Accepted spellings of the option identity field, in precedence order.
OPTION_ID_KEYS: tuple[str, ...] = ("optionId", "option_id")

_DECLARED_KINDS: dict[str, PermissionOptionKind] = {
    kind.value: kind for kind in PermissionOptionKind
}
_APPROVING_KINDS = frozenset(
    {PermissionOptionKind.ALLOW_ONCE, PermissionOptionKind.ALLOW_ALWAYS}
)
_REJECTING_KINDS = frozenset(
    {PermissionOptionKind.REJECT_ONCE, PermissionOptionKind.REJECT_ALWAYS}
)
_REMEMBERING_KINDS = frozenset(
    {PermissionOptionKind.ALLOW_ALWAYS, PermissionOptionKind.REJECT_ALWAYS}
)


def option_id_of(option: object) -> str | None:
    """Return the id of one ACP permission option, or None if it has none.

    ``None`` means "this option carries no usable identity" — a non-dict entry,
    a missing key under either spelling, or a value that is not a non-empty
    string. Callers that need a concrete id substitute their own fallback.
    """
    if not isinstance(option, dict):
        return None
    option_dict = cast("dict[str, object]", option)
    for key in OPTION_ID_KEYS:
        value = option_dict.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def valid_option_ids(options: object) -> set[str]:
    """Return every usable option id offered by a parsed ACP option list.

    Accepts both spellings on every entry, so a list mixing camelCase and
    snake_case options validates as one set. An entry carrying both spellings
    contributes both ids, keeping a client that echoes the other spelling
    valid. A non-list, or a list of malformed entries, yields an empty set —
    which callers read as "nothing to validate against", never as a set
    containing ``None``.
    """
    if not isinstance(options, list):
        return set()
    option_ids: set[str] = set()
    for option in cast("list[object]", options):
        if not isinstance(option, dict):
            continue
        option_dict = cast("dict[str, object]", option)
        for key in OPTION_ID_KEYS:
            value = option_dict.get(key)
            if isinstance(value, str) and value:
                option_ids.add(value)
    return option_ids


def offered_option(options: object, option_id: str) -> dict[str, object] | None:
    """Return the offered option that *option_id* names, or None if none does."""
    if not isinstance(options, list):
        return None
    for option in cast("list[object]", options):
        if option_id_of(option) == option_id:
            return cast("dict[str, object]", option)
    return None


def _map_acp_option_kind(option_id: str) -> PermissionOptionKind:
    # PRIVATE on purpose. This id-substring heuristic is the LAST RESORT of
    # `option_kind`, not a peer it can be chosen instead of. It was public once,
    # and a second consumer picked it over the declared kind and classified a
    # declared denial as an approval. Reaching it now means going through
    # `option_kind`, which is the only caller that knows when the declaration is
    # unusable.
    """Derive a ``PermissionOptionKind`` from an ACP option id's spelling.

    Looks for ``always`` and ``deny``/``reject`` keywords. Defaults to
    ``ALLOW_ONCE`` for an id carrying neither.

    The default is deliberately permissive and must stay that way: the keywords
    only detect *rejecting* and *remembering* spellings, so every approving id
    this system mints -- ``"approve"``, ``"allow"``, ``"allow_once"`` -- carries
    no rejecting keyword and reaches the default. Failing closed here would
    classify every one of them as a denial.
    """
    oid = option_id.lower()
    rejecting = "deny" in oid or "reject" in oid
    if "always" in oid:
        return (
            PermissionOptionKind.REJECT_ALWAYS
            if rejecting
            else PermissionOptionKind.ALLOW_ALWAYS
        )
    return (
        PermissionOptionKind.REJECT_ONCE
        if rejecting
        else PermissionOptionKind.ALLOW_ONCE
    )


def option_kind(option: object) -> PermissionOptionKind:
    """Return what choosing one ACP option means, preferring its declared kind.

    The ACP schema has the agent declare each option's ``kind`` alongside its id,
    and that declaration is the only authority on what the option does. An id is
    free-form and provider-defined, so deriving the kind from it discards the one
    field that carries the answer: an agent offering a rejecting option under an
    id spelling neither ``deny`` nor ``reject`` -- and nothing obliges it to use
    either -- would read as an approval, and the pinned Claude adapter's
    rule-writing approval is ``allow-with-updates``, an id that says nothing
    about remembering.

    The declaration is validated rather than trusted: a value outside
    :class:`PermissionOptionKind` (absent, empty, non-string, or unknown) falls
    back to the id's spelling, so a malformed kind degrades to the best reading
    available instead of reaching a durable column as an unreadable status.
    """
    if isinstance(option, dict):
        declared = cast("dict[str, object]", option).get("kind")
        if isinstance(declared, str) and declared in _DECLARED_KINDS:
            return _DECLARED_KINDS[declared]
    return _map_acp_option_kind(option_id_of(option) or "")


def is_approval(option: object) -> bool:
    """Whether choosing *option* lets the tool call proceed."""
    return option_kind(option) in _APPROVING_KINDS


def is_rejection(option: object) -> bool:
    """Whether choosing *option* refuses the tool call."""
    return option_kind(option) in _REJECTING_KINDS


def is_remembering(option: object) -> bool:
    """Whether choosing *option* asks the agent to remember the answer.

    Both polarities remember: the agent persists a remembered refusal as a rule
    exactly as it persists a remembered approval, and either one outlives the
    call it answered.
    """
    return option_kind(option) in _REMEMBERING_KINDS


def option_id_of_kind(options: object, kind: PermissionOptionKind) -> str | None:
    """Return the id of the first offered option of *kind*, or None if none is."""
    if not isinstance(options, list):
        return None
    for option in cast("list[object]", options):
        option_id = option_id_of(option)
        if option_id is not None and option_kind(option) == kind:
            return option_id
    return None


def narrowest_option_id(options: object, *, approving: bool) -> str | None:
    """Return the id of the narrowest offered option answering one way.

    The once-only option is preferred over the remembering one strictly, never by
    list order: an adapter that lists its remembering option first would
    otherwise turn one answer into a rule that widens or narrows every later run.
    ``None`` when no option of that polarity carries a usable id.
    """
    if approving:
        once, remembering = (
            PermissionOptionKind.ALLOW_ONCE,
            PermissionOptionKind.ALLOW_ALWAYS,
        )
    else:
        once, remembering = (
            PermissionOptionKind.REJECT_ONCE,
            PermissionOptionKind.REJECT_ALWAYS,
        )
    return option_id_of_kind(options, once) or option_id_of_kind(options, remembering)
