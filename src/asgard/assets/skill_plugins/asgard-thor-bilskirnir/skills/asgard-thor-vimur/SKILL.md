---
name: asgard-thor-vimur
description: The river Vimur that rose against Thor — wire protocols that fail silently. Framing, checksums, addressing, timing, and the retry rules for Modbus RTU/TCP and fieldbus-shaped protocols, plus a hardware-free reference oracle to validate an implementation against. Load before writing or debugging device communication, serial/TCP framing, register maps, or protocol parsers.
---

# asgard-thor-vimur — 🜄 Wire Protocols

Vimur rose against Thor as he crossed, and he held on to a rowan rather than to his own strength.
That is the discipline here. A wire protocol does not throw. **A wrong byte does not raise an error —
the line goes quiet, or the number is simply wrong**, and it looks like a sensor fault for three
weeks. So you hold on to something fixed outside your own code: a reference oracle, known-answer
vectors, and a device you can run before the real one exists.

## The failure mode that defines this domain

Nothing here is caught by a type system, a test that mocks the transport, or a review. Every classic
defect is a silent one:

- The checksum is right but the **byte order** of the checksum is not.
- The register address is right in the vendor document and off by one on the wire.
- The 32-bit value is assembled from two registers in the wrong **word order** — correct on this
  vendor's device, wrong on the next one.
- The frame is split across two TCP reads and the parser only ever tested a single read.
- A read timed out, the retry succeeded, and now every response is one frame behind forever.

## Validate against something that is not yourself

Testing your decoder against your encoder proves only that you were consistent. The same
misunderstanding sits on both sides. Use the bundled oracle:

    python3 scripts/modbus_ref.py selftest              # known-answer vectors, exit 1 on failure
    python3 scripts/modbus_ref.py serve --port 15020    # a device to talk to, no hardware
    python3 scripts/modbus_ref.py decode <hex> --transport rtu

The one anchor that grounds the whole checksum implementation is the published check value:
CRC-16/MODBUS of `123456789` is `0x4B37`. If that does not match, nothing else you measure means
anything. Establish it first, in whatever language you are writing.

## Framing

- **RTU** — `address | PDU | CRC16`. The CRC goes out **low byte first**, opposite to every other
  multi-byte field. Frame boundaries are *silence*: 3.5 character times. Above 19200 baud the
  standard fixes that interval at 1.75 ms instead of computing it.
- **TCP** — `MBAP(transaction, protocol=0, length, unit) | PDU`, and **no checksum**: the lower layer
  already guarantees integrity. The length field is what tells you where the frame ends — a parser
  that reads once and assumes a whole frame arrived will work in testing and fail under load.
- Addresses on the wire are **0-based**. Documentation numbering (40001, 30001) is a presentation
  convention. Convert once, at the edge, and write down which side of that boundary each value is on.
- Exception responses set the high bit of the function code. Never distinguish them by length.

## Limits are part of the protocol, not of your buffer

Reads cap at 125 holding registers and 2000 coils; writes at 123 registers. Exceeding them is not a
performance question, it is an illegal request — and a device that answers anyway is not evidence
that it is legal. Split at the protocol limit, not at whatever your buffer happens to be.

## Timing, retries, and half-duplex

- A serial bus is half-duplex: one conversation at a time. Concurrency lives above the transport, in
  a queue with one owner, never in two threads holding one port.
- Every read has a timeout, and a timeout is not a failure to retry blindly. **Reads are idempotent;
  writes are not** (Mjölnir's retry canon applies unchanged). Retrying a write without an idempotency
  story is how a meter gets configured twice.
- After a timeout, resynchronise on the silent interval before the next request. Retrying immediately
  into a device that is still answering the previous request is what puts responses permanently one
  frame behind.
- Log the raw frame on every error, in hex, with a direction marker. Without the bytes, a field
  report is a guess.

## What to hand back

A protocol change is finished when: the check value matches, encode/decode round-trips for every
function code you touched, at least one malformed frame is proven to be rejected (not ignored),
split-read reassembly is exercised, and the exception path returns an exception — not a default.
Report those as evidence, with the byte strings (Canon 10 — running is not evaluating).

Vendor documents disagree with the specification, with each other, and sometimes with the device.
When they do, the device wins, and you write down which one you followed and why.
