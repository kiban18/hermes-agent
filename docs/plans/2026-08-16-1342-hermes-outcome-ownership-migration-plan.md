---
title: Hermes Outcome-Ownership Organization Migration - Plan
type: refactor
date: 2026-08-16
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Hermes Outcome-Ownership Organization Migration - Plan

## Goal Capsule

Replace the current hierarchy of 11 active role bots with an eight-role execution organization in which the result owner, executor, and release verifier are visible. Reuse all 11 existing Telegram bot accounts. Change the eight active bots' display names, keep their immutable usernames, and retain the other three bots as disabled channel reserves.

The user direction in this plan outranks prior organization text. Live Telegram and Kanban state outrank snapshots. Project-specific read-only rules outrank internal execution authority. Stop the cutover if any Kanban task is running, two gateways can poll the same Telegram token, a required profile backup is missing, or an active card cannot be assigned to a valid new profile.

This plan changes local Hermes profiles, shared role skills, the organization wiki, Telegram bot display names, Cron ownership, and active Kanban routing. It does not commit, push, deploy a customer project, delete a bot, change a Telegram username, or mutate completed and archived Kanban history.

Plan paths use three roots:

- `[Hermes home]`: the runtime profile, skill, Cron, and Kanban root.
- `[Hermes Agent]`: this repository.
- `[Company wiki]`: the curated organization reference repository.

## Product Contract

### Summary

The target organization has four result owners under `업무조정`, with three delivery specialists supporting `납품책임`. Telegram remains the user-facing communication surface. Hermes profile IDs remain clean responsibility-based identifiers, while a single mapping records each profile's existing Telegram username.

### Problem Frame

The current organization exposes hierarchy and channel ownership more clearly than business results. Channel-specific sales bots fragment the opportunity pipeline, specialists report through long chains, and old profile IDs keep old routing semantics alive after a display-name change. Renaming Telegram alone would leave Kanban assignment, Cron, skills, approval ownership, and reporting behavior unchanged.

Telegram usernames cannot be changed after bot creation. Forcing Hermes profile IDs to equal the current usernames would produce unreadable identifiers and would not improve execution. The stable solution is to reuse bot accounts and tokens, change visible display names, and keep an explicit profile-to-username mapping.

### Key Decisions

- **Use eight active roles and retain three channel bots as disabled reserves.** (session-settled: user-directed — chosen over keeping 11 active departmental bots: responsibility should be visible before hierarchy.) Governs R1, R2, R7.
- **Use clean responsibility-based profile IDs and do not match them to Telegram usernames.** (session-settled: user-directed — chosen over username-shaped profile IDs: the existing usernames are too irregular to serve as organization names.) Governs R3, R4.
- **Let specialists communicate directly while the result owner receives summaries and decisions.** (session-settled: user-directed — chosen over routing every specialist message through a manager: direct delivery feedback is faster.) Governs R8, R9.
- **The result owner decides and the specialist uses execution tools.** (session-settled: user-directed — chosen over giving every specialist final authority: outcome responsibility must stay singular.) Governs R9, R10.
- **Commit, push, and ordinary deploy decisions never escalate to the representative.** (session-settled: user-directed — chosen over representative approval for routine delivery operations: delivery and service owners have enough authority.) Governs R11, R12.
- **Unify marketplace and relationship sales in one opportunity pipeline.** (session-settled: user-directed — chosen over separate channel owners: Wishket, Kmong, Nara, referrals, and direct contacts compete for the same delivery capacity.) Governs R13, R14.

### Actors

- A1. `업무조정`: aligns priorities, resolves cross-owner exceptions, and holds the only Company Wiki write role.
- A2. `수주책임`: owns the complete opportunity pipeline and chooses the business entity, pursuit, and follow-up.
- A3. `납품책임`: owns scope, sequence, completion criteria, delivery decision, and ordinary project release authority.
- A4. `서비스책임`: owns infrastructure, incidents, backups, security, and infrastructure release authority.
- A5. `경영책임`: owns contracts, tax, payments, subscriptions, domains, and certificates.
- A6. `디자인실행`: turns requirements into flows, screens, and design acceptance evidence.
- A7. `개발실행`: implements and tests approved requirements and requests release verification.
- A8. `출시검증`: independently verifies the result, returns defects to the relevant executor, and issues the release verdict.

### Requirements

#### Telegram and profile identity

- R1. Reuse all 11 existing Telegram bot accounts; create and delete no bot accounts.
- R2. Run eight bots as active organization roles and keep the Wishket, Kmong, and Nara bot accounts as recoverable reserves with Telegram disabled in profile configuration, Cron disabled, no installed gateway service, and no nonterminal Kanban assignment.
- R3. Set both the fallback and Korean localized Telegram display name for each active bot to its Korean role name; do not change its username.
- R4. Use the clean profile IDs and identity mapping in the target roster below; store each Telegram username in profile metadata and the organization reference.
- R5. Preserve each reused bot's token, existing direct-message history, home channel, and user authorization while preventing duplicate polling.
- R6. Update each active profile's `profile.yaml`, `SOUL.md`, configuration, installed role skills, and gateway identity in the same cutover.

#### Organization and authority

- R7. Use exactly these active roles: `업무조정`, `수주책임`, `납품책임`, `서비스책임`, `경영책임`, `디자인실행`, `개발실행`, and `출시검증`.
- R8. Route `디자인실행 → 개발실행 ↔ 출시검증` directly and send the resulting summary, decision request, and release verdict to `납품책임`.
- R9. Keep one result owner for each card; a specialist may execute tools and report evidence but does not assume the result owner's decision authority.
- R10. Limit representative escalation to legally or financially binding company decisions and objectively high-risk technical changes.
- R11. Treat a technical change as objectively high risk when any one condition holds: company-wide or multi-client impact, data-loss risk, security or privacy incident, no tested rollback, or prolonged total outage.
- R12. Let `납품책임` decide commit, push, and ordinary project deploy work; let `서비스책임` decide infrastructure and incident deploy work; unresolved cross-owner cases stop at `업무조정` unless R10 applies.

#### Sales intake

- R13. Let `수주책임` own Wishket, Kmong, Nara, existing-customer, referral, and network opportunities without active channel sub-bots.
- R14. Normalize KakaoTalk, Telegram, email, SMS, phone, meeting, and direct-introduction intake through source check, opportunity registration, follow-up, and proposal or contract conversion.
- R15. For phone intake, record the result, promises, and follow-up only; do not capture recordings or full call content unless the user directs it for that call.
- R16. Keep external send, application, bid, contract, payment, signature, and deletion boundaries separate from internal task ownership.

#### Kanban, reporting, and execution resources

- R17. Reassign every nonterminal Kanban card and its Telegram notification owner to the target roster; preserve terminal card assignees and events as historical truth.
- R18. Post `todo`, `ready`, `running`, `blocked`, `review`, and `done` lifecycle briefings through the card's current assignee bot, with reason or evidence for terminal and waiting states.
- R19. When a role reports its work, include only its own cards; an owner obtains subordinate status through direct subordinate requests and summarizes returned reports.
- R20. Keep headed E2E UI testing on `서윤 MacBook Air → Mac mini`; never open the E2E browser on the user's MacBook Pro and do not fall back locally when both remote GUI workers are unavailable.
- R21. Keep the Company Wiki reader-only for every role except `업무조정`; current work state remains in project and live-system sources.

### Target Roster

| Active role | New profile ID | Reused current profile | Existing Telegram username | Telegram display name |
|---|---|---|---|---|
| 업무조정 | `work-coordinator` | `default` | `crazyup_executive_assistant_bot` | `업무조정` |
| 수주책임 | `acquisition-owner` | `sales-manager` | `crazyup_sales_director_bot` | `수주책임` |
| 납품책임 | `delivery-owner` | `project-manager` | `crazyup_project_ops_bot` | `납품책임` |
| 서비스책임 | `service-owner` | `tech-operations` | `hermes_pxrcioj2nc32yed3_bot` | `서비스책임` |
| 경영책임 | `business-owner` | `business-manager` | `crazyup_business_ops_bot` | `경영책임` |
| 디자인실행 | `design-executor` | `design-lead` | `design_lead_crazy_bot` | `디자인실행` |
| 개발실행 | `development-executor` | `development-lead` | `development_lead_crazy_bot` | `개발실행` |
| 출시검증 | `release-verifier` | `qa-lead` | `CrazyUpFillGapsQABot` | `출시검증` |

| Reserve profile | Telegram username | Reserve display name | Runtime state |
|---|---|---|---|
| `wishket-sales` | `wishket_hermes_bot` | `보관 · 위시켓 채널` | Gateway and Cron disabled |
| `kmong-sales` | `hermes_kmong_sales_bot` | `보관 · 크몽 채널` | Gateway disabled |
| `nara-sales` | `hermes_nara_sales_bot` | `보관 · 나라장터 채널` | Gateway disabled |

Telegram usernames are case-insensitive. Preserve the server-returned spelling in metadata, but compare them with case folding.

### Key Flows

- F1. Opportunity: source channel → `수주책임` normalization → pursue or reject → `납품책임` internal order when an artifact is needed → proposal, application, or contract gate. Covers R13-R16.
- F2. Delivery: `납품책임` scope → `디자인실행` → `개발실행` → `출시검증` → release verdict to `납품책임`. Defects return directly to the relevant executor. Covers R8, R9, R12.
- F3. Exception: owner decision → R11 risk check → `업무조정` for cross-owner resolution → representative only when R10 requires it. Covers R10-R12.
- F4. Kanban briefing: state mutation → assignee notification ownership refresh → current assignee Telegram bot → role-scoped status response. Covers R17-R19.

### Acceptance Examples

- AE1. A KakaoTalk introduction that includes a phone follow-up becomes one `수주책임` opportunity. The record contains the introduction source, call result, promises, next action, and deadline, but no invented transcript. Covers R13-R15.
- AE2. A delivery card moved to `review` is owned by `출시검증`; its Telegram briefing comes from the `출시검증` bot. A rejection returns the same work to the relevant executor and the release verdict goes to `납품책임`. Covers R8, R17-R19.
- AE3. An ordinary customer-project deploy with a tested rollback is decided by `납품책임`. It does not create a representative approval card. Covers R10-R12.
- AE4. A browser QA card starts a headed browser on `서윤 MacBook Air`, or on Mac mini when the first worker is unavailable. If both are unavailable, the card waits and no browser opens on the MacBook Pro. Covers R20.
- AE5. An archived card assigned to `wishket-sales` remains unchanged after cutover, while an open Wishket card moves to `acquisition-owner` and future lifecycle messages come from that bot. Covers R17, R18.

### Scope Boundaries

- Do not add a Telegram bot, change a primary Telegram username, buy a collectible username, rotate a token, or delete an existing chat.
- Do not add a core Hermes display-name or profile-alias subsystem. Existing profile metadata, profile rename, shell wrapper alias, Kanban assignment, and Telegram Bot API methods are sufficient.
- Do not merge caches, session databases, execution logs, or stale gateway runtime files from reserve profiles into active profiles.
- Do not rewrite completed or archived task ownership, results, events, or notification history.
- Do not interrupt a currently running Kanban worker to perform the migration.
- Do not commit, push, or deploy as part of this organization cutover.

## Planning Contract

### Key Technical Decisions

- KTD1. Use existing Hermes primitives only: profile create or rename, profile command aliases, profile metadata, gateway lifecycle commands, Kanban assignment, Cron recreation, and Telegram `setMyName`. This implements R1-R6 without a core-code extension.
- KTD2. Create `work-coordinator` as a fresh named profile because Hermes forbids renaming `default`; do not use a whole-profile clone. Apply the curated user-facing configuration, SOUL, and skills, then transfer only the credential keys required by the enabled model provider and the existing Telegram bot. Do not copy unrelated `.env` entries, sessions, caches, logs, or runtime state. Verify the new gateway, then disable Telegram and Kanban execution in the root `default` profile. Keep `default` as an infrastructure and rollback root, not an active organization role. This implements R4-R6.
- KTD3. Rename the seven active named profiles in place so their credentials, sessions, home channels, and installed tools stay with the role. Create old-name command wrappers that target the new IDs. The wrappers are a transition aid only; all `hermes -p <old-id>` references must be updated because profile command aliases do not change `-p` resolution. This implements R4-R6 and R17.
- KTD4. Freeze at a zero-running-card boundary. Stop gateways only after current workers finish, back up profile metadata and the Kanban database, and prevent dispatcher restarts until identity and assignment migration is complete. This implements R5 and R17.
- KTD5. Reassign open cards through `hermes kanban assign`, not raw task-table SQL. The assignment event refreshes the assignee Telegram subscription. Use read-only SQL for before-and-after inventory and integrity checks. This implements R17-R19.
- KTD6. Consolidate channel capabilities into `acquisition-owner`: retain its sales-pipeline skill, install the existing Wishket, Kmong, and Nara operator skills, migrate only live read markers and required scripts, and recreate the Wishket Cron in the target profile. Do not copy `jobs.json` between profiles. This implements R13-R16.
- KTD7. Set Telegram names for the fallback language and `ko`, then verify both with `getMyName`; a localized old name can otherwise override the new fallback name. Use a one-shot standard-library request that loads the token in-process: the token must not appear in command arguments, shell history, process listings, logs, exceptions, or the cutover report. Verify identity with `getMe` and record only the redacted response fields required by R3 and R5.
- KTD8. Carry the profile-to-Telegram mapping in each profile's metadata and `[Company wiki]/concepts/organization.md`. Do not derive runtime routing from username equality. This implements R4 and R21.
- KTD9. Perform the cutover as one maintenance window with an explicit rollback checkpoint. Do not start any active gateway until all eight active profiles resolve, open cards use valid target IDs, and no token is enabled in two profiles. This implements R5 and R17.

### High-Level Technical Design

The profile directory owns the Telegram token, home channel, SOUL, skills, sessions, and Cron. The Kanban database stores the profile ID independently in task and notification rows. The organization wiki and shared skills define reporting and authority. The cutover therefore changes all three layers before gateways resume:

| Layer | Authority after cutover | Migration mechanism |
|---|---|---|
| Telegram identity | Existing bot account and token | `setMyName` for display; username unchanged |
| Hermes runtime identity | Clean profile ID and per-profile metadata | Create one named profile; rename seven profiles; retain three reserves |
| Work routing | Active Kanban assignee and notifier profile | `hermes kanban assign` on nonterminal cards |
| Behavior | Profile SOUL and role skills | Update role text and reuse existing operators |
| Organization reference | Company Wiki | Replace old hierarchy with outcome ownership and mapping |

### Sequencing and Rollback

1. Inventory all profiles, bot IDs, usernames, fallback and Korean display names, home channels, gateways, Cron jobs, and nonterminal Kanban cards. Wait until no card is running.
2. Stop the gateways and create timestamped backups of the Kanban database and affected profile files. Store secret-bearing backups in a user-only directory, preserve restrictive file modes, and keep tokens out of the manifest. Record the old-to-new map outside the database backup.
3. Create or rename profiles, update identity metadata and skills, and create old-name command wrappers. Keep the root `default` disabled. Leave the three reserve profile IDs unchanged; set their Telegram configuration and Cron disabled, remove their gateway services, and leave them with no nonterminal assignments.
4. Recreate the Wishket Cron and migrate only required channel read state into `acquisition-owner`.
5. Reassign nonterminal cards and audit active card text for old approval owners or report targets. Add a migration comment or edit current operational text when an old ID could steer execution.
6. Update shared organization skills and the Company Wiki. Validate profile and board resolution before external changes.
7. Change Telegram display names, start only the eight active gateways, and run Telegram and Kanban behavior checks.
8. If any identity, routing, or notification check fails, stop the affected gateways, restore the Kanban backup, rename profiles back, restore the old Telegram fallback and Korean display names, restore the old shared role text, and restart the former gateways. Do not partially run old and new owners on the same token.

### System-Wide Impact

- The default profile ceases to be the active organization coordinator. Any hard-coded assumption that `default` is the executive bot must be removed from local shared skills, scripts, Cron prompts, and active card text.
- Active task ownership changes, but dependency edges, status, results, attachments, and terminal history do not.
- Telegram chat continuity follows the bot token, not the profile ID or display name.
- Company Wiki write authority moves from the old root persona to `work-coordinator`; all other profiles remain readers.
- Remote-worker and E2E routing rules remain unchanged and must be restated under the renamed executor and verifier roles.

### Risks and Dependencies

- Copying root credentials too broadly would give `work-coordinator` unrelated secrets. Create it without `--clone`, transfer only credential keys required by its enabled providers, and keep both gateways stopped until the token-ownership check passes.
- Profile command aliases do not make `hermes -p old-name` work. A targeted search must replace every old `-p`, assignee, hierarchy, and notifier reference.
- A localized Telegram name can hide a successful fallback-name update. Verify fallback and Korean names separately.
- A task that becomes running after the preflight cannot be reassigned. The dispatcher must remain stopped through the board migration.
- The working tree already contains unrelated user changes. Implementation must not overwrite, revert, stage, or commit them.
- Telegram, Company Wiki, and profile runtime state are separate systems. HTTP success from one is not proof that the full route works.

## Implementation Units

### U1. Freeze and snapshot the live organization

**Goal:** Establish a recoverable zero-work cutover point.

**Requirements:** R1, R5, R17.

**Files:** `[Hermes home]/kanban/boards/crazyup-fillgaps/kanban.db`, `[Hermes home]/{config.yaml,profile.yaml,SOUL.md,.env}`, `[Hermes home]/profiles/*/{config.yaml,profile.yaml,SOUL.md,.env,cron/jobs.json}`.

**Approach:** Re-query live state. Wait for every running card and active agent to finish without interruption. Stop all 11 gateways, confirm their polling locks are released, create timestamped backups in a mode-0700 directory, preserve mode 0600 on secret files, and record counts by profile and status. Compare token ownership in-process and output only duplicate or unique status. Redact all secrets and token fingerprints from inventory output.

**Test Scenarios:** A running card aborts the cutover; a missing database backup aborts the cutover; a stopped gateway has no live Telegram polling lock.

**Verification:** Compare bot ID, username, fallback and Korean display name, gateway, profile, Cron, and Kanban inventories to the backup manifest and confirm SQLite integrity before continuing.

### U2. Build the clean profile roster

**Goal:** Create eight active responsibility profiles and three recoverable channel reserves.

**Requirements:** R2, R4-R7, R21.

**Files:** `[Hermes home]/profile.yaml`, `[Hermes home]/SOUL.md`, `[Hermes home]/config.yaml`, `[Hermes home]/profiles/*/{profile.yaml,SOUL.md,config.yaml,skills}`.

**Approach:** Apply KTD2 and KTD3. Write Korean role descriptions, role ownership, Telegram username metadata, reporting rules, authority boundaries, and remote-worker rules. Leave the three reserve profile IDs unchanged, disable Telegram and Cron in their configuration, remove their gateway services, and assign them no nonterminal work. Create transition command wrappers for the seven renamed active profiles.

**Test Scenarios:** Each active ID resolves to exactly one directory; the root `default` has no active Telegram or dispatcher role; every active profile has the expected token identity and home channel; reserve profiles cannot dispatch work.

**Verification:** Run profile list and show commands for all eight roles, inspect gateway configuration without revealing tokens, and confirm old wrapper commands select the intended new named profiles.

### U3. Replace hierarchy behavior with outcome ownership

**Goal:** Make every bot use the target responsibilities, communication flow, and approval boundaries.

**Requirements:** R7-R16, R19-R21.

**Files:** `[Hermes home]/shared-skills/organization-board-operator/SKILL.md`, `[Hermes home]/shared-skills/organization-board-operator/scripts/collect-subordinate-kanban-reports.sh`, `[Hermes home]/shared-skills/organization-chart/SKILL.md`, `[Hermes home]/shared-skills/project-operator/SKILL.md`, `[Hermes home]/profiles/*/SOUL.md`, `[Hermes home]/profiles/acquisition-owner/skills/sales-pipeline-operator/SKILL.md`, `[Company wiki]/concepts/organization.md`.

**Approach:** Replace old manager-team lists and approval owners with the eight-role model. Keep direct specialist communication and owner summaries. Extend the existing sales pipeline operator to cover referrals and all listed communication sources, including the phone-recording boundary. Preserve Company Wiki reader and writer restrictions.

**Test Scenarios:** A role-scoped status question returns only that role's cards; `납품책임` obtains direct reports from its three specialists; routine commit, push, or deploy text does not create a representative approval; a high-risk case follows R11.

**Verification:** Run the subordinate-report script in dry-run mode for `work-coordinator` and `delivery-owner`, then inspect the generated commands and target IDs. Ask each active Telegram role one responsibility question after U6.

### U4. Consolidate sales channel capability and Cron

**Goal:** Let `acquisition-owner` operate every sales source without active channel sub-bots.

**Requirements:** R2, R13-R16.

**Files:** `[Hermes home]/profiles/acquisition-owner/skills`, `[Hermes home]/profiles/acquisition-owner/scripts/wishket-operator.sh`, `[Hermes home]/profiles/acquisition-owner/cron/jobs.json`, `[Hermes home]/profiles/acquisition-owner/kmong-last-read.json`, reserve-profile memories and channel read markers.

**Approach:** Apply KTD6. Move or install only the three channel operator skills and current read markers. Patch the Wishket script's profile-local state and lock paths. Recreate the enabled Wishket Cron in `acquisition-owner` with the same schedule and delivery intent. Leave old Cron output and logs in the reserve profile as history.

**Test Scenarios:** Wishket dry-run resolves only target-profile paths; Kmong resumes after the last-read marker without replaying the inbox; Nara keeps source-first qualification rules; phone intake produces a concise action record.

**Verification:** List the target Cron, run the migrated script with `--dry-run`, and confirm every referenced script is a regular target-profile file rather than a cross-profile symbolic link.

### U5. Migrate active Kanban ownership and briefings

**Goal:** Route all current and future work through the new profiles without rewriting history.

**Requirements:** R17-R19.

**Files:** `[Hermes home]/kanban/boards/crazyup-fillgaps/kanban.db`.

**Approach:** Inventory nonterminal cards at cutover and assign them with this mapping: old executive work → `work-coordinator`; Wishket, Kmong, Nara, and sales-manager work → `acquisition-owner`; project-manager work → `delivery-owner`; tech-operations work → `service-owner`; business-manager work → `business-owner`; design, development, and QA work → their executor or verifier profile. Preserve each card's status and dependency graph. Audit active body and comment text for obsolete approval owners or reporting lines. Refresh or verify `notifier_profile` through assignment events.

**Test Scenarios:** A historical done card retains its old assignee; an open channel-sales card moves to `acquisition-owner`; a blocked card remains blocked; a review card remains review; each active subscription owner equals the task assignee.

**Verification:** Query status and assignee counts before and after, run read-only SQLite `PRAGMA integrity_check`, list `--mine` from every active profile, and verify no nonterminal card references a missing or reserve assignee.

### U6. Rename Telegram displays and activate eight gateways

**Goal:** Expose the new roles in existing Telegram conversations with no account recreation.

**Requirements:** R1-R5, R18, R19.

**Files:** No repository file; external Telegram bot profile state and per-profile gateway runtime state.

**Approach:** Apply KTD7 and KTD9. While every gateway remains stopped, set each active bot's fallback and Korean display name through the secret-safe one-shot request. Set the three reserve display names to their reserve labels, then disable their Telegram configuration and leave their gateway services removed. Start active gateways one at a time, verify `getMe`, `getMyName`, home-channel state, and connected polling before starting the next gateway.

**Test Scenarios:** The active chat shows the Korean role name; `getMe` returns the unchanged username and bot ID; fallback and Korean names match; a reserve gateway remains stopped; no token lock collision appears.

**Verification:** Verify all 11 bot IDs and usernames against the preflight inventory, verify eight connected gateways, and verify three stopped reserves. Send one role-identification prompt in each existing active home channel and confirm the expected Korean role response.

### U7. Prove end-to-end routing and close the maintenance window

**Goal:** Demonstrate that profile, Kanban, Telegram, and organization behavior agree.

**Requirements:** R7-R21.

**Files:** `[Hermes home]/shared-skills`, `[Company wiki]/concepts/organization.md`, live Kanban and gateway state.

**Approach:** Exercise AE1-AE5 without customer-facing sends. Use disposable internal cards or existing safe cards to test assignment briefings, scoped status, owner summaries, review return, and approval classification. Do not run a local browser. If a browser scenario is required, use the existing remote-worker route and collect remote evidence.

**Test Scenarios:** Every acceptance example passes; a reserve profile receives no new task; a current assignee bot delivers each tested lifecycle state; Company Wiki writes are unavailable to the other seven active roles.

**Verification:** Save a redacted cutover report with the final roster, profile-to-username mapping, gateway states, active-card counts, Cron status, notification ownership, passed examples, and any deferred cleanup. Remove temporary test cards and abandoned migration artifacts without deleting historical records.

## Verification Contract

Run verification from the relevant root. Commands beginning with `./` below run from `[Hermes home]`. Do not expose `.env` values or bot tokens.

1. **Profile and gateway inventory**

   ```bash
   hermes profile list
   hermes gateway list
   hermes profile show work-coordinator
   hermes profile show acquisition-owner
   hermes profile show delivery-owner
   hermes profile show service-owner
   hermes profile show business-owner
   hermes profile show design-executor
   hermes profile show development-executor
   hermes profile show release-verifier
   ```

2. **Cron and channel-state checks**

   ```bash
   hermes -p acquisition-owner cron list
   hermes -p acquisition-owner cron list --all
   ./profiles/acquisition-owner/scripts/wishket-operator.sh --dry-run
   ```

3. **Kanban routing and history checks**

   ```bash
   hermes kanban --board crazyup-fillgaps stats --json
   hermes kanban --board crazyup-fillgaps assignees
   hermes -p work-coordinator kanban --board crazyup-fillgaps list --mine --json
   hermes -p acquisition-owner kanban --board crazyup-fillgaps list --mine --json
   hermes -p delivery-owner kanban --board crazyup-fillgaps list --mine --json
   hermes -p service-owner kanban --board crazyup-fillgaps list --mine --json
   hermes -p business-owner kanban --board crazyup-fillgaps list --mine --json
   hermes -p design-executor kanban --board crazyup-fillgaps list --mine --json
   hermes -p development-executor kanban --board crazyup-fillgaps list --mine --json
   hermes -p release-verifier kanban --board crazyup-fillgaps list --mine --json
   sqlite3 ./kanban/boards/crazyup-fillgaps/kanban.db 'PRAGMA integrity_check;'
   ```

   Read-only SQL must show no nonterminal task assigned to a retired ID or reserve profile, every active notification owner equal to its task assignee, and unchanged terminal task assignees and counts from the backup manifest.

4. **Organization behavior checks**

   ```bash
   ./shared-skills/organization-board-operator/scripts/collect-subordinate-kanban-reports.sh work-coordinator --dry-run
   ./shared-skills/organization-board-operator/scripts/collect-subordinate-kanban-reports.sh delivery-owner --dry-run
   ```

   Telegram checks must confirm all eight role identities, own-card scoping, subordinate collection, and assignee-owned lifecycle briefings. Telegram API checks must confirm bot ID, unchanged username, fallback display name, and Korean display name.

5. **Resource-policy check**

   If end-to-end verification needs browser QA, run `remote-worker status` and `remote-worker slots`, then use a headed browser on `서윤 MacBook Air → Mac mini`. Evidence must identify the worker. A local MacBook Pro browser is a failed verification.

No Hermes Agent source test suite is required when implementation follows KTD1 and changes no core source. If implementation changes core source despite the plan, stop and revise the plan before running the repository's required `scripts/run_tests.sh` targets.

## Definition of Done

- All 11 existing Telegram bot accounts are accounted for; eight are active and three are disabled reserves.
- The eight active chats show the Korean role names for fallback and Korean locales, and all usernames and bot IDs remain unchanged.
- The eight active clean profile IDs resolve with correct descriptions, SOULs, skills, home channels, and gateway identities.
- The root `default` has no active organization gateway, dispatcher, Telegram role, or assigned nonterminal work.
- Every nonterminal Kanban card uses an active target profile and the correct notifier owner; terminal ownership and events match the preflight manifest.
- `acquisition-owner` can use Wishket, Kmong, Nara, referral, and direct-contact intake through one pipeline, and its Wishket Cron passes dry-run.
- Direct specialist communication, owner decisions, representative escalation, Company Wiki access, and remote E2E rules pass the acceptance examples.
- Exactly eight gateways are connected and the three reserve gateways are stopped, with no duplicate token polling.
- Rollback artifacts and a redacted cutover report exist until the user accepts the migration; after acceptance, remove secret-bearing temporary backups and retain only the redacted report.
- Temporary test cards, duplicate configuration, and abandoned migration artifacts are removed; unrelated working-tree changes remain untouched.
- No commit, push, customer deploy, bot creation, bot deletion, token rotation, or Telegram username change occurred.
