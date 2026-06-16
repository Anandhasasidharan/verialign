from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Any
from sqlalchemy import func, and_
from sqlalchemy.orm import Session

from verialign.storage.models import Trace, Claim, Contradiction


class MetricsStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_overview(self, days: int = 7) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        total_requests = (
            self.session.query(func.count(Trace.id))
            .filter(Trace.created_at >= cutoff)
            .scalar()
            or 0
        )

        total_claims = (
            self.session.query(func.count(Claim.id))
            .join(Trace)
            .filter(Trace.created_at >= cutoff)
            .scalar()
            or 0
        )

        status_counts = defaultdict(int)
        for status, count in (
            self.session.query(Claim.status, func.count(Claim.id))
            .join(Trace)
            .filter(Trace.created_at >= cutoff)
            .group_by(Claim.status)
            .all()
        ):
            status_counts[status] = count

        contradiction_count = (
            self.session.query(func.count(Contradiction.id))
            .join(Trace)
            .filter(Trace.created_at >= cutoff)
            .scalar()
            or 0
        )

        model_counts = defaultdict(int)
        for model, count in (
            self.session.query(Trace.model, func.count(Trace.id))
            .filter(Trace.created_at >= cutoff)
            .group_by(Trace.model)
            .all()
        ):
            model_counts[model] = count

        avg_confidence = (
            self.session.query(func.avg(Claim.confidence))
            .join(Trace)
            .filter(Trace.created_at >= cutoff)
            .scalar()
            or 0.0
        )

        return {
            "period_days": days,
            "total_requests": total_requests,
            "total_claims": total_claims,
            "claims_by_status": dict(status_counts),
            "contradictions_detected": contradiction_count,
            "requests_by_model": dict(model_counts),
            "average_confidence": round(float(avg_confidence), 3),
        }

    def get_per_model_metrics(self, days: int = 30) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        results = []
        for model in (
            self.session.query(Trace.model)
            .filter(Trace.created_at >= cutoff)
            .distinct()
            .all()
        ):
            model_name = model[0]
            model_traces = (
                self.session.query(Trace)
                .filter(and_(Trace.model == model_name, Trace.created_at >= cutoff))
                .all()
            )

            trace_ids = [t.id for t in model_traces]
            if not trace_ids:
                continue

            claims = (
                self.session.query(Claim).filter(Claim.trace_id.in_(trace_ids)).all()
            )
            contradictions = (
                self.session.query(Contradiction)
                .filter(Contradiction.trace_id.in_(trace_ids))
                .all()
            )

            status_counts = defaultdict(int)
            confidence_sum = 0.0
            for claim in claims:
                status_counts[claim.status] += 1
                confidence_sum += claim.confidence

            avg_conf = confidence_sum / len(claims) if claims else 0.0

            results.append(
                {
                    "model": model_name,
                    "total_requests": len(model_traces),
                    "total_claims": len(claims),
                    "claims_by_status": dict(status_counts),
                    "contradictions": len(contradictions),
                    "average_confidence": round(avg_conf, 3),
                }
            )

        return results

    def get_per_task_metrics(self, days: int = 30) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        traces = self.session.query(Trace).filter(Trace.created_at >= cutoff).all()

        task_stats: dict[str, dict] = defaultdict(
            lambda: {
                "requests": 0,
                "claims": 0,
                "supported": 0,
                "unsupported": 0,
                "unclear": 0,
            }
        )

        for trace in traces:
            task = self._classify_task(trace.request_json)
            task_stats[task]["requests"] += 1

            claims = self.session.query(Claim).filter(Claim.trace_id == trace.id).all()
            for claim in claims:
                task_stats[task]["claims"] += 1
                task_stats[task][claim.status] = (
                    task_stats[task].get(claim.status, 0) + 1
                )

        results = []
        for task, stats in task_stats.items():
            results.append(
                {
                    "task": task,
                    "requests": stats["requests"],
                    "total_claims": stats["claims"],
                    "supported": stats.get("supported", 0),
                    "unsupported": stats.get("unsupported", 0),
                    "unclear": stats.get("unclear", 0),
                    "partially_supported": stats.get("partially_supported", 0),
                }
            )

        return results

    def get_drift_metrics(self, days: int = 30) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        daily_stats = defaultdict(
            lambda: {"requests": 0, "claims": 0, "supported": 0, "avg_confidence": 0.0}
        )

        traces = self.session.query(Trace).filter(Trace.created_at >= cutoff).all()

        for trace in traces:
            day_key = trace.created_at.date().isoformat()
            daily_stats[day_key]["requests"] += 1

            claims = self.session.query(Claim).filter(Claim.trace_id == trace.id).all()
            for claim in claims:
                daily_stats[day_key]["claims"] += 1
                daily_stats[day_key]["avg_confidence"] += claim.confidence
                if claim.status == "supported":
                    daily_stats[day_key]["supported"] += 1

        results = []
        for day in sorted(daily_stats.keys()):
            stats = daily_stats[day]
            avg_conf = (
                stats["avg_confidence"] / stats["claims"]
                if stats["claims"] > 0
                else 0.0
            )
            results.append(
                {
                    "date": day,
                    "requests": stats["requests"],
                    "total_claims": stats["claims"],
                    "supported_claims": stats["supported"],
                    "average_confidence": round(avg_conf, 3),
                }
            )

        return results

    def get_recent_contradictions(self, limit: int = 50) -> list[dict[str, Any]]:
        contradictions = (
            self.session.query(Contradiction)
            .join(Trace)
            .order_by(Trace.created_at.desc())
            .limit(limit)
            .all()
        )

        results = []
        for c in contradictions:
            trace = self.session.query(Trace).filter(Trace.id == c.trace_id).first()
            results.append(
                {
                    "id": c.id,
                    "trace_id": c.trace_id,
                    "model": trace.model if trace else "unknown",
                    "created_at": trace.created_at.isoformat() if trace else None,
                    "claim_a": c.claim_a,
                    "claim_b": c.claim_b,
                    "type": c.type,
                    "confidence": c.confidence,
                }
            )

        return results

    def _classify_task(self, request_json: dict) -> str:
        messages = request_json.get("messages", [])
        if not messages:
            return "unknown"

        user_content = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_content = str(msg.get("content", "")).lower()
                break

        keywords = {
            "coding": [
                "code",
                "function",
                "class",
                "api",
                "bug",
                "debug",
                "implement",
                "refactor",
                "python",
                "javascript",
                "sql",
            ],
            "writing": [
                "write",
                "essay",
                "article",
                "blog",
                "email",
                "story",
                "creative",
                "copy",
                "content",
            ],
            "analysis": [
                "analyze",
                "compare",
                "evaluate",
                "assess",
                "review",
                "critique",
                "examine",
            ],
            "question_answering": [
                "what",
                "how",
                "why",
                "when",
                "where",
                "who",
                "explain",
                "define",
                "describe",
            ],
            "summarization": ["summarize", "summary", "tldr", "brief", "condense"],
            "translation": ["translate", "translation", "language"],
        }

        for task, kws in keywords.items():
            if any(kw in user_content for kw in kws):
                return task

        return "general"
