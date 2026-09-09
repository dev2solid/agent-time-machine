# Five-minute demo

1. Run `python3 -m agent_time_machine demo` and open the generated timeline.
2. Explain the stale-evidence bug and compare the instruction branch with the original.
3. Show `comparison.json`: configuration and decision change while retrieval is reused.
4. Show `Session.step` and why replay does not call the operation again.
5. Explain the external-effect/commit crash window and why a hash chain is not a signature.

Practice answering: Why copy prefixes? Which checkpoint should be used when changing
a tool? Why isn't this external exactly-once execution? How would you add redaction?

Use the code to learn the answers. This is an AI-assisted portfolio prototype; describe
your own contributions and understanding accurately rather than presenting the demo
as production infrastructure you operated at scale.
