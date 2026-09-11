# Mahbrus: odczyt ręczny i nadzorowany harmonogram

Netlify przyjmuje wyłącznie autoryzowane wywołania natywnej aplikacji. Zaszyfrowany raport zawiera osobny losowy klucz możliwości odświeżania dla rodziców i ucznia. Funkcja przechowuje skróty tych kluczy, mapuje je na konkretne workflow i nie przyjmuje od klienta nazwy repozytorium, workflow, ref ani inputs.

GitHub token: fine-grained PAT, tylko jakiesluchawki/promenada-dziennik, Actions read/write i wymagane Metadata read. Przechowywany jako MAHBRUS_GITHUB_TOKEN, wyłącznie po stronie Netlify. Nie trafia do aplikacji, raportu ani repozytorium. Funkcja nie otrzymuje haseł Librusa ani treści szkolnych.

POST /api/refresh uruchamia workflow. GET /api/refresh?run=ID sprawdza postęp, z tym samym Authorization: Bearer. Błędny klucz kończy się 401 bez połączenia z GitHubem. Brak konfiguracji lub błąd GitHuba kończy się 503 bez ujawnienia odpowiedzi upstream.

Odstęp między próbami: 5 minut, kontrolowany również wewnątrz serializowanego workflow. Odczyty rodziców i ucznia są osobne. Netlify wyzwala rodziców o 06:30 i 18:00 Europe/Warsaw, ucznia dwie minuty później. W razie potrzeby sprawdza ponownie po 10 i 20 minutach; maksymalnie trzy próby na okno. Funkcje mają harmonogram UTC obejmujący oba przesunięcia czasu; kod ogranicza pracę do właściwego okna w Warszawie. Uruchomienia poza oknem nie wywołują nawet GitHuba. Nie używamy już opóźnianego zdarzenia schedule GitHuba.

Watchdog nie odszyfrowuje raportów. Sprawdza w Actions, czy krok „Verify fresh published report” naprawdę zakończył się sukcesem w bieżącym oknie. Krok ten na runnerze sprawdza czas i zdrowie każdego konta oraz zgodność szyfrogramu pobranego z Pages z plikiem lokalnym. Sam sukces zadania lub pominięcie odczytu nie wystarczy. Ręczny, zweryfikowany odczyt także pokrywa okno. Przy trwającym zadaniu nie uruchamiamy następnego.

Wywołanie harmonogramu używa inputs.scheduled=true. Kolektor pomija zdrowy odczyt już wykonany w tym oknie; jeśli poprzednio zawiodła publikacja, można ponownie opublikować istniejący szyfrogram bez logowania do Librusa. Nie zapisujemy danych szkolnych ani ich haseł na Netlify. Wolna kolejka GitHuba lub awaria usług nadal może opóźnić raport; aplikacja pokazuje informację o starszych danych od 07:00/18:30. Uruchomienie przyciskiem nie omija kontroli dostępu Librusa, CAPTCHA ani ograniczeń konta.

Wdrożenie: oficjalny Netlify CLI, katalog server, projekt mahbrus-refresh. Tylko public/ i funkcje. Pozostała aplikacja i zaszyfrowane raporty nadal na GitHub Pages. Nie podłączaj automatycznych deployów serwera do aktualizacji raportu: niepotrzebnie zużywałyby kredyty Netlify.

Testy: npm test (Node z obsługą TypeScript stripping).
