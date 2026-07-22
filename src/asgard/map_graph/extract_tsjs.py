"""TS/JS(+prisma) 증거 추출기 — 정규식 기반 보조 추출기.

정규식은 구문 증명이 아니다: 관용구가 강한 패턴(Express 라우트, Nest 데코레이터, prisma
model)만 confirmed 로 표시하고 나머지는 전부 candidate 로 남긴다. tree-sitter 승격 여지를
위해 인터페이스는 extract_python 과 동일하게 유지한다.
"""

from __future__ import annotations

import re

from .evidence import Evidence, safe_url

_ROUTE = re.compile(
    r"\b(app|router|server|fastify)\s*\.\s*(get|post|put|delete|patch|all)\s*\(\s*['\"`](/[^'\"`]*)", re.I
)
_ROUTE_BINDING = re.compile(
    r"\b(?:const|let|var)\s+(app|router|server|fastify)\s*=\s*(?:express\s*\(\s*\)|(?:express\s*\.\s*)?Router\s*\(\s*\)|fastify\s*\(\s*\))",
    re.I,
)
_NEST_ROUTE = re.compile(r"@(Get|Post|Put|Delete|Patch)\s*\(\s*(?:['\"`]([^'\"`)]*)['\"`])?\s*\)")
_API_CALL = re.compile(r"\b(?:fetch|axios(?:\s*\.\s*(?:get|post|put|delete|patch|request))?)\s*\(\s*['\"`]([^'\"`]+)")
_PRISMA_MODEL = re.compile(r"^\s*model\s+(\w+)\s*\{", re.M)
_DRIZZLE_TABLE = re.compile(r"\b(?:pgTable|mysqlTable|sqliteTable)\s*\(\s*['\"`](\w+)")
_JOB = re.compile(r"\bcron\s*\.\s*schedule\s*\(|\bnew\s+CronJob\s*\(|@Cron\s*\(")
_IMPORT = re.compile(r"(?:from\s+['\"]([^'\"]+)['\"]|require\s*\(\s*['\"]([^'\"]+)['\"])")
# 패키지 접두 → 서비스 라벨
_SERVICE_PACKAGES = (
    ("@anthropic-ai/", "anthropic"),
    ("@aws-sdk/", "aws"),
    ("@sendgrid/", "sendgrid"),
    ("@slack/", "slack"),
    ("@supabase/", "supabase"),
    ("aws-sdk", "aws"),
    ("firebase", "firebase"),
    ("ioredis", "redis"),
    ("kafkajs", "kafka"),
    ("amqplib", "rabbitmq"),
    ("openai", "openai"),
    ("redis", "redis"),
    ("stripe", "stripe"),
    ("twilio", "twilio"),
)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def extract_tsjs(path: str, source: str) -> list[Evidence]:
    evidence: list[Evidence] = []
    if path.endswith(".prisma"):
        for match in _PRISMA_MODEL.finditer(source):
            evidence.append(Evidence("model", match.group(1), path, _line_of(source, match.start()), "confirmed"))
        return evidence

    route_receivers = {match.group(1).casefold() for match in _ROUTE_BINDING.finditer(source)}
    for match in _ROUTE.finditer(source):
        receiver, method, route_path = match.group(1).casefold(), match.group(2).upper(), match.group(3)
        confidence = "confirmed" if receiver in route_receivers else "candidate"
        evidence.append(Evidence("route", f"{method} {route_path}", path, _line_of(source, match.start()), confidence))
    for match in _NEST_ROUTE.finditer(source):
        method, route_path = match.group(1).upper(), match.group(2) or ""
        name = f"{method} /{route_path.lstrip('/')}" if route_path else f"{method} ."
        evidence.append(Evidence("route", name, path, _line_of(source, match.start()), "confirmed", "nest"))
    for match in _API_CALL.finditer(source):
        target = match.group(1)
        confidence = "confirmed" if target.startswith(("http://", "https://")) else "candidate"
        evidence.append(Evidence("api_call", safe_url(target), path, _line_of(source, match.start()), confidence))
    for match in _DRIZZLE_TABLE.finditer(source):
        evidence.append(
            Evidence("model", match.group(1), path, _line_of(source, match.start()), "candidate", "drizzle")
        )
    for match in _JOB.finditer(source):
        evidence.append(Evidence("job", "cron", path, _line_of(source, match.start()), "candidate"))
    seen_services: set[str] = set()
    for match in _IMPORT.finditer(source):
        package = match.group(1) or match.group(2) or ""
        for prefix, label in _SERVICE_PACKAGES:
            exact = package == prefix.rstrip("/")
            scoped = prefix.endswith("/") and package.startswith(prefix)
            if (exact or scoped) and label not in seen_services:
                seen_services.add(label)
                evidence.append(
                    Evidence("external_service", label, path, _line_of(source, match.start()), "confirmed", package)
                )
    return evidence
