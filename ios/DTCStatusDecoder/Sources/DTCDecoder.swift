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

    static func interpret(_ v: UInt8, mode: Mode) -> [String] {
        func s(_ i: Int) -> Bool { v & (1 << UInt8(i)) != 0 }
        switch mode {
        case .request:
            if v == 0 { return ["0x00 selects no bits, so the ECU reports no DTCs."] }
            var out = ["Matches a DTC if ANY of \(setBits(v).joined(separator: ", ")) is 1 (logical OR, not AND)."]
            if v == 0xFF { out.append("0xFF effectively reports all stored DTCs.") }
            if v == 0x08 { out.append("0x08 is the classic 'confirmed DTCs only' query.") }
            out.append("The ECU first ANDs this with its DTCStatusAvailabilityMask.")
            return out
        case .availability:
            return ["ECU supports: \(setBits(v).joined(separator: ", ")). Unsupported bits always read 0."]
        case .status:
            var out: [String] = []
            if s(0) { out.append("Active: fault present right now.") }
            else if s(3) { out.append("Historic: confirmed earlier, not failing on the latest test.") }
            else if s(2) { out.append("Pending: failed recently, not yet confirmed.") }
            else if s(5) { out.append("Failed at some point since last clear, now passing.") }
            else { out.append("No failure indicated.") }
            if s(7) { out.append("Warning lamp requested.") }
            if s(4) { out.append("Test not completed since last clear, so TF = 0 doesn't prove the fault is gone.") }
            else if s(6) { out.append("Test not completed this cycle yet.") }
            return out
        }
    }
}

struct ParseError: Error { let message: String; init(_ m: String) { message = m } }

extension UInt8 {
    var hex: String { String(format: "%02X", self) }
}
