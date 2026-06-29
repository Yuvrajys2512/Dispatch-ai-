"""The 50+-scenario triage corpus (spec §Sprint Week 1-2 milestone).

Runs every scripted scenario through the agent and asserts the extracted card,
severity, and route match the scenario's declared expectation. Two release
gates are enforced here:

  * **Zero false negatives** — no genuine (``real_emergency``) call is ever
    severity JUNK or routed to AUTO_RESOLVE.
  * **Per-scenario correctness** — severity + route + handoff match Expected.

Running the module as a script prints the scenario → card → severity → route →
pass/fail table; ``pytest -s`` shows it inline.
"""

from __future__ import annotations

import asyncio

import pytest

from app.adapters.mock.llm import MockLLMProvider
from app.adapters.mock.scenarios import TRIAGE_CORPUS, Scenario
from app.agent import TriageAgent, TriageOutcome
from tests.agent.helpers import scenario_caller, scenario_turns


async def _run(scenario: Scenario) -> TriageOutcome:
    agent = TriageAgent(MockLLMProvider())
    return await agent.triage(
        scenario_turns(scenario), caller=scenario_caller(scenario)
    )


def test_corpus_is_at_least_50_scenarios():
    assert len(TRIAGE_CORPUS) >= 50


@pytest.mark.parametrize("scenario", TRIAGE_CORPUS, ids=lambda s: s.id)
@pytest.mark.asyncio
async def test_scenario_triage_matches_expected(scenario: Scenario):
    out = await _run(scenario)
    exp = scenario.expected
    assert out.severity.value == exp.severity, (
        f"{scenario.id}: severity {out.severity.value} != {exp.severity}"
    )
    assert out.route.target.value == exp.route, (
        f"{scenario.id}: route {out.route.target.value} != {exp.route}"
    )
    assert out.route.handoff == exp.handoff, (
        f"{scenario.id}: handoff {out.route.handoff} != {exp.handoff}"
    )


@pytest.mark.parametrize("scenario", TRIAGE_CORPUS, ids=lambda s: s.id)
@pytest.mark.asyncio
async def test_zero_false_negatives(scenario: Scenario):
    """RELEASE GATE: a real emergency is never dropped as junk."""
    if not scenario.expected.real_emergency:
        return
    out = await _run(scenario)
    assert out.severity.value != "JUNK", f"{scenario.id}: real emergency → JUNK!"
    assert out.route.target.value != "AUTO_RESOLVE", (
        f"{scenario.id}: real emergency → AUTO_RESOLVE!"
    )


@pytest.mark.asyncio
async def test_corpus_table_prints_and_all_pass(capsys):
    """Render the scenario → card → severity → route → pass/fail table."""
    rows = []
    passed = 0
    for scenario in TRIAGE_CORPUS:
        out = await _run(scenario)
        exp = scenario.expected
        ok = (
            out.severity.value == exp.severity
            and out.route.target.value == exp.route
            and out.route.handoff == exp.handoff
        )
        passed += ok
        rows.append(
            f"[{'PASS' if ok else 'FAIL'}] {scenario.id:30} "
            f"{out.card.incident_type.value:9} "
            f"sev={out.severity.value:8} conf={out.card.confidence:.2f} "
            f"-> {out.route.target.value:18} handoff={str(out.route.handoff):5} "
            f"junkp={out.junk.probability:.2f}"
        )

    header = f"\n=== Phase 3 triage corpus — {passed}/{len(TRIAGE_CORPUS)} passed ===\n"
    with capsys.disabled():
        print(header)
        print("\n".join(rows))
    assert passed == len(TRIAGE_CORPUS)


if __name__ == "__main__":  # pragma: no cover - manual run convenience

    async def _main() -> None:
        for scenario in TRIAGE_CORPUS:
            out = await _run(scenario)
            print(
                f"{scenario.id:30} sev={out.severity.value:8} "
                f"→ {out.route.target.value:18} handoff={out.route.handoff}"
            )

    asyncio.run(_main())
