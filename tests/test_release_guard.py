#!/usr/bin/env python3
"""release-guard 자가 검증 — 외부 공개 부작용(publish/이미지 push/태그 push/deploy) 차단.

실행: uv run pytest tests/test_release_guard.py
"""

import json
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from asgard.hooks.release_guard import blocked_reason  # noqa: E402

_HOOK = os.path.join(os.path.dirname(__file__), "..", "src", "asgard", "hooks", "release_guard.py")


def _run(payload: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, _HOOK], input=payload, capture_output=True, text=True, timeout=10)


class TestBlocked(unittest.TestCase):
    def test_package_publish(self):
        for cmd in (
            "npm publish",
            "pnpm publish --access public",
            "yarn npm publish",
            "cargo publish",
            "uv publish",
            "poetry publish",
            "twine upload dist/*",
            "gem push pkg.gem",
            "dotnet nuget push pkg.nupkg",
            "helm push chart.tgz oci://registry",
            "./gradlew publishToMavenCentral",
            "mvn clean deploy",
        ):
            self.assertEqual(blocked_reason(cmd), "package publish", cmd)

    def test_image_push(self):
        for cmd in (
            "docker push ghcr.io/x/y:1.0",
            "podman push img",
            "docker compose push",
            "docker buildx build --push -t x .",
            "crane push image.tar registry/x",
        ):
            self.assertEqual(blocked_reason(cmd), "image push", cmd)

    def test_git_tag_push(self):
        for cmd in ("git push --tags", "git push origin refs/tags/v1.0.0", "git push --follow-tags origin main"):
            self.assertEqual(blocked_reason(cmd), "git tag push", cmd)

    def test_deploy(self):
        for cmd in (
            "kubectl apply -f deploy.yaml",
            "helm upgrade --install app ./chart",
            "terraform apply",
            "pulumi up",
            "flyctl deploy",
            "vercel --prod",
            "vercel",
            "firebase deploy",
            "wrangler deploy",
            "gcloud run deploy svc --image x",
            "kamal deploy",
        ):
            self.assertEqual(blocked_reason(cmd), "deploy", cmd)

    def test_chained_and_wrapped(self):
        self.assertIsNotNone(blocked_reason("npm run build && npm publish"))
        self.assertIsNotNone(blocked_reason("sudo docker push x"))
        self.assertIsNotNone(blocked_reason("NODE_ENV=production npm publish"))


class TestAllowed(unittest.TestCase):
    def test_local_flows_pass(self):
        for cmd in (
            "npm run build",
            "npm install",
            "npm pack",  # 로컬 아티팩트 생성 — 에이트리의 정당 스코프
            "docker build -t x .",
            "docker compose up -d",
            "docker pull nginx",
            "git push origin main",  # 브랜치 push 는 일상 흐름
            "git push -u origin feature/x",
            "terraform plan",
            "kubectl get pods",
            "kubectl describe deploy x",
            "helm template ./chart",
            "helm lint ./chart",
            "./gradlew publishToMavenLocal",  # 로컬 리포지토리 — 외부 아님
            "uv build",
            "cargo build --release",
            "vercel dev",
        ):
            self.assertIsNone(blocked_reason(cmd), cmd)

    def test_mentions_not_executions(self):
        # 인용·검색은 실행이 아니다 — 프로그램 위치를 세그먼트 선두로 한정한 이유
        for cmd in ('grep -rn "npm publish" docs/', "echo docker push is dangerous", "cat deploy.md"):
            self.assertIsNone(blocked_reason(cmd), cmd)


class TestProtocol(unittest.TestCase):
    def test_claude_codex_block_exit2(self):
        p = _run('{"tool_input":{"command":"npm publish"}}')
        self.assertEqual(p.returncode, 2)
        self.assertIn("release-guard", p.stderr)
        self.assertIn("Odin", p.stderr)

    def test_claude_codex_allow_exit0(self):
        self.assertEqual(_run('{"tool_input":{"command":"npm run build"}}').returncode, 0)

    def test_cursor_deny_json(self):
        p = _run('{"command":"docker push x"}')
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["permission"], "deny")

    def test_cursor_allow_json(self):
        p = _run('{"command":"docker build -t x ."}')
        self.assertEqual(json.loads(p.stdout)["permission"], "allow")

    def test_fail_open_on_garbage(self):
        self.assertEqual(_run("not-json").returncode, 0)


class TestWiring(unittest.TestCase):
    def test_scaffolded_everywhere(self):
        from asgard.commands.setup import plan_files

        files, _ = plan_files(cc=True, cursor=True, codex=True, root="/tmp/x")
        paths = [p for p, _ in files]
        for scope in (".claude", ".cursor", ".codex"):
            self.assertTrue(any(p.endswith(os.path.join(scope, "hooks", "release-guard.py")) for p in paths), scope)

    def test_settings_wire_release_guard(self):
        from asgard.templates.claude import cc_settings
        from asgard.templates.codex import codex_config
        from asgard.templates.cursor import cursor_hooks_json

        self.assertIn("release-guard.py", cc_settings())
        self.assertIn("release-guard.py", cursor_hooks_json())
        self.assertIn("release-guard.py", codex_config())

    def test_native_bash_blocks(self):
        from asgard.agent.tools import validate_bash_command

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertIsNotNone(validate_bash_command(root, "npm publish"))
        self.assertIsNone(validate_bash_command(root, "npm run build"))


if __name__ == "__main__":
    unittest.main()
