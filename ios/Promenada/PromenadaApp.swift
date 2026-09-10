import SwiftUI
import WebKit

@main
struct MahbrusApp: App {
    var body: some Scene {
        WindowGroup { JournalView().preferredColorScheme(.light) }
    }
}

struct JournalView: View {
    @StateObject private var model = JournalModel()
    @Environment(\.scenePhase) private var phase
    @State private var password = ""
    @State private var login = ""
    @State private var role = "parent"
    @State private var showPassword = false
    @State private var forget = false
    private let pink = Color(red: 1, green: 0.882, blue: 0.922)
    private let ink = Color(red: 0.427, green: 0.392, blue: 0.208)
    var body: some View {
        ZStack {
            pink.ignoresSafeArea()
            JournalWebView(model: model).opacity(model.open ? 1 : 0).accessibilityHidden(!model.open).allowsHitTesting(model.open)
            if !model.open {
                ScrollView {
                    VStack(alignment: .leading, spacing: 18) {
                        Text("mahbrus").font(.custom("Romie-Regular", size: 34, relativeTo: .largeTitle))
                        Spacer(minLength: 16)
                        Image("House").resizable().scaledToFit().frame(width: 124, height: 112).accessibilityHidden(true)
                        Text("Szkolne sprawy\npod ręką.").font(.custom("Romie-Regular", size: 36, relativeTo: .largeTitle)).fixedSize(horizontal: false, vertical: true)
                        Text("Wiadomości, plan lekcji i sprawy do dopilnowania.")
                            .font(.custom("Roobert-Regular", size: 17, relativeTo: .body)).foregroundStyle(ink.opacity(0.8))
                        if model.busy {
                            ProgressView("Otwieram dziennik…").tint(ink).padding(.vertical)
                        } else {
                            VStack(alignment: .leading, spacing: 12) {
                                Picker("Dostęp", selection: $role) {
                                    Text("Rodzic").tag("parent")
                                    Text("Uczeń").tag("student")
                                }.pickerStyle(.segmented).accessibilityIdentifier("journal-role")
                                if role == "student" {
                                    TextField("Login ucznia w Librusie", text: $login)
                                        .textContentType(.username).textInputAutocapitalization(.never).autocorrectionDisabled()
                                        .padding(15).background(.white.opacity(0.65), in: RoundedRectangle(cornerRadius: 16))
                                        .accessibilityIdentifier("journal-login")
                                }
                                Text(role == "student" ? "Hasło ucznia w Librusie" : "Hasło do dziennika").font(.custom("Roobert-Bold", size: 15, relativeTo: .subheadline))
                                Group {
                                    if showPassword { TextField("Hasło do dziennika", text: $password) }
                                    else { SecureField("Hasło do dziennika", text: $password) }
                                }.textContentType(.password).textInputAutocapitalization(.never)
                                    .autocorrectionDisabled().submitLabel(.go).onSubmit(unlock)
                                    .padding(15).background(.white.opacity(0.65), in: RoundedRectangle(cornerRadius: 16))
                                    .accessibilityIdentifier("journal-password")
                                Toggle("Pokaż hasło", isOn: $showPassword).font(.custom("Roobert-Regular", size: 15, relativeTo: .subheadline)).tint(ink)
                                Button(action: unlock) { Text("Otwórz dziennik").frame(maxWidth: .infinity).padding(16) }
                                    .buttonStyle(.plain).background(ink, in: Capsule()).foregroundStyle(.white)
                                    .disabled(password.isEmpty || (role == "student" && login.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
                                    .accessibilityIdentifier("journal-unlock")
                                Text("Wpisujesz je tylko pierwszy raz. Ten iPhone zapamięta dostęp w pęku kluczy.")
                                    .font(.custom("Roobert-Regular", size: 13, relativeTo: .footnote)).foregroundStyle(ink.opacity(0.8))
                            }
                        }
                        if !model.error.isEmpty { Text(model.error).font(.custom("Roobert-Regular", size: 15, relativeTo: .subheadline)).foregroundStyle(.red).accessibilityIdentifier("journal-error") }
                        Spacer(minLength: 16)
                    }.padding(28).frame(maxWidth: 560).frame(maxWidth: .infinity, alignment: .center)
                }
            }
            if phase != .active {
                pink.ignoresSafeArea()
                Text("mahbrus").font(.custom("Romie-Regular", size: 38, relativeTo: .largeTitle)).foregroundStyle(ink)
            }
        }
        .foregroundStyle(ink)
        .font(.custom("Roobert-Regular", size: 17, relativeTo: .body))
        .alert("Zapomnieć dostęp na tym iPhonie?", isPresented: $model.confirmForget) {
            Button("Anuluj", role: .cancel) {}
            Button("Wyloguj", role: .destructive) { password = ""; model.forget() }
        } message: { Text("Usuniemy zapisane hasło i raport z urządzenia. Przy następnym otwarciu podasz hasło ponownie.") }
        .onChange(of: phase) { _, new in if new == .active { model.foreground() } }
        .sheet(item: $model.attachment, onDismiss: { model.removeShare() }) { item in ShareSheet(url: item.url) }
    }
    private func unlock() {
        let value = password
        password = ""
        model.unlock(JournalAccess(role: role, login: login.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(), password: value))
    }
}

struct ShareItem: Identifiable { let id = UUID(); let url: URL }
struct ShareSheet: UIViewControllerRepresentable {
    let url: URL
    func makeUIViewController(context: Context) -> UIActivityViewController {
        let controller = UIActivityViewController(activityItems: [url], applicationActivities: nil)
        return controller
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

struct JournalWebView: UIViewRepresentable {
    @ObservedObject var model: JournalModel
    func makeUIView(context: Context) -> WKWebView { model.makeWebView() }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
