# DTC Status Decoder (iOS)

SwiftUI app that decodes the UDS (ISO 14229-1) DTC status byte.

- Single byte (`2F`), a `0x19` request (`19 02 2F`), a `0x59` response
  (`59 02 FF 01 23 45 2F ...`) or a `7F` negative response.
- Toggle bits, switch between "request mask", "DTC status" and "availability" readings.

## Build

Requires a Mac with Xcode 15+.

Option A (XcodeGen):
```
brew install xcodegen
cd dtc-status-decoder/ios && xcodegen
open DTCStatusDecoder.xcodeproj
```

Option B (no extra tools): Xcode → New Project → iOS App (SwiftUI), name it
`DTCStatusDecoder`, delete the generated `ContentView.swift` and app file, and drag
in the three files from `Sources/`.

Then pick your iPhone as the run target, set your Apple ID team under
Signing & Capabilities, and Run. A free Apple ID works for personal installs (re-sign every 7 days).
