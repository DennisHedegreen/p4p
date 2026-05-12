from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from p4p_core import ModuleManifest, load_reference_module_catalog, load_reference_provider_catalog


DEFAULT_LOCALE = "da"
SUPPORTED_LOCALES = ("da", "sv", "tr", "ar", "ku")
RTL_LOCALES = {"ar"}

P4P_ROOT = Path(__file__).resolve().parent
GITHUB_BLOB_BASE_URL = "https://github.com/DennisHedegreen/p4p/blob/main"


LOCALE_META = {
    "da": {"label": "Dansk", "native_label": "Dansk", "dir": "ltr"},
    "sv": {"label": "Swedish", "native_label": "Svenska", "dir": "ltr"},
    "tr": {"label": "Turkish", "native_label": "Türkçe", "dir": "ltr"},
    "ar": {"label": "Arabic", "native_label": "العربية", "dir": "rtl"},
    "ku": {"label": "Kurdish", "native_label": "Kurdî", "dir": "ltr"},
}


def normalize_locale(locale: str | None) -> str:
    normalized = str(locale or "").strip().lower()
    if normalized in SUPPORTED_LOCALES:
        return normalized
    return DEFAULT_LOCALE


def locale_direction(locale: str | None) -> str:
    return "rtl" if normalize_locale(locale) in RTL_LOCALES else "ltr"


def locale_choices() -> list[dict[str, str]]:
    return [
        {
            "id": locale_id,
            "label": str(LOCALE_META[locale_id]["label"]),
            "native_label": str(LOCALE_META[locale_id]["native_label"]),
            "dir": str(LOCALE_META[locale_id]["dir"]),
        }
        for locale_id in SUPPORTED_LOCALES
    ]


def localized_text(texts: dict[str, str] | None, locale: str | None) -> str:
    if not texts:
        return ""
    normalized_locale = normalize_locale(locale)
    for candidate in (normalized_locale, DEFAULT_LOCALE, "en"):
        value = texts.get(candidate, "").strip()
        if value:
            return value
    return next((value.strip() for value in texts.values() if str(value).strip()), "")


SHELL_STRINGS: dict[str, dict[str, str]] = {
    "nav.welcome": {
        "da": "Velkomst",
        "sv": "Välkomst",
        "tr": "Karşılama",
        "ar": "الترحيب",
        "ku": "Pêşwazî",
    },
    "nav.setup": {
        "da": "Opsætning",
        "sv": "Inställning",
        "tr": "Kurulum",
        "ar": "الإعداد",
        "ku": "Sazkirin",
    },
    "nav.operations": {
        "da": "Drift",
        "sv": "Drift",
        "tr": "Operasyon",
        "ar": "التشغيل",
        "ku": "Çalakî",
    },
    "nav.catalog": {
        "da": "Katalog",
        "sv": "Katalog",
        "tr": "Katalog",
        "ar": "الكتالوج",
        "ku": "Katalog",
    },
    "nav.modules": {
        "da": "Moduler",
        "sv": "Moduler",
        "tr": "Modüller",
        "ar": "الوحدات",
        "ku": "Modul",
    },
    "nav.discover": {
        "da": "Find moduler",
        "sv": "Hitta moduler",
        "tr": "Modülleri bul",
        "ar": "اكتشف الوحدات",
        "ku": "Modulan bibîne",
    },
    "nav.import": {
        "da": "Importér",
        "sv": "Importera",
        "tr": "İçe aktar",
        "ar": "استورد",
        "ku": "Bîne hundir",
    },
    "nav.node": {
        "da": "Node",
        "sv": "Nod",
        "tr": "Düğüm",
        "ar": "العقدة",
        "ku": "Node",
    },
    "toolbar.token_placeholder": {
        "da": "Operator-token",
        "sv": "Operatörstoken",
        "tr": "Operatör anahtarı",
        "ar": "رمز المشغّل",
        "ku": "Nîşana operatorê",
    },
    "toolbar.use_token": {
        "da": "Brug token",
        "sv": "Använd token",
        "tr": "Anahtarı kullan",
        "ar": "استخدم الرمز",
        "ku": "Tokenê bi kar bîne",
    },
    "toolbar.clear": {
        "da": "Ryd",
        "sv": "Rensa",
        "tr": "Temizle",
        "ar": "امسح",
        "ku": "Paqij bike",
    },
    "toolbar.refresh": {
        "da": "Opdatér",
        "sv": "Uppdatera",
        "tr": "Yenile",
        "ar": "حدّث",
        "ku": "Nû bike",
    },
    "toolbar.copy_json": {
        "da": "Kopiér JSON",
        "sv": "Kopiera JSON",
        "tr": "JSON kopyala",
        "ar": "انسخ JSON",
        "ku": "JSON kopî bike",
    },
    "toolbar.waiting": {
        "da": "Venter på token.",
        "sv": "Väntar på token.",
        "tr": "Anahtar bekleniyor.",
        "ar": "بانتظار الرمز.",
        "ku": "Li benda tokenê ye.",
    },
    "status.restart_required": {
        "da": "Genstart krævet",
        "sv": "Omstart krävs",
        "tr": "Yeniden başlatma gerekli",
        "ar": "إعادة التشغيل مطلوبة",
        "ku": "Destpêkkirina nû pêwîst e",
    },
    "status.restart_not_required": {
        "da": "Ingen genstart nu",
        "sv": "Ingen omstart nu",
        "tr": "Şimdi yeniden başlatma yok",
        "ar": "لا حاجة لإعادة التشغيل الآن",
        "ku": "Niha ne hewce ye ku ji nû ve dest pê bike",
    },
    "status.health.available": {
        "da": "tilgængelig",
        "sv": "tillgänglig",
        "tr": "hazır",
        "ar": "متاح",
        "ku": "amadeyê",
    },
    "status.health.up": {
        "da": "oppe",
        "sv": "uppe",
        "tr": "çalışıyor",
        "ar": "يعمل",
        "ku": "çalak",
    },
    "status.health.down": {
        "da": "nede",
        "sv": "nere",
        "tr": "kapalı",
        "ar": "متوقف",
        "ku": "girtî",
    },
    "status.health.not_configured": {
        "da": "ikke sat op",
        "sv": "inte konfigurerad",
        "tr": "yapılandırılmadı",
        "ar": "غير مضبوط",
        "ku": "nehatiye saz kirin",
    },
    "status.health.undeclared": {
        "da": "ikke erklæret",
        "sv": "inte deklarerad",
        "tr": "tanımsız",
        "ar": "غير مصرّح",
        "ku": "nehatiye ragihandin",
    },
    "page.welcome.title": {
        "da": "P4P Velkomst",
        "sv": "P4P Välkomst",
        "tr": "P4P Karşılama",
        "ar": "ترحيب P4P",
        "ku": "P4P Pêşwazî",
    },
    "page.setup.title": {
        "da": "P4P Opsætning",
        "sv": "P4P Inställning",
        "tr": "P4P Kurulum",
        "ar": "إعداد P4P",
        "ku": "P4P Sazkirin",
    },
    "page.operations.title": {
        "da": "P4P Drift",
        "sv": "P4P Drift",
        "tr": "P4P Operasyon",
        "ar": "تشغيل P4P",
        "ku": "P4P Çalakî",
    },
    "page.catalog.title": {
        "da": "P4P Katalog",
        "sv": "P4P Katalog",
        "tr": "P4P Katalog",
        "ar": "كتالوج P4P",
        "ku": "P4P Katalog",
    },
    "page.modules.title": {
        "da": "P4P Moduler",
        "sv": "P4P Moduler",
        "tr": "P4P Modüller",
        "ar": "وحدات P4P",
        "ku": "Modulên P4P",
    },
    "page.discover.title": {
        "da": "P4P Find moduler",
        "sv": "P4P Hitta moduler",
        "tr": "P4P Modülleri bul",
        "ar": "اكتشف وحدات P4P",
        "ku": "Modulên P4P bibîne",
    },
    "page.import.title": {
        "da": "P4P Importér moduler",
        "sv": "P4P Importera moduler",
        "tr": "P4P Modül içe aktar",
        "ar": "استيراد وحدات P4P",
        "ku": "Modulên P4P bîne hundir",
    },
    "page.node.title": {
        "da": "P4P Node",
        "sv": "P4P Nod",
        "tr": "P4P Düğüm",
        "ar": "عقدة P4P",
        "ku": "Nodeya P4P",
    },
    "setup.locale": {
        "da": "Operator-sprog",
        "sv": "Operatörsspråk",
        "tr": "Operatör dili",
        "ar": "لغة المشغّل",
        "ku": "Zimanê operatorê",
    },
    "setup.base_profile": {
        "da": "Grundform for hardware",
        "sv": "Grundform för hårdvara",
        "tr": "Temel donanım şekli",
        "ar": "شكل العتاد الأساسي",
        "ku": "Forma bingehîn a hardware",
    },
    "setup.addons": {
        "da": "Ekstra hardware på noden",
        "sv": "Extra hårdvara på noden",
        "tr": "Düğümde ekstra donanım",
        "ar": "عتاد إضافي على العقدة",
        "ku": "Hardwareya zêde li ser nodeyê",
    },
    "setup.save": {
        "da": "Gem opsætningsstate",
        "sv": "Spara inställningsstatus",
        "tr": "Kurulum durumunu kaydet",
        "ar": "احفظ حالة الإعداد",
        "ku": "Rewşa sazkirinê tomar bike",
    },
    "discover.public_catalog": {
        "da": "Offentligt modulkatalog",
        "sv": "Offentlig modulkatalog",
        "tr": "Genel modül kataloğu",
        "ar": "كتالوج الوحدات العام",
        "ku": "Kataloga gelemperî ya modulê",
    },
    "discover.shop_family": {
        "da": "Shop-familien",
        "sv": "Shop-familjen",
        "tr": "Shop ailesi",
        "ar": "عائلة shop",
        "ku": "Malbata shop",
    },
    "discover.open_public_catalog": {
        "da": "Åbn offentligt katalog",
        "sv": "Öppna offentlig katalog",
        "tr": "Genel kataloğu aç",
        "ar": "افتح الكتالوج العام",
        "ku": "Kataloga giştî veke",
    },
    "discover.open_shop_family": {
        "da": "Åbn shop-familien",
        "sv": "Öppna shop-familjen",
        "tr": "Shop ailesini aç",
        "ar": "افتح عائلة shop",
        "ku": "Malbata shop veke",
    },
    "discover.open_modules": {
        "da": "Åbn moduler",
        "sv": "Öppna moduler",
        "tr": "Modülleri aç",
        "ar": "افتح الوحدات",
        "ku": "Modulan veke",
    },
}


SHOP_FAMILY = {
    "id": "shop",
    "title": {
        "da": "Shop",
        "sv": "Shop",
        "tr": "Dükkan",
        "ar": "متجر",
        "ku": "Dikan",
    },
    "summary": {
        "da": "Moduler til små lokale butikker, takeaway, counter pickup og enkel direkte handel.",
        "sv": "Moduler för små lokala butiker, takeaway, pickup över disk och enkel direkt handel.",
        "tr": "Küçük yerel dükkânlar, takeaway, tezgahtan teslim ve basit doğrudan ticaret için modüller.",
        "ar": "وحدات للمتاجر المحلية الصغيرة، والطلبات الجاهزة، والاستلام من الكاونتر، والتعامل المباشر البسيط.",
        "ku": "Modul ji bo dikkanên biçûk ên herêmî, takeaway, stand pickup û bazirganiya rasterast a hêsan.",
    },
}


SHOP_CATEGORIES = {
    "menu_catalog": {
        "title": {
            "da": "Menu og katalog",
            "sv": "Meny och katalog",
            "tr": "Menü ve katalog",
            "ar": "القائمة والكتالوج",
            "ku": "Menu û katalog",
        },
        "summary": {
            "da": "Byg eller importér menuen og hold priser og varer på din egen node.",
            "sv": "Bygg eller importera menyn och behåll priser och artiklar på din egen nod.",
            "tr": "Menüyü oluşturun veya içe aktarın ve fiyatlarıyla ürünleri kendi düğümünüzde tutun.",
            "ar": "ابنِ القائمة أو استوردها واحتفظ بالأسعار والمواد على عقدتك الخاصة.",
            "ku": "Menuyê ava bike an derxe hundir û bihayê û tiştan li ser nodeya xwe biparêze.",
        },
        "order": 10,
    },
    "customer_surfaces": {
        "title": {
            "da": "Kundesider",
            "sv": "Kundsidor",
            "tr": "Müşteri yüzleri",
            "ar": "واجهات الزبون",
            "ku": "Rûyên xerîdar",
        },
        "summary": {
            "da": "Det kunden ser før og efter ordren: menu og status.",
            "sv": "Det kunden ser före och efter ordern: meny och status.",
            "tr": "Müşterinin siparişten önce ve sonra gördüğü şeyler: menü ve durum.",
            "ar": "ما يراه الزبون قبل الطلب وبعده: القائمة والحالة.",
            "ku": "Tiştên ku xerîdar berî û piştî fermanê dibîne: menu û status.",
        },
        "order": 20,
    },
    "counter_hardware": {
        "title": {
            "da": "Disk, køkken og hardware",
            "sv": "Disk, kök och hårdvara",
            "tr": "Tezgâh, mutfak ve donanım",
            "ar": "الكاونتر والمطبخ والعتاد",
            "ku": "Tezgah, metbex û hardware",
        },
        "summary": {
            "da": "Lokale operatorflader og hardwarehjælpere til køkken, print, pickup og alarm.",
            "sv": "Lokala operatörsytor och hårdvaruhjälpare för kök, utskrift, pickup och larm.",
            "tr": "Mutfak, baskı, teslim ve alarm için yerel operatör yüzleri ve donanım yardımcıları.",
            "ar": "واجهات المشغّل المحلية ومساعدات العتاد للمطبخ والطباعة والاستلام والتنبيه.",
            "ku": "Rûyên operatorê yên herêmî û alîkarên hardware ji bo metbex, çap, pickup û hişyarî.",
        },
        "order": 30,
    },
    "payment_adapters": {
        "title": {
            "da": "Betaling",
            "sv": "Betalning",
            "tr": "Ödeme",
            "ar": "الدفع",
            "ku": "Dravdan",
        },
        "summary": {
            "da": "Hold betaling lille i starten og tilføj kun de adapters, du faktisk vil stå på mål for.",
            "sv": "Håll betalningen liten i början och lägg bara till de adaptrar du faktiskt vill stå för.",
            "tr": "Ödemeyi başlangıçta küçük tutun ve yalnızca gerçekten desteklemek istediğiniz adaptörleri ekleyin.",
            "ar": "أبقِ الدفع صغيراً في البداية وأضف فقط الوحدات التي تريد فعلاً الوقوف خلفها.",
            "ku": "Di destpêkê de dravdan biçûk bîne û tenê wan adapteran zêde bike ku tu bixwazî bi rastî piştgirîyê bidî.",
        },
        "order": 40,
    },
    "notifications": {
        "title": {
            "da": "Notifikationer",
            "sv": "Notifieringar",
            "tr": "Bildirimler",
            "ar": "الإشعارات",
            "ku": "Agahdariyên hişyarî",
        },
        "summary": {
            "da": "Fallback-alarm når noget lokalt kræver opmærksomhed.",
            "sv": "Reservlarm när något lokalt kräver uppmärksamhet.",
            "tr": "Yerel olarak dikkat gerektiren durumlar için yedek uyarılar.",
            "ar": "تنبيهات احتياطية عندما يحتاج شيء محلي إلى انتباه.",
            "ku": "Hişyariyên paşve ji bo dema ku tiştek herêmî baldariyê dixwaze.",
        },
        "order": 50,
    },
    "trust_identity": {
        "title": {
            "da": "Tillid og identitet",
            "sv": "Tillit och identitet",
            "tr": "Güven ve kimlik",
            "ar": "الثقة والهوية",
            "ku": "Bawerî û nasname",
        },
        "summary": {
            "da": "Retninger for senere forretningsidentitet og dokumenterbar tillid.",
            "sv": "Riktningar för senare företagsidentitet och dokumenterbar tillit.",
            "tr": "Daha sonra iş kimliği ve belgelenebilir güven için yönler.",
            "ar": "اتجاهات لهوية العمل لاحقاً وثقة قابلة للمراجعة.",
            "ku": "Rêçûnên paşerojê ji bo nasnameya karsazî û baweriya ku dikare were nîşandan.",
        },
        "order": 60,
    },
    "internal_debug": {
        "title": {
            "da": "Interne testmoduler",
            "sv": "Interna testmoduler",
            "tr": "Dahili test modülleri",
            "ar": "وحدات اختبار داخلية",
            "ku": "Modulên testa hundirîn",
        },
        "summary": {
            "da": "Ting du bruger til at bryde flowet sikkert, ikke til at love en butik en live funktion.",
            "sv": "Saker du använder för att bryta flödet säkert, inte för att lova en butik en live-funktion.",
            "tr": "Akışı güvenle bozmak için kullandığınız şeylerdir; bir dükkâna canlı özellik vaadi değildir.",
            "ar": "أشياء تستخدمها لكسر التدفق بأمان، لا لتعد بها متجراً كوظيفة حية.",
            "ku": "Tiştên ku tu bi wan re rêçê bi ewle têk dibî, ne ji bo ku tu foksiyoneke zindî bi dikanek re bistînî.",
        },
        "order": 70,
    },
}


MODULE_META: dict[str, dict[str, Any]] = {
    "p4p.catalog.editor": {
        "category_id": "menu_catalog",
        "title": {"da": "Redigér menu", "en": "Edit menu"},
        "summary": {
            "da": "Redigér navne, priser, kategorier og aktive varer direkte på butikkens egen node.",
            "en": "Edit names, prices, categories, and active items directly on the shop-owned node.",
        },
        "recommended_with": ["p4p.menu.list", "p4p.customer.status", "p4p.payment.cash"],
    },
    "p4p.catalog.import.ocr": {
        "category_id": "menu_catalog",
        "title": {"da": "Importér menu fra foto", "en": "Import menu from photo"},
        "summary": {
            "da": "Lav OCR-drafts fra et papir-menukort før et menneske gemmer noget til katalogsandheden.",
            "en": "Create OCR drafts from a paper menu before a human saves anything into catalog truth.",
        },
        "recommended_with": ["p4p.catalog.editor"],
    },
    "p4p.menu.list": {
        "category_id": "customer_surfaces",
        "title": {"da": "Enkel kundemenu", "en": "Simple customer menu"},
        "summary": {
            "da": "Vis en klassisk online menu og send ordren direkte til noden.",
            "en": "Show a classic online menu and send the order directly to the node.",
        },
        "recommended_with": ["p4p.customer.status", "p4p.payment.cash", "p4p.catalog.editor"],
    },
    "p4p.menu.photo-map": {
        "category_id": "customer_surfaces",
        "title": {"da": "Klikbar menufoto-side", "en": "Clickable menu photo page"},
        "summary": {
            "da": "Vis menuen som et visuelt kort i stedet for en ren liste.",
            "en": "Show the menu as a visual map instead of a plain list.",
        },
        "recommended_with": ["p4p.customer.status", "p4p.catalog.editor"],
    },
    "p4p.customer.status": {
        "category_id": "customer_surfaces",
        "title": {"da": "Kunde-statusside", "en": "Customer status page"},
        "summary": {
            "da": "Lad kunden se om ordren er modtaget, afvist eller klar til afhentning.",
            "en": "Let the customer see whether the order is received, rejected, or ready for pickup.",
        },
        "recommended_with": ["p4p.menu.list", "p4p.payment.cash"],
    },
    "p4p.kitchen.screen": {
        "category_id": "counter_hardware",
        "title": {"da": "Køkkenkø", "en": "Kitchen queue"},
        "summary": {
            "da": "Vis indkommende ordrer og flyt dem gennem køkkenets arbejdsgang.",
            "en": "Show incoming orders and move them through the kitchen workflow.",
        },
        "recommended_with": ["p4p.menu.list", "p4p.customer.status", "p4p.payment.cash"],
    },
    "p4p.order.print": {
        "category_id": "counter_hardware",
        "title": {"da": "Print ordre", "en": "Print order"},
        "summary": {
            "da": "Send accepterede ordrer videre til en printer eller lokal POS-lignende flade.",
            "en": "Forward accepted orders to a printer or local POS-like surface.",
        },
        "recommended_with": ["p4p.kitchen.screen", "p4p.order.print.backup"],
    },
    "p4p.order.print.backup": {
        "category_id": "counter_hardware",
        "title": {"da": "Backup-print", "en": "Backup print"},
        "summary": {
            "da": "Hold en ekstra printvej klar, hvis den første printersti fejler.",
            "en": "Keep a secondary print path ready if the first printer path fails.",
        },
        "recommended_with": ["p4p.order.print", "p4p.notify.email"],
    },
    "p4p.order.alert.basic": {
        "category_id": "counter_hardware",
        "title": {"da": "Lyd eller lysalarm", "en": "Bell or light alert"},
        "summary": {
            "da": "Ring, bip eller blink lokalt, når en ny ordre kræver opmærksomhed.",
            "en": "Ring, beep, or flash locally when a new order needs attention.",
        },
        "recommended_with": ["p4p.kitchen.screen", "p4p.notify.sms"],
    },
    "p4p.pickup.board.basic": {
        "category_id": "counter_hardware",
        "title": {"da": "Afhentningsskærm", "en": "Pickup board"},
        "summary": {
            "da": "Vis accepterede eller klare ordrer på en enkel kundevendt pickup-skærm.",
            "en": "Show accepted or ready orders on a simple customer-facing pickup board.",
        },
        "recommended_with": ["p4p.customer.status", "p4p.kitchen.screen"],
    },
    "p4p.stock.basic": {
        "category_id": "counter_hardware",
        "title": {"da": "Slutlagercheck", "en": "Final stock check"},
        "summary": {
            "da": "Lav et sidste lokalt stock-check før næste ordrestep går videre.",
            "en": "Run one final local stock check before the next order step continues.",
        },
        "recommended_with": ["p4p.catalog.editor", "p4p.kitchen.screen"],
    },
    "p4p.payment.cash": {
        "category_id": "payment_adapters",
        "title": {"da": "Betal ved afhentning", "en": "Pay at pickup"},
        "summary": {
            "da": "Hold betaling enkel: bestil online, betal i butikken.",
            "en": "Keep payment simple: order online, pay in the shop.",
        },
        "recommended_with": ["p4p.menu.list", "p4p.customer.status", "p4p.kitchen.screen"],
    },
    "p4p.payment.mobilepay": {
        "category_id": "payment_adapters",
        "title": {"da": "MobilePay-adapter", "en": "MobilePay adapter"},
        "summary": {
            "da": "Senere ekstern adapter til et kendt pay-at-pickup-flow uden at gøre P4P til betalingsprocessor.",
            "en": "Later external adapter for a familiar pay-at-pickup flow without turning P4P into the payment processor.",
        },
        "recommended_with": ["p4p.payment.cash", "p4p.customer.status"],
    },
    "p4p.notify.email": {
        "category_id": "notifications",
        "title": {"da": "E-mail alarm", "en": "Email alert"},
        "summary": {
            "da": "Send fallback-besked til operatoren, hvis en ordre eller hardwaresti kræver opmærksomhed.",
            "en": "Send a fallback message to the operator if an order or hardware path needs attention.",
        },
        "recommended_with": ["p4p.order.print.backup", "p4p.order.alert.basic"],
    },
    "p4p.notify.sms": {
        "category_id": "notifications",
        "title": {"da": "SMS-alarm", "en": "SMS alert"},
        "summary": {
            "da": "Send en kort telefonbesked, når butikken vil have et hurtigere fallback end e-mail.",
            "en": "Send a short phone message when the shop wants a faster fallback than email.",
        },
        "recommended_with": ["p4p.order.alert.basic", "p4p.notify.email"],
    },
    "p4p.trust.cvr-basic": {
        "category_id": "trust_identity",
        "title": {"da": "CVR og virksomhedsidentitet", "en": "CVR and business identity"},
        "summary": {
            "da": "Peg mod senere dokumenterbar virksomhedsidentitet uden at gøre registret til autoriteten.",
            "en": "Point toward later documentable business identity without making the registry the authority.",
        },
        "recommended_with": ["p4p.payment.cash"],
    },
    "p4p.payment.godpay-mock": {
        "category_id": "internal_debug",
        "title": {"da": "Mock-betaling", "en": "Mock payment"},
        "summary": {
            "da": "Intern testbetaling til at bryde flowet sikkert før virkelige penge blandes ind.",
            "en": "Internal test payment for breaking the flow safely before real money enters the picture.",
        },
        "recommended_with": ["p4p.payment.cash"],
    },
    "p4p.payment.chaospay-mock": {
        "category_id": "internal_debug",
        "title": {"da": "Kaosbetaling", "en": "Chaos payment"},
        "summary": {
            "da": "Intern grim-test for timeouts, dobbeltcallbacks og andre betalingsfejlscenarier.",
            "en": "Internal ugly-case test for timeouts, duplicate callbacks, and other payment failure scenarios.",
        },
        "recommended_with": ["p4p.payment.cash", "p4p.payment.godpay-mock"],
    },
}


SHOP_RECOMMENDED_MODULE_IDS = [
    "p4p.catalog.editor",
    "p4p.menu.list",
    "p4p.customer.status",
    "p4p.kitchen.screen",
    "p4p.payment.cash",
    "p4p.catalog.import.ocr",
]


def shell_text(locale: str | None, key: str) -> str:
    return localized_text(SHELL_STRINGS.get(key), locale)


def github_blob_url(path: Path) -> str:
    relative = path.relative_to(P4P_ROOT).as_posix()
    return f"{GITHUB_BLOB_BASE_URL}/{relative}"


@dataclass(frozen=True)
class PublicCatalogUrls:
    pizza_site_url: str = "https://pizza4people.com/"
    protocols_site_url: str = "https://protocols4people.com/"


def _module_meta(manifest: ModuleManifest) -> dict[str, Any]:
    meta = dict(MODULE_META.get(manifest.module_id, {}))
    if not meta:
        meta["category_id"] = "internal_debug"
        meta["title"] = {"da": manifest.module_id, "en": manifest.module_id}
        meta["summary"] = {"da": manifest.description, "en": manifest.description}
        meta["recommended_with"] = list(manifest.raw.get("requires") or [])
    return meta


def _recommended_with(manifest: ModuleManifest, meta: dict[str, Any]) -> list[str]:
    combined = list(meta.get("recommended_with") or []) + [str(value) for value in manifest.raw.get("requires") or []]
    recommended: list[str] = []
    seen: set[str] = set()
    for module_id in combined:
        normalized = str(module_id).strip()
        if not normalized or normalized == manifest.module_id or normalized in seen:
            continue
        seen.add(normalized)
        recommended.append(normalized)
    return recommended


def _module_entry(manifest: ModuleManifest, *, urls: PublicCatalogUrls) -> dict[str, Any]:
    meta = _module_meta(manifest)
    category_id = str(meta["category_id"])
    manifest_path = P4P_ROOT / "modules" / manifest.module_id / "module.json"
    provider_doc_path = P4P_ROOT / "docs" / "providers" / f"{manifest.provider_id}.md"
    module_doc_path = P4P_ROOT / "docs" / "modules" / f"{manifest.module_id}.md"
    return {
        "module_id": manifest.module_id,
        "provider_id": manifest.provider_id,
        "family_id": SHOP_FAMILY["id"],
        "category_id": category_id,
        "category": SHOP_CATEGORIES[category_id],
        "lane": manifest.lane,
        "module_class": str(manifest.raw.get("module_class") or ""),
        "visibility": manifest.visibility,
        "readiness": manifest.readiness,
        "status": manifest.status,
        "title": dict(meta.get("title") or {}),
        "summary": dict(meta.get("summary") or {}),
        "function": str((manifest.raw.get("public_catalog") or {}).get("function") or manifest.description),
        "recommended_with": _recommended_with(manifest, meta),
        "proof_page_url": f"{urls.pizza_site_url.rstrip('/')}/modules/{manifest.module_id}/",
        "module_doc_url": github_blob_url(module_doc_path) if module_doc_path.is_file() else None,
        "module_manifest_url": github_blob_url(manifest_path) if manifest_path.is_file() else None,
        "provider_doc_url": github_blob_url(provider_doc_path) if provider_doc_path.is_file() else None,
        "public_family_url": f"{urls.protocols_site_url.rstrip('/')}/modules/shop/",
    }


def public_module_catalog(*, urls: PublicCatalogUrls | None = None) -> dict[str, Any]:
    effective_urls = urls or PublicCatalogUrls()
    manifests = load_reference_module_catalog()
    modules = sorted(
        (_module_entry(manifest, urls=effective_urls) for manifest in manifests.values()),
        key=lambda entry: (
            SHOP_CATEGORIES[entry["category_id"]]["order"],
            localized_text(entry["title"], DEFAULT_LOCALE).lower(),
            entry["module_id"],
        ),
    )
    providers = load_reference_provider_catalog()
    return {
        "default_locale": DEFAULT_LOCALE,
        "supported_locales": list(SUPPORTED_LOCALES),
        "rtl_locales": sorted(RTL_LOCALES),
        "locales": locale_choices(),
        "families": [
            {
                "id": SHOP_FAMILY["id"],
                "title": dict(SHOP_FAMILY["title"]),
                "summary": dict(SHOP_FAMILY["summary"]),
                "category_ids": list(SHOP_CATEGORIES),
                "recommended_module_ids": list(SHOP_RECOMMENDED_MODULE_IDS),
                "page_url": f"{effective_urls.protocols_site_url.rstrip('/')}/modules/shop/",
            }
        ],
        "categories": [
            {
                "id": category_id,
                "family_id": SHOP_FAMILY["id"],
                "title": dict(payload["title"]),
                "summary": dict(payload["summary"]),
                "order": int(payload["order"]),
            }
            for category_id, payload in SHOP_CATEGORIES.items()
        ],
        "modules": modules,
        "providers": [
            {
                "provider_id": provider.provider_id,
                "name": provider.name,
                "description": provider.description,
                "website": provider.website,
            }
            for provider in providers.values()
        ],
    }


def localized_module_catalog(locale: str | None, *, urls: PublicCatalogUrls | None = None) -> dict[str, Any]:
    normalized_locale = normalize_locale(locale)
    catalog = public_module_catalog(urls=urls)
    category_lookup = {entry["id"]: entry for entry in catalog["categories"]}
    modules: list[dict[str, Any]] = []
    for entry in catalog["modules"]:
        category = category_lookup[entry["category_id"]]
        modules.append(
            {
                "module_id": entry["module_id"],
                "provider_id": entry["provider_id"],
                "family_id": entry["family_id"],
                "family_title": localized_text(SHOP_FAMILY["title"], normalized_locale),
                "category_id": entry["category_id"],
                "category_title": localized_text(category["title"], normalized_locale),
                "category_summary": localized_text(category["summary"], normalized_locale),
                "lane": entry["lane"],
                "module_class": entry["module_class"],
                "visibility": entry["visibility"],
                "readiness": entry["readiness"],
                "status": entry["status"],
                "title": localized_text(entry["title"], normalized_locale),
                "summary": localized_text(entry["summary"], normalized_locale),
                "function": entry["function"],
                "recommended_with": list(entry["recommended_with"]),
                "proof_page_url": entry["proof_page_url"],
                "module_doc_url": entry["module_doc_url"],
                "module_manifest_url": entry["module_manifest_url"],
                "provider_doc_url": entry["provider_doc_url"],
                "public_family_url": entry["public_family_url"],
            }
        )
    return {
        "default_locale": catalog["default_locale"],
        "current_locale": normalized_locale,
        "is_rtl": normalized_locale in RTL_LOCALES,
        "locales": catalog["locales"],
        "family": {
            "id": SHOP_FAMILY["id"],
            "title": localized_text(SHOP_FAMILY["title"], normalized_locale),
            "summary": localized_text(SHOP_FAMILY["summary"], normalized_locale),
            "page_url": catalog["families"][0]["page_url"],
            "recommended_module_ids": list(SHOP_RECOMMENDED_MODULE_IDS),
        },
        "categories": [
            {
                "id": entry["id"],
                "title": localized_text(entry["title"], normalized_locale),
                "summary": localized_text(entry["summary"], normalized_locale),
                "order": entry["order"],
            }
            for entry in catalog["categories"]
        ],
        "modules": modules,
    }


def operator_locale_payload(locale: str | None) -> dict[str, Any]:
    normalized_locale = normalize_locale(locale)
    return {
        "current": normalized_locale,
        "default": DEFAULT_LOCALE,
        "is_rtl": normalized_locale in RTL_LOCALES,
        "choices": locale_choices(),
    }


__all__ = [
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "RTL_LOCALES",
    "PublicCatalogUrls",
    "locale_choices",
    "locale_direction",
    "localized_module_catalog",
    "localized_text",
    "normalize_locale",
    "operator_locale_payload",
    "public_module_catalog",
    "shell_text",
]
