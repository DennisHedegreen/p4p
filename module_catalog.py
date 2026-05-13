from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from p4p_core import ModuleManifest, load_reference_module_catalog, load_reference_provider_catalog


DEFAULT_LOCALE = "da"
SUPPORTED_LOCALES = ("da", "sv", "tr", "ar", "ku", "en")
RTL_LOCALES = {"ar"}

P4P_ROOT = Path(__file__).resolve().parent
GITHUB_BLOB_BASE_URL = "https://github.com/DennisHedegreen/p4p/blob/main"
I18N_ROOT = P4P_ROOT / "data" / "i18n"
I18N_CORE_ROOT = I18N_ROOT / "core"


LOCALE_META = {
    "da": {"label": "Dansk", "native_label": "Dansk", "dir": "ltr"},
    "sv": {"label": "Swedish", "native_label": "Svenska", "dir": "ltr"},
    "tr": {"label": "Turkish", "native_label": "Türkçe", "dir": "ltr"},
    "ar": {"label": "Arabic", "native_label": "العربية", "dir": "rtl"},
    "ku": {"label": "Kurdish", "native_label": "Kurdî", "dir": "ltr"},
    "en": {"label": "English", "native_label": "English", "dir": "ltr"},
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
    for candidate in (normalized_locale, "en", DEFAULT_LOCALE):
        value = texts.get(candidate, "").strip()
        if value:
            return value
    return next((value.strip() for value in texts.values() if str(value).strip()), "")


def localized_field_map(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        normalized: dict[str, str] = {}
        for key, raw_text in value.items():
            locale_id = str(key or "").strip().lower()
            text = str(raw_text or "").strip()
            if locale_id and text:
                normalized[locale_id] = text
        return normalized or None
    if isinstance(value, str):
        text = value.strip()
        if text:
            return {"en": text}
    return None


def localized_field_text(value: Any, locale: str | None, *, default: str = "") -> str:
    localized_map = localized_field_map(value)
    if localized_map:
        return localized_text(localized_map, locale) or default
    return default


SHELL_STRINGS: dict[str, dict[str, str]] = {
    "nav.welcome": {
        "da": "Velkomst",
        "sv": "Välkomst",
        "tr": "Karşılama",
        "ar": "الترحيب",
        "ku": "Pêşwazî",
        "en": "Welcome",
    },
    "nav.setup": {
        "da": "Opsætning",
        "sv": "Inställning",
        "tr": "Kurulum",
        "ar": "الإعداد",
        "ku": "Sazkirin",
        "en": "Setup",
    },
    "nav.operations": {
        "da": "Drift",
        "sv": "Drift",
        "tr": "Operasyon",
        "ar": "التشغيل",
        "ku": "Çalakî",
        "en": "Operations",
    },
    "nav.catalog": {
        "da": "Katalog",
        "sv": "Katalog",
        "tr": "Katalog",
        "ar": "الكتالوج",
        "ku": "Katalog",
        "en": "Catalog",
    },
    "nav.modules": {
        "da": "Moduler",
        "sv": "Moduler",
        "tr": "Modüller",
        "ar": "الوحدات",
        "ku": "Modul",
        "en": "Modules",
    },
    "nav.discover": {
        "da": "Find moduler",
        "sv": "Hitta moduler",
        "tr": "Modülleri bul",
        "ar": "اكتشف الوحدات",
        "ku": "Modulan bibîne",
        "en": "Discover",
    },
    "nav.import": {
        "da": "Importér",
        "sv": "Importera",
        "tr": "İçe aktar",
        "ar": "استورد",
        "ku": "Bîne hundir",
        "en": "Import",
    },
    "nav.node": {
        "da": "Node",
        "sv": "Nod",
        "tr": "Düğüm",
        "ar": "العقدة",
        "ku": "Node",
        "en": "Node",
    },
    "toolbar.token_placeholder": {
        "da": "Operator-token",
        "sv": "Operatörstoken",
        "tr": "Operatör anahtarı",
        "ar": "رمز المشغّل",
        "ku": "Nîşana operatorê",
        "en": "Operator token",
    },
    "toolbar.use_token": {
        "da": "Brug token",
        "sv": "Använd token",
        "tr": "Anahtarı kullan",
        "ar": "استخدم الرمز",
        "ku": "Tokenê bi kar bîne",
        "en": "Use token",
    },
    "toolbar.clear": {
        "da": "Ryd",
        "sv": "Rensa",
        "tr": "Temizle",
        "ar": "امسح",
        "ku": "Paqij bike",
        "en": "Clear",
    },
    "toolbar.refresh": {
        "da": "Opdatér",
        "sv": "Uppdatera",
        "tr": "Yenile",
        "ar": "حدّث",
        "ku": "Nû bike",
        "en": "Refresh",
    },
    "toolbar.copy_json": {
        "da": "Kopiér JSON",
        "sv": "Kopiera JSON",
        "tr": "JSON kopyala",
        "ar": "انسخ JSON",
        "ku": "JSON kopî bike",
        "en": "Copy JSON",
    },
    "toolbar.waiting": {
        "da": "Venter på token.",
        "sv": "Väntar på token.",
        "tr": "Anahtar bekleniyor.",
        "ar": "بانتظار الرمز.",
        "ku": "Li benda tokenê ye.",
        "en": "Waiting for token.",
    },
    "status.restart_required": {
        "da": "Genstart krævet",
        "sv": "Omstart krävs",
        "tr": "Yeniden başlatma gerekli",
        "ar": "إعادة التشغيل مطلوبة",
        "ku": "Destpêkkirina nû pêwîst e",
        "en": "Restart required",
    },
    "status.restart_not_required": {
        "da": "Ingen genstart nu",
        "sv": "Ingen omstart nu",
        "tr": "Şimdi yeniden başlatma yok",
        "ar": "لا حاجة لإعادة التشغيل الآن",
        "ku": "Niha ne hewce ye ku ji nû ve dest pê bike",
        "en": "No restart now",
    },
    "status.health.available": {
        "da": "tilgængelig",
        "sv": "tillgänglig",
        "tr": "hazır",
        "ar": "متاح",
        "ku": "amadeyê",
        "en": "available",
    },
    "status.health.up": {
        "da": "oppe",
        "sv": "uppe",
        "tr": "çalışıyor",
        "ar": "يعمل",
        "ku": "çalak",
        "en": "up",
    },
    "status.health.down": {
        "da": "nede",
        "sv": "nere",
        "tr": "kapalı",
        "ar": "متوقف",
        "ku": "girtî",
        "en": "down",
    },
    "status.health.not_configured": {
        "da": "ikke sat op",
        "sv": "inte konfigurerad",
        "tr": "yapılandırılmadı",
        "ar": "غير مضبوط",
        "ku": "nehatiye saz kirin",
        "en": "not configured",
    },
    "status.health.undeclared": {
        "da": "ikke erklæret",
        "sv": "inte deklarerad",
        "tr": "tanımsız",
        "ar": "غير مصرّح",
        "ku": "nehatiye ragihandin",
        "en": "undeclared",
    },
    "page.welcome.title": {
        "da": "P4P Velkomst",
        "sv": "P4P Välkomst",
        "tr": "P4P Karşılama",
        "ar": "ترحيب P4P",
        "ku": "P4P Pêşwazî",
        "en": "P4P Welcome",
    },
    "page.setup.title": {
        "da": "P4P Opsætning",
        "sv": "P4P Inställning",
        "tr": "P4P Kurulum",
        "ar": "إعداد P4P",
        "ku": "P4P Sazkirin",
        "en": "P4P Setup",
    },
    "page.operations.title": {
        "da": "P4P Drift",
        "sv": "P4P Drift",
        "tr": "P4P Operasyon",
        "ar": "تشغيل P4P",
        "ku": "P4P Çalakî",
        "en": "P4P Operations",
    },
    "page.catalog.title": {
        "da": "P4P Katalog",
        "sv": "P4P Katalog",
        "tr": "P4P Katalog",
        "ar": "كتالوج P4P",
        "ku": "P4P Katalog",
        "en": "P4P Catalog",
    },
    "page.modules.title": {
        "da": "P4P Moduler",
        "sv": "P4P Moduler",
        "tr": "P4P Modüller",
        "ar": "وحدات P4P",
        "ku": "Modulên P4P",
        "en": "P4P Modules",
    },
    "page.discover.title": {
        "da": "P4P Find moduler",
        "sv": "P4P Hitta moduler",
        "tr": "P4P Modülleri bul",
        "ar": "اكتشف وحدات P4P",
        "ku": "Modulên P4P bibîne",
        "en": "P4P Discover",
    },
    "page.import.title": {
        "da": "P4P Importér moduler",
        "sv": "P4P Importera moduler",
        "tr": "P4P Modül içe aktar",
        "ar": "استيراد وحدات P4P",
        "ku": "Modulên P4P bîne hundir",
        "en": "P4P Import Modules",
    },
    "page.node.title": {
        "da": "P4P Node",
        "sv": "P4P Nod",
        "tr": "P4P Düğüm",
        "ar": "عقدة P4P",
        "ku": "Nodeya P4P",
        "en": "P4P Node",
    },
    "setup.locale": {
        "da": "Operator-sprog",
        "sv": "Operatörsspråk",
        "tr": "Operatör dili",
        "ar": "لغة المشغّل",
        "ku": "Zimanê operatorê",
        "en": "Operator language",
    },
    "setup.base_profile": {
        "da": "Grundform for hardware",
        "sv": "Grundform för hårdvara",
        "tr": "Temel donanım şekli",
        "ar": "شكل العتاد الأساسي",
        "ku": "Forma bingehîn a hardware",
        "en": "Base hardware shape",
    },
    "setup.addons": {
        "da": "Ekstra hardware på noden",
        "sv": "Extra hårdvara på noden",
        "tr": "Düğümde ekstra donanım",
        "ar": "عتاد إضافي على العقدة",
        "ku": "Hardwareya zêde li ser nodeyê",
        "en": "Extra hardware on this node",
    },
    "setup.save": {
        "da": "Gem opsætningsstate",
        "sv": "Spara inställningsstatus",
        "tr": "Kurulum durumunu kaydet",
        "ar": "احفظ حالة الإعداد",
        "ku": "Rewşa sazkirinê tomar bike",
        "en": "Save setup state",
    },
    "discover.public_catalog": {
        "da": "Offentligt modulkatalog",
        "sv": "Offentlig modulkatalog",
        "tr": "Genel modül kataloğu",
        "ar": "كتالوج الوحدات العام",
        "ku": "Kataloga gelemperî ya modulê",
        "en": "Public module catalog",
    },
    "discover.shop_family": {
        "da": "Shop-familien",
        "sv": "Shop-familjen",
        "tr": "Shop ailesi",
        "ar": "عائلة shop",
        "ku": "Malbata shop",
        "en": "Shop family",
    },
    "discover.open_public_catalog": {
        "da": "Åbn offentligt katalog",
        "sv": "Öppna offentlig katalog",
        "tr": "Genel kataloğu aç",
        "ar": "افتح الكتالوج العام",
        "ku": "Kataloga giştî veke",
        "en": "Open public catalog",
    },
    "discover.open_shop_family": {
        "da": "Åbn shop-familien",
        "sv": "Öppna shop-familjen",
        "tr": "Shop ailesini aç",
        "ar": "افتح عائلة shop",
        "ku": "Malbata shop veke",
        "en": "Open shop family",
    },
    "discover.open_modules": {
        "da": "Åbn moduler",
        "sv": "Öppna moduler",
        "tr": "Modülleri aç",
        "ar": "افتح الوحدات",
        "ku": "Modulan veke",
        "en": "Open modules",
    },
    "common.node": {
        "da": "Node",
        "sv": "Nod",
        "tr": "Düğüm",
        "en": "Node",
    },
    "common.mode": {
        "da": "Mode",
        "sv": "Läge",
        "tr": "Mod",
        "en": "Mode",
    },
    "common.payment": {
        "da": "Betaling",
        "sv": "Betalning",
        "tr": "Ödeme",
        "en": "Payment",
    },
    "common.next": {
        "da": "Næste",
        "sv": "Nästa",
        "tr": "Sonraki",
        "en": "Next",
    },
    "common.orders": {
        "da": "Ordrer",
        "sv": "Order",
        "tr": "Siparişler",
        "en": "Orders",
    },
    "common.restart": {
        "da": "Genstart",
        "sv": "Omstart",
        "tr": "Yeniden başlatma",
        "en": "Restart",
    },
    "common.registry": {
        "da": "Register",
        "sv": "Register",
        "tr": "Kayıt",
        "en": "Registry",
    },
    "common.catalog_items": {
        "da": "Katalogvarer",
        "sv": "Katalogobjekt",
        "tr": "Katalog öğeleri",
        "en": "Catalog items",
    },
    "common.imported": {
        "da": "Importeret",
        "sv": "Importerat",
        "tr": "İçe aktarılan",
        "en": "Imported",
    },
    "common.imported_manifests": {
        "da": "Importerede manifests",
        "sv": "Importerade manifest",
        "tr": "İçe aktarılan manifestler",
        "en": "Imported manifests",
    },
    "common.running_now": {
        "da": "Kører nu",
        "sv": "Kör nu",
        "tr": "Şimdi çalışıyor",
        "en": "Running now",
    },
    "common.available": {
        "da": "Tilgængelig",
        "sv": "Tillgänglig",
        "tr": "Kullanılabilir",
        "en": "Available",
    },
    "common.family": {
        "da": "Familie",
        "sv": "Familj",
        "tr": "Aile",
        "en": "Family",
    },
    "common.status": {
        "da": "Status",
        "sv": "Status",
        "tr": "Durum",
        "en": "Status",
    },
    "common.checklist": {
        "da": "Checkliste",
        "sv": "Checklista",
        "tr": "Kontrol listesi",
        "en": "Checklist",
    },
    "common.menu_items": {
        "da": "Menuvarer",
        "sv": "Menyobjekt",
        "tr": "Menü öğeleri",
        "en": "Menu items",
    },
    "common.this_node": {
        "da": "Denne node",
        "sv": "Den här noden",
        "tr": "Bu düğüm",
        "en": "This node",
    },
    "common.current_reading": {
        "da": "Nuværende læsning",
        "sv": "Nuvarande läsning",
        "tr": "Geçerli okuma",
        "en": "Current reading",
    },
    "common.start_here": {
        "da": "Start her",
        "sv": "Börja här",
        "tr": "Buradan başla",
        "en": "Start here",
    },
    "common.next_rooms": {
        "da": "Næste rum",
        "sv": "Nästa rum",
        "tr": "Sonraki odalar",
        "en": "Next rooms",
    },
    "common.current_modules": {
        "da": "Nuværende moduler",
        "sv": "Nuvarande moduler",
        "tr": "Geçerli modüller",
        "en": "Current modules",
    },
    "common.public_reading": {
        "da": "Offentlig læsning",
        "sv": "Offentlig läsning",
        "tr": "Genel okuma",
        "en": "Public reading",
    },
    "common.quick_links": {
        "da": "Hurtiglinks",
        "sv": "Snabblänkar",
        "tr": "Hızlı bağlantılar",
        "en": "Quick links",
    },
    "common.use_these_rooms": {
        "da": "Brug disse rum",
        "sv": "Använd de här rummen",
        "tr": "Bu odaları kullan",
        "en": "Use these rooms",
    },
    "common.runtime": {
        "da": "Runtime",
        "sv": "Runtime",
        "tr": "Çalışma zamanı",
        "en": "Runtime",
    },
    "common.setup_truth": {
        "da": "Opsætningssandhed",
        "sv": "Inställningssanning",
        "tr": "Kurulum gerçeği",
        "en": "Setup truth",
    },
    "common.debug_json": {
        "da": "Debug JSON",
        "sv": "Debug JSON",
        "tr": "Hata ayıklama JSON",
        "en": "Debug JSON",
    },
    "common.open": {
        "da": "Åbn",
        "sv": "Öppna",
        "tr": "Aç",
        "en": "Open",
    },
    "common.yes": {
        "da": "Ja",
        "sv": "Ja",
        "tr": "Evet",
        "en": "Yes",
    },
    "common.no": {
        "da": "Nej",
        "sv": "Nej",
        "tr": "Hayır",
        "en": "No",
    },
    "common.required": {
        "da": "Krævet",
        "sv": "Krävs",
        "tr": "Gerekli",
        "en": "Required",
    },
    "common.accepts_orders": {
        "da": "Accepterer ordrer",
        "sv": "Tar emot order",
        "tr": "Sipariş kabul ediyor",
        "en": "Accepts orders",
    },
    "common.active_payment": {
        "da": "Aktiv betaling",
        "sv": "Aktiv betalning",
        "tr": "Etkin ödeme",
        "en": "Active payment",
    },
    "common.public_modules": {
        "da": "Offentlige moduler",
        "sv": "Offentliga moduler",
        "en": "Public modules",
    },
    "common.desired_after_restart": {
        "da": "Ønsket efter genstart",
        "sv": "Önskat efter omstart",
        "tr": "Yeniden başlatmadan sonra istenen",
        "en": "Desired after restart",
    },
    "common.checked": {
        "da": "Tjekket",
        "sv": "Kontrollerad",
        "tr": "Kontrol edildi",
        "en": "Checked",
    },
    "common.open_setup": {
        "da": "Åbn opsætning",
        "sv": "Öppna inställning",
        "tr": "Kurulumu aç",
        "en": "Open setup",
    },
    "common.open_catalog": {
        "da": "Åbn katalog",
        "sv": "Öppna katalog",
        "tr": "Kataloğu aç",
        "en": "Open catalog",
    },
    "common.open_modules": {
        "da": "Åbn moduler",
        "sv": "Öppna moduler",
        "tr": "Modülleri aç",
        "en": "Open modules",
    },
    "common.open_operations": {
        "da": "Åbn drift",
        "sv": "Öppna drift",
        "tr": "Operasyonu aç",
        "en": "Open operations",
    },
    "common.open_discover": {
        "da": "Åbn find moduler",
        "sv": "Öppna hitta moduler",
        "tr": "Modülleri bul odasını aç",
        "en": "Open discover",
    },
    "common.open_import": {
        "da": "Åbn import",
        "sv": "Öppna import",
        "tr": "İçe aktarma odasını aç",
        "en": "Open import",
    },
    "common.read_public_catalog": {
        "da": "Læs offentligt katalog",
        "sv": "Läs offentlig katalog",
        "tr": "Genel kataloğu oku",
        "en": "Read public catalog",
    },
    "common.open_public_catalog": {
        "da": "Åbn offentligt katalog",
        "sv": "Öppna offentlig katalog",
        "tr": "Genel kataloğu aç",
        "en": "Open public catalog",
    },
    "common.open_public_page": {
        "da": "Åbn offentlig side",
        "sv": "Öppna offentlig sida",
        "tr": "Genel sayfayı aç",
        "en": "Open public page",
    },
    "common.open_module": {
        "da": "Åbn modul",
        "sv": "Öppna modul",
        "tr": "Modülü aç",
        "en": "Open module",
    },
    "common.import_manifest": {
        "da": "Importér manifest",
        "sv": "Importera manifest",
        "tr": "Manifesti içe aktar",
        "en": "Import manifest",
    },
    "common.remove": {
        "da": "Fjern",
        "sv": "Ta bort",
        "tr": "Kaldır",
        "en": "Remove",
    },
    "common.add_item": {
        "da": "Tilføj vare",
        "sv": "Lägg till objekt",
        "tr": "Öğe ekle",
        "en": "Add item",
    },
    "common.save_catalog": {
        "da": "Gem katalog",
        "sv": "Spara katalog",
        "tr": "Kataloğu kaydet",
        "en": "Save catalog",
    },
    "common.save_setup_state": {
        "da": "Gem opsætningsstate",
        "sv": "Spara inställningsstatus",
        "tr": "Kurulum durumunu kaydet",
        "en": "Save setup state",
    },
    "common.no_orders": {
        "da": "Ingen ordrer",
        "sv": "Inga order",
        "en": "No orders",
    },
    "common.no_catalog_items": {
        "da": "Ingen katalogvarer",
        "sv": "Inga katalogobjekt",
        "tr": "Katalog öğesi yok",
        "en": "No catalog items",
    },
    "common.no_imported_manifests": {
        "da": "Ingen importerede manifests på denne node endnu.",
        "sv": "Inga importerade manifest på den här noden ännu.",
        "tr": "Bu düğümde henüz içe aktarılmış manifest yok.",
        "en": "No imported manifests on this node yet.",
    },
    "common.no_summary_in_manifest": {
        "da": "Ingen opsummering i manifestet.",
        "sv": "Ingen sammanfattning i manifestet.",
        "tr": "Manifestte özet yok.",
        "en": "No summary in manifest.",
    },
    "common.none": {
        "da": "ingen",
        "sv": "ingen",
        "tr": "yok",
        "en": "none",
    },
    "common.loading": {
        "da": "Indlæser.",
        "sv": "Laddar.",
        "tr": "Yükleniyor.",
        "en": "Loading.",
    },
    "common.updated": {
        "da": "Opdateret.",
        "sv": "Uppdaterad.",
        "tr": "Güncellendi.",
        "en": "Updated.",
    },
    "common.waiting_for_token": {
        "da": "Venter på token.",
        "sv": "Väntar på token.",
        "tr": "Anahtar bekleniyor.",
        "en": "Waiting for token.",
    },
    "common.token_cleared": {
        "da": "Token ryddet.",
        "sv": "Token rensad.",
        "tr": "Anahtar temizlendi.",
        "en": "Token cleared.",
    },
    "common.copied_json": {
        "da": "JSON kopieret.",
        "sv": "JSON kopierad.",
        "tr": "JSON kopyalandı.",
        "en": "Copied JSON.",
    },
    "common.search_module_placeholder": {
        "da": "Søg modul-id, provider, lane",
        "sv": "Sök modul-id, provider, lane",
        "tr": "Modül kimliği, sağlayıcı, lane ara",
        "en": "Search module id, provider, lane",
    },
    "common.all_lanes": {
        "da": "Alle lanes",
        "sv": "Alla lanes",
        "tr": "Tüm lane'ler",
        "en": "All lanes",
    },
    "common.all_health": {
        "da": "Al health",
        "sv": "All hälsa",
        "tr": "Tüm sağlık durumları",
        "en": "All health",
    },
    "common.active_now": {
        "da": "aktiv nu",
        "sv": "aktiv nu",
        "tr": "şimdi etkin",
        "en": "active now",
    },
    "common.remove_after_restart": {
        "da": "fjernes efter genstart",
        "sv": "tas bort efter omstart",
        "tr": "yeniden başlatmadan sonra kaldır",
        "en": "remove after restart",
    },
    "common.enable_after_restart": {
        "da": "aktiver efter genstart",
        "sv": "aktivera efter omstart",
        "tr": "yeniden başlatmadan sonra etkinleştir",
        "en": "enable after restart",
    },
    "common.imported_label": {
        "da": "importeret",
        "sv": "importerat",
        "tr": "içe aktarıldı",
        "en": "imported",
    },
    "common.not_runnable_yet": {
        "da": "ikke kørbar endnu",
        "sv": "inte körbar ännu",
        "tr": "henüz çalıştırılamaz",
        "en": "not runnable yet",
    },
    "common.metadata_only": {
        "da": "kun metadata",
        "sv": "bara metadata",
        "tr": "yalnızca metadata",
        "en": "metadata only",
    },
    "common.use_import_room": {
        "da": "brug importrummet",
        "sv": "använd importrummet",
        "tr": "içe aktarma odasını kullan",
        "en": "use Import room",
    },
    "common.no_provider": {
        "da": "ingen provider",
        "sv": "ingen provider",
        "tr": "sağlayıcı yok",
        "en": "no provider",
    },
    "common.no_version": {
        "da": "ingen version",
        "sv": "ingen version",
        "tr": "sürüm yok",
        "en": "no version",
    },
    "common.local_upload": {
        "da": "lokal upload",
        "sv": "lokal uppladdning",
        "tr": "yerel yükleme",
        "en": "local upload",
    },
    "common.configured": {
        "da": "konfigureret",
        "sv": "konfigurerad",
        "tr": "yapılandırılmış",
        "en": "configured",
    },
    "common.missing": {
        "da": "mangler",
        "sv": "saknas",
        "tr": "eksik",
        "en": "missing",
    },
    "common.executable": {
        "da": "kørbar",
        "sv": "körbar",
        "tr": "çalıştırılabilir",
        "en": "executable",
    },
    "common.not_executable": {
        "da": "ikke kørbar",
        "sv": "inte körbar",
        "tr": "çalıştırılamaz",
        "en": "not executable",
    },
    "common.not_confirmed_yet": {
        "da": "Ikke bekræftet endnu",
        "sv": "Inte bekräftad ännu",
        "tr": "Henüz doğrulanmadı",
        "en": "Not confirmed yet",
    },
    "common.local_manifest_file": {
        "da": "Lokalt manifest-fil",
        "sv": "Lokal manifestfil",
        "tr": "Yerel manifest dosyası",
        "en": "Local manifest file",
    },
    "common.choose_local_manifest_first": {
        "da": "Vælg først en lokal module.json.",
        "sv": "Välj först en lokal module.json.",
        "tr": "Önce yerel bir module.json seçin.",
        "en": "Choose a local module.json first.",
    },
    "common.importing": {
        "da": "Importerer.",
        "sv": "Importerar.",
        "tr": "İçe aktarılıyor.",
        "en": "Importing.",
    },
    "common.imported_action": {
        "da": "Importerede",
        "sv": "Importerade",
        "tr": "İçe aktarıldı",
        "en": "Imported",
    },
    "common.replaced_action": {
        "da": "Erstattede",
        "sv": "Ersatte",
        "tr": "Değiştirildi",
        "en": "Replaced",
    },
    "welcome.this_node_body": {
        "da": "Lokal menu, lokalt ordreflow og lokale operatorflader.",
        "sv": "Lokal meny, lokalt orderflöde och lokala operatörsytor.",
        "tr": "Yerel menü, yerel sipariş akışı ve yerel operatör yüzleri.",
        "en": "Local menu, local order flow, local operator surfaces.",
    },
    "welcome.menu_work_title": {
        "da": "Menuarbejde ligger i Katalog",
        "sv": "Menyarbete ligger i Katalog",
        "tr": "Menü çalışması Katalog'da",
        "en": "Menu work lives in Catalog",
    },
    "welcome.menu_work_body": {
        "da": "Varer, priser, billeder og menuimport.",
        "sv": "Objekt, priser, bilder och menyimport.",
        "tr": "Öğeler, fiyatlar, görseller ve menü içe aktarma.",
        "en": "Items, prices, images, and menu import.",
    },
    "welcome.daily_flow_title": {
        "da": "Dagligt flow ligger i Drift",
        "sv": "Dagligt flöde ligger i Drift",
        "tr": "Günlük akış Operasyon'da",
        "en": "Daily flow lives in Operations",
    },
    "welcome.daily_flow_body": {
        "da": "Indgående ordrer, køkkenarbejde og runtime-state.",
        "sv": "Inkommande order, köksarbete och runtime-status.",
        "tr": "Gelen siparişler, mutfak işi ve çalışma zamanı durumu.",
        "en": "Incoming orders, kitchen work, and runtime state.",
    },
    "welcome.system_shape_title": {
        "da": "Systemform ligger i Moduler",
        "sv": "Systemformen ligger i Moduler",
        "tr": "Sistem şekli Modüller'de",
        "en": "System shape lives in Modules",
    },
    "welcome.system_shape_body": {
        "da": "Kører nu, ønsket efter genstart og eksplicitte modulændringer.",
        "sv": "Kör nu, önskat efter omstart och explicita moduländringar.",
        "tr": "Şimdi çalışan, yeniden başlatmadan sonra istenen ve açık modül değişiklikleri.",
        "en": "Running now, desired after restart, and explicit module changes.",
    },
    "welcome.start_here_body": {
        "da": "Følg det næste rigtige skridt. Resten kan vente.",
        "sv": "Följ nästa riktiga steg. Resten kan vänta.",
        "tr": "Bir sonraki gerçek adıma uyun. Geri kalanı bekleyebilir.",
        "en": "Follow the next real step. The rest can wait.",
    },
    "welcome.restart_detail": {
        "da": "Det ønskede modulset er forskelligt fra den kørende node. Genstart efter opsætning eller backoffice-ændringer.",
        "sv": "Det önskade modulsetet skiljer sig från den körande noden. Starta om efter inställning eller backoffice-ändringar.",
        "tr": "İstenen modül seti çalışan düğümden farklı. Kurulum veya arka ofis değişikliklerinden sonra yeniden başlatın.",
        "en": "The desired module set differs from the running node. Restart after finishing setup or backoffice changes.",
    },
    "welcome.action_restart_node": {
        "da": "Genstart node",
        "sv": "Starta om noden",
        "tr": "Düğümü yeniden başlat",
        "en": "Restart node",
    },
    "welcome.action_restart_node_detail": {
        "da": "Det ønskede modulset er gemt, men runtime kører stadig på det gamle sæt.",
        "sv": "Det önskade modulsetet är sparat, men runtimen kör fortfarande på den gamla uppsättningen.",
        "tr": "İstenen modül seti kaydedildi, ancak çalışma zamanı hâlâ eski set üzerinde çalışıyor.",
        "en": "The desired module set is saved, but the runtime is still on the old set.",
    },
    "welcome.action_choose_payment": {
        "da": "Vælg betalingsbane",
        "sv": "Välj betalningsbana",
        "tr": "Ödeme hattını seç",
        "en": "Choose payment lane",
    },
    "welcome.action_choose_payment_detail": {
        "da": "En pickup-betalingsbane bør være aktiv før test.",
        "sv": "En pickup-betalningsbana bör vara aktiv före test.",
        "tr": "Testten önce bir pickup ödeme hattı etkin olmalıdır.",
        "en": "A pickup payment lane should be active before testing.",
    },
    "welcome.add_first_menu": {
        "da": "Læg første menu ind",
        "sv": "Lägg in första menyn",
        "tr": "İlk menüyü ekle",
        "en": "Add first menu",
    },
    "welcome.this_node_no_menu": {
        "da": "Denne node har ikke nogen menu endnu.",
        "sv": "Den här noden har ingen meny ännu.",
        "tr": "Bu düğümde henüz menü yok.",
        "en": "This node does not have a menu yet.",
    },
    "welcome.confirm_hardware_profile": {
        "da": "Bekræft hardwareprofil",
        "sv": "Bekräfta hårdvaruprofil",
        "tr": "Donanım profilini doğrula",
        "en": "Confirm hardware profile",
    },
    "welcome.confirm_hardware_profile_detail": {
        "da": "Registrér hvilken hardwareform denne node faktisk skal køre på før pilotbrug.",
        "sv": "Registrera vilken hårdvaruform den här noden faktiskt ska köra på före pilotbruk.",
        "tr": "Pilot kullanımdan önce bu düğümün gerçekten hangi donanım şeklinde çalışacağını kaydedin.",
        "en": "Record which hardware shape this node is meant to run on before pilot use.",
    },
    "welcome.review_menu": {
        "da": "Gennemgå menuen",
        "sv": "Granska menyn",
        "tr": "Menüyü gözden geçir",
        "en": "Review the menu",
    },
    "welcome.review_menu_detail": {
        "da": "Menuen findes, men opsætningen er ikke markeret som gennemgået endnu.",
        "sv": "Menyn finns, men inställningen har inte markerat den som granskad ännu.",
        "tr": "Menü mevcut, ancak kurulum onu henüz gözden geçirilmiş olarak işaretlemedi.",
        "en": "The menu exists, but setup has not marked it as reviewed yet.",
    },
    "welcome.run_local_tests": {
        "da": "Kør lokale tests",
        "sv": "Kör lokala tester",
        "tr": "Yerel testleri çalıştır",
        "en": "Run local tests",
    },
    "welcome.run_local_tests_detail": {
        "da": "Gør de lokale checks færdige før du stoler på noden i en rigtig butik.",
        "sv": "Slutför de lokala kontrollerna innan du litar på noden i en riktig butik.",
        "tr": "Gerçek bir dükkânda bu düğüme güvenmeden önce yerel kontrolleri tamamlayın.",
        "en": "Finish the local checks before trusting the node in a real shop.",
    },
    "welcome.set_menu_only": {
        "da": "Sæt menu_only",
        "sv": "Sätt menu_only",
        "tr": "menu_only ayarla",
        "en": "Set menu_only",
    },
    "welcome.set_menu_only_detail": {
        "da": "Hold noden i menu_only mens du gør opsætningen færdig.",
        "sv": "Behåll noden i menu_only medan du gör klart inställningen.",
        "tr": "Kurulumu tamamlarken düğümü menu_only modunda tutun.",
        "en": "Keep the node in menu_only while you finish setup.",
    },
    "welcome.action_open_operations": {
        "da": "Åbn drift",
        "sv": "Öppna drift",
        "tr": "Operasyonu aç",
        "en": "Open operations",
    },
    "welcome.action_open_operations_detail_ready": {
        "da": "Noden er nu menu_only-klar. Brug drift til daglig test.",
        "sv": "Noden är nu menu_only-redo. Använd drift för dagliga tester.",
        "tr": "Düğüm artık menu_only için hazır. Günlük testler için Operasyon'u kullanın.",
        "en": "The node is now menu_only-ready. Use operations for day-to-day testing.",
    },
    "welcome.action_open_operations_detail_basic": {
        "da": "Den grundlæggende pilotform er der. Brug drift til daglig test.",
        "sv": "Den grundläggande pilotformen finns där. Använd drift för dagliga tester.",
        "tr": "Temel pilot şekli hazır. Günlük testler için Operasyon'u kullanın.",
        "en": "The basic pilot shape is there. Use operations for day-to-day testing.",
    },
    "welcome.catalog_card_title": {
        "da": "Katalog er der, menuarbejdet sker",
        "sv": "Katalog är där menyn arbetas med",
        "tr": "Menü çalışması Katalog'da yapılır",
        "en": "Catalog is where menu work happens",
    },
    "welcome.catalog_card_detail": {
        "da": "Denne node har lige nu {count} katalogvare(r).",
        "sv": "Den här noden har just nu {count} katalogobjekt.",
        "tr": "Bu düğümde şu anda {count} katalog öğesi var.",
        "en": "This node currently has {count} catalog item(s).",
    },
    "welcome.modules_card_title": {
        "da": "Moduler er der, systemformen styres",
        "sv": "Moduler är där systemformen styrs",
        "tr": "Sistem şekli Modüller'de yönetilir",
        "en": "Modules is where system shape happens",
    },
    "welcome.modules_card_detail": {
        "da": "Kører nu: {current} modul(er). Ønsket efter genstart: {desired}.",
        "sv": "Kör nu: {current} modul(er). Önskat efter omstart: {desired}.",
        "tr": "Şimdi çalışan: {current} modül. Yeniden başlatmadan sonra istenen: {desired}.",
        "en": "Running now: {current} module(s). Desired after restart: {desired}.",
    },
    "operations.kitchen_title": {
        "da": "Køkken",
        "sv": "Kök",
        "tr": "Mutfak",
        "en": "Kitchen",
    },
    "operations.kitchen_body": {
        "da": "Indgående og aktive pickup-ordrer for det aktuelle skift.",
        "sv": "Inkommande och aktiva pickup-order för det aktuella skiftet.",
        "tr": "Geçerli vardiya için gelen ve aktif pickup siparişleri.",
        "en": "Incoming and active pickup orders for the current shift.",
    },
    "operations.backoffice_title": {
        "da": "Backoffice",
        "sv": "Backoffice",
        "tr": "Arka ofis",
        "en": "Backoffice",
    },
    "operations.backoffice_body": {
        "da": "Brug separate rum til menuarbejde og systemændringer. Redigér ikke kataloget på samme side, hvor du ser indgående ordrer.",
        "sv": "Använd separata rum för menyarbete och systemändringar. Redigera inte katalogen på samma sida där du ser inkommande order.",
        "tr": "Menü çalışması ve sistem değişiklikleri için ayrı odalar kullanın. Gelen siparişleri izlediğiniz aynı sayfada kataloğu düzenlemeyin.",
        "en": "Use separate rooms for menu work and system changes. Don’t edit the catalog on the same page where you watch incoming orders.",
    },
    "operations.catalog_card_body": {
        "da": "Redigér menuvarer, priser, kategorier og importhjælp i det dedikerede katalogrum.",
        "sv": "Redigera menyobjekt, priser, kategorier och importhjälp i det dedikerade katalogrummet.",
        "tr": "Menü öğelerini, fiyatları, kategorileri ve içe aktarma yardımını özel katalog odasında düzenleyin.",
        "en": "Edit menu items, prices, categories, and import help from the dedicated catalog room.",
    },
    "operations.modules_card_body": {
        "da": "Gennemgå modulhelbred, ønsket efter genstart og ekstra muligheder i det dedikerede modulrum.",
        "sv": "Granska modulhälsa, önskat efter omstart och extra möjligheter i det dedikerade modulrummet.",
        "tr": "Modül sağlığını, yeniden başlatmadan sonra istenen durumu ve ek yetenekleri özel modül odasında gözden geçirin.",
        "en": "Review module health, desired after restart, and optional capabilities in the dedicated modules room.",
    },
    "operations.restart_detail": {
        "da": "Det ønskede modulset er forskelligt fra den kørende node. Anvend ændringer ved at genstarte nodeprocessen efter dagens arbejde.",
        "sv": "Det önskade modulsetet skiljer sig från den körande noden. Verkställ ändringar genom att starta om nodprocessen efter dagens arbete.",
        "tr": "İstenen modül seti çalışan düğümden farklı. Değişiklikleri bugünkü iş bittiğinde düğüm sürecini yeniden başlatarak uygulayın.",
        "en": "The desired module set differs from the running node. Apply changes by restarting the node process after finishing today’s work.",
    },
    "orders.accept": {
        "da": "Acceptér",
        "sv": "Acceptera",
        "tr": "Kabul et",
        "en": "Accept",
    },
    "orders.ready": {
        "da": "Klar",
        "sv": "Klar",
        "tr": "Hazır",
        "en": "Ready",
    },
    "orders.complete": {
        "da": "Fuldfør",
        "sv": "Slutför",
        "tr": "Tamamla",
        "en": "Complete",
    },
    "orders.reject": {
        "da": "Afvis",
        "sv": "Avvisa",
        "tr": "Reddet",
        "en": "Reject",
    },
    "orders.cancel": {
        "da": "Annullér",
        "sv": "Avbryt",
        "tr": "İptal et",
        "en": "Cancel",
    },
    "orders.accepted_message": {
        "da": "Accepteret i køkkenet.",
        "sv": "Accepterad i köket.",
        "tr": "Mutfakta kabul edildi.",
        "en": "Accepted in kitchen.",
    },
    "orders.ready_message": {
        "da": "Klar til afhentning.",
        "sv": "Klar för upphämtning.",
        "tr": "Teslim almaya hazır.",
        "en": "Ready for pickup.",
    },
    "orders.completed_message": {
        "da": "Fuldført.",
        "sv": "Slutförd.",
        "tr": "Tamamlandı.",
        "en": "Completed.",
    },
    "orders.rejected_message": {
        "da": "Afvist af køkkenet.",
        "sv": "Avvisad av köket.",
        "tr": "Mutfak tarafından reddedildi.",
        "en": "Rejected by kitchen.",
    },
    "orders.cancelled_message": {
        "da": "Annulleret af køkkenet.",
        "sv": "Avbruten av köket.",
        "tr": "Mutfak tarafından iptal edildi.",
        "en": "Cancelled by kitchen.",
    },
    "catalog.editor_title": {
        "da": "Katalogeditor",
        "sv": "Katalogredigerare",
        "tr": "Katalog düzenleyici",
        "en": "Catalog editor",
    },
    "catalog.editor_body": {
        "da": "Redigér den strukturerede menu her. Hold live ordrehåndtering i Drift, ikke på denne side.",
        "sv": "Redigera den strukturerade menyn här. Behåll live orderhantering i Drift, inte på den här sidan.",
        "tr": "Yapılandırılmış menüyü burada düzenleyin. Canlı sipariş yönetimini bu sayfada değil, Operasyon'da tutun.",
        "en": "Edit the structured menu here. Keep live order handling in Operations, not on this page.",
    },
    "catalog.photo_import_title": {
        "da": "Fotoimport",
        "sv": "Fotoimport",
        "tr": "Fotoğraf içe aktarma",
        "en": "Photo import",
    },
    "catalog.photo_import_body": {
        "da": "OCR-import ejes af modulet. Åbn OCR-modulsiden, når modulet er aktivt på denne node.",
        "sv": "OCR-import ägs av modulen. Öppna OCR-modulsidan när modulen är aktiv på den här noden.",
        "tr": "OCR içe aktarma modüle aittir. Modül bu düğümde etkin olduğunda OCR modül sayfasını açın.",
        "en": "OCR import is module-owned. Open the OCR module page when that module is enabled on this node.",
    },
    "catalog.ocr_card_title": {
        "da": "Katalog OCR-import",
        "sv": "Katalog OCR-import",
        "tr": "Katalog OCR içe aktarma",
        "en": "Catalog OCR import",
    },
    "catalog.ocr_enabled_now": {
        "da": "OCR-modulet er aktivt nu. Brug den dedikerede OCR-modulsida til fotogennemgang.",
        "sv": "OCR-modulen är aktiv nu. Använd den dedikerade OCR-modulsidan för fotogranskning.",
        "tr": "OCR modülü şu anda etkin. Fotoğraf incelemesi için özel OCR modül sayfasını kullanın.",
        "en": "The OCR module is enabled now. Use the dedicated OCR module page for photo-import review.",
    },
    "catalog.ocr_disabled_now": {
        "da": "OCR-modulet er ikke aktivt nu. Aktivér det fra Moduler og genstart noden før fotoimport.",
        "sv": "OCR-modulen är inte aktiv nu. Aktivera den från Moduler och starta om noden före fotoimport.",
        "tr": "OCR modülü şu anda etkin değil. Fotoğraf içe aktarmadan önce onu Modüller'den etkinleştirip düğümü yeniden başlatın.",
        "en": "The OCR module is not enabled now. Enable it from Modules and restart the node before using photo import.",
    },
    "catalog.needs_one_item": {
        "da": "Kataloget skal have mindst én vare.",
        "sv": "Katalogen behöver minst ett objekt.",
        "tr": "Katalogda en az bir öğe olmalı.",
        "en": "Catalog needs at least one item.",
    },
    "catalog.saved": {
        "da": "Katalog gemt.",
        "sv": "Katalog sparad.",
        "tr": "Katalog kaydedildi.",
        "en": "Catalog saved.",
    },
    "field.id": {
        "da": "ID",
        "sv": "ID",
        "tr": "Kimlik",
        "en": "ID",
    },
    "field.name": {
        "da": "Navn",
        "sv": "Namn",
        "tr": "Ad",
        "en": "Name",
    },
    "field.description": {
        "da": "Beskrivelse",
        "sv": "Beskrivning",
        "tr": "Açıklama",
        "en": "Description",
    },
    "field.category": {
        "da": "Kategori",
        "sv": "Kategori",
        "tr": "Kategori",
        "en": "Category",
    },
    "field.price_minor": {
        "da": "Pris (minor units)",
        "sv": "Pris (minor units)",
        "tr": "Fiyat (küçük birimler)",
        "en": "Price (minor units)",
    },
    "field.image_url": {
        "da": "Billede-URL",
        "sv": "Bild-URL",
        "tr": "Görsel URL'si",
        "en": "Image URL",
    },
    "field.active": {
        "da": "Aktiv",
        "sv": "Aktiv",
        "tr": "Etkin",
        "en": "Active",
    },
    "discover.recommended_title": {
        "da": "Anbefalet til denne butikstype",
        "sv": "Rekommenderat för den här butikstypen",
        "tr": "Bu dükkân türü için önerilen",
        "en": "Recommended for this kind of shop",
    },
    "discover.family_summary_default": {
        "da": "Den første offentlige familie er den generiske shop-familie, ikke en pizza-only ramme.",
        "sv": "Den första offentliga familjen är den generiska shop-familjen, inte en pizza-only-ram.",
        "tr": "İlk genel aile, yalnızca pizza çerçevesi değil, genel shop ailesidir.",
        "en": "The first public family is the generic shop family, not a pizza-only frame.",
    },
    "discover.groups_title": {
        "da": "Gennemse modulgrupper",
        "sv": "Bläddra bland modulgrupper",
        "tr": "Modül gruplarına göz at",
        "en": "Browse module groups",
    },
    "discover.groups_body": {
        "da": "Læs det offentlige modulkatalog her, og brug derefter Moduler til at ændre det ønskede lokale sæt eller Importér til en lokal manifestfil.",
        "sv": "Läs den offentliga modulkatalogen här och använd sedan Moduler för att ändra den önskade lokala uppsättningen eller Importera för en lokal manifestfil.",
        "tr": "Genel modül kataloğunu burada okuyun, ardından istenen yerel seti değiştirmek için Modüller'i ya da yerel bir manifest dosyası getirmek için İçe aktar'ı kullanın.",
        "en": "Read the public module catalog here, then use Modules to change the desired local set or Import to bring in a local manifest file.",
    },
    "discover.restart_detail": {
        "da": "Det ønskede modulset er forskelligt fra den kørende node. Hold discovery læsende her, og anvend ændringer fra Moduler før genstart.",
        "sv": "Det önskade modulsetet skiljer sig från den körande noden. Håll discovery läsande här och gör ändringar från Moduler före omstart.",
        "tr": "İstenen modül seti çalışan düğümden farklı. Burada keşfi yalnızca okuma modunda tutun ve yeniden başlatmadan önce değişiklikleri Modüller'den uygulayın.",
        "en": "The desired module set differs from the running node. Keep discovery read-only here, then apply changes from Modules and restart when the shop is ready.",
    },
    "discover.module_count": {
        "da": "{count} moduler",
        "sv": "{count} moduler",
        "tr": "{count} modül",
        "en": "{count} modules",
    },
    "discover.import_your_manifest": {
        "da": "Importér dit eget manifest",
        "sv": "Importera ditt eget manifest",
        "tr": "Kendi manifestinizi içe aktarın",
        "en": "Import your own manifest",
    },
    "discover.open_local_modules_room": {
        "da": "Åbn lokalt modulrum",
        "sv": "Öppna lokalt modulrum",
        "tr": "Yerel Modüller odasını aç",
        "en": "Open local Modules room",
    },
    "modules.control_title": {
        "da": "Modulkontrol",
        "sv": "Modulkontroll",
        "tr": "Modül kontrolü",
        "en": "Module control",
    },
    "modules.control_body": {
        "da": "Vælg hvad der skal køre på denne node. Brug Find moduler til offentlig læsning og Importér til node-lokal manifestindtagelse.",
        "sv": "Välj vad som ska köra på den här noden. Använd Hitta moduler för offentlig läsning och Importera för nodlokal manifestinläsning.",
        "tr": "Bu düğümde neyin çalışacağını seçin. Genel okuma için Modülleri bul'u, düğümde yerel manifest alma için İçe aktar'ı kullanın.",
        "en": "Choose what should run on this node. Use Discover for public reading and Import for node-local manifest intake.",
    },
    "modules.current_body": {
        "da": "Kører nu på denne node.",
        "sv": "Kör nu på den här noden.",
        "tr": "Şu anda bu düğümde çalışıyor.",
        "en": "Running now on this node.",
    },
    "modules.available_body": {
        "da": "Kendt af denne node, men kører ikke endnu.",
        "sv": "Känd av den här noden, men kör inte ännu.",
        "tr": "Bu düğüm tarafından biliniyor, ancak henüz çalışmıyor.",
        "en": "Known to this node, but not running yet.",
    },
    "modules.imported_body": {
        "da": "Lagret kun på denne node. Ikke kørbar i denne fase.",
        "sv": "Lagrad bara på den här noden. Inte körbar i den här fasen.",
        "tr": "Yalnızca bu düğümde saklanır. Bu aşamada çalıştırılamaz.",
        "en": "Stored on this node only. Not runnable in this phase.",
    },
    "modules.state_title": {
        "da": "Modulsættets status",
        "sv": "Moduluppsättningens status",
        "tr": "Modül seti durumu",
        "en": "Module set state",
    },
    "modules.state_differs": {
        "da": "Det ønskede sæt adskiller sig fra den kørende runtime.",
        "sv": "Den önskade uppsättningen skiljer sig från den körande runtimen.",
        "tr": "İstenen set çalışan çalışma zamanından farklı.",
        "en": "Desired set differs from running runtime.",
    },
    "modules.state_in_sync": {
        "da": "Runtime matcher det ønskede sæt.",
        "sv": "Runtimen matchar den önskade uppsättningen.",
        "tr": "Çalışma zamanı istenen setle eşleşiyor.",
        "en": "Runtime matches desired set.",
    },
    "modules.desired_updated": {
        "da": "ønsket opdateret {timestamp}",
        "sv": "önskat uppdaterat {timestamp}",
        "tr": "istenen güncellendi {timestamp}",
        "en": "desired updated {timestamp}",
    },
    "modules.desired_payment": {
        "da": "ønsket betaling {payment}",
        "sv": "önskad betalning {payment}",
        "tr": "istenen ödeme {payment}",
        "en": "desired payment {payment}",
    },
    "modules.runtime_in_sync": {
        "da": "runtime i sync",
        "sv": "runtime i synk",
        "tr": "çalışma zamanı senkte",
        "en": "runtime in sync",
    },
    "modules.current_filtered_empty": {
        "da": "Ingen nuværende moduler matcher de aktive filtre.",
        "sv": "Inga nuvarande moduler matchar de aktiva filtren.",
        "tr": "Etkin filtrelerle eşleşen geçerli modül yok.",
        "en": "No current modules match the active filters.",
    },
    "modules.available_filtered_empty": {
        "da": "Ingen tilgængelige moduler matcher de aktive filtre.",
        "sv": "Inga tillgängliga moduler matchar de aktiva filtren.",
        "tr": "Etkin filtrelerle eşleşen kullanılabilir modül yok.",
        "en": "No available modules match the active filters.",
    },
    "modules.imported_metadata": {
        "da": "Importeret modulmetadata",
        "sv": "Importerad modulmetadata",
        "tr": "İçe aktarılan modül metadata'sı",
        "en": "Imported module metadata",
    },
    "modules.open_module_page": {
        "da": "Åbn modulsiden",
        "sv": "Öppna modulsidan",
        "tr": "Modül sayfasını aç",
        "en": "Open module page",
    },
    "modules.wanted_after_restart": {
        "da": "ønsket efter genstart",
        "sv": "önskat efter omstart",
        "tr": "yeniden başlatmadan sonra istenen",
        "en": "wanted after restart",
    },
    "modules.not_wanted_after_restart": {
        "da": "ikke ønsket efter genstart",
        "sv": "inte önskat efter omstart",
        "tr": "yeniden başlatmadan sonra istenmeyen",
        "en": "not wanted after restart",
    },
    "modules.module_count_label": {
        "da": "{count} moduler",
        "sv": "{count} moduler",
        "tr": "{count} modül",
        "en": "{count} modules",
    },
    "import.local_manifest_title": {
        "da": "Importér lokalt manifest",
        "sv": "Importera lokalt manifest",
        "tr": "Yerel manifesti içe aktar",
        "en": "Import local manifest",
    },
    "import.local_manifest_body": {
        "da": "Upload én lokal module.json. Denne fase gemmer kun metadata på noden. Importerede manifests er ikke kørbare og indgår ikke i det ønskede runtime-sæt endnu.",
        "sv": "Ladda upp en lokal module.json. Den här fasen lagrar bara metadata på noden. Importerade manifest är inte körbara och går ännu inte in i den önskade runtime-uppsättningen.",
        "tr": "Bir yerel module.json yükleyin. Bu aşama yalnızca düğümde metadata saklar. İçe aktarılan manifestler çalıştırılamaz ve henüz istenen çalışma zamanı setine girmez.",
        "en": "Upload one local module.json. This phase stores metadata on the node only. Imported manifests are not runnable and do not enter the desired runtime set yet.",
    },
    "import.imported_manifests_body": {
        "da": "Disse manifests lever kun på denne node til review. Brug Moduler senere, når en fremtidig fase gør importerede manifests kørbare.",
        "sv": "De här manifesten finns bara på den här noden för granskning. Använd Moduler senare när en framtida fas gör importerade manifest körbara.",
        "tr": "Bu manifestler yalnızca inceleme için bu düğümde bulunur. Gelecekteki bir aşama içe aktarılan manifestleri çalıştırılabilir hale getirdiğinde daha sonra Modüller'i kullanın.",
        "en": "These manifests live only on this node for review. Use Modules later when a future phase makes imported manifests runnable.",
    },
    "node.runtime_body": {
        "da": "Hvad denne lokale node faktisk kører og annoncerer nu.",
        "sv": "Vad den här lokala noden faktiskt kör och annonserar nu.",
        "tr": "Bu yerel düğümün şu anda gerçekten ne çalıştırdığı ve duyurduğu.",
        "en": "What this local node is actually running and announcing now.",
    },
    "node.setup_truth_body": {
        "da": "Bekræftet hardware, lokale checks og opsætningshukommelse for denne node.",
        "sv": "Bekräftad hårdvara, lokala kontroller och inställningsminne för den här noden.",
        "tr": "Bu düğüm için doğrulanmış donanım, yerel kontroller ve kurulum belleği.",
        "en": "Confirmed hardware, local checks, and setup memory for this node.",
    },
    "node.restart_detail": {
        "da": "Det ønskede modulset er forskelligt fra den kørende node. Gør den lokale gennemgang færdig og genstart derefter nodeprocessen, før du stoler på runtimen som endelig.",
        "sv": "Det önskade modulsetet skiljer sig från den körande noden. Slutför den lokala granskningen och starta sedan om nodprocessen innan du litar på runtimen som slutlig.",
        "tr": "İstenen modül seti çalışan düğümden farklı. Çalışma zamanına son hâliymiş gibi güvenmeden önce yerel incelemeyi bitirin ve ardından düğüm sürecini yeniden başlatın.",
        "en": "The desired module set differs from the running node. Finish local review, then restart the node process before trusting the runtime as final.",
    },
    "node.runtime_bundle": {
        "da": "Runtime-bundle",
        "sv": "Runtime-bundle",
        "tr": "Çalışma zamanı paketi",
        "en": "Runtime bundle",
    },
    "node.runtime_base": {
        "da": "Runtime-base",
        "sv": "Runtime-bas",
        "tr": "Çalışma zamanı tabanı",
        "en": "Runtime base",
    },
    "node.runtime_addons": {
        "da": "Runtime-add-ons",
        "sv": "Runtime-tillägg",
        "tr": "Çalışma zamanı eklentileri",
        "en": "Runtime add-ons",
    },
    "node.confirmed_bundle": {
        "da": "Bekræftet bundle",
        "sv": "Bekräftat bundle",
        "tr": "Doğrulanan paket",
        "en": "Confirmed bundle",
    },
    "node.confirmed_base": {
        "da": "Bekræftet base",
        "sv": "Bekräftad bas",
        "tr": "Doğrulanan taban",
        "en": "Confirmed base",
    },
    "node.confirmed_addons": {
        "da": "Bekræftede add-ons",
        "sv": "Bekräftade tillägg",
        "tr": "Doğrulanan eklentiler",
        "en": "Confirmed add-ons",
    },
    "node.setup_completed": {
        "da": "Opsætning fuldført",
        "sv": "Inställning klar",
        "tr": "Kurulum tamamlandı",
        "en": "Setup completed",
    },
    "node.catalog_reviewed": {
        "da": "Katalog gennemgået",
        "sv": "Katalog granskat",
        "tr": "Katalog gözden geçirildi",
        "en": "Catalog reviewed",
    },
    "node.local_tests_run": {
        "da": "Lokale tests kørt",
        "sv": "Lokala tester körda",
        "tr": "Yerel testler çalıştırıldı",
        "en": "Local tests run",
    },
    "node.operator_locale": {
        "da": "Operator-locale",
        "sv": "Operatörslocale",
        "tr": "Operatör yerel ayarı",
        "en": "Operator locale",
    },
    "node.registry_urls": {
        "da": "Register-URL'er",
        "sv": "Register-URL:er",
        "tr": "Kayıt URL'leri",
        "en": "Registry URLs",
    },
    "node.registry_ready_state": {
        "da": "klar",
        "sv": "klar",
        "tr": "hazır",
        "en": "ready",
    },
    "node.registry_not_ready_state": {
        "da": "ikke klar",
        "sv": "inte klar",
        "tr": "hazır değil",
        "en": "not ready",
    },
    "node.started": {
        "da": "Startet",
        "sv": "Startad",
        "tr": "Başlatıldı",
        "en": "Started",
    },
    "node.last_reviewed": {
        "da": "Senest gennemgået",
        "sv": "Senast granskad",
        "tr": "Son gözden geçirme",
        "en": "Last reviewed",
    },
    "setup.checklist_title": {
        "da": "Opsætningscheckliste",
        "sv": "Inställningschecklista",
        "tr": "Kurulum kontrol listesi",
        "en": "Setup checklist",
    },
    "setup.checklist_body": {
        "da": "Brug dette til at få noden sikkert ind i menu_only først.",
        "sv": "Använd detta för att få noden säkert in i menu_only först.",
        "tr": "Düğümü önce güvenli biçimde menu_only moduna almak için bunu kullanın.",
        "en": "Use this to get the node safely into `menu_only` first.",
    },
    "setup.recorded_state_title": {
        "da": "Registreret opsætningsstate",
        "sv": "Registrerad inställningsstatus",
        "tr": "Kaydedilen kurulum durumu",
        "en": "Recorded setup state",
    },
    "setup.recorded_state_body": {
        "da": "Små lokale noter for denne node. Runtime-sandheden lever stadig i de rigtige rum.",
        "sv": "Små lokala anteckningar för den här noden. Runtime-sanningen finns fortfarande i de riktiga rummen.",
        "tr": "Bu düğüm için küçük yerel notlar. Çalışma zamanı gerçeği hâlâ gerçek odalarda yaşar.",
        "en": "Small local notes for this node. Runtime truth still lives in the real rooms.",
    },
    "setup.reviewed_menu": {
        "da": "Jeg gennemgik den første rigtige menu på denne node.",
        "sv": "Jag granskade den första riktiga menyn på den här noden.",
        "tr": "Bu düğümdeki ilk gerçek menüyü gözden geçirdim.",
        "en": "I reviewed the first real menu on this node.",
    },
    "setup.local_tests_check": {
        "da": "Jeg kørte lokale tests eller hardwarechecks for denne node.",
        "sv": "Jag körde lokala tester eller hårdvarukontroller för den här noden.",
        "tr": "Bu düğüm için yerel testler veya donanım kontrolleri çalıştırdım.",
        "en": "I ran local tests or hardware checks for this node.",
    },
    "setup.no_state_saved": {
        "da": "Ingen opsætningsstate gemt endnu.",
        "sv": "Ingen inställningsstatus sparad ännu.",
        "tr": "Henüz kurulum durumu kaydedilmedi.",
        "en": "No setup state saved yet.",
    },
    "setup.modules_shape_title": {
        "da": "Moduler sætter nodeformen",
        "sv": "Moduler sätter nodformen",
        "tr": "Düğüm şeklini Modüller belirler",
        "en": "Modules sets the node shape",
    },
    "setup.modules_shape_body": {
        "da": "Vælg runtime-sættet dér, ikke her.",
        "sv": "Välj runtime-uppsättningen där, inte här.",
        "tr": "Çalışma zamanı setini burada değil, orada seçin.",
        "en": "Pick the runtime set there, not here.",
    },
    "setup.catalog_room_title": {
        "da": "Katalog holder den første rigtige menu",
        "sv": "Katalog håller den första riktiga menyn",
        "tr": "İlk gerçek menü Katalog'da tutulur",
        "en": "Catalog holds the first real menu",
    },
    "setup.catalog_room_body": {
        "da": "Tilføj eller importér rigtige varer dér, før du tester flowet.",
        "sv": "Lägg till eller importera riktiga objekt där innan du testar flödet.",
        "tr": "Akışı test etmeden önce gerçek öğeleri orada ekleyin veya içe aktarın.",
        "en": "Add or import real items there before testing the flow.",
    },
    "setup.operations_room_title": {
        "da": "Drift holder den rigtige runtime",
        "sv": "Drift håller den riktiga runtimen",
        "tr": "Gerçek çalışma zamanı Operasyon'da tutulur",
        "en": "Operations holds the real runtime",
    },
    "setup.operations_room_body": {
        "da": "Hold noden i menu_only dér, mens du tester lokalt.",
        "sv": "Behåll noden i menu_only där medan du testar lokalt.",
        "tr": "Yerel test yaparken düğümü orada menu_only modunda tutun.",
        "en": "Keep the node in `menu_only` there while you test locally.",
    },
    "setup.hardware_bundle": {
        "da": "Hardware-bundle",
        "sv": "Hårdvarubundle",
        "tr": "Donanım paketi",
        "en": "Hardware bundle",
    },
    "setup.base_shape": {
        "da": "Base-form",
        "sv": "Basform",
        "tr": "Temel şekil",
        "en": "Base shape",
    },
    "setup.extra_hardware": {
        "da": "Ekstra hardware",
        "sv": "Extra hårdvara",
        "tr": "Ek donanım",
        "en": "Extra hardware",
    },
    "setup.restart_detail": {
        "da": "Det ønskede modulset er gemt, men runtimen skal stadig genstartes. Gør det færdigt før du stoler på checklisten.",
        "sv": "Det önskade modulsetet är sparat, men runtimen måste fortfarande startas om. Gör det klart innan du litar på checklistan.",
        "tr": "İstenen modül seti kaydedildi, ancak çalışma zamanının hâlâ yeniden başlatılması gerekiyor. Kontrol listesine güvenmeden önce bunu tamamlayın.",
        "en": "The desired module set is saved, but the runtime still needs a restart. Finish that before trusting the checklist.",
    },
    "setup.saving_state": {
        "da": "Gemmer opsætningsstate.",
        "sv": "Sparar inställningsstatus.",
        "tr": "Kurulum durumu kaydediliyor.",
        "en": "Saving setup state.",
    },
    "setup.saved_state": {
        "da": "Opsætningsstate gemt.",
        "sv": "Inställningsstatus sparad.",
        "tr": "Kurulum durumu kaydedildi.",
        "en": "Saved setup state.",
    },
    "setup.done": {
        "da": "færdig",
        "sv": "klar",
        "tr": "tamam",
        "en": "done",
    },
    "setup.next": {
        "da": "næste",
        "sv": "nästa",
        "tr": "sonraki",
        "en": "next",
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
        "en": "Shop",
    },
    "summary": {
        "da": "Moduler til små lokale butikker, takeaway, counter pickup og enkel direkte handel.",
        "sv": "Moduler för små lokala butiker, takeaway, pickup över disk och enkel direkt handel.",
        "tr": "Küçük yerel dükkânlar, takeaway, tezgahtan teslim ve basit doğrudan ticaret için modüller.",
        "ar": "وحدات للمتاجر المحلية الصغيرة، والطلبات الجاهزة، والاستلام من الكاونتر، والتعامل المباشر البسيط.",
        "ku": "Modul ji bo dikkanên biçûk ên herêmî, takeaway, stand pickup û bazirganiya rasterast a hêsan.",
        "en": "Modules for small local shops, takeaway, counter pickup, and simple direct trade.",
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
            "en": "Menu and catalog",
        },
        "summary": {
            "da": "Byg eller importér menuen og hold priser og varer på din egen node.",
            "sv": "Bygg eller importera menyn och behåll priser och artiklar på din egen nod.",
            "tr": "Menüyü oluşturun veya içe aktarın ve fiyatlarıyla ürünleri kendi düğümünüzde tutun.",
            "ar": "ابنِ القائمة أو استوردها واحتفظ بالأسعار والمواد على عقدتك الخاصة.",
            "ku": "Menuyê ava bike an derxe hundir û bihayê û tiştan li ser nodeya xwe biparêze.",
            "en": "Build or import the menu and keep prices and items on your own node.",
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
            "en": "Customer surfaces",
        },
        "summary": {
            "da": "Det kunden ser før og efter ordren: menu og status.",
            "sv": "Det kunden ser före och efter ordern: meny och status.",
            "tr": "Müşterinin siparişten önce ve sonra gördüğü şeyler: menü ve durum.",
            "ar": "ما يراه الزبون قبل الطلب وبعده: القائمة والحالة.",
            "ku": "Tiştên ku xerîdar berî û piştî fermanê dibîne: menu û status.",
            "en": "What the customer sees before and after the order: menu and status.",
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
            "en": "Counter, kitchen, and hardware",
        },
        "summary": {
            "da": "Lokale operatorflader og hardwarehjælpere til køkken, print, pickup og alarm.",
            "sv": "Lokala operatörsytor och hårdvaruhjälpare för kök, utskrift, pickup och larm.",
            "tr": "Mutfak, baskı, teslim ve alarm için yerel operatör yüzleri ve donanım yardımcıları.",
            "ar": "واجهات المشغّل المحلية ومساعدات العتاد للمطبخ والطباعة والاستلام والتنبيه.",
            "ku": "Rûyên operatorê yên herêmî û alîkarên hardware ji bo metbex, çap, pickup û hişyarî.",
            "en": "Local operator surfaces and hardware helpers for kitchen, print, pickup, and alerts.",
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
            "en": "Payment",
        },
        "summary": {
            "da": "Hold betaling lille i starten og tilføj kun de adapters, du faktisk vil stå på mål for.",
            "sv": "Håll betalningen liten i början och lägg bara till de adaptrar du faktiskt vill stå för.",
            "tr": "Ödemeyi başlangıçta küçük tutun ve yalnızca gerçekten desteklemek istediğiniz adaptörleri ekleyin.",
            "ar": "أبقِ الدفع صغيراً في البداية وأضف فقط الوحدات التي تريد فعلاً الوقوف خلفها.",
            "ku": "Di destpêkê de dravdan biçûk bîne û tenê wan adapteran zêde bike ku tu bixwazî bi rastî piştgirîyê bidî.",
            "en": "Keep payment small at the start and add only the adapters you actually want to stand behind.",
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
            "en": "Notifications",
        },
        "summary": {
            "da": "Fallback-alarm når noget lokalt kræver opmærksomhed.",
            "sv": "Reservlarm när något lokalt kräver uppmärksamhet.",
            "tr": "Yerel olarak dikkat gerektiren durumlar için yedek uyarılar.",
            "ar": "تنبيهات احتياطية عندما يحتاج شيء محلي إلى انتباه.",
            "ku": "Hişyariyên paşve ji bo dema ku tiştek herêmî baldariyê dixwaze.",
            "en": "Fallback alerts when something local needs attention.",
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
            "en": "Trust and identity",
        },
        "summary": {
            "da": "Retninger for senere forretningsidentitet og dokumenterbar tillid.",
            "sv": "Riktningar för senare företagsidentitet och dokumenterbar tillit.",
            "tr": "Daha sonra iş kimliği ve belgelenebilir güven için yönler.",
            "ar": "اتجاهات لهوية العمل لاحقاً وثقة قابلة للمراجعة.",
            "ku": "Rêçûnên paşerojê ji bo nasnameya karsazî û baweriya ku dikare were nîşandan.",
            "en": "Directions for later business identity and reviewable trust.",
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
            "en": "Internal test modules",
        },
        "summary": {
            "da": "Ting du bruger til at bryde flowet sikkert, ikke til at love en butik en live funktion.",
            "sv": "Saker du använder för att bryta flödet säkert, inte för att lova en butik en live-funktion.",
            "tr": "Akışı güvenle bozmak için kullandığınız şeylerdir; bir dükkâna canlı özellik vaadi değildir.",
            "ar": "أشياء تستخدمها لكسر التدفق بأمان، لا لتعد بها متجراً كوظيفة حية.",
            "ku": "Tiştên ku tu bi wan re rêçê bi ewle têk dibî, ne ji bo ku tu foksiyoneke zindî bi dikanek re bistînî.",
            "en": "Things you use to break the flow safely, not to promise a shop a live function.",
        },
        "order": 70,
    },
}


MODULE_META: dict[str, dict[str, Any]] = {
    "p4p.catalog.editor": {
        "category_id": "menu_catalog",
        "title": {"da": "Redigér menu", "sv": "Redigera meny", "tr": "Menüyü düzenle", "en": "Edit menu"},
        "summary": {
            "da": "Redigér navne, priser, kategorier og aktive varer direkte på butikkens egen node.",
            "sv": "Redigera namn, priser, kategorier och aktiva objekt direkt på butikens egen nod.",
            "tr": "Adları, fiyatları, kategorileri ve etkin öğeleri doğrudan dükkâna ait düğüm üzerinde düzenleyin.",
            "en": "Edit names, prices, categories, and active items directly on the shop-owned node.",
        },
        "recommended_with": ["p4p.menu.list", "p4p.customer.status", "p4p.payment.cash"],
    },
    "p4p.catalog.import.ocr": {
        "category_id": "menu_catalog",
        "title": {"da": "Importér menu fra foto", "sv": "Importera meny från foto", "tr": "Menüyü fotoğraftan içe aktar", "en": "Import menu from photo"},
        "summary": {
            "da": "Lav OCR-drafts fra et papir-menukort før et menneske gemmer noget til katalogsandheden.",
            "sv": "Skapa OCR-utkast från en pappersmeny innan en människa sparar något till katalogsanningen.",
            "tr": "Bir insan kataloğun gerçeğine bir şey kaydetmeden önce kâğıt menüden OCR taslakları oluşturun.",
            "en": "Create OCR drafts from a paper menu before a human saves anything into catalog truth.",
        },
        "recommended_with": ["p4p.catalog.editor"],
    },
    "p4p.menu.list": {
        "category_id": "customer_surfaces",
        "title": {"da": "Enkel kundemenu", "sv": "Enkel kundmeny", "tr": "Basit müşteri menüsü", "en": "Simple customer menu"},
        "summary": {
            "da": "Vis en klassisk online menu og send ordren direkte til noden.",
            "sv": "Visa en klassisk onlinemeny och skicka ordern direkt till noden.",
            "tr": "Klasik bir çevrimiçi menü gösterin ve siparişi doğrudan düğüme gönderin.",
            "en": "Show a classic online menu and send the order directly to the node.",
        },
        "recommended_with": ["p4p.customer.status", "p4p.payment.cash", "p4p.catalog.editor"],
    },
    "p4p.menu.photo-map": {
        "category_id": "customer_surfaces",
        "title": {"da": "Klikbar menufoto-side", "sv": "Klickbar menyfotosida", "tr": "Tıklanabilir menü fotoğraf sayfası", "en": "Clickable menu photo page"},
        "summary": {
            "da": "Vis menuen som et visuelt kort i stedet for en ren liste.",
            "sv": "Visa menyn som en visuell karta i stället för en ren lista.",
            "tr": "Menüyü düz bir liste yerine görsel bir harita olarak gösterin.",
            "en": "Show the menu as a visual map instead of a plain list.",
        },
        "recommended_with": ["p4p.customer.status", "p4p.catalog.editor"],
    },
    "p4p.customer.status": {
        "category_id": "customer_surfaces",
        "title": {"da": "Kunde-statusside", "sv": "Kundstatussida", "tr": "Müşteri durum sayfası", "en": "Customer status page"},
        "summary": {
            "da": "Lad kunden se om ordren er modtaget, afvist eller klar til afhentning.",
            "sv": "Låt kunden se om ordern är mottagen, avvisad eller klar för upphämtning.",
            "tr": "Müşterinin siparişin alındığını, reddedildiğini veya teslim almaya hazır olduğunu görmesini sağlayın.",
            "en": "Let the customer see whether the order is received, rejected, or ready for pickup.",
        },
        "recommended_with": ["p4p.menu.list", "p4p.payment.cash"],
    },
    "p4p.kitchen.screen": {
        "category_id": "counter_hardware",
        "title": {"da": "Køkkenkø", "sv": "Kökskö", "tr": "Mutfak kuyruğu", "en": "Kitchen queue"},
        "summary": {
            "da": "Vis indkommende ordrer og flyt dem gennem køkkenets arbejdsgang.",
            "sv": "Visa inkommande order och flytta dem genom kökets arbetsflöde.",
            "tr": "Gelen siparişleri gösterin ve onları mutfak iş akışı boyunca ilerletin.",
            "en": "Show incoming orders and move them through the kitchen workflow.",
        },
        "recommended_with": ["p4p.menu.list", "p4p.customer.status", "p4p.payment.cash"],
    },
    "p4p.order.print": {
        "category_id": "counter_hardware",
        "title": {"da": "Print ordre", "sv": "Skriv ut order", "tr": "Siparişi yazdır", "en": "Print order"},
        "summary": {
            "da": "Send accepterede ordrer videre til en printer eller lokal POS-lignende flade.",
            "sv": "Skicka accepterade order vidare till en skrivare eller lokal POS-liknande yta.",
            "tr": "Kabul edilen siparişleri bir yazıcıya veya yerel POS benzeri bir yüzeye yönlendirin.",
            "en": "Forward accepted orders to a printer or local POS-like surface.",
        },
        "recommended_with": ["p4p.kitchen.screen", "p4p.order.print.backup"],
    },
    "p4p.order.print.backup": {
        "category_id": "counter_hardware",
        "title": {"da": "Backup-print", "sv": "Backup-utskrift", "tr": "Yedek yazdırma", "en": "Backup print"},
        "summary": {
            "da": "Hold en ekstra printvej klar, hvis den første printersti fejler.",
            "sv": "Håll en extra utskriftsväg redo om den första skrivarslingan fallerar.",
            "tr": "İlk yazıcı yolu başarısız olursa ikinci bir yazdırma yolunu hazır tutun.",
            "en": "Keep a secondary print path ready if the first printer path fails.",
        },
        "recommended_with": ["p4p.order.print", "p4p.notify.email"],
    },
    "p4p.order.alert.basic": {
        "category_id": "counter_hardware",
        "title": {"da": "Lyd eller lysalarm", "sv": "Ljud- eller ljuslarm", "tr": "Ses veya ışık uyarısı", "en": "Bell or light alert"},
        "summary": {
            "da": "Ring, bip eller blink lokalt, når en ny ordre kræver opmærksomhed.",
            "sv": "Ring, pipa eller blinka lokalt när en ny order kräver uppmärksamhet.",
            "tr": "Yeni bir sipariş dikkat gerektirdiğinde yerel olarak çalın, bipleyin veya yanıp sönün.",
            "en": "Ring, beep, or flash locally when a new order needs attention.",
        },
        "recommended_with": ["p4p.kitchen.screen", "p4p.notify.sms"],
    },
    "p4p.pickup.board.basic": {
        "category_id": "counter_hardware",
        "title": {"da": "Afhentningsskærm", "sv": "Pickup-tavla", "tr": "Teslim alma panosu", "en": "Pickup board"},
        "summary": {
            "da": "Vis accepterede eller klare ordrer på en enkel kundevendt pickup-skærm.",
            "sv": "Visa accepterade eller klara order på en enkel kundvänd pickup-skärm.",
            "tr": "Kabul edilen veya hazır siparişleri basit bir müşteri ekranlı teslim alma panosunda gösterin.",
            "en": "Show accepted or ready orders on a simple customer-facing pickup board.",
        },
        "recommended_with": ["p4p.customer.status", "p4p.kitchen.screen"],
    },
    "p4p.stock.basic": {
        "category_id": "counter_hardware",
        "title": {"da": "Slutlagercheck", "sv": "Sista lagerkontroll", "tr": "Son stok kontrolü", "en": "Final stock check"},
        "summary": {
            "da": "Lav et sidste lokalt stock-check før næste ordrestep går videre.",
            "sv": "Gör en sista lokal lagerkontroll innan nästa ordersteg går vidare.",
            "tr": "Bir sonraki sipariş adımı devam etmeden önce son bir yerel stok kontrolü çalıştırın.",
            "en": "Run one final local stock check before the next order step continues.",
        },
        "recommended_with": ["p4p.catalog.editor", "p4p.kitchen.screen"],
    },
    "p4p.payment.cash": {
        "category_id": "payment_adapters",
        "title": {"da": "Betal ved afhentning", "sv": "Betala vid upphämtning", "tr": "Teslim alırken öde", "en": "Pay at pickup"},
        "summary": {
            "da": "Hold betaling enkel: bestil online, betal i butikken.",
            "sv": "Håll betalningen enkel: beställ online, betala i butiken.",
            "tr": "Ödemeyi basit tutun: çevrimiçi sipariş verin, dükkânda ödeyin.",
            "en": "Keep payment simple: order online, pay in the shop.",
        },
        "recommended_with": ["p4p.menu.list", "p4p.customer.status", "p4p.kitchen.screen"],
    },
    "p4p.payment.mobilepay": {
        "category_id": "payment_adapters",
        "title": {"da": "MobilePay-adapter", "sv": "MobilePay-adapter", "tr": "MobilePay adaptörü", "en": "MobilePay adapter"},
        "summary": {
            "da": "Senere ekstern adapter til et kendt pay-at-pickup-flow uden at gøre P4P til betalingsprocessor.",
            "sv": "Senare extern adapter för ett välkänt pay-at-pickup-flöde utan att göra P4P till betalprocessor.",
            "tr": "P4P'yi ödeme işlemcisine dönüştürmeden tanıdık bir teslim alırken ödeme akışı için daha sonraki dış adaptör.",
            "en": "Later external adapter for a familiar pay-at-pickup flow without turning P4P into the payment processor.",
        },
        "recommended_with": ["p4p.payment.cash", "p4p.customer.status"],
    },
    "p4p.notify.email": {
        "category_id": "notifications",
        "title": {"da": "E-mail alarm", "sv": "E-postlarm", "tr": "E-posta uyarısı", "en": "Email alert"},
        "summary": {
            "da": "Send fallback-besked til operatoren, hvis en ordre eller hardwaresti kræver opmærksomhed.",
            "sv": "Skicka fallback-meddelande till operatören om en order eller hårdvaruväg kräver uppmärksamhet.",
            "tr": "Bir siparişin veya donanım yolunun dikkat gerektirmesi halinde operatöre yedek mesaj gönderin.",
            "en": "Send a fallback message to the operator if an order or hardware path needs attention.",
        },
        "recommended_with": ["p4p.order.print.backup", "p4p.order.alert.basic"],
    },
    "p4p.notify.sms": {
        "category_id": "notifications",
        "title": {"da": "SMS-alarm", "sv": "SMS-larm", "tr": "SMS uyarısı", "en": "SMS alert"},
        "summary": {
            "da": "Send en kort telefonbesked, når butikken vil have et hurtigere fallback end e-mail.",
            "sv": "Skicka ett kort telefonmeddelande när butiken vill ha ett snabbare fallback än e-post.",
            "tr": "Dükkân e-postadan daha hızlı bir yedek yol istediğinde kısa bir telefon mesajı gönderin.",
            "en": "Send a short phone message when the shop wants a faster fallback than email.",
        },
        "recommended_with": ["p4p.order.alert.basic", "p4p.notify.email"],
    },
    "p4p.trust.cvr-basic": {
        "category_id": "trust_identity",
        "title": {"da": "CVR og virksomhedsidentitet", "sv": "CVR och företagsidentitet", "tr": "CVR ve işletme kimliği", "en": "CVR and business identity"},
        "summary": {
            "da": "Peg mod senere dokumenterbar virksomhedsidentitet uden at gøre registret til autoriteten.",
            "sv": "Peka mot senare dokumenterbar företagsidentitet utan att göra registret till auktoritet.",
            "tr": "Kaydı otoriteye dönüştürmeden daha sonra belgelenebilir işletme kimliğine işaret edin.",
            "en": "Point toward later documentable business identity without making the registry the authority.",
        },
        "recommended_with": ["p4p.payment.cash"],
    },
    "p4p.payment.godpay-mock": {
        "category_id": "internal_debug",
        "title": {"da": "Mock-betaling", "sv": "Mock-betalning", "tr": "Sahte ödeme", "en": "Mock payment"},
        "summary": {
            "da": "Intern testbetaling til at bryde flowet sikkert før virkelige penge blandes ind.",
            "sv": "Intern testbetalning för att bryta flödet säkert innan riktiga pengar blandas in.",
            "tr": "Gerçek para devreye girmeden önce akışı güvenli biçimde bozmak için dahili test ödemesi.",
            "en": "Internal test payment for breaking the flow safely before real money enters the picture.",
        },
        "recommended_with": ["p4p.payment.cash"],
    },
    "p4p.payment.chaospay-mock": {
        "category_id": "internal_debug",
        "title": {"da": "Kaosbetaling", "sv": "Kaosbetalning", "tr": "Kaos ödemesi", "en": "Chaos payment"},
        "summary": {
            "da": "Intern grim-test for timeouts, dobbeltcallbacks og andre betalingsfejlscenarier.",
            "sv": "Internt grymtest för timeouts, dubbla callbacks och andra felscenarier för betalning.",
            "tr": "Zaman aşımı, yinelenen callback ve diğer ödeme hata senaryoları için dahili kötü durum testi.",
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


@lru_cache(maxsize=None)
def core_locale_pack(locale: str | None) -> dict[str, str]:
    normalized_locale = normalize_locale(locale)
    pack_path = I18N_CORE_ROOT / f"{normalized_locale}.json"
    if not pack_path.is_file():
        return {}
    try:
        payload = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, value in payload.items():
        key_text = str(key or "").strip()
        value_text = str(value or "").strip()
        if key_text and value_text:
            normalized[key_text] = value_text
    return normalized


def shell_text(locale: str | None, key: str) -> str:
    normalized_locale = normalize_locale(locale)
    for candidate in (normalized_locale, "en", DEFAULT_LOCALE):
        pack_value = core_locale_pack(candidate).get(key, "").strip()
        if pack_value:
            return pack_value
    return localized_text(SHELL_STRINGS.get(key), normalized_locale)


def localized_shell_strings(locale: str | None) -> dict[str, str]:
    ordered_keys: list[str] = list(SHELL_STRINGS)
    seen = set(ordered_keys)
    normalized_locale = normalize_locale(locale)
    for candidate in (normalized_locale, "en", DEFAULT_LOCALE):
        for key in core_locale_pack(candidate):
            if key in seen:
                continue
            seen.add(key)
            ordered_keys.append(key)
    return {
        key: shell_text(locale, key)
        for key in ordered_keys
    }


def github_blob_url(path: Path) -> str:
    relative = path.relative_to(P4P_ROOT).as_posix()
    return f"{GITHUB_BLOB_BASE_URL}/{relative}"


@dataclass(frozen=True)
class PublicCatalogUrls:
    pizza_site_url: str = "https://pizza4people.com/"
    protocols_site_url: str = "https://protocols4people.com/"


def _module_meta(manifest: ModuleManifest) -> dict[str, Any]:
    meta = dict(MODULE_META.get(manifest.module_id, {}))
    public_catalog = manifest.raw.get("public_catalog") or {}
    localized_title = localized_field_map(public_catalog.get("title"))
    localized_summary = localized_field_map(public_catalog.get("summary"))
    if not meta:
        meta["category_id"] = "internal_debug"
        meta["title"] = localized_title or {"da": manifest.module_id, "en": manifest.module_id}
        meta["summary"] = localized_summary or {"da": manifest.description, "en": manifest.description}
        meta["recommended_with"] = list(manifest.raw.get("requires") or [])
    else:
        if localized_title:
            meta["title"] = localized_title
        if localized_summary:
            meta["summary"] = localized_summary
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
    public_catalog = manifest.raw.get("public_catalog") or {}
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
        "function": localized_field_map(public_catalog.get("function")) or {"en": manifest.description},
        "data_access_summary": localized_field_map(public_catalog.get("data_access_summary"))
        or {"en": ", ".join(manifest.data_access) or "Not declared yet."},
        "trust_status": localized_field_map(public_catalog.get("trust_status")) or {"en": manifest.status},
        "operator_status": localized_field_map(public_catalog.get("operator_status")) or {"en": "not enabled"},
        "customer_notice": localized_field_map(public_catalog.get("customer_notice")) or {},
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
                "name": localized_field_map(provider.raw.get("name")) or {"en": provider.name},
                "description": localized_field_map(provider.raw.get("description")) or {"en": provider.description},
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
                "function": localized_text(entry["function"], normalized_locale),
                "data_access_summary": localized_text(entry["data_access_summary"], normalized_locale),
                "trust_status": localized_text(entry["trust_status"], normalized_locale),
                "operator_status": localized_text(entry["operator_status"], normalized_locale),
                "customer_notice": localized_text(entry["customer_notice"], normalized_locale),
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
        "supported_locales": catalog["supported_locales"],
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
        "supported": list(SUPPORTED_LOCALES),
        "choices": locale_choices(),
    }


__all__ = [
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "RTL_LOCALES",
    "PublicCatalogUrls",
    "locale_choices",
    "locale_direction",
    "localized_field_map",
    "localized_field_text",
    "localized_module_catalog",
    "localized_text",
    "normalize_locale",
    "operator_locale_payload",
    "public_module_catalog",
    "core_locale_pack",
    "shell_text",
]
