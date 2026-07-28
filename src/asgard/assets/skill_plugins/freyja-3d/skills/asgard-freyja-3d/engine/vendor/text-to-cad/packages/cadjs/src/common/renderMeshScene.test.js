import assert from "node:assert/strict";
import test from "node:test";

import * as THREE from "three";

import {
  buildModel
} from "./cadScene.js";
import {
  modelOptionsForRenderJob,
  projectedVisibleGeometryFrame,
  renderJobContext,
  renderMeshJob
} from "./renderMeshScene.js";

function twoPartMeshData() {
  return {
    vertices: new Float32Array([
      0, 0, 0,
      1, 0, 0,
      0, 1, 0,
      2, 0, 0,
      3, 0, 0,
      2, 1, 0
    ]),
    indices: new Uint32Array([0, 1, 2, 3, 4, 5]),
    normals: new Float32Array([
      0, 0, 1,
      0, 0, 1,
      0, 0, 1,
      0, 0, 1,
      0, 0, 1,
      0, 0, 1
    ]),
    bounds: {
      min: [0, 0, 0],
      max: [3, 1, 0]
    },
    parts: [
      {
        id: "left",
        name: "Left",
        vertexOffset: 0,
        vertexCount: 3,
        triangleOffset: 0,
        triangleCount: 1,
        bounds: { min: [0, 0, 0], max: [1, 1, 0] }
      },
      {
        id: "right",
        name: "Right",
        vertexOffset: 3,
        vertexCount: 3,
        triangleOffset: 1,
        triangleCount: 1,
        bounds: { min: [2, 0, 0], max: [3, 1, 0] }
      }
    ]
  };
}

test("renderMeshJob list capture uses buildModel selection", async () => {
  const result = await renderMeshJob(twoPartMeshData(), {
    mode: "list",
    selection: {
      focus: ["right"]
    }
  });

  assert.equal(result.ok, true);
  assert.equal(result.mode, "list");
  assert.deepEqual(result.parts.map((part) => part.id), ["right"]);
  assert.deepEqual(result.bounds, {
    min: [2, 0, 0],
    max: [3, 1, 0]
  });
});

test("render view focus preserves full assembly while hide still filters", () => {
  const focusedContext = renderJobContext(twoPartMeshData(), {
    mode: "view",
    selection: {
      focus: ["right"]
    }
  });
  const focused = buildModel(
    THREE,
    twoPartMeshData(),
    modelOptionsForRenderJob(focusedContext, {
      mode: "view",
      selection: {
        focus: ["right"]
      }
    })
  );

  assert.deepEqual(focused.displayRecords.map((record) => record.partId), ["left", "right"]);
  assert.deepEqual(focused.bounds, {
    min: [0, 0, 0],
    max: [3, 1, 0]
  });
  focused.dispose();

  const hiddenContext = renderJobContext(twoPartMeshData(), {
    mode: "view",
    selection: {
      hide: ["left"]
    }
  });
  const hidden = buildModel(
    THREE,
    twoPartMeshData(),
    modelOptionsForRenderJob(hiddenContext, {
      mode: "view",
      selection: {
        hide: ["left"]
      }
    })
  );

  assert.deepEqual(hidden.displayRecords.map((record) => record.partId), ["right"]);
  assert.deepEqual(hidden.bounds, {
    min: [2, 0, 0],
    max: [3, 1, 0]
  });
  hidden.dispose();
});

test("projectedVisibleGeometryFrame fits actual vertices instead of sparse bounds", () => {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array([
    -1, -1, 0,
    1, -1, 0,
    -1, 1, 0,
    1, 1, 0
  ]), 3));
  const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial());
  mesh.updateWorldMatrix(true, false);
  const camera = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.01, 100);
  camera.position.set(0, 0, 10);
  camera.up.set(0, 1, 0);
  camera.lookAt(0, 0, 0);
  camera.updateMatrixWorld(true);

  const frame = projectedVisibleGeometryFrame([{ mesh }], camera);

  assert.equal(frame.count, 4);
  assert.equal(frame.centerX, 0);
  assert.equal(frame.centerY, 0);
  assert.equal(frame.spanX, 2);
  assert.equal(frame.spanY, 2);
});
