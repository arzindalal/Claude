import SwiftUI

struct ContentView: View {
    @State private var input = "19 02 2F"
    @State private var mask: UInt8 = 0x2F
    @State private var mode: DTCDecoder.Mode = .request
    @State private var analysis = DTCDecoder.Analysis()
    @State private var parseError: String?
    @State private var bytes: [UInt8] = []

    private let examples = ["19 02 2F", "19 02 08", "59 02 FF 01 23 45 2F C1 00 87 08", "2F", "AF"]

    var body: some View {
        NavigationStack {
            Form {
                Section("Input (hex)") {
                    TextField("e.g. 19 02 2F", text: $input)
                        .font(.system(.title3, design: .monospaced))
                        .textInputAutocapitalization(.characters)
                        .autocorrectionDisabled()
                        .onChange(of: input) { _, _ in run() }
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack {
                            ForEach(examples, id: \.self) { ex in
                                Button(ex) { input = ex }
                                    .font(.caption.monospaced())
                                    .buttonStyle(.bordered)
                            }
                        }
                    }
                    if let parseError { Text(parseError).foregroundStyle(.red) }
                    if let err = analysis.error { Text(err).foregroundStyle(.red) }
                    if !analysis.explanation.isEmpty {
                        Text(analysis.explanation).font(.callout).foregroundStyle(.secondary)
                    }
                }

                Section("Overall") {
                    Text(DTCDecoder.overall(bytes: bytes, analysis: analysis, mask: mask, mode: mode))
                        .font(.headline)
                }

                Section {
                    HStack(alignment: .firstTextBaseline) {
                        Text("0x\(mask.hex)").font(.system(size: 34, weight: .semibold, design: .monospaced))
                        Spacer()
                        Text(binary(mask)).font(.system(.body, design: .monospaced)).foregroundStyle(.secondary)
                    }
                    Text(DTCDecoder.brief(mask, mode: mode))
                        .font(.headline)
                    Picker("Read as", selection: $mode) {
                        ForEach(DTCDecoder.Mode.allCases) { Text($0.rawValue).tag($0) }
                    }
                    .pickerStyle(.segmented)

                    ForEach(DTCDecoder.bits.reversed()) { bit in
                        let on = mask & bit.value != 0
                        Button { mask ^= bit.value } label: {
                            HStack(alignment: .top, spacing: 12) {
                                VStack {
                                    Text("bit").font(.caption2)
                                    Text("\(bit.id)").font(.headline.monospaced())
                                }
                                .frame(width: 36)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("\(bit.name)  ").bold() + Text(bit.abbr).font(.caption.monospaced()).foregroundColor(.secondary)
                                    Text(bit.detail).font(.footnote).foregroundStyle(.secondary)
                                }
                                Spacer()
                                Text(on ? "1" : "0")
                                    .font(.callout.monospaced().bold())
                                    .padding(.horizontal, 10).padding(.vertical, 4)
                                    .background(on ? Color.green.opacity(0.85) : Color.gray.opacity(0.2), in: Capsule())
                                    .foregroundStyle(on ? .white : .secondary)
                            }
                        }
                        .buttonStyle(.plain)
                        .listRowBackground(on ? Color.green.opacity(0.12) : nil)
                    }
                } header: {
                    Text("Status byte")
                } footer: {
                    Text("Tap a bit to toggle it.")
                }


                if !analysis.records.isEmpty {
                    Section {
                        ForEach(analysis.records) { r in
                            Button {
                                bytes = [r.status]
                                mask = r.status
                                mode = .status
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack {
                                        Text(r.hex).font(.body.monospaced())
                                        Spacer()
                                        Text("0x\(r.status.hex)").font(.body.monospaced().bold())
                                    }
                                    Text(DTCDecoder.brief(r.status, mode: .status)).font(.subheadline)
                                    Text("\(r.sae)  ·  \(DTCDecoder.setBits(r.status).joined(separator: " "))")
                                        .font(.caption.monospaced()).foregroundStyle(.secondary)
                                }
                            }
                            .buttonStyle(.plain)
                        }
                    } header: {
                        Text("DTC records")
                    } footer: {
                        Text("Tap a record to decode its status. P/C/B/U code is only meaningful if the ECU uses SAE J2012 / ISO 15031-6 DTC format.")
                    }
                }
            }
            .navigationTitle("DTC Status")
            .onAppear(perform: run)
        }
    }

    private func run() {
        analysis = DTCDecoder.Analysis()
        switch DTCDecoder.parseHex(input) {
        case .failure(let e): parseError = e.message; bytes = []
        case .success(let parsed):
            parseError = nil
            bytes = parsed
            analysis = DTCDecoder.analyze(bytes)
            if let m = analysis.mask {
                mask = m
                mode = bytes.count > 1 ? analysis.mode : .status
            }
        }
    }

    private func binary(_ v: UInt8) -> String {
        let s = String(v, radix: 2)
        let p = String(repeating: "0", count: 8 - s.count) + s
        return "\(p.prefix(4)) \(p.suffix(4))"
    }
}

#Preview { ContentView() }
