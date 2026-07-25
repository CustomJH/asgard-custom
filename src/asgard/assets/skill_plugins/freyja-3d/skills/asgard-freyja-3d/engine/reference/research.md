# 근거

이 엔진의 규칙은 취향이 아니라 다음 문헌·실측에서 나왔다. 규칙을 바꾸려면 여기부터 확인한다.

## 왜 되먹임 루프가 필수인가

- **CADCodeVerify** — *Generating CAD Code with Vision-Language Models for 3D Designs* (arXiv 2410.05340, ICLR 2025). 렌더 이미지에 대해 검증 질문을 생성·자답하게 하는 루프만으로 점군 거리 7.30% 감소, 컴파일 성공률 5.0%p 상승. 벤치마크 CADPrompt(자연어 200건 + 전문가 주석 코드) 동반. → `verify.md` 의 자기검증 절차.
- **3DCodeBench** — *Benchmarking Agentic Procedural 3D Modeling Via Code* (arXiv 2606.01057). 212 카테고리, 실패 대부분은 API 불일치에서 오고, **렌더에 성공한 결과조차 떠 있거나 끊어진 부품을 흔히 포함**한다. 고품질 되먹임을 주는 실행 환경과 다회차 정제가 성능을 올린다. → 렌더 확인을 배달 게이트로 올린 근거.
- **EvoCAD** (arXiv 2510.11631). VLM 기반 CAD 코드의 진화적 개선 — 여러 후보를 만들고 시각 평가로 선택하는 접근. → "같은 오류를 두 번 못 고치면 접근을 바꾼다".
- **BlenderGym** (arXiv 2504.01786). 245개 시작-목표 씬 쌍, 5개 편집 과제. 코드 기반 3D 재구성으로 VLM 시스템을 평가한 첫 벤치마크.

## 왜 먼저 묻는가

- **ProCAD** — *Clarify Before You Draw: Proactive Agents for Robust Text-to-CAD Generation* (arXiv 2602.03045). 명세를 먼저 감사하고 **필요할 때만** 질문하는 에이전트 + CAD 코딩 에이전트 조합. Chamfer 거리 79.9% 감소, 무효율 4.8% → 0.9%. 프런티어 모델 단독보다 우수. → `clarify.md` 전체.

## 왜 파라메트릭 코드인가

- **Text2CAD** (NeurIPS 2024) — DeepCAD 에 4단계 추상화의 자연어 주석 660K 를 붙인 첫 대규모 텍스트-CAD 데이터셋.
- **CAD-Recode** — 점군 → 실행 가능한 Python CAD 코드. 출력 코드가 **범용 LLM 이 읽고 편집할 수 있다**는 점이 핵심 — 결과물이 블랙박스 메시가 아니라 편집 가능한 프로그램이다.
- **cadrille** (ICLR 2026) — 멀티모달(점군·이미지·텍스트) + 온라인 RL. DeepCAD IoU 92.2, Fusion360 84.6, 무효율 0.0%. CadQuery Python 을 생성 타깃으로 삼는 계열의 도달점.
- **Embodied CAD** (arXiv 2606.31252) — 한 번에 전체 스크립트를 쓰는 대신 **계층화된 CAD 스킬에서 액션을 골라 커널에 실행시키고 솔버 피드백으로 수리·학습**. 산업용 CAD 는 문법적으로 유효한 코드가 아니라 커널이 받아들이는 형상을 요구한다. → 커널 진단(`cad_build.py`)을 루프에 넣은 근거.
- **BenchCAD**(arXiv 2605.10865), **Text2CAD-Bench**(arXiv 2605.18430) — 산업 표준 기준의 프로그램 CAD 벤치마크.
- **build123d vs CadQuery** — 같은 OpenCASCADE 커널, build123d 는 LLM 이 생성하기 쉬운 선형·상태 명시 구조. CadQuery 는 학습 데이터가 많아 첫 시도 성공률이 높다. → `lane-cad.md` 의 도구 선택표.
- **Resilient Modeling Strategy** — Gebhard, Solid Edge University 2013(학술 비교: Camba·Contero·Company, *Computer-Aided Design* 2016). 기준→뼈대→몸통→디테일→변형→**모서리 격리(필렛 맨 뒤)** 의 6그룹 순서와 상향 참조 규칙. 면 참조의 취약성(topology naming failure)과 완전 구속 원칙은 SolidWorks/Onshape 실무 문서(Engineers Rule, Onshape 포럼·쿼리 변수) 공통. 스켈레톤/마스터 모델은 PTC Creo 톱다운 설계 문서가 정본. → `lane-cad.md` 견고한 모델 문법.
- **FDM 끼워맞춤 등급** — 압입 −0.1~−0.2 / 밀착 0.15–0.25 / 활동 0.25–0.35 / 여유 0.4–0.6mm, 구멍 0.1–0.2mm 과소 출력(3dprintcalcs·X3D Studios·Creative3DP 실측 가이드, 2026-07 조사). → `dfm.md` 끼워맞춤 등급표.

## 진단 우선 워크플로

- **cad-khana** (Apache-2.0) — build123d 를 감싸 `diagnostics.json`(간섭·간극·살두께·오버행)을 내는 CLI. "스크립트의 assert 가 위반되면 빌드 실패가 된다 — 기하 제약은 희망이 아니라 강제된다." → `cad_build.py` 의 설계 원리(측정값을 루프에 넣기).

## 제조 규칙

- FDM/SLA 오버행 실용 한계 45°, FDM 최소 벽 0.8mm(권장 1.2), SLA 0.2~0.3mm 성형 가능하나 취급 고려 0.5mm 이상, FDM 끼워맞춤 간극 ±0.3mm — 다수 제조 서비스 설계 가이드의 공통 기준선.
- CNC: 최소 벽 금속 0.8mm/알루미늄 0.5mm, 비지지 벽 높이:두께 4:1 이하, 내부 코너 반경 ≥ 포켓 깊이의 1/3 또는 공구 반경의 1.0~1.3배, 포켓 깊이:폭 3:1(연장 공구 6:1).
- 값의 출처는 `engine/data/processes.json` 의 각 항목 주석과 `dfm.md` 본문. **벤더 데이터시트가 항상 우선한다.**

## 웹 3D 성능

- **Khronos Asset Creation Guidelines 2.0** (2025) — 좌표·단위·원점, GPU 친화적 삼각형, 인스턴싱, UV/텍셀 밀도/밉 블리드, 압축, 스킨·모프·애니메이션, PBR 확장을 한 배달 계약으로 묶는다. 규격 적합성은 공식 [glTF Validator](https://github.com/KhronosGroup/glTF-Validator), 용도별 예산·품질은 [glTF Asset Auditor](https://www.khronos.org/gltf/gltf-asset-auditor/)가 맡는다. → 자체 `scene_audit`를 규격 검사라고 부르지 않고, `specimens.md`에 목적별 표본 게이트를 분리한 근거. [가이드](https://github.com/KhronosGroup/3DC-Asset-Creation/blob/main/asset-creation-guidelines/RealtimeAssetCreationGuidelines.md)
- 드로우콜 모바일 <100(안전권 50 이하)·데스크톱 <500, 화면 삼각형 모바일 50K~150K·데스크톱 500K~1M, 텍스처 메모리 모바일 <50MB·데스크톱 <200MB, 모바일 GPU 메모리 150MB 이내. **"삼각형 수보다 드로우콜 수가 중요하다"** 는 것이 공통된 결론.
- WebGPU: three r171+ `three/webgpu` 에서 WebGL2 자동 폴백. `ShaderMaterial`/`RawShaderMaterial`/`onBeforeCompile` 은 WebGPU 경로 미지원 — TSL 노드 머티리얼로 포팅해야 한다. TSL 은 WGSL·GLSL 양쪽으로 컴파일된다. 이득은 드로우콜이 많은 씬과 컴퓨트에서 나온다.
- 압축: Draco 는 압축률, meshopt 는 디코드 속도. KTX2/Basis 는 GPU 상주 상태로 압축을 유지해 VRAM 을 크게 줄인다.
- 엔진 통합 표준(2026-07 조사): Epic FBX Static Mesh Pipeline(UCX 콜리전 명명·피벗=FBX 원점·1uu=1cm), Epic 자산 명명 규약, Unity Asset Transformer LOD 가이드(50/25/10%·3–4단), Khronos 3D-Formats-Guidelines(KTX 아티스트 가이드 — 노멀 UASTC·알베도 ETC1S), meshopt 는 모프·애니메이션까지 압축(gltf-transform·Needle 문서). → `lane-asset.md` 엔진 통합 표준.

## 생성형 3D

- 구조화 잠재(TRELLIS 계열)는 까다로운 위상에 강하고, Hunyuan3D 2.5 는 기하 해상도 1024·2.0 대비 정확도 +15%. 다만 **출력 50만~60만 삼각형은 게임·웹에 그대로 쓸 수 없어 리토폴로지가 전제**다. PartCrafter 계열은 부품 분해 출력을 준다.
- → `lane-asset.md`: 보여주기용이면 생성형, 만들거나 맞물릴 것이면 파라메트릭.

## 게임 아트 공정 (art 레인의 근거)

- **Blender glTF 2.0 exporter** — glTF는 삼각형으로 전달되고 UV·flat edge가 정점을 분리하며, tangent-space normal·ORM 패킹·스킨·모프·클립은 명시적인 내보내기 계약이다. UV·텍스처·스킨을 버리는 위치 전용 재작성기를 일반 glTF 최적화에 쓰면 안 된다. [공식 매뉴얼](https://docs.blender.org/manual/en/latest/addons/import_export/scene_gltf2.html)
- **Adobe Substance mesh maps** — high→low 베이크는 normal·world normal·ID·AO·curvature·position·thickness를 텍스처로 옮기는 공정이다. 이 엔진의 정점 AO/커버처는 진단·마스크 원료일 뿐 텍스처 베이크의 대체물이 아니다. [공식 문서](https://helpx.adobe.com/substance-3d-painter/using/baking.html)
- 파이프라인 9단계·수치 기준(히어로 무기 LOD0 15–40k tri, 텍셀 밀도 10.24/5.12 px/cm, LOD 단당 −50%, AAA 무기 1자루 12–19 영업일): Room 8 Studio·nastyrodent AAA 무기 파이프라인·Polycount 스레드·Leonardo Iezzi 텍셀 밀도 문서(2026-07 조사, 출처 URL 은 조사 보고 원문).
- 정점 베이크 = Substance "per vertex" 커버처 모드와 같은 급. AO 베이커 현업 기본값 64레이/180° 스프레드(Adobe Substance 문서). 커버처의 수학: Meyer et al. 2003 이산 미분기하 연산자(코탄젠트 라플라시안), 저비용 근사 = 부호 이면각.
- AO 의 기원: Zhukov et al., *An Ambient Light Illumination Model*(obscurances), EGSR 1998. 코사인 가중 반구 샘플링 = Malley's method (몬테카를로 중요도 샘플링).
- 마모 산수: Substance Edge Wear/Mask Builder 노드 = 커버처 임계 × 그런지 노이즈, AO 어두운 곳 배제 — lane-art.md 의 마스크 산수는 이 로직의 재구현이다.
- 노이즈: Perlin, *An Image Synthesizer*, SIGGRAPH 1985 + *Improving Noise*, 2002. 트라이플래너: GPU Gems 3 ch.1 (Geiss).
- PBR: Cook–Torrance 1982 → GGX(Trowbridge–Reitz 1975, Walter et al. 2007) → Schlick 프레넬 1994 → Burley 디즈니 BRDF 2012 → Karis, *Real Shading in UE4*, SIGGRAPH 2013(α=roughness², 금속/러프니스 워크플로의 사실상 표준). 보정 범위(알베도 30–240 sRGB, 비금속 F0≈0.04)는 Adobe PBR Validate 노드 기준.
- 톤맵: ACES — 실시간 근사는 Narkowicz 2016 해석적 피팅. 프레젠테이션 규약(3점 조명+HDRI+8–10초 턴테이블)은 Marmoset Toolbag 문서·마켓 관행.
- 자동화 지도(2024–26 논문): 텍스처 생성 TEXGen(SIGGRAPH Asia 2024)·Material Anything(CVPR 2025, arXiv:2411.15138)·Hunyuan3D-2.1(오픈 PBR 파이프라인), 아티스트 토폴로지 MeshAnything(ICLR 2025)·Meshtron(arXiv:2412.09548), 자동 UV PartUV·ArtUV·SeamGen — **스컬프트·리토포·아티스트 UV·텍스처 페인팅은 아직 연구 전선**이고, 파생 데이터(베이크·마스크·노이즈·ACES)는 결정론 수학이라 이 엔진이 무의존으로 구현한다. 이 판단이 art 레인의 경계선이다.

## 하드서피스·텍스처 문법 (lane-art 모델링·스택 절의 근거, 2026-07 조사)

- **하드 에지 ⇔ UV 심 1:1** — Polycount 정칙("모든 하드 에지는 UV 심, 역은 불필요") + Marmoset 베이크 문서(하드엣지 무분할 = 베이크 심). 90° 코너의 기하 근거: 표면 방향 270° 회전 vs 탄젠트 노멀맵 범위 180°. 안전 공식 "스무딩 그룹 = UV 섬"(Polycount). 케이지는 평균 노멀(명시 노멀 케이지는 하드엣지 경계에 틈).
- **워크플로 3가족** — 하이폴리 SubD+베이크(다수 스튜디오 표준), 미드폴리+면적 가중 노멀(Star Citizen·Alien: Isolation 실전 — 정점 수·노멀맵 압축 이점, Polycount wiki), 트림 시트(**Ultimate Trim**, Olsen/Insomniac, GDC 2015 — 표준 트림 배치 + 45° 노멀 베벨, 가로 타일링 무한 텍셀). 하이브리드가 현업 기본.
- **베벨 규율** — 폭 0 에지는 CG 티의 근원(스펙큘러 캐치 부재), 폭은 피처 크기 비례(자산 전체 균일 폭 = 초보 티, Novedge·Polycount 포트폴리오 리뷰), 게임 해상도는 2–3 세그먼트.
- **베이크·내보내기 전 수동 삼각화** — 베이커와 엔진의 자동 삼각화 불일치(Adobe Substance 베이커 공식 문서). ngon 은 정적 메시 평면 한정.
- **패딩** — 노멀맵 최소 8px, 밉 4단 16px, 셸 간격 = 패딩 2배(Polycount wiki: Edge padding).
- **텍셀 밀도 사다리** — 2.56(기준) / 5.12(3인칭·배경) / 10.24(FPS 히어로) / 20.48 px/cm(시네마틱 상한) = 256/512/1024/2048 px/m(Polycount 스레드 다수·Beyond Extent·StraySpark). lane-art 의 10.24/5.12 와 정합.
- **Substance 스택 규율** — 물리 지층 순서(바탕→변주→마모→그라임→이야기; 80.lv 실장 사례: Edge Rust balance 0.69·Dust Occlusion contrast 0.23), 제너레이터 70–80% + 손 20–30%("마스크를 수동으로 깨라" — Ayi Sanchez, Beyond Extent), 색 균형 75/20/5, 러프니스 변주가 재질을 판다. 마모는 커버처(볼록), 그라임은 AO(오목) — 뒤집히면 초보 티. 높이 채널은 HDR, 16비트 내보내기(Adobe).
- **알베도 검증 수치** — 비금속 30–240 sRGB(엄격 바닥 50), 금속 180–250 sRGB(Adobe PBR Validate 노드). → materials.json 프리셋 보정 기준.
- **3ds Max 생태계의 방법 증거** — Chamfer 모디파이어(가중 크리스·쿼드 코너·Inset=절차적 서포트 루프), Weighted Normals 모디파이어(챔퍼 0 세그먼트와 짝 = FWN 정본), Data Channel(커버처→정점색 절차 스택), TexTools 의 SG↔UV 상호 변환(하드엣지=심 규칙의 자동화). Max 스무딩 그룹 = Maya/Blender 하드엣지와 동일 기제(Polycount wiki).

## 룩뎁 (lookdev.md·look-floor 의 근거, 2026-07 조사)

- **비율** — 키:필 2:1 상업 / 3:1 표준 / 8:1 드라마(StudioBinder·Academy of Animated Art), 룩뎁 보정 리그 3:1–4:1 중립 HDRI(CG Lounge). 키 배치 15–45°/15–45°, 필 비대칭 반대편, 림은 윤곽이 설 때까지(Birn, 3dRender.com — "3점은 공식이 아니다"까지 포함).
- **KeyShot 관례** — 림>키>필의 "1,2,3 읽기", 핀은 위치가 아니라 **리플렉션으로 배치**(Set Highlight). HDRI 회전 = 키 리플렉션 배치(360 Render), 효율 기본 = HDRI + 그림자쪽 면광 하이브리드(Will Gibbons — HDRI 단독 그림자는 접지가 약함).
- **검증 트리오** — 18% 그레이 구(노출)·크롬 구(환경 방향)·맥베스 차트(색 파이프라인) (CAVE Academy·CG Lounge). EV100 = log2(N²/t × 100/ISO).
- **카메라** — 팩샷 85–100mm 상당·50mm 미만 금지(Packshot-Creator), 히어로 FOV 20–30° 반직교(Marmoset), 익스테리어 35mm/2m/−15°(Property Render), 3/4 뷰 +27% 관찰·대각 구도 +18% 유지(Property Render·Maverick Frame), 네거티브 스페이스 ≥60% 프리미엄(Blue Bend), 값 배분 2/3:1/3(80.lv 소품 워크플로).
- **접지** — 접촉 그림자 = 1순위 신호, 섀도 캐처·무한 사이클로라마(Corona 공식 문서), 스케일 혼란 = 지명된 리얼리즘 킬러(Rare Design Hive). 유리 = 브라이트 필드, 블랙 온 블랙 = 다크 필드(Advanced Illumination·ProPhoto Studio).
- **톤 2024–26** — Blender 4.0 기본 = AgX, three r160 AgXToneMapping 추가, ACES 2.0(OCIO 2.5 내장·Blender 5.0 탑재). AgX 는 하이라이트 탈포화(6색 문제 회피) — 채도는 변환 뒤 그레이딩(raw 워크플로, CG Cookie). 블룸 임계 1.0(Unity PostProcessing 공식 — 임계 하향 = 아마추어 헤일로). "포스트로 조명 결함 가리기"는 지명된 초보 패턴(다수).
- **턴테이블** — 288f/24fps/12초 per 360°(Blender Artists 합의), 마켓 규격 스틸 12–36장·이음매 루프(TurboSquid 공식). → lookdev.json 전체.

## 판정 프로토콜 (critique3d·look-floor 의 근거, 2026-07 조사)

- **VLM-as-3D-Judge 프로토콜** (arXiv 2606.20364 + 2606.18451). 노멀 맵 몽타주로 판정(뷰티 렌더는 지오메트리 결함을 가린다), A/B 위치 무작위화, 생성 모델과 다른 계열의 심판 — 보정 전 일치도 ~0.5 가 보정 후 0.83–1.0. → critique3d 의 격리 심판·정사영/하이라이트 시트 판정.
- **SEIG** (arXiv 2606.02580). 지오메트리→재질→구도→조명의 **단계 게이트**: 매 단계 렌더를 본 검증자가 진행/수정을 판정. 원샷 검증보다 전 지표 우수. → 조형이 무너진 산출물에 재질·조명 점수를 매기지 않는 순서 규칙.
- **Eval3D** (arXiv 2504.18509, CVPR 2025). 단일 점수 대신 파운데이션 모델 간 일치도(메시 노멀 vs 2D 노멀 추정기)로 국소 결함을 짚는다. **3DGen-Bench/Score** (arXiv 2503.21745) 는 인간 선호 정렬 자동 채점기, **MEt3R** (arXiv 2501.06336, CVPR 2025) 는 무참조 다시점 일관성 점수. → 채점표를 축으로 쪼갠 근거.
- **T23D-CompBench/Rank2Score** (arXiv 2509.23841) — 프롬프트 부합을 12 하위 항목으로 분해해야 사람 평가와 정렬. **P3D-Bench** (arXiv 2606.11152) — 프런티어 모델도 실루엣은 맞고 **부품 수·조립 연결**에서 실패. → 정확성 축의 항목별 대조, cad 간섭 검사 유지.
- 씬 배치: **SceneSmith** (arXiv 2602.09153, ICML 2026) 부품 충돌 <2%·물리 안정 ≥96% 를 수용 기준으로 실증. **LayoutVLM** (arXiv 2412.02193, CVPR 2025) — 좌표만 믿지 말고 선언 제약을 함께 내서 수치로 강제. → 씬 조립 시 간섭·접지 판정을 좌표 신뢰 대신 측정으로.
- 텍스처·마모: **Generative Detail Enhancement** (arXiv 2502.13994, SIGGRAPH 2025) — 마모·에이징은 셰이딩에 그리지 말고 SVBRDF 파라미터로 남게(역렌더 베이크). **LumiTex** (arXiv 2511.19437) — 알베도에 조명을 굽는 것이 대표 실패 모드; 조명 뒤집어 재렌더하면 잡힌다. → lane-art 마스크 산수·알베도 검증.
- LOD 지각 지표: **TGE** (arXiv 2512.01380, AAAI 2026) — 렌더 없이 텍스처드 메시를 직접 채점하는 유일한 신형 지표. 이 분야 문헌이 얇아 실루엣 편차·노멀 SSIM 휴리스틱을 병행한다.

## 내부 실측 (이 리포)

- 프레이야 3D 스킬 후보 6종 필드 테스트(2026-07-25): 동일 브리프로 전원 실구동, 콤보 4종(기본/Vue/React/정밀CAD) 확정. 상류 도구 3종에서 문서 드리프트·오탐(플랫백 오버행 오탐)·폐기 API 흔적 발견 → 이 엔진의 오버행 검사에서 **빌드 플레이트 접지면 제외**를 명시 규칙으로 넣은 직접적 근거.
- 엔진 2 벤치: 콘텐츠 우선 페인트·모션 후행 원칙 — 이 엔진의 motion 레인이 그대로 승계한다.
