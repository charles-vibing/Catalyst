# As-of date (demo clock)

All “today” logic in Catalyst should go through **one clock**, not scattered `new Date()` / `date.today()` calls.

## Modes

| Mode | When to use | Value |
|---|---|---|
| **Frozen demo** | Pitch decks, reproducible demos | Fixed ISO date, e.g. `2026-06-28` |
| **Live today** | Local dev against a shifted cohort, or future production | Real calendar date |

## Mockup

In `mockups/hospital-dashboard.html`:

```js
const USE_REAL_TODAY = false;   // true → browser today()
const DEMO_AS_OF = "2026-06-28"; // used when USE_REAL_TODAY is false
```

Header shows the resolved as-of and whether it is **frozen demo** or **live today()**.

## Real app (MVP plan)

Single source of truth, in priority order:

1. **UI override** (optional admin chip) → writes `app_setting.as_of_date`
2. **Env** `CATALYST_AS_OF=2026-06-28` (empty / unset = live today)
3. **Default** `app_setting`: freeze `2026-06-28` for demos

```text
get_as_of() =
  if CATALYST_AS_OF set and non-empty → that date
  else if app_setting.as_of_date set   → that date
  else                                 → date.today()
```

Every derived field uses `get_as_of()`:

- days remaining, active / completed / **upcoming** (`admit > as_of`)
- claims visibility (`file_received_dt ≤ as_of`)
- HIE vs claims storytelling
- signal “age” labels

## Episode status rules

Relative to `as_of`:

| Status | Rule |
|---|---|
| `upcoming` | `admit > as_of` — not on monitoring roster yet (patients 31–50 if freeze is 2026-06-28) |
| `active` | `admit ≤ as_of ≤ discharge + 30` |
| `completed` | `as_of > discharge + 30` |

## Swap checklist

- [ ] Change one setting (env or `USE_REAL_TODAY`) — do **not** rewrite patient files
- [ ] Confirm header shows the resolved date + mode
- [ ] Spot-check: upcoming admits disappear from “active”; claims lag still gated
