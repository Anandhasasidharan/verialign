import asyncio
import logging
from dataclasses import dataclass, field

from verialign.verification.engine import VerificationEngine
from verialign.verification.models import VerificationResult
from verialign.verification.overlay import Overlay, PolicyAction

logger = logging.getLogger(__name__)


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
        timeout_seconds: float | None = None,
    ) -> None:
        self.verifier = verifier or VerificationEngine()
        self.structured_output = structured_output
        self.policy = policy if policy in self.VALID_POLICIES else "pass-through"
        self.block_threshold = block_threshold
        self.timeout_seconds = timeout_seconds

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
        try:
            async with asyncio.timeout(self.timeout_seconds):
                verification = await self._verify(upstream_response, request_payload)
            trust_score = verification.trust_score
            action: PolicyAction = "pass-through"
            if (
                not verification.incomplete
                and trust_score is not None
                and trust_score < self.block_threshold
            ):
                if self.policy == "block":
                    action = "block"
                elif self.policy == "warn":
                    action = "warn"
            overlay = Overlay.from_result(verification, action)
            overlay_payload = overlay.model_dump(mode="json")
        except Exception:
            logger.warning("chat_verification_unavailable")
            return self.unavailable(upstream_response, self.structured_output)

        response = dict(upstream_response)
        overlay_key = "data" if self.structured_output else "verification"
        response[overlay_key] = overlay_payload

        if overlay.policy_action == "block":
            return AugmentedResponse(
                data={
                    "error": {
                        "message": f"Response blocked by verification policy: trust_score {overlay.trust_score:.3f} below threshold {self.block_threshold:.3f}",
                        "type": "verification_blocked",
                        "status_code": 422,
                    },
                    overlay_key: overlay_payload,
                },
                verification=verification,
                status_code=422,
                headers={"X-VeriAlign-Blocked": "true"},
            )

        if overlay.policy_action == "warn":
            caveat = f"[VeriAlign warning: trust_score {overlay.trust_score:.3f} below threshold {self.block_threshold:.3f} — verification recommended] "
            choices = response.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                msg = choices[0].get("message", {})
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    response["choices"] = [
                        {**choices[0], "message": {**msg, "content": caveat + msg["content"]}},
                        *choices[1:],
                    ]
            return AugmentedResponse(
                data=response,
                verification=verification,
                headers={"X-VeriAlign-Warning": "true"},
            )

        return AugmentedResponse(data=response, verification=verification)

    @staticmethod
    def unavailable(upstream_response: dict, structured_output: bool) -> AugmentedResponse:
        result = VerificationResult([], [], [], incomplete=True)
        overlay_key = "data" if structured_output else "verification"
        return AugmentedResponse(
            {**upstream_response, overlay_key: Overlay.from_result(result).model_dump(mode="json")},
            result,
        )

    async def _verify(self, upstream_response: dict, request_payload: dict) -> VerificationResult:
        assistant_text = self._extract_assistant_text(upstream_response)
        context = (request_payload.get("metadata") or {}).get("context", [])
        tool_calls = self._extract_tool_calls(request_payload)
        try:
            return await self.verifier.verify(
                assistant_text,
                context,
                response_data=upstream_response,
                tool_calls=tool_calls,
            )
        except TypeError as exc:
            if "tool_calls" in str(exc):
                return await self.verifier.verify(
                    assistant_text,
                    context,
                    response_data=upstream_response,
                )
            raise

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
