# Video call while paying (deepfake "officer")

**What it catches.** The AI-enabled "digital arrest": a fake police or CBI officer, sometimes a
deepfake, on a WhatsApp video call, watching the victim pay.

**How the phone knows.**
- **What Android tells any app:** when the camera is in use by another app
  (`CameraManager.AvailabilityCallback`). No permission and no images; only "camera N is busy".
- **The rule:** a VoIP call (audio in communication mode) plus a busy camera means a video call.
  `signals/ContextSensor.kt` sends `call.video: true / false / null` (contract c2-0.10). It is null
  when it can't tell (rule 1).
- **No video analysis:** RUKO never analyses the video or voice. Deepfake detectors break each time
  the AI improves, and it would mean sending private media. RUKO catches the scam by what it makes
  the victim do.

**How the engine uses it.**
- `video_call` is a C (context) feature (`features/build.py`). A video call from an unknown caller
  strengthens R1 (the live unknown call).
- It counts for the digital-arrest playbook (unknown caller + video call). It is the same family,
  so it can never light a second family on its own (rule 5).

**Try it.** In the debug panel (long-press "Cache Pay"), use the "call.video" override with an
unknown caller and pay the demo mule: the alert names digital arrest. A video call alone is one
family (C), so it can never interrupt by itself.
**Tests:** `backend/tests/test_demo_agents.py` (the `deepfake_video` scenario),
`backend/tests/test_playbooks.py` (the digital-arrest rule), and `ContractTest.kt` for the field.
