# Summary

<!-- State the problem, change, and resulting behavior. -->

- Problem:
- Change:
- Result:

## Tracking

- Issue:
- Audit findings or tasks:

## Tests and documentation

- Tests added or updated:
- Documentation added or updated:

## Validation

<!-- Record the exact result for each command. -->

| Gate | Command | Status | Result |
| --- | --- | --- | --- |
| Continuous integration | `just ci` | passed / failed / not run | |
| Documentation | `just dev build docs` | passed / failed / not run | |
| Service tests, if relevant | `just dev test service` | passed / failed / not run | |

### Excluded or not run gates

| Gate | Reason | Resulting uncertainty or follow-up |
| --- | --- | --- |
| | | |

## Formal review

| Severity | Type | Finding | Resolution | Queued follow-up |
| --- | --- | --- | --- | --- |
| | | | | |

## Checklist

- [ ] The change is focused and links its issue and audit records.
- [ ] Tests and documentation match the changed behavior.
- [ ] Validation results and gates that were not run are recorded truthfully.
- [ ] Every review finding has a resolution or queued follow-up.
- [ ] The change contains no secrets, runtime artifacts, or unrelated generated clutter.
