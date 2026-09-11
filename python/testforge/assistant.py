"""Optional LLM-backed failure analyst.

Talks to any OpenAI-compatible /v1/chat/completions endpoint. Falls back
silently to "no analysis available" when no endpoint is configured, so
this module is never a hard dependency.

Why an LLM here and not elsewhere? Failure diagnosis is the one place
where you genuinely benefit from natural-language reasoning over a mix
of structured inputs (stack trace, error message, environment, similar
past failures). Test selection, scheduling, regression thresholds - those
are all things where rule-based logic is faster, cheaper, and more
predictable. We deliberately keep the LLM out of those.

When enabled, the analyst is given:
    - the failure message + stack trace,
    - the test's metadata (component, tags, recent history),
    - the top-3 most similar past failures from storage.

It returns:
    - a short "likely cause" summary,
    - a confidence estimate (0.0 - 1.0),
    - a list of suggested investigation steps.

The orchestrator writes the analyst's output into the build report
alongside the rule-based cluster, clearly labeled as assistant-generated.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from .config import AssistantConfig


@dataclass
class AnalystReport:
    available: bool
    likely_cause: str = ""
    confidence: float = 0.0
    related_failures: list[str] = None
    suggested_investigation: list[str] = None
    raw: str = ""

    def __post_init__(self):
        if self.related_failures is None:
            self.related_failures = []
        if self.suggested_investigation is None:
            self.suggested_investigation = []


class FailureAnalyst:
    def __init__(self, config: AssistantConfig):
        self.config = config
        self._client = None
        if config.enabled and config.base_url:
            try:
                import httpx
            except ImportError:
                # httpx not installed; fall back silently.
                return
            self._client = httpx.Client(timeout=config.timeout_seconds)

    @property
    def available(self) -> bool:
        return self._client is not None and bool(self._api_key())

    def _api_key(self) -> str:
        if not self.config.api_key_env:
            return ""
        return os.environ.get(self.config.api_key_env, "")

    def analyze(self,
                failure_message: str,
                stack_trace: str,
                test_name: str,
                component: str,
                tags: list[str],
                similar_history: list[dict]) -> AnalystReport:
        if not self.available:
            return AnalystReport(available=False)

        prompt = self._build_prompt(failure_message, stack_trace, test_name,
                                     component, tags, similar_history)
        try:
            resp = self._client.post(
                f"{self.config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key()}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": self.config.max_tokens,
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return self._parse_response(content)
        except Exception as e:
            return AnalystReport(available=False, raw=f"analyst error: {e}")

    def _build_prompt(self, failure_message, stack_trace, test_name,
                       component, tags, similar_history) -> str:
        lines = [
            "Analyze this test failure and provide a diagnosis.",
            "",
            f"Test: {test_name}",
            f"Component: {component}",
            f"Tags: {', '.join(tags) if tags else '(none)'}",
            "",
            "Failure message:",
            failure_message or "(none)",
            "",
            "Stack trace:",
            stack_trace or "(none)",
            "",
            "Similar past failures (most recent first):",
        ]
        for i, h in enumerate(similar_history[:5], 1):
            lines.append(f"  {i}. {h.get('test_name', '?')} "
                         f"[build {h.get('build_id', '?')}]: "
                         f"{h.get('failure_message', '')[:200]}")
        lines += [
            "",
            "Respond with strict JSON only, in this schema:",
            "{",
            '  "likely_cause": "<one or two sentences>",',
            '  "confidence": <float 0.0-1.0>,',
            '  "related_failures": ["<test_name or build_id>", ...],',
            '  "suggested_investigation": ["<step>", ...]',
            "}",
        ]
        return "\n".join(lines)

    def _parse_response(self, content: str) -> AnalystReport:
        # The model is instructed to return strict JSON, but we tolerate
        # surrounding prose by extracting the first {...} block.
        m = re.search(r"\{[\s\S]*\}", content)
        if not m:
            return AnalystReport(available=True, raw=content)
        try:
            d = json.loads(m.group(0))
            return AnalystReport(
                available=True,
                likely_cause=d.get("likely_cause", ""),
                confidence=float(d.get("confidence", 0.0)),
                related_failures=d.get("related_failures", []),
                suggested_investigation=d.get("suggested_investigation", []),
                raw=content,
            )
        except Exception:
            return AnalystReport(available=True, raw=content)


SYSTEM_PROMPT = (
    "You are a failure analyst embedded inside a test automation platform. "
    "You receive a single test failure plus context. Diagnose the most likely "
    "root cause and propose concrete investigation steps. Be specific and "
    "concrete; do not speculate beyond what the inputs support. If you cannot "
    "determine a cause with reasonable confidence, say so and set confidence "
    "to a low value. Always respond in the exact JSON schema requested - "
    "no surrounding prose."
)
