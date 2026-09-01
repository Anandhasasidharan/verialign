import re
import json

_NUMBER = re.compile(r"\$?\s*(\d+(?:,\d{3})*(?:\.\d+)?)")
_TOOL_HINT = re.compile(
    r"\b(refund|payment|transfer|order|amount|processed|tool)\b", re.IGNORECASE
)


class ToolGrounder:
    """Ground claims about tool results against actual tool call records.

    This is the shared primitive between VeriAlign and AgentGuard/AgentOps —
    don't build it twice. Accepts tool call records as carried in
    ``metadata.tool_calls`` or parsed from ``messages`` with role=tool.
    """

    def normalize_tool_calls(self, raw) -> list[dict]:
        if not raw:
            return []
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        normalized: list[dict] = []
        for item in raw:
            if isinstance(item, dict):
                name = (
                    item.get("name") or item.get("tool") or item.get("function") or ""
                )
                args = item.get("arguments") or item.get("args") or {}
                result = (
                    item.get("result")
                    or item.get("output")
                    or item.get("content")
                    or ""
                )
                # also handle OpenAI tool_calls shape: {"function":{"name":..., "arguments":...}}
                if not name and isinstance(item.get("function"), dict):
                    name = item["function"].get("name", "")
                    args = item["function"].get("arguments", args)
                normalized.append(
                    {"name": str(name), "arguments": args, "result": result}
                )
        return normalized

    def ground(
        self, claim: str, tool_calls: list[dict]
    ) -> tuple[str | None, float, str | None]:
        """Returns (status, confidence, reason) if tool grounding applies, else (None, 0, None)."""
        if not tool_calls:
            return None, 0.0, None

        # Only apply if claim looks tool-relevant (mentions tool-ish words or dollar amounts)
        claim_has_hint = bool(
            _TOOL_HINT.search(claim) or "$" in claim or _NUMBER.search(claim)
        )
        if not claim_has_hint:
            return None, 0.0, None

        claim_numbers = self._extract_numbers(claim)

        for tc in tool_calls:
            result_str = (
                json.dumps(tc.get("result"))
                if not isinstance(tc.get("result"), str)
                else str(tc.get("result"))
            )
            args_str = (
                json.dumps(tc.get("arguments"))
                if not isinstance(tc.get("arguments"), str)
                else str(tc.get("arguments"))
            )
            combined = result_str + " " + args_str + " " + str(tc.get("name", ""))
            tool_numbers = self._extract_numbers(combined)

            # Numeric contradiction: claim says $50 but tool says 45
            if claim_numbers and tool_numbers:
                # If any claim number not present in tool numbers and claim explicitly about amount, flag
                for cn in claim_numbers:
                    if cn not in tool_numbers:
                        # Check if claim and tool share same tool name context
                        if tc.get("name") and tc["name"].lower() in claim.lower():
                            return (
                                "unsupported",
                                0.85,
                                f"claim amount {cn} != tool {tc['name']} result {tool_numbers}",
                            )
                        # Generic amount mismatch
                        if len(tool_numbers) == 1 and len(claim_numbers) == 1:
                            return (
                                "unsupported",
                                0.85,
                                f"amount mismatch claim {cn} vs tool {tool_numbers[0]}",
                            )
                        # If claim number clearly numeric and tool has different numeric, unclear
                        return (
                            "unsupported",
                            0.75,
                            f"numeric mismatch {cn} vs {tool_numbers}",
                        )

            # Textual contradiction: result says failed but claim says processed, etc.
            result_lower = result_str.lower()
            claim_lower = claim.lower()
            if "processed" in claim_lower and (
                "failed" in result_lower or "error" in result_lower
            ):
                return (
                    "unsupported",
                    0.8,
                    "status mismatch: claim says processed but tool result indicates failure",
                )
            if "refund" in claim_lower and tc.get("name") == "process_refund":
                # If claim says refund for X but args amount differs, already handled; else check status
                if "processed" in claim_lower and "processed" not in result_lower:
                    return "unclear", 0.6, "refund status not confirmed in tool output"

        return None, 0.0, None

    def _extract_numbers(self, text: str) -> list[str]:
        nums = []
        for m in _NUMBER.finditer(text):
            raw = m.group(1).replace(",", "")
            # Normalize to no-trailing-zero form
            try:
                if "." in raw:
                    v = float(raw)
                    # keep as int string if integer
                    if v.is_integer():
                        raw = str(int(v))
                    else:
                        raw = str(v)
                else:
                    raw = str(int(float(raw)))
            except Exception:
                pass
            nums.append(raw)
        return nums
