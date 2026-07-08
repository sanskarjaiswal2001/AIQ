# AIQ rules audit

AIQ should not blindly inherit Microsoft AI-Engineering-Coach's rule philosophy. The product should score behaviors that local coding-agent logs can support with reasonable evidence.

## Basis used

- Google Cloud's AI coding-assistant guidance emphasizes explicit requirements, iterative development, and keeping humans responsible for verification.
- Agentic Coding Principles frames AI-agent use around developer accountability for quality, security, and maintainability.
- Current context-engineering guidance emphasizes selecting, compressing, and structuring context instead of dumping arbitrary prompt text.

## Kept by default

- Context quality: repeated prompts, missing specs, verbose uncompressed prompts, context-engineering gaps.
- Human verification: speed-accept and review-proxy rules.
- Agent hygiene: runaway loops, session drift, mega sessions, cancellations, frustration signals.
- Cost/plan fit: premium waste, premium lookup routing, model overreliance as a low-priority routing signal, rolling-window pressure when plan context is configured.

## Off by default

- `late-night-coding`, `weekend-overwork`: lifestyle surveillance, not AI efficiency.
- `tunnel-vision`: single-project focus is often normal and healthy.
- `no-plan-mode`, `no-skills`: tool-specific proxies; useful for some Claude/Hermes workflows but not generally valid across Codex, OpenCode, Cursor, Copilot.

## UI policy

The Rules view shows each rule's audit verdict and basis. Admins can still enable off-by-default rules or change severity, but default recommendations should come from observable engineering behavior, not vague productivity morality.
