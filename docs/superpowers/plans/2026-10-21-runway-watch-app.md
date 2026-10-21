# Runway Watch Mac App (Plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The native macOS app of the Runway Watch live demo: a SwiftUI window where two people speak (or type, or replay) radio calls as Tower and Pilot, and the rules parser and Claude show side by side what each understood and which runway conflicts each raised, driven by the plan A helper.

**Architecture:** `mac/RunwayWatchCore` is a Swift package with all the logic and no UI or audio, tested with `swift test`: the helper's JSON, the event-stream parser, the HTTP client, `SessionState` (what the window shows, built only from the helper's events), `LiveSession` (the session the window drives), `HelperSupervisor` (use or launch the helper, one automatic restart), and the talk keys, text size and WAV encoding. `mac/RunwayWatch.xcodeproj` is a thin SwiftUI app over it: the window, toolbar, inspector, menus, Settings, the microphone with Apple's speech preview, and the Option-key monitor. The app talks to the helper only over HTTP on 127.0.0.1:8020.

**Tech Stack:** Swift 6 (language mode 6, toolchain 6.3 in Xcode 26.6), SwiftUI and Observation, Swift Testing, URLSession server-sent events, AVAudioEngine, the Speech framework's `SpeechAnalyzer` and `SpeechTranscriber`, Security (Keychain), Icon Composer's `.icon` format. Python 3 for one fixture script.

**Spec:** `docs/superpowers/specs/2026-10-20-live-demo-app-design.md`, with plan A's eight amendments (`docs/superpowers/plans/2026-10-20-live-demo-helper.md`) and the amendments below. HIG brief: `docs/2026-10-20-macos-hig-research.md`. The helper's API is what plan A built (`atcdb/live_api.py`), not the spec's first sketch of Section 6.

## Global Constraints

- macOS 26 or later on Apple silicon; `MACOSX_DEPLOYMENT_TARGET = 26.0`; Swift language mode 6 (`SWIFT_VERSION = 6.0`, `swift-tools-version: 6.2`).
- No paid API call in any task. Start a helper by hand only as `env -u ANTHROPIC_API_KEY uvicorn atcdb.api:app --host 127.0.0.1 --port 8020`, and leave the app's Settings key empty. An app run from Xcode or the Dock does not see the shell's key, but one started from a terminal does: start it with `env -u ANTHROPIC_API_KEY`. Paid checks are operational steps that need the user's yes.
- Run the Python tests with the key unset (`env -u ANTHROPIC_API_KEY python -m pytest -q`) and the Swift tests with `cd mac/RunwayWatchCore && swift test`; both stay green after every task.
- Helper: 127.0.0.1:8020, `.venv/bin/python -m uvicorn atcdb.api:app --host 127.0.0.1 --port 8020` from the repo checkout, log in `data/live/helper.log` (git-ignored through `data/*`).
- Term list (spec Section 7, item 9): Tower, Pilot, Runway conflict, Readback, Rules, Claude. The API's roles stay `controller` and `pilot`.
- Purpose strings, exactly: `NSMicrophoneUsageDescription` "Runway Watch uses the microphone to transcribe the radio calls you speak."; `NSSpeechRecognitionUsageDescription` "Runway Watch uses speech recognition to show your words while you talk."
- Apple's Human Interface Guidelines as spec Section 7 lists them: semantic colors and system text styles, conflicts as symbol plus label plus color, no alerts for status or conflicts, every toolbar item also in the menu bar.
- UWB-ATCC corpus text never goes into tests or fixtures (CC BY-NC-ND). Austin text (NTSB public record) and invented text are fine.
- Match the repo's style: a doc comment citing the spec where it helps, short comments only where the code cannot say it, no em dashes in docs.
- End every commit message with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Planning amendments to the spec (2026-10-21)

1. **SpeechAnalyzer probe (Section 9, week 1).** Run on four test-split clips fed in real time: with `SpeechTranscriber`'s `progressiveTranscription` preset, preview text arrives about once a second while audio arrives (the default options gave it only in two bursts, at 4.1 s and 5.2 s of a 4.95 s clip); priming `AnalysisContext.contextualStrings` with ATC words changed nothing on any clip, so the app does not prime. Apple's text on 8 kHz radio audio is poor, which is acceptable for a preview and a fallback. No speech-recognition prompt was needed; the purpose string stays in Info.plist in case one is. **Gate passed.**
2. **Esc discards a recording** (HIG: Esc cancels the current action); the Session menu item reads "Discard Recording" while recording and "Stop Replay" during a replay. A click on the Talk button, or ⌘1 / ⌘2, stops and sends.
3. **Edit > Undo Last Line replaces Undo and Redo** (⌘Z), so ⌘Z no longer undoes typing in the typed-input field.
4. **Replays** start a new session and send one line every 2 s, whatever the scenario (the spec gave 2 s for Austin and "the script's pace" for saved sessions); each line keeps its own `t`.
5. **"Raised by: Both"** means both extractors raised a conflict of the same type on the same runway on the same line. Callsigns can differ between them (the rules parser often drops one).
6. **An existing helper is used as it is.** If a helper already answers on 8020 (started from a terminal), the app uses it and leaves it running at quit; the key in Settings reaches only a helper the app launches.
7. **Whisper loading is shown as "Loading speech model..."**, not a determinate bar: the helper reports no download progress, and the weights are already downloaded (plan A, O1).
8. **One line at a time.** While one talk key is held the other is ignored; Option pressed with Command, Control or Shift is a shortcut, never a line, and cancels a line in progress. The app leaving the foreground ends a held line as if the key came up.
9. **The app is not sandboxed and has no hardened runtime; it is signed to run locally.** It launches the repo's Python and is not distributed (spec Section 1). macOS may ask for the microphone again after a rebuild.
10. **No `status` event.** Plan A's stream has none; the app polls `GET /api/live/health` (every second while Whisper loads, every 5 s after).
11. **The helper drops short clips** (plan A, `MIN_CLIP_S`); the app sends every clip and shows the `dropped` event.
12. **Tests.** The app target has no test target: its logic is in the package. The app is checked by a clean build, a smoke run, and the manual checklist (operational step B1). The shared scheme has no testables; the package's 51 tests run with `swift test`.

## Review Focus

1. The helper restarts during a session (a crash, or Restart Helper): every route answers 404 for the old session, so the window opens a new one and says why, instead of hanging. (Task 4: `aHelperThatForgotTheSessionGetsANewOneAndTheWindowSaysWhy`.)
2. ⌥⌘I (Show Inspector) with the left Option key must never record a line, and Option joining a shortcut mid-line discards it. (Task 6: `optionInAShortcutCancelsRatherThanTalks`.)
3. Undo pressed while Claude is still parsing that line: its late result must not reappear. (Task 2: `undoRemovesTheRowAndIgnoresItsLateResults`.)
4. The event stream drops (a sleep, a busy helper): the window resumes after the last event it saw, without repeating or losing lines. (Task 4: `aDroppedConnectionResumesAfterTheLastEventItSaw`.)
5. The helper the app launched crashes twice: the second time the window offers Restart Helper and disables Talk with the reason, instead of looping. (Task 5: `aCrashIsRestartedOnceThenTheWindowOffersRestartHelper`.)

What no automated test reaches (the microphone, Apple speech, the Option keys, VoiceOver) is operational step B1's checklist.

## Files

```
scripts/record_live_stream.py                 records the helper's event stream for the Swift tests (Task 1)
mac/RunwayWatchCore/                          Swift package: logic, tested with swift test (Tasks 1 to 6)
  Package.swift
  Sources/RunwayWatchCore/HelperAPI.swift          the helper's JSON
  Sources/RunwayWatchCore/ServerSentEvents.swift   the text/event-stream parser
  Sources/RunwayWatchCore/Wording.swift            event, hold, failure and time wording
  Sources/RunwayWatchCore/SessionState.swift       rows, conflict cards, runway table
  Sources/RunwayWatchCore/HelperClient.swift       the HelperClient protocol and its HTTP implementation
  Sources/RunwayWatchCore/LiveSession.swift        the session the window drives
  Sources/RunwayWatchCore/HelperSupervisor.swift   use or launch the helper; HelperCommand; ProcessLauncher
  Sources/RunwayWatchCore/TalkInput.swift          talk keys, text size, WAV
  Tests/RunwayWatchCoreTests/...                   one test file per source file; Fixtures/austin_stream.txt
mac/RunwayWatch.xcodeproj/                    the app target (synchronized folder mac/RunwayWatch) and shared scheme (Task 7)
mac/RunwayWatch/                              the app: views, menus, Settings, microphone, keys, icon (Task 7)
```

---

### Task 1: The helper's API and event stream in Swift

**Files:**
- Create: `scripts/record_live_stream.py`, then run it to create `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/Fixtures/austin_stream.txt`
- Create: `mac/RunwayWatchCore/Package.swift`
- Create: `mac/RunwayWatchCore/Sources/RunwayWatchCore/HelperAPI.swift`, `.../ServerSentEvents.swift`
- Modify: `.gitignore`
- Test: `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/HelperAPITests.swift`

**Interfaces:**
- Consumes: plan A's routes and event shapes (`atcdb/live.py`, `atcdb/live_hub.py`, `atcdb/serialize.py`); `tests/live_fakes.Scripted`.
- Produces: `Role` (`controller`, `pilot`; `.title` Tower / Pilot), `Extractor` (`rules`, `claude`; `.title`), `LineSource`, `Transcriber` (`whisper`, `apple`, `none`), `ExtractedEvent(kind:callsign:runway:to:)`, `Conflict` (`type`, `severity`, `runway`, `callsigns`, `explanation`), `RunwayHold`, `TranscriptEvent`, `ExtractionEvent`, `SessionEvent` (`.transcript`, `.extraction`, `.undone(seq:)`, `.dropped(role:t:reason:)`, `.other(type:)`), `StreamedEvent(id:event:)` and `StreamedEvent(_: ServerSentEvent) throws`, `Health` (`whisper.status: WhisperStatus`, `claude.available`), `Scenario`, `ScenarioLine`, `HelperJSON.decoder / .encoder` (snake case), `ServerSentEvent(id:event:data:)`, `ServerSentEventParser.feed(_ bytes) -> [ServerSentEvent]`. Test helpers: `fixture(_ name) throws -> String`, `parseAll(_ text) -> [ServerSentEvent]`.

- [ ] **Step 1: Record the fixture**

Create `scripts/record_live_stream.py`:

```python
#!/usr/bin/env python3
"""Record the helper's event stream for the Mac app's tests (plan B): the Austin replay through the live routes, with
the rules parser and the scripted Claude stand-in of tests/live_fakes.py, then a clip too short to keep and an undo.

Usage:
    python scripts/record_live_stream.py

Writes mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/Fixtures/austin_stream.txt: the server-sent event text exactly as
GET /api/live/sessions/{id}/stream sends it. Free: no API call and no Whisper. The stand-in fails once on "fedex is on
the go", so the stream carries a Claude error too. Austin is NTSB public record.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402
from live_fakes import Scripted, wav  # noqa: E402

from atcdb import parse_rules  # noqa: E402
from atcdb.api import create_app  # noqa: E402
from atcdb.live import Track  # noqa: E402
from atcdb.live_hub import AUSTIN_ID, LiveHub, WhisperLoader  # noqa: E402

OUT = ROOT / "mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/Fixtures/austin_stream.txt"
FAILS = "fedex is on the go"


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tracks = lambda: {"rules": Track("rules", parse_rules.parse), "claude": Track("claude", Scripted(fail_texts=[FAILS]))}
        hub = LiveHub(Path(tmp) / "sessions", WhisperLoader(lambda: None), tracks)
        client = TestClient(create_app(Path(tmp) / "none.sqlite", Path(tmp), live_hub=hub))
        sid = client.post("/api/live/sessions").json()["session_id"]
        lines = client.get(f"/api/live/scenarios/{AUSTIN_ID}").json()
        for x in lines:
            client.post(f"/api/live/sessions/{sid}/text",
                        json={"role": x["role"], "t": x["t"], "text": x["text"], "source": "replay"})
        session = hub.get(sid)
        session.wait_for(lambda ev: sum(e["type"] == "extraction" for e in ev) == 2 * len(lines))
        client.post(f"/api/live/sessions/{sid}/audio", params={"role": "pilot", "t": 900.0}, content=wav(0.2))
        client.post(f"/api/live/sessions/{sid}/undo")
        n = len(session.events_after())
        with client.stream("GET", f"/api/live/sessions/{sid}/stream", params={"max_events": n}) as r:
            text = "".join(r.iter_text())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {n} events to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
```

Run: `env -u ANTHROPIC_API_KEY python scripts/record_live_stream.py`
Expected: `wrote 95 events to mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/Fixtures/austin_stream.txt` (31 transcripts, 62 extractions, 1 dropped, 1 undone). Free: no API call, no Whisper.

- [ ] **Step 2: Write the failing tests**

Create `mac/RunwayWatchCore/Package.swift`:

```swift
// swift-tools-version: 6.2
// The Mac app's logic, with no UI and no audio, so it is tested with `swift test` (plan B; spec
// docs/superpowers/specs/2026-10-20-live-demo-app-design.md, Section 9).
import PackageDescription

let package = Package(
    name: "RunwayWatchCore",
    platforms: [.macOS(.v26)],
    products: [.library(name: "RunwayWatchCore", targets: ["RunwayWatchCore"])],
    targets: [
        .target(name: "RunwayWatchCore"),
        .testTarget(name: "RunwayWatchCoreTests", dependencies: ["RunwayWatchCore"], resources: [.copy("Fixtures")]),
    ]
)
```

Create `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/HelperAPITests.swift`:

```swift
import Foundation
import Testing
@testable import RunwayWatchCore

func fixture(_ name: String) throws -> String {
    let url = try #require(Bundle.module.url(forResource: name, withExtension: nil, subdirectory: "Fixtures"))
    return try String(contentsOf: url, encoding: .utf8)
}

func parseAll(_ text: String) -> [ServerSentEvent] {
    var parser = ServerSentEventParser()
    return parser.feed(Array(text.utf8))
}

@Test func theParserSplitsEventsOnBlankLinesAndSkipsComments() {
    let events = parseAll(": keep-alive\n\nid: 3\nevent: undone\ndata: {\"seq\": 1}\n\nid: 4\ndata: a\ndata: b\n\n")
    #expect(events == [ServerSentEvent(id: "3", event: "undone", data: "{\"seq\": 1}"),
                       ServerSentEvent(id: "4", event: nil, data: "a\nb")])
}

@Test func theParserHandlesCarriageReturnsAndEventsSplitAcrossChunks() {
    var parser = ServerSentEventParser()
    let text = Array("id: 7\r\nevent: transcript\r\ndata: {}\r\n\r\n".utf8)
    #expect(parser.feed(text[..<10]).isEmpty)
    #expect(parser.feed(text[10...]) == [ServerSentEvent(id: "7", event: "transcript", data: "{}")])
}

@Test func theRecordedAustinStreamDecodesIntoSessionEvents() throws {
    let events = try parseAll(fixture("austin_stream.txt")).map(StreamedEvent.init)
    #expect(events.count == 95 && events.map(\.id) == Array(0..<95))
    guard case .transcript(let first) = events[0].event else { Issue.record("not a transcript"); return }
    #expect(first.seq == 0 && first.role == .pilot && first.source == .replay && first.transcriber == .none)
    #expect(first.text.hasPrefix("and tower spirit wings eleven forty five") && first.error == nil)
    let extractions = events.compactMap { if case .extraction(let x) = $0.event { x } else { nil } }
    #expect(extractions.count == 62)
    let failed = try #require(extractions.first { $0.error != nil })
    #expect(failed.extractor == .claude && failed.error == "RuntimeError: Claude unavailable: no internet connection")
    let takeoff = try #require(extractions.first { $0.extractor == .claude && $0.conflicts.contains { $0.runway == "18L" } })
    #expect(takeoff.events == [ExtractedEvent(kind: "TAKEOFF", callsign: "southwest seven zero eight", runway: "18L", to: nil)])
    #expect(takeoff.conflicts[0].type == "RUNWAY" && takeoff.conflicts[0].severity == "alert")
    // the stand-in reads FedEx's readback as a second landing clearance (tests/live_fakes.py is crude on purpose)
    #expect(takeoff.runways["18L"]?.map(\.kind) == ["LAND", "LAND", "TAKEOFF"])
    #expect(events[93].event == .dropped(role: .pilot, t: 900, reason: "Too short"))
    #expect(events[94].event == .undone(seq: 30))
}

@Test func anUnknownEventTypeIsKeptAsOther() throws {
    let event = try StreamedEvent(ServerSentEvent(id: "9", event: "status", data: "{\"id\": 9, \"type\": \"status\"}"))
    #expect(event == StreamedEvent(id: 9, event: .other(type: "status")))
}

@Test func healthAndScenariosDecodeFromTheHelpersJSON() throws {
    let health = try HelperJSON.decoder.decode(Health.self, from: Data("""
        {"whisper": {"status": "loading", "reason": null}, "claude": {"model": "claude-haiku-5-5", "available": false,
         "reason": "ANTHROPIC_API_KEY not set"}, "extractors": ["rules", "claude"], "parser_versions": {"rules": "v1"}}
        """.utf8))
    #expect(health.whisper == .init(status: .loading, reason: nil))
    #expect(health.claude == .init(model: "claude-haiku-5-5", available: false, reason: "ANTHROPIC_API_KEY not set"))
    let lines = try HelperJSON.decoder.decode([ScenarioLine].self, from: Data("""
        [{"role": "controller", "t": 1.0, "text": "csa one two three", "preview_text": "", "audio": "/api/live/sessions/s/clips/0"},
         {"role": "pilot", "t": 4.0, "text": "say again", "preview_text": "", "audio": null}]
        """.utf8))
    #expect(lines.map(\.audio) == ["/api/live/sessions/s/clips/0", nil] && lines[0].role == .controller)
}

@Test func rolesAndExtractorsUseTheTermList() {
    #expect(Role.allCases.map(\.title) == ["Tower", "Pilot"])
    #expect(Extractor.allCases.map(\.title) == ["Rules", "Claude"])
}
```

In `.gitignore`, replace:

```text
# subagent-driven-development scratch (ledger, briefs, review packages)
.superpowers/
```

with:

```text
# subagent-driven-development scratch (ledger, briefs, review packages)
.superpowers/

# the Mac app (mac/): SwiftPM and Xcode build state
.build/
.swiftpm/
xcuserdata/
mac/RunwayWatch.xcodeproj/project.xcworkspace/
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: FAIL before compiling: `error: 'runwaywatchcore': target 'RunwayWatchCore' referenced in product 'RunwayWatchCore' is empty`.

- [ ] **Step 4: Implement**

Create `mac/RunwayWatchCore/Sources/RunwayWatchCore/HelperAPI.swift`:

```swift
import Foundation

// The helper's JSON, as atcdb/live.py, atcdb/live_hub.py and atcdb/serialize.py write it (spec Section 6; plan A).

/// Who spoke. The helper says controller and pilot; the app says Tower and Pilot (spec Section 7, item 9).
public enum Role: String, Codable, Sendable, CaseIterable {
    case controller, pilot

    public var title: String { self == .controller ? "Tower" : "Pilot" }
}

public enum Extractor: String, Codable, Sendable, CaseIterable {
    case rules, claude

    public var title: String { self == .rules ? "Rules" : "Claude" }
}

public enum LineSource: String, Codable, Sendable {
    case speech, typed, replay
}

/// Where a line's text came from: Whisper, Apple speech, or none (typed or scripted text).
public enum Transcriber: String, Codable, Sendable {
    case whisper, apple, none
}

public struct ExtractedEvent: Codable, Sendable, Hashable {
    public var kind: String
    public var callsign: String
    public var runway: String?
    public var to: String?

    public init(kind: String, callsign: String, runway: String? = nil, to: String? = nil) {
        self.kind = kind
        self.callsign = callsign
        self.runway = runway
        self.to = to
    }
}

public struct Conflict: Codable, Sendable, Hashable {
    public var type: String        // RUNWAY | READBACK
    public var severity: String    // alert | warning
    public var runway: String?
    public var callsigns: [String]
    public var explanation: String
}

/// One reservation an engine holds on a runway.
public struct RunwayHold: Codable, Sendable, Hashable {
    public var callsign: String
    public var kind: String
}

public struct TranscriptEvent: Codable, Sendable, Equatable {
    public var seq: Int
    public var role: Role
    public var t: Double
    public var text: String
    public var source: LineSource
    public var transcriber: Transcriber
    public var previewText: String
    public var error: String?
}

public struct ExtractionEvent: Codable, Sendable, Equatable {
    public var seq: Int
    public var extractor: Extractor
    public var events: [ExtractedEvent]
    public var conflicts: [Conflict]
    public var runways: [String: [RunwayHold]]
    public var error: String?
}

public enum SessionEvent: Sendable, Equatable {
    case transcript(TranscriptEvent)
    case extraction(ExtractionEvent)
    case undone(seq: Int)
    case dropped(role: Role, t: Double, reason: String)
    case other(type: String)
}

/// A session event with its stream id, which `after` and Last-Event-ID resume from.
public struct StreamedEvent: Sendable, Equatable {
    public var id: Int
    public var event: SessionEvent

    public init(id: Int, event: SessionEvent) {
        self.id = id
        self.event = event
    }

    public init(_ message: ServerSentEvent) throws {
        let data = Data(message.data.utf8)
        let head = try HelperJSON.decoder.decode(Head.self, from: data)
        id = head.id
        switch head.type {
        case "transcript": event = .transcript(try HelperJSON.decoder.decode(TranscriptEvent.self, from: data))
        case "extraction": event = .extraction(try HelperJSON.decoder.decode(ExtractionEvent.self, from: data))
        case "undone": event = .undone(seq: try HelperJSON.decoder.decode(Undone.self, from: data).seq)
        case "dropped":
            let d = try HelperJSON.decoder.decode(Dropped.self, from: data)
            event = .dropped(role: d.role, t: d.t, reason: d.reason)
        default: event = .other(type: head.type)
        }
    }

    private struct Head: Decodable { var id: Int; var type: String }
    private struct Undone: Decodable { var seq: Int }
    private struct Dropped: Decodable { var role: Role; var t: Double; var reason: String }
}

public struct Health: Codable, Sendable, Equatable {
    public enum WhisperStatus: String, Codable, Sendable { case idle, loading, ready, failed }

    public struct Whisper: Codable, Sendable, Equatable {
        public var status: WhisperStatus
        public var reason: String?
    }

    public struct Claude: Codable, Sendable, Equatable {
        public var model: String
        public var available: Bool
        public var reason: String?
    }

    public var whisper: Whisper
    public var claude: Claude
}

/// An entry in the Replay menu: the Austin transcript or a saved session.
public struct Scenario: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var title: String
    public var lines: Int
    public var audio: Bool
}

public struct ScenarioLine: Codable, Sendable, Equatable {
    public var role: Role
    public var t: Double
    public var text: String
    public var previewText: String
    public var audio: String?   // the clip's path on the helper, for a saved session's spoken line
}

public enum HelperJSON {
    public static var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    public static var encoder: JSONEncoder {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }
}
```

Create `mac/RunwayWatchCore/Sources/RunwayWatchCore/ServerSentEvents.swift`:

```swift
/// One server-sent event: the fields the helper's stream uses.
public struct ServerSentEvent: Sendable, Equatable {
    public var id: String?
    public var event: String?
    public var data: String

    public init(id: String?, event: String?, data: String) {
        self.id = id
        self.event = event
        self.data = data
    }
}

/// Reads the text/event-stream format from bytes as they arrive. URLSession's `lines` drops blank lines, and a blank line
/// is what ends an event, so the parser splits lines itself.
public struct ServerSentEventParser: Sendable {
    private var line: [UInt8] = []
    private var lastWasCR = false
    private var id: String?
    private var event: String?
    private var data: [String] = []

    public init() {}

    /// The events these bytes complete.
    public mutating func feed(_ bytes: some Sequence<UInt8>) -> [ServerSentEvent] {
        var out: [ServerSentEvent] = []
        for byte in bytes {
            if byte == UInt8(ascii: "\n") && lastWasCR {   // the \n of a \r\n: the line already ended
                lastWasCR = false
                continue
            }
            lastWasCR = byte == UInt8(ascii: "\r")
            if byte == UInt8(ascii: "\n") || byte == UInt8(ascii: "\r") {
                if let e = endLine() { out.append(e) }
            } else {
                line.append(byte)
            }
        }
        return out
    }

    private mutating func endLine() -> ServerSentEvent? {
        let text = String(decoding: line, as: UTF8.self)
        line.removeAll(keepingCapacity: true)
        if text.isEmpty {
            defer { (id, event, data) = (nil, nil, []) }
            return data.isEmpty ? nil : ServerSentEvent(id: id, event: event, data: data.joined(separator: "\n"))
        }
        if text.hasPrefix(":") { return nil }   // a comment, such as the helper's keep-alive
        let parts = text.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        var value = parts.count > 1 ? String(parts[1]) : ""
        if value.hasPrefix(" ") { value.removeFirst() }
        switch parts[0] {
        case "id": id = value
        case "event": event = value
        case "data": data.append(value)
        default: break
        }
        return nil
    }
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: `Test run with 6 tests in 0 suites passed`. `git status --short` shows no `.build/` or `.swiftpm/`.

- [ ] **Step 6: Commit**

```bash
git add .gitignore scripts/record_live_stream.py mac/RunwayWatchCore
git commit -m "feat: the Mac app's core package reads the helper's JSON and event stream

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Session state, conflict cards and wording

**Files:**
- Create: `mac/RunwayWatchCore/Sources/RunwayWatchCore/Wording.swift`, `.../SessionState.swift`
- Test: `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/SessionStateTests.swift`

**Interfaces:**
- Consumes: Task 1's types; `fixture`, `parseAll`.
- Produces: `Wording.event(_:)`, `.hold(_:)`, `.failure(_ extractor, _ error)`, `.reason(_ error)` (drops the Python exception class), `.time(_ seconds)` (m:ss, or h:mm:ss); `ExtractorStatus` (`.waiting`, `.understood([String])`, `.nothing`, `.failed(String)`, `.notRun`); `LineRow` (`seq`, `transcript`, `results`, `status(_:)`, `cards`, `conflictBy`, `accessibilitySummary`); `ConflictCard` (`seq`, `time`, `type`, `runway`, `raised: [Extractor: [Conflict]]`, `title`, `symbol`, `isAlert`, `raisedBy` "Rules" / "Claude" / "Both", `callsigns`); `RunwayRow(runway:rules:claude:)`; `DroppedNote(role:reason:)`; `SessionState` (`rows`, `dropped`, `apply(_:)`, `clearResults(_:from:)`, `row(_:)`, `cards` newest first, `board(_:)`, `runwayRows`). Test helpers: `land18L`, `takeoff18L`, `transcript(...)`, `extraction(...)`, `runwayConflict(...)`.

- [ ] **Step 1: Write the failing tests**

Create `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/SessionStateTests.swift`:

```swift
import Testing
@testable import RunwayWatchCore

let land18L = ExtractedEvent(kind: "LAND", callsign: "fedex fourteen thirty two heavy", runway: "18L")
let takeoff18L = ExtractedEvent(kind: "TAKEOFF", callsign: "southwest seven zero eight", runway: "18L")

func transcript(_ seq: Int, _ text: String = "southwest seven zero eight runway one eight left cleared for takeoff",
                role: Role = .controller, t: Double = 0, transcriber: Transcriber = .none,
                error: String? = nil) -> SessionEvent {
    .transcript(TranscriptEvent(seq: seq, role: role, t: t, text: text, source: .typed, transcriber: transcriber,
                                previewText: "", error: error))
}

func extraction(_ seq: Int, _ x: Extractor, _ events: [ExtractedEvent] = [], conflicts: [Conflict] = [],
                runways: [String: [RunwayHold]] = [:], error: String? = nil) -> SessionEvent {
    .extraction(ExtractionEvent(seq: seq, extractor: x, events: events, conflicts: conflicts, runways: runways, error: error))
}

func runwayConflict(_ severity: String = "alert", _ callsigns: [String] = ["southwest seven zero eight",
                                                                          "fedex fourteen thirty two heavy"]) -> Conflict {
    Conflict(type: "RUNWAY", severity: severity, runway: "18L", callsigns: callsigns,
             explanation: "TAKEOFF on 18L while fedex fourteen thirty two heavy holds a landing clearance")
}

@Test func rowsFillAsEventsArriveInAnyOrder() {
    var s = SessionState()
    s.apply(extraction(1, .rules, [takeoff18L]))
    s.apply(transcript(0, "fedex one eight left cleared to land"))
    s.apply(transcript(1))
    #expect(s.rows.map(\.seq) == [0, 1])
    #expect(s.rows[1].status(.rules) == .understood(["TAKEOFF 18L southwest seven zero eight"]))
    #expect(s.rows[1].status(.claude) == .waiting && s.rows[0].status(.rules) == .waiting)
    s.apply(extraction(1, .claude))
    #expect(s.rows[1].status(.claude) == .nothing)
}

@Test func aLineWithNoWordsShowsItsErrorAndWaitsForNoExtractor() {
    var s = SessionState()
    s.apply(transcript(0, "", error: "No speech recognized"))
    #expect(s.rows[0].status(.rules) == .notRun && s.rows[0].status(.claude) == .notRun)
}

@Test func failuresSayWhatHappenedAndHowToFixIt() {
    var s = SessionState()
    s.apply(transcript(0))
    s.apply(extraction(0, .claude, error: "RuntimeError: ANTHROPIC_API_KEY not set"))
    s.apply(transcript(1))
    s.apply(extraction(1, .claude, error: "APITimeoutError: Request timed out."))
    #expect(s.rows[0].status(.claude) == .failed("Claude unavailable: ANTHROPIC_API_KEY not set. Add the API key in Settings."))
    #expect(s.rows[1].status(.claude) == .failed("Claude unavailable: Request timed out."))
}

@Test func undoRemovesTheRowAndIgnoresItsLateResults() {
    var s = SessionState()
    s.apply(transcript(0))
    s.apply(.undone(seq: 0))
    s.apply(extraction(0, .claude, [takeoff18L]))
    #expect(s.rows.isEmpty && s.cards.isEmpty)
}

@Test func retryClearsOneExtractorsResultsFromALineOnSoTheyShowAsWaiting() {
    var s = SessionState()
    for seq in 0..<3 {
        s.apply(transcript(seq))
        s.apply(extraction(seq, .rules))
        s.apply(extraction(seq, .claude, error: seq == 1 ? "APIConnectionError: Connection error." : nil))
    }
    s.clearResults(.claude, from: 1)
    #expect(s.rows.map { $0.status(.claude) } == [.nothing, .waiting, .waiting])
    #expect(s.rows.map { $0.status(.rules) } == [.nothing, .nothing, .nothing])
}

@Test func aConflictBothExtractorsRaiseOnTheSameLineIsOneCardRaisedByBoth() {
    var s = SessionState()
    s.apply(transcript(0, "fedex one eight left cleared to land", t: 5))
    s.apply(extraction(0, .claude, [land18L]))
    s.apply(transcript(1, t: 289))
    s.apply(extraction(1, .claude, [takeoff18L], conflicts: [runwayConflict()]))
    s.apply(transcript(2, "fedex affirmative one eight left cleared to land", t: 325))
    s.apply(extraction(2, .rules, [land18L], conflicts: [runwayConflict("warning", ["", "southwest seven zero eight"])]))
    s.apply(extraction(2, .claude, [land18L], conflicts: [runwayConflict("alert", ["fedex fourteen thirty two heavy",
                                                                                   "southwest seven zero eight"])]))
    #expect(s.cards.map(\.seq) == [2, 1])   // newest first
    #expect(s.cards.map(\.raisedBy) == ["Both", "Claude"])
    let card = s.cards[0]
    #expect(card.title == "Runway conflict" && card.symbol == "exclamationmark.octagon.fill" && card.isAlert)
    #expect(card.runway == "18L" && card.callsigns == ["southwest seven zero eight", "fedex fourteen thirty two heavy"])
    #expect(card.time == "5:25" && s.rows[2].conflictBy == [.rules, .claude])
}

@Test func aReadbackConflictHasItsOwnSymbolAndLabel() {
    var s = SessionState()
    s.apply(transcript(0, role: .pilot))
    s.apply(extraction(0, .claude, conflicts: [Conflict(type: "READBACK", severity: "warning", runway: "13",
                                                       callsigns: ["air france one nine eight romeo"],
                                                       explanation: "readback leaves out runway 13")]))
    let card = s.cards[0]
    #expect(card.title == "Readback" && card.symbol == "exclamationmark.triangle" && !card.isAlert && card.raisedBy == "Claude")
}

@Test func theRunwayTableShowsWhatEachEngineHoldsAfterItsLatestLine() {
    var s = SessionState()
    s.apply(transcript(0))
    s.apply(extraction(0, .claude, [land18L], runways: ["18L": [RunwayHold(callsign: "fedex fourteen thirty two heavy", kind: "LAND")]]))
    s.apply(extraction(0, .rules))
    s.apply(transcript(1))
    s.apply(extraction(1, .rules, [takeoff18L], runways: ["18L": [RunwayHold(callsign: "southwest seven zero eight", kind: "TAKEOFF")],
                                                         "31": [RunwayHold(callsign: "csa one two three", kind: "LAND")]]))
    #expect(s.runwayRows == [RunwayRow(runway: "18L", rules: "TAKEOFF southwest seven zero eight",
                                       claude: "LAND fedex fourteen thirty two heavy"),
                             RunwayRow(runway: "31", rules: "LAND csa one two three", claude: "")])
    s.apply(.undone(seq: 1))
    #expect(s.runwayRows == [RunwayRow(runway: "18L", rules: "", claude: "LAND fedex fourteen thirty two heavy")])
}

@Test func aDroppedClipIsShownUntilTheNextLine() {
    var s = SessionState()
    s.apply(.dropped(role: .pilot, t: 3, reason: "Too short"))
    #expect(s.dropped == DroppedNote(role: .pilot, reason: "Too short"))
    s.apply(transcript(0))
    #expect(s.dropped == nil)
}

@Test func theAustinStreamEndsWithRulesWarningOnceAndClaudeAlertingAtTheTakeoffClearance() throws {
    var s = SessionState()
    for message in parseAll(try fixture("austin_stream.txt")) { s.apply(try StreamedEvent(message).event) }
    #expect(s.rows.count == 30)   // 31 lines, the last one undone
    let rules = s.cards.filter { $0.raised[.rules] != nil }.map { ($0.time, $0.runway, $0.raised[.rules]![0].severity) }
    #expect(rules.count == 1 && rules[0] == ("6:39:34", "18L", "warning"))   // late, as in docs/results/pilot-cases.md
    let firstClaude18L = try #require(s.cards.last { $0.raised[.claude] != nil && $0.runway == "18L" })
    #expect(firstClaude18L.time == "6:38:58")
    #expect(s.rows.first { $0.transcript?.text == "fedex is on the go" }?.status(.claude) ==
            .failed("Claude unavailable: Claude unavailable: no internet connection"))
}

@Test func wordingFollowsTheEventSheet() {
    #expect(Wording.event(ExtractedEvent(kind: "HOLD_SHORT", callsign: "lufthansa four five six", runway: "31")) ==
            "HOLD SHORT 31 lufthansa four five six")
    #expect(Wording.event(ExtractedEvent(kind: "HANDOFF", callsign: "american nineteen thirteen", to: "departure")) ==
            "HANDOFF departure american nineteen thirteen")
    #expect(Wording.event(ExtractedEvent(kind: "READBACK", callsign: "")) == "READBACK")
    #expect([4.2, 65, 3600, 23306].map(Wording.time) == ["0:04", "1:05", "1:00:00", "6:28:26"])
}

@Test func aRowReadsAsOneSentenceForVoiceOver() {
    var s = SessionState()
    s.apply(transcript(0, "fedex one eight left cleared to land", t: 65, transcriber: .apple))
    s.apply(extraction(0, .rules))
    s.apply(extraction(0, .claude, [land18L], conflicts: [runwayConflict()]))
    #expect(s.rows[0].accessibilitySummary ==
            "Tower, 1:05, Apple speech: fedex one eight left cleared to land. Rules: Nothing understood. " +
            "Claude: LAND 18L fedex fourteen thirty two heavy. Runway conflict raised by Claude.")
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: FAIL to compile: `cannot find 'SessionState' in scope` (and `Wording`, `RunwayRow`, `DroppedNote`).

- [ ] **Step 3: Implement**

Create `mac/RunwayWatchCore/Sources/RunwayWatchCore/Wording.swift`:

```swift
/// The words the window uses for events, holds, failures and times (spec Section 3 and Section 7, item 9).
public enum Wording {
    /// An event in the event sheet's wording: kind, runway or handoff target, callsign ("LAND 18L fedex ...").
    public static func event(_ e: ExtractedEvent) -> String {
        words([kind(e.kind), e.runway ?? e.to ?? "", e.callsign])
    }

    /// What an engine holds on a runway: kind and callsign.
    public static func hold(_ h: RunwayHold) -> String {
        words([kind(h.kind), h.callsign])
    }

    /// A failed extraction, saying what happened and, where the app can fix it, how.
    public static func failure(_ extractor: Extractor, _ error: String) -> String {
        let reason = reason(error)
        var message = (extractor == .claude ? "Claude unavailable: " : "Rules failed: ") + reason
        if reason.contains("ANTHROPIC_API_KEY") {
            if !message.hasSuffix(".") { message += "." }
            message += " Add the API key in Settings."
        }
        return message
    }

    /// A helper error without its Python exception class ("APITimeoutError: Request timed out." reads "Request timed out.").
    public static func reason(_ error: String) -> String {
        error.replacing(#/^[A-Za-z_][\w.]*(?:Error|Exception|Timeout)\w*: /#, with: "")
    }

    /// Seconds as m:ss, or h:mm:ss from an hour on (Austin's lines carry the time of day).
    public static func time(_ t: Double) -> String {
        let total = Int(t.rounded(.down))
        let (h, m, s) = (total / 3600, total % 3600 / 60, total % 60)
        let ss = s < 10 ? "0\(s)" : "\(s)"
        if h > 0 { return "\(h):\(m < 10 ? "0\(m)" : "\(m)"):\(ss)" }
        return "\(m):\(ss)"
    }

    private static func kind(_ k: String) -> String { k.replacing("_", with: " ") }

    private static func words(_ parts: [String]) -> String {
        parts.filter { !$0.isEmpty }.joined(separator: " ")
    }
}
```

Create `mac/RunwayWatchCore/Sources/RunwayWatchCore/SessionState.swift`:

```swift
/// What one extractor's row in the transcript says (spec Section 3).
public enum ExtractorStatus: Sendable, Equatable {
    case waiting                  // no result yet: a small spinner
    case understood([String])     // each event in the event sheet's wording
    case nothing                  // "Nothing understood"
    case failed(String)           // the reason and how to fix it, with Retry
    case notRun                   // the line had no words, so no extractor runs
}

/// One transmission: its transcript and each extractor's latest result.
public struct LineRow: Identifiable, Sendable, Equatable {
    public let seq: Int
    public var transcript: TranscriptEvent?
    public var results: [Extractor: ExtractionEvent] = [:]

    public var id: Int { seq }

    public func status(_ x: Extractor) -> ExtractorStatus {
        if let t = transcript, t.error != nil || t.text.isEmpty { return .notRun }
        guard let r = results[x] else { return .waiting }
        if let error = r.error { return .failed(Wording.failure(x, error)) }
        return r.events.isEmpty ? .nothing : .understood(r.events.map(Wording.event))
    }

    /// The conflicts this line raised, one card per type and runway, whichever extractor raised them.
    public var cards: [ConflictCard] {
        var out: [ConflictCard] = []
        for x in Extractor.allCases {
            for c in results[x]?.conflicts ?? [] {
                if let k = out.firstIndex(where: { $0.type == c.type && $0.runway == c.runway }) {
                    out[k].raised[x, default: []].append(c)
                } else {
                    out.append(ConflictCard(seq: seq, time: transcript.map { Wording.time($0.t) } ?? "", type: c.type,
                                            runway: c.runway, raised: [x: [c]]))
                }
            }
        }
        return out
    }

    /// The extractors that raised a conflict on this line, for the row's conflict symbols.
    public var conflictBy: [Extractor] {
        Extractor.allCases.filter { !(results[$0]?.conflicts.isEmpty ?? true) }
    }

    /// The row as one VoiceOver element (spec Section 7, item 6).
    public var accessibilitySummary: String {
        guard let t = transcript else { return "Line \(seq + 1), waiting for its transcript." }
        let source = t.transcriber == .apple ? ", Apple speech" : ""
        var parts = ["\(t.role.title), \(Wording.time(t.t))\(source): \(t.error ?? t.text)."]
        for x in Extractor.allCases {
            switch status(x) {
            case .waiting: parts.append("\(x.title): Working.")
            case .understood(let events): parts.append("\(x.title): \(events.joined(separator: "; ")).")
            case .nothing: parts.append("\(x.title): Nothing understood.")
            case .failed(let message): parts.append("\(x.title): \(message)")
            case .notRun: break
            }
        }
        parts += cards.map { "\($0.title) raised by \($0.raisedBy == "Both" ? "Rules and Claude" : $0.raisedBy)." }
        return parts.joined(separator: " ")
    }
}

/// A conflict as the inspector shows it: one card per line, type and runway, with who raised it.
public struct ConflictCard: Identifiable, Sendable, Equatable {
    public let seq: Int
    public let time: String
    public let type: String       // RUNWAY | READBACK
    public let runway: String?
    public var raised: [Extractor: [Conflict]]

    public var id: String { "\(seq) \(type) \(runway ?? "-")" }
    public var title: String { type == "READBACK" ? "Readback" : "Runway conflict" }
    public var symbol: String { type == "READBACK" ? "exclamationmark.triangle" : "exclamationmark.octagon.fill" }
    public var isAlert: Bool { raised.values.joined().contains { $0.severity == "alert" } }

    /// "Rules", "Claude" or "Both".
    public var raisedBy: String {
        let by = Extractor.allCases.filter { raised[$0] != nil }
        return by.count == Extractor.allCases.count ? "Both" : by.first?.title ?? ""
    }

    /// Every callsign involved, in the extractors' order, without blanks or repeats.
    public var callsigns: [String] {
        var out: [String] = []
        for x in Extractor.allCases {
            for c in raised[x] ?? [] {
                for name in c.callsigns where !name.isEmpty && !out.contains(name) { out.append(name) }
            }
        }
        return out
    }
}

/// One row of the inspector's Runways table: what each engine holds on a runway.
public struct RunwayRow: Identifiable, Sendable, Equatable {
    public let runway: String
    public var rules: String
    public var claude: String

    public var id: String { runway }

    public init(runway: String, rules: String, claude: String) {
        self.runway = runway
        self.rules = rules
        self.claude = claude
    }
}

public struct DroppedNote: Sendable, Equatable {
    public var role: Role
    public var reason: String
}

/// A session as the window shows it, built only from the helper's events, so it is the same however they interleave.
public struct SessionState: Sendable, Equatable {
    public private(set) var rows: [LineRow] = []   // in line order, undone lines removed
    public private(set) var dropped: DroppedNote?  // the last clip too short to keep, until the next line
    private var undone: Set<Int> = []

    public init() {}

    public mutating func apply(_ event: SessionEvent) {
        switch event {
        case .transcript(let t):
            dropped = nil
            update(t.seq) { $0.transcript = t }
        case .extraction(let x):
            update(x.seq) { $0.results[x.extractor] = x }
        case .undone(let seq):
            undone.insert(seq)
            rows.removeAll { $0.seq == seq }
        case .dropped(let role, _, let reason):
            dropped = DroppedNote(role: role, reason: reason)
        case .other:
            break
        }
    }

    /// Forget one extractor's results from line `seq` on, as Retry redoes them.
    public mutating func clearResults(_ x: Extractor, from seq: Int) {
        for k in rows.indices where rows[k].seq >= seq { rows[k].results[x] = nil }
    }

    public func row(_ seq: Int) -> LineRow? { rows.first { $0.seq == seq } }

    /// Every conflict card, newest line first.
    public var cards: [ConflictCard] { rows.reversed().flatMap(\.cards) }

    /// What one extractor's engine holds now: the board after the latest line it has handled.
    public func board(_ x: Extractor) -> [String: [RunwayHold]] {
        rows.last { $0.results[x] != nil }?.results[x]?.runways ?? [:]
    }

    public var runwayRows: [RunwayRow] {
        let (rules, claude) = (board(.rules), board(.claude))
        let cell = { (holds: [RunwayHold]?) in (holds ?? []).map(Wording.hold).joined(separator: "; ") }
        return Set(rules.keys).union(claude.keys).sorted()
            .map { RunwayRow(runway: $0, rules: cell(rules[$0]), claude: cell(claude[$0])) }
    }

    private mutating func update(_ seq: Int, _ change: (inout LineRow) -> Void) {
        guard !undone.contains(seq) else { return }   // a late result for an undone line
        if let k = rows.firstIndex(where: { $0.seq == seq }) {
            change(&rows[k])
            return
        }
        var row = LineRow(seq: seq)
        change(&row)
        rows.insert(row, at: rows.firstIndex { $0.seq > seq } ?? rows.endIndex)
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: `Test run with 18 tests in 0 suites passed`. On the recorded Austin stream the rules parser raises one conflict, the late 18L warning at 6:39:34, as `docs/results/pilot-cases.md` reports.

- [ ] **Step 5: Commit**

```bash
git add mac/RunwayWatchCore
git commit -m "feat: session state for the Mac app: rows, conflict cards raised by Rules, Claude or Both, runway table

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The helper over HTTP

**Files:**
- Create: `mac/RunwayWatchCore/Sources/RunwayWatchCore/HelperClient.swift`
- Test: `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/HTTPHelperClientTests.swift`

**Interfaces:**
- Consumes: Task 1's types and parser.
- Produces: `protocol HelperClient: Sendable` with `health()`, `newSession() -> String`, `sendText(session:role:t:text:source:) -> Int`, `sendAudio(session:role:t:wav:previewText:transcriber:source:) -> AudioReceipt`, `undo(session:) -> Int?`, `retry(session:extractor:seq:)`, `label(session:as:)`, `scenarios()`, `scenarioLines(_:)`, `clip(_ path) -> Data`, `events(session:after:) -> AsyncThrowingStream<StreamedEvent, any Error>`; `HelperError` (`.notFound(String)`, `.rejected(String)`, `.status(Int)`); `AudioReceipt(seq:dropped:)`; `HTTPHelperClient(base: = http://127.0.0.1:8020, session: = .shared)`. Test helpers: `StubProtocol`, `Seen`, `stubbedClient(_:_:)`, `json(_:status:)`.

- [ ] **Step 1: Write the failing tests**

Create `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/HTTPHelperClientTests.swift`:

```swift
import Foundation
import Testing
@testable import RunwayWatchCore

/// Answers every request to one made-up host, so each test gets its own stub and tests can run in parallel.
final class StubProtocol: URLProtocol, @unchecked Sendable {
    struct Reply: Sendable {
        var status = 200
        var body = Data("{}".utf8)
    }

    typealias Handler = @Sendable (URLRequest, Data) -> Reply
    private static let lock = NSLock()
    nonisolated(unsafe) private static var handlers: [String: Handler] = [:]

    static func register(_ handler: @escaping Handler) -> String {
        let host = "helper-\(UUID().uuidString.lowercased())"
        lock.withLock { handlers[host] = handler }
        return host
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let handler = Self.lock.withLock { Self.handlers[request.url!.host!] }!
        let reply = handler(request, request.httpBody ?? request.httpBodyStream.map(Self.readAll) ?? Data())
        let response = HTTPURLResponse(url: request.url!, statusCode: reply.status, httpVersion: "HTTP/1.1", headerFields: nil)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        var start = reply.body.startIndex
        while start < reply.body.endIndex {   // small chunks, as a stream arrives
            let end = reply.body.index(start, offsetBy: 97, limitedBy: reply.body.endIndex) ?? reply.body.endIndex
            client?.urlProtocol(self, didLoad: reply.body[start..<end])
            start = end
        }
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func readAll(_ stream: InputStream) -> Data {
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let n = stream.read(&buffer, maxLength: buffer.count)
            if n <= 0 { break }
            data.append(buffer, count: n)
        }
        return data
    }
}

/// The requests a stubbed helper received.
final class Seen: @unchecked Sendable {
    private let lock = NSLock()
    private var all: [(URLRequest, Data)] = []

    func add(_ request: URLRequest, _ body: Data) { lock.withLock { all.append((request, body)) } }
    var requests: [(URLRequest, Data)] { lock.withLock { all } }
}

func stubbedClient(_ seen: Seen = Seen(), _ reply: @escaping @Sendable (URLRequest) -> StubProtocol.Reply) -> HTTPHelperClient {
    let host = StubProtocol.register { request, body in
        seen.add(request, body)
        return reply(request)
    }
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [StubProtocol.self]
    return HTTPHelperClient(base: URL(string: "http://\(host)")!, session: URLSession(configuration: config))
}

func json(_ text: String, status: Int = 200) -> StubProtocol.Reply { .init(status: status, body: Data(text.utf8)) }

@Test func healthIsAGetOnTheLiveRoute() async throws {
    let seen = Seen()
    let client = stubbedClient(seen) { _ in
        json(#"{"whisper": {"status": "ready", "reason": null}, "claude": {"model": "claude-haiku-5-5", "available": true, "reason": null}}"#)
    }
    #expect(try await client.health().whisper.status == .ready)
    #expect(seen.requests[0].0.httpMethod == "GET" && seen.requests[0].0.url?.path == "/api/live/health")
}

@Test func aTypedLineIsPostedAsJSON() async throws {
    let seen = Seen()
    let client = stubbedClient(seen) { _ in json(#"{"seq": 4}"#) }
    #expect(try await client.sendText(session: "s1", role: .pilot, t: 2.5, text: "say again", source: .typed) == 4)
    let (request, body) = seen.requests[0]
    #expect(request.httpMethod == "POST" && request.url?.path == "/api/live/sessions/s1/text")
    #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")
    let sent = try JSONSerialization.jsonObject(with: body) as? [String: Any]
    #expect(sent?["role"] as? String == "pilot" && sent?["t"] as? Double == 2.5 && sent?["source"] as? String == "typed")
}

@Test func aClipIsPostedAsTheRawWAVBodyWithItsFieldsInTheQuery() async throws {
    let seen = Seen()
    let client = stubbedClient(seen) { _ in json(#"{"seq": null, "dropped": "Too short"}"#) }
    let wav = Data([1, 2, 3])
    let receipt = try await client.sendAudio(session: "s1", role: .controller, t: 3, wav: wav, previewText: "csa one",
                                             transcriber: .apple, source: .speech)
    #expect(receipt == AudioReceipt(seq: nil, dropped: "Too short"))
    let (request, body) = seen.requests[0]
    let query = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!
    #expect(request.url?.path == "/api/live/sessions/s1/audio" && body == wav)
    #expect(request.value(forHTTPHeaderField: "Content-Type") == "audio/wav")
    #expect(Dictionary(uniqueKeysWithValues: query.map { ($0.name, $0.value!) }) ==
            ["role": "controller", "t": "3.0", "preview_text": "csa one", "transcriber": "apple", "source": "speech"])
}

@Test func undoRetryAndLabelUseTheirRoutes() async throws {
    let seen = Seen()
    let client = stubbedClient(seen) { request in
        request.url!.path.hasSuffix("undo") ? json(#"{"seq": null}"#) : json(#"{"ok": true}"#)
    }
    #expect(try await client.undo(session: "s1") == nil)
    try await client.retry(session: "s1", extractor: .claude, seq: 2)
    try await client.label(session: "s1", as: "Rehearsal 1")
    #expect(seen.requests.map { $0.0.url!.path } ==
            ["/api/live/sessions/s1/undo", "/api/live/sessions/s1/retry", "/api/live/sessions/s1/label"])
    #expect(String(decoding: seen.requests[1].1, as: UTF8.self).contains(#""extractor":"claude""#))
}

@Test func anUnknownSessionIsNotFoundAndBadInputIsRejectedWithTheHelpersReason() async throws {
    let client = stubbedClient { request in
        request.url!.path.contains("nope") ? json(#"{"detail": "no live session nope"}"#, status: 404)
            : json(#"{"detail": "unknown role 'tower'; expected one of ('controller', 'pilot')"}"#, status: 422)
    }
    await #expect(throws: HelperError.notFound("no live session nope")) {
        try await client.undo(session: "nope")
    }
    await #expect(throws: HelperError.rejected("unknown role 'tower'; expected one of ('controller', 'pilot')")) {
        try await client.sendText(session: "s1", role: .controller, t: 0, text: "x", source: .typed)
    }
}

@Test func theEventStreamYieldsEveryRecordedEventAndResumesAfterAnID() async throws {
    let seen = Seen()
    let text = try fixture("austin_stream.txt")
    let client = stubbedClient(seen) { _ in .init(body: Data(text.utf8)) }
    var ids: [Int] = []
    for try await e in client.events(session: "s1", after: 41) { ids.append(e.id) }
    #expect(ids == Array(0..<95))   // the stub ignores `after`; the helper honours it
    let query = URLComponents(url: seen.requests[0].0.url!, resolvingAgainstBaseURL: false)!.queryItems!
    #expect(seen.requests[0].0.url?.path == "/api/live/sessions/s1/stream" && query == [URLQueryItem(name: "after", value: "41")])
}

@Test func scenariosTheirLinesAndClipsAreFetched() async throws {
    let seen = Seen()
    let client = stubbedClient(seen) { request in
        switch request.url!.path {
        case "/api/live/scenarios": json(#"[{"id": "austin-2023", "title": "Austin 2023 (NTSB DCA23FA149)", "lines": 31, "audio": false}]"#)
        case "/api/live/scenarios/austin-2023": json(#"[{"role": "pilot", "t": 23306.0, "text": "and tower", "preview_text": "", "audio": null}]"#)
        default: .init(body: Data([82, 73, 70, 70]))
        }
    }
    #expect(try await client.scenarios().map(\.title) == ["Austin 2023 (NTSB DCA23FA149)"])
    #expect(try await client.scenarioLines("austin-2023")[0].t == 23306)
    #expect(try await client.clip("/api/live/sessions/s1/clips/0") == Data([82, 73, 70, 70]))
    #expect(seen.requests[2].0.url?.path == "/api/live/sessions/s1/clips/0")
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: FAIL to compile: `cannot find type 'HTTPHelperClient' in scope` (and `HelperError`, `AudioReceipt`).

- [ ] **Step 3: Implement**

Create `mac/RunwayWatchCore/Sources/RunwayWatchCore/HelperClient.swift`:

```swift
import Foundation

/// What the app asks of the helper (spec Section 6; routes as built in plan A). A protocol, so `LiveSession`'s tests
/// run against a fake.
public protocol HelperClient: Sendable {
    func health() async throws -> Health
    func newSession() async throws -> String
    func sendText(session: String, role: Role, t: Double, text: String, source: LineSource) async throws -> Int
    func sendAudio(session: String, role: Role, t: Double, wav: Data, previewText: String, transcriber: Transcriber,
                   source: LineSource) async throws -> AudioReceipt
    func undo(session: String) async throws -> Int?
    func retry(session: String, extractor: Extractor, seq: Int) async throws
    func label(session: String, as label: String) async throws
    func scenarios() async throws -> [Scenario]
    func scenarioLines(_ id: String) async throws -> [ScenarioLine]
    func clip(_ path: String) async throws -> Data
    /// The session's events with an id above `after`, as they happen; ends when the connection does.
    func events(session: String, after: Int) -> AsyncThrowingStream<StreamedEvent, any Error>
}

public enum HelperError: Error, Equatable, Sendable {
    case notFound(String)    // 404: for a session, the helper restarted and no longer knows it
    case rejected(String)    // 422: the helper refused the input, with its reason
    case status(Int)
}

/// The helper's answer to a clip: the line's number, or why the clip was dropped.
public struct AudioReceipt: Codable, Sendable, Equatable {
    public var seq: Int?
    public var dropped: String?

    public init(seq: Int?, dropped: String?) {
        self.seq = seq
        self.dropped = dropped
    }
}

/// The helper over HTTP on 127.0.0.1:8020.
public struct HTTPHelperClient: HelperClient {
    public static let defaultBase = URL(string: "http://127.0.0.1:8020")!
    let base: URL
    let session: URLSession

    public init(base: URL = defaultBase, session: URLSession = .shared) {
        self.base = base
        self.session = session
    }

    public func health() async throws -> Health {
        try await send("GET", "api/live/health")
    }

    public func newSession() async throws -> String {
        let r: NewSession = try await send("POST", "api/live/sessions")
        return r.sessionId
    }

    public func sendText(session sid: String, role: Role, t: Double, text: String, source: LineSource) async throws -> Int {
        let r: Seq = try await send("POST", "api/live/sessions/\(sid)/text",
                                    json: TextLine(role: role, t: t, text: text, source: source))
        return r.seq!
    }

    public func sendAudio(session sid: String, role: Role, t: Double, wav: Data, previewText: String,
                          transcriber: Transcriber, source: LineSource) async throws -> AudioReceipt {
        let query = ["role": role.rawValue, "t": "\(t)", "preview_text": previewText, "transcriber": transcriber.rawValue,
                     "source": source.rawValue]
        return try await send("POST", "api/live/sessions/\(sid)/audio", query: query, body: wav, contentType: "audio/wav")
    }

    public func undo(session sid: String) async throws -> Int? {
        let r: Seq = try await send("POST", "api/live/sessions/\(sid)/undo")
        return r.seq
    }

    public func retry(session sid: String, extractor: Extractor, seq: Int) async throws {
        let _: Ok = try await send("POST", "api/live/sessions/\(sid)/retry", json: RetryRequest(extractor: extractor, seq: seq))
    }

    public func label(session sid: String, as label: String) async throws {
        let _: Ok = try await send("POST", "api/live/sessions/\(sid)/label", json: LabelRequest(label: label))
    }

    public func scenarios() async throws -> [Scenario] {
        try await send("GET", "api/live/scenarios")
    }

    public func scenarioLines(_ id: String) async throws -> [ScenarioLine] {
        try await send("GET", "api/live/scenarios/\(id)")
    }

    public func clip(_ path: String) async throws -> Data {
        let (data, response) = try await session.data(from: base.appending(path: path))
        try check(response, data)
        return data
    }

    public func events(session sid: String, after: Int) -> AsyncThrowingStream<StreamedEvent, any Error> {
        let request = URLRequest(url: url("api/live/sessions/\(sid)/stream", ["after": "\(after)"]))
        let urlSession = session
        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    let (bytes, response) = try await urlSession.bytes(for: request)
                    try check(response, nil)
                    var parser = ServerSentEventParser()
                    for try await byte in bytes {
                        for message in parser.feed(CollectionOfOne(byte)) { continuation.yield(try StreamedEvent(message)) }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    // MARK: - HTTP

    private func url(_ path: String, _ query: [String: String] = [:]) -> URL {
        var c = URLComponents(url: base.appending(path: path), resolvingAgainstBaseURL: false)!
        if !query.isEmpty { c.queryItems = query.sorted { $0.key < $1.key }.map { URLQueryItem(name: $0.key, value: $0.value) } }
        return c.url!
    }

    private func send<T: Decodable>(_ method: String, _ path: String, query: [String: String] = [:],
                                    json: (any Encodable)? = nil, body: Data? = nil,
                                    contentType: String? = nil) async throws -> T {
        var request = URLRequest(url: url(path, query))
        request.httpMethod = method
        if let json {
            request.httpBody = try HelperJSON.encoder.encode(json)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        } else if let body {
            request.httpBody = body
            request.setValue(contentType, forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        try check(response, data)
        return try HelperJSON.decoder.decode(T.self, from: data)
    }

    private struct NewSession: Decodable { var sessionId: String }
    private struct Seq: Decodable { var seq: Int? }
    private struct Ok: Decodable { var ok: Bool }
    private struct TextLine: Encodable { var role: Role; var t: Double; var text: String; var source: LineSource }
    private struct RetryRequest: Encodable { var extractor: Extractor; var seq: Int }
    private struct LabelRequest: Encodable { var label: String }
}

/// Throws the helper's refusal, with the reason FastAPI put in `detail` when it is a sentence.
private func check(_ response: URLResponse, _ data: Data?) throws {
    guard let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) else { return }
    struct Detail: Decodable { var detail: String }
    let reason = data.flatMap { try? JSONDecoder().decode(Detail.self, from: $0).detail } ?? ""
    switch http.statusCode {
    case 404: throw HelperError.notFound(reason)
    case 422: throw HelperError.rejected(reason.isEmpty ? "The helper refused the input." : reason)
    default: throw HelperError.status(http.statusCode)
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: `Test run with 25 tests in 0 suites passed`.

- [ ] **Step 5: Commit**

```bash
git add mac/RunwayWatchCore
git commit -m "feat: the Mac app's HTTP client for the helper's live routes and event stream

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The live session the window drives

**Files:**
- Create: `mac/RunwayWatchCore/Sources/RunwayWatchCore/LiveSession.swift`
- Test: `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/LiveSessionTests.swift`

**Interfaces:**
- Consumes: Tasks 1 to 3; the test helpers `transcript`, `extraction`, `takeoff18L`, `runwayConflict`.
- Produces: `@MainActor @Observable final class LiveSession` with `init(client:now:pause:announce:)`, read-only `state`, `sessionID`, `replaying` (the scenario title), `problem`; `elapsed`; `start()`, `newSession()`, `send(typed:as:)`, `send(clip:as:at:previewText:preferApple:) -> Int?` (discardable), `undo()`, `retry(_:from:)`, `save(as:) throws`, `replay(_:lineGap: = .seconds(2))`, `stopReplay()`. Test helpers: `FakeHelper` (`calls`, `requests`, `failNext(_:with:)`, `push(_:_:)`, `endStream(throwing:)`, `receipt`, `lines`), `ManualClock`, `Pauses`, `until(_:)`, `makeSession(...)`.

- [ ] **Step 1: Write the failing tests**

Create `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/LiveSessionTests.swift`:

```swift
import Foundation
import Testing
@testable import RunwayWatchCore

/// A helper that records what it was asked and whose event stream the test drives.
final class FakeHelper: HelperClient, @unchecked Sendable {
    typealias Stream = AsyncThrowingStream<StreamedEvent, any Error>
    private let lock = NSLock()
    private var log: [String] = []
    private var continuations: [Stream.Continuation] = []
    private var sessions = 0
    private var failures: [String: any Error] = [:]   // the next call whose log line starts with the key throws
    var receipt = AudioReceipt(seq: 0, dropped: nil)
    var lines: [ScenarioLine] = []

    var calls: [String] { lock.withLock { log } }
    /// The calls without the stream connections, which happen on their own schedule.
    var requests: [String] { calls.filter { !$0.hasPrefix("events") } }

    func failNext(_ prefix: String, with error: any Error) { lock.withLock { failures[prefix] = error } }

    private func record(_ line: String) throws {
        try lock.withLock {
            log.append(line)
            if let key = failures.keys.first(where: { line.hasPrefix($0) }) { throw failures.removeValue(forKey: key)! }
        }
    }

    func push(_ id: Int, _ event: SessionEvent) {
        _ = lock.withLock { continuations.last }?.yield(StreamedEvent(id: id, event: event))
    }

    func endStream(throwing error: (any Error)? = nil) {
        let c = lock.withLock { continuations.last }
        if let error { c?.finish(throwing: error) } else { c?.finish() }
    }

    func health() async throws -> Health { fatalError("not used") }

    func newSession() async throws -> String {
        try record("newSession")
        return lock.withLock { sessions += 1; return "s\(sessions)" }
    }

    func sendText(session: String, role: Role, t: Double, text: String, source: LineSource) async throws -> Int {
        try record("text \(session) \(role.rawValue) \(t) \(source.rawValue): \(text)")
        return 0
    }

    func sendAudio(session: String, role: Role, t: Double, wav: Data, previewText: String, transcriber: Transcriber,
                   source: LineSource) async throws -> AudioReceipt {
        try record("audio \(session) \(role.rawValue) \(t) \(source.rawValue) \(transcriber.rawValue) \(wav.count) bytes: \(previewText)")
        return receipt
    }

    func undo(session: String) async throws -> Int? { try record("undo \(session)"); return nil }
    func retry(session: String, extractor: Extractor, seq: Int) async throws { try record("retry \(session) \(extractor.rawValue) \(seq)") }
    func label(session: String, as label: String) async throws { try record("label \(session): \(label)") }
    func scenarios() async throws -> [Scenario] { [] }
    func scenarioLines(_ id: String) async throws -> [ScenarioLine] { try record("lines \(id)"); return lines }
    func clip(_ path: String) async throws -> Data { try record("clip \(path)"); return Data([0, 1, 2, 3]) }

    func events(session: String, after: Int) -> Stream {
        let (stream, continuation) = Stream.makeStream()
        lock.withLock {
            log.append("events \(session) after \(after)")
            continuations.append(continuation)
        }
        return stream
    }
}

/// A clock the test moves by hand.
final class ManualClock: @unchecked Sendable {
    private let lock = NSLock()
    private var t = 1000.0
    var now: Double { lock.withLock { t } }
    func advance(_ s: Double) { lock.withLock { t += s } }
}

/// Waits (up to 2 s) for the session's tasks to catch up.
@MainActor
func until(_ condition: @MainActor () -> Bool) async throws {
    for _ in 0..<2000 where !condition() { try await Task.sleep(for: .milliseconds(1)) }
    #expect(condition())
}

@MainActor
func makeSession(_ helper: FakeHelper = FakeHelper(), clock: ManualClock = ManualClock(),
                 pauses: Pauses = Pauses()) -> LiveSession {
    LiveSession(client: helper, now: { clock.now }, pause: { d in pauses.add(d) })
}

final class Pauses: @unchecked Sendable {
    private let lock = NSLock()
    private var all: [Duration] = []
    func add(_ d: Duration) { lock.withLock { all.append(d) } }
    var durations: [Duration] { lock.withLock { all } }
}

@MainActor @Test func startingOpensAHelperSessionAndFollowsItsStream() async throws {
    let helper = FakeHelper()
    let session = makeSession(helper)
    await session.start()
    #expect(session.sessionID == "s1")
    try await until { helper.calls.contains("events s1 after -1") }
    helper.push(0, transcript(0))
    helper.push(1, extraction(0, .rules, [takeoff18L]))
    try await until { session.state.rows.first?.status(.rules) == .understood(["TAKEOFF 18L southwest seven zero eight"]) }
}

@MainActor @Test func aTypedLineCarriesTheSecondsSinceTheSessionStarted() async throws {
    let (helper, clock) = (FakeHelper(), ManualClock())
    let session = makeSession(helper, clock: clock)
    await session.start()
    clock.advance(12.5)
    await session.send(typed: "  CSA 123 runway 31 cleared to land ", as: .controller)
    await session.send(typed: "   ", as: .pilot)
    #expect(helper.calls.filter { $0.hasPrefix("text") } == ["text s1 controller 12.5 typed: CSA 123 runway 31 cleared to land"])
}

@MainActor @Test func aClipIsSentWithApplesTextAndTheTranscriberAsked() async throws {
    let helper = FakeHelper()
    let session = makeSession(helper)
    await session.start()
    helper.receipt = AudioReceipt(seq: 7, dropped: nil)
    #expect(await session.send(clip: Data(count: 3200), as: .pilot, at: 4, previewText: "say again", preferApple: true) == 7)
    #expect(helper.requests.last == "audio s1 pilot 4.0 speech apple 3200 bytes: say again")
    helper.receipt = AudioReceipt(seq: nil, dropped: "Too short")   // the dropped event says why
    #expect(await session.send(clip: Data(count: 32), as: .pilot, at: 9, previewText: "", preferApple: false) == nil)
}

@MainActor @Test func undoAndRetryGoToTheHelperAndRetryShowsTheRedoneLinesAsWaiting() async throws {
    let helper = FakeHelper()
    let session = makeSession(helper)
    await session.start()
    try await until { helper.calls.contains("events s1 after -1") }
    helper.push(0, transcript(0))
    helper.push(1, extraction(0, .claude, error: "APIConnectionError: Connection error."))
    try await until { session.state.rows.first?.results[.claude] != nil }
    await session.retry(.claude, from: 0)
    #expect(session.state.rows[0].status(.claude) == .waiting)
    await session.undo()
    #expect(helper.requests.suffix(2) == ["retry s1 claude 0", "undo s1"])
}

@MainActor @Test func aDroppedConnectionResumesAfterTheLastEventItSaw() async throws {
    let helper = FakeHelper()
    let pauses = Pauses()
    let session = makeSession(helper, pauses: pauses)
    await session.start()
    try await until { helper.calls.contains("events s1 after -1") }
    helper.push(0, transcript(0))
    helper.push(1, extraction(0, .rules))
    try await until { session.state.rows.first?.results[.rules] != nil }
    helper.endStream(throwing: URLError(.networkConnectionLost))
    try await until { helper.calls.contains("events s1 after 1") }
    #expect(pauses.durations == [.seconds(1)])
}

@MainActor @Test func aHelperThatForgotTheSessionGetsANewOneAndTheWindowSaysWhy() async throws {
    let helper = FakeHelper()
    let session = makeSession(helper)
    await session.start()
    try await until { helper.calls.contains("events s1 after -1") }
    helper.push(0, transcript(0))
    try await until { !session.state.rows.isEmpty }
    helper.endStream(throwing: HelperError.notFound("no live session s1"))
    try await until { session.sessionID == "s2" }
    #expect(session.state.rows.isEmpty && session.problem == "The helper restarted, so a new session started.")
    try await until { helper.calls.contains("events s2 after -1") }
    helper.failNext("text", with: HelperError.notFound("no live session s2"))
    await session.send(typed: "say again", as: .pilot)
    #expect(session.sessionID == "s3")
}

@MainActor @Test func aRefusedLineShowsTheHelpersReasonUntilTheNextLineGoesThrough() async throws {
    let helper = FakeHelper()
    let session = makeSession(helper)
    await session.start()
    helper.failNext("text", with: HelperError.rejected("unknown source 'radio'"))
    await session.send(typed: "say again", as: .pilot)
    #expect(session.problem == "unknown source 'radio'")
    await session.send(typed: "say again", as: .pilot)
    #expect(session.problem == nil)
}

@MainActor @Test func anUnreachableHelperIsReportedInline() async throws {
    let helper = FakeHelper()
    let session = makeSession(helper)
    await session.start()
    helper.failNext("undo", with: URLError(.cannotConnectToHost))
    await session.undo()
    #expect(session.problem == "The helper is not responding. Wait for it to restart, or use Restart Helper.")
}

@MainActor @Test func aReplayStartsANewSessionAndSendsEachLineTwoSecondsApartWithItsOwnTime() async throws {
    let (helper, pauses) = (FakeHelper(), Pauses())
    helper.lines = [ScenarioLine(role: .controller, t: 23674, text: "fedex one eight left cleared to land", previewText: "", audio: nil),
                    ScenarioLine(role: .pilot, t: 23700, text: "cleared to land", previewText: "cleared to land",
                                 audio: "/api/live/sessions/old/clips/1")]
    let session = makeSession(helper, pauses: pauses)
    await session.start()
    await session.replay(Scenario(id: "austin-2023", title: "Austin 2023", lines: 2, audio: false))
    #expect(session.replaying == "Austin 2023")
    try await until { session.replaying == nil }
    #expect(helper.requests ==
            ["newSession", "newSession", "lines austin-2023",
             "text s2 controller 23674.0 replay: fedex one eight left cleared to land",
             "clip /api/live/sessions/old/clips/1", "audio s2 pilot 23700.0 replay whisper 4 bytes: cleared to land"])
    #expect(pauses.durations == [.seconds(2)])
}

@MainActor @Test func stoppingAReplayLeavesTheRestUnsent() async throws {
    let helper = FakeHelper()
    helper.lines = (0..<5).map { ScenarioLine(role: .pilot, t: Double($0), text: "line \($0)", previewText: "", audio: nil) }
    let session = LiveSession(client: helper, now: { 0 }, pause: { _ in try await Task.sleep(for: .seconds(10)) })
    await session.start()
    await session.replay(Scenario(id: "x", title: "X", lines: 5, audio: false))
    try await until { helper.calls.contains { $0.hasSuffix("replay: line 0") } }
    session.stopReplay()
    #expect(session.replaying == nil)
    try await Task.sleep(for: .milliseconds(20))
    #expect(helper.calls.filter { $0.hasPrefix("text") }.count == 1)
}

@MainActor @Test func eachNewConflictIsAnnouncedOnce() async throws {
    let helper = FakeHelper()
    var spoken: [String] = []
    let session = LiveSession(client: helper, now: { 0 }, pause: { _ in }, announce: { spoken.append($0) })
    await session.start()
    try await until { helper.calls.contains("events s1 after -1") }
    helper.push(0, transcript(0))
    helper.push(1, extraction(0, .claude, [takeoff18L], conflicts: [runwayConflict()]))
    helper.push(2, extraction(0, .rules, [takeoff18L], conflicts: [runwayConflict("warning")]))
    try await until { session.state.cards.first?.raisedBy == "Both" }
    #expect(spoken == ["Runway conflict on runway 18L, raised by Claude."])
}

@MainActor @Test func savingLabelsTheSessionForTheReplayMenu() async throws {
    let helper = FakeHelper()
    let session = makeSession(helper)
    await session.start()
    try await session.save(as: "Rehearsal 1")
    #expect(helper.requests.last == "label s1: Rehearsal 1")
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: FAIL to compile: `cannot find type 'LiveSession' in scope`.

- [ ] **Step 3: Implement**

Create `mac/RunwayWatchCore/Sources/RunwayWatchCore/LiveSession.swift`:

```swift
import Foundation
import Observation

/// One live demo session as the window drives it (spec Sections 3 to 6). It opens a helper session, follows its event
/// stream into `state` (resuming after a dropped connection), and sends lines, Undo, Retry and replays. Anything that
/// goes wrong is one sentence in `problem`, shown inline, never an alert.
@MainActor @Observable
public final class LiveSession {
    public private(set) var state = SessionState()
    public private(set) var sessionID: String?
    public private(set) var replaying: String?   // the scenario's title while its lines are being sent
    public private(set) var problem: String?

    @ObservationIgnored private let client: any HelperClient
    @ObservationIgnored private let now: @Sendable () -> Double
    @ObservationIgnored private let pause: @Sendable (Duration) async throws -> Void
    @ObservationIgnored private let announce: @MainActor (String) -> Void
    @ObservationIgnored private var startedAt = 0.0
    @ObservationIgnored private var lastEventID = -1
    @ObservationIgnored private var streamTask: Task<Void, Never>?
    @ObservationIgnored private var replayTask: Task<Void, Never>?

    /// `now` is in seconds; `pause` waits between replayed lines and before reconnecting; `announce` tells VoiceOver
    /// about each new conflict (spec Section 7, item 6).
    public init(client: any HelperClient,
                now: @escaping @Sendable () -> Double = { Date().timeIntervalSinceReferenceDate },
                pause: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
                announce: @escaping @MainActor (String) -> Void = { _ in }) {
        self.client = client
        self.now = now
        self.pause = pause
        self.announce = announce
    }

    /// Seconds since the session started: a spoken or typed line's `t`.
    public var elapsed: Double { now() - startedAt }

    public func start() async {
        if sessionID == nil { await newSession() }
    }

    public func newSession() async {
        stopReplay()
        await open(note: nil)
    }

    public func send(typed text: String, as role: Role) async {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        let t = elapsed
        await call { sid in _ = try await self.client.sendText(session: sid, role: role, t: t, text: text, source: .typed) }
    }

    /// A recorded clip, `t` taken when the talk key went down. The line's number, or nil if the helper dropped the
    /// clip (a `dropped` event says why) or the request failed (`problem` says why).
    @discardableResult
    public func send(clip wav: Data, as role: Role, at t: Double, previewText: String, preferApple: Bool) async -> Int? {
        await call { sid in
            try await self.client.sendAudio(session: sid, role: role, t: t, wav: wav, previewText: previewText,
                                            transcriber: preferApple ? .apple : .whisper, source: .speech).seq
        } ?? nil
    }

    public func undo() async {
        await call { sid in _ = try await self.client.undo(session: sid) }
    }

    /// Redo one extractor from line `seq` on; its rows show as waiting until the new results arrive.
    public func retry(_ x: Extractor, from seq: Int) async {
        state.clearResults(x, from: seq)
        await call { sid in try await self.client.retry(session: sid, extractor: x, seq: seq) }
    }

    /// Name the session for the Replay menu (File > Save Session As...).
    public func save(as label: String) async throws {
        guard let sid = sessionID else { return }
        try await client.label(session: sid, as: label)
    }

    /// Replay a scenario in a new session: one line every `lineGap`, each with the script's own time. A saved session's
    /// spoken lines go through Whisper again from their clips; the other lines are sent as text.
    public func replay(_ scenario: Scenario, lineGap: Duration = .seconds(2)) async {
        await newSession()
        guard sessionID != nil else { return }
        let lines: [ScenarioLine]
        do {
            lines = try await client.scenarioLines(scenario.id)
        } catch {
            report(error)
            return
        }
        replaying = scenario.title
        replayTask = Task { [weak self] in
            for (k, line) in lines.enumerated() {
                guard let self, !Task.isCancelled else { return }
                if k > 0 {
                    do { try await self.pause(lineGap) } catch { return }
                }
                await self.call { sid in
                    if let audio = line.audio {
                        let wav = try await self.client.clip(audio)
                        _ = try await self.client.sendAudio(session: sid, role: line.role, t: line.t, wav: wav,
                                                            previewText: line.previewText, transcriber: .whisper,
                                                            source: .replay)
                    } else {
                        _ = try await self.client.sendText(session: sid, role: line.role, t: line.t, text: line.text,
                                                           source: .replay)
                    }
                }
            }
            self?.replaying = nil
        }
    }

    public func stopReplay() {
        replayTask?.cancel()
        replayTask = nil
        replaying = nil
    }

    // MARK: - Session and stream

    private func open(note: String?) async {
        streamTask?.cancel()
        streamTask = nil
        (state, lastEventID, sessionID) = (SessionState(), -1, nil)
        do {
            let sid = try await client.newSession()
            (sessionID, startedAt, problem) = (sid, now(), note)
            follow(sid)
        } catch {
            report(error)
        }
    }

    private func follow(_ sid: String) {
        streamTask = Task { [weak self] in
            while let self, !Task.isCancelled, self.sessionID == sid {
                do {
                    for try await e in self.client.events(session: sid, after: self.lastEventID) {
                        guard self.sessionID == sid else { return }
                        self.receive(e)
                    }
                } catch HelperError.notFound {
                    if self.sessionID == sid { await self.sessionForgotten() }
                    return
                } catch {
                    if Task.isCancelled { return }
                }
                do { try await self.pause(.seconds(1)) } catch { return }   // then resume after the last event seen
            }
        }
    }

    private func receive(_ e: StreamedEvent) {
        lastEventID = e.id
        guard case .extraction(let x) = e.event, !x.conflicts.isEmpty else {
            state.apply(e.event)
            return
        }
        let before = Set(state.cards.map(\.id))
        state.apply(e.event)
        for card in state.cards where !before.contains(card.id) {
            announce("\(card.title)\(card.runway.map { " on runway \($0)" } ?? ""), raised by \(card.raisedBy).")
        }
    }

    /// The helper restarted and no longer knows the session: start a new one and say so.
    private func sessionForgotten() async {
        stopReplay()
        await open(note: "The helper restarted, so a new session started.")
    }

    /// One request for the current session: its result, or nil if it failed. A success clears the last problem.
    @discardableResult
    private func call<T>(_ request: (String) async throws -> T) async -> T? {
        guard let sid = sessionID else {
            problem = "No session is open. Choose File > New Session."
            return nil
        }
        do {
            let result = try await request(sid)
            problem = nil
            return result
        } catch HelperError.notFound {
            await sessionForgotten()
        } catch {
            report(error)
        }
        return nil
    }

    private func report(_ error: any Error) {
        switch error {
        case is CancellationError: break
        case HelperError.rejected(let reason): problem = reason
        case HelperError.notFound(let reason) where !reason.isEmpty: problem = reason
        case HelperError.status(let code): problem = "The helper failed (HTTP \(code)). Try again, or use Restart Helper."
        default: problem = "The helper is not responding. Wait for it to restart, or use Restart Helper."
        }
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mac/RunwayWatchCore && swift test` three times (the session runs tasks; all three runs must pass).
Expected: `Test run with 37 tests in 0 suites passed` each time.

- [ ] **Step 5: Commit**

```bash
git add mac/RunwayWatchCore
git commit -m "feat: the Mac app's live session: stream that resumes, lines, undo, retry, paced replays, announcements

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Using or launching the helper

**Files:**
- Create: `mac/RunwayWatchCore/Sources/RunwayWatchCore/HelperSupervisor.swift`
- Test: `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/HelperSupervisorTests.swift`

**Interfaces:**
- Consumes: Task 1's `Health`; Task 2's `Wording.reason` and `Wording.failure`; Task 4's `until`.
- Produces: `@MainActor protocol HelperLauncher` (`launch(onExit:) throws -> any RunningHelper`), `@MainActor protocol RunningHelper` (`terminate()`); `@MainActor @Observable final class HelperSupervisor` with `init(health:launcher:pause:startPolls: = 120)`, `status: Status` (`.starting`, `.running(Health)`, `.stopped(String)`), `attached`, `start()`, `restart()`, `stop()`; `Status.talkBlockedReason: String?` and `Status.notes: [String]`; `HelperCommand(executable:arguments:environment:directory:log:)` and `HelperCommand.uvicorn(repo:apiKey:environment:)`; `@MainActor final class ProcessLauncher(command:)`.

- [ ] **Step 1: Write the failing tests**

Create `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/HelperSupervisorTests.swift`:

```swift
import Foundation
import Testing
@testable import RunwayWatchCore

let readyHealth = Health(whisper: .init(status: .ready, reason: nil),
                         claude: .init(model: "claude-haiku-5-5", available: true, reason: nil))

/// A helper process that answers health checks only while "running".
@MainActor
final class FakeProcesses: HelperLauncher {
    var launches = 0
    var running = false
    var whisper = Health.WhisperStatus.ready
    var failLaunch = false
    private var onExit: (@MainActor @Sendable () -> Void)?

    func launch(onExit: @escaping @MainActor @Sendable () -> Void) throws -> any RunningHelper {
        launches += 1
        if failLaunch { throw CocoaError(.fileNoSuchFile) }
        running = true
        self.onExit = onExit
        return Handle(owner: self)
    }

    func crash() {
        running = false
        onExit?()
    }

    final class Handle: RunningHelper {
        let owner: FakeProcesses
        init(owner: FakeProcesses) { self.owner = owner }
        func terminate() { owner.running = false }
    }
}

@MainActor
final class Flag {
    var on = false
}

@MainActor
func supervisor(_ processes: FakeProcesses, alreadyRunning: Bool = false) -> HelperSupervisor {
    let external = alreadyRunning
    return HelperSupervisor(health: { @MainActor in
        guard processes.running || external else { throw URLError(.cannotConnectToHost) }
        var h = readyHealth
        h.whisper.status = processes.whisper
        return h
    }, launcher: processes, pause: { _ in try await Task.sleep(for: .milliseconds(1)) }, startPolls: 20)
}

@MainActor @Test func aHelperAlreadyRunningIsUsedAsItIs() async throws {
    let processes = FakeProcesses()
    let s = supervisor(processes, alreadyRunning: true)
    s.start()
    try await until { s.status == .running(readyHealth) }
    #expect(processes.launches == 0 && s.attached)
}

@MainActor @Test func otherwiseTheAppLaunchesTheHelperAndWaitsForItToAnswer() async throws {
    let processes = FakeProcesses()
    let s = supervisor(processes)
    #expect(s.status == .starting && s.status.talkBlockedReason == "Waiting for the helper to start.")
    s.start()
    try await until { s.status == .running(readyHealth) }
    #expect(processes.launches == 1 && !s.attached && s.status.talkBlockedReason == nil)
}

@MainActor @Test func aCrashIsRestartedOnceThenTheWindowOffersRestartHelper() async throws {
    let processes = FakeProcesses()
    let s = supervisor(processes)
    s.start()
    try await until { s.status == .running(readyHealth) }
    processes.crash()
    try await until { processes.launches == 2 && s.status == .running(readyHealth) }
    processes.crash()
    try await until { s.status == .stopped("The helper stopped twice. Check data/live/helper.log, then use Restart Helper.") }
    #expect(processes.launches == 2 && s.status.talkBlockedReason == "The helper is not running.")
    s.restart()
    try await until { processes.launches == 3 && s.status == .running(readyHealth) }
}

@MainActor @Test func aHelperThatCannotStartSaysWhy() async throws {
    let processes = FakeProcesses()
    processes.failLaunch = true
    let s = supervisor(processes)
    s.start()
    try await until { if case .stopped = s.status { true } else { false } }
    #expect(s.status == .stopped("The helper could not start: The file doesn’t exist. Check the repository path in Settings."))
}

@MainActor @Test func aHelperThatNeverAnswersIsStoppedAfterTheStartTimeout() async throws {
    let processes = FakeProcesses()
    let s = HelperSupervisor(health: { throw URLError(.cannotConnectToHost) }, launcher: processes,
                             pause: { _ in }, startPolls: 3)
    s.start()
    try await until { if case .stopped = s.status { true } else { false } }
    #expect(s.status == .stopped("The helper did not answer. Check data/live/helper.log, then use Restart Helper."))
    #expect(!processes.running)
}

@MainActor @Test func quittingStopsOnlyAHelperTheAppLaunched() async throws {
    let processes = FakeProcesses()
    let s = supervisor(processes)
    s.start()
    try await until { s.status == .running(readyHealth) }
    s.stop()
    #expect(!processes.running && processes.launches == 1)
}

@Test func theStatusSaysWhatTheWindowShows() {
    func health(_ whisper: Health.WhisperStatus, _ reason: String? = nil, claude: String? = nil) -> HelperSupervisor.Status {
        .running(Health(whisper: .init(status: whisper, reason: reason),
                        claude: .init(model: "claude-haiku-5-5", available: claude == nil, reason: claude)))
    }
    #expect(health(.loading).notes == ["Loading speech model..."] && health(.loading).talkBlockedReason == "Loading speech model...")
    #expect(health(.failed, "FileNotFoundError: no Whisper weights in data/models").notes ==
            ["Speech model unavailable: no Whisper weights in data/models. Lines use Apple speech."])
    #expect(health(.failed).talkBlockedReason == nil)
    #expect(health(.ready, claude: "ANTHROPIC_API_KEY not set").notes ==
            ["Claude unavailable: ANTHROPIC_API_KEY not set. Add the API key in Settings."])
    #expect(health(.ready).notes == [] && HelperSupervisor.Status.starting.notes == ["Starting the helper..."])
}

@Test func theHelperRunsFromTheRepositorysVirtualEnvironmentWithTheKeyFromSettings() {
    let repo = URL(fileURLWithPath: "/Users/me/nst2046-proj")
    let c = HelperCommand.uvicorn(repo: repo, apiKey: "sk-test", environment: ["PATH": "/usr/bin", "ANTHROPIC_API_KEY": "old"])
    #expect(c.executable.path == "/Users/me/nst2046-proj/.venv/bin/python")
    #expect(c.arguments == ["-m", "uvicorn", "atcdb.api:app", "--host", "127.0.0.1", "--port", "8020"])
    #expect(c.environment == ["PATH": "/usr/bin", "ANTHROPIC_API_KEY": "sk-test", "PYTHONUNBUFFERED": "1"])
    #expect(c.directory == repo && c.log.path == "/Users/me/nst2046-proj/data/live/helper.log")
    let inherited = HelperCommand.uvicorn(repo: repo, apiKey: "", environment: ["ANTHROPIC_API_KEY": "from-shell"])
    #expect(inherited.environment["ANTHROPIC_API_KEY"] == "from-shell")
}

@MainActor @Test func theProcessLauncherRunsTheCommandLogsItAndReportsAnExit() async throws {
    let dir = FileManager.default.temporaryDirectory.appending(path: "rw-\(UUID().uuidString)")
    let command = HelperCommand(executable: URL(fileURLWithPath: "/bin/sh"), arguments: ["-c", "echo started; exit 3"],
                                environment: [:], directory: dir, log: dir.appending(path: "data/live/helper.log"))
    try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    let exited = Flag()
    _ = try ProcessLauncher { command }.launch { exited.on = true }
    try await until { exited.on }
    #expect(try String(contentsOf: command.log, encoding: .utf8) == "started\n")
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: FAIL to compile: `cannot find type 'HelperLauncher' in scope` (and `HelperSupervisor`, `HelperCommand`, `ProcessLauncher`).

- [ ] **Step 3: Implement**

Create `mac/RunwayWatchCore/Sources/RunwayWatchCore/HelperSupervisor.swift`:

```swift
import Foundation
import Observation

/// Starts helper processes. The app's launcher runs the repo's Python (`ProcessLauncher`); tests use a fake.
@MainActor
public protocol HelperLauncher: AnyObject {
    /// Starts the helper. `onExit` runs if it exits by itself, not when it is terminated.
    func launch(onExit: @escaping @MainActor @Sendable () -> Void) throws -> any RunningHelper
}

@MainActor
public protocol RunningHelper: AnyObject {
    func terminate()
}

/// Keeps the helper running (spec Section 6). A helper that already answers on 127.0.0.1:8020, such as one started
/// from a terminal, is used as it is; otherwise the app launches its own and stops it at quit. A helper that exits is
/// restarted once; after that the window offers Restart Helper.
@MainActor @Observable
public final class HelperSupervisor {
    public enum Status: Equatable, Sendable {
        case starting
        case running(Health)
        case stopped(String)   // why, and what to do
    }

    public private(set) var status = Status.starting
    public private(set) var attached = false   // using a helper the app did not launch

    @ObservationIgnored private let health: @Sendable () async throws -> Health
    @ObservationIgnored private let launcher: any HelperLauncher
    @ObservationIgnored private let pause: @Sendable (Duration) async throws -> Void
    @ObservationIgnored private let startPolls: Int
    @ObservationIgnored private var process: (any RunningHelper)?
    @ObservationIgnored private var launches = 0   // since start or Restart Helper: the first, then one restart
    @ObservationIgnored private var task: Task<Void, Never>?

    /// `startPolls` half-second checks are allowed for a launched helper to answer (60 s by default: the first launch
    /// imports PyTorch).
    public init(health: @escaping @Sendable () async throws -> Health, launcher: any HelperLauncher,
                pause: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) },
                startPolls: Int = 120) {
        self.health = health
        self.launcher = launcher
        self.pause = pause
        self.startPolls = startPolls
    }

    public func start() {
        task?.cancel()
        task = Task { [weak self] in await self?.run() }
    }

    /// The Restart Helper button: a fresh start, with its automatic restart.
    public func restart() {
        process?.terminate()
        process = nil
        launches = 0
        set(.starting)
        start()
    }

    /// At quit: stop the helper if the app launched it.
    public func stop() {
        task?.cancel()
        task = nil
        process?.terminate()
        process = nil
    }

    private func run() async {
        var waited = 0
        while !Task.isCancelled {
            if let h = try? await health() {
                attached = launches == 0
                set(.running(h))
                waited = 0
                let loading = h.whisper.status == .idle || h.whisper.status == .loading
                do { try await pause(loading ? .seconds(1) : .seconds(5)) } catch { return }
                continue
            }
            if process == nil {
                guard launches < 2 else {
                    set(.stopped("The helper stopped twice. Check data/live/helper.log, then use Restart Helper."))
                    return
                }
                do {
                    process = try launcher.launch { [weak self] in self?.exited() }
                } catch {
                    set(.stopped("The helper could not start: \(error.localizedDescription) Check the repository path in Settings."))
                    return
                }
                launches += 1
                set(.starting)
                waited = 0
            }
            waited += 1
            if waited > startPolls {
                process?.terminate()
                process = nil
                set(.stopped("The helper did not answer. Check data/live/helper.log, then use Restart Helper."))
                return
            }
            do { try await pause(.milliseconds(500)) } catch { return }
        }
    }

    private func exited() {
        process = nil
        set(.starting)
        start()   // check at once rather than at the next poll
    }

    private func set(_ new: Status) {
        if status != new { status = new }
    }
}

extension HelperSupervisor.Status {
    /// Why Talk is unavailable, or nil. A failed speech model does not block Talk: lines use Apple speech.
    public var talkBlockedReason: String? {
        switch self {
        case .starting: "Waiting for the helper to start."
        case .stopped: "The helper is not running."
        case .running(let h): h.whisper.status == .idle || h.whisper.status == .loading ? "Loading speech model..." : nil
        }
    }

    /// The inline notes above the transcript (spec Section 6, Failures).
    public var notes: [String] {
        switch self {
        case .starting: return ["Starting the helper..."]
        case .stopped(let reason): return [reason]
        case .running(let h):
            var out: [String] = []
            switch h.whisper.status {
            case .idle, .loading: out.append("Loading speech model...")
            case .failed: out.append("Speech model unavailable: \(Wording.reason(h.whisper.reason ?? "unknown error")). Lines use Apple speech.")
            case .ready: break
            }
            if !h.claude.available { out.append(Wording.failure(.claude, h.claude.reason ?? "unknown error")) }
            return out
        }
    }
}

/// How the app runs the helper: the repo's .venv Python running uvicorn on 127.0.0.1:8020 (spec Section 2), with the
/// API key from Settings, since an app started from the Dock cannot see the shell's environment.
public struct HelperCommand: Equatable, Sendable {
    public var executable: URL
    public var arguments: [String]
    public var environment: [String: String]
    public var directory: URL
    public var log: URL

    public init(executable: URL, arguments: [String], environment: [String: String], directory: URL, log: URL) {
        self.executable = executable
        self.arguments = arguments
        self.environment = environment
        self.directory = directory
        self.log = log
    }

    /// An empty `apiKey` keeps whatever key `environment` already has.
    public static func uvicorn(repo: URL, apiKey: String, environment: [String: String]) -> HelperCommand {
        var env = environment
        if !apiKey.isEmpty { env["ANTHROPIC_API_KEY"] = apiKey }
        env["PYTHONUNBUFFERED"] = "1"
        return HelperCommand(executable: repo.appending(path: ".venv/bin/python"),
                             arguments: ["-m", "uvicorn", "atcdb.api:app", "--host", "127.0.0.1", "--port", "8020"],
                             environment: env, directory: repo, log: repo.appending(path: "data/live/helper.log"))
    }
}

/// Runs a `HelperCommand` as a child process, its output appended to the command's log.
@MainActor
public final class ProcessLauncher: HelperLauncher {
    private let command: @MainActor () -> HelperCommand

    /// `command` is read at each launch, so a key or path changed in Settings applies on the next start.
    public init(command: @escaping @MainActor () -> HelperCommand) {
        self.command = command
    }

    public func launch(onExit: @escaping @MainActor @Sendable () -> Void) throws -> any RunningHelper {
        let c = command()
        let files = FileManager.default
        try files.createDirectory(at: c.log.deletingLastPathComponent(), withIntermediateDirectories: true)
        if !files.fileExists(atPath: c.log.path) { files.createFile(atPath: c.log.path, contents: nil) }
        let log = try FileHandle(forWritingTo: c.log)
        try log.seekToEnd()
        let process = Process()
        process.executableURL = c.executable
        process.arguments = c.arguments
        process.environment = c.environment
        process.currentDirectoryURL = c.directory
        process.standardOutput = log
        process.standardError = log
        let handle = LaunchedHelper(process)
        process.terminationHandler = { _ in
            Task { @MainActor in
                if !handle.stopping { onExit() }
            }
        }
        try process.run()
        return handle
    }
}

@MainActor
final class LaunchedHelper: RunningHelper {
    let process: Process
    var stopping = false

    init(_ process: Process) {
        self.process = process
    }

    func terminate() {
        stopping = true
        process.terminate()
    }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: `Test run with 46 tests in 0 suites passed`.

- [ ] **Step 5: Commit**

```bash
git add mac/RunwayWatchCore
git commit -m "feat: the Mac app uses a running helper or launches its own, restarting it once

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Talk keys, text size and the clip format

**Files:**
- Create: `mac/RunwayWatchCore/Sources/RunwayWatchCore/TalkInput.swift`
- Test: `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/TalkInputTests.swift`

**Interfaces:**
- Consumes: Task 1's `Role`.
- Produces: `TalkKeys` (`leftOption = 0x20`, `rightOption = 0x40`, `update(_ rawFlags) -> [Change]`, `Change` `.down(Role)`, `.up(Role)`, `.cancelled(Role)`); `TextScale` (`steps` 1 to 2 in quarters, `factor`, `init(factor:)` clamped, `canGrow`, `canShrink`, `bigger()`, `smaller()`, `actualSize()`, `points(_ Style)`; `Style` `.title3`, `.headline`, `.body`, `.callout`, `.subheadline`, `.caption`); `WAV.sampleRate = 16000`, `WAV.encode(_ samples: [Float]) -> Data`, `WAV.seconds(samples:)`.

- [ ] **Step 1: Write the failing tests**

Create `mac/RunwayWatchCore/Tests/RunwayWatchCoreTests/TalkInputTests.swift`:

```swift
import Foundation
import Testing
@testable import RunwayWatchCore

let option: UInt = 1 << 19   // NSEvent.ModifierFlags.option
let command: UInt = 1 << 20

@Test func leftOptionTalksAsTowerAndRightOptionAsPilot() {
    var keys = TalkKeys()
    #expect(keys.update(option | TalkKeys.leftOption) == [.down(.controller)])
    #expect(keys.update(0) == [.up(.controller)])
    #expect(keys.update(option | TalkKeys.rightOption) == [.down(.pilot)])
    #expect(keys.update(0) == [.up(.pilot)])
}

@Test func theSecondKeyIsIgnoredWhileTheFirstIsHeld() {
    var keys = TalkKeys()
    #expect(keys.update(option | TalkKeys.leftOption) == [.down(.controller)])
    #expect(keys.update(option | TalkKeys.leftOption | TalkKeys.rightOption) == [])
    #expect(keys.update(option | TalkKeys.rightOption) == [.up(.controller)])   // releasing the first ends its line
    #expect(keys.update(0) == [])
}

@Test func optionInAShortcutCancelsRatherThanTalks() {
    var keys = TalkKeys()
    #expect(keys.update(command) == [])
    #expect(keys.update(command | option | TalkKeys.leftOption) == [])   // ⌥⌘I: never a line
    #expect(keys.update(0) == [])
    #expect(keys.update(option | TalkKeys.leftOption) == [.down(.controller)])
    #expect(keys.update(option | TalkKeys.leftOption | command) == [.cancelled(.controller)])
    #expect(keys.update(0) == [])
}

@Test func textSizeStepsUpToTwiceTheDefault() {
    var size = TextScale()
    #expect(size.factor == 1 && !size.canShrink)
    for _ in 0..<6 { size.bigger() }
    #expect(size.factor == 2 && !size.canGrow)
    size.smaller()
    #expect(size.factor == 1.75)
    size.actualSize()
    #expect(size.factor == 1)
    #expect(TextScale(factor: 1.5).points(.body) == 19.5 && TextScale().points(.caption) == 10)
    #expect(TextScale(factor: 3).factor == 2)   // a stored value out of range is clamped
}

@Test func aClipIs16kHzMono16BitPCM() {
    let wav = WAV.encode([0, 0.5, -1, 2])
    #expect(wav.count == 44 + 8)
    #expect(String(decoding: wav[0..<4], as: UTF8.self) == "RIFF" && String(decoding: wav[8..<16], as: UTF8.self) == "WAVEfmt ")
    func u32(_ at: Int) -> UInt32 { wav[at..<at + 4].enumerated().reduce(0) { $0 | UInt32($1.element) << (8 * $1.offset) } }
    func u16(_ at: Int) -> UInt16 { UInt16(wav[at]) | UInt16(wav[at + 1]) << 8 }
    #expect(u32(4) == 44 + 8 - 8 && u32(16) == 16 && u16(20) == 1 && u16(22) == 1)   // sizes, PCM, mono
    #expect(u32(24) == 16000 && u32(28) == 32000 && u16(32) == 2 && u16(34) == 16)    // rate, bytes/s, block, bits
    #expect(String(decoding: wav[36..<40], as: UTF8.self) == "data" && u32(40) == 8)
    #expect((0..<4).map { Int16(bitPattern: u16(44 + 2 * $0)) } == [0, 16384, -32767, 32767])   // clipped, not wrapped
    #expect(WAV.seconds(samples: 8000) == 0.5)
}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: FAIL to compile: `cannot find 'TalkKeys' in scope` (and `TextScale`, `WAV`).

- [ ] **Step 3: Implement**

Create `mac/RunwayWatchCore/Sources/RunwayWatchCore/TalkInput.swift`:

```swift
import Foundation

/// Hold-to-talk on the two Option keys (spec Section 4): left Option talks as Tower, right Option as Pilot. NSEvent's
/// modifier flags carry device-dependent bits that tell the two keys apart. One line at a time: the other key is
/// ignored while one is held, and Option pressed with Command, Control or Shift is a shortcut, never a line.
public struct TalkKeys: Sendable, Equatable {
    public static let leftOption: UInt = 0x20    // NX_DEVICELALTKEYMASK
    public static let rightOption: UInt = 0x40   // NX_DEVICERALTKEYMASK
    static let shortcutModifiers: UInt = 1 << 17 | 1 << 18 | 1 << 20   // Shift, Control, Command

    public enum Change: Sendable, Equatable {
        case down(Role)        // start recording
        case up(Role)          // stop and send the line
        case cancelled(Role)   // stop and discard: the key became part of a shortcut
    }

    private var held: Role?
    private var inShortcut = false   // Option went down as part of a shortcut; wait until every key is up

    public init() {}

    /// What one flagsChanged event changes, from its raw modifier flags.
    public mutating func update(_ flags: UInt) -> [Change] {
        let shortcut = flags & Self.shortcutModifiers != 0
        let left = flags & Self.leftOption != 0, right = flags & Self.rightOption != 0
        if let role = held {
            let stillDown = role == .controller ? left : right
            if shortcut {
                held = nil
                inShortcut = true
                return [.cancelled(role)]
            }
            if !stillDown {
                held = nil
                return [.up(role)]
            }
            return []
        }
        if shortcut || inShortcut {
            inShortcut = shortcut || left || right
            return []
        }
        if left != right {   // exactly one Option key: both at once is ambiguous
            held = left ? .controller : .pilot
            return [.down(held!)]
        }
        return []
    }
}

/// The View menu's text size (spec Section 3): macOS has no Dynamic Type, so the app scales its own text styles, in
/// quarter steps up to 200 percent.
public struct TextScale: Sendable, Equatable {
    public static let steps: [Double] = [1, 1.25, 1.5, 1.75, 2]

    /// The macOS text styles the window uses, at their default sizes in points (HIG typography).
    public enum Style: Sendable {
        case title3, headline, body, callout, subheadline, caption

        var points: Double {
            switch self {
            case .title3: 15
            case .headline, .body: 13
            case .callout: 12
            case .subheadline: 11
            case .caption: 10
            }
        }
    }

    public private(set) var factor: Double

    public init(factor: Double = 1) {
        self.factor = Self.steps.last { $0 <= factor } ?? 1
    }

    public var canGrow: Bool { factor < Self.steps.last! }
    public var canShrink: Bool { factor > Self.steps.first! }

    public mutating func bigger() { factor = Self.steps.first { $0 > factor } ?? factor }
    public mutating func smaller() { factor = Self.steps.last { $0 < factor } ?? factor }
    public mutating func actualSize() { factor = 1 }

    public func points(_ style: Style) -> Double { style.points * factor }
}

/// The clip the app sends: 16 kHz mono 16-bit PCM WAV (spec Section 5).
public enum WAV {
    public static let sampleRate = 16000

    /// Samples in -1...1; anything outside is clipped.
    public static func encode(_ samples: [Float]) -> Data {
        var data = Data(capacity: 44 + 2 * samples.count)
        func u32(_ v: UInt32) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
        func u16(_ v: UInt16) { withUnsafeBytes(of: v.littleEndian) { data.append(contentsOf: $0) } }
        let bytes = UInt32(2 * samples.count)
        data.append(contentsOf: Array("RIFF".utf8)); u32(36 + bytes)
        data.append(contentsOf: Array("WAVEfmt ".utf8)); u32(16)
        u16(1); u16(1); u32(UInt32(sampleRate)); u32(UInt32(2 * sampleRate)); u16(2); u16(16)
        data.append(contentsOf: Array("data".utf8)); u32(bytes)
        for s in samples {
            u16(UInt16(bitPattern: Int16((max(-1, min(1, s)) * 32767).rounded())))
        }
        return data
    }

    public static func seconds(samples: Int) -> Double { Double(samples) / Double(sampleRate) }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd mac/RunwayWatchCore && swift test`
Expected: `Test run with 51 tests in 0 suites passed`.

Also check that the helper reads the app's clips. From the repo root, with `.venv` active:

```bash
mkdir -p /tmp/rw-wav && cat > /tmp/rw-wav/main.swift <<'EOF'
import Foundation
let samples = (0..<12000).map { Float(sin(Double($0) * 2 * .pi * 440 / 16000) * 0.5) }
try! WAV.encode(samples).write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
EOF
C=mac/RunwayWatchCore/Sources/RunwayWatchCore
swiftc $C/TalkInput.swift $C/HelperAPI.swift $C/ServerSentEvents.swift /tmp/rw-wav/main.swift -o /tmp/rw-wav/wav
/tmp/rw-wav/wav /tmp/rw-wav/tone.wav
python -c "from atcdb.live import clip_seconds; import soundfile as sf; d, r = sf.read('/tmp/rw-wav/tone.wav'); print(r, len(d), round(abs(d).max(), 3), clip_seconds(open('/tmp/rw-wav/tone.wav', 'rb').read()))"
rm -r /tmp/rw-wav
```

Expected: `16000 12000 0.5 0.75`.

- [ ] **Step 5: Commit**

```bash
git add mac/RunwayWatchCore
git commit -m "feat: left and right Option talk keys, text size steps and 16 kHz WAV clips

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: The Mac app

**Files:**
- Create: `mac/RunwayWatch.xcodeproj/project.pbxproj`, `mac/RunwayWatch.xcodeproj/xcshareddata/xcschemes/RunwayWatch.xcscheme`
- Create in `mac/RunwayWatch/` (an Xcode synchronized folder: every file in it is part of the target): `RunwayWatchApp.swift`, `AppModel.swift`, `AppSettings.swift`, `Recorder.swift`, `TalkKeyMonitor.swift`, `ScaledFont.swift`, `SessionWindow.swift`, `TranscriptPane.swift`, `InspectorPane.swift`, `AppCommands.swift`, `SettingsView.swift`, `AppIcon.icon/icon.json`, `AppIcon.icon/Assets/airplane.svg`, `AppIcon.icon/Assets/runway.svg`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything in `RunwayWatchCore`.
- Produces: the app `Runway Watch.app` (bundle id `edu.nst2046.RunwayWatch`, module `RunwayWatch`). `AppModel` holds the window's state; `Recorder` gives `Clip(samples:preview:)`; `TalkKeyMonitor` reports `TalkKeys.Change`; `AppSettings` keeps the repo path (UserDefaults `repoPath`) and the key (Keychain, service "Runway Watch", account `ANTHROPIC_API_KEY`).

The project file is written by hand. It uses Xcode 16's synchronized folders (object version 77), so it never lists source files, and it depends on the package as a local Swift package. The app is signed to run locally (amendment 9).

- [ ] **Step 1: Create the project and the app**

Create `mac/RunwayWatch.xcodeproj/project.pbxproj`:

```text
// !$*UTF8*$!
{
	archiveVersion = 1;
	classes = {
	};
	objectVersion = 77;
	objects = {

/* Begin PBXBuildFile section */
		A1000000000000000000000A /* RunwayWatchCore in Frameworks */ = {isa = PBXBuildFile; productRef = A1000000000000000000000B /* RunwayWatchCore */; };
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
		A10000000000000000000001 /* Runway Watch.app */ = {isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = "Runway Watch.app"; sourceTree = BUILT_PRODUCTS_DIR; };
/* End PBXFileReference section */

/* Begin PBXFileSystemSynchronizedRootGroup section */
		A10000000000000000000002 /* RunwayWatch */ = {
			isa = PBXFileSystemSynchronizedRootGroup;
			path = RunwayWatch;
			sourceTree = "<group>";
		};
/* End PBXFileSystemSynchronizedRootGroup section */

/* Begin PBXFrameworksBuildPhase section */
		A10000000000000000000003 /* Frameworks */ = {
			isa = PBXFrameworksBuildPhase;
			buildActionMask = 2147483647;
			files = (
				A1000000000000000000000A /* RunwayWatchCore in Frameworks */,
			);
			runOnlyForDeploymentPostprocessing = 0;
		};
/* End PBXFrameworksBuildPhase section */

/* Begin PBXGroup section */
		A10000000000000000000004 = {
			isa = PBXGroup;
			children = (
				A10000000000000000000002 /* RunwayWatch */,
				A10000000000000000000005 /* Products */,
			);
			sourceTree = "<group>";
		};
		A10000000000000000000005 /* Products */ = {
			isa = PBXGroup;
			children = (
				A10000000000000000000001 /* Runway Watch.app */,
			);
			name = Products;
			sourceTree = "<group>";
		};
/* End PBXGroup section */

/* Begin PBXNativeTarget section */
		A10000000000000000000006 /* RunwayWatch */ = {
			isa = PBXNativeTarget;
			buildConfigurationList = A10000000000000000000010 /* Build configuration list for PBXNativeTarget "RunwayWatch" */;
			buildPhases = (
				A10000000000000000000007 /* Sources */,
				A10000000000000000000003 /* Frameworks */,
				A10000000000000000000008 /* Resources */,
			);
			buildRules = (
			);
			dependencies = (
			);
			fileSystemSynchronizedGroups = (
				A10000000000000000000002 /* RunwayWatch */,
			);
			name = RunwayWatch;
			packageProductDependencies = (
				A1000000000000000000000B /* RunwayWatchCore */,
			);
			productName = RunwayWatch;
			productReference = A10000000000000000000001 /* Runway Watch.app */;
			productType = "com.apple.product-type.application";
		};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		A10000000000000000000009 /* Project object */ = {
			isa = PBXProject;
			attributes = {
				BuildIndependentTargetsInParallel = 1;
				LastSwiftUpdateCheck = 2600;
				LastUpgradeCheck = 2600;
				TargetAttributes = {
					A10000000000000000000006 = {
						CreatedOnToolsVersion = 26.6;
					};
				};
			};
			buildConfigurationList = A10000000000000000000011 /* Build configuration list for PBXProject "RunwayWatch" */;
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = (
				en,
				Base,
			);
			mainGroup = A10000000000000000000004;
			minimizedProjectReferenceProxies = 1;
			packageReferences = (
				A1000000000000000000000C /* XCLocalSwiftPackageReference "RunwayWatchCore" */,
			);
			preferredProjectObjectVersion = 77;
			productRefGroup = A10000000000000000000005 /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				A10000000000000000000006 /* RunwayWatch */,
			);
		};
/* End PBXProject section */

/* Begin PBXResourcesBuildPhase section */
		A10000000000000000000008 /* Resources */ = {
			isa = PBXResourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		};
/* End PBXResourcesBuildPhase section */

/* Begin PBXSourcesBuildPhase section */
		A10000000000000000000007 /* Sources */ = {
			isa = PBXSourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		};
/* End PBXSourcesBuildPhase section */

/* Begin XCBuildConfiguration section */
		A10000000000000000000012 /* Debug */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ENABLE_MODULES = YES;
				CLANG_ENABLE_OBJC_ARC = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = dwarf;
				ENABLE_STRICT_OBJC_MSGSEND = YES;
				ENABLE_TESTABILITY = YES;
				ENABLE_USER_SCRIPT_SANDBOXING = YES;
				GCC_OPTIMIZATION_LEVEL = 0;
				GCC_PREPROCESSOR_DEFINITIONS = (
					"DEBUG=1",
					"$(inherited)",
				);
				MACOSX_DEPLOYMENT_TARGET = 26.0;
				ONLY_ACTIVE_ARCH = YES;
				SDKROOT = macosx;
				SWIFT_ACTIVE_COMPILATION_CONDITIONS = "DEBUG $(inherited)";
				SWIFT_OPTIMIZATION_LEVEL = "-Onone";
			};
			name = Debug;
		};
		A10000000000000000000013 /* Release */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ENABLE_MODULES = YES;
				CLANG_ENABLE_OBJC_ARC = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";
				ENABLE_NS_ASSERTIONS = NO;
				ENABLE_STRICT_OBJC_MSGSEND = YES;
				ENABLE_USER_SCRIPT_SANDBOXING = YES;
				MACOSX_DEPLOYMENT_TARGET = 26.0;
				SDKROOT = macosx;
				SWIFT_COMPILATION_MODE = wholemodule;
			};
			name = Release;
		};
		A10000000000000000000014 /* Debug */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
				CODE_SIGN_IDENTITY = "-";
				CODE_SIGN_STYLE = Manual;
				COMBINE_HIDPI_IMAGES = YES;
				CURRENT_PROJECT_VERSION = 1;
				ENABLE_APP_SANDBOX = NO;
				ENABLE_HARDENED_RUNTIME = NO;
				GENERATE_INFOPLIST_FILE = YES;
				INFOPLIST_KEY_CFBundleDisplayName = "Runway Watch";
				INFOPLIST_KEY_LSApplicationCategoryType = "public.app-category.education";
				INFOPLIST_KEY_NSMicrophoneUsageDescription = "Runway Watch uses the microphone to transcribe the radio calls you speak.";
				INFOPLIST_KEY_NSSpeechRecognitionUsageDescription = "Runway Watch uses speech recognition to show your words while you talk.";
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/../Frameworks",
				);
				MARKETING_VERSION = 1.0;
				PRODUCT_BUNDLE_IDENTIFIER = edu.nst2046.RunwayWatch;
				PRODUCT_MODULE_NAME = RunwayWatch;
				PRODUCT_NAME = "Runway Watch";
				SWIFT_VERSION = 6.0;
			};
			name = Debug;
		};
		A10000000000000000000015 /* Release */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon;
				CODE_SIGN_IDENTITY = "-";
				CODE_SIGN_STYLE = Manual;
				COMBINE_HIDPI_IMAGES = YES;
				CURRENT_PROJECT_VERSION = 1;
				ENABLE_APP_SANDBOX = NO;
				ENABLE_HARDENED_RUNTIME = NO;
				GENERATE_INFOPLIST_FILE = YES;
				INFOPLIST_KEY_CFBundleDisplayName = "Runway Watch";
				INFOPLIST_KEY_LSApplicationCategoryType = "public.app-category.education";
				INFOPLIST_KEY_NSMicrophoneUsageDescription = "Runway Watch uses the microphone to transcribe the radio calls you speak.";
				INFOPLIST_KEY_NSSpeechRecognitionUsageDescription = "Runway Watch uses speech recognition to show your words while you talk.";
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/../Frameworks",
				);
				MARKETING_VERSION = 1.0;
				PRODUCT_BUNDLE_IDENTIFIER = edu.nst2046.RunwayWatch;
				PRODUCT_MODULE_NAME = RunwayWatch;
				PRODUCT_NAME = "Runway Watch";
				SWIFT_VERSION = 6.0;
			};
			name = Release;
		};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		A10000000000000000000010 /* Build configuration list for PBXNativeTarget "RunwayWatch" */ = {
			isa = XCConfigurationList;
			buildConfigurations = (
				A10000000000000000000014 /* Debug */,
				A10000000000000000000015 /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		};
		A10000000000000000000011 /* Build configuration list for PBXProject "RunwayWatch" */ = {
			isa = XCConfigurationList;
			buildConfigurations = (
				A10000000000000000000012 /* Debug */,
				A10000000000000000000013 /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		};
/* End XCConfigurationList section */

/* Begin XCLocalSwiftPackageReference section */
		A1000000000000000000000C /* XCLocalSwiftPackageReference "RunwayWatchCore" */ = {
			isa = XCLocalSwiftPackageReference;
			relativePath = RunwayWatchCore;
		};
/* End XCLocalSwiftPackageReference section */

/* Begin XCSwiftPackageProductDependency section */
		A1000000000000000000000B /* RunwayWatchCore */ = {
			isa = XCSwiftPackageProductDependency;
			productName = RunwayWatchCore;
		};
/* End XCSwiftPackageProductDependency section */
	};
	rootObject = A10000000000000000000009 /* Project object */;
}
```

Create `mac/RunwayWatch.xcodeproj/xcshareddata/xcschemes/RunwayWatch.xcscheme`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Scheme
   LastUpgradeVersion = "2600"
   version = "1.7">
   <BuildAction
      parallelizeBuildables = "YES"
      buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry
            buildForTesting = "YES"
            buildForRunning = "YES"
            buildForProfiling = "YES"
            buildForArchiving = "YES"
            buildForAnalyzing = "YES">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "A10000000000000000000006"
               BuildableName = "Runway Watch.app"
               BlueprintName = "RunwayWatch"
               ReferencedContainer = "container:RunwayWatch.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      shouldUseLaunchSchemeArgsEnv = "YES">
      <Testables>
      </Testables>
   </TestAction>
   <LaunchAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      launchStyle = "0"
      useCustomWorkingDirectory = "NO"
      ignoresPersistentStateOnLaunch = "NO"
      debugDocumentVersioning = "YES"
      debugServiceExtension = "internal"
      allowLocationSimulation = "YES">
      <BuildableProductRunnable
         runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "A10000000000000000000006"
            BuildableName = "Runway Watch.app"
            BlueprintName = "RunwayWatch"
            ReferencedContainer = "container:RunwayWatch.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ProfileAction
      buildConfiguration = "Release"
      shouldUseLaunchSchemeArgsEnv = "YES"
      savedToolIdentifier = ""
      useCustomWorkingDirectory = "NO"
      debugDocumentVersioning = "YES">
      <BuildableProductRunnable
         runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "A10000000000000000000006"
            BuildableName = "Runway Watch.app"
            BlueprintName = "RunwayWatch"
            ReferencedContainer = "container:RunwayWatch.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </ProfileAction>
   <AnalyzeAction
      buildConfiguration = "Debug">
   </AnalyzeAction>
   <ArchiveAction
      buildConfiguration = "Release"
      revealArchiveInOrganizer = "YES">
   </ArchiveAction>
</Scheme>
```

Create `mac/RunwayWatch/RunwayWatchApp.swift`:

```swift
import RunwayWatchCore
import SwiftUI

/// Runway Watch, the live demo app (spec docs/superpowers/specs/2026-10-20-live-demo-app-design.md). One window, one
/// session at a time; the logic lives in RunwayWatchCore and the helper (atcdb/live.py).
@main
struct RunwayWatchApp: App {
    @NSApplicationDelegateAdaptor private var delegate: AppDelegate
    @State private var model = AppModel()

    var body: some Scene {
        Window("Live Session", id: "live") {
            SessionWindow()
                .environment(model)
                .task {
                    delegate.onQuit = { model.quit() }
                    await model.launch()
                }
        }
        .defaultSize(width: 1120, height: 720)
        .commands { AppCommands(model: model) }

        Settings {
            SettingsView()
                .environment(model)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    var onQuit: (() -> Void)?

    func applicationWillTerminate(_ notification: Notification) {
        onQuit?()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}
```

Create `mac/RunwayWatch/AppModel.swift`:

```swift
import AVFoundation
import AppKit
import RunwayWatchCore
import SwiftUI

/// What the window shows and does: the core's `LiveSession` and `HelperSupervisor`, wired to the microphone, the talk
/// keys, Settings and the Replay menu. Window state (inspector, text size, typed-line speaker, Apple speech) is kept
/// across launches (spec Section 7, item 10).
@MainActor @Observable
final class AppModel {
    /// The line being recorded: `t` was taken when the key went down.
    struct Recording: Equatable {
        var role: Role
        var t: Double
        var byKey: Bool   // started by holding Option, so it ends when the key comes up
    }

    /// A line between key-up and its transcript: shown as "Transcribing..." with Apple's text.
    struct Pending: Equatable {
        var role: Role
        var t: Double
        var preview: String
        var seq: Int?
    }

    /// An inline note above the transcript (spec Section 6, Failures), with the button that fixes it, if any.
    struct Note: Identifiable, Equatable {
        enum Action { case restartHelper, openMicrophoneSettings, openSettings }
        var text: String
        var symbol = "exclamationmark.circle"
        var action: Action?
        var id: String { text }
    }

    let session: LiveSession
    let helper: HelperSupervisor
    let settings: AppSettings
    let recorder = Recorder()
    private(set) var scenarios: [Scenario] = []
    private(set) var recording: Recording?
    private(set) var pending: Pending?
    private(set) var micDenied = false
    private(set) var micProblem: String?
    var selectedSeq: Int?
    var namingSession = false

    var showInspector = UserDefaults.standard.object(forKey: "showInspector") as? Bool ?? true {
        didSet { UserDefaults.standard.set(showInspector, forKey: "showInspector") }
    }
    var textScale = TextScale(factor: UserDefaults.standard.double(forKey: "textScale")) {
        didSet { UserDefaults.standard.set(textScale.factor, forKey: "textScale") }
    }
    var typedRole = Role(rawValue: UserDefaults.standard.string(forKey: "typedRole") ?? "") ?? .controller {
        didSet { UserDefaults.standard.set(typedRole.rawValue, forKey: "typedRole") }
    }
    var useAppleSpeech = UserDefaults.standard.bool(forKey: "useAppleSpeech") {
        didSet { UserDefaults.standard.set(useAppleSpeech, forKey: "useAppleSpeech") }
    }

    @ObservationIgnored private let client: HTTPHelperClient
    @ObservationIgnored private let keys = TalkKeyMonitor()
    @ObservationIgnored private var watcher: Task<Void, Never>?

    init() {
        let client = HTTPHelperClient()
        let settings = AppSettings()
        self.client = client
        self.settings = settings
        session = LiveSession(client: client, announce: { AccessibilityNotification.Announcement($0).post() })
        helper = HelperSupervisor(health: { try await client.health() },
                                  launcher: ProcessLauncher { settings.command })
    }

    /// At launch: keys, the helper, Apple's speech model, then a session once the helper answers. The watcher also
    /// opens a session again if one could not be opened while the helper was down.
    func launch() async {
        keys.start(onChange: { [weak self] in self?.keyChanged($0) }, onEscape: { [weak self] in self?.escape() ?? false })
        helper.start()
        Task { await recorder.prepare() }
        watcher = Task { [weak self] in
            var listed = false
            while let self, !Task.isCancelled {
                if case .running = self.helper.status {
                    if self.session.sessionID == nil { await self.session.start() }
                    if !listed { listed = await self.loadScenarios() }
                } else {
                    listed = false
                }
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }

    func quit() {
        watcher?.cancel()
        helper.stop()
    }

    @discardableResult
    func loadScenarios() async -> Bool {
        guard let list = try? await client.scenarios() else { return false }
        scenarios = list
        return true
    }

    func newSession() async {
        stopTalking(send: false)
        (pending, selectedSeq) = (nil, nil)
        await session.newSession()
    }

    func replay(_ scenario: Scenario) {
        stopTalking(send: false)
        (pending, selectedSeq) = (nil, nil)
        Task { await session.replay(scenario) }
    }

    func send(typed text: String) async {
        await session.send(typed: text, as: typedRole)
    }

    var canType: Bool { session.sessionID != nil && session.replaying == nil }

    // MARK: - Notes

    var notes: [Note] {
        var out = helper.status.notes.map { text in
            Note(text: text, symbol: text.hasSuffix("...") ? "hourglass" : "exclamationmark.circle",
                 action: text.contains("API key") ? .openSettings : nil)
        }
        if case .stopped = helper.status, !out.isEmpty { out[0].action = .restartHelper }
        if micDenied {
            out.append(Note(text: "Microphone access is off, so Talk cannot record. Typing still works.",
                            symbol: "mic.slash", action: .openMicrophoneSettings))
        }
        if let micProblem { out.append(Note(text: micProblem, symbol: "mic.slash")) }
        if let problem = session.problem {
            out.append(Note(text: problem, action: problem.contains("Restart Helper") ? .restartHelper : nil))
        }
        return out
    }

    // MARK: - Talking

    /// Why `role` cannot talk now, or nil.
    func talkBlockedReason(_ role: Role) -> String? {
        if let reason = helper.status.talkBlockedReason { return reason }
        if session.sessionID == nil { return "Waiting for the helper to start." }
        if session.replaying != nil { return "A replay is running. Stop it to talk." }
        if micDenied { return "Microphone access is off." }
        if let r = recording, r.role != role { return "\(r.role.title) is talking." }
        return nil
    }

    /// A click on a Talk button or ⌘1 / ⌘2: start, or stop and send.
    func toggleTalk(_ role: Role) {
        if recording?.role == role { stopTalking(send: true) } else { startTalking(role, byKey: false) }
    }

    /// Esc: discard a recording, else stop a replay. Whether Esc was used.
    @discardableResult
    func escape() -> Bool {
        if recording != nil {
            stopTalking(send: false)
            return true
        }
        if session.replaying != nil {
            session.stopReplay()
            return true
        }
        return false
    }

    /// The app went to the background: Option key changes stop arriving, so a held key counts as released.
    func appResignedActive() {
        for change in keys.releaseAll() { keyChanged(change) }
    }

    private func keyChanged(_ change: TalkKeys.Change) {
        switch change {
        case .down(let role): startTalking(role, byKey: true)
        case .up(let role): if recording?.role == role && recording?.byKey == true { stopTalking(send: true) }
        case .cancelled(let role): if recording?.role == role { stopTalking(send: false) }
        }
    }

    /// The microphone is asked for on the first Talk, not at launch; after it is granted, recording starts with no
    /// message (spec Section 6; HIG brief, section 5).
    private func startTalking(_ role: Role, byKey: Bool) {
        guard recording == nil, talkBlockedReason(role) == nil else { return }
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            begin(role, byKey: byKey)
        case .notDetermined:
            Task {
                let granted = await AVCaptureDevice.requestAccess(for: .audio)
                micDenied = !granted
                if granted && (!byKey || keys.isHeld(role)) { begin(role, byKey: byKey) }
            }
        default:
            micDenied = true
        }
    }

    private func begin(_ role: Role, byKey: Bool) {
        do {
            try recorder.start()
            (micProblem, pending) = (nil, nil)
            recording = Recording(role: role, t: session.elapsed, byKey: byKey)
        } catch {
            micProblem = "The microphone could not start: \(error.localizedDescription)"
        }
    }

    private func stopTalking(send: Bool) {
        guard let r = recording else { return }
        recording = nil
        if send { pending = Pending(role: r.role, t: r.t, preview: recorder.preview) }
        Task {
            let clip = await recorder.stop()
            guard send else { return }
            pending?.preview = clip.preview
            let seq = await session.send(clip: WAV.encode(clip.samples), as: r.role, at: r.t, previewText: clip.preview,
                                         preferApple: useAppleSpeech)
            if let seq, pending?.t == r.t { pending?.seq = seq } else if pending?.t == r.t { pending = nil }
        }
    }

    /// The pending row, until the line's transcript arrives.
    var visiblePending: Pending? {
        guard let p = pending else { return nil }
        if let seq = p.seq, session.state.row(seq)?.transcript != nil { return nil }
        return p
    }
}
```

Create `mac/RunwayWatch/AppSettings.swift`:

```swift
import Foundation
import RunwayWatchCore
import Security

/// The settings the helper needs (spec Section 6, API key): the Anthropic API key, kept in the Keychain because an app
/// started from the Dock cannot see the shell's environment, and the repository checkout the helper runs from.
@MainActor @Observable
final class AppSettings {
    /// The checkout this app was built from: this file is mac/RunwayWatch/AppSettings.swift.
    static let builtFrom = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().path

    var repoPath = UserDefaults.standard.string(forKey: "repoPath") ?? AppSettings.builtFrom {
        didSet { UserDefaults.standard.set(repoPath, forKey: "repoPath") }
    }
    var apiKey = Keychain.read() {
        didSet { Keychain.write(apiKey) }
    }

    var repoLooksRight: Bool {
        FileManager.default.isExecutableFile(atPath: URL(fileURLWithPath: repoPath).appending(path: ".venv/bin/python").path)
    }

    var command: HelperCommand {
        .uvicorn(repo: URL(fileURLWithPath: repoPath), apiKey: apiKey, environment: ProcessInfo.processInfo.environment)
    }
}

/// The API key as one generic password in the login keychain.
enum Keychain {
    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "Runway Watch",
         kSecAttrAccount as String: "ANTHROPIC_API_KEY"]
    }

    static func read() -> String {
        var q = query
        q[kSecReturnData as String] = true
        var item: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return "" }
        return String(decoding: data, as: UTF8.self)
    }

    /// An empty key removes the item.
    static func write(_ key: String) {
        SecItemDelete(query as CFDictionary)
        guard !key.isEmpty else { return }
        var q = query
        q[kSecValueData as String] = Data(key.utf8)
        SecItemAdd(q as CFDictionary, nil)
    }
}
```

Create `mac/RunwayWatch/Recorder.swift`:

```swift
import AVFoundation
import RunwayWatchCore
import Speech

/// Records the microphone for one line (spec Section 5): 16 kHz mono samples for the clip, and the same audio through
/// Apple's SpeechAnalyzer for the live preview. Probed while planning (2026-10-20): the progressive preset gives
/// preview text about once a second while someone talks, and priming it with ATC words changed nothing, so it is not
/// primed. Without Apple's speech model there is no preview; Whisper still transcribes.
@MainActor @Observable
final class Recorder {
    struct Clip {
        var samples: [Float]
        var preview: String
    }

    private(set) var preview = ""

    @ObservationIgnored private let engine = AVAudioEngine()
    @ObservationIgnored private var sink: TapSink?
    @ObservationIgnored private var analyzer: SpeechAnalyzer?
    @ObservationIgnored private var results: Task<Void, Never>?
    @ObservationIgnored private var speechFormat: AVAudioFormat?   // set once Apple's speech model is installed

    private static let locale = Locale(identifier: "en-US")

    private static func transcriber() -> SpeechTranscriber {
        SpeechTranscriber(locale: locale, preset: .progressiveTranscription)
    }

    /// Installs Apple's on-device speech model if needed (a one-time download).
    func prepare() async {
        let t = Self.transcriber()
        do {
            if let request = try await AssetInventory.assetInstallationRequest(supporting: [t]) {
                try await request.downloadAndInstall()
            }
            speechFormat = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [t])
        } catch {
            speechFormat = nil
        }
    }

    func start() throws {
        preview = ""
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        let sink = try TapSink(input: format, speech: speechFormat)
        self.sink = sink
        if let speechFormat { startPreview(sink, format: speechFormat) }
        input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in sink.receive(buffer) }
        engine.prepare()
        do {
            try engine.start()
        } catch {
            input.removeTap(onBus: 0)
            self.sink = nil
            throw error
        }
    }

    /// Stops recording; the samples and Apple's final text, waiting at most a second for it.
    func stop() async -> Clip {
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        guard let sink else { return Clip(samples: [], preview: preview) }
        self.sink = nil
        sink.finish()
        if let analyzer, let results {
            self.analyzer = nil
            await within(.seconds(1)) {
                try? await analyzer.finalizeAndFinishThroughEndOfInput()
                await results.value
            }
            results.cancel()
        }
        return Clip(samples: sink.samples, preview: preview)
    }

    private func startPreview(_ sink: TapSink, format: AVAudioFormat) {
        let transcriber = Self.transcriber()
        let analyzer = SpeechAnalyzer(modules: [transcriber])
        self.analyzer = analyzer
        results = Task { [weak self] in
            var finalized = ""
            do {
                try await analyzer.prepareToAnalyze(in: format)
                try await analyzer.start(inputSequence: sink.speechInput)
                for try await r in transcriber.results {
                    let text = String(r.text.characters).trimmingCharacters(in: .whitespaces)
                    if r.isFinal { finalized += (finalized.isEmpty ? "" : " ") + text }
                    self?.preview = r.isFinal ? finalized : [finalized, text].filter { !$0.isEmpty }.joined(separator: " ")
                }
            } catch {
                // no preview for this line: the clip still goes to Whisper
            }
        }
    }
}

/// Runs `work`, giving up on it after `limit`.
private func within(_ limit: Duration, _ work: @escaping @Sendable () async -> Void) async {
    await withTaskGroup(of: Void.self) { group in
        group.addTask { await work() }
        group.addTask { try? await Task.sleep(for: limit) }
        await group.next()
        group.cancelAll()
    }
}

/// Receives microphone buffers on the audio thread: converts each to 16 kHz mono for the clip and to the speech
/// analyzer's format for the preview.
final class TapSink: @unchecked Sendable {
    let speechInput: AsyncStream<AnalyzerInput>
    private let continuation: AsyncStream<AnalyzerInput>.Continuation
    private let clipFormat: AVAudioFormat
    private let toClip: AVAudioConverter
    private let speechFormat: AVAudioFormat?
    private let toSpeech: AVAudioConverter?
    private let lock = NSLock()
    private var clip: [Float] = []

    init(input: AVAudioFormat, speech: AVAudioFormat?) throws {
        guard let clipFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Double(WAV.sampleRate),
                                             channels: 1, interleaved: false),
              let toClip = AVAudioConverter(from: input, to: clipFormat) else {
            throw CocoaError(.featureUnsupported)
        }
        toClip.downmix = true
        self.clipFormat = clipFormat
        self.toClip = toClip
        speechFormat = speech
        toSpeech = speech.flatMap { AVAudioConverter(from: input, to: $0) }
        toSpeech?.downmix = true
        (speechInput, continuation) = AsyncStream.makeStream()
    }

    var samples: [Float] { lock.withLock { clip } }

    func receive(_ buffer: AVAudioPCMBuffer) {
        if let out = Self.convert(buffer, toClip, clipFormat), let channel = out.floatChannelData {
            let added = UnsafeBufferPointer(start: channel[0], count: Int(out.frameLength))
            lock.withLock { clip.append(contentsOf: added) }
        }
        if let toSpeech, let speechFormat, let out = Self.convert(buffer, toSpeech, speechFormat) {
            continuation.yield(AnalyzerInput(buffer: out))
        }
    }

    func finish() {
        continuation.finish()
    }

    private static func convert(_ buffer: AVAudioPCMBuffer, _ converter: AVAudioConverter,
                                _ format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * format.sampleRate / buffer.format.sampleRate) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return nil }
        let once = Once()
        nonisolated(unsafe) let input = buffer
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if once.done {
                status.pointee = .noDataNow
                return nil
            }
            once.done = true
            status.pointee = .haveData
            return input
        }
        return error == nil && out.frameLength > 0 ? out : nil
    }

    private final class Once: @unchecked Sendable {
        var done = false
    }
}
```

Create `mac/RunwayWatch/TalkKeyMonitor.swift`:

```swift
import AppKit
import RunwayWatchCore

/// Reads the two Option keys while the app is active (spec Section 4), and Esc, which discards a recording or stops a
/// replay. A local monitor only sees events while the app is frontmost, which is what the demo wants.
@MainActor
final class TalkKeyMonitor {
    private var monitor: Any?
    private var keys = TalkKeys()
    private var flags: UInt = 0
    private var onChange: (TalkKeys.Change) -> Void = { _ in }
    private var onEscape: () -> Bool = { false }

    func start(onChange: @escaping (TalkKeys.Change) -> Void, onEscape: @escaping () -> Bool) {
        guard monitor == nil else { return }
        self.onChange = onChange
        self.onEscape = onEscape
        monitor = NSEvent.addLocalMonitorForEvents(matching: [.flagsChanged, .keyDown]) { [weak self] event in
            let (type, raw, keyCode) = (event.type, UInt(event.modifierFlags.rawValue), event.keyCode)
            let used = MainActor.assumeIsolated { self?.handle(type, raw, keyCode) ?? false }
            return used ? nil : event
        }
    }

    func isHeld(_ role: Role) -> Bool {
        flags & (role == .controller ? TalkKeys.leftOption : TalkKeys.rightOption) != 0
    }

    /// Every key counts as released (the app lost focus mid-line).
    func releaseAll() -> [TalkKeys.Change] {
        flags = 0
        return keys.update(0)
    }

    private func handle(_ type: NSEvent.EventType, _ raw: UInt, _ keyCode: UInt16) -> Bool {
        if type == .flagsChanged {
            flags = raw
            keys.update(raw).forEach(onChange)
            return false
        }
        return keyCode == 53 && onEscape()   // 53: Esc
    }
}
```

Create `mac/RunwayWatch/ScaledFont.swift`:

```swift
import RunwayWatchCore
import SwiftUI

extension EnvironmentValues {
    @Entry var textScale = TextScale()
}

extension View {
    /// A macOS text style at the View menu's text size; `mono` for times, runways and callsigns (SF Mono).
    func scaledFont(_ style: TextScale.Style, mono: Bool = false) -> some View {
        modifier(ScaledFont(style: style, mono: mono))
    }
}

private struct ScaledFont: ViewModifier {
    @Environment(\.textScale) private var scale
    let style: TextScale.Style
    let mono: Bool

    func body(content: Content) -> some View {
        content.font(.system(size: scale.points(style), weight: style == .headline ? .bold : .regular,
                             design: mono ? .monospaced : .default))
    }
}

extension ConflictCard {
    /// Runway conflicts red, readbacks orange: always with their own symbol and label, never color alone.
    var color: Color { type == "READBACK" ? .orange : .red }
}

extension Role {
    var symbol: String { self == .controller ? "headset" : "airplane" }
}
```

Create `mac/RunwayWatch/SessionWindow.swift`:

```swift
import RunwayWatchCore
import SwiftUI

/// The window (spec Section 3): the transcript, a trailing inspector, and a toolbar of three groups: the title, the
/// two Talk buttons, and Replay with the inspector toggle.
struct SessionWindow: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        TranscriptPane()
            .frame(minWidth: 520, minHeight: 400)
            .inspector(isPresented: $model.showInspector) {
                InspectorPane()
                    .inspectorColumnWidth(min: 300, ideal: 360, max: 560)
            }
            .toolbar {
                ToolbarItemGroup(placement: .principal) {
                    TalkButton(role: .controller)
                    TalkButton(role: .pilot)
                }
                ToolbarItemGroup(placement: .primaryAction) {
                    ReplayControl()
                    Button {
                        model.showInspector.toggle()
                    } label: {
                        Label(model.showInspector ? "Hide Inspector" : "Show Inspector", systemImage: "sidebar.trailing")
                    }
                    .help(model.showInspector ? "Hide conflicts and runways" : "Show conflicts and runways")
                }
            }
            .navigationTitle("Live Session")
            .environment(\.textScale, model.textScale)
            .sheet(isPresented: $model.namingSession) { SaveSessionSheet() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didResignActiveNotification)) { _ in
                model.appResignedActive()
            }
    }
}

/// Talk as Tower or Pilot: click to start and stop, or hold the Option key named in the tooltip. While recording, the
/// button reads "Recording" on a red background and its microphone breathes, except under Reduce Motion.
struct TalkButton: View {
    let role: Role
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let recording = model.recording?.role == role
        let blocked = model.talkBlockedReason(role)
        let button = Button {
            model.toggleTalk(role)
        } label: {
            Label(recording ? "Recording" : "Talk as \(role.title)", systemImage: recording ? "mic.fill" : "mic")
                .symbolEffect(.breathe, isActive: recording && !reduceMotion)
        }
        .labelStyle(.titleAndIcon)
        .disabled(blocked != nil && !recording)
        .help(blocked ?? "Hold the \(role == .controller ? "left" : "right") Option key, or click to start and stop")
        .accessibilityLabel(recording ? "Stop talking as \(role.title)" : "Start talking as \(role.title)")
        if recording {
            button.buttonStyle(.borderedProminent).tint(.red)
        } else {
            button
        }
    }
}

/// The Replay menu, or Stop Replay while one runs.
struct ReplayControl: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        if model.session.replaying != nil {
            Button {
                model.session.stopReplay()
            } label: {
                Label("Stop Replay", systemImage: "stop.fill")
            }
            .labelStyle(.titleAndIcon)
            .help("Stop sending the replay's lines")
        } else {
            Menu {
                ForEach(model.scenarios) { s in
                    Button(s.title) { model.replay(s) }
                }
            } label: {
                Label("Replay", systemImage: "play.rectangle")
            }
            .labelStyle(.titleAndIcon)
            .disabled(model.scenarios.isEmpty || model.recording != nil || model.session.sessionID == nil)
            .help("Replay the Austin transcript or a saved session")
        }
    }
}

/// File > Save Session As...: names the session for the Replay menu.
struct SaveSessionSheet: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var failure: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Save Session").font(.headline)
            TextField("Name", text: $name, prompt: Text("Rehearsal 1"))
            Text(failure ?? "Saved sessions appear in the Replay menu.")
                .foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                    .keyboardShortcut(.cancelAction)
                Button("Save") { save() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding(20)
        .frame(width: 380)
    }

    private func save() {
        Task {
            do {
                try await model.session.save(as: name.trimmingCharacters(in: .whitespaces))
                await model.loadScenarios()
                dismiss()
            } catch {
                failure = "The session could not be saved. Check that the helper is running, then try again."
            }
        }
    }
}
```

Create `mac/RunwayWatch/TranscriptPane.swift`:

```swift
import RunwayWatchCore
import SwiftUI

/// The main pane (spec Section 3): inline notes, the transcript (newest at the bottom), and the typed-input backup.
struct TranscriptPane: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        @Bindable var model = model
        let rows = model.session.state.rows
        VStack(spacing: 0) {
            NotesView()
            ScrollViewReader { proxy in
                List(selection: $model.selectedSeq) {
                    Section {
                        ForEach(rows) { row in
                            LineRowView(row: row).tag(row.seq)
                        }
                        if let r = model.recording {
                            LiveRowView(role: r.role, t: r.t, title: "Recording, \(r.role.title)",
                                        text: model.recorder.preview, working: false)
                        } else if let p = model.visiblePending {
                            LiveRowView(role: p.role, t: p.t, title: "Transcribing...", text: p.preview, working: true)
                        } else if let d = model.session.state.dropped {
                            Label("\(d.role.title): \(d.reason). Hold the key for the whole call.", systemImage: "scissors")
                                .scaledFont(.callout)
                                .foregroundStyle(.secondary)
                        }
                        Color.clear.frame(height: 1).id("end")
                    } header: {
                        Text("Transcript").accessibilityAddTraits(.isHeader)
                    }
                }
                .overlay {
                    if rows.isEmpty && model.recording == nil && model.visiblePending == nil {
                        Text("No transmissions yet. Hold a talk key and read a clearance.")
                            .scaledFont(.body)
                            .foregroundStyle(.secondary)
                    }
                }
                .onChange(of: rows.last?.id) { scrollToEnd(proxy) }
                .onChange(of: model.recording) { scrollToEnd(proxy) }
            }
            Divider()
            TypedInputBar()
        }
    }

    private func scrollToEnd(_ proxy: ScrollViewProxy) {
        if reduceMotion {
            proxy.scrollTo("end", anchor: .bottom)
        } else {
            withAnimation(.easeOut(duration: 0.15)) { proxy.scrollTo("end", anchor: .bottom) }
        }
    }
}

/// Status and problems, beside what they describe, each with the button that fixes it; never an alert.
struct NotesView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let notes = model.notes
        if !notes.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                ForEach(notes) { note in
                    HStack(spacing: 8) {
                        Image(systemName: note.symbol).foregroundStyle(.secondary).accessibilityHidden(true)
                        Text(note.text).scaledFont(.callout)
                        Spacer(minLength: 0)
                        switch note.action {
                        case .restartHelper: Button("Restart Helper") { model.helper.restart() }
                        case .openSettings: SettingsLink { Text("Open Settings...") }
                        case .openMicrophoneSettings:
                            Button("Open System Settings") {
                                NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")!)
                            }
                        case nil: EmptyView()
                        }
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.quaternary.opacity(0.5))
        }
    }
}

/// The line being recorded or transcribed, with Apple's text so far.
struct LiveRowView: View {
    let role: Role
    let t: Double
    let title: String
    let text: String
    let working: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(Wording.time(t)).scaledFont(.callout, mono: true).foregroundStyle(.secondary)
                .frame(minWidth: 64, alignment: .trailing)
            Image(systemName: role.symbol).foregroundStyle(.secondary).scaledFont(.body).accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(title).scaledFont(.callout).foregroundStyle(.secondary)
                Text(text.isEmpty ? "Listening..." : text).scaledFont(.body).italic()
            }
            if working { ProgressView().controlSize(.small) }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .combine)
    }
}

/// One transmission: time, speaker, text, then a Rules row and a Claude row.
struct LineRowView: View {
    let row: LineRow
    @Environment(AppModel.self) private var model

    var body: some View {
        let t = row.transcript
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(t.map { Wording.time($0.t) } ?? "").scaledFont(.callout, mono: true).foregroundStyle(.secondary)
                .frame(minWidth: 64, alignment: .trailing)
            Image(systemName: (t?.role ?? .controller).symbol).foregroundStyle(.secondary).scaledFont(.body)
                .help(t?.role.title ?? "")
            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Text(t.map { $0.error ?? $0.text } ?? "Waiting for the transcript...")
                        .scaledFont(.body)
                        .textSelection(.enabled)
                    if t?.transcriber == .apple {
                        Text("Apple speech").scaledFont(.caption)
                            .padding(.horizontal, 5).padding(.vertical, 1)
                            .background(.quaternary, in: Capsule())
                    }
                }
                ForEach(Extractor.allCases, id: \.self) { x in
                    if row.status(x) != .notRun { ExtractorLine(row: row, extractor: x) }
                }
            }
        }
        .padding(.vertical, 4)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(row.accessibilitySummary)
        .accessibilityActions {
            ForEach(Extractor.allCases, id: \.self) { x in
                if case .failed = row.status(x) {
                    Button("Retry \(x.title)") { Task { await model.session.retry(x, from: row.seq) } }
                }
            }
        }
    }
}

/// What one extractor made of the line: a spinner, its events, "Nothing understood", or why it failed with Retry.
struct ExtractorLine: View {
    let row: LineRow
    let extractor: Extractor
    @Environment(AppModel.self) private var model
    @Environment(\.textScale) private var scale

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text(extractor.title).scaledFont(.caption).foregroundStyle(.secondary)
                .frame(width: 48 * scale.factor, alignment: .leading)
            switch row.status(extractor) {
            case .waiting:
                ProgressView().controlSize(.mini)
            case .understood(let events):
                Text(events.joined(separator: "; ")).scaledFont(.callout, mono: true)
            case .nothing:
                Text("Nothing understood").scaledFont(.callout).foregroundStyle(.secondary)
            case .failed(let message):
                Text(message).scaledFont(.callout).foregroundStyle(.secondary)
                Button("Retry") { Task { await model.session.retry(extractor, from: row.seq) } }
                    .controlSize(.small)
            case .notRun:
                EmptyView()
            }
            ForEach(row.cards.filter { $0.raised[extractor] != nil }) { card in
                Image(systemName: card.symbol).foregroundStyle(card.color).help("\(card.title), raised by \(extractor.title)")
            }
        }
    }
}

/// The typed-input backup (spec Section 3): speaker, text, Send (Return).
struct TypedInputBar: View {
    @Environment(AppModel.self) private var model
    @State private var draft = ""

    var body: some View {
        @Bindable var model = model
        HStack(spacing: 10) {
            Picker("Speaker", selection: $model.typedRole) {
                ForEach(Role.allCases, id: \.self) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            .help("Choose who says the typed line")
            TextField("Type a transmission", text: $draft)
                .textFieldStyle(.roundedBorder)
                .scaledFont(.body)
                .onSubmit(send)
            Button("Send", action: send)
                .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty || !model.canType)
        }
        .padding(12)
    }

    private func send() {
        let text = draft
        guard model.canType, !text.trimmingCharacters(in: .whitespaces).isEmpty else { return }
        draft = ""
        Task { await model.send(typed: text) }
    }
}
```

Create `mac/RunwayWatch/InspectorPane.swift`:

```swift
import RunwayWatchCore
import SwiftUI

/// The trailing inspector (spec Section 3): conflicts newest first, what each engine holds per runway, and the
/// selected line's events field by field.
struct InspectorPane: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let state = model.session.state
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                section("Conflicts") {
                    if state.cards.isEmpty {
                        Text("No conflicts yet.").scaledFont(.callout).foregroundStyle(.secondary)
                    }
                    ForEach(state.cards) { ConflictCardView(card: $0) }
                }
                section("Runways") { RunwayTable(rows: state.runwayRows) }
                section("Selected Line") {
                    if let seq = model.selectedSeq, let row = state.row(seq) {
                        SelectedLineView(row: row)
                    } else {
                        Text("Select a line to compare what each extractor found.")
                            .scaledFont(.callout).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private func section(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).scaledFont(.headline).accessibilityAddTraits(.isHeader)
            content()
        }
    }
}

/// One conflict: symbol, label and color together, the runway, the callsigns and clearances, and who raised it.
struct ConflictCardView: View {
    let card: ConflictCard

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 6) {
                HStack(alignment: .firstTextBaseline) {
                    Label(card.title, systemImage: card.symbol)
                        .foregroundStyle(card.color)
                        .scaledFont(.headline)
                    Spacer()
                    Text(card.time).scaledFont(.caption, mono: true).foregroundStyle(.secondary)
                }
                if let runway = card.runway { Text("Runway \(runway)").scaledFont(.body, mono: true) }
                if !card.callsigns.isEmpty {
                    Text(card.callsigns.joined(separator: " and ")).scaledFont(.callout, mono: true)
                }
                ForEach(Extractor.allCases, id: \.self) { x in
                    if let conflicts = card.raised[x] {
                        Text("\(x.title): \(conflicts.map(\.explanation).joined(separator: "; "))")
                            .scaledFont(.callout).foregroundStyle(.secondary)
                    }
                }
                Text("Raised by: \(card.raisedBy)").scaledFont(.caption)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
    }
}

/// What each extractor's engine holds on each runway now.
struct RunwayTable: View {
    let rows: [RunwayRow]

    var body: some View {
        if rows.isEmpty {
            Text("No runway is held.").scaledFont(.callout).foregroundStyle(.secondary)
        } else {
            Grid(alignment: .leading, horizontalSpacing: 14, verticalSpacing: 6) {
                GridRow {
                    Text("Runway")
                    Text("Rules")
                    Text("Claude")
                }
                .scaledFont(.caption)
                .foregroundStyle(.secondary)
                Divider()
                ForEach(rows) { r in
                    GridRow(alignment: .firstTextBaseline) {
                        Text(r.runway)
                        cell(r.rules)
                        cell(r.claude)
                    }
                    .scaledFont(.callout, mono: true)
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }

    private func cell(_ text: String) -> some View {
        Text(text).accessibilityLabel(text.isEmpty ? "nothing held" : text)
    }
}

/// The selected line's events, field by field, per extractor.
struct SelectedLineView: View {
    let row: LineRow

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(row.transcript?.text ?? "").scaledFont(.body).textSelection(.enabled)
            ForEach(Extractor.allCases, id: \.self) { x in
                VStack(alignment: .leading, spacing: 4) {
                    Text(x.title).scaledFont(.subheadline).foregroundStyle(.secondary)
                    let events = row.results[x]?.events ?? []
                    if events.isEmpty {
                        Text(summary(row.status(x))).scaledFont(.callout).foregroundStyle(.secondary)
                    } else {
                        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 4) {
                            GridRow {
                                Text("Kind")
                                Text("Runway")
                                Text("Callsign")
                            }
                            .scaledFont(.caption)
                            .foregroundStyle(.secondary)
                            ForEach(Array(events.enumerated()), id: \.offset) { _, e in
                                GridRow(alignment: .firstTextBaseline) {
                                    Text(e.kind.replacing("_", with: " "))
                                    Text(e.runway ?? e.to ?? "")
                                    Text(e.callsign)
                                }
                                .scaledFont(.callout, mono: true)
                                .accessibilityElement(children: .combine)
                            }
                        }
                    }
                }
            }
        }
    }

    private func summary(_ status: ExtractorStatus) -> String {
        switch status {
        case .waiting: "Working..."
        case .failed(let message): message
        case .notRun: "No words, so nothing to extract."
        case .nothing, .understood: "Nothing understood"
        }
    }
}
```

Create `mac/RunwayWatch/AppCommands.swift`:

```swift
import RunwayWatchCore
import SwiftUI

/// The menu bar (spec Section 4): every toolbar item has a command here.
struct AppCommands: Commands {
    let model: AppModel

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Button("New Session") { Task { await model.newSession() } }
                .keyboardShortcut("n")
        }
        CommandGroup(replacing: .saveItem) {
            Button("Save Session As...") { model.namingSession = true }
                .keyboardShortcut("s")
                .disabled(model.session.sessionID == nil)
        }
        CommandGroup(replacing: .undoRedo) {
            Button("Undo Last Line") { Task { await model.session.undo() } }
                .keyboardShortcut("z")
                .disabled(model.session.state.rows.isEmpty)
        }
        CommandMenu("Session") {
            ForEach(Role.allCases, id: \.self) { role in
                Button(model.recording?.role == role ? "Stop Talking as \(role.title)" : "Talk as \(role.title)") {
                    model.toggleTalk(role)
                }
                .keyboardShortcut(role == .controller ? "1" : "2")
                .disabled(model.talkBlockedReason(role) != nil && model.recording?.role != role)
            }
            Divider()
            Menu("Replay") {
                ForEach(model.scenarios) { s in
                    Button(s.title) { model.replay(s) }
                }
            }
            .disabled(model.scenarios.isEmpty || model.session.replaying != nil || model.recording != nil)
            Button(model.recording != nil ? "Discard Recording" : "Stop Replay") { model.escape() }
                .keyboardShortcut(.escape, modifiers: [])
                .disabled(model.recording == nil && model.session.replaying == nil)
        }
        CommandGroup(before: .toolbar) {
            Button(model.showInspector ? "Hide Inspector" : "Show Inspector") { model.showInspector.toggle() }
                .keyboardShortcut("i", modifiers: [.option, .command])
            Divider()
            Button("Bigger Text") { model.textScale.bigger() }
                .keyboardShortcut("+")
                .disabled(!model.textScale.canGrow)
            Button("Smaller Text") { model.textScale.smaller() }
                .keyboardShortcut("-")
                .disabled(!model.textScale.canShrink)
            Button("Actual Size") { model.textScale.actualSize() }
                .keyboardShortcut("0")
                .disabled(model.textScale.factor == 1)
            Divider()
            Toggle("Use Apple Speech for Transcripts", isOn: Bindable(model).useAppleSpeech)
            Divider()
        }
    }
}
```

Create `mac/RunwayWatch/SettingsView.swift`:

```swift
import AppKit
import SwiftUI

/// Settings (⌘,): the Anthropic API key and the repository the helper runs from. Changes apply the next time the
/// helper starts, so the pane offers Restart Helper.
struct SettingsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var settings = model.settings
        Form {
            Section("Claude") {
                SecureField("Anthropic API key", text: $settings.apiKey)
                Text("Claude reads each transcript on Anthropic's servers, so transcript text leaves this Mac. The key is kept in your keychain and used the next time the helper starts.")
                    .font(.callout).foregroundStyle(.secondary)
                if model.helper.attached {
                    Text("A helper started outside the app is running; it uses its own key until it is restarted.")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }
            Section("Helper") {
                LabeledContent("Repository") {
                    HStack {
                        TextField("Repository", text: $settings.repoPath).labelsHidden()
                        Button("Choose...") { choose(into: settings) }
                    }
                }
                if !settings.repoLooksRight {
                    Label("This folder has no .venv/bin/python. Choose the nst2046-proj checkout.",
                          systemImage: "exclamationmark.triangle")
                        .font(.callout)
                }
                HStack {
                    Spacer()
                    Button("Restart Helper") { model.helper.restart() }
                }
            }
        }
        .formStyle(.grouped)
        .frame(width: 560)
    }

    private func choose(into settings: AppSettings) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.directoryURL = URL(fileURLWithPath: settings.repoPath)
        if panel.runModal() == .OK, let url = panel.url { settings.repoPath = url.path }
    }
}
```

The app icon is an Icon Composer document (open `mac/RunwayWatch/AppIcon.icon` in Icon Composer to refine it): two layers drawn as SVG, no SF Symbols (HIG brief, section 4); the system renders the dark, clear and tinted variants from the layers.

Create `mac/RunwayWatch/AppIcon.icon/icon.json`:

```json
{
  "fill" : {
    "automatic-gradient" : "extended-srgb:0.09804,0.32157,0.67843,1.00000"
  },
  "groups" : [
    {
      "layers" : [
        {
          "image-name" : "airplane.svg",
          "name" : "airplane"
        }
      ],
      "shadow" : {
        "kind" : "neutral",
        "opacity" : 0.5
      },
      "translucency" : {
        "enabled" : false,
        "value" : 0.3
      }
    },
    {
      "layers" : [
        {
          "image-name" : "runway.svg",
          "name" : "runway"
        }
      ],
      "shadow" : {
        "kind" : "neutral",
        "opacity" : 0.5
      },
      "translucency" : {
        "enabled" : true,
        "value" : 0.5
      }
    }
  ],
  "supported-platforms" : {
    "squares" : [
      "macOS"
    ]
  }
}
```

Create `mac/RunwayWatch/AppIcon.icon/Assets/airplane.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <path fill="#FFFFFF" d="M512 110 C536 110 550 136 550 170 L550 270 L760 360 L760 400 L550 350 L550 450 L610 488
    L610 514 L522 496 L512 524 L502 496 L414 514 L414 488 L474 450 L474 350 L264 400 L264 360 L474 270 L474 170
    C474 136 488 110 512 110 Z"/>
</svg>
```

Create `mac/RunwayWatch/AppIcon.icon/Assets/runway.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <path fill="#D9DEE6" fill-rule="evenodd" d="M446 470 L578 470 L790 900 L234 900 Z
    M500 560 L524 560 L527 600 L497 600 Z
    M494 640 L530 640 L535 700 L489 700 Z
    M486 740 L538 740 L544 810 L480 810 Z
    M300 840 L360 840 L352 880 L288 880 Z M386 840 L436 840 L432 880 L378 880 Z
    M588 840 L638 840 L646 880 L592 880 Z M664 840 L724 840 L736 880 L672 880 Z"/>
</svg>
```

In `README.md`, replace:

```text
uvicorn atcdb.api:app --host 127.0.0.1 --port 8020  # /api/live/health, /api/live/sessions, ... (Claude needs a key)

pytest   # the live smoke tests skip without ANTHROPIC_API_KEY; run `env -u ANTHROPIC_API_KEY pytest` to spend nothing
```

with:

```text
uvicorn atcdb.api:app --host 127.0.0.1 --port 8020  # /api/live/health, /api/live/sessions, ... (Claude needs a key)

# 9. the Mac app (Runway Watch): uses a helper already on port 8020, or starts its own from this checkout.
open mac/RunwayWatch.xcodeproj                      # Product > Run; or build from a terminal:
xcodebuild -project mac/RunwayWatch.xcodeproj -scheme RunwayWatch build
(cd mac/RunwayWatchCore && swift test)             # the app's logic: no network, no microphone

pytest   # the live smoke tests skip without ANTHROPIC_API_KEY; run `env -u ANTHROPIC_API_KEY pytest` to spend nothing
```

- [ ] **Step 2: Build it**

Run: `xcodebuild -project mac/RunwayWatch.xcodeproj -scheme RunwayWatch -configuration Debug -derivedDataPath /tmp/rw-dd build 2>&1 | grep -E "error|warning:|BUILD" | grep -v appintents`
Expected: `** BUILD SUCCEEDED **` and no errors or warnings. `plutil -p "/tmp/rw-dd/Build/Products/Debug/Runway Watch.app/Contents/Info.plist"` shows both purpose strings and `CFBundleIconName => AppIcon`; `Contents/Resources` holds `AppIcon.icns` and `Assets.car`.

- [ ] **Step 3: Smoke run (free)**

Start a helper with no key, then the app from the same terminal with no key:

```bash
env -u ANTHROPIC_API_KEY uvicorn atcdb.api:app --host 127.0.0.1 --port 8020 &
env -u ANTHROPIC_API_KEY "/tmp/rw-dd/Build/Products/Debug/Runway Watch.app/Contents/MacOS/Runway Watch" &
```

Expected, in the window:
- "Loading speech model..." for about 18 s on the first launch, Talk disabled with that reason as its tooltip, then the note goes away.
- The note "Claude unavailable: ANTHROPIC_API_KEY not set. Add the API key in Settings." with "Open Settings...".
- Typing "CSA 123 runway 31 cleared to land" as Tower and Return gives a row `csa one two three runway three one cleared to land`, Rules `LAND 31 csa one two three`, Claude "Claude unavailable: ..." with Retry; the inspector's Runways shows `31  LAND csa one two three`.
- Typing "Lufthansa 456 runway 31 cleared for takeoff" adds a red octagon on its Rules row and a "Runway conflict" card for runway 31, "Raised by: Rules".
- Replay > Austin 2023 starts a new session, sends a line every 2 s, shows Stop Replay meanwhile, and ends with one Rules card: Runway 18L at 6:39:34.

Quit the app (⌘Q), then the helper (`kill %1`), and delete the smoke sessions: `rm -rf data/live/sessions/*`.

- [ ] **Step 4: Run every test**

Run: `cd mac/RunwayWatchCore && swift test`, then from the repo root `env -u ANTHROPIC_API_KEY python -m pytest -q`
Expected: 51 Swift tests pass; the Python suite has no failures.

- [ ] **Step 5: Commit**

```bash
git add mac/RunwayWatch.xcodeproj mac/RunwayWatch README.md
git commit -m "feat: Runway Watch, the SwiftUI live demo app over the core package and the helper

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Operational steps (with the user, after Task 7)

These need a person at the Mac. B1 and B2 are free. B3 and B4 call Claude and cost money: ask the user first, state the cost, and run them only after a yes.

**B1. Manual checklist (spec Section 9), free: no key anywhere.**
1. Microphone, first use: hold left Option. macOS asks once with the purpose string; after Allow, recording starts at once with no message (if the key was let go during the prompt, nothing records). The row reads "Recording, Tower" with Apple's text appearing while you talk; the Talk as Tower button reads "Recording" on red, its microphone breathing.
2. Release: the row reads "Transcribing...", then the Whisper transcript replaces it within about 2 s; both extractor rows within about 4 s.
3. Right Option talks as Pilot. Holding both, or pressing ⌥⌘I, records nothing. Esc while talking discards the line.
4. A tap under half a second: "Tower: Too short. Hold the key for the whole call."
5. Microphone denied (System Settings > Privacy & Security > Microphone, turn Runway Watch off, relaunch): the note with `mic.slash` and Open System Settings; Talk disabled; typing still works.
6. View > Use Apple Speech for Transcripts on: new rows carry the "Apple speech" label.
7. Helper crash: `pkill -f "uvicorn atcdb.api:app"` while the app launched it: it restarts once by itself and the note says "The helper restarted, so a new session started."; kill it twice more: "The helper stopped twice..." with Restart Helper, which works.
8. Text: ⌘+ to 200 percent, ⌘- back, ⌘0; rows grow and nothing is cut off.
9. Light and dark appearance; Increase Contrast and Reduce Transparency (System Settings > Accessibility > Display); Reduce Motion stops the breathing microphone.
10. Full screen (⌃⌘F): Talk and the inspector toggle stay in the toolbar.
11. Quit and relaunch: the window size, the inspector state and the text size come back.
12. VoiceOver (⌘F5): each Talk button reads "Start talking as Tower", then "Stop talking as Tower" while recording; a row reads as one sentence; a new conflict is announced; the headings Transcript, Conflicts, Runways and Selected Line are listed in the rotor.
13. Full Keyboard Access (System Settings > Keyboard > Keyboard navigation): every control is reachable with Tab.

**B2. Accessibility Inspector audit, free.** Xcode > Open Developer Tool > Accessibility Inspector, target Runway Watch, Audit. Fix every finding before the rehearsals.

**B3. One paid check (about 1 cent; ask first).** Put the API key in Settings, Restart Helper, replay Austin 2023 (31 lines at about $0.0002 each). Expected: Claude's cards at 6:38:58 (Raised by: Claude) and 6:39:34 (Raised by: Both), as in `docs/results/pilot-cases.md`. Turn Wi-Fi off for one typed line: its Claude row says why and offers Retry; Retry after Wi-Fi is back fills it.

**B4. Rehearsals with Jennifer (about 1 cent per 50 lines; ask first).** Two full rehearsals of the scripted exchange; save one with File > Save Session As... "Rehearsal 1": it appears in the Replay menu as the backup.
