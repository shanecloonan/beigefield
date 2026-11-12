"""Evidence-heat regressions: known tokens stay non-hot; funded vault ranks by funds.

Defensive only. Network optional — live invariant suite can be injected.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eth_scanner.funnel.s0_s7 import FunnelConfig, FunnelContext, run_lane_a
from eth_scanner.heat import evidence_heat, funds_heat, should_promote_lane_b
from eth_scanner.known_safe import is_known_safe
from eth_scanner.types import FunctionIR, IRDocument, SourceArtifact, Target

LINK = "0x514910771af9ca656af840dff83e8264ecf986ca"
SAND = "0x3845badade8e6dff049820680d1f14bd3903a5d0"
HEX_ = "0x2b591e99afe9f32eaa6214f7b7629768c40eeb39"
FRXUSD = "0xcacd6fd266af91b8aed52accc382b4e165586e29"
# Curve.fi alUSDavUSD Liquidity Gauge Deposit
CURVE_GAUGE = "0x1270787da38849fc5f3148357f3b8f6e69ab3858"
SUSDE = "0x9d39a5de30e57443bff2a8307a4256c8797a3497"


def _art(name: str, content: str = "pragma solidity ^0.8.20;\ncontract T { function transfer(address,uint256) external returns (bool) { return true; } }") -> SourceArtifact:
    return SourceArtifact(
        kind="source",
        language="solidity",
        content=content,
        src_confidence="high",
        verified_match="exact",
        tool="test",
        contract_name=name,
    )


def _token_ir() -> IRDocument:
    return IRDocument(
        functions=[
            FunctionIR(
                name="transfer",
                visibility="external",
                line=2,
                fund_signals=[".transfer("],
                auth_heuristic="WEAK",
                is_value_mover=True,
                exposed=True,
                role="erc20-standard",
            ),
            FunctionIR(
                name="mint",
                visibility="external",
                line=3,
                fund_signals=["_mint("],
                auth_heuristic="PRESENT",
                auth_signals=["onlyOwner"],
                is_value_mover=True,
                exposed=True,
                role="custody",
            ),
        ],
        ir_confidence="high",
        src_confidence="high",
        language="solidity",
        lift_tool="test",
        contract_class="token",
        scope="demoted-token",
        scope_signals=["erc20-interface:4"],
    )


class KnownSafeTokens(unittest.TestCase):
    def test_curated_addresses_are_known_safe(self):
        for addr, name in (
            (LINK, "LinkToken"),
            (SAND, "SAND"),
            (HEX_, "HEX"),
            (FRXUSD, "FrxUSD"),
        ):
            ok, reasons = is_known_safe(address=addr, contract_name=name)
            self.assertTrue(ok, msg="%s %s %s" % (addr, name, reasons))

    def test_known_tokens_are_non_hot(self):
        cfg = FunnelConfig(skip_live_invariants=True, min_funds_usd=2_000.0)
        for addr, name in (
            (LINK, "LinkToken"),
            (SAND, "SAND"),
            (HEX_, "HEX"),
            (FRXUSD, "FrxUSD"),
            (CURVE_GAUGE, "LiquidityGaugeV6"),
        ):
            r = run_lane_a(FunnelContext(
                target=Target(address=addr, has_code=True, tvl_usd=1_000_000, funds_usd=1_000_000),
                artifact=_art(name),
                ir=_token_ir(),
                config=cfg,
            ))
            self.assertEqual(r.bucket, "lane-a-cool", msg=addr)
            self.assertNotEqual(r.bucket, "lane-b-queue", msg=addr)
            # Demoted / known-safe — heat is funds-only ranking, not pattern heat.
            self.assertLess(r.heat, 12)


class SusdeRanking(unittest.TestCase):
    def test_susde_ranks_by_funds_with_held_invariants(self):
        funds = 1_200_000_000.0
        inv = [
            {"id": "erc4626-solvency", "name": "convertToAssets <= totalAssets", "status": "held", "evidence": "ok"},
            {"id": "privileged-pause", "name": "pause reverts", "status": "held", "evidence": "reverted"},
        ]
        heat, bd = evidence_heat(funds_usd=funds, invariant_results=inv)
        promote, why = should_promote_lane_b(funds_usd=funds, invariant_results=inv)
        self.assertFalse(promote, why)
        self.assertGreaterEqual(funds_heat(funds), funds_heat(1_000_000))
        self.assertGreater(heat, 0)
        self.assertEqual(bd["invariants_failed"], 0)

        cfg = FunnelConfig(skip_live_invariants=True, min_funds_usd=2_000.0)
        r = run_lane_a(FunnelContext(
            target=Target(address=SUSDE, has_code=True, tvl_usd=funds, funds_usd=funds),
            artifact=_art("StakedUSDeV2", content=(
                "pragma solidity ^0.8.20;\n"
                "contract StakedUSDeV2 {\n"
                "  function totalAssets() external view returns (uint256) { return 1; }\n"
                "  function deposit(uint256,address) external returns (uint256) { return 1; }\n"
                "}\n"
            )),
            ir=IRDocument(
                functions=[
                    FunctionIR(
                        name="deposit",
                        visibility="external",
                        line=4,
                        fund_signals=[".transfer("],
                        auth_heuristic="WEAK",
                        is_value_mover=True,
                        exposed=True,
                        role="custody",
                    ),
                ],
                ir_confidence="high",
                src_confidence="high",
                language="solidity",
                lift_tool="test",
                contract_class="vault",
                scope="in-scope",
                scope_signals=["erc4626"],
            ),
            config=cfg,
            invariant_results=inv,
        ))
        self.assertEqual(r.bucket, "lane-a-cool")
        self.assertGreaterEqual(r.heat, funds_heat(1_000_000))


class HeatWeightsUnit(unittest.TestCase):
    def test_pattern_leads_do_not_affect_heat(self):
        a, _ = evidence_heat(funds_usd=10_000, invariant_results=[])
        b, _ = evidence_heat(
            funds_usd=10_000,
            invariant_results=[{"id": "x", "status": "held", "evidence": "ok"}],
        )
        self.assertEqual(a, b)

    def test_failed_invariant_adds_heat_and_promotes(self):
        inv = [{"id": "x", "status": "failed", "evidence": "broken"}]
        heat, bd = evidence_heat(funds_usd=50_000, invariant_results=inv)
        self.assertGreater(bd["invariants_failed"], 0)
        ok, _ = should_promote_lane_b(funds_usd=50_000, invariant_results=inv)
        self.assertTrue(ok)
        self.assertGreater(heat, funds_heat(50_000))


if __name__ == "__main__":
    unittest.main()
