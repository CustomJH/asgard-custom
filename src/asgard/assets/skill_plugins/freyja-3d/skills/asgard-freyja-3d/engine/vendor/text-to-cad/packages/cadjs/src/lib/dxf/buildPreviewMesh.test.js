import assert from "node:assert/strict";
import test from "node:test";

import { buildDxfPreviewMeshData } from "./buildPreviewMesh.js";
import { parseDxf } from "./parseDxf.js";

function dxfText(lines) {
  return `${lines.join("\n")}\n`;
}

function line(start, end) {
  return {
    kind: "cut",
    start,
    end
  };
}

function rectangle(minX, minY, maxX, maxY) {
  return [
    line([minX, minY], [maxX, minY]),
    line([maxX, minY], [maxX, maxY]),
    line([maxX, maxY], [minX, maxY]),
    line([minX, maxY], [minX, minY])
  ];
}

test("DXF preview extrudes multiple disconnected no-bend flat contours", () => {
  const dxfData = {
    geometry: {
      lines: [
        ...rectangle(0, 0, 10, 10),
        ...rectangle(5, 20, 15, 30)
      ],
      arcs: [],
      circles: []
    },
    defaultThicknessMm: 2
  };

  const meshData = buildDxfPreviewMeshData(dxfData, 2);

  assert.equal(meshData.triangle_count > 0, true);
  assert.equal(meshData.guide_line_segments.length, 0);
  assert.deepEqual(meshData.bounds.min, [0, -1, 0]);
  assert.deepEqual(meshData.bounds.max, [15, 1, 30]);
});

test("DXF preview extrudes bulged lwpolyline contours", () => {
  const quarterBulge = Math.tan(Math.PI / 8);
  const dxfData = parseDxf(dxfText([
    "0", "SECTION",
    "2", "ENTITIES",
    "0", "LWPOLYLINE",
    "8", "CUT",
    "90", "4",
    "70", "1",
    "10", "0",
    "20", "0",
    "10", "10",
    "20", "0",
    "10", "10",
    "20", "10",
    "10", "0",
    "20", "10",
    "0", "LWPOLYLINE",
    "8", "CUT",
    "90", "4",
    "70", "1",
    "10", "7",
    "20", "5",
    "42", String(quarterBulge),
    "10", "5",
    "20", "7",
    "42", String(quarterBulge),
    "10", "3",
    "20", "5",
    "42", String(quarterBulge),
    "10", "5",
    "20", "3",
    "42", String(quarterBulge),
    "0", "ENDSEC",
    "0", "EOF"
  ]));

  const meshData = buildDxfPreviewMeshData(dxfData, 2);

  assert.equal(meshData.triangle_count > 0, true);
  assert.equal(meshData.guide_line_segments.length, 0);
  assert.deepEqual(meshData.bounds.min, [0, -1, 0]);
  assert.deepEqual(meshData.bounds.max, [10, 1, 10]);
});
