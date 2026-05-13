from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

P4P_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = (
    P4P_ROOT.parent
    if (P4P_ROOT.parent / "private").exists() or (P4P_ROOT.parent / "public").exists()
    else P4P_ROOT
)
ROOT = WORKSPACE_ROOT
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_core import load_reference_provider_catalog
from module_catalog import (
    PublicCatalogUrls,
    locale_direction,
    localized_field_map,
    localized_field_text,
    localized_text,
    normalize_locale,
    operator_locale_payload,
    public_module_catalog,
)

PRIVATE_SITE_DATA_PATH = ROOT / "private/data/p4p/site-data.json"
REPO_SITE_DATA_PATH = P4P_ROOT / "docs/site-data.json"
PRIVATE_SCREENSHOT_PACK_PATH = ROOT / "private/data/p4p/screenshot-pack.json"
REPO_SCREENSHOT_PACK_PATH = P4P_ROOT / "docs/screenshot-pack.json"
PUBLIC_ROOT = ROOT / "public/www/pizza4people"
PROTOCOLS_ROOT = ROOT / "public/www/protocols4people"
PRESS_ROOT = PUBLIC_ROOT / "press-kit"
MODULES_ROOT = P4P_ROOT / "modules"
TEMPLATE_ROOT = P4P_ROOT / "scripts/templates/public-site"
PUBLIC_CATALOG_URLS = PublicCatalogUrls()
PIZZA_SCREENSHOT_ROOT = PUBLIC_ROOT / "assets" / "screenshots"
PROTOCOLS_SCREENSHOT_ROOT = PROTOCOLS_ROOT / "assets" / "screenshots"

SCREENSHOT_STAGE_LABELS = {
    "next_gate": {
        "da": "Næste gate / pilot-node",
        "sv": "Nästa gate / pilot-node",
        "tr": "Sonraki aşama / pilot-node",
        "ar": "البوابة التالية / pilot-node",
        "ku": "Dergehê paş / pilot-node",
        "en": "Pilot-node / next gate",
    },
    "public_proof": {
        "da": "Offentligt proof",
        "sv": "Offentligt bevis",
        "tr": "Kamusal kanıt",
        "ar": "إثبات عام",
        "ku": "Proofa giştî",
        "en": "Public proof",
    },
}

PIZZA_HOME_UI = {
    "page_title": {
        "da": "Pizza4People - Åben protokol for direkte restaurantordrer",
        "sv": "Pizza4People - Öppet protokoll för direkta restaurangbeställningar",
        "tr": "Pizza4People - Doğrudan restoran siparişi için açık protokol",
        "ar": "Pizza4People - بروتوكول مفتوح للطلبات المباشرة من المطعم",
        "ku": "Pizza4People - Protokola vekirî ji bo fermanên rasterast ji restaurantê",
        "en": "Pizza4People - Open Protocol for Direct Restaurant Ordering",
    },
    "page_description": {
        "da": "Pizza4People er et offentligt open-protocol proof og en kontrolleret live-pilotsti for restaurant-discovery, direkte menuadgang, direkte ordreflow og node-ejet identitet.",
        "en": "Pizza4People is a public open-protocol proof and controlled live-pilot path for restaurant discovery, direct menu access, direct ordering, and node-owned identity.",
    },
    "og_description": {
        "da": "Et offentligt protokol-proof og en kontrolleret live-pilotsti for direkte restaurant-kunde-ordrer.",
        "en": "A public protocol proof and controlled live-pilot path for direct restaurant-customer ordering.",
    },
    "skip": {
        "da": "Spring til indhold",
        "sv": "Hoppa till innehåll",
        "tr": "İçeriğe geç",
        "ar": "انتقل إلى المحتوى",
        "ku": "Biçe naverokê",
        "en": "Skip to content",
    },
    "brand_home": {
        "da": "Pizza4People hjem",
        "sv": "Pizza4People hem",
        "tr": "Pizza4People ana sayfa",
        "ar": "الصفحة الرئيسية لـ Pizza4People",
        "ku": "Mala serî ya Pizza4People",
        "en": "Pizza4People home",
    },
    "nav_label": {
        "da": "Primær navigation",
        "sv": "Primär navigering",
        "tr": "Birincil gezinme",
        "ar": "التنقل الرئيسي",
        "ku": "Navîgasyona bingehîn",
        "en": "Primary navigation",
    },
    "nav_owner": {
        "da": "For pizzeriaer",
        "sv": "För pizzerior",
        "tr": "Pizzacılar için",
        "ar": "لأصحاب البيتزا",
        "ku": "Ji bo pizzeriayan",
        "en": "For pizzerias",
    },
    "nav_proof": {
        "da": "Proof",
        "sv": "Bevis",
        "tr": "Kanıt",
        "ar": "الإثبات",
        "ku": "Proof",
        "en": "Proof",
    },
    "nav_modules": {
        "da": "Moduler",
        "sv": "Moduler",
        "tr": "Modüller",
        "ar": "الوحدات",
        "ku": "Modul",
        "en": "Modules",
    },
    "nav_story": {
        "da": "Historien",
        "sv": "Berättelsen",
        "tr": "Hikâye",
        "ar": "القصة",
        "ku": "Çîrok",
        "en": "Story",
    },
    "nav_providers": {
        "da": "Providers",
        "sv": "Providers",
        "tr": "Sağlayıcılar",
        "ar": "المزوّدون",
        "ku": "Provider",
        "en": "Providers",
    },
    "nav_press": {
        "da": "Pressekit",
        "sv": "Presskit",
        "tr": "Basın kiti",
        "ar": "ملف صحفي",
        "ku": "Paketa çapemeniyê",
        "en": "Press kit",
    },
    "nav_contact": {
        "da": "Kontakt",
        "sv": "Kontakt",
        "tr": "İletişim",
        "ar": "اتصل",
        "ku": "Têkilî",
        "en": "Contact",
    },
    "locale_label": {
        "da": "Sprog",
        "sv": "Språk",
        "tr": "Dil",
        "ar": "اللغة",
        "ku": "Ziman",
        "en": "Language",
    },
    "hero_shape_label": {
        "da": "Nuværende form",
        "sv": "Nuvarande form",
        "tr": "Mevcut şekil",
        "ar": "الشكل الحالي",
        "ku": "Forma niha",
        "en": "Current shape",
    },
    "hero_tag_public": {
        "da": "Offentligt proof nu",
        "sv": "Offentligt bevis nu",
        "tr": "Şimdi kamusal kanıt",
        "ar": "إثبات عام الآن",
        "ku": "Niha proofa giştî",
        "en": "Public proof now",
    },
    "hero_tag_pilot": {
        "da": "Pickup-først pilot næste",
        "sv": "Pickup-först pilot nästa",
        "tr": "Sıradaki adım pickup-first pilot",
        "ar": "الخطوة التالية: تجريب pickup-first",
        "ku": "Pilotê pickup-first dergeha paş e",
        "en": "Pickup-first pilot next",
    },
    "hero_tag_not_marketplace": {
        "da": "Ikke en marketplace-app",
        "sv": "Inte en marketplace-app",
        "tr": "Marketplace uygulaması değil",
        "ar": "ليست تطبيق سوق",
        "ku": "Sepana marketplace neye",
        "en": "Not a marketplace app",
    },
    "hero_action_owner": {
        "da": "Hvis du driver et pizzeria",
        "sv": "Om du driver en pizzeria",
        "tr": "Bir pizzacı işletiyorsan",
        "ar": "إذا كنت تدير محل بيتزا",
        "ku": "Heke tu pizzeriyayek dimeşînî",
        "en": "If you run a pizzeria",
    },
    "hero_action_proof": {
        "da": "Se proofet",
        "sv": "Se beviset",
        "tr": "Kanıtı gör",
        "ar": "اعرض الإثبات",
        "ku": "Proofê bibîne",
        "en": "See the proof",
    },
    "hero_action_code": {
        "da": "Kode / protokol",
        "sv": "Kod / protokoll",
        "tr": "Kod / protokol",
        "ar": "الكود / البروتوكول",
        "ku": "Kod / protokol",
        "en": "Code / protocol",
    },
    "hero_more_routes": {
        "da": "Flere ruter:",
        "sv": "Fler vägar:",
        "tr": "Daha fazla rota:",
        "ar": "مسارات أخرى:",
        "ku": "Rêyên din:",
        "en": "More routes:",
    },
    "hero_route_story": {
        "da": "60-sekunders version",
        "sv": "60-sekundersversion",
        "tr": "60 saniyelik sürüm",
        "ar": "نسخة 60 ثانية",
        "ku": "Versiyona 60 çirke",
        "en": "60-second version",
    },
    "hero_route_proof": {
        "da": "Proof note",
        "sv": "Bevisnot",
        "tr": "Kanıt notu",
        "ar": "مذكرة الإثبات",
        "ku": "Noteya proofê",
        "en": "Proof note",
    },
    "hero_route_broader": {
        "da": "Bredere vision",
        "sv": "Bredare vision",
        "tr": "Daha geniş vizyon",
        "ar": "الرؤية الأوسع",
        "ku": "Dîtina firehtir",
        "en": "Broader vision",
    },
    "hero_route_press_da": {
        "da": "Pressekit DK",
        "sv": "Presskit DK",
        "tr": "Basın kiti DK",
        "ar": "ملف صحفي DK",
        "ku": "Paketa çapemeniyê DK",
        "en": "Press kit DK",
    },
    "hero_route_press_en": {
        "da": "Pressekit EN",
        "sv": "Presskit EN",
        "tr": "Basın kiti EN",
        "ar": "ملف صحفي EN",
        "ku": "Paketa çapemeniyê EN",
        "en": "Press kit EN",
    },
    "proof_figure_alt": {
        "da": "Diagram der viser klient-discovery gennem registries og direkte menu-/ordreflow til restaurantnoden.",
        "en": "Diagram showing client discovery through registries and direct menu/order flow to the restaurant node.",
    },
    "proof_figure_caption": {
        "da": "Discovery kan gå gennem registries. Menu og ordrer går direkte til restaurantnoden.",
        "en": "Discovery can go through registries. Menu and orders go directly to the restaurant node.",
    },
    "source_label": {
        "da": "Kilde",
        "sv": "Källa",
        "tr": "Kaynak",
        "ar": "المصدر",
        "ku": "Çavkanî",
        "en": "Source",
    },
    "owner_kicker": {
        "da": "Hvis du driver et pizzeria",
        "sv": "Om du driver en pizzeria",
        "tr": "Bir pizzacı işletiyorsan",
        "ar": "إذا كنت تدير محل بيتزا",
        "ku": "Heke tu pizzeriyayek dimeşînî",
        "en": "If You Run A Pizzeria",
    },
    "owner_title": {
        "da": "Det her er den enkle version.",
        "sv": "Det här är den enkla versionen.",
        "tr": "Bu basit sürüm.",
        "ar": "هذه هي النسخة البسيطة.",
        "ku": "Ev versiyona hêsan e.",
        "en": "This is the simple version.",
    },
    "owner_body": {
        "da": "Pizza4People prøver at holde den grundlæggende digitale forbindelse i restaurantens hænder. Den første live-form er bevidst lille: kontrollerede pickup-ordrer, direkte menukontrol og enkel betaling ved afhentning før noget bredere.",
        "en": "Pizza4People is trying to keep the basic digital connection in the restaurant's hands. The first live shape is intentionally small: controlled pickup orders, direct menu control, and simple payment at pickup before anything broader.",
    },
    "modules_kicker": {
        "da": "Hvordan delene passer sammen",
        "sv": "Hur delarna hänger ihop",
        "tr": "Parçalar nasıl birleşiyor",
        "ar": "كيف تتماسك الأجزاء",
        "ku": "Parçe çawa li hev tên",
        "en": "How The Pieces Fit",
    },
    "modules_title": {
        "da": "Start med det der betyder noget for butikken, og åbn først detaljerne hvis du har brug for dem.",
        "en": "Start with what matters to the shop, then open the details only if needed.",
    },
    "modules_body_1": {
        "da": "Listen nedenfor er bevidst skrevet til første forståelse, ikke til manifest-læsning. Hver boks åbner først ind i de tekniske links når du har brug for dem.",
        "en": "The list below is intentionally written for first understanding, not for manifest reading. Each box opens into the technical links only when you need them.",
    },
    "modules_body_2": {
        "da": "Betaling holdes bevidst smal. P4P holder ikke penge, behandler ikke betalinger, opbevarer ikke betalingscredentials, afregner ikke penge og er ikke merchant of record.",
        "en": "Payment stays narrow on purpose. P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.",
    },
    "modules_body_3": {
        "da": "Hvis moduler ikke giver mening endnu, så start med den enkle guide inde i modulsiderne.",
        "en": "If modules make no sense yet, start with the simple guide inside the module pages.",
    },
    "modules_body_4": {
        "da": "Hvis du vil have hele den offentlige læsesti for modul-laget, så åbn de dedikerede modulsider.",
        "en": "If you want the full public reading path for the module layer, open the dedicated module pages.",
    },
    "modules_body_5": {
        "da": "Det nuværende offentlige katalog peger på {provider_count} læsbar(e) provider-identitetsside som et separat menneskeligt lag: åbn provider-kataloget.",
        "en": "The current public catalog points to {provider_count} readable provider identity page as a separate human layer: open provider catalog.",
    },
    "modules_link_new_here": {
        "da": "modulsider",
        "en": "module pages",
    },
    "modules_link_catalog": {
        "da": "modulsider",
        "en": "module pages",
    },
    "modules_link_providers": {
        "da": "åbn provider-katalog",
        "en": "open provider catalog",
    },
    "story_kicker": {
        "da": "Historien",
        "sv": "Berättelsen",
        "tr": "Hikâye",
        "ar": "القصة",
        "ku": "Çîrok",
        "en": "The story",
    },
    "brief_label": {
        "da": "I én sætning",
        "sv": "I en mening",
        "tr": "Tek cümlede",
        "ar": "في جملة واحدة",
        "ku": "Di hevokekê de",
        "en": "In one sentence",
    },
    "plain_kicker": {
        "da": "Det du allerede kan se",
        "sv": "Det du redan kan se",
        "tr": "Şimdiden görülebilen şeyler",
        "ar": "ما يمكنك رؤيته بالفعل",
        "ku": "Tiştên ku tu jixwe dikarî bibînî",
        "en": "What you can see already",
    },
    "plain_title": {
        "da": "Fire synlige ting, uden at du behøver kende protokollen.",
        "en": "Four visible things, no protocol knowledge required.",
    },
    "problem_kicker": {
        "da": "Problemet",
        "sv": "Problemet",
        "tr": "Sorun",
        "ar": "المشكلة",
        "ku": "Pirsgirêk",
        "en": "Problem",
    },
    "proof_kicker": {
        "da": "Proof",
        "sv": "Bevis",
        "tr": "Kanıt",
        "ar": "الإثبات",
        "ku": "Proof",
        "en": "Proof",
    },
    "proof_title": {
        "da": "Det offentlige proof viser én smal løkke.",
        "en": "The public proof demonstrates one narrow loop.",
    },
    "takeaway_kicker": {
        "da": "Presse-takeaway",
        "sv": "Press takeaway",
        "tr": "Basın özeti",
        "ar": "خلاصة صحفية",
        "ku": "Xulasaya çapemeniyê",
        "en": "Press takeaway",
    },
    "proves_kicker": {
        "da": "Det her beviser",
        "sv": "Det här visar",
        "tr": "Bunun gösterdiği",
        "ar": "ما يثبته هذا",
        "ku": "Ev çi diprove dike",
        "en": "What this proves",
    },
    "not_proves_kicker": {
        "da": "Det her beviser ikke",
        "sv": "Det här visar inte",
        "tr": "Bunun göstermediği",
        "ar": "ما لا يثبته هذا",
        "ku": "Ev ne diprove dike",
        "en": "What this does not prove",
    },
    "trust_kicker": {
        "da": "Retning for tillid",
        "sv": "Tillitens riktning",
        "tr": "Güven yönü",
        "ar": "اتجاه الثقة",
        "ku": "Rêya baweriyê",
        "en": "Trust direction",
    },
    "gate_kicker": {
        "da": "Proof-gate",
        "sv": "Bevis-gate",
        "tr": "Kanıt kapısı",
        "ar": "بوابة الإثبات",
        "ku": "Dergehê proofê",
        "en": "Proof gate",
    },
    "roadmap_kicker": {
        "da": "Roadmap",
        "sv": "Roadmap",
        "tr": "Yol haritası",
        "ar": "خارطة الطريق",
        "ku": "Roadmap",
        "en": "Roadmap",
    },
    "roadmap_title": {
        "da": "Fra offentligt protokol-proof til kontrolleret live-pilot.",
        "en": "From public protocol proof to controlled live pilot.",
    },
    "pilot_kicker": {
        "da": "Næste gate",
        "sv": "Nästa gate",
        "tr": "Sonraki aşama",
        "ar": "البوابة التالية",
        "ku": "Dergehê paş",
        "en": "Next gate",
    },
    "pilot_title": {
        "da": "Det her er det restauranten vil styre lokalt i den kontrollerede pilot.",
        "en": "What the restaurant will control locally in the controlled pilot.",
    },
    "pilot_lede": {
        "da": "De her flader er virkelige og allerede bygget, men de hører til pilot-node-sporet efter det nuværende offentlige proof. De er ikke selve den smalle v0.1-proofløkke.",
        "en": "These surfaces are real and already built, but they belong to the pilot-node path after the current public proof. They are not the narrow v0.1 proof loop itself.",
    },
    "contact_kicker": {
        "da": "Kontakt",
        "sv": "Kontakt",
        "tr": "İletişim",
        "ar": "اتصل",
        "ku": "Têkilî",
        "en": "Contact",
    },
    "contact_title": {
        "da": "Det her er et offentligt protokol-proof og en kontrolleret pilotsti, ikke en kommerciel marketplace-lancering.",
        "en": "This is a public protocol proof and controlled pilot path, not a commercial marketplace launch.",
    },
    "contact_line": {
        "da": "Til teknisk review, protokolspørgsmål eller pressekontekst:",
        "en": "For technical review, protocol questions, or press context:",
    },
    "contact_source_label": {
        "da": "Kilde- og protokolarbejde:",
        "en": "Source and protocol work:",
    },
    "contact_broader_label": {
        "da": "Bredere protokol-familieretning:",
        "en": "Broader protocol-family direction:",
    },
    "contact_fine_print": {
        "da": "Pizza4People er det konkrete restaurant-ordering proof. Protocols4People er den bredere protokol-familieretning.",
        "en": "Pizza4People is the concrete restaurant-ordering proof. Protocols4People is the broader protocol-family direction.",
    },
}

PIZZA_PRESS_UI = {
    "download_da": {
        "da": "Download dansk PDF",
        "sv": "Ladda ner dansk PDF",
        "tr": "Danca PDF indir",
        "ar": "نزّل PDF الدنماركية",
        "ku": "PDF-a Danîmarkî daxîne",
        "en": "Download Danish PDF",
    },
    "download_en": {
        "da": "Download English PDF",
        "sv": "Ladda ner engelsk PDF",
        "tr": "İngilizce PDF indir",
        "ar": "نزّل PDF الإنجليزية",
        "ku": "PDF-a Îngilîzî daxîne",
        "en": "Download English PDF",
    },
    "site_label": {
        "da": "pizza4people.com",
        "en": "pizza4people.com",
    },
    "provider_catalog": {
        "da": "provider-katalog",
        "sv": "provider-katalog",
        "tr": "sağlayıcı kataloğu",
        "ar": "كتالوج المزوّدين",
        "ku": "kataloga provideran",
        "en": "provider catalog",
    },
    "repo_label": {
        "da": "github.com/DennisHedegreen/p4p",
        "en": "github.com/DennisHedegreen/p4p",
    },
    "diagram_core_flow": {
        "da": "Kerneflow",
        "sv": "Kärnflöde",
        "tr": "Çekirdek akış",
        "ar": "التدفق الأساسي",
        "ku": "Herikîna bingehîn",
        "en": "Core flow",
    },
    "client_label": {
        "da": "Klient",
        "sv": "Klient",
        "tr": "İstemci",
        "ar": "العميل",
        "ku": "Klîent",
        "en": "Client",
    },
    "registry_label": {
        "da": "Registry",
        "sv": "Registry",
        "tr": "Registry",
        "ar": "السجل",
        "ku": "Registry",
        "en": "Registry",
    },
    "pilot_topology": {
        "da": "Pilot-topologi",
        "sv": "Pilot-topologi",
        "tr": "Pilot topolojisi",
        "ar": "بنية الطيار",
        "ku": "Topolojiya pilotê",
        "en": "Pilot topology",
    },
    "primary_registry": {
        "da": "Primær registry",
        "sv": "Primär registry",
        "tr": "Birincil registry",
        "ar": "السجل الأساسي",
        "ku": "Registry-a bingehîn",
        "en": "Primary registry",
    },
    "backup_registry": {
        "da": "Backup registry",
        "sv": "Backup registry",
        "tr": "Yedek registry",
        "ar": "السجل الاحتياطي",
        "ku": "Registry-a paşve",
        "en": "Backup registry",
    },
    "minimum_api": {
        "da": "Minimum node-API",
        "sv": "Minsta node-API",
        "tr": "Minimum node API",
        "ar": "أدنى API للعقدة",
        "ku": "API-ya nodeyê ya herî kêm",
        "en": "Minimum node API",
    },
    "checker": {
        "da": "Checker",
        "sv": "Checker",
        "tr": "Denetleyici",
        "ar": "أداة التحقق",
        "ku": "Checker",
        "en": "Checker",
    },
    "contact_card": {
        "da": "Kontakt",
        "sv": "Kontakt",
        "tr": "İletişim",
        "ar": "اتصل",
        "ku": "Têkilî",
        "en": "Contact",
    },
    "links_card": {
        "da": "Links",
        "sv": "Länkar",
        "tr": "Bağlantılar",
        "ar": "روابط",
        "ku": "Girêdan",
        "en": "Links",
    },
    "source_link": {
        "da": "Just Eat Takeaway.com-kilde",
        "sv": "Just Eat Takeaway.com-källa",
        "tr": "Just Eat Takeaway.com kaynağı",
        "ar": "مصدر Just Eat Takeaway.com",
        "ku": "Çavkaniya Just Eat Takeaway.com",
        "en": "Just Eat Takeaway.com source",
    },
}

PIZZA_MODULES_UI = {
    "nav_home": {"da": "Hjem", "en": "Home"},
    "nav_modules": {"da": "Moduler", "en": "Modules"},
    "nav_providers": {"da": "Providers", "en": "Providers"},
    "nav_press_dk": {"da": "Pressekit DK", "en": "Press kit DK"},
    "nav_press_en": {"da": "Pressekit EN", "en": "Press kit EN"},
    "nav_proof": {"da": "Proof note", "en": "Proof note"},
    "nav_code": {"da": "Kode / protokol", "en": "Code / protocol"},
    "page_title_modules": {
        "da": "Pizza4People Modulsider",
        "en": "Pizza4People Module Pages",
    },
    "page_description_modules": {
        "da": "Menneskelige modulsider for den nuværende Pizza4People-stack før rå manifests og GitHub-docs.",
        "en": "Plain-language module pages for the current Pizza4People stack, before raw manifests and GitHub docs.",
    },
    "page_description_modules_og": {
        "da": "Et læsbart modul-katalog for den nuværende Pizza4People proof-stack.",
        "en": "A readable module catalog for the current Pizza4People proof stack.",
    },
    "hero_eyebrow_modules": {
        "da": "Modulsider / menneskelig læsning af stacken",
        "en": "Module pages / plain-language stack reading",
    },
    "hero_title_modules": {
        "da": "Hvilket modul betyder noget først?",
        "en": "Which module matters first?",
    },
    "hero_lede_modules": {
        "da": "Det her er det menneskelige modul-katalog for det nuværende Pizza4People proof. Start her hvis du vil forstå hvad kunden ser, hvad butikken styrer, og hvor betalings- eller tillidsgrænserne ligger før du åbner rå manifests.",
        "en": "This is the human module catalog for the current Pizza4People proof. Start here if you want to understand what the customer sees, what the shop controls, and where payment or trust boundaries sit before opening raw manifests.",
    },
    "hero_action_back_home": {"da": "Tilbage til forsiden", "en": "Back to homepage"},
    "hero_action_new_here": {"da": "Ny her?", "en": "New here?"},
    "hero_action_provider_pages": {"da": "Providersider", "en": "Provider pages"},
    "brief_label_scope": {"da": "Nuværende scope", "en": "Current scope"},
    "brief_line_modules": {
        "da": "{module_count} modulsider på tværs af {provider_count} delt provider-lag.",
        "en": "{module_count} module pages across {provider_count} shared provider layer.",
    },
    "brief_body_modules": {
        "da": "Læsbarhed først. Rå manifests og GitHub-referencer kun når du har brug for udviklerlaget.",
        "en": "Readable first. Raw manifests and GitHub references only when you need the developer-facing view.",
    },
    "new_here_kicker": {"da": "Ny her?", "en": "New here?"},
    "new_here_title_modules": {
        "da": "Start med den enkle idé, ikke de rå ids.",
        "en": "Start with the simple idea, not the raw ids.",
    },
    "new_here_body_modules_1": {
        "da": "P4P-kernen er vejen. Moduler er valgfrie værktøjer rundt om vejen.",
        "en": "P4P core is the road. Modules are optional tools around the road.",
    },
    "new_here_body_modules_2": {
        "da": "Gode eksempler er menuer, køkkenskærme, pickup boards, alarmer og betalingsadaptere. Dårlige eksempler er registryet selv eller det direkte node-order-endpoint selv.",
        "en": "Good examples are menus, kitchen screens, pickup boards, alerts, and payment adapters. Bad examples are the registry itself or the direct node order endpoint itself.",
    },
    "start_kicker": {"da": "Start her", "en": "Start here"},
    "start_title_modules": {
        "da": "Tre praktiske veje ind i modul-stacken.",
        "en": "Three practical ways into the module stack.",
    },
    "catalog_kicker": {"da": "Katalog", "en": "Catalog"},
    "catalog_title_modules": {
        "da": "Åbn den nuværende stack efter rolle, ikke rå id.",
        "en": "Open the current stack by role, not by raw id.",
    },
    "catalog_body_modules_1": {
        "da": "Den grupperede liste nedenfor er stadig den samme smalle proof-fortælling. Den er bare arrangeret i den rækkefølge en normal læser kan bruge: kundeflader først, derefter butiksværktøjer, derefter betalings-/tillidskanter, derefter interne tests.",
        "en": "The grouped list below is still the same narrow proof story. It is just arranged in the order a normal reader can use: customer surfaces first, then shop tools, then payment/trust edges, then internal tests.",
    },
    "catalog_body_modules_2": {
        "da": "Hvis du vil have det præcise tekniske sprog, er GitHub stadig source of truth. Den her side er det offentlige menneskelige lag oven på.",
        "en": "If you want the exact technical language, GitHub remains the source of truth. This page is the public human layer above it.",
    },
    "current_module_pages": {"da": "Nuværende modulsider", "en": "Current module pages"},
    "groups_title_modules": {
        "da": "Læs de nuværende moduler som værktøjer, og åbn kun detaljerne når det er nødvendigt.",
        "en": "Read the current modules as tools, then open the details only when needed.",
    },
    "contact_title_modules": {
        "da": "Spørgsmål om modul-laget eller den nuværende proof-grænse?",
        "en": "Questions about the module layer or the current proof boundary?",
    },
    "contact_body_modules_1": {
        "da": "Spørgsmål om modulbetydning, provider-ejerskab eller live-pilotgrænsen:",
        "en": "Questions about module meaning, provider ownership, or the live-pilot boundary:",
    },
    "contact_body_modules_2": {
        "da": "Offentlig proof-fordør:",
        "en": "Public proof front door:",
    },
    "contact_body_modules_3": {
        "da": "Bredere protokol-familieretning:",
        "en": "Broader protocol-family direction:",
    },
    "footer_modules_left": {"da": "Pizza4People / Modulsider", "en": "Pizza4People / Module Pages"},
    "footer_next_gate": {
        "da": "Offentligt protokol-proof. Kontrolleret live-pilot næste.",
        "en": "Public protocol proof. Controlled live pilot next.",
    },
    "toggle_hint": {"da": "Klik for detaljer", "en": "Click for details"},
    "owner_prefix": {"da": "For et pizzeria:", "en": "For a pizzeria:"},
    "touches": {"da": "Berører", "en": "Touches"},
    "does_not_own": {"da": "Ejer ikke", "en": "Does not own"},
    "current_state": {"da": "Nuværende tilstand", "en": "Current state"},
    "technical_id": {"da": "Teknisk id", "en": "Technical id"},
    "more_info": {"da": "Mere info:", "en": "More info:"},
    "open_full_module_page": {"da": "Åbn fuld modulside", "en": "Open full module page"},
    "open_provider_page": {"da": "Åbn providerside", "en": "Open provider page"},
    "open_manifest": {"da": "Åbn manifest", "en": "Open manifest"},
    "reader_card_1_title": {"da": "Hvis du driver en butik", "en": "If you run a shop"},
    "reader_card_1_body": {
        "da": "Start med kundemenuen, butikskataloget og den enkle pay-at-pickup lane. Læs moduler som valgfrie værktøjer rundt om order flow, ikke som protokolteori.",
        "en": "Start with the customer menu, the shop-side catalog, and the simple pay-at-pickup lane. Read modules as optional tools around the order flow, not as protocol theory.",
    },
    "reader_card_2_title": {"da": "Hvis du bygger software", "en": "If you build software"},
    "reader_card_2_body": {
        "da": "Start med den dum-sikre modul-forklaring, derefter community builder-guiden, og så én smal hardware-lane så du kan se hvad et smalt modul ligner før de tungere kontrakter.",
        "en": "Start with the dumb-safe module explanation, then the community builder guide, then one small hardware lane so you can see what a narrow module looks like before reading the heavier contracts.",
    },
    "reader_card_3_title": {"da": "Hvis du er skeptisk", "en": "If you are skeptical"},
    "reader_card_3_body": {
        "da": "Start med review-pakken, undersøg derefter payment boundary og de to nye pilot hardware lanes. Det nyttige spørgsmål er om kernen bliver lille mens ekstra lagene bliver ærlige og valgfrie.",
        "en": "Start with the review packet, then inspect the payment boundary and the two new pilot hardware lanes. The useful question is whether the core stays small while the extras stay honest and optional.",
    },
    "open_customer_menu_page": {"da": "Åbn kundemenuside", "en": "Open customer menu page"},
    "open_shop_catalog_page": {"da": "Åbn butikskatalog-side", "en": "Open shop catalog page"},
    "open_simple_payment_page": {"da": "Åbn enkel betalingsside", "en": "Open simple payment page"},
    "open_simple_module_guide": {"da": "Åbn enkel modulguide", "en": "Open simple module guide"},
    "open_builder_guide": {"da": "Åbn builder-guide", "en": "Open builder guide"},
    "open_backup_print_example": {"da": "Åbn backup-print eksempel", "en": "Open backup-print example"},
    "open_review_packet": {"da": "Åbn review-pakke", "en": "Open review packet"},
    "open_payment_boundary_page": {"da": "Åbn payment boundary-side", "en": "Open payment boundary page"},
    "open_pickup_board_page": {"da": "Åbn pickup-board-side", "en": "Open pickup-board page"},
    "route_card_1_title": {"da": "Start med kundesiden", "en": "Start with the customer side"},
    "route_card_1_body": {
        "da": "Hvis du først vil forstå det synlige offentlige proof, så start med menuen og statussiderne kunden faktisk ser.",
        "en": "If you want to understand the visible public proof first, start with the menu and status pages the customer actually sees.",
    },
    "route_card_2_title": {"da": "Læs derefter butiksværktøjerne", "en": "Then read the shop-side tools"},
    "route_card_2_body": {
        "da": "Hvis du vil forstå hvad et pizzeria faktisk kontrollerer, så hop til katalog-editoren og køkkenkøen før de dybere tekniske lag.",
        "en": "If you want to understand what a pizzeria actually controls, jump to the catalog editor and kitchen queue before the deeper technical layers.",
    },
    "route_card_3_title": {"da": "Hold grænsen i syne", "en": "Keep the boundary in view"},
    "route_card_3_body": {
        "da": "Hvis du vil have den praktiske kant af det nuværende proof, så læs den enkle payment path og providersiden sammen.",
        "en": "If you want the practical edge of the current proof, read the simple payment path and the provider page together.",
    },
    "simple_online_menu": {"da": "Enkel online-menu", "en": "Simple online menu"},
    "order_status_page": {"da": "Ordrestatus-side", "en": "Order status page"},
    "edit_menu_and_prices": {"da": "Rediger menu og priser", "en": "Edit menu and prices"},
    "kitchen_order_queue": {"da": "Køkken-ordrekø", "en": "Kitchen order queue"},
    "pay_at_pickup_cash": {"da": "Betal ved afhentning / kontant", "en": "Pay at pickup / cash"},
    "current_provider_page": {"da": "Nuværende providerside", "en": "Current provider page"},
}

PIZZA_PROVIDER_UI = {
    "page_title_providers": {"da": "Pizza4People Providersider", "en": "Pizza4People Provider Pages"},
    "page_description_providers": {
        "da": "Hvem der står bag de nuværende Pizza4People-værktøjer, i menneskeligt sprog før rå manifests.",
        "en": "Who stands behind the current Pizza4People tools, in plain language before raw manifests.",
    },
    "page_description_providers_og": {
        "da": "Menneskelige providersider for de nuværende Pizza4People-værktøjer.",
        "en": "Plain-language provider pages for the current Pizza4People tools.",
    },
    "hero_eyebrow_providers": {"da": "Nuværende værktøjskilde / menneskelige providersider", "en": "Current tool source / plain-language provider pages"},
    "hero_title_providers": {
        "da": "Hvem står bag de nuværende Pizza4People-værktøjer?",
        "en": "Who stands behind the current Pizza4People tools?",
    },
    "hero_lede_providers": {
        "da": "Lige nu peger det offentlige Pizza4People-site på ét delt reference-provider-lag. Det betyder at den nuværende menu-, ordre- og operator-flade kommer fra én in-repo reference-stack. Den her side forklarer det i menneskeligt sprog før rå manifests og GitHub-docs.",
        "en": "Right now the public Pizza4People site points to one shared reference provider. That means the current menu, order, and operator pages come from one in-repo reference stack. This page explains that in plain language before raw manifests and GitHub docs.",
    },
    "hero_action_module_catalog": {"da": "Modul-katalog", "en": "Module catalog"},
    "hero_action_broader": {"da": "Bredere vision", "en": "Broader vision"},
    "brief_label_reality": {"da": "Nuværende virkelighed", "en": "Current reality"},
    "brief_line_providers": {
        "da": "{provider_count} delt providerside i det nuværende offentlige site.",
        "en": "{provider_count} shared provider page in the current public site.",
    },
    "brief_body_providers": {
        "da": "Ikke et bredt vendor-marked endnu. Én delt reference-stack med den samme smalle proof-grænse som resten af sitet.",
        "en": "Not a broad vendor marketplace yet. One shared reference stack, with the same narrow proof boundary as the rest of the site.",
    },
    "providers_kicker": {"da": "Providers", "en": "Providers"},
    "providers_title": {"da": "Hvad en providerside er til for.", "en": "What a provider page is for."},
    "providers_body_1": {
        "da": "En modulside forklarer hvad et værktøj gør. En providerside forklarer hvem der udgiver den værktøjsfamilie lige nu. Det er det menneskelige læselag ved siden af de rå manifests.",
        "en": "A module page explains what a tool does. A provider page explains who publishes that tool family right now. It is the human reading layer beside the raw manifests.",
    },
    "providers_body_2": {
        "da": "Det certificerer ingen. Det gør ikke registryet til en marketplace-operatør. Det gør bare den nuværende kilde til værktøjerne læsbar for en butiksejer, journalist eller reviewer.",
        "en": "This does not certify anyone. It does not turn the registry into a marketplace operator. It simply makes the current source of the tools readable for a shop owner, journalist, or reviewer.",
    },
    "current_catalog": {"da": "Nuværende katalog", "en": "Current catalog"},
    "provider_cards_title": {
        "da": "Den nuværende delte provider bag de offentlige værktøjer.",
        "en": "The current shared provider behind the public tools.",
    },
    "contact_title_providers": {
        "da": "Spørgsmål om hvem der står bag den nuværende stack?",
        "en": "Questions about who stands behind the current stack?",
    },
    "contact_body_providers_1": {
        "da": "Spørgsmål om provider-identitet, modulejerskab eller den nuværende offentlige værktøjskilde:",
        "en": "Questions about provider identity, module ownership, or the current public tool source:",
    },
    "contact_body_providers_2": {"da": "Kilde- og protokolarbejde:", "en": "Source and protocol work:"},
    "contact_body_providers_3": {"da": "Offentlig proof-fordør:", "en": "Public proof front door:"},
    "footer_providers_left": {"da": "Pizza4People / Providersider", "en": "Pizza4People / Provider Pages"},
    "current_tool_source": {"da": "Nuværende værktøjskilde", "en": "Current tool source"},
    "what_this_is_not": {"da": "Hvad det ikke er", "en": "What this is not"},
    "module_count_label": {"da": "Modulantal", "en": "Module count"},
    "good_first_pages": {"da": "Gode første sider for en butik", "en": "Good first pages for a shop"},
    "open_full_provider_page": {"da": "Åbn fuld providerside", "en": "Open full provider page"},
    "github_provider_reference": {"da": "GitHub provider-reference", "en": "GitHub provider reference"},
    "open_provider_manifest": {"da": "Åbn provider-manifest", "en": "Open provider manifest"},
    "provider_title_suffix": {"da": "Pizza4People Providerside", "en": "Pizza4People Provider Page"},
    "hero_action_back_provider_catalog": {"da": "Tilbage til provider-katalog", "en": "Back to provider catalog"},
    "brief_label_for_shop": {"da": "For et pizzeria", "en": "For a pizzeria"},
    "what_it_is": {"da": "Hvad det er", "en": "What it is"},
    "what_this_covers_right_now": {"da": "Hvad det dækker lige nu", "en": "What this covers right now"},
    "for_shop_strong": {"da": "For en butik:", "en": "For a shop:"},
    "not_yet": {"da": "Ikke endnu:", "en": "Not yet:"},
    "current_modules": {"da": "Nuværende moduler", "en": "Current modules"},
    "provider_modules_title": {"da": "Hvad den her provider udgiver lige nu.", "en": "What this provider publishes right now."},
    "technical_record": {"da": "Teknisk registrering", "en": "Technical record"},
    "status": {"da": "Status", "en": "Status"},
    "supported_lanes": {"da": "Understøttede lanes", "en": "Supported lanes"},
    "website": {"da": "Website", "en": "Website"},
    "provider_readable_surface": {
        "da": "Den lokale side her er P4P’s læsbare flade. GitHub-referencen og det rå manifest er stadig det udviklervendte kildemateriale.",
        "en": "This local page is the P4P-readable surface. The GitHub reference and raw manifest remain the developer-facing source material.",
    },
    "back_to_provider_catalog": {"da": "Tilbage til provider-katalog", "en": "Back to provider catalog"},
    "open_raw_provider_manifest": {"da": "Åbn rå provider-manifest", "en": "Open raw provider manifest"},
    "contact_title_provider_detail": {
        "da": "Spørgsmål om hvem der står bag de her værktøjer?",
        "en": "Questions about who stands behind these tools?",
    },
    "contact_body_provider_detail_1": {
        "da": "Spørgsmål om den her providerside, modulejerskab eller live-pilotgrænsen:",
        "en": "Questions about this provider page, module ownership, or the live-pilot boundary:",
    },
    "provider_focus_modules_suffix": {"da": " ", "en": " "},
}


def resolve_first_existing_path(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    joined = ", ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"Could not resolve required path from: {joined}")


SITE_DATA_PATH = resolve_first_existing_path(PRIVATE_SITE_DATA_PATH, REPO_SITE_DATA_PATH)
SCREENSHOT_PACK_PATH = resolve_first_existing_path(PRIVATE_SCREENSHOT_PACK_PATH, REPO_SCREENSHOT_PACK_PATH)
SCREENSHOT_PACK_BASE_ROOT = ROOT if SCREENSHOT_PACK_PATH == PRIVATE_SCREENSHOT_PACK_PATH else P4P_ROOT


def load_screenshot_pack() -> dict[str, object]:
    return json.loads(SCREENSHOT_PACK_PATH.read_text(encoding="utf-8"))


def public_localized_text(texts: dict[str, str] | None, locale: str) -> str:
    if not texts:
        return ""
    normalized_locale = str(locale or "").strip().lower()
    for candidate in (normalized_locale, "en", "da"):
        value = str(texts.get(candidate, "")).strip()
        if value:
            return value
    return next((str(value).strip() for value in texts.values() if str(value).strip()), "")


def public_field_text(value: object, locale: str = "en") -> str:
    if isinstance(value, dict):
        normalized = {
            ("da" if str(key).strip().lower() == "dk" else str(key).strip().lower()): str(text)
            for key, text in value.items()
        }
        return public_localized_text(normalized, locale)
    return str(value or "").strip()


def public_ui_text(table: dict[str, dict[str, str]], key: str, locale: str) -> str:
    return public_localized_text(table.get(key, {}), locale)


def public_locale_choices() -> list[dict[str, str]]:
    return operator_locale_payload("da").get("choices", [])


def locale_file_href(*, kind: str, locale: str) -> str:
    if kind == "press":
        return "./" if locale == "da" else f"./{locale}.html"
    return "./" if locale == "en" else f"./{locale}.html"


def localized_static_page_href(prefix: str, locale: str, *, default_locale: str) -> str:
    return prefix if locale == default_locale else f"{prefix}{locale}.html"


def localized_detail_page_href(prefix: str, item_id: str, locale: str, *, default_locale: str = "en") -> str:
    return f"{prefix}{item_id}/" if locale == default_locale else f"{prefix}{item_id}/{locale}.html"


def render_locale_switcher(*, kind: str, locale: str, ui: dict[str, dict[str, str]]) -> str:
    label = public_ui_text(ui, "locale_label", locale) or "Language"
    links: list[str] = []
    for choice in public_locale_choices():
        choice_locale = str(choice.get("id", "")).strip()
        if not choice_locale:
            continue
        href = locale_file_href(kind=kind, locale=choice_locale)
        active_attr = ' aria-current="page"' if choice_locale == locale else ""
        class_name = "locale-link active" if choice_locale == locale else "locale-link"
        link_label = str(choice.get("native_label") or choice.get("label") or choice_locale)
        links.append(f'<a class="{class_name}" href="{escape(href)}"{active_attr}>{escape(link_label)}</a>')
    return (
        f'<div class="locale-switcher" aria-label="{escape(label)}">'
        f'<span class="locale-switcher-label">{escape(label)}</span>'
        f'<div class="locale-switcher-links">{"".join(links)}</div>'
        "</div>"
    )


def render_custom_locale_switcher(*, locale: str, label: str, href_for_locale) -> str:
    links: list[str] = []
    for choice in public_locale_choices():
        choice_locale = str(choice.get("id", "")).strip()
        if not choice_locale:
            continue
        href = href_for_locale(choice_locale)
        active_attr = ' aria-current="page"' if choice_locale == locale else ""
        class_name = "locale-link active" if choice_locale == locale else "locale-link"
        link_label = str(choice.get("native_label") or choice.get("label") or choice_locale)
        links.append(f'<a class="{class_name}" href="{escape(href)}"{active_attr}>{escape(link_label)}</a>')
    return (
        f'<div class="locale-switcher" aria-label="{escape(label)}">'
        f'<span class="locale-switcher-label">{escape(label)}</span>'
        f'<div class="locale-switcher-links">{"".join(links)}</div>'
        "</div>"
    )


def screenshot_asset_source_root(pack: dict[str, object]) -> Path:
    defaults = pack.get("defaults", {})
    return SCREENSHOT_PACK_BASE_ROOT / str(defaults.get("public_asset_dir", "docs/assets/screenshots"))


def screenshot_stage_label(stage: str, *, locale: str) -> str:
    return public_localized_text(SCREENSHOT_STAGE_LABELS.get(stage, {}), locale)


def screenshot_entries(
    pack: dict[str, object],
    placement: str,
    *,
    locale: str,
    asset_prefix: str,
) -> list[dict[str, str]]:
    source_root = screenshot_asset_source_root(pack)
    entries: list[dict[str, str]] = []
    for entry in sorted(pack.get("screenshots", []), key=lambda row: row["display_order"]):
        if placement not in entry.get("placements", []):
            continue
        asset_name = str(entry.get("assets", {}).get("public", "")).strip()
        if not asset_name:
            continue
        asset_path = source_root / asset_name
        if not asset_path.exists():
            continue
        title = public_localized_text(entry.get("title", {}), locale)
        alt = public_localized_text(entry.get("alt", {}), locale)
        caption = public_localized_text(entry.get("captions", {}).get(placement, {}), locale)
        entries.append(
            {
                "id": str(entry["id"]),
                "asset_url": f"{asset_prefix}{asset_name}",
                "title": title,
                "alt": alt,
                "caption": caption,
                "stage": str(entry["stage"]),
                "stage_label": screenshot_stage_label(str(entry["stage"]), locale=locale),
                "route": str(entry.get("source", {}).get("path", "")),
            }
        )
    return entries


def screenshot_payload_entries(pack: dict[str, object], placement: str) -> list[dict[str, object]]:
    source_root = screenshot_asset_source_root(pack)
    payload_entries: list[dict[str, object]] = []
    for entry in sorted(pack.get("screenshots", []), key=lambda row: row["display_order"]):
        if placement not in entry.get("placements", []):
            continue
        asset_name = str(entry.get("assets", {}).get("public", "")).strip()
        if not asset_name:
            continue
        if not (source_root / asset_name).exists():
            continue
        payload_entries.append(
            {
                "id": str(entry["id"]),
                "asset_path": f"assets/screenshots/{asset_name}",
                "title": entry.get("title", {}),
                "alt": entry.get("alt", {}),
                "captions": entry.get("captions", {}).get(placement, {}),
                "stage": str(entry["stage"]),
                "route": str(entry.get("source", {}).get("path", "")),
            }
        )
    return payload_entries


def render_screenshot_cards(entries: list[dict[str, str]], *, card_class: str = "screenshot-card") -> str:
    rendered: list[str] = []
    for entry in entries:
        stage_class = " proof" if entry["stage"] == "public_proof" else ""
        route_html = (
            f'<span class="screenshot-route"><code>{escape(entry["route"])}</code></span>'
            if entry["route"]
            else ""
        )
        rendered.append(
            f"""        <figure class="{card_class}{stage_class}">
          <img src="{escape(entry["asset_url"])}" alt="{escape(entry["alt"])}">
          <figcaption>
            <span class="screenshot-stage">{escape(entry["stage_label"])}</span>
            <strong>{escape(entry["title"])}</strong>
            <p>{escape(entry["caption"])}</p>
            {route_html}
          </figcaption>
        </figure>"""
        )
    return "\n".join(rendered)


def copy_screenshot_assets(pack: dict[str, object]) -> None:
    source_root = screenshot_asset_source_root(pack)
    PIZZA_SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    PROTOCOLS_SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    for entry in pack.get("screenshots", []):
        asset_name = str(entry.get("assets", {}).get("public", "")).strip()
        if not asset_name:
            continue
        source_path = source_root / asset_name
        if not source_path.exists():
            continue
        shutil.copy2(source_path, PIZZA_SCREENSHOT_ROOT / asset_name)
        shutil.copy2(source_path, PROTOCOLS_SCREENSHOT_ROOT / asset_name)

OWNER_EXPLAINERS = [
    {
        "title": "You keep your own menu",
        "body": "Names, prices, categories, and active items stay with the restaurant node instead of living only inside a marketplace listing.",
    },
    {
        "title": "Orders go directly to the shop",
        "body": "The customer can discover through a registry, but the menu and order request go straight to the restaurant node.",
    },
    {
        "title": "Start with pickup and simple payment",
        "body": "The first live shape is intentionally small: controlled pickup ordering, with pay-at-pickup as the simple starting point.",
    },
    {
        "title": "Add tools without giving away ownership",
        "body": "Kitchen screen, print, notifications, stock checks, and later trust or payment modules can be added without turning the registry into the middleman.",
    },
]

MODULE_GROUPS = [
    {
        "id": "customer",
        "title": {"da": "Hvad kunden ser", "en": "What the customer sees"},
        "intro": {
            "da": "Det her er de offentlige flader en kunde faktisk kan åbne under discovery og ordering.",
            "en": "These are the public surfaces a customer can actually open during discovery and ordering.",
        },
    },
    {
        "id": "operator",
        "title": {"da": "Hvad butikken bruger bag disken", "en": "What the shop uses behind the counter"},
        "intro": {
            "da": "Det her er restaurant-side værktøjer til menu-kontrol, køkkenflow, lager, print og fallback-alarmer.",
            "en": "These are the restaurant-side tools for menu control, kitchen flow, stock, printing, and fallback alerts.",
        },
    },
    {
        "id": "payment_trust",
        "title": {"da": "Betaling og forretningstillid", "en": "Payment and business trust"},
        "intro": {
            "da": "Her holdes betaling bevidst enkel, og her kan identitet eller virksomhedsverifikation senere blive læsbar og reviewbar.",
            "en": "This is where payment stays intentionally simple and where identity or business verification can later become reviewable.",
        },
    },
    {
        "id": "internal",
        "title": {"da": "Interne tests og fremtidige ekstra-lag", "en": "Internal tests and future extras"},
        "intro": {
            "da": "De her moduler er ikke det live restaurant-tilbud i dag. De er intern test-stillads eller planlagte næste skridt.",
            "en": "These modules are not the live restaurant offer today. They are internal test scaffolding or planned next-step pieces.",
        },
    },
]

MODULE_PRESENTATION = {
    "p4p.menu.list": {
        "group": "customer",
        "title": "Simple online menu",
        "audience": "Customer side",
        "summary": "A customer opens a normal menu list and sends the order directly to the restaurant.",
        "owner_value": "You keep the menu basics on your own node instead of relying on a marketplace-owned list.",
        "touches": "Active items, prices, descriptions, and categories.",
        "not_owner": "It does not own payment, stock, or staff workflow.",
    },
    "p4p.menu.photo-map": {
        "group": "customer",
        "title": "Clickable photo-style menu",
        "audience": "Customer side",
        "summary": "A customer taps a paper-menu style surface instead of a plain item list.",
        "owner_value": "Useful if you want the customer surface to feel closer to a printed flyer or visual takeaway menu.",
        "touches": "Active items, prices, descriptions, and categories.",
        "not_owner": "It does not own OCR, payment, stock, or operator workflow.",
    },
    "p4p.customer.status": {
        "group": "customer",
        "title": "Order status page",
        "audience": "Customer side",
        "summary": "A customer can check whether the order was accepted, rejected, or is ready for pickup.",
        "owner_value": "Reduces the need for status phone calls when the restaurant updates the order state.",
        "touches": "Order status, estimated ready time, fulfillment type, and payment mode.",
        "not_owner": "It does not expose operator notes, customer contact data, or the full event log.",
    },
    "p4p.catalog.editor": {
        "group": "operator",
        "title": "Edit menu and prices",
        "audience": "Owner / operator side",
        "summary": "The restaurant can change names, prices, categories, and whether an item is active.",
        "owner_value": "This is the control surface that lets the shop own its own menu instead of waiting for a platform back office.",
        "touches": "Item ids, names, descriptions, prices, categories, and active/inactive state.",
        "not_owner": "It is not a customer-facing menu page.",
    },
    "p4p.catalog.import.ocr": {
        "group": "operator",
        "title": "Scan a paper menu",
        "audience": "Owner / operator side",
        "summary": "The restaurant can scan a paper menu into draft catalog rows before a human review.",
        "owner_value": "Useful when a shop starts from a printed takeaway card instead of rebuilding the whole menu by hand.",
        "touches": "Draft OCR item names, prices, categories, and source lines before catalog save.",
        "not_owner": "It does not become catalog truth by itself and it is not a customer-facing menu.",
    },
    "p4p.kitchen.screen": {
        "group": "operator",
        "title": "Kitchen order queue",
        "audience": "Owner / operator side",
        "summary": "Staff can see incoming orders and move them through kitchen states.",
        "owner_value": "Lets the restaurant turn direct orders into an actual working queue behind the counter.",
        "touches": "Order items, note, customer contact, fulfillment type, and order status.",
        "not_owner": "It is not public discovery and it does not own payment.",
    },
    "p4p.stock.basic": {
        "group": "operator",
        "title": "Final stock check",
        "audience": "Owner / operator side",
        "summary": "The system can do one last local stock check before the next order step continues.",
        "owner_value": "Helps stop the flow before the kitchen commits to something the shop no longer has.",
        "touches": "Order items and local stock state.",
        "not_owner": "It does not replace the menu or the kitchen workflow.",
    },
    "p4p.order.print": {
        "group": "operator",
        "title": "Print to kitchen or POS",
        "audience": "Owner / operator side",
        "summary": "Accepted orders can later be printed or forwarded to a restaurant-owned printer or POS surface.",
        "owner_value": "This is the bridge from a direct online order to a paper ticket or POS flow inside the shop.",
        "touches": "Order items, note, contact, and fulfillment type.",
        "not_owner": "It does not replace payment or public discovery.",
    },
    "p4p.order.print.backup": {
        "group": "operator",
        "title": "Backup printer path",
        "audience": "Counter / hardware side",
        "summary": "If the first printer path fails, the order can be rerouted to a second print target or local spool.",
        "owner_value": "Useful when a shop wants hardware redundancy before trusting direct orders during busy service.",
        "touches": "Order items, note, customer contact, fulfillment type, and backup printer target.",
        "not_owner": "It is fallback routing, not the main customer or kitchen workflow.",
    },
    "p4p.notify.email": {
        "group": "operator",
        "title": "Operator email alert",
        "audience": "Owner / operator side",
        "summary": "The system can send an email when an order needs attention or a printer flow fails.",
        "owner_value": "Useful as a fallback alert so the shop is not blind if another operator-side step fails.",
        "touches": "Order summary and the operator destination address.",
        "not_owner": "It is a fallback notification, not the main order surface.",
    },
    "p4p.notify.sms": {
        "group": "operator",
        "title": "Operator SMS alert",
        "audience": "Owner / operator side",
        "summary": "The system can send a short phone alert when an order or printer problem needs fast attention.",
        "owner_value": "Useful if the test hardware is noisy or partially unattended and the operator still needs a direct phone fallback.",
        "touches": "Order summary and the operator phone destination.",
        "not_owner": "It is a fallback notification, not the main order surface.",
    },
    "p4p.order.alert.basic": {
        "group": "operator",
        "title": "Bell or light alert",
        "audience": "Counter / hardware side",
        "summary": "A local box can ring, beep, or flash when a new order or hardware problem needs attention.",
        "owner_value": "Lets the hardware give an audible or visible cue without turning the alert layer into the actual order queue.",
        "touches": "Order summary, configured alert target, and urgency state.",
        "not_owner": "It does not accept orders, replace the kitchen queue, or settle payment.",
    },
    "p4p.pickup.board.basic": {
        "group": "operator",
        "title": "Ready-for-pickup board",
        "audience": "Counter / pickup side",
        "summary": "A simple local screen can show which direct orders are accepted or ready at the counter.",
        "owner_value": "Gives the shop a cheap customer-facing pickup signal without exposing the full operator dashboard.",
        "touches": "Order summary, public order status, estimated ready time, payment mode, and board target.",
        "not_owner": "It does not take new orders or replace the kitchen queue.",
    },
    "p4p.payment.cash": {
        "group": "payment_trust",
        "title": "Pay at pickup / cash",
        "audience": "Customer + operator side",
        "summary": "The restaurant can keep payment simple by taking cash or direct in-person payment outside the protocol.",
        "owner_value": "This is the easiest first live shape: order online, pay when the customer arrives.",
        "touches": "Order total and fulfillment type only.",
        "not_owner": "It does not hold card data, wallets, settlement, or merchant-of-record responsibility.",
    },
    "p4p.payment.mobilepay": {
        "group": "payment_trust",
        "title": "External MobilePay adapter",
        "audience": "Customer + operator side",
        "summary": "A future external adapter can expose a familiar MobilePay-style pay-at-pickup instruction without making P4P the payment processor.",
        "owner_value": "Lets pilot restaurants say whether an external MobilePay-style adapter is worth adding after cash-first feedback.",
        "touches": "Order total, fulfillment type, and operator payment destination.",
        "not_owner": "It does not make P4P hold funds, process cards, or become merchant of record.",
    },
    "p4p.trust.cvr-basic": {
        "group": "payment_trust",
        "title": "Business identity check",
        "audience": "Trust layer",
        "summary": "A later trust layer can connect a node identity claim to a Danish CVR lookup or trust claim.",
        "owner_value": "This is meant to make a restaurant identity more reviewable later without turning the registry into the authority.",
        "touches": "Declared CVR identifiers and public node identity data.",
        "not_owner": "It is not part of the live ordering loop today.",
    },
    "p4p.payment.godpay-mock": {
        "group": "internal",
        "title": "Fake payment tester",
        "audience": "Internal debug",
        "summary": "An internal mock can randomly accept or reject a test payment during local debugging.",
        "owner_value": "Not something a restaurant should read as a live offer. It exists to test ugly edge cases before any real payment direction exists.",
        "touches": "Order total only.",
        "not_owner": "It is not real money, not real settlement, and not a real provider.",
    },
    "p4p.payment.chaospay-mock": {
        "group": "internal",
        "title": "Ugly-case payment tester",
        "audience": "Internal debug",
        "summary": "An internal mock for timeouts, wrong amounts, duplicate callbacks, and other payment chaos scenarios.",
        "owner_value": "This exists to break things safely in local testing before any broader payment layer is discussed.",
        "touches": "Order total and order state.",
        "not_owner": "It is not real money, not real settlement, and not a live customer payment option.",
    },
}

MODULE_READ_NEXT = {
    "p4p.menu.list": [
        {
            "title": "See what happens after the order",
            "body": "After the customer sends the order, the next useful public page is the status screen.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "Then look behind the counter",
            "body": "If you want the shop-side counterpart, open the menu-control page the restaurant uses.",
            "kind": "module",
            "target": "p4p.catalog.editor",
        },
        {
            "title": "Keep the payment edge small",
            "body": "The first live payment shape stays intentionally simple: order online, pay at pickup.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.menu.photo-map": [
        {
            "title": "See the plain menu baseline",
            "body": "This visual menu is easier to understand when you compare it to the simpler list version.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the customer follow-up",
            "body": "After the order is sent, the next customer-facing step is the status page.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "Keep the boundary in view",
            "body": "The visual menu still sits inside the same small payment boundary as the rest of the proof.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.customer.status": [
        {
            "title": "Start at the order surface first",
            "body": "If you landed here early, read the menu module first so the order-status page makes sense in context.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then look at the kitchen side",
            "body": "The status page only changes when the restaurant updates the order behind the counter.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Keep payment simple",
            "body": "The first live shape still avoids deeper payment handling and keeps the edge small.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.catalog.editor": [
        {
            "title": "See the public result",
            "body": "After the restaurant edits the menu, the simplest customer-facing result is the plain online menu.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the paper-menu helper",
            "body": "If the shop starts from a printed flyer, the OCR helper is the separate optional import surface beside the editor.",
            "kind": "module",
            "target": "p4p.catalog.import.ocr",
        },
        {
            "title": "See who currently provides this stack",
            "body": "The provider page explains the shared reference layer behind the current public tools.",
            "kind": "provider",
        },
    ],
    "p4p.catalog.import.ocr": [
        {
            "title": "See the catalog truth surface next",
            "body": "The OCR helper only creates drafts. The real local source of truth still lives in the catalog editor.",
            "kind": "module",
            "target": "p4p.catalog.editor",
        },
        {
            "title": "Then see the public result",
            "body": "After the operator reviews and saves imported items, the simplest customer-facing result is the plain online menu.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "See who currently provides this stack",
            "body": "The provider page explains the shared reference layer behind the current public tools.",
            "kind": "provider",
        },
    ],
    "p4p.kitchen.screen": [
        {
            "title": "See what the customer opens first",
            "body": "The kitchen queue is easier to read once you start from the direct customer menu surface.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the customer follow-up",
            "body": "The customer-side mirror of kitchen state changes is the order-status page.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "Keep the payment edge small",
            "body": "Even when the kitchen flow exists, the first live payment shape is still pay at pickup.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.stock.basic": [
        {
            "title": "See the queue this protects",
            "body": "The stock check only matters because the restaurant is already running an active order queue.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "See the menu control beside it",
            "body": "Stock checks make more sense when you read them next to the menu-control surface.",
            "kind": "module",
            "target": "p4p.catalog.editor",
        },
        {
            "title": "Keep the live boundary small",
            "body": "This extra operator check still sits inside a deliberately small first live payment edge.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
    ],
    "p4p.order.print": [
        {
            "title": "See the main kitchen flow first",
            "body": "Printing is a support surface. The main operator story still starts with the kitchen queue.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Then see the fallback alert",
            "body": "If a print path fails or stalls, the operator alert module is the next useful fallback.",
            "kind": "module",
            "target": "p4p.notify.email",
        },
        {
            "title": "See who currently provides the tools",
            "body": "The provider page explains the current shared source behind the operator-side extras.",
            "kind": "provider",
        },
    ],
    "p4p.order.print.backup": [
        {
            "title": "Start with the main print lane",
            "body": "The backup path only makes sense after you read the primary printer/POS lane.",
            "kind": "module",
            "target": "p4p.order.print",
        },
        {
            "title": "Then see the queue it protects",
            "body": "Fallback printing exists because the kitchen queue still needs a dependable handoff during service.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Keep the human fallback nearby",
            "body": "If both print paths fail, the next useful backup is a direct operator notification path.",
            "kind": "module",
            "target": "p4p.notify.sms",
        },
    ],
    "p4p.notify.email": [
        {
            "title": "See the main kitchen flow first",
            "body": "This email alert makes more sense when you first read the ordinary kitchen queue it supports.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Then see the print fallback beside it",
            "body": "Print and alert modules live in the same operator-support layer, not in the public customer loop.",
            "kind": "module",
            "target": "p4p.order.print",
        },
        {
            "title": "See who currently provides the tools",
            "body": "The provider page shows the current shared reference layer behind these support modules.",
            "kind": "provider",
        },
    ],
    "p4p.notify.sms": [
        {
            "title": "See the email fallback beside it",
            "body": "SMS is easiest to judge when you compare it to the simpler email fallback lane already in the stack.",
            "kind": "module",
            "target": "p4p.notify.email",
        },
        {
            "title": "Then see the queue it protects",
            "body": "Phone fallback only matters because the restaurant still has a real operator queue behind the alert.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "See who currently provides the tools",
            "body": "The provider page keeps the current pilot-feedback modules inside one clearly labeled reference stack.",
            "kind": "provider",
        },
    ],
    "p4p.order.alert.basic": [
        {
            "title": "See the main kitchen flow first",
            "body": "A bell or light alert only helps because there is still a real kitchen queue behind it.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
        {
            "title": "Then compare it to the print lane",
            "body": "This alert lane becomes more concrete when you read it next to the primary print/POS handoff.",
            "kind": "module",
            "target": "p4p.order.print",
        },
        {
            "title": "Keep the phone fallback nearby",
            "body": "If a local bell or light path disappears, the next useful fallback is a phone notification lane.",
            "kind": "module",
            "target": "p4p.notify.sms",
        },
    ],
    "p4p.pickup.board.basic": [
        {
            "title": "Start with the customer order surface",
            "body": "The pickup board only matters after the customer has first seen the direct menu and submitted an order.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the status source behind it",
            "body": "The local pickup board is easier to judge when you compare it to the public order-status page.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "See the kitchen queue behind the board",
            "body": "The board only stays truthful if the operator queue is still the thing driving state changes.",
            "kind": "module",
            "target": "p4p.kitchen.screen",
        },
    ],
    "p4p.payment.cash": [
        {
            "title": "Start from the customer order surface",
            "body": "The payment edge only matters after the customer has first seen the direct menu.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the customer follow-up",
            "body": "After ordering and paying at pickup, the next customer-facing surface is the status page.",
            "kind": "module",
            "target": "p4p.customer.status",
        },
        {
            "title": "See the current provider boundary",
            "body": "The provider page keeps the current ownership and proof boundary explicit.",
            "kind": "provider",
        },
    ],
    "p4p.payment.mobilepay": [
        {
            "title": "Start from the cash baseline",
            "body": "This only makes sense after you read the simpler cash-first lane that defines the current live boundary.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
        {
            "title": "Then return to the customer order surface",
            "body": "The payment adapter still sits after the direct menu flow, not before it.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Keep the provider boundary explicit",
            "body": "The provider page keeps this as a planned adapter candidate, not a claim that P4P is processing money.",
            "kind": "provider",
        },
    ],
    "p4p.trust.cvr-basic": [
        {
            "title": "Keep the live order flow first",
            "body": "This trust direction sits after the basic ordering flow, not before it.",
            "kind": "module",
            "target": "p4p.menu.list",
        },
        {
            "title": "Then see the simple live payment edge",
            "body": "The current real-world payment boundary is still much smaller than the later trust direction.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
        {
            "title": "See the current provider boundary",
            "body": "The provider page explains what the current shared stack is and what it does not claim yet.",
            "kind": "provider",
        },
    ],
    "p4p.payment.godpay-mock": [
        {
            "title": "See the real live payment baseline",
            "body": "This mock only makes sense after you read the simple pay-at-pickup module that represents the current live edge.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
        {
            "title": "See the current provider boundary",
            "body": "The provider page explains why this remains internal test scaffolding, not a public money claim.",
            "kind": "provider",
        },
        {
            "title": "Back to the full module catalog",
            "body": "If you want the broader shape again, return to the grouped module stack.",
            "kind": "catalog",
        },
    ],
    "p4p.payment.chaospay-mock": [
        {
            "title": "See the real live payment baseline",
            "body": "This ugly-case tester only makes sense after you read the small live payment shape it is meant to protect.",
            "kind": "module",
            "target": "p4p.payment.cash",
        },
        {
            "title": "See the current provider boundary",
            "body": "The provider page explains why this remains internal failure testing, not a public payment promise.",
            "kind": "provider",
        },
        {
            "title": "Back to the full module catalog",
            "body": "If you want the broader module layout again, return to the grouped stack.",
            "kind": "catalog",
        },
    ],
}

PROVIDER_PRESENTATION = {
    "p4p.reference": {
        "summary": "Right now the public Pizza4People tools come from one shared reference provider inside the repo.",
        "owner_value": "The current menu, order, and operator pages come from one shared reference stack, not from a big live marketplace of outside vendors yet.",
        "what_it_is": "A shared reference provider for the first customer pages, operator tools, simple pay-at-pickup flow, and local test modules in the current proof.",
        "what_it_is_not": "Not a live certification authority, not a marketplace full of competing vendors, and not proof that every declared module is production-ready.",
        "current_shape": "One shared reference stack behind the current public site.",
        "not_yet": "No broad provider marketplace yet. No certification layer yet.",
    }
}

PRESS_MODULE_SPOTLIGHTS = [
    {
        "module_id": "p4p.catalog.editor",
        "title": {
            "dk": "Butikken styrer menu og priser",
            "en": "The shop keeps menu and prices",
        },
        "body": {
            "dk": "Butikken kan selv ændre varer, priser og hvad der er aktivt, i stedet for at vente på et platform-backoffice.",
            "en": "The shop can change items, prices, and what is active instead of waiting for a platform back office.",
        },
    },
    {
        "module_id": "p4p.menu.list",
        "title": {
            "dk": "Kunden kan bestille direkte",
            "en": "Customers can order direct",
        },
        "body": {
            "dk": "Kunden åbner en enkel menu og sender ordren direkte til butikken i stedet for gennem et marketplace-flow.",
            "en": "The customer opens a simple menu and sends the order straight to the shop instead of through a marketplace flow.",
        },
    },
    {
        "module_id": "p4p.customer.status",
        "title": {
            "dk": "Kunden kan selv se status",
            "en": "Customers can check order status",
        },
        "body": {
            "dk": "Når butikken opdaterer ordren, kan kunden selv se om den er accepteret eller klar, i stedet for at ringe.",
            "en": "When the shop updates the order, the customer can see whether it is accepted or ready instead of having to call.",
        },
    },
    {
        "module_id": "p4p.payment.cash",
        "title": {
            "dk": "Start med betaling ved afhentning",
            "en": "Start with pay at pickup",
        },
        "body": {
            "dk": "Den første live-model er bevidst enkel: bestil online, betal når kunden møder op.",
            "en": "The first live shape is deliberately simple: order online, pay when the customer arrives.",
        },
    },
]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_template(name: str, context: dict[str, str]) -> str:
    rendered = load_text(TEMPLATE_ROOT / name)
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    unresolved = sorted(set(re.findall(r"\{\{[a-zA-Z0-9_]+\}\}", rendered)))
    if unresolved:
        raise ValueError(f"Unresolved template placeholders in {name}: {', '.join(unresolved)}")
    return rendered


def load_site_data() -> dict:
    return load_json(SITE_DATA_PATH)


def load_modules() -> list[dict]:
    modules: list[dict] = []
    for manifest_path in sorted(MODULES_ROOT.glob("*/module.json")):
        payload = load_json(manifest_path)
        public_catalog = payload.get("public_catalog", {})
        module_id = payload["module_id"]
        provider_id = payload["provider_id"]
        modules.append(
            {
                "module_id": module_id,
                "module_class": payload["module_class"],
                "lane": payload["lane"],
                "visibility": payload["visibility"],
                "provider_id": provider_id,
                "title": localized_field_map(public_catalog.get("title")) or {"en": module_id},
                "summary": localized_field_map(public_catalog.get("summary"))
                or localized_field_map(public_catalog.get("function"))
                or localized_field_map(payload.get("description"))
                or {"en": localized_field_text(payload.get("description"), "en")},
                "description": localized_field_map(payload.get("description")) or {"en": localized_field_text(payload.get("description"), "en")},
                "function": localized_field_map(public_catalog.get("function"))
                or localized_field_map(payload.get("description"))
                or {"en": localized_field_text(payload.get("description"), "en")},
                "data_access": localized_field_map(public_catalog.get("data_access_summary"))
                or {"en": ", ".join(payload.get("data_access", [])) or "Not declared yet."},
                "trust_status": localized_field_map(public_catalog.get("trust_status")) or {"en": payload["status"]},
                "readiness": public_catalog.get("readiness", payload["status"]),
                "operator_status": localized_field_map(public_catalog.get("operator_status")) or {"en": "not enabled"},
                "module_site_path": f"modules/{module_id}/",
                "provider_site_path": f"providers/{provider_id}/",
                "module_doc_url": f"https://github.com/DennisHedegreen/p4p/blob/main/docs/modules/{module_id}.md",
                "module_manifest_url": f"https://github.com/DennisHedegreen/p4p/blob/main/modules/{module_id}/module.json",
                "provider_doc_url": f"https://github.com/DennisHedegreen/p4p/blob/main/docs/providers/{provider_id}.md",
            }
        )
    return modules


def load_providers(modules: list[dict]) -> list[dict]:
    modules_by_provider: dict[str, list[dict]] = {}
    for module in modules:
        modules_by_provider.setdefault(module["provider_id"], []).append(module)

    providers: list[dict] = []
    for provider_id, manifest in sorted(load_reference_provider_catalog().items()):
        provider_modules = sorted(modules_by_provider.get(provider_id, []), key=lambda entry: entry["module_id"])
        manifest_relpath = manifest.source_path.relative_to(P4P_ROOT).as_posix()
        providers.append(
            {
                "provider_id": provider_id,
                "name": localized_field_map(manifest.raw.get("name")) or {"en": manifest.name},
                "description": localized_field_map(manifest.raw.get("description")) or {"en": manifest.description},
                "website": manifest.website,
                "status": manifest.status,
                "supported_lanes": list(manifest.supported_lanes),
                "module_ids": [entry["module_id"] for entry in provider_modules],
                "module_count": len(provider_modules),
                "provider_site_path": f"providers/{provider_id}/",
                "provider_doc_url": f"https://github.com/DennisHedegreen/p4p/blob/main/docs/providers/{provider_id}.md",
                "provider_manifest_url": f"https://github.com/DennisHedegreen/p4p/blob/main/{manifest_relpath}",
            }
        )
    return providers


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def module_page_path(module_id: str, *, locale: str = "en") -> Path:
    filename = "index.html" if locale == "en" else f"{locale}.html"
    return PUBLIC_ROOT / "modules" / module_id / filename


def provider_page_path(provider_id: str, *, locale: str = "en") -> Path:
    filename = "index.html" if locale == "en" else f"{locale}.html"
    return PUBLIC_ROOT / "providers" / provider_id / filename


def module_catalog_payload(site_data: dict, modules: list[dict]) -> dict:
    site_url = site_data["canonical_urls"]["site"]
    return {
        "catalog_name": "Pizza4People Module Catalog",
        "catalog_status": "generated from module manifests",
        "generated_at": site_data["generated_at"],
        "modules": [
            {
                "module_id": entry["module_id"],
                "provider_id": entry["provider_id"],
                "function": entry["function"],
                "data_access": entry["data_access"],
                "trust_status": entry["trust_status"],
                "readiness": entry["readiness"],
                "operator_status": entry["operator_status"],
                "module_page_url": f'{site_url}{entry["module_site_path"]}',
                "provider_page_url": f'{site_url}{entry["provider_site_path"]}',
                "module_doc_url": entry["module_doc_url"],
                "module_manifest_url": entry["module_manifest_url"],
                "provider_doc_url": entry["provider_doc_url"],
            }
            for entry in modules
        ],
    }


def provider_catalog_payload(site_data: dict, providers: list[dict]) -> dict:
    site_url = site_data["canonical_urls"]["site"]
    return {
        "catalog_name": "Pizza4People Provider Catalog",
        "catalog_status": "generated from provider manifests",
        "generated_at": site_data["generated_at"],
        "providers": [
            {
                "provider_id": entry["provider_id"],
                "name": entry["name"],
                "description": entry["description"],
                "website": entry["website"],
                "status": entry["status"],
                "supported_lanes": entry["supported_lanes"],
                "module_count": entry["module_count"],
                "module_ids": entry["module_ids"],
                "provider_page_url": f'{site_url}{entry["provider_site_path"]}',
                "provider_doc_url": entry["provider_doc_url"],
                "provider_manifest_url": entry["provider_manifest_url"],
            }
            for entry in providers
        ],
    }


PROTOCOLS_MODULE_UI = {
    "locale_label": {
        "da": "Sprog",
        "sv": "Språk",
        "tr": "Dil",
        "ar": "اللغة",
        "ku": "Ziman",
        "en": "Language",
    },
    "modules_title": {
        "da": "Moduler til lokale butikker og direkte kontakt",
        "sv": "Moduler för lokala butiker och direkt kontakt",
        "tr": "Yerel dükkânlar ve doğrudan ilişki için modüller",
        "ar": "وحدات للمتاجر المحلية والعلاقة المباشرة",
        "ku": "Modul ji bo dikkanên herêmî û têkiliya rasterast",
        "en": "Modules for local shops and direct contact",
    },
    "modules_lede": {
        "da": "Læs modul-familierne menneskeligt her. Brug operatoren lokalt til at vælge hvad din node faktisk skal køre.",
        "sv": "Läs modulfamiljerna mänskligt här. Använd operatören lokalt för att välja vad din nod faktiskt ska köra.",
        "tr": "Modül ailelerini burada insanvenligt okuyun. Düğümünüzün gerçekten ne çalıştıracağını seçmek için yerel operatörü kullanın.",
        "ar": "اقرأ عائلات الوحدات هنا بشكل إنساني. استخدم واجهة المشغّل محلياً لتختار ما الذي يجب أن تشغله عقدتك فعلاً.",
        "ku": "Li vir malbatên modulê bi awayekî merivane bixwîne. Operatorê herêmî bi kar bîne da ku tu hilbijêrî nodeya te bi rastî çi bixebitîne.",
        "en": "Read module families here in human terms. Use the local operator to choose what your node should actually run.",
    },
    "shop_title": {
        "da": "Shop er første familie",
        "sv": "Shop är den första familjen",
        "tr": "Shop ilk aile",
        "ar": "shop هي العائلة الأولى",
        "ku": "shop malbata yekem e",
        "en": "Shop is the first family",
    },
    "shop_lede": {
        "da": "Start med behov som menu, kundesider, betaling og lokal hardware i stedet for at starte med pizza som kategori.",
        "sv": "Börja med behov som meny, kundsidor, betalning och lokal hårdvara i stället för att börja med pizza som kategori.",
        "tr": "Kategori olarak pizzayla başlamak yerine menü, müşteri yüzleri, ödeme ve yerel donanım gibi ihtiyaçlarla başlayın.",
        "ar": "ابدأ بالاحتياجات مثل القائمة وواجهات الزبون والدفع والعتاد المحلي بدلاً من البدء بالبيتزا كفئة.",
        "ku": "Li şûna ku bi pizza wek kategori dest pê bikî, bi hewcedariyên wek menu, rûyên xerîdar, dravdan û hardwareya herêmî dest pê bike.",
        "en": "Start with needs like menu, customer surfaces, payment, and local hardware instead of starting with pizza as a category.",
    },
    "recommended": {
        "da": "Anbefalet baseline",
        "sv": "Rekommenderad baslinje",
        "tr": "Önerilen başlangıç seti",
        "ar": "الحد الأدنى الموصى به",
        "ku": "Bingehê pêşniyarkirî",
        "en": "Recommended baseline",
    },
    "browse": {
        "da": "Gennemse grupper",
        "sv": "Bläddra bland grupper",
        "tr": "Gruplara göz at",
        "ar": "تصفّح المجموعات",
        "ku": "Li koman bigere",
        "en": "Browse groups",
    },
    "open_proof": {
        "da": "Åbn proof-side",
        "sv": "Öppna proofsida",
        "tr": "Proof sayfasını aç",
        "ar": "افتح صفحة الإثبات",
        "ku": "Rûpela proof veke",
        "en": "Open proof page",
    },
    "open_doc": {
        "da": "Åbn modul-doc",
        "sv": "Öppna modul-doc",
        "tr": "Modül dokümanını aç",
        "ar": "افتح توثيق الوحدة",
        "ku": "Belgeya modulê veke",
        "en": "Open module doc",
    },
    "open_manifest": {
        "da": "Åbn manifest",
        "sv": "Öppna manifest",
        "tr": "Manifesti aç",
        "ar": "افتح المانيفست",
        "ku": "Manifestê veke",
        "en": "Open manifest",
    },
    "open_shop": {
        "da": "Åbn shop-familien",
        "sv": "Öppna shop-familjen",
        "tr": "Shop ailesini aç",
        "ar": "افتح عائلة shop",
        "ku": "Malbata shop veke",
        "en": "Open shop family",
    },
    "screenshots": {
        "da": "Lokale flader",
        "sv": "Lokala ytor",
        "tr": "Yerel yüzeyler",
        "ar": "الأسطح المحلية",
        "ku": "Rûberên herêmî",
        "en": "Local surfaces",
    },
    "screenshots_catalog_lede": {
        "da": "Det offentlige modul-katalog ender på en lokal node, hvor butikken kan læse og styre modulerne selv.",
        "sv": "Den offentliga modulkatalogen landar på en lokal nod där butiken kan läsa och styra modulerna själv.",
        "tr": "Açık modül kataloğu, dükkânın modülleri yerel düğümde okuyup yönetebildiği yere bağlanır.",
        "ar": "ينتهي كتالوج الوحدات العام على عقدة محلية حيث يمكن للمتجر قراءة الوحدات والتحكم بها بنفسه.",
        "ku": "Kataloga giştî ya modulê di nodeyek herêmî de bi dawî dibe ku firotgeh dikare modulan bixwîne û bi xwe bi rê ve bibe.",
        "en": "The public module catalog ends at a local node where the shop can read and control modules itself.",
    },
    "screenshots_shop_lede": {
        "da": "Shop-familien bliver først rigtig, når offentlig forklaring, lokal discover, import og modulvalg hænger sammen.",
        "sv": "Shop-familjen blir först verklig när offentlig förklaring, lokal discovery, import och modulval hänger ihop.",
        "tr": "Shop ailesi ancak açık açıklama, yerel keşif, içe aktarma ve modül seçimi birlikte çalışınca gerçek olur.",
        "ar": "تصبح عائلة shop حقيقية حين تتماسك الشروح العامة مع الاكتشاف المحلي والاستيراد واختيار الوحدات.",
        "ku": "Malbata shop tenê dema ku ravekirina giştî, discover ya herêmî, import û hilbijartina modulê bi hev re bixebitin rast dibe.",
        "en": "The shop family only becomes real when public explanation, local discover, import, and module choice hang together.",
    },
    "stage_next_gate": {
        "da": "Næste gate / pilot-node",
        "sv": "Nästa steg / pilot-nod",
        "tr": "Sonraki kapı / pilot düğüm",
        "ar": "البوابة التالية / عقدة تجريبية",
        "ku": "Deriyê din / nodeya pilotê",
        "en": "Pilot-node / next gate",
    },
    "stage_public_proof": {
        "da": "Offentligt proof",
        "sv": "Offentligt bevis",
        "tr": "Kamusal kanıt",
        "ar": "إثبات عام",
        "ku": "Proofa giştî",
        "en": "Public proof",
    },
}


def protocols_text(key: str, locale: str) -> str:
    return localized_text(PROTOCOLS_MODULE_UI.get(key), locale)


def protocols_modules_shell(
    *,
    page_kind: str,
    page_title: str,
    base_path: str,
    payload: dict[str, object],
) -> str:
    catalog_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="da">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(page_title)}</title>
  <link rel="stylesheet" href="{escape(base_path)}style.css">
  <style>
    .modules-shell {{
      width: min(1120px, calc(100% - 2rem));
      margin: 0 auto;
      padding-bottom: 4rem;
    }}
    .modules-hero, .modules-section, .module-grid, .module-card, .module-meta, .module-actions, .locale-row {{
      display: grid;
      gap: 0.9rem;
    }}
    .modules-hero {{
      padding: 1.5rem 0 2rem;
    }}
    .locale-row {{
      align-items: end;
      max-width: 14rem;
    }}
    .locale-row select {{
      min-height: 2.7rem;
      border-radius: 0.8rem;
      border: 1px solid rgba(219, 232, 216, 0.24);
      background: rgba(18, 26, 24, 0.9);
      color: var(--text);
      padding: 0 0.8rem;
      font: inherit;
    }}
    .modules-section {{
      margin-top: 1.5rem;
      padding: 1.15rem;
      border: 1px solid var(--line);
      border-radius: 1rem;
      background: rgba(18, 26, 24, 0.78);
    }}
    .module-grid {{
      grid-template-columns: repeat(auto-fit, minmax(17rem, 1fr));
    }}
    .module-card {{
      padding: 1rem;
      border: 1px solid var(--line);
      border-radius: 0.9rem;
      background: rgba(23, 35, 31, 0.85);
    }}
    .module-meta {{
      grid-template-columns: repeat(auto-fit, minmax(7rem, auto));
    }}
    .module-badge {{
      display: inline-flex;
      align-items: center;
      min-height: 1.8rem;
      padding: 0 0.65rem;
      border-radius: 999px;
      background: rgba(123, 224, 196, 0.12);
      color: var(--mint);
      font-family: var(--mono);
      font-size: 0.72rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .module-actions {{
      grid-template-columns: repeat(auto-fit, minmax(10rem, auto));
    }}
    .module-actions a {{
      display: inline-flex;
      justify-content: center;
      align-items: center;
      min-height: 2.45rem;
      padding: 0 0.9rem;
      border: 1px solid rgba(123, 224, 196, 0.32);
      border-radius: 999px;
      text-decoration: none;
      font-family: var(--mono);
      font-size: 0.72rem;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }}
    .module-actions a:hover {{
      border-color: rgba(123, 224, 196, 0.55);
      background: rgba(123, 224, 196, 0.06);
    }}
    .screenshot-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
      gap: 1rem;
    }}
    .screenshot-card {{
      display: grid;
      gap: 0.75rem;
      padding: 0.9rem;
      border: 1px solid var(--line);
      border-radius: 0.9rem;
      background: rgba(23, 35, 31, 0.85);
    }}
    .screenshot-card img {{
      display: block;
      width: 100%;
      height: auto;
      border-radius: 0.85rem;
      border: 1px solid rgba(219, 232, 216, 0.14);
    }}
    .screenshot-card figcaption {{
      display: grid;
      gap: 0.45rem;
      margin: 0;
    }}
    .screenshot-stage {{
      display: inline-flex;
      width: fit-content;
      min-height: 1.7rem;
      align-items: center;
      padding: 0 0.7rem;
      border-radius: 999px;
      background: rgba(123, 224, 196, 0.12);
      color: var(--mint);
      font-family: var(--mono);
      font-size: 0.7rem;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }}
    .screenshot-stage.proof {{
      background: rgba(233, 189, 99, 0.16);
      color: var(--gold);
    }}
    .screenshot-route {{
      color: var(--muted);
      font-family: var(--mono);
      font-size: 0.72rem;
    }}
    .modules-subnav {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
      margin-top: 0.8rem;
    }}
    .modules-subnav a {{
      display: inline-flex;
      align-items: center;
      min-height: 2.3rem;
      padding: 0 0.8rem;
      border: 1px solid var(--line);
      border-radius: 999px;
      text-decoration: none;
      font-family: var(--mono);
      font-size: 0.72rem;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <a class="brand" href="{escape(base_path)}" aria-label="Protocols4People home">
      <span class="brand-mark">P4P</span>
      <span class="brand-copy">Protocols4People</span>
    </a>
    <nav class="top-nav" aria-label="Primary navigation">
      <a href="{escape(base_path)}">Home</a>
      <a href="{escape(base_path)}modules/">Modules</a>
      <a href="{escape(base_path)}modules/shop/">Shop</a>
      <a href="https://pizza4people.com/" rel="noopener noreferrer">Pizza4People</a>
    </nav>
  </header>
  <main id="main" class="modules-shell" data-page-kind="{escape(page_kind)}">
    <section class="modules-hero">
      <p class="section-kicker" id="hero-kicker"></p>
      <h1 id="hero-title"></h1>
      <p class="hero-lede" id="hero-lede"></p>
      <div class="modules-subnav">
        <a id="hero-shop-link" href="{escape(base_path)}modules/shop/"></a>
        <a href="https://pizza4people.com/modules/" rel="noopener noreferrer">Pizza4People proof</a>
        <a href="https://github.com/DennisHedegreen/p4p" rel="noopener noreferrer">Public GitHub</a>
      </div>
      <label class="locale-row">
        <span id="locale-label"></span>
        <select id="locale-switcher"></select>
      </label>
    </section>

    <section class="modules-section" aria-labelledby="recommended-title">
      <p class="section-kicker" id="recommended-kicker"></p>
      <h2 id="recommended-title"></h2>
      <div id="recommended-grid" class="module-grid"></div>
    </section>

    <section class="modules-section" aria-labelledby="browse-title">
      <p class="section-kicker" id="browse-kicker"></p>
      <h2 id="browse-title"></h2>
      <div id="category-sections"></div>
    </section>

    <section class="modules-section" id="screenshots-section" aria-labelledby="screens-title" hidden>
      <p class="section-kicker" id="screens-kicker"></p>
      <h2 id="screens-title"></h2>
      <p class="hero-lede" id="screens-lede"></p>
      <div id="screens-grid" class="screenshot-grid"></div>
    </section>
  </main>
  <script id="module-catalog-payload" type="application/json">{catalog_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById("module-catalog-payload").textContent);
    const ui = {json.dumps(PROTOCOLS_MODULE_UI, ensure_ascii=False)};
    const pageKind = document.querySelector("main").dataset.pageKind;
    const basePath = {json.dumps(base_path)};
    const localeSwitcher = document.getElementById("locale-switcher");

    function normalizeLocale(locale) {{
      const supported = new Set(payload.supported_locales || []);
      return supported.has(locale) ? locale : (payload.default_locale || "da");
    }}

    function localizedText(map, locale) {{
      if (!map) return "";
      return map[locale] || map.en || map[payload.default_locale] || Object.values(map)[0] || "";
    }}

    function uiText(key, locale) {{
      return localizedText(ui[key], locale);
    }}

    function currentLocale() {{
      const params = new URLSearchParams(window.location.search);
      return normalizeLocale(params.get("lang"));
    }}

    function setLocaleParam(locale) {{
      const params = new URLSearchParams(window.location.search);
      params.set("lang", locale);
      const url = `${{window.location.pathname}}?${{params.toString()}}`;
      window.history.replaceState({{}}, "", url);
    }}

    function renderModuleCard(entry, locale) {{
      return `
        <article class="module-card">
          <div>
            <h3>${{localizedText(entry.title, locale) || entry.module_id}}</h3>
            <p>${{localizedText(entry.summary, locale)}}</p>
          </div>
          <div class="module-meta">
            <span class="module-badge">${{localizedText(entry.category.title, locale)}}</span>
            <span class="module-badge">${{entry.readiness}}</span>
            <span class="module-badge">${{entry.visibility}}</span>
          </div>
          <div class="module-actions">
            <a href="${{entry.proof_page_url}}" target="_blank" rel="noopener noreferrer">${{uiText("open_proof", locale)}}</a>
            <a href="${{entry.module_doc_url}}" target="_blank" rel="noopener noreferrer">${{uiText("open_doc", locale)}}</a>
            <a href="${{entry.module_manifest_url}}" target="_blank" rel="noopener noreferrer">${{uiText("open_manifest", locale)}}</a>
          </div>
        </article>
      `;
    }}

    function renderScreenshotCard(entry, locale) {{
      const stageKey = entry.stage === "public_proof" ? "stage_public_proof" : "stage_next_gate";
      const stageClass = entry.stage === "public_proof" ? "proof" : "";
      return `
        <figure class="screenshot-card">
          <img src="${{basePath}}${{entry.asset_path}}" alt="${{localizedText(entry.alt, locale)}}" loading="lazy">
          <figcaption>
            <span class="screenshot-stage ${{stageClass}}">${{uiText(stageKey, locale)}}</span>
            <strong>${{localizedText(entry.title, locale)}}</strong>
            <p>${{localizedText(entry.captions, locale)}}</p>
            <span class="screenshot-route"><code>${{entry.route}}</code></span>
          </figcaption>
        </figure>
      `;
    }}

    function render(locale) {{
      const family = payload.families[0];
      const categories = payload.categories;
      const modules = payload.modules;
      const screenshotSections = payload.screenshot_sections || {{}};
      document.documentElement.lang = locale;
      document.documentElement.dir = locale === "ar" ? "rtl" : "ltr";
      document.title = pageKind === "shop" ? uiText("shop_title", locale) : uiText("modules_title", locale);

      document.getElementById("hero-kicker").textContent = pageKind === "shop" ? localizedText(family.title, locale) : uiText("browse", locale);
      document.getElementById("hero-title").textContent = pageKind === "shop" ? uiText("shop_title", locale) : uiText("modules_title", locale);
      document.getElementById("hero-lede").textContent = pageKind === "shop" ? uiText("shop_lede", locale) : uiText("modules_lede", locale);
      document.getElementById("hero-shop-link").textContent = uiText("open_shop", locale);
      document.getElementById("locale-label").textContent = uiText("locale_label", locale);
      document.getElementById("recommended-kicker").textContent = localizedText(family.title, locale);
      document.getElementById("recommended-title").textContent = uiText("recommended", locale);
      document.getElementById("browse-kicker").textContent = localizedText(family.title, locale);
      document.getElementById("browse-title").textContent = uiText("browse", locale);

      localeSwitcher.innerHTML = "";
      (payload.locales || []).forEach((choice) => {{
        const option = document.createElement("option");
        option.value = choice.id;
        option.textContent = choice.native_label || choice.label || choice.id;
        localeSwitcher.appendChild(option);
      }});
      localeSwitcher.value = locale;

      const recommendedIds = new Set(family.recommended_module_ids || []);
      const recommended = modules.filter((entry) => recommendedIds.has(entry.module_id));
      document.getElementById("recommended-grid").innerHTML = recommended.map((entry) => renderModuleCard(entry, locale)).join("");

      document.getElementById("category-sections").innerHTML = categories.map((category) => {{
        const categoryModules = modules.filter((entry) => entry.category_id === category.id);
        return `
          <section class="modules-section">
            <h3>${{localizedText(category.title, locale)}}</h3>
            <p>${{localizedText(category.summary, locale)}}</p>
            <div class="module-grid">
              ${{categoryModules.map((entry) => renderModuleCard(entry, locale)).join("")}}
            </div>
          </section>
        `;
      }}).join("");

      const screenshots = pageKind === "shop" ? (screenshotSections.protocols_shop || []) : (screenshotSections.protocols_catalog || []);
      const screenshotsSection = document.getElementById("screenshots-section");
      if (screenshots.length) {{
        screenshotsSection.hidden = false;
        document.getElementById("screens-kicker").textContent = uiText("screenshots", locale);
        document.getElementById("screens-title").textContent = pageKind === "shop" ? uiText("shop_title", locale) : uiText("modules_title", locale);
        document.getElementById("screens-lede").textContent = pageKind === "shop" ? uiText("screenshots_shop_lede", locale) : uiText("screenshots_catalog_lede", locale);
        document.getElementById("screens-grid").innerHTML = screenshots.map((entry) => renderScreenshotCard(entry, locale)).join("");
      }} else {{
        screenshotsSection.hidden = true;
        document.getElementById("screens-grid").innerHTML = "";
      }}
    }}

    localeSwitcher.addEventListener("change", (event) => {{
      const locale = normalizeLocale(event.target.value);
      setLocaleParam(locale);
      render(locale);
    }});

    render(currentLocale());
  </script>
</body>
</html>"""


def render_press_facts(facts: list[dict], urls: dict, *, locale: str) -> str:
    items = []
    for fact in facts:
        body = escape(public_field_text(fact["body"], locale))
        body = body.replace("Danish", '<a href="press-kit/">Danish</a>')
        body = body.replace("English", '<a href="press-kit/en.html">English</a>')
        body = body.replace("proof site", f'<a href="{escape(urls["site"])}">proof site</a>')
        body = body.replace("public repo", f'<a href="{escape(urls["repo"])}">public repo</a>')
        body = body.replace("public main repo", f'<a href="{escape(urls["repo"])}">public main repo</a>')
        body = body.replace("repo README", f'<a href="{escape(urls["repo_readme"])}">repo README</a>')
        body = body.replace("proof note", f'<a href="{escape(urls["repo_proof"])}">proof note</a>')
        body = body.replace("SPEC.md", f'<a href="{escape(urls["repo_spec"])}">SPEC.md</a>')
        body = body.replace(
            "release notes",
            f'<a href="{escape(urls["repo_release_notes"])}">release notes</a>',
        )
        items.append(
            f"""        <article>
          <h3>{escape(public_field_text(fact["title"], locale))}</h3>
          <p>{body}</p>
        </article>"""
        )
    return "\n".join(items)


def render_plain_cards(items: list[dict], *, locale: str) -> str:
    cards = []
    for index, item in enumerate(items, start=1):
        cards.append(
            f"""        <article class="plain-card">
          <span class="plain-number">{index}</span>
          <h3>{escape(public_field_text(item["title"], locale))}</h3>
          <p>{escape(public_field_text(item["body"], locale))}</p>
        </article>"""
        )
    return "\n".join(cards)


def render_owner_cards() -> str:
    cards = []
    for item in OWNER_EXPLAINERS:
        cards.append(
            f"""        <article class="owner-card">
          <h3>{escape(item["title"])}</h3>
          <p>{escape(item["body"])}</p>
        </article>"""
        )
    return "\n".join(cards)


def render_proof_steps(items: list[dict], *, locale: str) -> str:
    cards = []
    for index, item in enumerate(items, start=1):
        cards.append(
            f"""        <article class="proof-step">
          <span class="step-number">{index:02d}</span>
          <h3>{escape(public_field_text(item["title"], locale))}</h3>
          <p>{escape(public_field_text(item["body"], locale))}</p>
        </article>"""
        )
    return "\n".join(cards)


def render_list_items(items: list[object], *, locale: str, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    inner = "\n".join(f"          <li>{escape(public_field_text(item, locale))}</li>" for item in items)
    return f"<{tag}>\n{inner}\n        </{tag}>"


def render_modules(modules: list[dict]) -> str:
    cards = []
    for entry in modules:
        live_class = " module-live" if entry["readiness"] in {"test", "live"} else ""
        cards.append(
            f"""        <article class="module-card{live_class}">
          <div class="module-head">
            <h3>{escape(entry["module_id"])}</h3>
            <span>{escape(entry["readiness"])}</span>
          </div>
          <p>{escape(public_field_text(entry["function"]))}</p>
          <dl>
            <div><dt>Provider</dt><dd><a href="{escape(entry["provider_doc_url"])}" rel="noopener noreferrer">{escape(entry["provider_id"])}</a></dd></div>
            <div><dt>Data</dt><dd>{escape(public_field_text(entry["data_access"]))}</dd></div>
            <div><dt>Trust</dt><dd>{escape(public_field_text(entry["trust_status"]))}</dd></div>
            <div><dt>Operator</dt><dd>{escape(public_field_text(entry["operator_status"]))}</dd></div>
          </dl>
          <p class="module-links"><a href="{escape(entry["module_doc_url"])}" rel="noopener noreferrer">Read module page</a> <span>/</span> <a href="{escape(entry["provider_doc_url"])}" rel="noopener noreferrer">Read provider page</a> <span>/</span> <a href="{escape(entry["module_manifest_url"])}" rel="noopener noreferrer">Open manifest</a></p>
        </article>"""
        )
    return "\n".join(cards)


def module_state(entry: dict, locale: str) -> tuple[str, str]:
    module_id = entry["module_id"]
    if "mock" in module_id:
        return (public_localized_text({"da": "Kun intern test", "en": "Internal test only"}, locale), "state-internal")
    if entry["lane"] == "trust":
        return (public_localized_text({"da": "Tillidsretning", "en": "Trust direction"}, locale), "state-planned")
    if entry["readiness"] == "planned":
        return (public_localized_text({"da": "Planlagt næste", "en": "Planned next"}, locale), "state-planned")
    if entry["visibility"] == "public":
        return (public_localized_text({"da": "Vist i proof", "en": "Shown in proof"}, locale), "state-proof")
    if entry["visibility"] == "operator_only":
        return (
            public_localized_text({"da": "Operator-side prototype", "en": "Operator-side prototype"}, locale),
            "state-operator",
        )
    return (public_localized_text({"da": "Prototype", "en": "Prototype"}, locale), "state-proof")


def module_presentation(entry: dict, locale: str) -> dict[str, str]:
    fallback = {
        "group": "internal",
        "title": public_field_text(entry.get("title", entry["module_id"]), locale),
        "audience": public_localized_text({"da": "Reference-lag", "en": "Reference layer"}, locale),
        "summary": public_field_text(entry.get("summary", entry["function"]), locale),
        "owner_value": public_field_text(entry["description"], locale),
        "touches": public_field_text(entry["data_access"], locale),
        "not_owner": public_localized_text(
            {"da": "Det her modul er kun beskrevet på reference-niveau lige nu.", "en": "This module is only described at reference level right now."},
            locale,
        ),
    }
    payload = dict(fallback)
    payload.update(MODULE_PRESENTATION.get(entry["module_id"], {}))
    return {
        "group": str(payload["group"]),
        "title": public_field_text(payload["title"], locale),
        "audience": public_field_text(payload["audience"], locale),
        "summary": public_field_text(payload["summary"], locale),
        "owner_value": public_field_text(payload["owner_value"], locale),
        "touches": public_field_text(payload["touches"], locale),
        "not_owner": public_field_text(payload["not_owner"], locale),
    }


def provider_presentation(entry: dict, locale: str) -> dict[str, str]:
    fallback = {
        "summary": public_field_text(entry["description"], locale),
        "owner_value": public_localized_text(
            {
                "da": "Den her provider er en del af det nuværende reference-katalog og skal læses som en erklæret modul-kilde, ikke som en marketplace-autoritet.",
                "en": "This provider is part of the current reference catalog and should be read as a declared source of modules, not as a marketplace authority.",
            },
            locale,
        ),
        "what_it_is": public_field_text(entry["description"], locale),
        "what_it_is_not": public_localized_text(
            {"da": "Ikke en certificeringsautoritet og ikke bevis for at alle erklærede moduler er live.", "en": "Not a certification authority and not proof that all declared modules are live."},
            locale,
        ),
        "current_shape": public_localized_text(
            {"da": "En erklæret kilde til de nuværende reference-moduler.", "en": "A declared source of the current reference modules."},
            locale,
        ),
        "not_yet": public_localized_text(
            {"da": "Ikke et bredt vendor-marked eller certificeringslag.", "en": "Not a broad vendor marketplace or certification layer."},
            locale,
        ),
    }
    payload = dict(fallback)
    payload.update(PROVIDER_PRESENTATION.get(entry["provider_id"], {}))
    return {key: public_field_text(value, locale) for key, value in payload.items()}


def provider_state(entry: dict, locale: str) -> tuple[str, str]:
    status = entry["status"]
    if status == "unsigned-reference":
        return (public_localized_text({"da": "Delt reference-stack", "en": "Shared reference stack"}, locale), "state-proof")
    if status == "planned":
        return (public_localized_text({"da": "Planlagt provider", "en": "Planned provider"}, locale), "state-planned")
    return (public_localized_text({"da": "Prototype-provider", "en": "Prototype provider"}, locale), "state-proof")


def provider_focus_modules(entry: dict, modules_by_id: dict[str, dict], *, path_prefix: str, locale: str) -> str:
    preferred = [
        "p4p.catalog.editor",
        "p4p.menu.list",
        "p4p.customer.status",
        "p4p.payment.cash",
    ]
    selected: list[str] = []
    for module_id in preferred + entry["module_ids"]:
        if module_id in selected:
            continue
        module_entry = modules_by_id.get(module_id)
        if module_entry is None:
            continue
        presentation = module_presentation(module_entry, locale)
        if presentation["group"] == "internal":
            continue
        selected.append(module_id)
        if len(selected) == 4:
            break

    items: list[str] = []
    for module_id in selected:
        module_entry = modules_by_id[module_id]
        module_view = module_presentation(module_entry, locale)
        items.append(
            f"""                <li><a href="{escape(localized_detail_page_href(path_prefix, module_id, locale))}">{escape(module_view["title"])}</a> <span>{escape(module_view["summary"])}</span></li>"""
        )
    return "\n".join(items)


def provider_module_groups(entry: dict, modules_by_id: dict[str, dict], *, locale: str) -> str:
    items_by_group: dict[str, list[str]] = {group["id"]: [] for group in MODULE_GROUPS}
    for module_id in entry["module_ids"]:
        module_entry = modules_by_id.get(module_id)
        if module_entry is None:
            continue
        module_view = module_presentation(module_entry, locale)
        state_label, _ = module_state(module_entry, locale)
        items_by_group.setdefault(module_view["group"], []).append(
            f"""            <li><a href="{escape(localized_detail_page_href('../../modules/', module_id, locale))}">{escape(module_view["title"])}</a><span>{escape(module_view["summary"])} {escape(state_label)}.</span></li>"""
        )

    sections: list[str] = []
    for group in MODULE_GROUPS:
        group_items = items_by_group.get(group["id"], [])
        if not group_items:
            continue
        sections.append(
            f"""        <article class="provider-module-group">
          <h3>{escape(public_field_text(group["title"], locale))}</h3>
          <p>{escape(public_field_text(group["intro"], locale))}</p>
          <ul class="provider-module-list">
{chr(10).join(group_items)}
          </ul>
        </article>"""
        )
    return "\n".join(sections)


def render_module_groups(
    modules: list[dict],
    *,
    module_prefix: str,
    provider_prefix: str,
    locale: str,
    open_modules: set[str] | None = None,
) -> str:
    module_lookup = {entry["module_id"]: entry for entry in modules}
    output: list[str] = []
    default_open = {"p4p.menu.list", "p4p.catalog.editor", "p4p.payment.cash"}
    open_module_ids = open_modules if open_modules is not None else default_open

    for group in MODULE_GROUPS:
        items: list[str] = []
        for module_id, mapped in MODULE_PRESENTATION.items():
            if mapped["group"] != group["id"]:
                continue
            entry = module_lookup.get(module_id)
            if entry is None:
                continue
            presentation = module_presentation(entry, locale)
            state_label, state_class = module_state(entry, locale)
            open_attr = " open" if module_id in open_module_ids else ""
            items.append(
                f"""          <details class="module-item {state_class}"{open_attr}>
            <summary>
              <div class="module-summary">
                <div class="module-summary-copy">
                  <p class="module-audience">{escape(presentation["audience"])}</p>
                  <h3>{escape(presentation["title"])}</h3>
                  <p>{escape(presentation["summary"])}</p>
                </div>
                <div class="module-summary-side">
                  <span class="module-state-badge">{escape(state_label)}</span>
                  <span class="module-toggle-hint">{escape(public_ui_text(PIZZA_MODULES_UI, "toggle_hint", locale))}</span>
                </div>
              </div>
            </summary>
            <div class="module-body">
              <p class="module-owner-line"><strong>{escape(public_ui_text(PIZZA_MODULES_UI, "owner_prefix", locale))}</strong> {escape(presentation["owner_value"])}</p>
              <dl>
                <div><dt>{escape(public_ui_text(PIZZA_MODULES_UI, "touches", locale))}</dt><dd>{escape(presentation["touches"])}</dd></div>
                <div><dt>{escape(public_ui_text(PIZZA_MODULES_UI, "does_not_own", locale))}</dt><dd>{escape(presentation["not_owner"])}</dd></div>
                <div><dt>{escape(public_ui_text(PIZZA_MODULES_UI, "current_state", locale))}</dt><dd>{escape(public_field_text(entry["operator_status"], locale))}</dd></div>
                <div><dt>{escape(public_ui_text(PIZZA_MODULES_UI, "technical_id", locale))}</dt><dd><code>{escape(entry["module_id"])}</code></dd></div>
              </dl>
              <p class="module-links">{escape(public_ui_text(PIZZA_MODULES_UI, "more_info", locale))} <a href="{escape(localized_detail_page_href(module_prefix, entry['module_id'], locale))}">{escape(public_ui_text(PIZZA_MODULES_UI, "open_full_module_page", locale))}</a> <span>/</span> <a href="{escape(localized_detail_page_href(provider_prefix, entry['provider_id'], locale))}">{escape(public_ui_text(PIZZA_MODULES_UI, "open_provider_page", locale))}</a> <span>/</span> <a href="{escape(entry["module_manifest_url"])}" rel="noopener noreferrer">{escape(public_ui_text(PIZZA_MODULES_UI, "open_manifest", locale))}</a></p>
            </div>
          </details>"""
            )

        output.append(
            f"""        <section class="module-group">
          <div class="module-group-header">
            <p class="section-kicker">{escape(public_field_text(group["title"], locale))}</p>
            <p>{escape(public_field_text(group["intro"], locale))}</p>
          </div>
          <div class="module-stack">
{chr(10).join(items)}
          </div>
        </section>"""
        )

    return "\n".join(output)


def render_module_route_cards(locale: str) -> str:
    routes = [
        {
            "title": public_ui_text(PIZZA_MODULES_UI, "route_card_1_title", locale),
            "body": public_ui_text(PIZZA_MODULES_UI, "route_card_1_body", locale),
            "links": [
                (public_ui_text(PIZZA_MODULES_UI, "simple_online_menu", locale), "p4p.menu.list"),
                (public_ui_text(PIZZA_MODULES_UI, "order_status_page", locale), "p4p.customer.status"),
            ],
        },
        {
            "title": public_ui_text(PIZZA_MODULES_UI, "route_card_2_title", locale),
            "body": public_ui_text(PIZZA_MODULES_UI, "route_card_2_body", locale),
            "links": [
                (public_ui_text(PIZZA_MODULES_UI, "edit_menu_and_prices", locale), "p4p.catalog.editor"),
                (public_ui_text(PIZZA_MODULES_UI, "kitchen_order_queue", locale), "p4p.kitchen.screen"),
            ],
        },
        {
            "title": public_ui_text(PIZZA_MODULES_UI, "route_card_3_title", locale),
            "body": public_ui_text(PIZZA_MODULES_UI, "route_card_3_body", locale),
            "links": [
                (public_ui_text(PIZZA_MODULES_UI, "pay_at_pickup_cash", locale), "p4p.payment.cash"),
                (public_ui_text(PIZZA_MODULES_UI, "current_provider_page", locale), "../providers/p4p.reference/"),
            ],
        },
    ]
    cards: list[str] = []
    for route in routes:
        link_rows: list[str] = []
        for label, target in route["links"]:
            href = target if target.startswith("../") else f"{target}/"
            link_rows.append(f'<a href="{escape(href)}">{escape(label)}</a>')
        cards.append(
            f"""        <article class="module-route-card">
          <h3>{escape(route["title"])}</h3>
          <p>{escape(route["body"])}</p>
          <div class="source-list">
            {' '.join(link_rows)}
          </div>
        </article>"""
        )
    return "\n".join(cards)


def render_module_read_next(entry: dict, modules_by_id: dict[str, dict], *, locale: str) -> str:
    cards: list[str] = []
    for route in MODULE_READ_NEXT.get(entry["module_id"], []):
        kind = route["kind"]
        if kind == "module":
            target_entry = modules_by_id[route["target"]]
            target_title = module_presentation(target_entry, locale)["title"]
            href = localized_detail_page_href("../", route["target"], locale)
            link_label = public_localized_text({"da": f"Åbn {target_title}", "en": f"Open {target_title}"}, locale)
        elif kind == "provider":
            href = localized_detail_page_href("../../providers/", entry["provider_id"], locale)
            link_label = public_ui_text(PIZZA_MODULES_UI, "open_provider_page", locale)
        else:
            href = localized_static_page_href("../", locale, default_locale="en")
            link_label = public_localized_text({"da": "Åbn modul-katalog", "en": "Open module catalog"}, locale)
        cards.append(
            f"""        <article class="module-route-card">
          <h3>{escape(public_field_text(route["title"], locale))}</h3>
          <p>{escape(public_field_text(route["body"], locale))}</p>
          <div class="source-list">
            <a href="{escape(href)}">{escape(link_label)}</a>
          </div>
        </article>"""
        )
    return "\n".join(cards)


def render_module_reader_cards(repo_url: str, *, locale: str) -> str:
    repo_prefix = f"{repo_url.rstrip('/')}/blob/main/"
    cards = [
        {
            "title": public_ui_text(PIZZA_MODULES_UI, "reader_card_1_title", locale),
            "body": public_ui_text(PIZZA_MODULES_UI, "reader_card_1_body", locale),
            "links": [
                (public_ui_text(PIZZA_MODULES_UI, "open_customer_menu_page", locale), "p4p.menu.list/"),
                (public_ui_text(PIZZA_MODULES_UI, "open_shop_catalog_page", locale), "p4p.catalog.editor/"),
                (public_ui_text(PIZZA_MODULES_UI, "open_simple_payment_page", locale), "p4p.payment.cash/"),
            ],
        },
        {
            "title": public_ui_text(PIZZA_MODULES_UI, "reader_card_2_title", locale),
            "body": public_ui_text(PIZZA_MODULES_UI, "reader_card_2_body", locale),
            "links": [
                (public_ui_text(PIZZA_MODULES_UI, "open_simple_module_guide", locale), f"{repo_prefix}docs/MODULES-START-HERE.md"),
                (public_ui_text(PIZZA_MODULES_UI, "open_builder_guide", locale), f"{repo_prefix}docs/COMMUNITY-MODULES.md"),
                (public_ui_text(PIZZA_MODULES_UI, "open_backup_print_example", locale), "p4p.order.print.backup/"),
            ],
        },
        {
            "title": public_ui_text(PIZZA_MODULES_UI, "reader_card_3_title", locale),
            "body": public_ui_text(PIZZA_MODULES_UI, "reader_card_3_body", locale),
            "links": [
                (public_ui_text(PIZZA_MODULES_UI, "open_review_packet", locale), f"{repo_prefix}REVIEW-ME.md"),
                (public_ui_text(PIZZA_MODULES_UI, "open_payment_boundary_page", locale), "p4p.payment.cash/"),
                (public_ui_text(PIZZA_MODULES_UI, "open_pickup_board_page", locale), "p4p.pickup.board.basic/"),
            ],
        },
    ]
    rendered = []
    for card in cards:
        links = []
        for label, href in card["links"]:
            rel = ' rel="noopener noreferrer"' if href.startswith("http") else ""
            links.append(f'<a href="{escape(href)}"{rel}>{escape(label)}</a>')
        rendered.append(
            f"""        <article class="module-route-card">
          <h3>{escape(card["title"])}</h3>
          <p>{escape(card["body"])}</p>
          <div class="source-list">
            {' <span>/</span> '.join(links)}
          </div>
        </article>"""
        )
    return "\n".join(rendered)


def modules_html(site_data: dict, modules: list[dict], providers: list[dict], *, locale: str) -> str:
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    canonical_url = f'{urls["site"]}modules/' if locale == "en" else f'{urls["site"]}modules/{locale}.html'
    return render_template(
        "modules.html",
        {
            "lang_attr": escape(locale),
            "dir_attr": escape(locale_direction(locale)),
            "generated_comment": f"Generated from P4P module manifests on {datetime.now(timezone.utc).isoformat()}",
            "author_name": escape(contact["name"]),
            "page_title": escape(public_ui_text(PIZZA_MODULES_UI, "page_title_modules", locale)),
            "page_description": escape(public_ui_text(PIZZA_MODULES_UI, "page_description_modules", locale)),
            "page_og_description": escape(public_ui_text(PIZZA_MODULES_UI, "page_description_modules_og", locale)),
            "canonical_url": escape(canonical_url),
            "skip_link": escape(public_ui_text(PIZZA_HOME_UI, "skip", locale)),
            "brand_home_aria": escape(public_ui_text(PIZZA_HOME_UI, "brand_home", locale)),
            "nav_label": escape(public_ui_text(PIZZA_HOME_UI, "nav_label", locale)),
            "nav_home": escape(public_ui_text(PIZZA_MODULES_UI, "nav_home", locale)),
            "nav_providers": escape(public_ui_text(PIZZA_MODULES_UI, "nav_providers", locale)),
            "nav_press_dk": escape(public_ui_text(PIZZA_MODULES_UI, "nav_press_dk", locale)),
            "nav_press_en": escape(public_ui_text(PIZZA_MODULES_UI, "nav_press_en", locale)),
            "nav_proof": escape(public_ui_text(PIZZA_MODULES_UI, "nav_proof", locale)),
            "nav_code": escape(public_ui_text(PIZZA_MODULES_UI, "nav_code", locale)),
            "nav_contact": escape(public_ui_text(PIZZA_HOME_UI, "nav_contact", locale)),
            "locale_switcher_html": render_custom_locale_switcher(
                locale=locale,
                label=public_ui_text(PIZZA_HOME_UI, "locale_label", locale) or "Language",
                href_for_locale=lambda choice_locale: localized_static_page_href("./", choice_locale, default_locale="en"),
            ),
            "site_url": escape(urls["site"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "hero_eyebrow": escape(public_ui_text(PIZZA_MODULES_UI, "hero_eyebrow_modules", locale)),
            "hero_title": escape(public_ui_text(PIZZA_MODULES_UI, "hero_title_modules", locale)),
            "hero_lede": escape(public_ui_text(PIZZA_MODULES_UI, "hero_lede_modules", locale)),
            "hero_action_back_home": escape(public_ui_text(PIZZA_MODULES_UI, "hero_action_back_home", locale)),
            "hero_action_new_here": escape(public_ui_text(PIZZA_MODULES_UI, "hero_action_new_here", locale)),
            "hero_action_provider_pages": escape(public_ui_text(PIZZA_MODULES_UI, "hero_action_provider_pages", locale)),
            "brief_label": escape(public_ui_text(PIZZA_MODULES_UI, "brief_label_scope", locale)),
            "brief_line": escape(public_ui_text(PIZZA_MODULES_UI, "brief_line_modules", locale).format(module_count=len(modules), provider_count=len(providers))),
            "brief_body": escape(public_ui_text(PIZZA_MODULES_UI, "brief_body_modules", locale)),
            "new_here_kicker": escape(public_ui_text(PIZZA_MODULES_UI, "new_here_kicker", locale)),
            "new_here_title": escape(public_ui_text(PIZZA_MODULES_UI, "new_here_title_modules", locale)),
            "new_here_body_1": escape(public_ui_text(PIZZA_MODULES_UI, "new_here_body_modules_1", locale)),
            "new_here_body_2": escape(public_ui_text(PIZZA_MODULES_UI, "new_here_body_modules_2", locale)),
            "module_count": escape(str(len(modules))),
            "provider_count": escape(str(len(providers))),
            "module_reader_cards_html": render_module_reader_cards(urls["repo"], locale=locale),
            "start_kicker": escape(public_ui_text(PIZZA_MODULES_UI, "start_kicker", locale)),
            "start_title": escape(public_ui_text(PIZZA_MODULES_UI, "start_title_modules", locale)),
            "module_route_cards_html": render_module_route_cards(locale),
            "catalog_kicker": escape(public_ui_text(PIZZA_MODULES_UI, "catalog_kicker", locale)),
            "catalog_title": escape(public_ui_text(PIZZA_MODULES_UI, "catalog_title_modules", locale)),
            "catalog_body_1": escape(public_ui_text(PIZZA_MODULES_UI, "catalog_body_modules_1", locale)),
            "catalog_body_2": escape(public_ui_text(PIZZA_MODULES_UI, "catalog_body_modules_2", locale)),
            "current_module_pages": escape(public_ui_text(PIZZA_MODULES_UI, "current_module_pages", locale)),
            "groups_title": escape(public_ui_text(PIZZA_MODULES_UI, "groups_title_modules", locale)),
            "module_groups_html": render_module_groups(
                modules,
                module_prefix="",
                provider_prefix="../providers/",
                locale=locale,
                open_modules={"p4p.menu.list", "p4p.catalog.editor", "p4p.payment.cash", "p4p.customer.status"},
            ),
            "contact_email": escape(contact["email"]),
            "contact_title": escape(public_ui_text(PIZZA_MODULES_UI, "contact_title_modules", locale)),
            "contact_body_1": escape(public_ui_text(PIZZA_MODULES_UI, "contact_body_modules_1", locale)),
            "contact_body_2": escape(public_ui_text(PIZZA_MODULES_UI, "contact_body_modules_2", locale)),
            "contact_body_3": escape(public_ui_text(PIZZA_MODULES_UI, "contact_body_modules_3", locale)),
            "footer_left": escape(public_ui_text(PIZZA_MODULES_UI, "footer_modules_left", locale)),
            "footer_right": escape(public_ui_text(PIZZA_MODULES_UI, "footer_next_gate", locale)),
            "home_href": escape(localized_static_page_href("../", locale, default_locale="en")),
            "providers_href": escape(localized_static_page_href("../providers/", locale, default_locale="en")),
            "press_kit_dk_href": escape(localized_static_page_href("../press-kit/", "da", default_locale="da")),
            "press_kit_en_href": escape(localized_static_page_href("../press-kit/", "en", default_locale="da")),
        },
    )


def module_page_html(site_data: dict, entry: dict, modules_by_id: dict[str, dict], *, locale: str) -> str:
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    presentation = module_presentation(entry, locale)
    state_label, state_class = module_state(entry, locale)
    group = next((group for group in MODULE_GROUPS if group["id"] == presentation["group"]), MODULE_GROUPS[-1])
    canonical_url = (
        f'{urls["site"]}modules/{entry["module_id"]}/'
        if locale == "en"
        else f'{urls["site"]}modules/{entry["module_id"]}/{locale}.html'
    )
    return render_template(
        "module-page.html",
        {
            "lang_attr": escape(locale),
            "dir_attr": escape(locale_direction(locale)),
            "generated_comment": f'Generated module page for {entry["module_id"]} on {datetime.now(timezone.utc).isoformat()}',
            "author_name": escape(contact["name"]),
            "page_title": escape(f'{presentation["title"]} - {public_localized_text({"da": "Pizza4People Modulside", "en": "Pizza4People Module"}, locale)}'),
            "canonical_url": escape(canonical_url),
            "skip_link": escape(public_ui_text(PIZZA_HOME_UI, "skip", locale)),
            "brand_home_aria": escape(public_ui_text(PIZZA_HOME_UI, "brand_home", locale)),
            "nav_label": escape(public_ui_text(PIZZA_HOME_UI, "nav_label", locale)),
            "nav_home": escape(public_ui_text(PIZZA_MODULES_UI, "nav_home", locale)),
            "nav_modules": escape(public_ui_text(PIZZA_MODULES_UI, "nav_modules", locale)),
            "nav_providers": escape(public_ui_text(PIZZA_MODULES_UI, "nav_providers", locale)),
            "nav_press_dk": escape(public_ui_text(PIZZA_MODULES_UI, "nav_press_dk", locale)),
            "nav_press_en": escape(public_ui_text(PIZZA_MODULES_UI, "nav_press_en", locale)),
            "nav_proof": escape(public_ui_text(PIZZA_MODULES_UI, "nav_proof", locale)),
            "nav_code": escape(public_ui_text(PIZZA_MODULES_UI, "nav_code", locale)),
            "nav_contact": escape(public_ui_text(PIZZA_HOME_UI, "nav_contact", locale)),
            "locale_switcher_html": render_custom_locale_switcher(
                locale=locale,
                label=public_ui_text(PIZZA_HOME_UI, "locale_label", locale) or "Language",
                href_for_locale=lambda choice_locale: localized_static_page_href("./", choice_locale, default_locale="en"),
            ),
            "site_url": escape(urls["site"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "module_title": escape(presentation["title"]),
            "module_audience": escape(presentation["audience"]),
            "module_summary": escape(presentation["summary"]),
            "module_owner_value": escape(presentation["owner_value"]),
            "module_touches": escape(presentation["touches"]),
            "module_not_owner": escape(presentation["not_owner"]),
            "module_state": escape(state_label),
            "module_state_class": escape(state_class),
            "module_current_state": escape(public_field_text(entry["operator_status"], locale)),
            "module_id": escape(entry["module_id"]),
            "module_group_title": escape(public_field_text(group["title"], locale)),
            "module_group_intro": escape(public_field_text(group["intro"], locale)),
            "module_data_access": escape(public_field_text(entry["data_access"], locale)),
            "module_read_next_html": render_module_read_next(entry, modules_by_id, locale=locale),
            "module_catalog_url": escape(localized_static_page_href("../", locale, default_locale="en")),
            "module_provider_catalog_url": escape(localized_static_page_href("../../providers/", locale, default_locale="en")),
            "module_provider_page_url": escape(localized_detail_page_href("../../providers/", entry["provider_id"], locale)),
            "module_github_doc_url": escape(entry["module_doc_url"]),
            "module_manifest_url": escape(entry["module_manifest_url"]),
            "module_provider_doc_url": escape(entry["provider_doc_url"]),
            "hero_action_back_catalog": escape(public_localized_text({"da": "Tilbage til modul-katalog", "en": "Back to module catalog"}, locale)),
            "brief_label_for_shop": escape(public_ui_text(PIZZA_PROVIDER_UI, "brief_label_for_shop", locale)),
            "fit_kicker": escape(public_localized_text({"da": "Hvor den passer", "en": "Where it fits"}, locale)),
            "module_explainer": escape(public_localized_text({"da": "Den her side er P4P’s læsbare forklaring af ét modul. Den er lavet til at kunne forstås før du åbner det rå manifest.", "en": "This page is the readable P4P explanation for one module. It is meant to be understandable before you open the raw manifest."}, locale)),
            "touches_kicker": escape(public_ui_text(PIZZA_MODULES_UI, "touches", locale)),
            "not_owner_kicker": escape(public_ui_text(PIZZA_MODULES_UI, "does_not_own", locale)),
            "state_kicker": escape(public_ui_text(PIZZA_MODULES_UI, "current_state", locale)),
            "state_data_access_line": escape(public_localized_text({"da": "Nuværende erklærede data-access-summary:", "en": "Current declared data-access summary:"}, locale)),
            "read_next_kicker": escape(public_localized_text({"da": "Læs næste", "en": "Read next"}, locale)),
            "read_next_title": escape(public_localized_text({"da": "Stop ikke ved én modulside.", "en": "Do not stop at one module page."}, locale)),
            "tech_kicker": escape(public_localized_text({"da": "Teknisk identitet", "en": "Technical identity"}, locale)),
            "tech_body_1": escape(public_localized_text({"da": "Hvis du har brug for udviklerlaget, så åbn GitHub module reference eller det rå manifest. Den offentlige P4P-side holder fokus på hvad modulet betyder operationelt.", "en": "If you need the developer-facing version, open the GitHub module reference or the raw manifest. The public P4P page stays focused on what the module means operationally."}, locale)),
            "open_provider_page_label": escape(public_ui_text(PIZZA_MODULES_UI, "open_provider_page", locale)),
            "open_github_module_reference": escape(public_localized_text({"da": "Åbn GitHub module reference", "en": "Open GitHub module reference"}, locale)),
            "open_github_provider_reference": escape(public_localized_text({"da": "Åbn GitHub provider reference", "en": "Open GitHub provider reference"}, locale)),
            "open_raw_manifest": escape(public_localized_text({"da": "Åbn rå manifest", "en": "Open raw manifest"}, locale)),
            "contact_title": escape(public_localized_text({"da": "Den her modulside er stadig del af den samme smalle proof-fortælling.", "en": "This module page is still part of the same narrow proof story."}, locale)),
            "contact_body_1": escape(public_localized_text({"da": "Spørgsmål om det her modul, provider-laget eller live-pilotgrænsen:", "en": "Questions about this module, the provider layer, or the live-pilot boundary:"}, locale)),
            "contact_body_2": escape(public_ui_text(PIZZA_MODULES_UI, "contact_body_modules_2", locale)),
            "contact_body_3": escape(public_ui_text(PIZZA_MODULES_UI, "contact_body_modules_3", locale)),
            "footer_left": escape(f'Pizza4People / {presentation["title"]}'),
            "footer_right": escape(public_ui_text(PIZZA_MODULES_UI, "footer_next_gate", locale)),
            "home_href": escape(localized_static_page_href("../../", locale, default_locale="en")),
            "press_kit_dk_href": escape(localized_static_page_href("../../press-kit/", "da", default_locale="da")),
            "press_kit_en_href": escape(localized_static_page_href("../../press-kit/", "en", default_locale="da")),
        },
    )


def provider_page_html(site_data: dict, entry: dict, modules_by_id: dict[str, dict], *, locale: str) -> str:
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    presentation = provider_presentation(entry, locale)
    state_label, state_class = provider_state(entry, locale)
    canonical_url = (
        f'{urls["site"]}providers/{entry["provider_id"]}/'
        if locale == "en"
        else f'{urls["site"]}providers/{entry["provider_id"]}/{locale}.html'
    )
    return render_template(
        "provider-page.html",
        {
            "lang_attr": escape(locale),
            "dir_attr": escape(locale_direction(locale)),
            "generated_comment": f'Generated provider page for {entry["provider_id"]} on {datetime.now(timezone.utc).isoformat()}',
            "author_name": escape(contact["name"]),
            "page_title": escape(f'{public_field_text(entry["name"], locale)} - {public_ui_text(PIZZA_PROVIDER_UI, "provider_title_suffix", locale)}'),
            "canonical_url": escape(canonical_url),
            "skip_link": escape(public_ui_text(PIZZA_HOME_UI, "skip", locale)),
            "brand_home_aria": escape(public_ui_text(PIZZA_HOME_UI, "brand_home", locale)),
            "nav_label": escape(public_ui_text(PIZZA_HOME_UI, "nav_label", locale)),
            "nav_home": escape(public_ui_text(PIZZA_MODULES_UI, "nav_home", locale)),
            "nav_modules": escape(public_ui_text(PIZZA_MODULES_UI, "nav_modules", locale)),
            "nav_providers": escape(public_ui_text(PIZZA_MODULES_UI, "nav_providers", locale)),
            "nav_press_dk": escape(public_ui_text(PIZZA_MODULES_UI, "nav_press_dk", locale)),
            "nav_press_en": escape(public_ui_text(PIZZA_MODULES_UI, "nav_press_en", locale)),
            "nav_proof": escape(public_ui_text(PIZZA_MODULES_UI, "nav_proof", locale)),
            "nav_code": escape(public_ui_text(PIZZA_MODULES_UI, "nav_code", locale)),
            "nav_contact": escape(public_ui_text(PIZZA_HOME_UI, "nav_contact", locale)),
            "locale_switcher_html": render_custom_locale_switcher(
                locale=locale,
                label=public_ui_text(PIZZA_HOME_UI, "locale_label", locale) or "Language",
                href_for_locale=lambda choice_locale: localized_static_page_href("./", choice_locale, default_locale="en"),
            ),
            "site_url": escape(urls["site"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "provider_id": escape(entry["provider_id"]),
            "provider_name": escape(public_field_text(entry["name"], locale)),
            "hero_eyebrow": escape(f'{public_ui_text(PIZZA_PROVIDER_UI, "current_tool_source", locale)} / {state_label}'),
            "provider_state_label": escape(state_label),
            "provider_state_class": escape(state_class),
            "provider_status": escape(entry["status"]),
            "provider_summary": escape(presentation["summary"]),
            "provider_owner_value": escape(presentation["owner_value"]),
            "provider_what_it_is": escape(presentation["what_it_is"]),
            "provider_what_it_is_not": escape(presentation["what_it_is_not"]),
            "provider_current_shape": escape(presentation["current_shape"]),
            "provider_not_yet": escape(presentation["not_yet"]),
            "provider_website": escape(entry["website"]),
            "provider_lanes": escape(", ".join(entry["supported_lanes"])),
            "provider_module_count": escape(str(entry["module_count"])),
            "provider_focus_modules_html": provider_focus_modules(
                entry,
                modules_by_id,
                path_prefix="../../modules/",
                locale=locale,
            ),
            "provider_module_groups_html": provider_module_groups(entry, modules_by_id, locale=locale),
            "provider_catalog_url": escape(localized_static_page_href("../", locale, default_locale="en")),
            "provider_doc_url": escape(entry["provider_doc_url"]),
            "provider_manifest_url": escape(entry["provider_manifest_url"]),
            "hero_action_back_catalog": escape(public_ui_text(PIZZA_PROVIDER_UI, "hero_action_back_provider_catalog", locale)),
            "brief_label_for_shop": escape(public_ui_text(PIZZA_PROVIDER_UI, "brief_label_for_shop", locale)),
            "what_it_is_kicker": escape(public_ui_text(PIZZA_PROVIDER_UI, "what_it_is", locale)),
            "what_it_is_not_kicker": escape(public_ui_text(PIZZA_PROVIDER_UI, "what_this_is_not", locale)),
            "state_kicker": escape(public_ui_text(PIZZA_PROVIDER_UI, "what_this_covers_right_now", locale)),
            "for_shop_label": escape(public_ui_text(PIZZA_PROVIDER_UI, "for_shop_strong", locale)),
            "good_first_pages": escape(public_ui_text(PIZZA_PROVIDER_UI, "good_first_pages", locale)),
            "not_yet_label": escape(public_ui_text(PIZZA_PROVIDER_UI, "not_yet", locale)),
            "current_modules_kicker": escape(public_ui_text(PIZZA_PROVIDER_UI, "current_modules", locale)),
            "provider_modules_title": escape(public_ui_text(PIZZA_PROVIDER_UI, "provider_modules_title", locale)),
            "technical_record": escape(public_ui_text(PIZZA_PROVIDER_UI, "technical_record", locale)),
            "status_label": escape(public_ui_text(PIZZA_PROVIDER_UI, "status", locale)),
            "supported_lanes_label": escape(public_ui_text(PIZZA_PROVIDER_UI, "supported_lanes", locale)),
            "module_count_label": escape(public_ui_text(PIZZA_PROVIDER_UI, "module_count_label", locale)),
            "website_label": escape(public_ui_text(PIZZA_PROVIDER_UI, "website", locale)),
            "provider_readable_surface": escape(public_ui_text(PIZZA_PROVIDER_UI, "provider_readable_surface", locale)),
            "back_to_provider_catalog": escape(public_ui_text(PIZZA_PROVIDER_UI, "back_to_provider_catalog", locale)),
            "github_provider_reference": escape(public_ui_text(PIZZA_PROVIDER_UI, "github_provider_reference", locale)),
            "open_raw_provider_manifest": escape(public_ui_text(PIZZA_PROVIDER_UI, "open_raw_provider_manifest", locale)),
            "contact_title": escape(public_ui_text(PIZZA_PROVIDER_UI, "contact_title_provider_detail", locale)),
            "contact_body_1": escape(public_ui_text(PIZZA_PROVIDER_UI, "contact_body_provider_detail_1", locale)),
            "contact_body_2": escape(public_ui_text(PIZZA_MODULES_UI, "contact_body_modules_2", locale)),
            "contact_body_3": escape(public_ui_text(PIZZA_MODULES_UI, "contact_body_modules_3", locale)),
            "footer_left": escape(f'Pizza4People / {public_field_text(entry["name"], locale)}'),
            "footer_right": escape(public_ui_text(PIZZA_MODULES_UI, "footer_next_gate", locale)),
            "home_href": escape(localized_static_page_href("../../", locale, default_locale="en")),
            "modules_href": escape(localized_static_page_href("../../modules/", locale, default_locale="en")),
            "press_kit_dk_href": escape(localized_static_page_href("../../press-kit/", "da", default_locale="da")),
            "press_kit_en_href": escape(localized_static_page_href("../../press-kit/", "en", default_locale="da")),
        },
    )


def render_providers(providers: list[dict], modules_by_id: dict[str, dict], *, locale: str) -> str:
    cards = []
    for index, entry in enumerate(providers):
        presentation = provider_presentation(entry, locale)
        state_label, state_class = provider_state(entry, locale)
        open_attr = " open" if index == 0 else ""
        cards.append(
            f"""        <details class="module-item provider-item {escape(state_class)}"{open_attr}>
          <summary>
            <div class="module-summary">
              <div class="module-summary-copy">
                <p class="module-audience">{escape(public_ui_text(PIZZA_PROVIDER_UI, "current_tool_source", locale))}</p>
            <h3>{escape(public_field_text(entry["name"], locale))}</h3>
                <p>{escape(presentation["summary"])}</p>
              </div>
              <div class="module-summary-side">
                <span class="module-state-badge">{escape(state_label)}</span>
                <span class="module-toggle-hint">{escape(public_ui_text(PIZZA_MODULES_UI, "toggle_hint", locale))}</span>
              </div>
            </div>
          </summary>
          <div class="module-body">
            <p class="module-owner-line"><strong>{escape(public_ui_text(PIZZA_MODULES_UI, "owner_prefix", locale))}</strong> {escape(presentation["owner_value"])}</p>
            <dl>
              <div><dt>{escape(public_localized_text({"da": "Nuværende form", "en": "Current shape"}, locale))}</dt><dd>{escape(presentation["current_shape"])}</dd></div>
              <div><dt>{escape(public_ui_text(PIZZA_PROVIDER_UI, "what_this_is_not", locale))}</dt><dd>{escape(presentation["not_yet"])}</dd></div>
              <div><dt>{escape(public_ui_text(PIZZA_PROVIDER_UI, "module_count_label", locale))}</dt><dd>{escape(str(entry["module_count"]))}</dd></div>
              <div><dt>{escape(public_ui_text(PIZZA_MODULES_UI, "technical_id", locale))}</dt><dd><code>{escape(entry["provider_id"])}</code></dd></div>
            </dl>
            <div class="provider-focus">
              <p class="provider-focus-label">{escape(public_ui_text(PIZZA_PROVIDER_UI, "good_first_pages", locale))}</p>
              <ul class="provider-focus-list">
{provider_focus_modules(entry, modules_by_id, path_prefix="../modules/", locale=locale)}
              </ul>
            </div>
            <p class="module-links">{escape(public_ui_text(PIZZA_MODULES_UI, "more_info", locale))} <a href="{escape(localized_detail_page_href('', entry['provider_id'], locale))}">{escape(public_ui_text(PIZZA_PROVIDER_UI, "open_full_provider_page", locale))}</a> <span>/</span> <a href="{escape(entry["provider_doc_url"])}" rel="noopener noreferrer">{escape(public_ui_text(PIZZA_PROVIDER_UI, "github_provider_reference", locale))}</a> <span>/</span> <a href="{escape(entry["provider_manifest_url"])}" rel="noopener noreferrer">{escape(public_ui_text(PIZZA_PROVIDER_UI, "open_provider_manifest", locale))}</a></p>
          </div>
        </details>"""
        )
    return "\n".join(cards)


def render_trace(items: list[object], *, locale: str) -> str:
    return "\n".join(f'          <span role="listitem">{escape(public_field_text(item, locale))}</span>' for item in items)


def render_gate(items: list[dict], *, locale: str) -> str:
    rendered = []
    for item in items:
        checked = " checked" if item["done"] else ""
        rendered.append(
            f'        <label><input type="checkbox"{checked} disabled> {escape(public_field_text(item["label"], locale))}</label>'
        )
    return "\n".join(rendered)


def render_roadmap(items: list[object], *, locale: str) -> str:
    rows = []
    for item in items:
        localized_item = public_field_text(item, locale)
        number, body = localized_item.split(". ", 1)
        rows.append(f"        <li><strong>{escape(number)}.</strong> {escape(body)}</li>")
    return "\n".join(rows)


def render_press_badges(labels: list[object], *, locale: str) -> str:
    output = []
    for label in labels:
        text = public_field_text(label, locale)
        badge_class = " warn" if "Ikke" in text or "Not" in text else ""
        output.append(f'            <span class="badge{badge_class}">{escape(text)}</span>')
    return "\n".join(output)


def render_press_points(points: list[object], *, locale: str, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    inner = "\n".join(f"            <li>{escape(public_field_text(point, locale))}</li>" for point in points)
    return f"<{tag}>\n{inner}\n          </{tag}>"


def render_press_angles(items: list[dict], *, locale: str) -> str:
    cards = []
    for item in items:
        cards.append(
            f"""        <div class="card">
          <h3>{escape(public_field_text(item["title"], locale))}</h3>
          <p>{escape(public_field_text(item["body"], locale))}</p>
        </div>"""
        )
    return "\n".join(cards)


def render_press_module_cards(*, locale: str) -> str:
    cards = []
    open_label = public_localized_text(
        {
            "da": "Åbn modulsiden",
            "sv": "Öppna modulsidan",
            "tr": "Modül sayfasını aç",
            "ar": "افتح صفحة الوحدة",
            "ku": "Rûpela modulê veke",
            "en": "Open module page",
        },
        locale,
    )
    for item in PRESS_MODULE_SPOTLIGHTS:
        module_id = item["module_id"]
        cards.append(
            f"""        <div class="card">
          <h3>{escape(public_field_text(item["title"], locale))}</h3>
          <p>{escape(public_field_text(item["body"], locale))}</p>
          <div class="source-list">
            <a href="../modules/{escape(module_id)}/">{escape(open_label)}</a>
          </div>
        </div>"""
        )
    return "\n".join(cards)


def homepage_html(
    site_data: dict,
    modules: list[dict],
    providers: list[dict],
    *,
    locale: str,
    screenshot_pack: dict[str, object],
) -> str:
    home = site_data["homepage"]
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    next_gate_entries = screenshot_entries(
        screenshot_pack,
        "pizza_home",
        locale=locale,
        asset_prefix="assets/screenshots/",
    )
    canonical_url = urls["site"] if locale == "en" else f'{urls["site"]}{locale}.html'
    return render_template(
        "homepage.html",
        {
            "lang_attr": escape(locale),
            "dir_attr": escape(locale_direction(locale)),
            "generated_comment": f"Generated from site-data + P4P/modules on {datetime.now(timezone.utc).isoformat()}",
            "author_name": escape(contact["name"]),
            "page_title": escape(public_ui_text(PIZZA_HOME_UI, "page_title", locale)),
            "page_description": escape(public_ui_text(PIZZA_HOME_UI, "page_description", locale)),
            "canonical_url": escape(canonical_url),
            "og_title": escape(public_ui_text(PIZZA_HOME_UI, "page_title", locale)),
            "og_description": escape(public_ui_text(PIZZA_HOME_UI, "og_description", locale)),
            "skip_link": escape(public_ui_text(PIZZA_HOME_UI, "skip", locale)),
            "brand_home_aria": escape(public_ui_text(PIZZA_HOME_UI, "brand_home", locale)),
            "nav_label": escape(public_ui_text(PIZZA_HOME_UI, "nav_label", locale)),
            "nav_owner": escape(public_ui_text(PIZZA_HOME_UI, "nav_owner", locale)),
            "nav_proof": escape(public_ui_text(PIZZA_HOME_UI, "nav_proof", locale)),
            "nav_modules": escape(public_ui_text(PIZZA_HOME_UI, "nav_modules", locale)),
            "nav_story": escape(public_ui_text(PIZZA_HOME_UI, "nav_story", locale)),
            "nav_providers": escape(public_ui_text(PIZZA_HOME_UI, "nav_providers", locale)),
            "nav_press": escape(public_ui_text(PIZZA_HOME_UI, "nav_press", locale)),
            "nav_contact": escape(public_ui_text(PIZZA_HOME_UI, "nav_contact", locale)),
            "locale_switcher_html": render_locale_switcher(kind="home", locale=locale, ui=PIZZA_HOME_UI),
            "site_url": escape(urls["site"]),
            "hero_eyebrow": escape(public_field_text(home["eyebrow"], locale)),
            "hero_title": escape(public_field_text(home["title"], locale)),
            "hero_lede": escape(public_field_text(home["lede"], locale)),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "hero_shape_label": escape(public_ui_text(PIZZA_HOME_UI, "hero_shape_label", locale)),
            "hero_tag_public": escape(public_ui_text(PIZZA_HOME_UI, "hero_tag_public", locale)),
            "hero_tag_pilot": escape(public_ui_text(PIZZA_HOME_UI, "hero_tag_pilot", locale)),
            "hero_tag_not_marketplace": escape(public_ui_text(PIZZA_HOME_UI, "hero_tag_not_marketplace", locale)),
            "hero_action_owner": escape(public_ui_text(PIZZA_HOME_UI, "hero_action_owner", locale)),
            "hero_action_proof": escape(public_ui_text(PIZZA_HOME_UI, "hero_action_proof", locale)),
            "hero_action_code": escape(public_ui_text(PIZZA_HOME_UI, "hero_action_code", locale)),
            "hero_more_routes": escape(public_ui_text(PIZZA_HOME_UI, "hero_more_routes", locale)),
            "hero_route_story": escape(public_ui_text(PIZZA_HOME_UI, "hero_route_story", locale)),
            "hero_route_proof": escape(public_ui_text(PIZZA_HOME_UI, "hero_route_proof", locale)),
            "hero_route_broader": escape(public_ui_text(PIZZA_HOME_UI, "hero_route_broader", locale)),
            "hero_route_press_da": escape(public_ui_text(PIZZA_HOME_UI, "hero_route_press_da", locale)),
            "hero_route_press_en": escape(public_ui_text(PIZZA_HOME_UI, "hero_route_press_en", locale)),
            "proof_figure_alt": escape(public_ui_text(PIZZA_HOME_UI, "proof_figure_alt", locale)),
            "proof_figure_caption": escape(public_ui_text(PIZZA_HOME_UI, "proof_figure_caption", locale)),
            "notice": escape(public_field_text(home["notice"], locale)),
            "source_label": escape(public_ui_text(PIZZA_HOME_UI, "source_label", locale)),
            "owner_kicker": escape(public_ui_text(PIZZA_HOME_UI, "owner_kicker", locale)),
            "owner_title": escape(public_ui_text(PIZZA_HOME_UI, "owner_title", locale)),
            "owner_body": escape(public_ui_text(PIZZA_HOME_UI, "owner_body", locale)),
            "just_eat_source_url": escape(urls["just_eat_source"]),
            "owner_cards_html": render_owner_cards(),
            "press_heading": escape(public_field_text(home["press_heading"], locale)),
            "press_lede": escape(public_field_text(home["press_lede"], locale)),
            "press_facts_html": render_press_facts(home["press_facts"], urls, locale=locale),
            "modules_kicker": escape(public_ui_text(PIZZA_HOME_UI, "modules_kicker", locale)),
            "modules_title": escape(public_ui_text(PIZZA_HOME_UI, "modules_title", locale)),
            "modules_body_1": escape(public_ui_text(PIZZA_HOME_UI, "modules_body_1", locale)),
            "modules_body_2": escape(public_ui_text(PIZZA_HOME_UI, "modules_body_2", locale)),
            "modules_body_3": escape(public_ui_text(PIZZA_HOME_UI, "modules_body_3", locale)),
            "modules_body_4": escape(public_ui_text(PIZZA_HOME_UI, "modules_body_4", locale)),
            "modules_body_5": escape(public_ui_text(PIZZA_HOME_UI, "modules_body_5", locale).format(provider_count=len(providers))),
            "modules_link_new_here": escape(public_ui_text(PIZZA_HOME_UI, "modules_link_new_here", locale)),
            "modules_link_catalog": escape(public_ui_text(PIZZA_HOME_UI, "modules_link_catalog", locale)),
            "modules_link_providers": escape(public_ui_text(PIZZA_HOME_UI, "modules_link_providers", locale)),
            "story_kicker": escape(public_ui_text(PIZZA_HOME_UI, "story_kicker", locale)),
            "story_heading": escape(public_field_text(home["story_heading"], locale)),
            "story_body": escape(public_field_text(home["story_body"], locale)),
            "brief_label": escape(public_ui_text(PIZZA_HOME_UI, "brief_label", locale)),
            "one_sentence": escape(public_field_text(home["one_sentence"], locale)),
            "plain_kicker": escape(public_ui_text(PIZZA_HOME_UI, "plain_kicker", locale)),
            "plain_title": escape(public_ui_text(PIZZA_HOME_UI, "plain_title", locale)),
            "plain_cards_html": render_plain_cards(home["plain_demo"], locale=locale),
            "problem_kicker": escape(public_ui_text(PIZZA_HOME_UI, "problem_kicker", locale)),
            "problem_heading": escape(public_field_text(home["problem_heading"], locale)),
            "problem_body_1": escape(public_field_text(home["problem_body"][0], locale)),
            "problem_body_2": escape(public_field_text(home["problem_body"][1], locale)),
            "proof_kicker": escape(public_ui_text(PIZZA_HOME_UI, "proof_kicker", locale)),
            "proof_title": escape(public_ui_text(PIZZA_HOME_UI, "proof_title", locale)),
            "proof_steps_html": render_proof_steps(home["proof_steps"], locale=locale),
            "takeaway_kicker": escape(public_ui_text(PIZZA_HOME_UI, "takeaway_kicker", locale)),
            "takeaway_heading": escape(public_field_text(home["takeaway_heading"], locale)),
            "takeaway_body": escape(public_field_text(home["takeaway_body"], locale)),
            "proves_kicker": escape(public_ui_text(PIZZA_HOME_UI, "proves_kicker", locale)),
            "proves_list_html": render_list_items(home["proves"], locale=locale),
            "not_proves_kicker": escape(public_ui_text(PIZZA_HOME_UI, "not_proves_kicker", locale)),
            "does_not_prove_list_html": render_list_items(home["does_not_prove"], locale=locale),
            "trust_kicker": escape(public_ui_text(PIZZA_HOME_UI, "trust_kicker", locale)),
            "trust_heading": escape(public_field_text(home["trust_heading"], locale)),
            "trust_body": escape(public_field_text(home["trust_body"], locale)),
            "trace_html": render_trace(home["trace"], locale=locale),
            "module_groups_html": render_module_groups(
                modules,
                module_prefix="modules/",
                provider_prefix="providers/",
                locale=locale,
                open_modules={"p4p.menu.list", "p4p.catalog.editor", "p4p.payment.cash"},
            ),
            "provider_count": escape(str(len(providers))),
            "gate_kicker": escape(public_ui_text(PIZZA_HOME_UI, "gate_kicker", locale)),
            "proof_gate_heading": escape(public_field_text(home["proof_gate_heading"], locale)),
            "gate_html": render_gate(home["proof_gate"], locale=locale),
            "roadmap_kicker": escape(public_ui_text(PIZZA_HOME_UI, "roadmap_kicker", locale)),
            "roadmap_title": escape(public_ui_text(PIZZA_HOME_UI, "roadmap_title", locale)),
            "roadmap_html": render_roadmap(home["roadmap"], locale=locale),
            "pilot_kicker": escape(public_ui_text(PIZZA_HOME_UI, "pilot_kicker", locale)),
            "pilot_title": escape(public_ui_text(PIZZA_HOME_UI, "pilot_title", locale)),
            "pilot_lede": escape(public_ui_text(PIZZA_HOME_UI, "pilot_lede", locale)),
            "pilot_gallery_html": render_screenshot_cards(next_gate_entries, card_class="screenshot-card compact"),
            "contact_email": escape(contact["email"]),
            "contact_kicker": escape(public_ui_text(PIZZA_HOME_UI, "contact_kicker", locale)),
            "contact_title": escape(public_ui_text(PIZZA_HOME_UI, "contact_title", locale)),
            "contact_line": escape(public_ui_text(PIZZA_HOME_UI, "contact_line", locale)),
            "contact_source_label": escape(public_ui_text(PIZZA_HOME_UI, "contact_source_label", locale)),
            "contact_broader_label": escape(public_ui_text(PIZZA_HOME_UI, "contact_broader_label", locale)),
            "contact_fine_print": escape(public_ui_text(PIZZA_HOME_UI, "contact_fine_print", locale)),
            "footer_status": escape(public_field_text(home["footer_status"], locale)),
        },
    )


def press_kit_html(
    site_data: dict,
    modules: list[dict],
    providers: list[dict],
    *,
    locale: str,
    screenshot_pack: dict[str, object],
) -> str:
    data = site_data["press_kit"]["dk" if locale == "da" else "en"]
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    press_entries = screenshot_entries(
        screenshot_pack,
        "pizza_press",
        locale=locale,
        asset_prefix="../assets/screenshots/",
    )
    canonical_url = urls["press_kit_dk"] if locale == "da" else f'{urls["site"]}press-kit/{locale}.html'
    return render_template(
        "press-kit.html",
        {
            "lang_attr": escape(locale),
            "dir_attr": escape(locale_direction(locale)),
            "author_name": escape(contact["name"]),
            "page_title": escape("Pizza4People Pressekit" if locale == "da" else "Pizza4People Press Kit"),
            "page_description": escape(
                public_localized_text(
                    {
                        "da": "Kort pressekit for Pizza4People: et offentligt open-protocol proof for direkte restaurant-kunde discovery og ordering.",
                        "en": "Press kit for Pizza4People: an open protocol proof for direct restaurant-customer discovery and ordering.",
                    },
                    locale,
                )
            ),
            "canonical_url": escape(canonical_url),
            "press_style": load_text(TEMPLATE_ROOT / "press-style.css").strip(),
            "locale_switcher_html": render_locale_switcher(kind="press", locale=locale, ui=PIZZA_HOME_UI),
            "topbar_label": escape(public_field_text(data["topbar_label"], locale)),
            "date_label": escape(public_field_text(data["date_label"], locale)),
            "kicker": escape(public_field_text(data["kicker"], locale)),
            "headline": escape(public_field_text(data["headline"], locale)),
            "lede": escape(public_field_text(data["lede"], locale)),
            "badges_html": render_press_badges(data["badges"], locale=locale),
            "quote": escape(public_field_text(data["quote"], locale)),
            "contact_name": escape(contact["name"]),
            "contact_org": escape(contact["org"]),
            "contact_email": escape(contact["email"]),
            "why_now_label": escape(public_localized_text({"da": "Hvorfor nu", "en": "Why now"}, locale)),
            "why_now_heading": escape(public_field_text(data["why_now_heading"], locale)),
            "why_now_body_html": "\n".join(
                f"          <p>{escape(public_field_text(paragraph, locale))}</p>" for paragraph in data["why_now_body"]
            ),
            "journalist_box_label": escape(
                public_localized_text(
                    {"da": "Hvad en journalist kan skrive nu", "en": "What can be written now"},
                    locale,
                )
            ),
            "journalist_bullets_html": render_press_points(data["journalist_bullets"], locale=locale),
            "source_note": escape(public_field_text(data["source_note"], locale)),
            "system_label": escape(public_localized_text({"da": "Systemet på én side", "en": "System in one page"}, locale)),
            "system_heading": escape(public_field_text(data["system_heading"], locale)),
            "diagram_core_flow": escape(public_ui_text(PIZZA_PRESS_UI, "diagram_core_flow", locale)),
            "client_label": escape(public_ui_text(PIZZA_PRESS_UI, "client_label", locale)),
            "client_flow_text": escape(
                public_localized_text(
                    {"da": "Finder restauranter, viser menu, sender ordre.", "en": "Finds restaurants, renders menus, sends orders."},
                    locale,
                )
            ),
            "registry_label": escape(public_ui_text(PIZZA_PRESS_UI, "registry_label", locale)),
            "registry_flow_text": escape(
                public_localized_text(
                    {"da": "Discovery, heartbeat, offentlig node-metadata.", "en": "Discovery, heartbeat and public node metadata."},
                    locale,
                )
            ),
            "node_flow_label": escape(public_localized_text({"da": "Restaurant node", "en": "Restaurant node"}, locale)),
            "node_flow_text": escape(
                public_localized_text(
                    {"da": "Menu, ordreendpoint, status, identitet og operator-kontrol.", "en": "Menu, order endpoint, status, identity and operator control."},
                    locale,
                )
            ),
            "flow_caption": escape(
                public_localized_text(
                    {"da": "Registry bruges til discovery. Menu og ordre går direkte fra client til restaurant node.", "en": "Registry is used for discovery. Menu and order flow go directly from client to restaurant node."},
                    locale,
                )
            ),
            "layers_label": escape(public_localized_text({"da": "Lagene", "en": "Layers"}, locale)),
            "layers_heading": escape(public_field_text(data["layers_heading"], locale)),
            "module_intro": escape(
                public_localized_text(
                    {
                        "da": "Her er den korte butikslæsning af den nuværende stack. De fulde modul- og providersider ligger på selve Pizza4People-sitet.",
                        "en": "This is the short shop-owner reading of the current stack. Full module and provider pages live on the Pizza4People site itself.",
                    },
                    locale,
                )
            ),
            "module_cards_html": render_press_module_cards(locale=locale),
            "module_footer_html": (
                f'Fuld lokal læsesti: <a href="{escape(urls["site"])}modules/p4p.menu.list/">modulsider</a> og '
                f'<a href="{escape(urls["site"])}providers/">providersider</a>.'
                if locale == "da"
                else f'Full local reading path: <a href="{escape(urls["site"])}modules/p4p.menu.list/">module pages</a> and '
                f'<a href="{escape(urls["site"])}providers/">provider pages</a>.'
            ),
            "status_label": escape(public_localized_text({"da": "Nuværende status", "en": "Current status"}, locale)),
            "status_heading": escape(public_field_text(data["status_heading"], locale)),
            "current_status_title": escape(public_field_text(data["current_status_title"], locale)),
            "current_status_items_html": render_press_points(data["current_status_items"], locale=locale),
            "next_test_title": escape(public_field_text(data["next_test_title"], locale)),
            "next_test_items_html": render_press_points(data["next_test_items"], locale=locale, ordered=True),
            "pilot_topology": escape(public_ui_text(PIZZA_PRESS_UI, "pilot_topology", locale)),
            "primary_registry_label": escape(public_ui_text(PIZZA_PRESS_UI, "primary_registry", locale)),
            "backup_registry_label": escape(public_ui_text(PIZZA_PRESS_UI, "backup_registry", locale)),
            "screenshots_label": escape(public_localized_text({"da": "Pilot-flader", "en": "Pilot surfaces"}, locale)),
            "screenshots_heading": escape(
                public_localized_text(
                    {"da": "Sådan ser den lokale node ud i den kontrollerede pilot", "en": "What the local node looks like in the controlled pilot"},
                    locale,
                )
            ),
            "screenshots_lede": escape(
                public_localized_text(
                    {
                        "da": "Det her er ikke det nuværende v0.1-proof. Det er den næste gate: de lokale driftsrum og modulflader, som restauranten selv kontrollerer.",
                        "en": "This is not the current v0.1 proof. It is the next gate: the local control rooms and module surfaces the restaurant owns itself.",
                    },
                    locale,
                )
            ),
            "screenshots_html": render_screenshot_cards(press_entries, card_class="press-screenshot-card"),
            "primary_registry_text": escape(public_localized_text({"da": "Første discovery-endpoint.", "en": "First discovery endpoint."}, locale)),
            "backup_registry_text": escape(public_localized_text({"da": "Separat server, så discovery kan failover.", "en": "Separate server for discovery failover."}, locale)),
            "pilot_node_label": escape("Restaurant-owned node"),
            "pilot_node_text": escape(
                public_localized_text(
                    {"da": "Menu, order mode, order state og operator-kontrol.", "en": "Menu, order mode, order state and operator control."},
                    locale,
                )
            ),
            "pilot_client_text": escape(
                public_localized_text(
                    {"da": "Finder via registry. Taler direkte med node efter discovery.", "en": "Finds via registry. Talks directly to node after discovery."},
                    locale,
                )
            ),
            "verification_label": escape(public_localized_text({"da": "Teknisk verifikation", "en": "Technical verification"}, locale)),
            "verification_heading": escape(public_field_text(data["verification_heading"], locale)),
            "verification_body_html": "\n".join(
                f"          <p>{escape(public_field_text(paragraph, locale))}</p>"
                for paragraph in data["verification_body"]
            ),
            "press_angles_label": escape(public_localized_text({"da": "Pressevinkler", "en": "Press angles"}, locale)),
            "press_angles_heading": escape(public_field_text(data["press_angles_heading"], locale)),
            "press_angles_html": render_press_angles(data["press_angles"], locale=locale),
            "site_url": escape(urls["site"]),
            "umbrella_url": escape(urls["umbrella"]),
            "repo_url": escape(urls["repo"]),
            "just_eat_source_url": escape(urls["just_eat_source"]),
            "minimum_api_label": escape(public_ui_text(PIZZA_PRESS_UI, "minimum_api", locale)),
            "checker_label": escape(public_ui_text(PIZZA_PRESS_UI, "checker", locale)),
            "contact_card_label": escape(public_ui_text(PIZZA_PRESS_UI, "contact_card", locale)),
            "links_card_label": escape(public_ui_text(PIZZA_PRESS_UI, "links_card", locale)),
            "download_da_label": escape(public_ui_text(PIZZA_PRESS_UI, "download_da", locale)),
            "download_en_label": escape(public_ui_text(PIZZA_PRESS_UI, "download_en", locale)),
            "provider_catalog_label": escape(public_ui_text(PIZZA_PRESS_UI, "provider_catalog", locale)),
            "source_link_label": escape(public_ui_text(PIZZA_PRESS_UI, "source_link", locale)),
            "status_line": escape(public_field_text(data["status_line"], locale)),
        },
    )


def providers_html(site_data: dict, providers: list[dict], modules_by_id: dict[str, dict], *, locale: str) -> str:
    urls = site_data["canonical_urls"]
    contact = site_data["contact"]
    canonical_url = f'{urls["site"]}providers/' if locale == "en" else f'{urls["site"]}providers/{locale}.html'
    return render_template(
        "providers.html",
        {
            "lang_attr": escape(locale),
            "dir_attr": escape(locale_direction(locale)),
            "generated_comment": f"Generated from P4P provider manifests on {datetime.now(timezone.utc).isoformat()}",
            "author_name": escape(contact["name"]),
            "page_title": escape(public_ui_text(PIZZA_PROVIDER_UI, "page_title_providers", locale)),
            "page_description": escape(public_ui_text(PIZZA_PROVIDER_UI, "page_description_providers", locale)),
            "page_og_description": escape(public_ui_text(PIZZA_PROVIDER_UI, "page_description_providers_og", locale)),
            "canonical_url": escape(canonical_url),
            "skip_link": escape(public_ui_text(PIZZA_HOME_UI, "skip", locale)),
            "brand_home_aria": escape(public_ui_text(PIZZA_HOME_UI, "brand_home", locale)),
            "nav_label": escape(public_ui_text(PIZZA_HOME_UI, "nav_label", locale)),
            "nav_home": escape(public_ui_text(PIZZA_MODULES_UI, "nav_home", locale)),
            "nav_modules": escape(public_ui_text(PIZZA_MODULES_UI, "nav_modules", locale)),
            "nav_press_dk": escape(public_ui_text(PIZZA_MODULES_UI, "nav_press_dk", locale)),
            "nav_press_en": escape(public_ui_text(PIZZA_MODULES_UI, "nav_press_en", locale)),
            "nav_proof": escape(public_ui_text(PIZZA_MODULES_UI, "nav_proof", locale)),
            "nav_code": escape(public_ui_text(PIZZA_MODULES_UI, "nav_code", locale)),
            "nav_contact": escape(public_ui_text(PIZZA_HOME_UI, "nav_contact", locale)),
            "locale_switcher_html": render_custom_locale_switcher(
                locale=locale,
                label=public_ui_text(PIZZA_HOME_UI, "locale_label", locale) or "Language",
                href_for_locale=lambda choice_locale: localized_static_page_href("./", choice_locale, default_locale="en"),
            ),
            "site_url": escape(urls["site"]),
            "repo_url": escape(urls["repo"]),
            "repo_proof_url": escape(urls["repo_proof"]),
            "umbrella_url": escape(urls["umbrella"]),
            "provider_count": escape(str(len(providers))),
            "providers_html": render_providers(providers, modules_by_id, locale=locale),
            "contact_email": escape(contact["email"]),
            "hero_eyebrow": escape(public_ui_text(PIZZA_PROVIDER_UI, "hero_eyebrow_providers", locale)),
            "hero_title": escape(public_ui_text(PIZZA_PROVIDER_UI, "hero_title_providers", locale)),
            "hero_lede": escape(public_ui_text(PIZZA_PROVIDER_UI, "hero_lede_providers", locale)),
            "hero_action_module_catalog": escape(public_ui_text(PIZZA_PROVIDER_UI, "hero_action_module_catalog", locale)),
            "hero_action_broader": escape(public_ui_text(PIZZA_PROVIDER_UI, "hero_action_broader", locale)),
            "brief_label": escape(public_ui_text(PIZZA_PROVIDER_UI, "brief_label_reality", locale)),
            "brief_line": escape(public_ui_text(PIZZA_PROVIDER_UI, "brief_line_providers", locale).format(provider_count=len(providers))),
            "brief_body": escape(public_ui_text(PIZZA_PROVIDER_UI, "brief_body_providers", locale)),
            "providers_kicker": escape(public_ui_text(PIZZA_PROVIDER_UI, "providers_kicker", locale)),
            "providers_title": escape(public_ui_text(PIZZA_PROVIDER_UI, "providers_title", locale)),
            "providers_body_1": escape(public_ui_text(PIZZA_PROVIDER_UI, "providers_body_1", locale)),
            "providers_body_2": escape(public_ui_text(PIZZA_PROVIDER_UI, "providers_body_2", locale)),
            "current_catalog": escape(public_ui_text(PIZZA_PROVIDER_UI, "current_catalog", locale)),
            "provider_cards_title": escape(public_ui_text(PIZZA_PROVIDER_UI, "provider_cards_title", locale)),
            "contact_title": escape(public_ui_text(PIZZA_PROVIDER_UI, "contact_title_providers", locale)),
            "contact_body_1": escape(public_ui_text(PIZZA_PROVIDER_UI, "contact_body_providers_1", locale)),
            "contact_body_2": escape(public_ui_text(PIZZA_PROVIDER_UI, "contact_body_providers_2", locale)),
            "contact_body_3": escape(public_ui_text(PIZZA_PROVIDER_UI, "contact_body_providers_3", locale)),
            "footer_left": escape(public_ui_text(PIZZA_PROVIDER_UI, "footer_providers_left", locale)),
            "footer_right": escape(public_ui_text(PIZZA_MODULES_UI, "footer_next_gate", locale)),
            "home_href": escape(localized_static_page_href("../", locale, default_locale="en")),
            "modules_href": escape(localized_static_page_href("../modules/", locale, default_locale="en")),
            "press_kit_dk_href": escape(localized_static_page_href("../press-kit/", "da", default_locale="da")),
            "press_kit_en_href": escape(localized_static_page_href("../press-kit/", "en", default_locale="da")),
        },
    )


def write_protocols_module_catalog(*, screenshot_pack: dict[str, object]) -> None:
    catalog_payload = public_module_catalog(urls=PUBLIC_CATALOG_URLS)
    catalog_payload["screenshot_sections"] = {
        "protocols_catalog": screenshot_payload_entries(screenshot_pack, "protocols_catalog"),
        "protocols_shop": screenshot_payload_entries(screenshot_pack, "protocols_shop"),
    }
    write_text(
        PROTOCOLS_ROOT / "modules.json",
        json.dumps(catalog_payload, ensure_ascii=False, indent=2) + "\n",
    )
    write_text(
        PROTOCOLS_ROOT / "modules/index.html",
        protocols_modules_shell(
            page_kind="catalog",
            page_title="Protocols4People Modules",
            base_path="../",
            payload=catalog_payload,
        ),
    )
    write_text(
        PROTOCOLS_ROOT / "modules/shop/index.html",
        protocols_modules_shell(
            page_kind="shop",
            page_title="Protocols4People Shop Modules",
            base_path="../../",
            payload=catalog_payload,
        ),
    )


def build() -> None:
    site_data = load_site_data()
    screenshot_pack = load_screenshot_pack()
    copy_screenshot_assets(screenshot_pack)
    modules = load_modules()
    providers = load_providers(modules)
    modules_by_id = {entry["module_id"]: entry for entry in modules}
    write_text(
        PUBLIC_ROOT / "modules.json",
        json.dumps(module_catalog_payload(site_data, modules), indent=2) + "\n",
    )
    write_text(
        PUBLIC_ROOT / "providers.json",
        json.dumps(provider_catalog_payload(site_data, providers), indent=2) + "\n",
    )
    write_text(
        PUBLIC_ROOT / "index.html",
        homepage_html(site_data, modules, providers, locale="en", screenshot_pack=screenshot_pack),
    )
    for locale in ("da", "sv", "tr", "ar", "ku"):
        write_text(
            PUBLIC_ROOT / f"{locale}.html",
            homepage_html(site_data, modules, providers, locale=locale, screenshot_pack=screenshot_pack),
        )
    write_text(PUBLIC_ROOT / "modules/index.html", modules_html(site_data, modules, providers, locale="en"))
    for locale in ("da", "sv", "tr", "ar", "ku"):
        write_text(PUBLIC_ROOT / "modules" / f"{locale}.html", modules_html(site_data, modules, providers, locale=locale))
    write_text(PUBLIC_ROOT / "providers/index.html", providers_html(site_data, providers, modules_by_id, locale="en"))
    for locale in ("da", "sv", "tr", "ar", "ku"):
        write_text(
            PUBLIC_ROOT / "providers" / f"{locale}.html",
            providers_html(site_data, providers, modules_by_id, locale=locale),
        )
    for entry in modules:
        write_text(module_page_path(entry["module_id"], locale="en"), module_page_html(site_data, entry, modules_by_id, locale="en"))
        for locale in ("da", "sv", "tr", "ar", "ku"):
            write_text(
                module_page_path(entry["module_id"], locale=locale),
                module_page_html(site_data, entry, modules_by_id, locale=locale),
            )
    for entry in providers:
        write_text(
            provider_page_path(entry["provider_id"], locale="en"),
            provider_page_html(site_data, entry, modules_by_id, locale="en"),
        )
        for locale in ("da", "sv", "tr", "ar", "ku"):
            write_text(
                provider_page_path(entry["provider_id"], locale=locale),
                provider_page_html(site_data, entry, modules_by_id, locale=locale),
            )
    write_text(
        PRESS_ROOT / "index.html",
        press_kit_html(site_data, modules, providers, locale="da", screenshot_pack=screenshot_pack),
    )
    for locale in ("en", "sv", "tr", "ar", "ku"):
        write_text(
            PRESS_ROOT / f"{locale}.html",
            press_kit_html(site_data, modules, providers, locale=locale, screenshot_pack=screenshot_pack),
        )
    write_protocols_module_catalog(screenshot_pack=screenshot_pack)


if __name__ == "__main__":
    build()
