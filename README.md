# Promenada
Rodzinny dziennik w stylistyce CHMURNIKA: Romie, Roobert, różowy papier, oliwkowy tekst i autorskie ilustracje z filcu, w tym tło kompaktowego widoku.

Publiczna część zawiera wyłącznie interfejs, fonty, ilustracje oraz zaszyfrowany raport. Dane szkolne i załączniki są odszyfrowywane w przeglądarce kluczem wyprowadzonym z hasła. Repozytorium nie zawiera loginów do Librusa ani hasła dziennika.

## Ochrona treści
AES-256-GCM; PBKDF2-SHA256, 600 000 iteracji; losowa sól i nonce dla każdego wydania. Hasło nie jest przechowywane w kodzie, localStorage ani sessionStorage. Dziennik zamyka się po 30 minutach bezczynności lub opuszczeniu strony.

GitHub Pages udostępnia publiczny interfejs i szyfrogram. Nie zapewnia tu logowania po stronie serwera. Poufność raportu zależy od silnego, prywatnego hasła; opublikowane kopie szyfrogramu mogą być pobrane i zachowane.

## Dane
Przegląd, wiadomości, ogłoszenia, plan, terminy, oceny, frekwencja, uwagi, zadania i osiągnięcia. Na stronie zawsze widnieje czas ostatniego odczytu. Błędy odświeżenia nie są przedstawiane jako brak wiadomości lub brak zdarzeń.

Odczyt treści wiadomości może oznaczyć je jako przeczytane w Librusie. Promenada korzysta z własnego archiwum i porównuje treść, niezależnie od statusu „przeczytane”.

Ilustracje i prompty: [ARTWORK.md](ARTWORK.md).

## Automatyczny odczyt
GitHub Actions planuje odczyt kont o 07:07 i 18:07 w strefie Europe/Warsaw, szyfruje raport i publikuje go w Pages. Komputer domowy może być wyłączony. Harmonogram może być opóźniony albo pominąć uruchomienie. Przycisk „Sprawdź raport” pobiera ostatni raport i informuje, czy pojawił się nowszy plik; w aplikacji iOS przycisk „Odśwież z Librusa” uruchamia nowy odczyt przez zabezpieczoną funkcję Netlify i czeka na opublikowanie raportu. Oznaczenia pozostają lokalne na urządzeniu, zgodnie z decyzją rodziny.

Sekrety LIBRUS_ACCOUNTS i SITE_PASSWORD są przekazywane wyłącznie do etapu kolektora. Artefakt Pages zawiera tylko dozwolone pliki interfejsu i szyfrogram. Przy błędzie konta zachowywany jest ostatni poprawny odczyt oraz ostrzeżenie.

## Nowości i priorytety
Fioletowe znaczniki wskazują nieprzejrzane treści, bordowe bliskie lub przekroczone terminy, oliwkowe sprawy do dopilnowania, a niebieskie informacje. Priorytet wiadomości można zmienić. Stan przeczytania i wykonania zapisuje się w danej przeglądarce, bez synchronizacji między urządzeniami. Nowe treści są pobierane automatycznie; pierwsza lista spraw została opracowana ręcznie, a priorytety korzystają z prostych reguł, bez modelu AI.

## Kompaktowy widok produkcyjny

Zatwierdzona wersja B jest głównym interfejsem. Korzysta z aktualizowanego report.enc.json, dotychczasowego hasła i zapisanych oznaczeń produkcyjnych. Ścieżka /kompakt/ przekierowuje do głównej strony.
