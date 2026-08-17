#!/usr/bin/env python3
"""관계 그래프 시험 공용 하네스 — 임시 워킹트리 하나와 여러 모듈이 함께 쓰는 소스 픽스처.

여기 있는 픽스처는 **둘 이상의 시험 모듈이 쓰는 것만**이다. 한 클래스만 쓰는 픽스처는
그 클래스가 있는 파일에 함께 산다. 시험 본문은 주제별 `test_*.py` 에 있다.
실행: uv run pytest tests/map_graph
"""

import os
import tempfile
import unittest

_PY_FIXTURE = """
import httpx
import sqlite3
import stripe
from celery import shared_task
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class User(BaseModel):
    name: str


@router.get("/users")
def list_users():
    return httpx.get("https://api.stripe.com/v1/charges")


@router.post("/users")
def create_user():
    connection = sqlite3.connect("app.db")
    connection.execute("INSERT INTO users VALUES (?)", ("a",))


@shared_task
def nightly_sync():
    pass
"""

_TS_FIXTURE = """
import Stripe from 'stripe';
const app = express();
app.get('/health', handler);
app.post('/orders', handler);
fetch('https://api.example.com/v1/items');
axios.get('/internal/items');
"""

_PRISMA_FIXTURE = """
model Order {
  id Int @id
}
"""

_JAVA_CONTROLLER = """
package com.acme.api;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 문서 주석의 @GetMapping("/ghost") 은 증거가 아니다. */
@RestController
@RequestMapping("/api/v1/orders")
public class OrderController {
    @GetMapping("/list")
    public String list() { return "ok"; }

    @PostMapping
    public String create() { return "ok"; }
}
"""

_JAVA_LISTENER = """
package com.acme.stream;

import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

@Component
public class FrameListener {
    private final KafkaTemplate<String, String> kafkaTemplate;

    @KafkaListener(topics = "${acme.kafka.in}", groupId = "${acme.group}")
    public void onFrame(String record) { }

    @KafkaListener(topics = {"audit.raw"})
    public void onAudit(String record) { kafkaTemplate.send(topicVar, record); }

    public void emit() { kafkaTemplate.send("billing.raw", "x"); }
}
"""

_MAPPER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE mapper PUBLIC "-//mybatis.org//DTD Mapper 3.0//EN" "http://mybatis.org/dtd/mybatis-3-mapper.dtd">
<mapper namespace="com.acme.store.MeterMapper">
    <select id="findMeter" resultType="map">
        SELECT * FROM TCFG_METER WHERE mid = #{mid}
    </select>
    <update id="mergeMeter">
        MERGE INTO TCFG_METER USING dual ON (mid = #{mid})
        WHEN MATCHED THEN UPDATE SET kind = #{kind}
    </update>
</mapper>
"""

_APPLICATION_YML = """
acme:
  kafka:
    in: ${ACME_TOPIC_IN:frame.raw}
    ambiguous: one
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        from asgard import ui

        ui.set_quiet(False)
        self.tmp.cleanup()

    def write(self, rel: str, body: str = "") -> None:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write(body)

    def seed(self) -> None:
        self.write("pyproject.toml", '[project]\nname = "graphed"\n')
        self.write("src/app/api.py", _PY_FIXTURE)
        self.write("web/server.ts", _TS_FIXTURE)
        self.write("web/schema.prisma", _PRISMA_FIXTURE)
        self.write("tests/test_api.py", "import httpx\n")  # 테스트 파일은 스캔 제외
