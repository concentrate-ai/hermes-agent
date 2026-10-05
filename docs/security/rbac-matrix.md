# RBAC role matrix — LLM gateway admin console

**Status:** Design draft — this matrix is not derived from a shipped product; the permissions below are proposals for the console build, to be validated against implementation. · **Companion reading:** LLM Spend Budgets and Alerts — Internal Policy (budget guardrails in this matrix mirror that policy's approval tiers).

This matrix defines what each admin-console role can do on the Concentrate LLM gateway — an OpenAI-compatible proxy in front of providers like OpenAI, Anthropic, and Azure. It covers five roles (Owner, Admin, Developer, Billing, Viewer) across five resource domains: API keys, budgets/spend, logs, models, and SSO/settings. Model assumptions: users map to roles, one role per user per workspace, and no custom or cascading roles in v1.

## Legend

| Symbol | Meaning |
|---|---|
| **F** | Full control — perform the action and manage who/what else can |
| **L** | Limited — works on resources they own: create and use own keys; see own-key logs. Cannot revoke or manage other users' resources |
| **C** | Create/use — can submit; an Owner/Admin acts on it |
| **V** | View only |
| **–** | No access |

## Permission matrix

| Domain | Action | Owner | Admin | Developer | Billing | Viewer |
|---|---|---|---|---|---|---|
| API keys | Create API key | F | F | L | – | – |
| API keys | Revoke own API key | F | F | L | – | – |
| API keys | Revoke others' API keys | F | F | – | – | – |
| API keys | Rotate API key (dual-key window) | F | F | L | – | – |
| API keys | Set per-key rate limits | F | F | L | V | – |
| API keys | View key usage | F | F | L | V | V |
| Budgets | Create/edit budgets | F | F | – | – | – |
| Budgets | Delete budgets | F | F | – | – | – |
| Budgets | Approve budget overage | F | F | – | – | – |
| Budgets | Create/edit spend alerts | F | F | – | V | V |
| Budgets | View spend dashboards | F | F | V | F | V |
| Logs | View request/response logs | F | F | L | – | V |
| Logs | Export logs | F | F | – | – | – |
| Logs | Configure log retention/redaction | F | F | – | – | – |
| Logs | View audit log | F | F | V | V | V |
| Models | View model catalog + pricing | F | F | V | V | V |
| Models | Enable/disable or route models | F | F | – | – | – |
| Models | Request model additions | F | F | C | – | – |
| SSO/settings | View SSO config | F | F | V | V | V |
| SSO/settings | Configure SSO/SCIM | F | F | – | – | – |
| SSO/settings | Manage org members and roles | F | F | – | – | – |
| SSO/settings | Change billing plan | F | F | – | F | – |
| SSO/settings | Delete workspace | F | – | – | – | – |

## Per-row rationale

**API keys.**
- *Create / revoke own / rotate:* Developers are self-service — they mint, rotate, and retire their own keys without filing a ticket. Owner/Admin can create keys on anyone's behalf (e.g., service accounts).
- *Revoke others' keys:* Owner/Admin only. A Developer revoking a teammate's key mid-incident would worsen debugging; leaked-key response is an admin action.
- *Set per-key rate limits:* Developers can throttle their own keys down; raising limits above the workspace default needs Admin. Billing sees the limits because per-key limits drive bill shape, but view-only.
- *View key usage:* Owner/Admin see everything; Developers see their own keys' usage; Billing sees aggregate usage for reconciliation; Viewers see aggregated usage, not per-key token counts.

**Budgets.**
- *Create/edit/delete budgets, approve overage:* Owner/Admin only, with the two-person guardrail below. Finance monitors but doesn't set engineering budgets — consistent with the spend policy, where team leads propose and FinOps approves.
- *Spend alerts:* Owner/Admin configure thresholds and recipients; others can see active alerts. Alert visibility is the point — nobody should learn about spend at month-end.
- *Spend dashboards:* Billing's one full-control row in the domain: dashboards are read surfaces, and billing needs every budget against actuals without filing a request.

**Logs.**
- *View request/response logs:* Developers see logs for their own keys' traffic (redacted by default); Viewers see workspace-wide logs but always redacted; Billing gets none — prompts and responses contain no billing signal worth the privacy cost.
- *Export logs:* Owner/Admin only, because exports are how logs leak. Viewer exports render the redacted version if that combination is ever needed.
- *Configure retention/redaction:* Owner/Admin, with every change audit-logged (redaction guardrail below).
- *Audit log:* visible to all internal roles — an audit log that only admins can read is an audit log nobody checks. Viewer access is view-only and audit logs can never be edited or deleted by any role.

**Models.**
- *View catalog + pricing:* open to every role; model choice is a team concern.
- *Enable/disable or route:* Owner/Admin — routing changes alter cost and reliability for the whole workspace.
- *Request model additions:* Developers submit; Owner/Admin configure routing and pricing. Keeps provider-expense decisions with budget holders.

**SSO/settings.**
- *View SSO config:* readable by all roles (the config itself contains no secrets).
- *Configure SSO/SCIM, manage members and roles:* Owner/Admin. One asymmetry: Admin cannot grant or revoke the Owner role — that stays Owner-only, closing the self-escalation path.
- *Change billing plan:* Billing role's headline action, plus Owner/Admin.
- *Delete workspace:* Owner-only. The action is irreversible — it kills every key, budget, and log at once — so one person, not two, holds it deliberately, and it cannot be delegated to Admin.

## Guardrails

**Key lifecycle.** Revoking a key kills in-flight sessions within 30 seconds — a stream mid-generation may finish its current response, but no further provider call is charged. Rotation uses a dual-key window: old and new keys both authenticate for a configurable period (default 24 hours), after which the old key revokes automatically. No integration has a hard cutover, and revocation latency after the window is the same 30-second kill.

**Budget changes.** Raising a budget by more than 20% or deleting any budget requires Owner or Admin plus a second approver, and the requester never approves their own change. This mirrors the spend policy: routine top-ups under $500/month per project get team-lead-plus-one-engineer verification; anything larger goes to FinOps or senior engineering. Threshold and hard-stop notifications (80% / 90% / 100%) are not disableable by any role, including Owner.

**Log redaction.** Redaction of prompt and response bodies is default-on for Viewers and configured by Owner/Admin only. Viewers never see unredacted bodies — including in exports. Owner/Admin can toggle redaction per-project for debugging; every toggle is an audit-log entry.

**SCIM deprovisioning.** When SSO-enforced SCIM removes a user, everything they owned is repossessed within 24 hours: their API keys revoke (with the 30-second kill), and budgets they own reassign to their Admin or Owner rather than orphaning. SCIM leads the members list; the console cleans up the resources the member left behind.

## Fail-open vs fail-closed

All permission checks fail closed: if role resolution errors, the session times out, or the console cannot reach the policy store, the action is refused — never permitted because a check broke. The single deliberate fail-close on data is redaction: if the redaction engine is down, Viewer log bodies render empty rather than raw, because a rendering failure exposing customer prompts is worse than a blank panel. Owner/Admin toggle redaction from their role grant, not from any absence of enforcement.

## Open questions for implementation

- Rate-limit ceiling for Developer-managed keys: hard per-key cap by default with Admin override, or unlimited with per-key limits only? Decision needed per-tenant before the rate-limits row ships.
- In-flight billing at revocation: a stream deeper than the 30-second kill window is billed through the current request, then hard-killed — confirm with finance that billed-through token amounts are accepted as an exception to the kill promise.
