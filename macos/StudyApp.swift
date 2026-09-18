import SwiftUI
import AppKit
import UniformTypeIdentifiers

struct Folder: Decodable, Identifiable { var id: String; var name: String }
struct LibraryNode: Decodable, Identifiable {
    var id: String; var name: String; var path: String; var parent: String
    var is_folder: Bool; var can_select: Bool; var preview_path: String?; var children: [LibraryNode]?
    var foldersOnly: LibraryNode {
        var copy = self
        copy.children = children?.filter { $0.is_folder }.map { $0.foldersOnly }
        if copy.children?.isEmpty == true { copy.children = nil }
        return copy
    }
}
struct Attachment: Decodable, Identifiable { var id: String; var name: String }
struct QuizQuestion: Decodable { var topic: String; var question: String; var options: [String] }
struct Quiz: Decodable { var title: String; var questions: [QuizQuestion]; var warnings: [String] }
struct Review: Decodable { var question: String; var correct: Bool; var answer: String; var explanation: String }
struct Result: Decodable { var score_percent: Int; var weak_topics: [String]; var recommended_minutes: Int; var explanation: String; var review: [Review] }
struct TestItem: Decodable, Identifiable {
    var id: String; var subject: String; var title: String; var date: String
    var material_ids: [String]
    var start_time: String?; var folder_id: String?; var folder_selection: String; var test_number: Int; var school_scope: String; var study_hours: Double
    var knowledge_level: Int; var target_grade: Int; var scope_notes: String
    var attachments: [Attachment]; var output_path: String?; var diagnostic: Quiz?; var diagnostic_result: Result?
}
struct AppState: Decodable {
    var library: [LibraryNode]
    var tests: [TestItem]; var folders: [Folder]; var geography_path: String; var attention: String; var report_path: String
    var easistent_connected: Bool; var calendar_connected: Bool
}
struct Envelope: Decodable { var ok: Bool; var data: AppState?; var error: String? }
let ink = Color(red: 0.12, green: 0.23, blue: 0.20)
let green = Color(red: 0.19, green: 0.39, blue: 0.31)
let paper = Color(red: 0.965, green: 0.96, blue: 0.94)

@MainActor final class Model: ObservableObject {
    @Published var state: AppState?
    @Published var selected: String?
    @Published var busy = false
    @Published var message = ""
    @Published var error = false
    var root: String { (try? String(contentsOf: Bundle.main.url(forResource: "Workspace", withExtension: "txt")!, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines)) ?? "" }
    func call(_ request: [String: Any], label: String = "", done: (() -> Void)? = nil) {
        guard !busy else { return }
        busy = true; message = label; error = false
        let root = self.root
        guard let input = try? JSONSerialization.data(withJSONObject: request) else { busy = false; return }
        Task {
            let output: Data? = await Task.detached {
                let process = Process(); process.executableURL = URL(fileURLWithPath: root + "/.venv/bin/python")
                process.arguments = ["-m", "study.desktop", root]; process.currentDirectoryURL = URL(fileURLWithPath: root)
                var env = ProcessInfo.processInfo.environment
                env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
                process.environment = env
                let stdin = Pipe(), stdout = Pipe()
                process.standardInput = stdin; process.standardOutput = stdout
                process.standardError = FileHandle.nullDevice
                do {
                    try process.run(); stdin.fileHandleForWriting.write(input); try stdin.fileHandleForWriting.close()
                    let data = stdout.fileHandleForReading.readDataToEndOfFile(); process.waitUntilExit(); return data
                } catch { return nil }
            }.value
            busy = false
            if let output, let response = try? JSONDecoder().decode(Envelope.self, from: output) {
                if response.ok, let data = response.data {
                    state = data
                    if selected == nil { selected = data.tests.first?.id }
                    message = label.isEmpty ? "" : "Končano."
                    done?()
                } else { error = true; message = response.error ?? "Dejanje ni uspelo." }
            } else { error = true; message = "Programa ni bilo mogoče zagnati. Preveri mapo remarkable-goat in okolje Python." }
        }
    }
    func open(_ path: String) { NSWorkspace.shared.open(URL(fileURLWithPath: path)) }
}

@main struct StudyApp: App {
    @StateObject var model = Model()
    var body: some Scene {
        WindowGroup("Učna priprava") { ContentView().environmentObject(model).frame(minWidth: 1080, minHeight: 760).tint(green).preferredColorScheme(.light) }
            .windowStyle(.hiddenTitleBar)
            .commands { CommandGroup(replacing: .newItem) { Button("Osveži") { model.call(["action": "refresh"], label: "Preverjam teste, koledar in zapiske …") }.keyboardShortcut("r") } }
    }
}

struct ContentView: View {
    @EnvironmentObject var model: Model
    @State var newTest = false
    @State var showLibrary = false
    @State var month = Date()
    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 20) {
                Label("Učna priprava", systemImage: "book.closed.fill").font(.title2.bold()).foregroundStyle(ink).padding(.top, 22)
                Text("TVOJ PROSTOR ZA UČENJE").font(.system(size: 10, weight: .semibold)).tracking(1.7).foregroundStyle(.secondary)
                Button("Datoteke reMarkable", systemImage: "folder.badge.gearshape") { showLibrary = true }.buttonStyle(.bordered).controlSize(.large)
                calendar
                HStack { Text("Vsi testi").font(.headline); Spacer(); Button { newTest = true } label: { Image(systemName: "plus") }.buttonStyle(.borderless).help("Dodaj test") }
                ScrollView {
                    VStack(spacing: 8) {
                        ForEach(model.state?.tests ?? []) { test in
                            Button { model.selected = test.id } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 5) {
                                        Text(test.subject).font(.system(size: 15, weight: .semibold))
                                        Text(test.date + (test.start_time.map { " · " + String($0.prefix(5)) } ?? "")).font(.caption).foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    Image(systemName: test.output_path == nil ? "chevron.right" : "checkmark.circle.fill").font(.caption)
                                }.padding(14).background(model.selected == test.id ? Color.white : Color.clear).clipShape(RoundedRectangle(cornerRadius: 12))
                            }.buttonStyle(.plain).foregroundStyle(ink)
                        }
                        if model.state?.tests.isEmpty == true { Text("Dodaj test ali osveži eAsistent.").font(.callout).foregroundStyle(.secondary) }
                    }
                }
                Spacer(minLength: 0)
                VStack(alignment: .leading, spacing: 8) {
                    Label(model.state?.calendar_connected == true ? "Google Calendar povezan" : "Google Calendar ni povezan", systemImage: "calendar")
                    Label(model.state?.easistent_connected == true ? "eAsistent povezan" : "eAsistent: povezava v pripravi", systemImage: "arrow.triangle.2.circlepath")
                    Text("Samodejno vsako uro, ko Mac deluje. Priprava 7 dni pred testom.").font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                }.font(.caption)
                if let state = model.state, !state.attention.isEmpty {
                    Text(state.attention).font(.caption).foregroundStyle(.orange).fixedSize(horizontal: false, vertical: true)
                    Button("Poročilo povezav") { model.open(state.report_path) }.buttonStyle(.borderless)
                }
                Button("Odpri geografsko gradivo", systemImage: "folder") { if let path = model.state?.geography_path { model.open(path) } }.buttonStyle(.borderless)
                Button("Poveži eAsistent", systemImage: "person.badge.key") { model.call(["action": "connect_school"], label: "Prijavi se v odprtem uradnem oknu eAsistent …") }.disabled(model.busy)
                Button("Osveži povezave", systemImage: "arrow.clockwise") { model.call(["action": "refresh"], label: "Preverjam eAsistent, Google Calendar in reMarkable …") }.disabled(model.busy)
            }.padding(24).frame(width: 282).background(paper)
            Divider()
            VStack(spacing: 0) {
                if let test = model.state?.tests.first(where: { $0.id == model.selected }) {
                    TestView(test: test).id(test.id)
                } else {
                    ContentUnavailableView("Tvoji testi, na enem mestu", systemImage: "calendar", description: Text("Dodaj test ali osveži povezave, da začneš."))
                }
                if model.busy || !model.message.isEmpty {
                    HStack(spacing: 12) {
                        if model.busy { ProgressView().controlSize(.small) }
                        Text(model.message).font(.callout).foregroundStyle(model.error ? .red : ink)
                        Spacer()
                    }.padding(14).background(paper)
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity).background(Color.white)
        }.task { model.call(["action": "state"]) }.sheet(isPresented: $newTest) { AddTestView().environmentObject(model) }
        .sheet(isPresented: $showLibrary) { ExplorerView(initialFolder: nil, onChoose: nil).environmentObject(model) }
    }
    var calendar: some View {
        VStack(spacing: 12) {
            HStack {
                Button { month = Calendar.current.date(byAdding: .month, value: -1, to: month)! } label: { Image(systemName: "chevron.left") }
                Spacer(); Text(month.formatted(.dateTime.month(.wide).year()).capitalized).font(.subheadline.bold()); Spacer()
                Button { month = Calendar.current.date(byAdding: .month, value: 1, to: month)! } label: { Image(systemName: "chevron.right") }
            }.buttonStyle(.borderless)
            let cal = Calendar(identifier: .gregorian)
            let start = cal.date(from: cal.dateComponents([.year, .month], from: month))!
            let offset = (cal.component(.weekday, from: start) + 5) % 7
            let count = cal.range(of: .day, in: .month, for: month)!.count
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 2), count: 7), spacing: 7) {
                ForEach(Array(["P", "T", "S", "Č", "P", "S", "N"].enumerated()), id: \.offset) { _, label in Text(label).font(.caption2).foregroundStyle(.secondary) }
                ForEach(0..<(offset + count), id: \.self) { n in
                    if n < offset { Color.clear.frame(height: 27) }
                    else {
                        let day = cal.date(byAdding: .day, value: n - offset, to: start)!
                        let key = dateKey(day)
                        let matches = (model.state?.tests ?? []).filter { $0.date == key }
                        Button { if let first = matches.first { model.selected = first.id } } label: {
                            Text("\(n - offset + 1)").font(.system(size: 12, weight: matches.isEmpty ? .regular : .bold)).frame(width: 27, height: 27)
                                .background(matches.isEmpty ? (cal.isDateInToday(day) ? Color.white : Color.clear) : green)
                                .foregroundStyle(matches.isEmpty ? ink : .white).clipShape(Circle())
                        }.buttonStyle(.plain).help(matches.map(\.subject).joined(separator: ", "))
                    }
                }
            }
        }.environment(\.locale, Locale(identifier: "sl_SI"))
    }
}
func dateKey(_ date: Date) -> String { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; return f.string(from: date) }

struct TestView: View {
    @EnvironmentObject var model: Model
    let test: TestItem
    @State var hours: Double = 3
    @State var knowledge = 2
    @State var grade = 4
    @State var scope = ""
    @State var folder = ""
    @State var showFiles = false
    @State var materials: [String] = []
    @State var answers: [Int] = []
    @State var dirty = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 26) {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("PRIPRAVA NA TEST").font(.system(size: 10, weight: .semibold)).tracking(2).foregroundStyle(green)
                        Text(test.subject).font(.system(size: 36, weight: .bold, design: .rounded)).foregroundStyle(ink)
                        Text(test.date + "  ·  " + test.title).foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("Odpri Google Calendar", systemImage: "arrow.up.right") { NSWorkspace.shared.open(URL(string: "https://calendar.google.com")!) }.buttonStyle(.borderless)
                }
                GroupBox {
                    VStack(alignment: .leading, spacing: 18) {
                        HStack { Text("Moj cilj").font(.title3.bold()); Spacer(); if dirty && (hours != test.study_hours || knowledge != test.knowledge_level || grade != test.target_grade || scope != test.scope_notes || folder != test.folder_selection || materials.sorted() != test.material_ids.sorted()) { Text("Neshranjene spremembe").font(.caption).foregroundStyle(.orange) } }
                        HStack(alignment: .top, spacing: 24) {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Skupni čas za učenje").font(.subheadline.bold())
                                Stepper(value: $hours, in: 0.25...100, step: 0.25) { Text("\(hours, specifier: "%.2g") ur").font(.title2.monospacedDigit()) }
                                Text("Skupaj do testa, ne na dan.").font(.caption).foregroundStyle(.secondary)
                            }.frame(maxWidth: .infinity)
                            VStack(alignment: .leading, spacing: 8) {
                                Text("Ciljna ocena").font(.subheadline.bold())
                                Picker("Ocena", selection: $grade) { ForEach(2...5, id: \.self) { Text("\($0)").tag($0) } }.pickerStyle(.segmented).labelsHidden()
                            }.frame(maxWidth: .infinity)
                        }
                        Picker("Koliko že znam?", selection: $knowledge) {
                            Text("Še nič").tag(0); Text("Malo").tag(1); Text("Približno polovico").tag(2); Text("Večino").tag(3); Text("Zelo dobro").tag(4)
                        }
                        Text("To je tvoja samoocena. Predtest spodaj preveri znanje na vzorcu vprašanj.").font(.caption).foregroundStyle(.secondary)
                    }.padding(14)
                }
                GroupBox {
                    VStack(alignment: .leading, spacing: 14) {
                        Text("Kaj bo na testu?").font(.title3.bold())
                        Text("Vpiši teme, poglavja ali učiteljeva navodila. Gradivo bo uporabilo izbrane zapiske in priloge.").font(.callout).foregroundStyle(.secondary)
                        TextEditor(text: $scope).font(.body).frame(height: 90).padding(6).background(paper).clipShape(RoundedRectangle(cornerRadius: 8))
                        if !test.school_scope.isEmpty { Text("eAsistent: " + test.school_scope).font(.callout).foregroundStyle(green) }
                        Picker(materials.isEmpty ? "Mapa reMarkable" : "Zamenjaj z eno mapo", selection: Binding(get: { folder }, set: { folder = $0; materials = [] })) {
                            Text("Samodejno: \(test.subject) / Test \(test.test_number)").tag("")
                            if let existing = test.folder_id, !(model.state?.folders.contains(where: { $0.id == existing }) ?? false) { Text("Povezana mapa").tag(existing) }
                            ForEach(model.state?.folders ?? []) { f in Text(f.name).tag(f.id) }
                        }
                        Button("Izberi zapiske in mape", systemImage: "checklist") { showFiles = true }
                        if !materials.isEmpty {
                            Text("Izbrani viri (\(materials.count))").font(.headline)
                            ForEach(materials, id: \.self) { identifier in
                                let node = allLibraryNodes(model.state?.library ?? []).first { $0.id == identifier }
                                HStack {
                                    Label(node?.path ?? "Vir ni več v seznamu — osveži datoteke", systemImage: node?.is_folder == true ? "folder.fill" : "doc.text").font(.callout)
                                    Spacer()
                                    Button { materials.removeAll { $0 == identifier } } label: { Image(systemName: "xmark.circle") }.buttonStyle(.borderless)
                                }
                            }
                            Text("Izbrane mape vključujejo vse zapiske in podmape. Isti zapisek se uporabi le enkrat.").font(.caption).foregroundStyle(.secondary)
                            Button("Ponastavi na samodejno izbiro Test N") { materials = []; folder = "" }.buttonStyle(.borderless)
                        }
                        Text("Samodejno številčenje po predmetu v tem šolskem letu: prvi test v koledarju → Test 1. Če takih podmap ni, uporabi celo mapo predmeta. Ročna izbira ima prednost.").font(.caption).foregroundStyle(.secondary)
                        HStack { Button("Dodaj slike ali PDF", systemImage: "paperclip") { addFiles() }; Spacer(); Text("Do 20 MB na datoteko").font(.caption).foregroundStyle(.secondary) }
                        ForEach(test.attachments) { a in
                            HStack { Label(a.name, systemImage: "doc"); Spacer(); Button { model.call(["action": "remove_attachment", "id": test.id, "attachment_id": a.id], label: "Odstranjujem prilogo …") } label: { Image(systemName: "xmark.circle") }.buttonStyle(.borderless).help("Odstrani iz snovi") }
                        }
                        HStack { Spacer(); Button("Shrani nastavitve") { save() }.buttonStyle(.borderedProminent) }
                    }.padding(14)
                }
                GroupBox {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack { Label("Najprej preveri znanje", systemImage: "checklist").font(.title3.bold()); Spacer(); Text("NEOBVEZNO").font(.caption2.bold()).foregroundStyle(.secondary) }
                        Text("Kratek predtest iz tvojih zapiskov odkrije šibke teme in predlaga začetni čas učenja. Rezultat ne napoveduje šolske ocene.").font(.callout).foregroundStyle(.secondary)
                        Button(test.diagnostic == nil ? "Ustvari predtest" : "Ustvari nov predtest", systemImage: "sparkles") { saveThen("diagnostic", label: "Berem zapiske in pripravljam predtest. To lahko traja nekaj minut …") }
                        if let result = test.diagnostic_result {
                            HStack(alignment: .top, spacing: 30) {
                                VStack(alignment: .leading) { Text("\(result.score_percent)%").font(.largeTitle.bold()).foregroundStyle(green); Text("Pravilno na predtestu").font(.caption) }
                                VStack(alignment: .leading) { Text("\(result.recommended_minutes) min").font(.title.bold()); Text("Predlagani začetni čas").font(.caption); Button("Uporabi ta čas") { hours = min(100, Double(result.recommended_minutes) / 60); save() } }
                            }
                            Text(result.weak_topics.isEmpty ? "Vsa vprašanja so bila pravilna. Nadaljuj z zahtevnejšimi vajami in samostojnim priklicem." : "Prednostne teme: " + result.weak_topics.joined(separator: ", ")).font(.callout)
                            Text(result.explanation).font(.caption).foregroundStyle(.secondary)
                            DisclosureGroup("Odgovori in razlage") {
                                ForEach(Array(result.review.enumerated()), id: \.offset) { _, r in
                                    VStack(alignment: .leading, spacing: 5) { Label(r.question, systemImage: r.correct ? "checkmark.circle.fill" : "xmark.circle").font(.headline); Text(r.answer); Text(r.explanation).foregroundStyle(.secondary) }.frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 8)
                                }
                            }
                        } else if let quiz = test.diagnostic {
                            ForEach(Array(quiz.questions.enumerated()), id: \.offset) { i, q in
                                VStack(alignment: .leading, spacing: 8) {
                                    Text("\(i + 1). \(q.question)").font(.headline)
                                    Picker(q.topic, selection: Binding(get: { answers.indices.contains(i) ? answers[i] : -2 }, set: { value in if answers.count != quiz.questions.count { answers = Array(repeating: -2, count: quiz.questions.count) }; answers[i] = value })) {
                                        Text("Izberi odgovor").tag(-2)
                                        ForEach(Array(q.options.enumerated()), id: \.offset) { j, option in Text(option).tag(j) }
                                        Text("Ne vem").tag(-1)
                                    }.pickerStyle(.radioGroup).labelsHidden().fixedSize(horizontal: false, vertical: true)
                                }.padding(.vertical, 6)
                            }
                            ForEach(quiz.warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
                            Button("Oceni predtest") { model.call(["action": "score", "id": test.id, "answers": answers], label: "Ocenjujem predtest …") }.buttonStyle(.borderedProminent).disabled(answers.count != quiz.questions.count || answers.contains(-2))
                        }
                    }.padding(14)
                }
                HStack(spacing: 14) {
                    Button("Pripravi zapiske in vaje", systemImage: "sparkles") { saveThen("prepare", label: "Pripravljam gradivo in pošiljam na reMarkable. To lahko traja nekaj minut …") }.buttonStyle(.borderedProminent).controlSize(.large)
                    if let path = test.output_path { Button("Odpri gradivo", systemImage: "folder") { model.open(path) }.controlSize(.large) }
                }
                Text("Branje rokopisa: GPT-5.6 Sol · Učno gradivo in predtest: GPT-5.6 Luna").font(.caption).foregroundStyle(.secondary)
            }.padding(34).frame(maxWidth: 920, alignment: .leading).disabled(model.busy)
        }.sheet(isPresented: $showFiles) {
            ExplorerView(initialFolder: folder.isEmpty ? test.folder_id : folder, initialSelection: materials.isEmpty ? (folder.isEmpty ? [] : [folder]) : materials, onChoose: { chosen in materials = chosen; folder = ""; dirty = true }).environmentObject(model)
        }.onAppear { load() }.onChange(of: test.id) { _, _ in load() }
            .onChange(of: hours) { _, _ in dirty = true }.onChange(of: knowledge) { _, _ in dirty = true }.onChange(of: grade) { _, _ in dirty = true }.onChange(of: scope) { _, _ in dirty = true }.onChange(of: folder) { _, _ in dirty = true }.onChange(of: materials) { _, _ in dirty = true }
    }
    func load() { hours = test.study_hours; knowledge = test.knowledge_level; grade = test.target_grade; scope = test.scope_notes; folder = test.folder_selection; materials = test.material_ids; dirty = false }
    func save(_ done: (() -> Void)? = nil) {
        model.call(["action": "save", "id": test.id, "study_hours": hours, "knowledge_level": knowledge, "target_grade": grade, "scope_notes": scope, "folder_id": folder, "material_ids": materials], label: "Shranjujem …") { dirty = false; done?() }
    }
    func saveThen(_ action: String, label: String) { save { model.call(["action": action, "id": test.id], label: label) } }
    func addFiles() {
        let panel = NSOpenPanel(); panel.allowsMultipleSelection = true; panel.canChooseDirectories = false; panel.allowedContentTypes = [.pdf, .png, .jpeg, .tiff, .webP]
        if panel.runModal() == .OK { let paths = panel.urls.map(\.path); save { model.call(["action": "attach", "id": test.id, "paths": paths], label: "Dodajam gradivo …") } }
    }
}
struct AddTestView: View {
    @EnvironmentObject var model: Model
    @Environment(\.dismiss) var dismiss
    @State var subject = ""
    @State var title = "Ocenjevanje znanja"
    @State var date = Date()
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Dodaj test").font(.title.bold())
            TextField("Predmet", text: $subject); TextField("Naslov", text: $title)
            DatePicker("Datum", selection: $date, displayedComponents: .date)
            HStack { Button("Prekliči") { dismiss() }; Spacer(); Button("Dodaj") { model.call(["action": "add_test", "subject": subject, "title": title, "date": dateKey(date)], label: "Dodajam test …") { model.selected = model.state?.tests.last(where: { $0.subject == subject && $0.date == dateKey(date) })?.id; dismiss() } }.buttonStyle(.borderedProminent).disabled(subject.trimmingCharacters(in: .whitespaces).isEmpty || model.busy) }
        }.padding(30).frame(width: 430).textFieldStyle(.roundedBorder)
    }
}

struct ExplorerView: View {
    @EnvironmentObject var model: Model
    @Environment(\.dismiss) var dismiss
    var initialFolder: String?
    var initialSelection: [String] = []
    var onChoose: (([String]) -> Void)?
    @State var selectedItems: Set<String> = []
    @State var folderID: String?
    @State var selectedFile: String?
    @State var search = ""
    var roots: [LibraryNode] { model.state?.library ?? [] }
    func flatten(_ nodes: [LibraryNode]) -> [LibraryNode] { nodes.flatMap { [$0] + flatten($0.children ?? []) } }
    var all: [LibraryNode] { flatten(roots) }
    var current: LibraryNode? { all.first { $0.id == folderID } }
    var selected: LibraryNode? { all.first { $0.id == selectedFile } }
    var rows: [LibraryNode] {
        let children = current?.children ?? roots
        return search.isEmpty ? children : all.filter { $0.name.localizedCaseInsensitiveContains(search) }
    }
    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 14) {
                Image(systemName: "folder.fill").font(.title2).foregroundStyle(green)
                VStack(alignment: .leading, spacing: 3) {
                    Text("Datoteke reMarkable").font(.title2.bold()).foregroundStyle(ink)
                    Text("Mape, podmape in tvoji zapiski").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button { model.call(["action": "refresh_files"], label: "Osvežujem datoteke reMarkable …") } label: { Label("Osveži", systemImage: "arrow.clockwise") }.disabled(model.busy)
                Button("Zapri") { dismiss() }.keyboardShortcut(.cancelAction)
            }.padding(22)
            Divider()
            HSplitView {
                VStack(alignment: .leading, spacing: 0) {
                    Button { navigate(nil) } label: { Label("Vse datoteke", systemImage: "externaldrive").font(.headline).frame(maxWidth: .infinity, alignment: .leading).padding(14) }.buttonStyle(.plain)
                    List(selection: $folderID) {
                        OutlineGroup(roots.filter { $0.is_folder }.map { $0.foldersOnly }, children: \.children) { node in
                            Label(node.name, systemImage: "folder.fill").foregroundStyle(ink).tag(node.id)
                        }
                    }.listStyle(.sidebar)
                }.frame(minWidth: 220, idealWidth: 265, maxWidth: 360).background(paper)
                VStack(alignment: .leading, spacing: 0) {
                    HStack {
                        Button { navigate(current?.parent.isEmpty == false ? current?.parent : nil) } label: { Image(systemName: "arrow.up") }.disabled(current == nil).help("Nadrejena mapa")
                        Text(current?.path ?? "reMarkable").font(.headline).lineLimit(2)
                        Spacer()
                    }.padding(16)
                    HStack { Image(systemName: "magnifyingglass").foregroundStyle(.secondary); TextField("Poišči datoteko ali mapo …", text: $search).textFieldStyle(.plain) }.padding(10).background(paper).clipShape(RoundedRectangle(cornerRadius: 8)).padding(.horizontal, 16).padding(.bottom, 12)
                    HStack { Text("IME"); Spacer(); Text("VRSTA / VSEBINA") }.font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary).padding(.horizontal, 24).padding(.bottom, 8)
                    Divider()
                    if rows.isEmpty {
                        ContentUnavailableView(search.isEmpty ? "Mapa je prazna" : "Ni zadetkov", systemImage: "folder", description: Text(search.isEmpty ? "Osveži za zadnje spremembe s tablice." : "Poskusi z drugim imenom."))
                    } else {
                        List {
                            ForEach(rows) { node in
                                HStack(spacing: 12) {
                                    if onChoose != nil && node.can_select {
                                        Button { toggle(node) } label: {
                                            Image(systemName: included(node) ? "checkmark.square.fill" : "square").foregroundStyle(green).font(.title3)
                                        }.buttonStyle(.borderless).accessibilityLabel("Izberi " + node.name)
                                        .help(inherited(node) ? "Vključeno z izbrano nadrejeno mapo" : "Izberi za gradivo").disabled(inherited(node))
                                    }
                                    Button {
                                        if node.is_folder { navigate(node.id) }
                                        else { selectedFile = node.id }
                                    } label: {
                                        HStack(spacing: 12) {
                                            Image(systemName: node.is_folder ? "folder.fill" : "doc.text").font(.title3).foregroundStyle(node.is_folder ? green : .secondary).frame(width: 24)
                                            VStack(alignment: .leading, spacing: 3) {
                                                Text(node.name).font(.body).foregroundStyle(ink)
                                                if !search.isEmpty { Text(node.path).font(.caption).foregroundStyle(.secondary).lineLimit(1) }
                                            }
                                            Spacer()
                                            Text(node.is_folder ? "\(node.children?.count ?? 0) elementov" : "Dokument").font(.caption).foregroundStyle(.secondary)
                                            if node.is_folder { Image(systemName: "chevron.right").font(.caption).foregroundStyle(.secondary) }
                                        }.contentShape(Rectangle())
                                    }.buttonStyle(.plain)
                                }.padding(.vertical, 8).padding(.horizontal, 4).listRowBackground(selectedFile == node.id ? green.opacity(0.10) : Color.clear)
                            }
                        }.listStyle(.plain)
                    }
                    if let file = selected, !file.is_folder {
                        Divider()
                        VStack(alignment: .leading, spacing: 8) {
                            Label(file.name, systemImage: "doc.text").font(.headline)
                            Text(file.path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                            if let path = file.preview_path {
                                Button("Odpri predogled PDF", systemImage: "doc.richtext") { model.open(path) }
                                Text("Predogled zadnje prenesene različice na tem Macu.").font(.caption).foregroundStyle(.secondary)
                            } else {
                                Text("Dokument je na reMarkable. Predogled PDF bo na voljo po prenosu te mape za učno pripravo.").font(.caption).foregroundStyle(.secondary)
                            }
                        }.padding(16).frame(maxWidth: .infinity, alignment: .leading).background(paper)
                    }
                    HStack {
                        Text("\(rows.count) elementov").font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        if onChoose != nil {
                            if let current, current.can_select {
                                Button(selectedItems.contains(current.id) ? "Odstrani celo mapo" : "Izberi celo mapo") { toggle(current) }.disabled(model.busy || inherited(current))
                            }
                            Button("Uporabi izbor (\(selectedItems.count))") { onChoose?(selectedItems.sorted()); dismiss() }.buttonStyle(.borderedProminent).disabled(selectedItems.isEmpty || model.busy)
                        }
                    }.padding(16)
                }.frame(minWidth: 460)
            }
            if model.busy || model.error {
                Divider()
                HStack { if model.busy { ProgressView().controlSize(.small) }; Text(model.message).font(.callout).foregroundStyle(model.error ? .red : ink); Spacer() }.padding(12)
            }
        }.frame(width: 960, height: 650).background(.white).tint(green)
        .onAppear {
            folderID = initialFolder
            selectedItems = Set(initialSelection)
            if roots.isEmpty { model.call(["action": "refresh_files"], label: "Prenašam seznam datotek …") }
        }.onChange(of: folderID) { _, _ in selectedFile = nil }
    }
    func inherited(_ node: LibraryNode) -> Bool {
        var parent = node.parent
        var visited = Set<String>()
        while !parent.isEmpty && !visited.contains(parent) {
            if selectedItems.contains(parent) { return true }
            visited.insert(parent)
            parent = all.first { $0.id == parent }?.parent ?? ""
        }
        return false
    }
    func included(_ node: LibraryNode) -> Bool { selectedItems.contains(node.id) || inherited(node) }
    func toggle(_ node: LibraryNode) {
        if selectedItems.contains(node.id) { selectedItems.remove(node.id) }
        else {
            if node.is_folder { selectedItems.subtract(Set(flatten(node.children ?? []).map(\.id))) }
            selectedItems.insert(node.id)
        }
    }
    func navigate(_ identifier: String?) { folderID = identifier; selectedFile = nil; search = "" }
}


func allLibraryNodes(_ nodes: [LibraryNode]) -> [LibraryNode] {
    nodes.flatMap { [$0] + allLibraryNodes($0.children ?? []) }
}
