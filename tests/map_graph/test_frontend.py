#!/usr/bin/env python3
"""프런트엔드 레인 — 페이지·컴포저블·서비스·스토어 소비 사슬.

실행: uv run pytest tests/map_graph
"""

import unittest

from map_graph.map_base import (
    Base,
)

_VUE_PAGE_FIXTURE = """<template>
  <div @click="axios.get('/template-noise')">x</div>
</template>

<script setup lang="ts">
const rows = await $fetch(`/api/alarms/${id}/detail`)
</script>
"""


_COMPOSABLE_FIXTURE = """
import { apiGet, apiPut } from '@/services/api/client'

export function useAlarms() {
  return apiGet<AlarmRow[]>('/alarms/active')
}

export const useAck = async () => {
  await apiPut(`/alarms/${id}/acknowledge`)
}
"""


_SERVICE_FIXTURE = """
import { apiGet } from '../api/client'

export const alarmService = {
  list() {
    return apiGet('/alarms/active')
  },
}

export async function fetchOne(id) {
  return apiGet(`/alarms/${id}`)
}
"""


_SERVICE_CONSUMER_FIXTURE = """
import { alarmService, fetchOne } from '@/services/alarm/alarmService'
import type { AlarmRow } from '@/services/alarm/types'
import { ghostService } from '@/services/nope/ghostService'
import { helper } from '@/utils/helper'

export function useAlarmFeed() {
  const rows = alarmService.list()
  const one = fetchOne(1)
  const ghost = ghostService.load()
  helper()
  return { rows, one, ghost }
}
"""


_CONSUMER_FIXTURE = """
<script setup lang="ts">
import { useAlarms } from '@/composables/useAlarms'
import { useAuthStore } from '@/stores/auth.store'

const { rows } = useAlarms()
const auth = useAuthStore()
const [open, setOpen] = useState(false)
const label = registry.useAlarms()
</script>

<template><AlarmTable :rows="rows" /></template>
"""


_STORE_FIXTURE = """
import { defineStore } from 'pinia'

export const useAuthStore = defineStore('auth', {
  actions: {
    async login() {
      await apiPost('/auth/login')
    },
  },
})

const cartSlice = createSlice({
  name: 'cart',
  initialState,
})
"""


class TestFrontendLane(Base):
    """프론트 레인 — 파일 기반 page·store·composable·래퍼 api_call, SFC 마스킹."""

    def kinds(self, path: str, source: str) -> dict:
        from asgard.map_graph.extract_tsjs import extract_tsjs

        out = {}
        for item in extract_tsjs(path, source):
            out.setdefault(item.kind, []).append(item)
        return out

    def test_page_routes_derived_from_file_conventions(self):
        cases = {
            "app/pages/(auth)/login.vue": ("/login", "nuxt"),
            "app/pages/index.vue": ("/", "nuxt"),
            "app/pages/alarms/[id].vue": ("/alarms/:id", "nuxt"),
            "app/pages/users/_uid.vue": ("/users/:uid", "nuxt"),
            "src/routes/blog/[slug]/+page.svelte": ("/blog/:slug", "sveltekit"),
            "web/app/dash/(admin)/page.tsx": ("/dash", "next"),
            "web/pages/users/[id].tsx": ("/users/:id", "next"),
        }
        for path, (route, framework) in cases.items():
            pages = self.kinds(path, "")["page"]
            self.assertEqual((pages[0].name, pages[0].detail, pages[0].confidence), (route, framework, "confirmed"))

    def test_non_page_paths_make_no_page_claim(self):
        for path in (
            "web/pages/api/users.tsx",  # Next API 라우트는 페이지가 아니다
            "web/pages/_app.tsx",
            "app/components/templates/pages/Hero.vue",  # 아토믹 pages 레벨
            "web/src/Button.vue",
            "src/routes/blog/Widget.svelte",
        ):
            self.assertNotIn("page", self.kinds(path, ""), path)

    def test_sfc_template_masked_and_script_line_numbers_preserved(self):
        found = self.kinds("app/pages/alarms/[id].vue", _VUE_PAGE_FIXTURE)
        calls = found["api_call"]
        self.assertEqual(
            [(e.name, e.confidence, e.detail) for e in calls], [("/api/alarms/{}/detail", "candidate", "$fetch")]
        )
        # 템플릿 줄의 axios는 마스킹되고, 스크립트 증거는 원본 줄 번호를 유지한다
        self.assertEqual(calls[0].line, 6)
        page = found["page"][0]
        self.assertEqual(page.scope_end, _VUE_PAGE_FIXTURE.count("\n") + 1)

    def test_wrapper_calls_and_composables_with_body_spans(self):
        found = self.kinds("app/composables/useAlarms.ts", _COMPOSABLE_FIXTURE)
        by_name = {e.name: e for e in found["api_call"]}
        self.assertEqual(by_name["/alarms/active"].detail, "apiGet")
        self.assertEqual(by_name["/alarms/{}/acknowledge"].detail, "apiPut")
        composables = {e.name: e for e in found["composable"]}
        self.assertEqual(set(composables), {"useAlarms", "useAck"})
        span = composables["useAlarms"]
        self.assertTrue(span.line <= by_name["/alarms/active"].line <= span.scope_end)

    def test_composables_only_claimed_in_convention_dirs(self):
        self.assertNotIn("composable", self.kinds("app/lib/useAlarms.ts", _COMPOSABLE_FIXTURE))

    def test_stores_pinia_and_redux_slice(self):
        found = self.kinds("app/stores/auth.store.ts", _STORE_FIXTURE)
        stores = {e.name: e for e in found["store"]}
        self.assertEqual(
            {(s.detail, s.confidence) for s in stores.values()}, {("pinia", "confirmed"), ("redux", "confirmed")}
        )
        # 스토어 본문 스팬이 액션의 api_call을 포함한다
        auth = stores["auth"]
        call = found["api_call"][0]
        self.assertTrue(auth.line <= call.line <= auth.scope_end)

    def test_dollar_fetch_not_double_counted(self):
        found = self.kinds("app/composables/useX.ts", "export function useX() { return $fetch('/x') }\n")
        self.assertEqual(len(found["api_call"]), 1)

    def test_hook_calls_emit_provisional_use_evidence(self):
        found = self.kinds("app/pages/alarms.vue", _CONSUMER_FIXTURE)
        uses = {e.name: e for e in found["composable"]}
        # 소비는 잠정 증거다 — 정체 확정은 그래프 빌드의 수렴이 맡으므로 이름은 원문 그대로다.
        self.assertEqual(set(uses), {"useAlarms", "useAuthStore", "useState"})
        self.assertEqual({(e.detail, e.confidence, e.scope_end) for e in uses.values()}, {("use", "candidate", 0)})

    def test_comments_are_not_consumption_evidence(self):
        source = "// wired via useGhost()\n/* usePhantom() */\nconst u = 'https://x/y' + useReal()\n"
        uses = {e.name for e in self.kinds("app/lib/a.ts", source).get("composable", [])}
        # 주석 속 산문·죽은 호출은 증거가 아니고, 문자열의 `//`는 주석이 아니다
        self.assertEqual(uses, {"useReal"})

    def test_declaration_line_is_not_self_consumption(self):
        found = self.kinds("app/composables/useAlarms.ts", _COMPOSABLE_FIXTURE)
        composables = {(e.name, e.detail) for e in found["composable"]}
        self.assertEqual(composables, {("useAlarms", ""), ("useAck", "")})
        # `^\s*`가 앞 개행을 삼켜도 선언 줄은 이름 토큰이 있는 줄이다
        decl = {e.name: e.line for e in found["composable"]}
        self.assertEqual(
            _COMPOSABLE_FIXTURE.splitlines()[decl["useAlarms"] - 1].strip().split("(")[0], "export function useAlarms"
        )

    def test_store_aliases_map_accessor_to_store_id(self):
        from asgard.map_graph.extract_tsjs import extract_store_aliases

        self.assertEqual(extract_store_aliases(_STORE_FIXTURE), [("useAuthStore", "auth")])
        self.assertEqual(extract_store_aliases("// const useDead = defineStore('dead')\n"), [])

    def test_service_declared_in_convention_dir_with_body_spans(self):
        found = self.kinds("app/services/alarm/alarmService.ts", _SERVICE_FIXTURE)
        services = {e.name: e for e in found["service"]}
        self.assertEqual(set(services), {"alarmService", "fetchOne"})
        # 네임스페이스 객체 스팬이 자기 메서드의 api_call을 포함한다
        obj, call = services["alarmService"], found["api_call"][0]
        self.assertTrue(obj.line <= call.line <= obj.scope_end)
        # 관례 밖 같은 소스는 서비스를 주장하지 않는다
        self.assertNotIn("service", self.kinds("app/lib/alarmService.ts", _SERVICE_FIXTURE))

    def test_constant_object_in_services_dir_is_not_a_service(self):
        source = (
            "export const DEFAULT_OPTIONS = {\n  retries: 3,\n  timeout: 1000,\n}\n\n"
            "export const tsService = {\n  list(p: Params = {}): Promise<Row[]> { return apiGet('/a') },\n}\n\n"
            "export const arrowService = {\n  fetch: async () => apiGet('/b'),\n}\n"
        )
        names = {e.name for e in self.kinds("app/services/x.ts", source)["service"]}
        # 호출 가능한 멤버가 근거다 — TS 반환 타입 표기와 화살표 값 둘 다 서비스로 선다
        self.assertEqual(names, {"tsService", "arrowService"})

    def test_service_consumption_proven_by_import_origin(self):
        found = self.kinds("app/composables/useAlarmFeed.ts", _SERVICE_CONSUMER_FIXTURE)
        uses = {e.name for e in found["service"]}
        # 임포트 경로가 `services/` 인 런타임 심볼의 *호출*만 소비로 읽는다 —
        # 타입 전용 임포트(AlarmRow)와 비-서비스 임포트(helper)는 제외된다.
        # ghostService는 여기서 잠정 통과하고, 선언이 없으므로 그래프 빌드에서 탈락한다.
        self.assertEqual(uses, {"alarmService", "fetchOne", "ghostService"})
        self.assertEqual({e.detail for e in found["service"]}, {"use"})

    def test_service_import_without_call_is_not_consumption(self):
        source = "import { alarmService } from '@/services/a'\nconst x = alarmService\n"
        self.assertNotIn("service", self.kinds("app/pages/p.vue", f"<script setup>\n{source}</script>\n"))

    def test_service_chain_reaches_route_in_scan(self):
        from asgard.map_graph import graph_state, scan_graph

        self.write("pyproject.toml", '[project]\nname = "fe"\n')
        self.write("app/services/alarm/alarmService.ts", _SERVICE_FIXTURE)
        self.write("app/composables/useAlarmFeed.ts", _SERVICE_CONSUMER_FIXTURE)
        self.write("app/pages/alarms.vue", "<script setup>\nconst f = useAlarmFeed()\n</script>\n")
        self.write("api/server.ts", "app.get('/alarms/active', h)\n")
        scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        edges = {(e["source"], e["target"], e["kind"]) for e in state["edges"]}
        # page → composable → service → api_call → route 전 구간
        self.assertIn(("page:/alarms", "composable:useAlarmFeed", "uses"), edges)
        self.assertIn(("composable:useAlarmFeed", "service:alarmService", "uses"), edges)
        self.assertIn(("service:alarmService", "api_call:/alarms/active", "calls"), edges)
        self.assertIn(("api_call:/alarms/active", "route:GET_/alarms/active", "calls"), edges)
        # 임포트가 출처를 증명해도 리포에 선언이 없으면 노드를 세우지 않는다
        self.assertNotIn("service:ghostService", {n["id"] for n in state["nodes"]})

    def test_page_flow_joins_inline_fetch_in_scan(self):
        from asgard.map_graph import graph_state, scan_graph

        self.write("pyproject.toml", '[project]\nname = "fe"\n')
        self.write("app/pages/alarms/[id].vue", _VUE_PAGE_FIXTURE)
        scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        edges = {(e["source"], e["target"], e["kind"]): e["confidence"] for e in state["edges"]}
        # 페이지가 파일 본문을 소유한다 — 인라인 $fetch가 페이지 플로우로 귀속 (근사 스팬 → candidate)
        # (api_call의 `{}`는 id 슬러그에서 `_`로 정규화된다)
        self.assertEqual(edges.get(("page:/alarms/:id", "api_call:/api/alarms/_/detail", "calls")), "candidate")

    def test_fe_logic_chain_edges_and_convergence_gate_in_scan(self):
        from asgard.map_graph import graph_state, scan_graph

        self.write("pyproject.toml", '[project]\nname = "fe"\n')
        self.write("app/composables/useAlarms.ts", _COMPOSABLE_FIXTURE)
        self.write("app/stores/auth.store.ts", _STORE_FIXTURE)
        self.write("app/pages/alarms.vue", _CONSUMER_FIXTURE)
        scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        edges = {(e["source"], e["target"], e["kind"]) for e in state["edges"]}
        # 화면 → 로직 → 상태 체인이 선다 (TS 스팬은 근사라 candidate)
        self.assertIn(("page:/alarms", "composable:useAlarms", "uses"), edges)
        # 접근자 `useAuthStore`는 별칭표로 `defineStore` id 노드에 수렴한다
        self.assertIn(("page:/alarms", "store:auth", "uses"), edges)
        kinds = {n["id"]: n["kind"] for n in state["nodes"]}
        # 리포에 선언이 없는 프레임워크 원시 훅과 수신자 메서드 호출은 노드를 세우지 않는다
        self.assertNotIn("composable:useState", kinds)
        self.assertNotIn("store:useAuthStore", kinds)
        # 소비 파일의 파일 엣지는 선언이 아니라 uses 다
        self.assertIn(("file:app/pages/alarms.vue", "composable:useAlarms", "uses"), edges)
        self.assertNotIn(("file:app/pages/alarms.vue", "composable:useAlarms", "declares"), edges)

    def test_ambiguous_store_accessor_is_not_resolved(self):
        from asgard.map_graph import graph_state, scan_graph

        self.write("pyproject.toml", '[project]\nname = "fe"\n')
        self.write("a/stores/x.ts", "export const useThing = defineStore('alpha', {})\n")
        self.write("b/stores/y.ts", "export const useThing = defineStore('beta', {})\n")
        self.write("app/pages/p.vue", "<script setup>\nconst t = useThing()\n</script>\n")
        scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        ids = {n["id"] for n in state["nodes"]}
        # 접근자가 두 스토어로 갈리면 정체가 증명되지 않는다 — 어느 쪽으로도 잇지 않는다
        self.assertEqual({i for i in ids if i.startswith("store:")}, {"store:alpha", "store:beta"})
        edges = {(e["source"], e["target"]) for e in state["edges"]}
        self.assertNotIn(("page:/p", "store:alpha"), edges)
        self.assertNotIn(("page:/p", "store:beta"), edges)
        limit = next(row for row in state["coverage"]["limits"] if row["code"] == "store_alias_ambiguous")
        self.assertEqual(limit["subject"], "useThing")
        self.assertEqual(limit["candidates"], ["alpha", "beta"])

    def test_component_declared_only_in_components_tree(self):
        decls = {
            "app/components/organisms/alarm/ActiveAlarmDataTable.vue": ("ActiveAlarmDataTable", "organisms/alarm"),
            "app/components/atoms/ui/button/index.vue": ("Button", "atoms/ui"),
            "web/components/data-table.tsx": ("DataTable", ""),
        }
        for path, (name, level) in decls.items():
            component = self.kinds(path, "")["component"][0]
            self.assertEqual((component.name, component.detail, component.confidence), (name, level, "confirmed"))
        for path in ("app/pages/alarms.vue", "app/layouts/default.vue"):
            self.assertNotIn("component", self.kinds(path, ""), path)

    def test_template_tags_consumed_builtins_and_script_generics_excluded(self):
        source = (
            "<template>\n  <NuxtLink to='/x'/>\n  <AlarmBadge/>\n  <alarm-chip/>\n  <AlarmBadge/>\n</template>\n"
            "<script setup lang='ts'>\nconst x = apiGet<AlarmRow[]>('/rows')\n</script>\n"
        )
        found = self.kinds("app/components/molecules/AlarmCard.vue", source)
        uses = {e.name: e for e in found["component"] if not e.scope_end}
        # 빌트인(NuxtLink)·스크립트 제네릭(AlarmRow) 제외, 케밥 태그는 Pascal 수렴, 중복 1회
        self.assertEqual(set(uses), {"AlarmBadge", "AlarmChip"})
        self.assertTrue(all(e.confidence == "candidate" and e.detail == "use" for e in uses.values()))
        # 자기 선언 태그는 소비로 계상하지 않는다
        self_use = self.kinds("app/components/molecules/AlarmCard.vue", "<template><AlarmCard/></template>")
        self.assertEqual([e for e in self_use["component"] if not e.scope_end], [])

    def test_composition_chain_page_to_atom_in_scan(self):
        from asgard.map_graph import graph_state, scan_graph

        self.write("pyproject.toml", '[project]\nname = "fe"\n')
        self.write("app/pages/alarms.vue", "<template><AlarmTable/></template>\n")
        self.write("app/components/organisms/AlarmTable.vue", "<template><BaseButton label='ack'/></template>\n")
        self.write("app/components/atoms/BaseButton.vue", "<template><button/></template>\n")
        scan_graph(self.root)
        state = graph_state(self.root)
        assert state is not None
        edges = {(e["source"], e["target"], e["kind"]): e["confidence"] for e in state["edges"]}
        # 합성 체인: page → organism → atom (태그 소비는 candidate)
        self.assertEqual(edges.get(("page:/alarms", "component:AlarmTable", "uses")), "candidate")
        self.assertEqual(edges.get(("component:AlarmTable", "component:BaseButton", "uses")), "candidate")
        # 파일 엣지: 선언은 declares, 소비는 uses
        self.assertEqual(
            edges.get(("file:app/components/atoms/BaseButton.vue", "component:BaseButton", "declares")), "confirmed"
        )
        self.assertEqual(edges.get(("file:app/pages/alarms.vue", "component:AlarmTable", "uses")), "confirmed")


if __name__ == "__main__":
    unittest.main(verbosity=1)
