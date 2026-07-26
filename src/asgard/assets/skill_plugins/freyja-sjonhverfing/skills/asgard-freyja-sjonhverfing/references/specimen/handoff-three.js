// 경계 표본 — anime.js v4 의 three.js 어댑터로 씬 객체를 트윈하는 자리.
//
// 소유권이 여기서 갈린다.
//   · 이 스킬(Sjónhverfing) 이 소유하는 것: 트윈 계층 — 어떤 값이 어떤 곡선으로 언제 움직이는가.
//   · 엔진 3(asgard-freyja-3d) 이 소유하는 것: 씬 구성, 카메라 연출, 성능 예산, 자산,
//     자원 해제, 그리고 detect3d / scene_audit 판정.
//
// 캔버스를 여는 결정은 이 파일이 하지 않는다. L5 로 올라간다는 판단(depth-ladder.md)이
// 이미 내려진 뒤에 이 seam 이 쓰인다.

import * as THREE from "three";
import { animate, createTimeline, utils } from "animejs";
import "animejs/adapters/three"; // 부수 효과 임포트 — Object3D·Material·Color 를 대상으로 받게 한다

const reduced = matchMedia("(prefers-reduced-motion: reduce)");

export function mount(canvas) {
  /* ── 엔진 3 의 영역: 씬·카메라·렌더러 ────────────────────────────── */
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); // 예산: 3 이상은 모바일에서 무너진다
  renderer.toneMapping = THREE.ACESFilmicToneMapping;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
  camera.position.set(0, 0, 6);

  // 환경광이 재질을 만든다. PBR 머티리얼을 환경 없이 두면 전부 플라스틱으로 보인다.
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new THREE.Scene(), 0.04).texture;

  const geometry = new THREE.IcosahedronGeometry(1, 2);
  const material = new THREE.MeshStandardMaterial({ color: 0x8899aa, roughness: 0.4 });
  const mesh = new THREE.Mesh(geometry, material);
  scene.add(mesh, new THREE.DirectionalLight(0xffffff, 2.2), new THREE.AmbientLight(0xffffff, 0.4));

  const resize = () => {
    const { clientWidth: w, clientHeight: h } = canvas;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  addEventListener("resize", resize);
  resize();

  // 컨텍스트 손실 — 모바일 백그라운드 복귀나 드라이버 리셋에서 캔버스가 검게 남는다.
  const onLost = (event) => { event.preventDefault(); renderer.setAnimationLoop(null); };
  const onRestored = () => renderer.setAnimationLoop(() => renderer.render(scene, camera));
  canvas.addEventListener("webglcontextlost", onLost);
  canvas.addEventListener("webglcontextrestored", onRestored);

  /* ── 이 스킬의 영역: 트윈 계층 ────────────────────────────────────── */
  // 어댑터가 실려 있으므로 Object3D 를 그대로 넘긴다. 각도 필드는 도(degree)로 읽고 쓴다.
  // 저감 모션은 삭제가 아니라 대체다 — 최종 상태를 즉시 세우고 움직이지 않는다.
  if (reduced.matches) {
    utils.set(mesh, { rotateY: 24, scale: 1 });
  } else {
    createTimeline({ defaults: { ease: "out(3)" } })
      .add(mesh, { scale: [0, 1], duration: 620 })
      .add(mesh, { rotateY: 24, duration: 520 }, "-=320");
  }

  const focus = (degrees) => animate(mesh, { rotateY: degrees, duration: 480, ease: "out(3)" });

  /* ── 다시 엔진 3: 프레임 루프와 해제 ──────────────────────────────── */
  // anime.js 는 자체 메인 루프로 값을 갱신한다. 여기서는 그리기만 한다 —
  // 루프 안에서 새 객체를 만들지 않는다.
  renderer.setAnimationLoop(() => renderer.render(scene, camera));

  return {
    focus,
    dispose() {
      renderer.setAnimationLoop(null);
      removeEventListener("resize", resize);
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      pmrem.dispose();
      geometry.dispose();
      material.dispose();
      renderer.dispose();
    },
  };
}
