import Foundation

/// ISO 14229-1 DTCStatusMask bit definitions (bit 0 = LSB).
struct StatusBit: Identifiable {
    let id: Int
    let abbr: String
    let name: String
    let detail: String
    var value: UInt8 { 1 << UInt8(id) }
}

enum DTCDecoder {
    static let bits: [StatusBit] = [
        .init(id: 0, abbr: "TF", name: "testFailed",
              detail: "The most recent test result is FAILED. Fault is active right now."),
        .init(id: 1, abbr: "TFTOC", name: "testFailedThisOperationCycle",
              detail: "Failed at least once during the current operation cycle. Resets at the start of a new cycle."),
        .init(id: 2, abbr: "PDTC", name: "pendingDTC",
              detail: "Failed during the current or last completed operation cycle. Clears after a full cycle that completes with no failure."),
        .init(id: 3, abbr: "CDTC", name: "confirmedDTC",
              detail: "Fault confirmed and stored in fault memory. Stays set until aged out or cleared (0x14)."),
        .init(id: 4, abbr: "TNCSLC", name: "testNotCompletedSinceLastClear",
              detail: "1 = test has NOT completed since DTCs were last cleared (inverted logic)."),
        .init(id: 5, abbr: "TFSLC", name: "testFailedSinceLastClear",
              detail: "Failed at least once since DTCs were last cleared."),
        .init(id: 6, abbr: "TNCTOC", name: "testNotCompletedThisOperationCycle",
              detail: "1 = test has NOT completed this operation cycle (inverted logic)."),
        .init(id: 7, abbr: "WIR", name: "warningIndicatorRequested",
              detail: "ECU requests a warning indicator (MIL / telltale) for this DTC."),
    ]

    static let subFunctions: [UInt8: String] = [
        0x01: "reportNumberOfDTCByStatusMask",
        0x02: "reportDTCByStatusMask",
        0x0A: "reportSupportedDTC",
        0x0F: "reportMirrorMemoryDTCByStatusMask",
        0x11: "reportNumberOfMirrorMemoryDTCByStatusMask",
        0x12: "reportNumberOfEmissionsOBDDTCByStatusMask",
        0x13: "reportEmissionsOBDDTCByStatusMask",
        0x15: "reportDTCWithPermanentStatus",
        0x17: "reportUserDefMemoryDTCByStatusMask",
        0x42: "reportWWHOBDDTCByMaskRecord",
    ]

    /// Index of the DTCStatusMask byte inside a 0x19 request, per sub-function.
    static let requestMaskPosition: [UInt8: Int] = [
        0x01: 2, 0x02: 2, 0x0F: 2, 0x11: 2, 0x12: 2, 0x13: 2, 0x17: 2, 0x42: 3,
    ]

    enum Mode: String, CaseIterable, Identifiable {
        case request = "Request mask"
        case status = "DTC status"
        case availability = "Availability"
        var id: String { rawValue }
    }

    struct DTCRecord: Identifiable {
        let id = UUID()
        let dtc: [UInt8]
        let status: UInt8
        var hex: String { "0x" + dtc.map { $0.hex }.joined() }
        /// SAE J2012 rendering; only meaningful if DTCFormatIdentifier is SAE / ISO 15031-6.
        var sae: String {
            let sys = Array("PCBU")[Int(dtc[0] >> 6)]
            return "\(sys)\((dtc[0] >> 4) & 3)\(String(dtc[0] & 0x0F, radix: 16).uppercased())\(dtc[1].hex)-\(dtc[2].hex)"
        }
    }

    struct Analysis {
        var mask: UInt8?
        var mode: Mode = .request
        var explanation = ""
        var records: [DTCRecord] = []
        var error: String?
    }

    static func parseHex(_ s: String) -> Result<[UInt8], ParseError> {
        let clean = s.replacingOccurrences(of: "0x", with: "", options: .caseInsensitive)
            .filter { !" ,:-\n\t".contains($0) }
        guard !clean.isEmpty else { return .failure(.init("Enter a hex value, e.g. 2F or 19 02 2F.")) }
        guard clean.allSatisfy(\.isHexDigit) else { return .failure(.init("Only hex digits 0-9 and A-F are allowed.")) }
        if clean.count == 1 { return .success([UInt8(clean, radix: 16)!]) }
        guard clean.count % 2 == 0 else { return .failure(.init("Odd number of hex digits.")) }
        var out: [UInt8] = []
        var i = clean.startIndex
        while i < clean.endIndex {
            let j = clean.index(i, offsetBy: 2)
            out.append(UInt8(clean[i..<j], radix: 16)!)
            i = j
        }
        return .success(out)
    }

    static func analyze(_ b: [UInt8]) -> Analysis {
        var a = Analysis()
        if b.count == 1 { a.mask = b[0]; return a }

        switch b[0] {
        case 0x19:
            let sf = b[1] & 0x7F
            let name = subFunctions[sf] ?? "sub-function 0x\(sf.hex)"
            guard let pos = requestMaskPosition[sf] else {
                a.explanation = "0x19 \(sf.hex) = \(name). This sub-function has no DTCStatusMask."
                return a
            }
            guard b.count > pos else { a.error = "Status mask byte is missing."; return a }
            a.mask = b[pos]
            a.mode = .request
            a.explanation = "ReadDTCInformation 0x\(sf.hex) \(name). 0x\(b[pos].hex) is the DTCStatusMask: the ECU returns DTCs where (status & mask & availabilityMask) ≠ 0, i.e. ANY selected bit set."
        case 0x59:
            let sf = b[1]
            let name = subFunctions[sf] ?? "sub-function 0x\(sf.hex)"
            let p = sf == 0x17 ? 3 : 2
            guard b.count > p else { a.error = "Response too short."; return a }
            a.mask = b[p]
            a.mode = .availability
            if [0x01, 0x11, 0x12].contains(sf) {
                let count = b.count >= p + 4 ? Int(b[p + 2]) << 8 | Int(b[p + 3]) : nil
                a.explanation = "Positive response, \(name). Availability mask 0x\(b[p].hex)" +
                    (count.map { ", matching DTC count: \($0)." } ?? ".")
                return a
            }
            var i = p + 1
            while i + 3 < b.count {
                a.records.append(.init(dtc: Array(b[i..<i + 3]), status: b[i + 3]))
                i += 4
            }
            a.explanation = "Positive response, \(name). 0x\(b[p].hex) is the DTCStatusAvailabilityMask (bits this ECU supports), followed by \(a.records.count) DTC record(s) of 3 DTC bytes + 1 status byte."
        case 0x7F:
            a.explanation = "Negative response to 0x\((b.count > 1 ? b[1] : 0).hex), NRC 0x\((b.count > 2 ? b[2] : 0).hex)."
        default:
            a.error = "Not a 0x19 request, 0x59 response or 0x7F negative response."
        }
        return a
    }

    static func setBits(_ v: UInt8) -> [String] {
        bits.filter { v & $0.value != 0 }.map(\.abbr)
    }

    /// One-line meaning of a byte in the given reading mode.
    static func brief(_ v: UInt8, mode: Mode) -> String {
        func s(_ i: Int) -> Bool { v & (1 << UInt8(i)) != 0 }
        switch mode {
        case .request:
            return v == 0 ? "Selects nothing: no DTCs reported"
                : "Reports DTCs with ANY of: \(setBits(v).joined(separator: ", "))"
        case .availability:
            return "ECU supports: \(setBits(v).joined(separator: ", "))"
        case .status:
            let failed = s(0) || s(2) || s(3) || s(5)
            let state = s(0) ? "Active now" : s(3) ? "Stored, not active" : s(2) ? "Pending"
                : s(5) ? "Failed earlier, passing now" : s(4) ? "Not tested since clear" : "No fault"
            var tags = [state]
            if s(0) && s(3) { tags.append("Confirmed") }
            if s(2) && (s(0) || s(3)) { tags.append("Pending") }
            if !s(0) && s(1) { tags.append("failed earlier this cycle") }
            if s(7) { tags.append("Lamp ON") }
            if failed && s(4) { tags.append("test not run since clear") }
            else if s(6) && !s(4) { tags.append("test not run this cycle") }
            return tags.joined(separator: " · ")
        }
    }

    static let plain = ["active now", "failed this cycle", "pending", "confirmed",
                        "not tested since clear", "failed since last clear", "not tested this cycle", "lamp on"]

    private static func list(_ a: [String], _ conj: String) -> String {
        a.count < 2 ? a.joined() : a.dropLast().joined(separator: ", ") + " \(conj) " + a.last!
    }

    /// One plain-English sentence for a DTC's actual status byte.
    static func statusSentence(_ v: UInt8) -> String {
        func s(_ i: Int) -> Bool { v & (1 << UInt8(i)) != 0 }
        let main: String
        if s(0) { main = "The fault is present right now" }
        else if s(3) { main = "The fault is not present now, but is stored as confirmed from earlier" }
        else if s(2) { main = "The fault was seen recently but is not confirmed yet" }
        else if s(5) { main = "The fault occurred since the last clear but is passing now" }
        else if s(4) { main = "The test hasn't run since codes were cleared, so the state is unknown" }
        else { return s(6) ? "No fault recorded, but the test hasn't run yet this cycle." : "No fault recorded, and the test has completed." }
        var extra: [String] = []
        if s(0) { extra.append(s(3) ? "confirmed in memory" : "not confirmed yet") }
        if !s(0) && s(1) { extra.append("it failed earlier this cycle") }
        if s(7) { extra.append("the warning lamp is on") }
        if !s(4) && s(6) { extra.append("this cycle's test hasn't run yet") }
        let tail = extra.count == 1 ? " and " + extra[0] : extra.isEmpty ? "" : ", " + list(extra, "and")
        return main + tail + "."
    }

    /// One sentence for the overall picture: the whole frame if one was entered, else the byte.
    static func overall(bytes: [UInt8], analysis a: Analysis, mask: UInt8, mode: Mode) -> String {
        if bytes.count > 1 {
            if bytes[0] == 0x7F { return "The ECU rejected the request (NRC 0x\((bytes.count > 2 ? bytes[2] : 0).hex))." }
            if bytes[0] == 0x59, [0x01, 0x11, 0x12].contains(bytes[1]), bytes.count >= 6 {
                return "The ECU has \(Int(bytes[4]) << 8 | Int(bytes[5])) DTC(s) matching the requested mask."
            }
            if bytes[0] == 0x59, a.error == nil {
                let n = a.records.count
                if n == 0 { return "The ECU reports no DTCs matching the requested mask." }
                let act = a.records.filter { $0.status & 0x01 != 0 }
                let stored = a.records.filter { $0.status & 0x01 == 0 && $0.status & 0x08 != 0 }
                let pend = a.records.filter { $0.status & 0x09 == 0 && $0.status & 0x04 != 0 }
                let other = n - act.count - stored.count - pend.count
                var parts: [String] = []
                if !act.isEmpty { parts.append("\(act.count) active now (\(act.map(\.sae).joined(separator: ", ")))") }
                if !stored.isEmpty { parts.append("\(stored.count) stored but not active") }
                if !pend.isEmpty { parts.append("\(pend.count) pending") }
                if other > 0 { parts.append("\(other) passing now") }
                return "The ECU reports \(n) DTC\(n > 1 ? "s" : ""): \(list(parts, "and"))." + (act.isEmpty ? " Nothing is failing right now." : "")
            }
            if a.mask == nil { return a.error ?? a.explanation }
        }
        switch mode {
        case .request:
            guard mask != 0 else { return "This request selects nothing, so the ECU will return no DTCs." }
            let what = list(bits.filter { mask & $0.value != 0 }.map { plain[$0.id] }, "or")
            let counting = bytes.count > 1 && [0x01, 0x11, 0x12].contains(bytes[1] & 0x7F)
            return counting ? "You're asking the ECU how many DTCs are \(what)." : "You're asking the ECU for every DTC that is \(what)."
        case .availability:
            return "The ECU supports \(setBits(mask).count) of 8 status bits: \(setBits(mask).joined(separator: ", "))."
        case .status:
            return statusSentence(mask)
        }
    }
}

struct ParseError: Error { let message: String; init(_ m: String) { message = m } }

extension UInt8 {
    var hex: String { String(format: "%02X", self) }
}
