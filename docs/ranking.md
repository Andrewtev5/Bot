# Ranking produktów

Bot wybiera produkty w dwóch krokach: najpierw odrzuca te, które nie spełniają wymagań zapytania, a potem sortuje pozostałe według sumy punktów.

Kod: `app/search/ranking.py` (punktacja), `app/search/vocabulary.py` (słownictwo), `app/search/evaluate.py` (pomiar jakości).

## Filtry

Produkt jest odrzucany niezależnie od punktów, gdy:

- zapytanie dotyczy łazienki, a produkt nie jest kinkietem, plafonem ani oświetleniem lustra;
- zapytanie dotyczy lampy smart, a w opisie produktu nie ma takiej funkcji;
- produkt ma inną barwę światła, niż chce klient (biała albo ciepła).

## Skala wag

Wagi nie są dobierane osobno. Każda jest jednym z sześciu poziomów, a kolejny poziom jest wart dwa razy więcej niż poprzedni:

| Poziom | Punkty | Znaczenie |
|---|---:|---|
| `HINT` | 10 | Słabe potwierdzenie, na przykład słowo w opisie |
| `WEAK` | 20 | Słowo w kategorii lub w wygenerowanych słowach kluczowych |
| `MODERATE` | 40 | Dopasowanie do nazwy przez synonim |
| `STRONG` | 80 | Słowo wpisane przez klienta w nazwie lub tagach |
| `VERY_STRONG` | 160 | Cała fraza w nazwie lub tagach |
| `DECISIVE` | 320 | Identyfikator produktu, jednoznaczne dopasowanie |

Podwajanie ma prosty sens: jeden sygnał wyższego poziomu jest wart tyle, co dwa sygnały niższego poziomu.

Kolejność poziomów wynika z trzech zasad:

1. **Cała fraza jest pewniejsza niż pojedyncze słowo.** Dlatego fraza dostaje `VERY_STRONG`, a słowo najwyżej `STRONG`.
2. **Słowo wpisane przez klienta jest pewniejsze niż synonim.** Synonim może być powiązany tylko luźno, więc to samo dopasowanie jest o poziom niżej.
3. **Pole krótkie i opisowe znaczy więcej niż długi tekst.** Słowo w nazwie mówi o produkcie więcej niż to samo słowo w opisie.

## Pomiar jakości

Zbiór testowy `tests/data/ranking_golden.json` zawiera 54 zapytania po polsku i angielsku. Przy każdym zapytaniu jest wzorzec identyfikatorów produktów uznawanych za trafne. Pomiar uruchamia się poleceniem:

```powershell
python -m app.search.evaluate
```

Wyniki na katalogu 170 produktów:

| Metoda | P@5 | MRR | nDCG@5 | Hit@5 |
|---|---:|---:|---:|---:|
| Kolejność z katalogu (bez rankingu) | 0,089 | 0,181 | 0,096 | 0,333 |
| BM25 (standardowa metoda wyszukiwania pełnotekstowego) | 0,659 | 0,889 | 0,763 | 0,926 |
| Reguły, wszystkie wagi równe | 0,722 | 0,946 | 0,825 | 0,981 |
| Poprzednie wagi ręczne (ponad 30 różnych liczb) | 0,733 | 0,948 | 0,834 | 0,981 |
| **Reguły, skala wag (obecne rozwiązanie)** | **0,733** | **0,948** | **0,835** | **0,981** |

Oznaczenia: P@5 to udział trafnych produktów w pierwszej piątce, MRR to średnia odwrotność pozycji pierwszego trafnego wyniku, nDCG@5 uwzględnia kolejność wyników, a Hit@5 to udział zapytań z co najmniej jednym trafnym wynikiem w pierwszej piątce.

## Wnioski

- **Jakość daje słownictwo i reguły, a nie dokładne liczby.** Reguły są wyraźnie lepsze od BM25, bo rozumieją synonimy i polsko-angielskie zapytania. Różnica między równymi wagami a skalą jest niewielka.
- **Uproszczenie wag nie pogorszyło wyników.** Zamiana ponad 30 różnych liczb na 6 poziomów dała te same wyniki, a pierwsze piątki pokrywają się średnio w 97% (indeks Jaccarda).
- **Wyniki są stabilne.** Zmiana dowolnej pojedynczej wagi o -50%, -25%, +25% lub +50% utrzymuje MRR w zakresie od 0,948 do 0,960, czyli nigdy poniżej wyniku bazowego. Dokładna wartość wagi nie jest więc krytyczna.

## Ograniczenia

- Etykiety trafności wynikają z identyfikatorów produktów i przygotował je autor zbioru, a nie niezależni oceniający. Wyniki służą do porównywania metod na tym samym zbiorze, a nie jako ocena bezwzględna.
- Reguły kontekstowe (łazienka, stół, czytanie w łóżku) dotyczą niewielu zapytań, więc MRR słabo reaguje na ich wagi. Ich działanie sprawdzają osobne testy w `tests/test_product_repository.py`.
- Zapytanie „lampa z piórami” nie ma trafnego wyniku w pierwszej piątce, bo słowa „pióra” nie ma w słownictwie. Zostawiono je w zbiorze celowo, żeby nie dopasowywać systemu do testu.
- Przy większym katalogu lub rzeczywistych danych o kliknięciach warto byłoby uczyć wagi na tych danych (learning to rank). Przy 170 produktach i bez historii zachowań klientów taki model przeuczyłby się.
