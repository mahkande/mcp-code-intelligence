DİKKAT: Yeni MD5 hashing sistemi nedeniyle, mevcut indekslerin hash alanlarını doldurmak için ilk çalıştırmada --force-reindex yapılması önerilir.

Açıklama: `content_hash` artık MD5 olarak hesaplanmakta ve indeks meta verisinde saklanmaktadır. Eğer mevcut indekslerinizde hash alanları boşsa veya eski hash algoritmaları kullanıldıysa, tam doğruluk ve ilişki yeniden oluşturma için `--force-reindex` ile yeniden indeksleme yapın.
