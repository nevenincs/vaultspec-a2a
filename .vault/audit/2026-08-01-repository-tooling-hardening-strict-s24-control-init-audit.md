---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:19cf5790880f50c427e724dec07d49a28699cb5fee16708eaf535545f34fcf37'
related: []
---
# `repository-tooling-hardening` audit: `Control package export contract review`

## Scope

Reviewed S24's isolated removal of the stale `__all__` declaration from the control package initializer. The contract requires direct-child module imports to remain available without adding imports, shims, or a replacement export list.

## Findings

No findings. The removed declaration listed a missing `diagnostics` child and omitted six present children, so it was not a truthful export contract. A fresh-process import check confirmed every 23 immediate module children remains available through `from vaultspec_a2a.control import child`; the initializer declares no `__all__`; no in-repository consumer uses a package-level or wildcard import. The diff is limited to the 23 removed declaration lines and adds no test-policy-prohibited construction.

## Recommendations

No follow-up is required for this isolated correction. Future callers should continue importing concrete control implementations from their direct child modules.
