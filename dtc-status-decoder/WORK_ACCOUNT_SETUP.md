# Recreate the DTC Status Decoder on your work Claude account

You have three options. **Option A is the fastest and gives the exact same app.**

Before you start:
- Check that your company allows bringing in outside files and code. The decoder contains only public ISO 14229-1 definitions and no company data.
- Your work account needs **Artifacts** turned on (Settings → Capabilities). If artifacts are disabled by your admin, use Option C or open the HTML file directly (see the end of this guide).

---

## Option A: Upload the finished file (recommended)

1. Get `dtc-status.html` onto the device you use for work Claude:
   - From this chat (the file card), or
   - From GitHub: repo `arzindalal/claude`, branch `claude/dtc-status-decoder-ios`, file `dtc-status-decoder/dtc-status.html`.
2. Open **claude.ai** with your **work** account and start a new chat.
3. Attach `dtc-status.html` and paste this prompt:

   ```
   Publish the attached HTML file as an artifact exactly as it is.
   Don't change, rewrite or shorten any of the code. It's a finished,
   tested tool: a UDS ISO 14229-1 DTC status mask decoder.
   ```

4. Open the artifact on your iPhone in Safari → Share → **Add to Home Screen**.

**Check it worked.** Type each input and compare the Overall line:

| Input | Expected Overall |
|---|---|
| `19 02 2F` | You're asking the ECU for every DTC that is active now, failed this cycle, pending, confirmed or failed since last clear. |
| `2F` | The fault is present right now and confirmed in memory. |
| `08` | The fault is not present now, but is stored as confirmed from earlier. |
| `59 02 FF 01 23 45 2F C1 00 87 08 9A 11 00 24` | The ECU reports 3 DTCs: 1 active now (P0123-45), 1 stored but not active and 1 pending. |

If Claude rewrote the file instead of publishing it as-is, these lines won't match. Reply: "Use the uploaded file verbatim."

---

## Option B: Rebuild from a prompt (no file needed)

Use this if you can't move files to your work device. Paste the whole block into a new work Claude chat. The result will look different from the original, but it should decode the same way. **Run the check table from Option A afterwards.**

```
Build me a single-page HTML artifact called "DTC Status Decoder" that works well
on an iPhone (375px wide, no horizontal scrolling, light and dark mode, long words
must wrap and never overlap other elements).

PURPOSE: decode the UDS (ISO 14229-1) DTC status byte.

INPUT: one hex text field (ignore spaces, commas, colons, dashes and "0x").
Show tappable example chips: 19 02 2F, 19 02 FF, 19 02 08,
59 02 FF 01 23 45 2F C1 00 87 08 9A 11 00 24, 59 01 FF 01 00 03, 2F, 08, 09, 24, AF, 50.
Decode live as the user types. Show clear errors for non-hex or an odd number of digits.

STATUS BITS (bit 0 = LSB):
0 testFailed (TF): most recent test result failed; active now.
1 testFailedThisOperationCycle (TFTOC): failed at least once this operation cycle.
2 pendingDTC (PDTC): failed in current or last completed cycle; not yet confirmed.
3 confirmedDTC (CDTC): confirmed and stored; stays until aged out or cleared (0x14).
4 testNotCompletedSinceLastClear (TNCSLC): 1 = test NOT completed since clear (inverted).
5 testFailedSinceLastClear (TFSLC): failed at least once since last clear.
6 testNotCompletedThisOperationCycle (TNCTOC): 1 = test NOT completed this cycle (inverted).
7 warningIndicatorRequested (WIR): warning lamp requested.

PARSING:
- 1 byte: treat as a DTC status by default.
- 0x19 request: the DTCStatusMask is at byte index 2 for sub-functions 01, 02, 0F, 11, 12, 13, 17,
  and index 3 for 42. Other sub-functions have no mask; say so. Strip bit 7 of the
  sub-function (suppressPosRspMsgIndicationBit).
- 0x59 response: byte after the sub-function is the DTCStatusAvailabilityMask (for 59 17
  it's after the memory-selection byte). For 59 01/11/12: then format ID, count hi, count lo.
  For other sub-functions: repeated records of 3 DTC bytes + 1 status byte; report trailing bytes.
- 0x7F: negative response; show the NRC name (10, 11, 12, 13, 14, 22, 31, 78, 7E, 7F).
- Show the frame as labeled byte boxes, with the mask byte highlighted.

THREE READING MODES (segmented control):
- "Request filter": the ECU returns DTCs where (status AND mask AND availabilityMask) != 0,
  i.e. ANY selected bit (logical OR, not AND).
- "DTC status": the actual state of one DTC.
- "ECU support": the availability mask (unsupported bits always read 0).

UI:
1. An "Overall" box with ONE plain-English sentence for the whole input:
   - Request: "You're asking the ECU for every DTC that is <bits joined with 'or'>."
     For 19 01/11/12 use "You're asking the ECU how many DTCs are ...".
     Plain names: active now, failed this cycle, pending, confirmed, not tested since clear,
     failed since last clear, not tested this cycle, lamp on.
   - Response with records: "The ECU reports N DTCs: X active now (codes), Y stored but not
     active and Z pending." Add "Nothing is failing right now." if none are active.
   - 59 01: "The ECU has N DTC(s) matching the requested mask."
   - 7F: "The ECU rejected the request: <NRC name>."
   - Single status byte. Main clause, first match wins:
     TF -> "The fault is present right now"
     CDTC -> "The fault is not present now, but is stored as confirmed from earlier"
     PDTC -> "The fault was seen recently but is not confirmed yet"
     TFSLC -> "The fault occurred since the last clear but is passing now"
     TNCSLC -> "The test hasn't run since codes were cleared, so the state is unknown"
     else TNCTOC -> "No fault recorded, but the test hasn't run yet this cycle."
     else -> "No fault recorded, and the test has completed."
     Then add clauses: if TF, "confirmed in memory" (when CDTC) or "not confirmed yet";
     if TFTOC and not TF, "it failed earlier this cycle"; if WIR, "the warning lamp is on";
     if TNCTOC and not TNCSLC, "this cycle's test hasn't run yet".
     Join one clause with " and ", several with commas and a final "and".
2. A status-byte card: big hex value and binary (e.g. 0010 1111), plus a short one-line verdict
   ("Active now · Confirmed · Pending · Lamp ON"). Then 8 bit rows (bit 7 at the top), each
   with bit number, hex weight, name, abbreviation, a one-line description and a 0/1 pill.
   Tapping a row toggles that bit.
3. For responses, a DTC table: hex DTC, SAE J2012 code (bits 15-14 of the first byte = P/C/B/U,
   e.g. 01 23 45 -> P0123-45, with a note that it's only valid for SAE/ISO 15031-6 DTC format),
   a status button (tap = decode that status), and the one-line meaning.

Test these before publishing and show me the Overall output for each:
19 02 2F, 2F, 08, AF, 50, 59 02 FF 01 23 45 2F C1 00 87 08 9A 11 00 24, 7F 19 31.
```

---

## Option C: Native iPhone app (needs a Mac with Xcode)

The SwiftUI source is on the same branch in `dtc-status-decoder/ios/`. See `ios/README.md` for the build steps. You don't need Claude for this option.
- This code has **never been compiled**, so expect a few small fixes the first time.
- If you use Claude Code on your work account, point it at that folder and ask: "Build and fix any compile errors."

---

## Without Claude at all

`dtc-status.html` is a complete standalone page. You can:
- On a computer, double-click it to open it in a browser.
- On an iPhone, host it on any internal web server and open the URL in Safari. Opening the file from Mail or the Files app only shows a preview, and the decoder won't run there.

It only loads Google Fonts from the internet. Without that it falls back to system fonts and still works.
