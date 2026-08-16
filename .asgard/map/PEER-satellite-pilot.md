<!-- asgard:project-map schema=3 -->
# Peer Map — satellite-development-helper

> Asgard managed orientation map. Regenerate with `asgard map update`; do not hand-edit this file.
> It is a navigation hint, not completion evidence: re-read every path used by a plan.

## Orientation

- Project root: `../satellite-pilot/`
- Languages by observed source files: TypeScript (24), JavaScript (16)
- Evidence scan: 117 files; 4 landmarks
- Declared work root of the session repository — paths below open as written from `./`.
- The relation graph (`asgard map impact` / `trace`) covers the session repository only.
- Source revision: source-stat-sha256:b4904d471b3d107ab107452a8fd6871f66359ea7500eb14557a4e392374c7135

## Landmarks

- `../satellite-pilot/README.md` — project overview and operating guide
- `../satellite-pilot/package.json` — Node.js project manifest
- `../satellite-pilot/scripts/` — automation scripts
- `../satellite-pilot/src/` — primary source area

## Documents

- `../satellite-pilot/AGENTS.md` — doc: satellite-pilot — Agent Guide · sections: Asgard — Identity (Worldview); Asgard — Canon (Common Laws); Asgard — Trinity Loop (Heimdall Orchestration); Asgard — Codebase Map (.asgard/map/); Asgard — Lagom (Minimalism Contract); Asgard — Bragi (Human Voice)
- `../satellite-pilot/DEVELOPMENT_PLAN.md` — doc: Satellite Development Helper - 개발 계획서 · sections: 📋 프로젝트 개요; 🏗️ 시스템 아키텍처; 📅 개발 로드맵; 🛠️ 기술 스펙; ⚠️ 리스크 관리; 📊 성공 지표 추적
- `../satellite-pilot/MANUAL.md` — doc: MANUAL · sections: API; Database; Naming
- `../satellite-pilot/README.md` — doc: 🛰️ Satellite Development Helper · sections: ✨ Features; 📥 Installation; 📖 Usage; 🏗️ Architecture; 💻 Development; 🤝 Contributing
- `../satellite-pilot/projectbrief.md` — doc: Satellite Development Helper - Project Brief · sections: Core Mission; Problem Statement; Solution; Success Metrics; Target Users; Core Value Proposition
- `../satellite-pilot/PRD/device-lab-prd.md` — doc: PRD — Device Lab (디바이스 랩) · sections: 1. 기능명 & 포지셔닝; 2. v1 범위; 3. 기기 목록 v1 (17항목 = 16기종, Z Fold5는 커버/메인 2항목); 4. UX; 5. 협의 결정 사항 (Resolved); 5.1 증보 (2026-07-21, 유저 요청)
- `../satellite-pilot/bridge/README.md` — doc: Satellite Bridge · sections: 실행; 테스트 (자동); 두 전송 경로 (스파이크 결과); 수동 페어링 테스트
- `../satellite-pilot/design_fix_doc/V2_DESIGN.md` — doc: V2_DESIGN · sections: Overview; Colors; Typography; Layout; Elevation & Depth; Shapes
- `../satellite-pilot/extension/README.md` — doc: 🛰️ Satellite Development Helper · sections: Features; Installation; Usage; File Structure; Technical Details; Development
- `../satellite-pilot/figma-plugin/README.md` — doc: Satellite Capture — Figma 플러그인 · sections: 동작 원리; 빌드; Figma에 로드 (수동 테스트); 검증 포인트 (Phase 0 스파이크)
- `../satellite-pilot/store-assets/permission-justifications.md` — doc: Chrome Web Store — Permission Justifications · sections: host_permissions: _<all_urls>_; _activeTab_; _scripting_; _storage_; _clipboardWrite_; _downloads_

## Public surfaces

- `../satellite-pilot/figma-plugin/src/figma-extractor.ts` — public surface: getFigmaNodeInfo
- `../satellite-pilot/src/background/device-lab.ts` — public surface: setDeviceLabRules; clearDeviceLabRules; initDeviceLab; captureVisibleTab; isDeviceLabSupported
- `../satellite-pilot/src/content/asset-extractor.ts` — public surface: extractCssUrls; spriteFragmentId; parseSrcset; resolveUrl; dedupeAssets
- `../satellite-pilot/src/shared/devices.ts` — public surface: DeviceCategory; FrameStyle; UaMode; DeviceSpec; getDevice
- `../satellite-pilot/src/background/figma-bridge.ts` — public surface: getLatestFigmaRef; getBridgeStatus; isBridgeEnabled; setFigmaRef; initFigmaBridge
- `../satellite-pilot/src/content/asset-image.ts` — public surface: AssetFormat; pickPrimaryAsset; formatMeta; assetBaseName; isAnimatedAsset
- `../satellite-pilot/src/shared/messages.ts` — public surface: FigmaRef; ExtensionMessage; ExtensionResponse
- `../satellite-pilot/src/content/asset-panel.ts` — public surface: collectPageAssets; closeAssetPanel; toggleAssetPanel
- `../satellite-pilot/src/shared/prompt-formatter.ts` — public surface: formatElementForClipboard
- `../satellite-pilot/src/content/color-utils.ts` — public surface: rgbToHex; hexToRgb; rgbToHsl; hslToRgb; rgbToHsv
- `../satellite-pilot/src/shared/storage.ts` — public surface: StorageManager
- `../satellite-pilot/src/content/extractor.ts` — public surface: getElementInfo; cleanupHTML
- `../satellite-pilot/src/shared/types.ts` — public surface: OutputFormat; SelectionMode; ColorProperty; ColorFormat; ColorChange
- `../satellite-pilot/src/content/framework-detect.ts` — public surface: detectFramework
- `../satellite-pilot/src/content/markdown-formatter.ts` — public surface: formatElementForMarkdown; collectAssets; formatAssetsForMarkdown
- `../satellite-pilot/src/content/selector.ts` — public surface: ElementSelector

## Navigation contract

- Read `PROJECT.md` first, then the matching human-authored area map if present.
- A `## Documents` row lists a document's own title and sections — open it before re-deriving what it already records.
- Verify target definitions and usages from source before planning or editing.
- Structural changes refresh this managed map before Verifier hashing; use `asgard map check` in CI.
