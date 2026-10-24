# Run diagnostics summary

- Link policy: `no-guess`; cases: 518; statuses: {'INCOMPLETE': 355, 'COMPLETE': 153, 'NOT_APPLICABLE': 10}
- Output steps: 3127; share resting on weak/unresolved links: 6.9%; cases with any such step: 203

| Link confidence | Linked resources | Output steps |
|---|---|---|
| direct | 1435 | 2877 |
| strong | 35 | 35 |
| weak | 215 | 215 |
| unresolved | 0 | 0 |

Status decision relies on (status:weakest link needed):

- COMPLETE:direct: 153
- INCOMPLETE:direct: 355

Linking methods:

- direct:catalog: 5
- direct:document:identifier: 7
- direct:evidence:identifier: 1419
- direct:identifier+slot: 4
- strong:slot_exclusion_by_direct_links+audit_evidence: 3
- strong:slot_unique+audit_evidence: 32
- weak:clean_run: 38
- weak:evidence_coverage: 5
- weak:in_audit_capture: 1
- weak:run_cadence: 29
- weak:slot_exclusion_by_direct_links: 21
- weak:slot_exclusion_propagated: 3
- weak:slot_unique: 118

Deletion-worker events (confidence:outcome):

- -:no_candidate_request: 4
- -:unassigned: 2
- -:unassigned_ambiguous: 7
- direct:owned_by_identifier: 1039
- direct:owned_by_other_subject: 19
- strong:slot_exclusion_by_direct_links+audit_evidence: 4
- strong:slot_unique+audit_evidence: 34
- unresolved:tie_guess: 122
- weak:clean_run: 38
- weak:evidence_coverage: 7
- weak:in_audit_capture: 1
- weak:in_audit_capture+clean_run: 2
- weak:in_audit_capture+run_cadence: 1
- weak:run_cadence: 31
- weak:slot_exclusion_by_direct_links: 24
- weak:slot_exclusion_propagated: 4
- weak:slot_unique: 127

- Learned run cadence (s): [390, 449]
- States by omission: 140; omission overrides: 1
- States resting only on files captured after audit_at: 178
- Completion guard: 8 cases not claimed COMPLETE ({'tie candidate': 10}); cases whose unattributed tie had every candidate proven compliant: 110
- Catalog conflicts: 1; rejected catalog links: 0
- Evidence: 94 files, problems: 0, observations: 2893
