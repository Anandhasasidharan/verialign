from dataclasses import dataclass, field

from verialign.verification.engine import VerificationEngine
from verialign.verification.models import VerificationResult


@dataclass
class AugmentedResponse:
    data: dict
    verification: VerificationResult
    status_code: int = 200
    headers: dict = field(default_factory=dict)


class ResponseHandler:
    VALID_POLICIES = {"pass-through", "warn", "block"}  # noqa: RUF012

    def __init__(
        self,
        verifier: VerificationEngine | None = None,
        structured_output: bool = False,
        policy: str = "pass-through",
        block_threshold: float = 0.5,
    ) -> None:
        self.verifier = verifier or VerificationEngine()
        self.structured_output = structured_output
        self.policy = policy if policy in self.VALID_POLICIES else "pass-through"
        self.block_threshold = block_threshold

    def _extract_tool_calls(self, request_payload: dict) -> list[dict] | None:
        # Prefer explicit metadata.tool_calls / tool_results
        meta = (
            request_payload.get("metadata", {})
            if isinstance(request_payload.get("metadata"), dict)
            else {}
        )
        for key in ("tool_calls", "tool_results", "tool_call_records"):
            if isinstance(meta.get(key), list) and meta.get(key):
                return meta.get(key)
            if isinstance(meta.get(key), dict):
                return [meta.get(key)]
        if isinstance(request_payload.get("tool_calls"), list) and request_payload.get(
            "tool_calls",
        ):
            return request_payload["tool_calls"]
        # Fallback: messages with role == "tool" or tool_calls inside assistant messages
        messages = request_payload.get("messages", [])
        tool_msgs = []
        if isinstance(messages, list):
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") == "tool":
                    tool_msgs.append(
                        {
                            "name": msg.get("name", "tool"),
                            "arguments": {},
                            "result": msg.get("content", ""),
                        },
                    )
                # OpenAI tool_calls shape in assistant messages
                if isinstance(msg.get("tool_calls"), list):
                    for tc in msg["tool_calls"]:
                        if isinstance(tc, dict):
                            func = (
                                tc.get("function", {})
                                if isinstance(tc.get("function"), dict)
                                else {}
                            )
                            tool_msgs.append(
                                {
                                    "name": func.get("name", tc.get("name", "")),
                                    "arguments": func.get("arguments", {}),
                                    "result": tc.get("result", ""),
                                },
                            )
        return tool_msgs or None

    async def augment(
        self,
        upstream_response: dict,
        request_payload: dict,
    ) -> AugmentedResponse:
        assistant_text = self._extract_assistant_text(upstream_response)
        context = request_payload.get("metadata", {}).get("context", [])
        tool_calls = self._extract_tool_calls(request_payload)
        try:
            verification = await self.verifier.verify(
                assistant_text,
                context,
                response_data=upstream_response,
                tool_calls=tool_calls,
            )
        except TypeError as exc:
            if "tool_calls" in str(exc):
                verification = await self.verifier.verify(
                    assistant_text,
                    context,
                    response_data=upstream_response,
                )
            else:
                raise

        response = dict(upstream_response)
        v_dict = verification.to_dict()

        # Phase 0 fix: structured_output branches were identical. Now they differ:
        # - structured_output=True: nest verification under `data` key to avoid
        #   polluting the top-level JSON object that a structured-output client
        #   expects to be schema-constrained.
        # - otherwise: top-level `verification` (inline-verification headline feature)
        if self.structured_output:
            response["data"] = v_dict
        else:
            response["verification"] = v_dict

        # Policy handling (Phase 2)
        trust_score = verification.trust_score

        # Only apply policy when trust_score is available
        should_evaluate = trust_score is not None

        if self.policy == "block" and should_evaluate and trust_score < self.block_threshold:
            blocked = {
                "error": {
                    "message": f"Response blocked by verification policy: trust_score {trust_score:.3f} below threshold {self.block_threshold:.3f}",
                    "type": "verification_blocked",
                    "status_code": 422,
                },
                "verification": v_dict,
            }
            # Preserve structured nesting if requested
            if self.structured_output:
                blocked = {"error": blocked["error"], "data": v_dict}
            return AugmentedResponse(
                data=blocked,
                verification=verification,
                status_code=422,
                headers={"X-VeriAlign-Blocked": "true"},
            )

        if self.policy == "warn" and should_evaluate and trust_score < self.block_threshold:
            # Inject visible caveat into content and set warning header
            caveat = f"[VeriAlign warning: trust_score {trust_score:.3f} below threshold {self.block_threshold:.3f} — verification recommended] "
            choices = response.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                msg = choices[0].get("message", {})
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    response["choices"] = [dict(c) for c in choices]
                    response["choices"][0] = dict(choices[0])
                    response["choices"][0]["message"] = dict(msg)
                    response["choices"][0]["message"]["content"] = caveat + msg["content"]
            return AugmentedResponse(
                data=response,
                verification=verification,
                status_code=200,
                headers={"X-VeriAlign-Warning": "true"},
            )

        return AugmentedResponse(data=response, verification=verification)

    def _extract_assistant_text(self, response: dict) -> str:
        choices = response.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content")
        return content if isinstance(content, str) else ""

    def build_error_response(self, error: Exception, status_code: int = 500) -> dict:
        return {
            "error": {
                "message": str(error),
                "type": type(error).__name__,
                "status_code": status_code,
            },
        }
