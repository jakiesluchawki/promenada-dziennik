# Mahbrus iOS

Prywatny rodzinny dziennik dla iPhone'a i iPada. Wydanie TestFlight **1.0.0 (1)**, iOS 18+.
Nazwa aplikacji i schematu: **Mahbrus**. Bundle ID: **pl.mahboob.mahbrus**.
Promenada.xcodeproj to wewnętrzna nazwa projektu, zachowana po zmianie marki.

## Działanie

Aplikacja dołącza zaakceptowany kompaktowy interfejs i pobiera gotowy raport z istniejącego serwera. Harmonogram odczytu Librusa działa niezależnie od telefonu i Maca. Przycisk „Sprawdź raport” pobiera opublikowaną wersję; nie uruchamia dodatkowego logowania do Librusa.

Hasło dziennika jest wpisywane raz. Po poprawnym odblokowaniu trafia do systemowego Keychain (WhenUnlockedThisDeviceOnly), bez synchronizacji przez iCloud. Raport jest odszyfrowywany lokalnie przez CryptoKit AES-GCM i CommonCrypto PBKDF2-SHA256. Paczka nie zawiera haseł ani danych uczniów.

Ostatni zaszyfrowany raport jest dostępny offline z widocznym komunikatem o braku połączenia. Plik ma pełną ochronę iOS i jest wyłączony z kopii zapasowej. „Wyloguj” usuwa zapamiętany dostęp, raport oraz lokalne oznaczenia.

Interfejs zawiera sprawy, pocztę, ogłoszenia, plan lekcji, terminy, oceny, frekwencję, uwagi, zadania domowe i osiągnięcia. Załączniki otwierają systemowy panel udostępniania. Linki do Librusa otwierają się poza aplikacją. Oznaczenia „przeczytane” i „zrobione” są na razie lokalne dla urządzenia.

## Budowanie i testy

Wymagany Xcode z SDK iOS 18 lub nowszym oraz Python 3. Zweryfikowano w Xcode 26.6 na symulatorach iOS 26.5.

Synchronizacja publicznego UI przed budowaniem:

    python3 ios/scripts/sync-web.py

Skrypt kopiuje wyłącznie interfejs, ilustracje i fonty. Wyklucza raport i zastępuje logowanie w przeglądarce natywnym mostkiem.

Testy iPhone'a, z identyfikatorem własnego symulatora i katalogiem poza repozytorium:

    MAHBRUS_BUILD_DIR=/absolute/path/to/build MAHBRUS_SIMULATOR_ID=SIMULATOR_UUID ios/scripts/test-iphone.sh

Dla iPada uruchom PromenadaUITests/testTabletLayout ze schematu Mahbrus. Testy korzystają wyłącznie z fikcyjnych danych. Obsługa testowych raportów jest kompilowana tylko w Debug; nie trafia do wydania Release.

Archiwum do kontroli, jeszcze bez podpisu:

    MAHBRUS_BUILD_DIR=/absolute/path/to/build ios/scripts/archive-candidate.sh

## Wynik weryfikacji — 10 września 2026

- iPhone 17 Pro: dwa scenariusze UI, bez błędów — pierwsze logowanie, złe hasło, zapamiętanie dostępu po restarcie, offline, wylogowanie, odświeżanie, działy dziennika, zachowanie oznaczeń, otwieranie i ponowne otwieranie załącznika.
- iPad mini (A17 Pro): plan lekcji, nawigacja do frekwencji i kontrola zrzutu, bez błędów.
- Natywne odszyfrowanie aktualnego raportu obu kont; odrzucenie złego hasła, naruszonego szyfrogramu i zmienionych parametrów szyfrowania.
- Archiwum Release zbudowane poprawnie. Sprawdzono nazwę, Bundle ID, wersję, fonty, manifest prywatności i brak testowych mechanizmów oraz raportu w pakiecie.
- Przejrzano zrzuty pierwszego dostępu, kompaktowego dziennika, planu oraz systemowego panelu załączników. Test na fizycznym urządzeniu pozostaje etapem TestFlight.

## Wydanie

Wyłącznie TestFlight Internal Only. ExportOptions.template.plist ma testFlightInternalTestingOnly=true; po rejestracji aplikacji trzeba uzupełnić konfigurację profilu i certyfikatu. To szablon, a nie gotowy profil podpisywania.

10 września 2026 zarejestrowano aplikację, podpisano archiwum istniejącym certyfikatem dystrybucyjnym i przesłano wersję 1.0.0 (1). Apple potwierdziło processingState=VALID oraz buildAudienceType=INTERNAL_ONLY. Build przypisano do wewnętrznej grupy „Mahbrus — rodzina”; pierwsze zaproszenie testera ma status INVITED. Dodano polski opis aplikacji i instrukcję testowania.

App Store Connect ID: 6810649704. Build wygasa 9 grudnia 2026. Nie wykonano publicznej publikacji ani zgłoszenia do App Review. Dalsi testerzy wewnętrzni wymagają zaakceptowanego zaproszenia do App Store Connect i osobnego przypisania do grupy TestFlight.
