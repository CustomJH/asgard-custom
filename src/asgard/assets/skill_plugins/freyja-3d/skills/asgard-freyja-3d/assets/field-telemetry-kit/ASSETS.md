# Field telemetry kit

- `field-telemetry-kit.py`, generated STEP/STL/GLB, two-material preview GLB, and evidence: original Asgard reference asset, MIT.
- Purpose: exercise a two-part industrial enclosure assembly, named solids, STEP round-trip, DIN-rail orientation, connector/service features, mesh audit, and glTF delivery.
- Meter reference envelope: Schneider Electric A9MEM3155, 90×95×69 mm, DIN-rail clip-on, Modbus RTU over RS485. Source: <https://iportal.se.com/Contents/docs/SQD-A9MEM3155_DATASHEET.PDF>
- Gateway reference envelope: Teltonika TRB145 housing, 74.5×25×64.4 mm excluding antenna connectors and screws. Source: <https://teltonika-networks.com/cdn/products/2023/01/63b7fe638fe507-90268388/flyer/trb145-black-flyer-2025-v11.pdf>
- Rail datum: Phoenix Contact NS 35/7.5, 35 mm wide and 7.5 mm deep, EN 60715 profile. Source: <https://www.phoenixcontact.com/en-pc/products/din-rail-perforated-ns-35-75-perf-2000mm-0801733>
- Protocol context: Modbus over Serial Line V1.02. Source: <https://www.modbus.org/file/secure/modbusoverserial.pdf>

The forms are generic and omit vendor marks. The modem housing was reoriented to use its 25 mm side as panel width. Connector internals, PCB keep-outs, live-part barriers, creepage/clearance, heat, antenna RF keep-out, EMC, flammability, IP rating, and exact DIN latch geometry are intentionally **not inferred**. Replace this specimen with approved vendor CAD and electrical/mechanical drawings before production.

`field-telemetry-kit.glb` preserves the two CAD parts. `field-telemetry-kit-preview.glb` merges face primitives to two draw calls, adds crease normals, neutral plastic/aluminum PBR materials, and deterministic vertex AO masks. Shape renders are still material-blind; inspect the preview in a real glTF viewer before making a look claim.
