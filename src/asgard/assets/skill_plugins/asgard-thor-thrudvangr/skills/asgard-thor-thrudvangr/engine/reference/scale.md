# scale — how it behaves after it is deployed

Load `asgard-thor-megingjord`. Scope is the runtime behavior and policy values of what is deployed.
Build graphs, image construction, CI, and packaging belong to `asgard-eitri` — in a mixed file (an
image tag beside a probe in a k8s manifest, a HEALTHCHECK in a Dockerfile), the owner of the primary
surface edits, but runtime values follow this canon.

## Stateless first — it is the precondition, not an optimisation

Process-local sessions, uploaded files on local disk, and in-memory caches that carry consistency all
make horizontal scaling impossible. Externalise before you scale.

Litmus: **does it survive running on two instances?** If you cannot answer yes, nothing below
matters yet.

## Probes — liveness and readiness are not the same question

- **Liveness** — is it alive? Failure means restart.
- **Readiness** — can it accept work? Failure means remove from traffic.

Never cascade a dependency into liveness. A database outage propagated into a liveness failure
triggers a fleet-wide restart storm — dependency state belongs in readiness at most. Keep both
checks light; the check must not become a load source.

## Graceful shutdown

Receive the signal → drop readiness → let in-flight work finish, bounded → release resources → exit.
Cutting in-flight work is data loss for any client without retries. Set the wait cap **shorter** than
the platform's forced-kill grace period, or the platform wins and the drain never completes.

## Scaling policy

- Horizontal first. Vertical needs measured evidence of a single-process bottleneck.
- Autoscale on the real bottleneck signal — queue depth, p99, concurrent work count. CPU alone
  misses every I/O-bound workload.
- Every policy states an upper bound, a lower bound, and a cooldown. Uncapped autoscaling is a cost
  incident and a cascading-failure amplifier.

## Configuration

No per-environment branches in code — inject values, ship one artifact everywhere. Defaults lean
safe (local/dev); production values arrive by explicit injection only.

## Observability minimum

Structured logs with searchable fields, correlation IDs propagated across boundaries, and four
metrics: traffic, error rate, latency (p50/p99), saturation. SLOs on hot paths only.

Litmus: **if this dies at 3am, can logs alone narrow the cause candidates?**

## Hand back

    Runtime: stateless <yes|externalised X>; probes <liveness|readiness split>; drain <n s, under grace>;
    scale on <signal, bounds>; observability <fields, metrics>

## Next

`evidence`. Note that changing a runtime policy value in a live environment is an externally visible
side effect — deliver the plan, do not apply it (approval belongs to Odin).
