"""Every visible GUI string, in English and Italian."""

from __future__ import annotations

LANGUAGES = ("en", "it")

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "SmartSwitch Backup Analyzer",
        "lang_button": "Italiano",
        "back": "< Back",
        "next": "Next >",
        "cancel": "Close",
        "finish": "Finish",
        "p1_title": "Choose the backup",
        "p1_subtitle": "Pick a Smart Switch backup and the folder where the recovered data will be saved.",
        "p1_found": "Backups found on this PC:",
        "p1_none": "No backup found in the usual Smart Switch folders. Use \u201cBrowse\u2026\u201d.",
        "p1_browse_backup": "Browse\u2026",
        "p1_backup_line": "{name} ({model}) \u2014 {date} \u2014 {size}",
        "p1_scan_folder": "Already decrypted: {path}",
        "p1_save_to": "Save to:",
        "p1_browse_dest": "Browse\u2026",
        "p1_pick_backup": "Choose a backup folder or an already decrypted folder",
        "p1_pick_dest": "Choose where to save the recovered data",
        "p1_not_backup": "This folder is not a Smart Switch backup (it has no backupHistoryInfo.xml).",
        "p1_dest_inside": "Choose a folder outside the backup: the backup itself is never changed.",
        "p1_low_space": "Only {free} are free on that disk; about {needed} are needed. Continue anyway?",
        "p1_reuse": "This folder already holds a decrypted copy of a backup. Use it? (No = decrypt again)",
        "p2_title": "Decrypting the backup",
        "p2_subtitle": "This can take several minutes for a large backup.",
        "p2_progress": "Category {done} of {total}",
        "p2_stop": "Stop",
        "p2_confirm_stop": "Stop decrypting? You can start again later.",
        "p2_done": "Decryption finished.",
        "p2_cancelled": "Stopped. Go back and press Next to start again.",
        "p2_failed": "Decryption failed.",
        "p3_title": "What to recover",
        "p3_subtitle": "Only the data found in this backup is listed.",
        "p3_count": " ({n})",
        "p3_wifi_warning": " \u2014 the page contains the Wi-Fi passwords",
        "p3_nothing": "Nothing that can be recovered was found in this backup.",
        "p3_files": "Photos, videos and documents:",
        "p3_files_keep": "Keep them separate, as the backup stores them",
        "p3_files_copy": "Merge them into one phone folder tree (copy)",
        "p3_files_move": "Merge them into one phone folder tree (move)",
        "p3_files_move_help": "Moving is instant on the same disk and needs no extra space; the category folders are emptied.",
        "p4_title": "Recovering",
        "p4_subtitle": "Each kind of data is saved on its own: an error in one does not stop the others.",
        "p4_stop": "Stop",
        "p4_confirm_stop": "Stop after the current file? What is done stays.",
        "p4_row_waiting": "\u2022 {name}",
        "p4_row_running": "\u25b6 {name}",
        "p4_row_ok": "\u2714 {name}",
        "p4_row_error": "\u2716 {name}",
        "p4_done": "Finished.",
        "p4_cancelled": "Stopped.",
        "p5_title": "Summary",
        "p5_subtitle": "Open the recovered data, or read how to put it on a new phone.",
        "p5_open": "Open",
        "p5_open_results": "Open the results folder",
        "p5_guide_button": "How to put this on a new phone",
        "p5_guide_text": (
            "Contacts: copy contacts.vcf to the phone and open it, or import it in Google Contacts.\n"
            "SMS and calls: install \u201cSMS Backup & Restore\u201d, copy sms.xml and calls.xml to the phone and restore them.\n"
            "Wi-Fi: open wifi.html, \u201cShow QR code\u201d, and scan it from Settings \u2192 Wi-Fi.\n"
            "Bookmarks: import browser\\bookmarks.html in Chrome or Firefox.\n"
            "Photos, videos, documents and notes: copy their folders to the phone."
        ),
        "export_contacts": "Contacts",
        "export_messages": "SMS messages",
        "export_calls": "Call log",
        "export_wifi": "Wi-Fi networks",
        "export_blocked-numbers": "Blocked numbers",
        "export_browser": "Samsung Internet bookmarks and history",
        "export_clipboard": "Keyboard clipboard",
        "export_clock": "Alarms, timers and world clock",
        "export_notes": "Samsung Notes",
        "export_apps": "Installed apps",
        "export_files": "Photos, videos and documents",
        "sum_contacts": "{n} contacts",
        "sum_messages": "{n} messages",
        "sum_calls": "{n} calls",
        "sum_wifi": "{n} networks, {p} with a password",
        "sum_blocked": "{n} numbers",
        "sum_browser": "{b} bookmarks, {h} visited sites",
        "sum_clipboard": "{t} texts, {i} images",
        "sum_clock": "{a} alarms, {t} timers, {c} cities",
        "sum_notes": "{n} notes, {a} attachments",
        "sum_apps": "{n} apps",
        "sum_files": "{n} files, {m} duplicates merged",
        "sum_files_kept": "Left in their category folders",
        "sum_check": "{n} to check",
        "sum_error": "Failed: {error}",
        "error_title": "Unexpected error",
        "error_text": "Something went wrong. The details below were also saved in {log}.",
    },
    "it": {
        "app_title": "SmartSwitch Backup Analyzer",
        "lang_button": "English",
        "back": "< Indietro",
        "next": "Avanti >",
        "cancel": "Chiudi",
        "finish": "Fine",
        "p1_title": "Scegli il backup",
        "p1_subtitle": "Scegli un backup di Smart Switch e la cartella dove salvare i dati recuperati.",
        "p1_found": "Backup trovati su questo PC:",
        "p1_none": "Nessun backup trovato nelle cartelle abituali di Smart Switch. Usa \u201cSfoglia\u2026\u201d.",
        "p1_browse_backup": "Sfoglia\u2026",
        "p1_backup_line": "{name} ({model}) \u2014 {date} \u2014 {size}",
        "p1_scan_folder": "Gi\u00e0 decifrato: {path}",
        "p1_save_to": "Salva in:",
        "p1_browse_dest": "Sfoglia\u2026",
        "p1_pick_backup": "Scegli la cartella di un backup o una cartella gi\u00e0 decifrata",
        "p1_pick_dest": "Scegli dove salvare i dati recuperati",
        "p1_not_backup": "Questa cartella non \u00e8 un backup di Smart Switch (manca backupHistoryInfo.xml).",
        "p1_dest_inside": "Scegli una cartella fuori dal backup: il backup non viene mai modificato.",
        "p1_low_space": "Su quel disco sono liberi solo {free}; ne servono circa {needed}. Continuare comunque?",
        "p1_reuse": "Questa cartella contiene gi\u00e0 una copia decifrata di un backup. Usarla? (No = decifra di nuovo)",
        "p2_title": "Decifratura del backup",
        "p2_subtitle": "Per un backup grande pu\u00f2 richiedere parecchi minuti.",
        "p2_progress": "Categoria {done} di {total}",
        "p2_stop": "Interrompi",
        "p2_confirm_stop": "Interrompere la decifratura? Potrai ricominciare in seguito.",
        "p2_done": "Decifratura completata.",
        "p2_cancelled": "Interrotta. Torna indietro e premi Avanti per ricominciare.",
        "p2_failed": "Decifratura non riuscita.",
        "p3_title": "Cosa recuperare",
        "p3_subtitle": "Sono elencati solo i dati presenti in questo backup.",
        "p3_count": " ({n})",
        "p3_wifi_warning": " \u2014 la pagina contiene le password del Wi-Fi",
        "p3_nothing": "In questo backup non c'\u00e8 nulla che si possa recuperare.",
        "p3_files": "Foto, video e documenti:",
        "p3_files_keep": "Lasciali divisi, come li salva il backup",
        "p3_files_copy": "Uniscili in un unico albero di cartelle del telefono (copia)",
        "p3_files_move": "Uniscili in un unico albero di cartelle del telefono (sposta)",
        "p3_files_move_help": "Spostare \u00e8 istantaneo sullo stesso disco e non occupa spazio; le cartelle delle categorie vengono svuotate.",
        "p4_title": "Recupero in corso",
        "p4_subtitle": "Ogni tipo di dato viene salvato a s\u00e9: un errore in uno non ferma gli altri.",
        "p4_stop": "Interrompi",
        "p4_confirm_stop": "Interrompere dopo il file in corso? Quello gi\u00e0 fatto resta.",
        "p4_row_waiting": "\u2022 {name}",
        "p4_row_running": "\u25b6 {name}",
        "p4_row_ok": "\u2714 {name}",
        "p4_row_error": "\u2716 {name}",
        "p4_done": "Finito.",
        "p4_cancelled": "Interrotto.",
        "p5_title": "Riepilogo",
        "p5_subtitle": "Apri i dati recuperati, oppure leggi come rimetterli su un telefono nuovo.",
        "p5_open": "Apri",
        "p5_open_results": "Apri la cartella dei risultati",
        "p5_guide_button": "Come rimetterli su un telefono nuovo",
        "p5_guide_text": (
            "Contatti: copia contacts.vcf sul telefono e aprilo, oppure importalo in Contatti Google.\n"
            "SMS e chiamate: installa \u201cSMS Backup & Restore\u201d, copia sms.xml e calls.xml sul telefono e ripristinali.\n"
            "Wi-Fi: apri wifi.html, \u201cShow QR code\u201d, e inquadralo da Impostazioni \u2192 Wi-Fi.\n"
            "Segnalibri: importa browser\\bookmarks.html in Chrome o Firefox.\n"
            "Foto, video, documenti e note: copia le loro cartelle sul telefono."
        ),
        "export_contacts": "Contatti",
        "export_messages": "SMS",
        "export_calls": "Registro chiamate",
        "export_wifi": "Reti Wi-Fi",
        "export_blocked-numbers": "Numeri bloccati",
        "export_browser": "Segnalibri e cronologia di Samsung Internet",
        "export_clipboard": "Appunti della tastiera",
        "export_clock": "Sveglie, timer e orologio mondiale",
        "export_notes": "Samsung Notes",
        "export_apps": "App installate",
        "export_files": "Foto, video e documenti",
        "sum_contacts": "{n} contatti",
        "sum_messages": "{n} messaggi",
        "sum_calls": "{n} chiamate",
        "sum_wifi": "{n} reti, {p} con password",
        "sum_blocked": "{n} numeri",
        "sum_browser": "{b} segnalibri, {h} siti visitati",
        "sum_clipboard": "{t} testi, {i} immagini",
        "sum_clock": "{a} sveglie, {t} timer, {c} citt\u00e0",
        "sum_notes": "{n} note, {a} allegati",
        "sum_apps": "{n} app",
        "sum_files": "{n} file, {m} doppioni uniti",
        "sum_files_kept": "Lasciati nelle cartelle delle categorie",
        "sum_check": "{n} da controllare",
        "sum_error": "Non riuscito: {error}",
        "error_title": "Errore imprevisto",
        "error_text": "Qualcosa \u00e8 andato storto. I dettagli qui sotto sono stati salvati anche in {log}.",
    },
}

_current = "en"


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in LANGUAGES else "en"


def language() -> str:
    return _current


def system_language(locale_name: str) -> str:
    return "it" if locale_name.lower().startswith("it") else "en"


def tr(key: str, **fmt) -> str:
    return STRINGS[_current][key].format(**fmt)
