import assert from "node:assert/strict";
import test from "node:test";
import * as THREE from "three";

import {
  applyExplodedViewProgress,
  clearExplodedViewRecords,
  createExplodedViewRecordStates,
  easeExplodedViewProgress,
  explodedViewBoundsFromStates,
  explodedViewGroupKey,
  explodedViewStateTranslationAtProgress
} from "./explodedView.js";

function record(partId, center, bounds) {
  return {
    partId,
    mesh: new THREE.Object3D(),
    partCenter: new THREE.Vector3(...center),
    partBounds: bounds
  };
}

test("exploded view groups first-level assembly components by default", () => {
  const records = [
    record("o1.1.1", [0, 0, 1], { min: [-1, -1, 0], max: [1, 1, 2] }),
    record("o1.1.2", [0, 0, 3], { min: [-1, -1, 2], max: [1, 1, 4] }),
    record("o1.2", [0, 0, 7], { min: [-1, -1, 6], max: [1, 1, 8] })
  ];
  const states = createExplodedViewRecordStates(THREE, records, {
    min: [-1, -1, 0],
    max: [1, 1, 8]
  });

  assert.equal(states.length, 3);
  assert.equal(states[0].groupKey, "o1.1");
  assert.equal(states[1].groupKey, "o1.1");
  assert.equal(states[2].groupKey, "o1.2");
  assert.equal(states[0].translation.z, states[1].translation.z);
  assert.equal(states[0].translation.z, 0);
  assert.ok(states[2].translation.z > 0);
  assert.equal(states[2].translation.x, 0);
  assert.equal(states[2].translation.y, 0);

  applyExplodedViewProgress(THREE, states, 1);
  assert.equal(records[0].explodedViewMatrix.elements[14], 0);
  assert.ok(records[2].explodedViewMatrix.elements[14] > 0);

  const explodedBounds = explodedViewBoundsFromStates(THREE, states, { min: [-1, -1, 0], max: [1, 1, 8] });
  assert.equal(explodedBounds.min[2], 0);
  assert.ok(explodedBounds.max[2] > 8);

  clearExplodedViewRecords(records);
  assert.equal(records[0].explodedViewMatrix, null);
  assert.equal(records[2].explodedViewMatrix, null);
});

test("exploded view separates first-level components even when their heights match", () => {
  const records = [
    record("o1.1", [0, 0, 1], { min: [-1, -1, 0], max: [1, 1, 2] }),
    record("o1.2", [0, 0, 1], { min: [-1, -1, 0], max: [1, 1, 2] }),
    record("o1.3", [0, 0, 1], { min: [-1, -1, 0], max: [1, 1, 2] })
  ];
  const states = createExplodedViewRecordStates(THREE, records, {
    min: [-1, -1, 0],
    max: [1, 1, 2]
  });

  assert.deepEqual(states.map((state) => state.groupKey), ["o1.1", "o1.2", "o1.3"]);
  assert.deepEqual(states.map((state) => state.layerIndex), [0, 1, 2]);
  assert.equal(states[0].translation.z, 0);
  assert.ok(states[1].translation.z > states[0].translation.z);
  assert.ok(states[2].translation.z > states[1].translation.z);

  const mergedStates = createExplodedViewRecordStates(THREE, records, {
    min: [-1, -1, 0],
    max: [1, 1, 2]
  }, { mergeCoplanar: true });
  assert.deepEqual(mergedStates.map((state) => state.layerIndex), [0, 0, 0]);
});

test("exploded view depth can break subassemblies into deeper components", () => {
  assert.equal(explodedViewGroupKey("o1.2.3", { depth: 1, commonPrefix: ["o1"] }), "o1.2");
  assert.equal(explodedViewGroupKey("o1.2.3", { depth: 2, commonPrefix: ["o1"] }), "o1.2.3");

  const records = [
    record("o1.1.1", [0, 0, 1], { min: [0, 0, 0], max: [1, 1, 2] }),
    record("o1.1.2", [0, 0, 4], { min: [0, 0, 3], max: [1, 1, 5] }),
    record("o1.2", [0, 0, 7], { min: [0, 0, 6], max: [1, 1, 8] })
  ];
  const states = createExplodedViewRecordStates(THREE, records, {
    min: [0, 0, 0],
    max: [1, 1, 8]
  }, { depth: 2 });

  assert.deepEqual(states.map((state) => state.groupKey), ["o1.1.1", "o1.1.2", "o1.2"]);
  assert.ok(states[1].translation.z > states[0].translation.z);
});

test("exploded view radial axis moves first-level groups outward from model center", () => {
  const records = [
    record("o1.1.1", [-2, 0, 0], { min: [-3, -1, -1], max: [-1, 1, 1] }),
    record("o1.1.2", [-2, 0, 0], { min: [-3, -1, -1], max: [-1, 1, 1] }),
    record("o1.2", [2, 0, 0], { min: [1, -1, -1], max: [3, 1, 1] })
  ];
  const states = createExplodedViewRecordStates(THREE, records, {
    min: [-3, -1, -1],
    max: [3, 1, 1]
  }, { axis: "radial", keepBaseGrounded: false });

  assert.equal(states.length, 3);
  assert.deepEqual(states.map((state) => state.groupKey), ["o1.1", "o1.1", "o1.2"]);
  assert.ok(states[0].translation.x < 0);
  assert.equal(states[0].translation.x, states[1].translation.x);
  assert.equal(states[0].translation.y, states[1].translation.y);
  assert.equal(states[0].translation.z, states[1].translation.z);
  assert.ok(states[2].translation.x > 0);
  assert.equal(states[2].translation.y, 0);
  assert.equal(states[2].translation.z, 0);
});

test("exploded view radial axis can keep the exploded set above the original floor", () => {
  const records = [
    record("o1.1", [0, 0, 0.5], { min: [-1, -1, 0], max: [1, 1, 1] }),
    record("o1.2", [0, 0, 4.5], { min: [-1, -1, 4], max: [1, 1, 5] })
  ];
  const bounds = { min: [-1, -1, 0], max: [1, 1, 5] };
  const ungroundedStates = createExplodedViewRecordStates(THREE, records, bounds, {
    axis: "radial",
    keepBaseGrounded: false
  });
  const groundedStates = createExplodedViewRecordStates(THREE, records, bounds, {
    axis: "radial"
  });

  assert.ok(explodedViewBoundsFromStates(THREE, ungroundedStates, bounds).min[2] < 0);
  assert.ok(explodedViewBoundsFromStates(THREE, groundedStates, bounds).min[2] >= 0);
});

test("exploded view easing clamps to animation bounds", () => {
  assert.equal(easeExplodedViewProgress(-1), 0);
  assert.equal(easeExplodedViewProgress(1.5), 1);
  assert.ok(easeExplodedViewProgress(0.5) > 0.5);
});

test("exploded view progress can interpolate from current translated state", () => {
  const records = [
    record("o1.1", [0, 0, 0], { min: [0, 0, 0], max: [1, 1, 1] })
  ];
  const states = [{
    record: records[0],
    fromTranslation: new THREE.Vector3(0, 0, 10),
    translation: new THREE.Vector3(10, 0, 0),
    matrix: new THREE.Matrix4()
  }];

  assert.deepEqual(explodedViewStateTranslationAtProgress(THREE, states[0], 0).toArray(), [0, 0, 10]);
  assert.deepEqual(explodedViewStateTranslationAtProgress(THREE, states[0], 1).toArray(), [10, 0, 0]);

  applyExplodedViewProgress(THREE, states, 0);
  assert.equal(records[0].explodedViewMatrix.elements[12], 0);
  assert.equal(records[0].explodedViewMatrix.elements[14], 10);

  applyExplodedViewProgress(THREE, states, 0.5);
  assert.equal(records[0].explodedViewMatrix.elements[12], 5);
  assert.equal(records[0].explodedViewMatrix.elements[14], 5);

  applyExplodedViewProgress(THREE, states, 1);
  assert.equal(records[0].explodedViewMatrix.elements[12], 10);
  assert.equal(records[0].explodedViewMatrix.elements[14], 0);
});
