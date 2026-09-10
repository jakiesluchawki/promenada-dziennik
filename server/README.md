# Mahbrus: ręczny odczyt

Netlify przyjmuje wyłącznie autoryzowane wywołania natywnej aplikacji. Zaszyfrowany raport zawiera osobny losowy klucz możliwości odświeżania dla rodziców i ucznia. Funkcja przechowuje skróty tych kluczy, mapuje je na konkretne workflow i nie przyjmuje od klienta nazwy repozytorium, workflow, ref ani inputs.

GitHub token: fine-grained PAT, tylko jakiesluchawki/promenada-dziennik, Actions read/write i wymagane Metadata read. Przechowywany jako MAHBRUS_GITHUB_TOKEN, wyłącznie po stronie Netlify. Nie trafia do aplikacji, raportu ani repozytorium. Funkcja nie otrzymuje haseł Librusa ani treści szkolnych.

POST /api/refresh uruchamia workflow. GET /api/refresh?run=ID sprawdza postęp, z tym samym Authorization: Bearer. Błędny klucz kończy się 401 bez połączenia z GitHubem. Brak konfiguracji lub błąd GitHuba kończy się 503 bez ujawnienia odpowiedzi upstream.

Odstęp między próbami: 5 minut, kontrolowany również wewnątrz serializowanego workflow. Odczyty rodziców i ucznia są osobne. Oba mają harmonogram 07:07 i 18:07 Europe/Warsaw. Harmonogram GitHuba może wystartować z opóźnieniem. Uruchomienie przyciskiem nie omija kontroli dostępu Librusa, CAPTCHA ani ograniczeń konta; nie gwarantuje uniknięcia blokady automatyzacji.

Wdrożenie: oficjalny Netlify CLI, katalog server, projekt mahbrus-refresh. Tylko public/ i funkcje. Pozostała aplikacja i zaszyfrowane raporty nadal na GitHub Pages. Nie podłączaj automatycznych deployów serwera do aktualizacji raportu: niepotrzebnie zużywałyby kredyty Netlify.

Testy: npm test (Node z obsługą TypeScript stripping).
