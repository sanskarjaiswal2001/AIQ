# Collector Signal Inventory

AIQ is using a collector-first / telemetry-first approach: harvest the maximum safe local signal from project directories and agent harness logs, then design admin workflows from real observed metrics.

Generated from the current collector code and local sample log schemas.

## Already collected today

Top-level snapshot:

- employee_id, employee_name, employee_email when configured
- collected_at, period_start, period_end
- summary totals: sessions, requests, workspaces, AI LOC, user LOC, input/output tokens, estimated cost
- practice_scores and anti_patterns
- model_usage by model: requests, input tokens, output tokens, cost
- work_types: bug fix, refactor, code review, test, docs, style, config, feature, other
- activity: daily request/session/LOC counts and hourly heatmap
- plan_context when locally configured

Project-level snapshot:

- project_id from normalized git remote when available, otherwise stable workspace hash
- project_name, project_path
- git_remote_url, normalized_git_remote
- harness_usage by harness
- sessions, requests
- AI LOC, user LOC
- input/output tokens and estimated cost
- first_activity, last_activity, active_days
- model_usage, work_types
- git_branches
- files_edited_count

Currently supported harnesses:

- Claude Code: dedicated parser
- Codex CLI: generic JSON/JSONL parser plus metadata inheritance
- OpenCode: generic JSON/JSONL parser, but current local sample is mostly package/cache files, not useful session logs
- Cursor: generic JSON/JSON parser, current local sample only exposes recentlyViewedFiles
- Copilot/VS Code: generic workspaceStorage parser when the directory exists

## Implemented telemetry sections

These are now emitted in every collector payload:

- `tool_usage`: total calls, calls/failures/interruptions/duration/output bytes by tool, read/write call totals
- `command_usage`: shell command totals, executable breakdown, repeated-command hashes, failed/interrupted command counts
- `file_activity`: edited/referenced file counts, top files/directories, AI LOC by language
- `context_metrics`: cache read/write tokens, total tokens, high-context request count, cache-token ratio
- `agent_metrics`: agent/plan/subagent/MCP/skill request counts, skill names when exposed
- `quality_metrics`: canceled requests, failed commands, interrupted tools, test-command count, average elapsed request time

## Extra signal visible in Claude Code logs

Claude logs expose enough structure for much richer metrics than AIQ currently stores:

- Prompt/session identity: sessionId, uuid, parentUuid, requestId, promptId, messageId
- Workspace identity: cwd, gitBranch, version, entrypoint
- Mode/context: permissionMode, isSidechain, userType
- Message metadata: model, stop_reason, stop_sequence, diagnostics, context_management, container
- Token usage: input/output plus cache read/write tokens
- Tool calls from assistant content blocks: tool name, inputs, file paths, command text
- Tool results from `toolUseResult`: stdout/stderr presence, exit/interruption status, filePath, originalFile, structuredPatch, old/new strings, replaceAll, persistedOutputPath, persistedOutputSize
- Hook/attachment events: hookName, hookEvent, command, durationMs, stdout/stderr, exitCode, itemCount, addedLines, addedNames/removedNames/readdedNames, skillCount, pendingMcpServers
- File snapshots: trackedFileBackups and snapshot timestamps
- AI-generated titles and last-prompt metadata

Best admin metrics we can build from Claude next:

- tool success/failure rate
- bash/test/build command frequency and failure rate
- retry loops and repeated failing commands
- file churn: touched files, created/removed files, patch sizes, persisted output sizes
- context growth/compaction pressure from diagnostics/context_management
- subagent/sidechain usage quality
- skill and MCP adoption
- permission friction: prompt approvals, denied/blocked tools if present
- elapsed time per request using timestamps and hook durationMs

## Extra signal visible in Codex logs

Local Codex sample logs expose:

- session_meta and turn_context records
- cwd in payload metadata
- response_item/event_msg stream
- tool call records with call_id, name, arguments, output
- assistant/user role/content records
- usage in response.done: input_tokens, output_tokens, total_tokens, input_token_details, output_token_details
- rate_limits when emitted
- auth_mode and model/provider metadata when present

Best admin metrics we can build from Codex next:

- per-turn token/cost attribution
- tool-call count and tool mix
- command/file operation extraction from tool arguments/output
- rate-limit pressure
- cwd/git-remote based project attribution
- model/provider usage by project and employee

## Weak or harness-dependent signal

These are not guaranteed across all tools, but should be opportunistically parsed when present:

- exact acceptance/rejection of generated code
- actual human review quality
- true wall-clock coding time when the harness omits duration fields
- full git diff unless the tool records patch/old/new strings or the workspace still has a repo available
- Azure AD/company identity until admin/auth integration provides it
- paid plan/seat limits unless employee/admin config or provider API supplies it

## Recommended collector roadmap

1. Keep raw payload extensible. Store new sections under payload_json first; normalize later only when admin features need fast queries.
2. Add `tool_usage` aggregate: calls by tool, failures, interrupted calls, command calls, read/write/search counts.
3. Add `command_usage` aggregate: shell commands normalized by executable, exit code, durationMs, stderr presence.
4. Add `file_activity` aggregate: edited/referenced file counts, extensions, created/deleted/patch LOC estimates, top changed directories.
5. Add `context_metrics`: cache read/write tokens, context/compaction diagnostics, long-context risk.
6. Add `agent_metrics`: subagent/sidechain count, MCP usage, skill usage, plan-mode usage.
7. Add `quality_metrics`: test command usage, failed test/build commands, retry loops, canceled/interrupted requests.
8. Add `project_git_metrics`: branch list, repo remote, maybe current commit if workspace exists locally at collection time.
9. Only after these exist, design admin features around real metrics: training, productivity, capacity, cost controls, project health, and compliance.

## Privacy stance

Prefer counts, names, paths, command executables, status codes, durations, and hashes over raw prompt/output text. Keep raw text local in payload_json only when needed for debugging and never send to external services.
