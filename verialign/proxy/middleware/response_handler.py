from dataclasses import dataclass

from verialign.verification.engine import VerificationEngine
from verialign.verification.models import VerificationResult


@dataclass
class AugmentedResponse:
    data: dict
    verification: VerificationResult


class ResponseHandler:
    def __init__(
        self,
        verifier: VerificationEngine | None = None,
        structured_output: bool = False,
    ) -> None:
        self.verifier = verifier or VerificationEngine()
        self.structured_output = structured_output

    async def augment(
        self, upstream_response: dict, request_payload: dict
    ) -> AugmentedResponse:
        assistant_text = self._extract_assistant_text(upstream_response)
        context = request_payload.get("metadata", {}).get("context", [])
        verification = await self.verifier.verify(
            assistant_text, context, response_data=upstream_response
        )

        response = dict(upstream_response)
        v_dict = verification.to_dict()
        if self.structured_output:
            response["verification"] = v_dict
        else:
            response["verification"] = v_dict

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
            }
        }
