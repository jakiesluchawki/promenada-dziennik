# Mahbrus iOS

Prywatny rodzinny dziennik dla iPhone'a i iPada. Przygotowywana aktualizacja TestFlight **1.0.0 (3)**, iOS 18+.
Nazwa aplikacji i schematu: **Mahbrus**. Bundle ID: **pl.mahboob.mahbrus**.
Promenada.xcodeproj to wewnętrzna nazwa projektu, zachowana po zmianie marki.

## Działanie

Aplikacja dołącza zaakceptowany kompaktowy interfejs i pobiera gotowy raport z istniejącego serwera. Harmonogram odczytu Librusa działa niezależnie od telefonu i Maca dwa razy dziennie dla raportu rodziców i ucznia. Przycisk „Odśwież z Librusa” zleca odczyt przez zabezpieczoną funkcję Netlify i czeka na publikację GitHub Actions. „Wczytaj raport” pobiera już opublikowaną wersję. Otwarcie aplikacji nie uruchamia kolektora.

Hasło dziennika jest wpisywane raz. Po poprawnym odblokowaniu trafia do systemowego Keychain (WhenUnlockedThisDeviceOnly), bez synchronizacji przez iCloud. Raport jest odszyfrowywany lokalnie przez CryptoKit AES-GCM i CommonCrypto PBKDF2-SHA256. Paczka nie zawiera haseł ani danych uczniów.

Ostatni zaszyfrowany raport jest dostępny offline z widocznym komunikatem o braku połączenia. Plik ma pełną ochronę iOS i jest wyłączony z kopii zapasowej. „Wyloguj” usuwa zapamiętany dostęp, raport oraz lokalne oznaczenia.

Interfejs zawiera sprawy, pocztę, ogłoszenia, plan lekcji, terminy, oceny, frekwencję, uwagi, zadania domowe i osiągnięcia. Załączniki otwierają systemowy panel udostępniania. Linki do Librusa otwierają się poza aplikacją. Oznaczenia „przeczytane” i „zrobione” pozostają lokalne dla urządzenia zgodnie z decyzją rodziny.

## Automatyczne wczytywanie (build 3)

Przy zapamiętanym dostępie aplikacja pokazuje zweryfikowany lokalny szyfrogram od razu i pobiera aktualną publikację w tle. Powrót na pierwszy plan sprawdza gotowy plik (najczęściej raz na 30 sekund, bez powielania trwających operacji). Nie wysyła POST do kolektora. Nie resetuje lokalnych oznaczeń; niezmieniony raport nie przebudowuje otwartego widoku. Zmiana dnia odświeża jednak informację o świeżości. Offline pozostaje ostatni raport z komunikatem. Nowe dane nadal przechodzą walidację granicy rodzic/uczeń przed zapisem i wyświetleniem.

Nowy harmonogram serwerowy: rodzice 06:30/18:00, uczeń 06:32/18:02 czasu Warszawy, z kontrolą i ograniczonymi ponowieniami po 10 i 20 minutach. Szczegóły i ograniczenia: server/README.md. Starsze wpisy poniżej dokumentują stan poprzednich wydań.

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

## Dostęp ucznia (build 2)

Ten sam pakiet, wybór Rodzic / Uczeń przy pierwszym wejściu. Uczeń podaje login i hasło swojego zarejestrowanego konta Librusa. Hasło służy lokalnie do odszyfrowania osobnego raportu, a nie do logowania telefonu w Librusie. Odczyt serwerowy używa osobnych GitHub Secrets. Raport ucznia powstaje wyłącznie z konta potwierdzonego jako uczeń; błędy zachowują poprzedni raport ucznia i nigdy nie podstawiają rodzinnego.

Osobna ścieżka szyfrogramu, kontrola audience/principal/role przed renderowaniem, odseparowane oznaczenia i cache. Stare rodzinne hasło w Keychain migruje automatycznie. Wylogowanie usuwa dostęp i lokalne szyfrogramy. Zmiana hasła Librusa wymaga aktualizacji sekretu kolektora i ponownego zaszyfrowania raportu.

Bieżące oznaczenia nadal są lokalne na urządzeniu. Zmiany danych w Librusie są widoczne po odczycie i publikacji; przycisk nie oznacza natychmiastowej synchronizacji.

## Stan builda 2 — 10 września 2026, wieczór

Build 1.0.0 (2) przesłano, Apple potwierdziło VALID / INTERNAL_ONLY oraz IN_BETA_TESTING. Jest przypisany do grupy „Mahbrus — rodzina”. Instalacja builda 2 przez właściciela jest widoczna w App Store Connect; nie zastępuje to pełnej weryfikacji na urządzeniach wszystkich testerów.

Konto Kostka zaakceptowało zaproszenie App Store Connect, ma rolę Marketing ograniczoną do Mahbrusa i zostało dodane do grupy wewnętrznej. Apple API przyjęło ponowne wysłanie zaproszenia TestFlight. Kostek zainstalował aplikację; potwierdził to użytkownik oraz API Apple (stan INSTALLED). Panel wcześniej pokazywał „No Builds Available”; dokładna przyczyna rozbieżności nie została ustalona. Dodatkową grupę diagnostyczną usunięto po sprawdzeniu, że Kostek i build 2 pozostają w grupie rodzinnej.

Weryfikacja nowego zakresu: sześć testów bramki odświeżania, cztery testy granicy raportu ucznia i ochrony przed powtórnymi odczytami oraz cztery scenariusze iPhone'a (rodzic, uczeń, odrzucenie raportu rodzica w trybie ucznia, działy i załączniki). Scenariusz załącznika przeszedł po poprawieniu przewijania w samym teście. Zbiory danych do testów UI są fikcyjne.

Oba rzeczywiste odczyty GitHub Actions i publikacje Pages zakończyły się powodzeniem: rodzice — run 34523713250, uczeń — run 34523709943. Harmonogramy obu raportów: 07:07 i 18:07 Europe/Warsaw.

**Ręczne odświeżanie uruchomione:** projekt Netlify mahbrus-refresh korzysta z klucza przechowywanego jako sekret środowiska produkcyjnego. Serwer przechowuje osobne skróty uprawnień rodzica i ucznia. Dnia 10 września 2026 zweryfikowano pełną ścieżkę przycisku: autoryzowany POST → GitHub Actions → poprawne zakończenie → nowszy raport pobrany z Pages i odszyfrowany w pamięci. Rodzice: run 34528942367, odczyt 20:52:45 UTC; uczeń: run 34528945652, odczyt 20:53:27 UTC. Poprzednie oba raporty pochodziły z 20:00 UTC. Końcowy deploy funkcji: 6aa318522a4972bc0ce9ff13. Nie było potrzeby zmiany builda iOS.

Klucz GitHuba jest ograniczony do repozytorium promenada-dziennik, Actions read/write i wymaganych Metadata read, z terminem do 30 czerwca 2027. Nie trafia do aplikacji ani zaszyfrowanego raportu. Diagnostyka zapisuje wyłącznie kod odpowiedzi GitHuba, metodę, nazwę workflow i typ błędu, bez tokenów i danych szkolnych. Sześć testów bramki przechodzi po dodaniu diagnostyki i usuwania białych znaków z końców wklejonego klucza.

**Ustalona decyzja produktu:** oznaczenia „przeczytane”, „zrobione” i priorytety pozostają lokalne dla urządzenia. Nie synchronizujemy ich między członkami rodziny ani nie wysyłamy tych zmian do Librusa. Ręczne odświeżanie zleca odczyt; po jego zakończeniu aplikacja pobiera opublikowany raport. Minimalny odstęp między kolejnymi próbami wynosi 5 minut; kliknięcie podczas trwającego odczytu dołącza do sprawdzania jego stanu.
